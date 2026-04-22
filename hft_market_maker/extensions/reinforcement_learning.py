"""
Reinforcement Learning Extension
----------------------------------

Replaces (or augments) the A-S quote decision with a learned policy.

Two approaches implemented:

1. TabularQLearning
   - Discrete state space (inventory bucket × vol bucket × OFI bucket)
   - Actions: adjust half-spread by one of several discrete offsets
   - Good for thesis baseline / interpretability

2. DQNMarketMaker
   - Deep Q-Network using a small MLP
   - Continuous state features; discrete action set
   - More expressive, suitable for complex regimes
   - Uses experience replay and target network

State features (both approaches):
  - Inventory (normalised, discretised for tabular)
  - Volatility (normalised, discretised for tabular)
  - Order flow imbalance
  - Time since last fill
  - Spread vs historical average
  - Regime signal (Hurst exponent)

Actions:
  - Discrete spread adjustments: [0.25x, 0.5x, 1x, 1.5x, 2x, 3x] × base spread
  - Optionally: also adjust reservation price offset (lean bid/ask)

Reward:
  - PnL per step + inventory penalty
  - r_t = delta_PnL - lambda * q_t^2

Reference: Spooner et al. (2018) "Market Making via Reinforcement Learning"
"""

from __future__ import annotations
from dataclasses import dataclass
from collections import deque
from typing import Optional, List, Tuple
import numpy as np
import random

from ..strategies.avellaneda_stoikov import AvellanedaStoikov, QuoteDecision
from ..core.market_state import MicrostructureStats


# ===========================================================================
# Shared helpers
# ===========================================================================

SPREAD_MULTIPLIERS = np.array([0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0])
SKEW_OFFSETS = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])  # in bps, applied to reservation price

# Full action space: (spread_mult_idx, skew_idx)
ACTIONS = [(sm, sk) for sm in range(len(SPREAD_MULTIPLIERS))
                     for sk in range(len(SKEW_OFFSETS))]
N_ACTIONS = len(ACTIONS)


def encode_state_continuous(
    stats: MicrostructureStats,
    inventory: float,
    max_inventory: float,
    time_since_fill: float,
    hurst: float = 0.5,
) -> np.ndarray:
    """
    Returns a normalised state vector for the RL agent.
    """
    return np.array([
        np.clip(inventory / max_inventory, -1, 1),       # normalised inventory
        np.clip(stats.sigma / (stats.sigma + 1e-6), 0, 1),  # vol (normalised by itself)
        stats.ofi,                                           # order flow imbalance [-1,1]
        np.clip(time_since_fill / 60.0, 0, 1),              # time since last fill (capped at 1min)
        np.clip(hurst, 0, 1),                               # hurst exponent
        np.clip(stats.spread / (stats.mid_price + 1e-6) * 1e4, 0, 1),  # spread in bps, normalised
    ], dtype=np.float32)


# ===========================================================================
# 1. Tabular Q-Learning
# ===========================================================================

class TabularQLearning:
    """
    Tabular Q-learning with a discrete state space.

    State bins:
      inventory:  [-max, -0.5*max, 0, 0.5*max, max] → 4 buckets
      vol_zscore: very low / low / normal / high / very high → 5 buckets
      ofi:        sell-heavy / balanced / buy-heavy → 3 buckets

    Total: 4 × 5 × 3 = 60 states
    Actions: N_ACTIONS spread/skew combinations
    """

    def __init__(
        self,
        base_strategy: AvellanedaStoikov,
        learning_rate: float = 0.1,
        discount: float = 0.99,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
        epsilon_decay: float = 0.9999,
        inventory_penalty: float = 0.01,
    ):
        self.base = base_strategy
        self.lr = learning_rate
        self.gamma = discount
        self.epsilon = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay
        self.inventory_penalty = inventory_penalty

        # Q-table: state → action values
        n_inv_bins = 4
        n_vol_bins = 5
        n_ofi_bins = 3
        self.Q = np.zeros((n_inv_bins, n_vol_bins, n_ofi_bins, N_ACTIONS))

        self._vol_history: deque[float] = deque(maxlen=50)
        self._prev_state: Optional[tuple] = None
        self._prev_action: Optional[int] = None
        self._prev_pnl: float = 0.0
        self._step: int = 0

    def _discretise_state(self, stats: MicrostructureStats,
                          inventory: float) -> tuple:
        self._vol_history.append(stats.sigma)
        mean_vol = np.mean(self._vol_history) if len(self._vol_history) > 5 else stats.sigma
        std_vol = np.std(self._vol_history) + 1e-10 if len(self._vol_history) > 5 else 1e-10
        vol_z = (stats.sigma - mean_vol) / std_vol

        inv_ratio = inventory / max(self.base.max_inventory, 1e-6)
        inv_bin = int(np.digitize(inv_ratio, [-0.5, 0.0, 0.5])) % 4
        vol_bin = int(np.digitize(vol_z, [-1.5, -0.5, 0.5, 1.5])) % 5
        ofi_bin = int(np.digitize(stats.ofi, [-0.2, 0.2])) % 3

        return (inv_bin, vol_bin, ofi_bin)

    def select_action(self, state: tuple) -> int:
        self._step += 1
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)
        if np.random.random() < self.epsilon:
            return np.random.randint(N_ACTIONS)
        return int(np.argmax(self.Q[state]))

    def update(self, state: tuple, action: int, reward: float, next_state: tuple) -> None:
        current_q = self.Q[state][action]
        best_next = np.max(self.Q[next_state])
        target = reward + self.gamma * best_next
        self.Q[state][action] += self.lr * (target - current_q)

    def compute_quotes(
        self,
        stats: MicrostructureStats,
        inventory: float,
        timestamp: float,
        total_pnl: float = 0.0,
    ) -> QuoteDecision:
        # Get base A-S quote
        base_decision = self.base.compute_quotes(stats, inventory, timestamp)
        state = self._discretise_state(stats, inventory)

        # Compute reward for previous step
        if self._prev_state is not None:
            reward = (total_pnl - self._prev_pnl) - self.inventory_penalty * inventory ** 2
            self.update(self._prev_state, self._prev_action, reward, state)

        # Select action
        action_idx = self.select_action(state)
        spread_mult, skew_bps = ACTIONS[action_idx]

        spread_multiplier = SPREAD_MULTIPLIERS[spread_mult]
        skew_offset = SKEW_OFFSETS[skew_bps] * stats.mid_price / 10_000

        half_spread = base_decision.optimal_spread / 2.0 * spread_multiplier
        reservation = base_decision.reservation_price + skew_offset

        bid = self.base._round_price(reservation - half_spread, "bid")
        ask = self.base._round_price(reservation + half_spread, "ask")

        self._prev_state = state
        self._prev_action = action_idx
        self._prev_pnl = total_pnl

        return QuoteDecision(
            bid_price=bid,
            ask_price=ask,
            reservation_price=reservation,
            optimal_spread=half_spread * 2,
            bid_size=base_decision.bid_size,
            ask_size=base_decision.ask_size,
        )


# ===========================================================================
# 2. Deep Q-Network (DQN)
# ===========================================================================

@dataclass
class Transition:
    state: np.ndarray
    action: int
    reward: float
    next_state: np.ndarray
    done: bool


class ReplayBuffer:
    def __init__(self, capacity: int = 10_000):
        self.buffer: deque[Transition] = deque(maxlen=capacity)

    def push(self, t: Transition) -> None:
        self.buffer.append(t)

    def sample(self, batch_size: int) -> List[Transition]:
        return random.sample(self.buffer, batch_size)

    def __len__(self) -> int:
        return len(self.buffer)


class MLP:
    """
    Minimal NumPy MLP (no deep learning framework required).
    3 layers: input → 64 → 64 → N_ACTIONS
    Uses ReLU activations, He initialisation.
    """

    def __init__(self, input_dim: int, hidden_dim: int, output_dim: int):
        self.layers = [
            self._init_layer(input_dim, hidden_dim),
            self._init_layer(hidden_dim, hidden_dim),
            self._init_layer(hidden_dim, output_dim),
        ]

    def _init_layer(self, fan_in: int, fan_out: int) -> dict:
        W = np.random.randn(fan_in, fan_out) * np.sqrt(2.0 / fan_in)
        b = np.zeros(fan_out)
        return {"W": W, "b": b}

    def forward(self, x: np.ndarray) -> np.ndarray:
        h = x
        for i, layer in enumerate(self.layers):
            h = h @ layer["W"] + layer["b"]
            if i < len(self.layers) - 1:
                h = np.maximum(0, h)  # ReLU
        return h

    def copy_weights_from(self, other: "MLP") -> None:
        for dst, src in zip(self.layers, other.layers):
            dst["W"] = src["W"].copy()
            dst["b"] = src["b"].copy()


class DQNMarketMaker:
    """
    DQN-based market maker.

    Uses:
    - Experience replay (ReplayBuffer)
    - Target network (updated every `target_update` steps)
    - Epsilon-greedy exploration

    Note: for thesis use, you may want to swap the numpy MLP for
    a PyTorch / TensorFlow model for GPU acceleration and easier
    backpropagation. The interface stays identical.
    """

    STATE_DIM = 6  # matches encode_state_continuous

    def __init__(
        self,
        base_strategy: AvellanedaStoikov,
        hidden_dim: int = 64,
        lr: float = 1e-3,
        discount: float = 0.99,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
        epsilon_decay: float = 0.9998,
        batch_size: int = 64,
        target_update: int = 100,
        replay_capacity: int = 10_000,
        inventory_penalty: float = 0.1,
    ):
        self.base = base_strategy
        self.lr = lr
        self.discount = discount
        self.epsilon = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay
        self.batch_size = batch_size
        self.target_update = target_update
        self.inventory_penalty = inventory_penalty

        self.online_net = MLP(self.STATE_DIM, hidden_dim, N_ACTIONS)
        self.target_net = MLP(self.STATE_DIM, hidden_dim, N_ACTIONS)
        self.target_net.copy_weights_from(self.online_net)

        self.replay = ReplayBuffer(replay_capacity)

        self._step = 0
        self._prev_state: Optional[np.ndarray] = None
        self._prev_action: Optional[int] = None
        self._prev_pnl: float = 0.0
        self._time_since_fill: float = 0.0
        self._last_fill_time: float = 0.0
        self._hurst: float = 0.5

    def on_fill(self, timestamp: float) -> None:
        self._time_since_fill = 0.0
        self._last_fill_time = timestamp

    def set_hurst(self, hurst: float) -> None:
        self._hurst = hurst

    def _get_state(self, stats: MicrostructureStats, inventory: float,
                   timestamp: float) -> np.ndarray:
        self._time_since_fill = timestamp - self._last_fill_time
        return encode_state_continuous(
            stats, inventory, self.base.max_inventory,
            self._time_since_fill, self._hurst,
        )

    def _select_action(self, state: np.ndarray) -> int:
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)
        if np.random.random() < self.epsilon:
            return np.random.randint(N_ACTIONS)
        q_values = self.online_net.forward(state)
        return int(np.argmax(q_values))

    def _train_step(self) -> Optional[float]:
        if len(self.replay) < self.batch_size:
            return None

        batch = self.replay.sample(self.batch_size)
        states = np.vstack([t.state for t in batch])
        actions = np.array([t.action for t in batch])
        rewards = np.array([t.reward for t in batch])
        next_states = np.vstack([t.next_state for t in batch])
        dones = np.array([t.done for t in batch], dtype=float)

        # Target Q values
        online_next = self.online_net.forward(next_states)
        best_actions = np.argmax(online_next, axis=1)  # Double DQN
        target_next = self.target_net.forward(next_states)
        targets = rewards + self.discount * (1 - dones) * target_next[
            np.arange(self.batch_size), best_actions
        ]

        # Current Q values and loss
        current_q = self.online_net.forward(states)
        errors = targets - current_q[np.arange(self.batch_size), actions]
        loss = np.mean(errors ** 2)

        # Manual gradient step (simplified — use PyTorch for real training)
        # This is a placeholder gradient update for demonstration purposes
        # In practice, replace with: loss.backward(); optimizer.step()
        grad_scale = self.lr * 2 * errors / self.batch_size
        for i, (s, a, g) in enumerate(zip(states, actions, grad_scale)):
            # Update only the last layer's contribution (simplified)
            self.online_net.layers[-1]["b"][a] += g
            self.online_net.layers[-1]["W"][:, a] += g * self.online_net.forward(
                s.reshape(1, -1)
            ).flatten()[a] * 0.01  # approximation

        return float(loss)

    def compute_quotes(
        self,
        stats: MicrostructureStats,
        inventory: float,
        timestamp: float,
        total_pnl: float = 0.0,
    ) -> Tuple[QuoteDecision, dict]:
        self._step += 1
        state = self._get_state(stats, inventory, timestamp)
        base_decision = self.base.compute_quotes(stats, inventory, timestamp)

        # Store transition from previous step
        if self._prev_state is not None:
            reward = (total_pnl - self._prev_pnl) - self.inventory_penalty * inventory ** 2
            transition = Transition(
                state=self._prev_state,
                action=self._prev_action,
                reward=reward,
                next_state=state,
                done=False,
            )
            self.replay.push(transition)
            loss = self._train_step()
        else:
            loss = None

        # Update target network
        if self._step % self.target_update == 0:
            self.target_net.copy_weights_from(self.online_net)

        # Select action
        action_idx = self._select_action(state)
        spread_mult_idx, skew_idx = ACTIONS[action_idx]
        spread_multiplier = SPREAD_MULTIPLIERS[spread_mult_idx]
        skew_bps = SKEW_OFFSETS[skew_idx]

        half_spread = base_decision.optimal_spread / 2.0 * spread_multiplier
        skew_offset = skew_bps * stats.mid_price / 10_000
        reservation = base_decision.reservation_price + skew_offset

        bid = self.base._round_price(reservation - half_spread, "bid")
        ask = self.base._round_price(reservation + half_spread, "ask")

        self._prev_state = state
        self._prev_action = action_idx
        self._prev_pnl = total_pnl

        decision = QuoteDecision(
            bid_price=bid,
            ask_price=ask,
            reservation_price=reservation,
            optimal_spread=half_spread * 2,
            bid_size=base_decision.bid_size,
            ask_size=base_decision.ask_size,
        )

        info = {
            "epsilon": self.epsilon,
            "action_idx": action_idx,
            "spread_multiplier": float(spread_multiplier),
            "skew_bps": float(skew_bps),
            "loss": loss,
            "replay_size": len(self.replay),
        }

        return decision, info
