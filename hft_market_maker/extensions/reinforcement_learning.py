"""
Reinforcement Learning Extension
---------------------------------
Replaces the A-S/GLFT quote decision with a learned policy.

Two approaches:
  1. TabularQLearning  — discrete state+action, interpretable baseline
  2. DQNMarketMaker    — PyTorch DQN, continuous state, experience replay

Both share the same action space and state encoder.

Action space (N_ACTIONS = 19)
-------------------------------
Each action specifies three things jointly:
  - bid_ticks  : half-spread on the bid side  (ticks from mid)
  - ask_ticks  : half-spread on the ask side  (ticks from mid)
  - hold_sec   : how long to hold this order before recomputing

Expressing spreads in absolute ticks (not multipliers) makes the action
table directly interpretable against the asset's market structure.
For LINK the natural spread is 5 ticks each side; for BTC the default
tick_size is 0.01 and natural spread ~1-2 ticks.

The "inside/at/outside" labels refer to LINK's natural spread at 5 ticks.
For BTC the same action IDs correspond to different fill-curve regimes.

  ID  Name                bid  ask  hold   Fill regime (LINK)
  --  ----                ---  ---  ----   ------------------
   0  halt                 —    —   —      no quotes
   1  inside_sym_fast      3    3   0.25s  inside market, fast repost
   2  inside_sym           3    3   0.5s   inside market, normal
   3  inside_lean_bid      2    4   0.25s  sell long fast
   4  inside_lean_ask      4    2   0.25s  buy short fast
   5  near_sym             4    4   0.5s   one tick inside market
   6  near_lean_bid        3    5   0.5s   sell, one tick inside
   7  near_lean_ask        5    3   0.5s   buy, one tick inside
   8  at_sym               5    5   0.5s   at natural bid/ask
   9  at_lean_bid          4    6   0.5s   sell, at market
  10  at_lean_ask          6    4   0.5s   buy, at market
  11  at_sym_patient       5    5   2.0s   at market, patient (fewer cancels)
  12  outside_sym          6    6   1.0s   one tick outside market
  13  outside_lean_bid     5    7   1.0s   sell, just outside market
  14  outside_lean_ask     7    5   1.0s   buy, just outside market
  15  outside_patient      6    6   2.0s   price-dip fills only
  16  wide_sym             8    8   2.0s   very selective, wide
  17  wide_lean_bid        7    9   2.0s   sell, very wide
  18  wide_lean_ask        9    7   2.0s   buy, very wide

The hold_sec dimension lets the agent trade off responsiveness vs.
fill probability. Short hold = more cancels, faster quote updates when
price moves. Long hold = cheaper (fewer order events), but orders
stale during momentum moves.

State features (6-dim, all normalised to [-1,1] or [0,1])
----------------------------------------------------------
  0  inv_ratio      inventory / max_inventory                  [-1, 1]
  1  vol_ratio      sigma_t / rolling_mean_sigma (÷4, clip)    [0, 1]
  2  momentum       stats.momentum                             [-1, 1]
  3  ofi            stats.ofi                                  [-1, 1]
  4  spike_ratio    tps_short / (tps_long+ε) ÷5, clip         [0, 1]
  5  pnl_draw       daily_pnl / daily_loss_limit (clip -2→0)÷2 [-1, 0]

Reward
------
  r_t = ΔPnL_t  −  λ_inv × |q_t| × σ_t / max_inventory

where σ_t is the rolling per-step volatility. The inventory penalty
scales with vol so that the agent learns to be flatter during high-vol.

Reference: Spooner et al. (2018) "Market Making via Reinforcement Learning"
"""

from __future__ import annotations

import numpy as np
import random
from collections import deque
from dataclasses import dataclass
from typing import Optional, List, Tuple

from ..strategies.avellaneda_stoikov import QuoteDecision
from ..core.market_state import MicrostructureStats


# ---------------------------------------------------------------------------
# Action definitions
# ---------------------------------------------------------------------------

# Each entry: (bid_half_ticks, ask_half_ticks, hold_sec)
# bid_half_ticks = 0 means halt (no quotes on either side)
ACTION_PARAMS: List[Tuple[int, int, float]] = [
    (0,  0,  0.0 ),   #  0: halt
    (3,  3,  0.25),   #  1: inside_sym_fast
    (3,  3,  0.50),   #  2: inside_sym
    (2,  4,  0.25),   #  3: inside_lean_bid   (tighter bid → sell long fast)
    (4,  2,  0.25),   #  4: inside_lean_ask   (tighter ask → buy short fast)
    (4,  4,  0.50),   #  5: near_sym
    (3,  5,  0.50),   #  6: near_lean_bid
    (5,  3,  0.50),   #  7: near_lean_ask
    (5,  5,  0.50),   #  8: at_sym
    (4,  6,  0.50),   #  9: at_lean_bid
    (6,  4,  0.50),   # 10: at_lean_ask
    (5,  5,  2.00),   # 11: at_sym_patient
    (6,  6,  1.00),   # 12: outside_sym
    (5,  7,  1.00),   # 13: outside_lean_bid
    (7,  5,  1.00),   # 14: outside_lean_ask
    (6,  6,  2.00),   # 15: outside_patient
    (8,  8,  2.00),   # 16: wide_sym
    (7,  9,  2.00),   # 17: wide_lean_bid
    (9,  7,  2.00),   # 18: wide_lean_ask
]
N_ACTIONS = len(ACTION_PARAMS)

ACTION_NAMES = [
    "halt",
    "inside_sym_fast", "inside_sym",
    "inside_lean_bid", "inside_lean_ask",
    "near_sym", "near_lean_bid", "near_lean_ask",
    "at_sym", "at_lean_bid", "at_lean_ask", "at_sym_patient",
    "outside_sym", "outside_lean_bid", "outside_lean_ask", "outside_patient",
    "wide_sym", "wide_lean_bid", "wide_lean_ask",
]

# Default hold time if action is halt (how long to stay quiet)
HALT_HOLD_SEC = 0.5


def action_hold(action: int) -> float:
    """Return the hold duration in seconds for a given action index."""
    if action == 0:
        return HALT_HOLD_SEC
    return ACTION_PARAMS[action][2]


# ---------------------------------------------------------------------------
# State encoder (shared by all agents)
# ---------------------------------------------------------------------------

STATE_DIM = 6


def encode_state(
    stats: MicrostructureStats,
    inventory: float,
    max_inventory: float,
    daily_pnl: float,
    daily_loss_limit: float,
    vol_history: deque,
) -> np.ndarray:
    """
    Encode market observables into a normalised 6-dim state vector.
    """
    inv_ratio = np.clip(inventory / (max_inventory + 1e-9), -1.0, 1.0)

    if len(vol_history) >= 5:
        vol_mean  = float(np.mean(vol_history))
        vol_ratio = np.clip(stats.sigma / (vol_mean + 1e-10) / 4.0, 0.0, 1.0)
    else:
        vol_ratio = 0.25

    momentum = np.clip(stats.momentum, -1.0, 1.0)
    ofi      = np.clip(stats.ofi,      -1.0, 1.0)

    tps_long    = max(stats.trades_per_sec, 1e-6)
    spike_ratio = np.clip(stats.trades_per_sec_short / tps_long / 5.0, 0.0, 1.0)

    if daily_loss_limit > 0:
        pnl_draw = np.clip(daily_pnl / daily_loss_limit, -2.0, 0.0) / 2.0
    else:
        pnl_draw = 0.0

    return np.array([inv_ratio, vol_ratio, momentum, ofi, spike_ratio, pnl_draw],
                    dtype=np.float32)


# ---------------------------------------------------------------------------
# Quote builder: action → QuoteDecision
# ---------------------------------------------------------------------------

def build_quote(
    action: int,
    stats: MicrostructureStats,
    tick_size: float,
    order_size: float,
    max_inventory: float,
    inventory: float,
) -> QuoteDecision:
    """
    Build a QuoteDecision from the action index.

    bid/ask prices are mid ± (N ticks × tick_size), rounded to tick.
    Returns a halt decision (should_quote_bid/ask = False) for action 0.
    """
    bid_ticks, ask_ticks, _ = ACTION_PARAMS[action]
    mid = stats.mid_price

    EPS = 1e-9  # guard against floating-point under-floor
    def _floor(p: float) -> float:
        return np.floor(p / tick_size + EPS) * tick_size if tick_size > 0 else p

    def _ceil(p: float) -> float:
        return np.ceil(p / tick_size - EPS) * tick_size if tick_size > 0 else p

    if action == 0 or mid <= 0:
        # Halt — prices are set but both sides suppressed
        half = tick_size * 5  # placeholder; won't be used
        d = QuoteDecision(
            bid_price=_floor(mid - half),
            ask_price=_ceil(mid + half),
            reservation_price=mid,
            optimal_spread=2 * half,
            bid_size=order_size,
            ask_size=order_size,
        )
        d.should_quote_bid = False
        d.should_quote_ask = False
        return d

    bid_price = _floor(mid - bid_ticks * tick_size)
    ask_price = _ceil(mid  + ask_ticks * tick_size)
    if ask_price <= bid_price:
        ask_price = bid_price + tick_size

    d = QuoteDecision(
        bid_price=bid_price,
        ask_price=ask_price,
        reservation_price=mid,
        optimal_spread=(bid_ticks + ask_ticks) * tick_size,
        bid_size=order_size,
        ask_size=order_size,
    )
    d.should_quote_bid = (inventory < max_inventory)
    d.should_quote_ask = (inventory > -max_inventory)
    return d


# ---------------------------------------------------------------------------
# 1. Tabular Q-Learning
# ---------------------------------------------------------------------------

# Discrete bins.  The state encoder maps features to [0,1] or [-1,1];
# digitize thresholds are on those normalised values.
INV_BINS   = [-0.6, -0.2, 0.2, 0.6]   # 5 inventory buckets
VOL_BINS   = [0.2, 0.5, 0.8]          # 4 vol buckets
MOM_BINS   = [-0.15, 0.15]            # 3 momentum buckets
SPIKE_BINS = [0.4]                     # 2 spike buckets
N_STATES   = 5 * 4 * 3 * 2            # = 120


class TabularQLearning:
    """
    Tabular Q-learning market maker.

    State: (inv_bin × vol_bin × momentum_bin × spike_bin) = 120 states
    Action: N_ACTIONS = 19 (spread × lean × lifetime combinations)
    Reward: ΔPnL − λ_inv × |inventory| × vol / max_inventory
    Hold time: taken from the action's ACTION_PARAMS[action][2].

    Training is online — every call to compute_quotes is a Q-update step.
    """

    def __init__(
        self,
        tick_size: float = 0.001,
        order_size: float = 5.0,
        max_inventory: float = 100.0,
        daily_loss_limit: float = 30.0,
        learning_rate: float = 0.05,
        discount: float = 0.99,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
        epsilon_decay: float = 0.99995,
        inventory_penalty: float = 0.05,
    ):
        self.tick_size       = tick_size
        self.order_size      = order_size
        self.max_inventory   = max_inventory
        self.daily_loss_limit = daily_loss_limit
        self.lr              = learning_rate
        self.discount        = discount
        self.epsilon         = epsilon_start
        self.epsilon_end     = epsilon_end
        self.epsilon_decay   = epsilon_decay
        self.inv_penalty     = inventory_penalty

        self.Q = np.zeros((N_STATES, N_ACTIONS), dtype=np.float64)

        self._vol_history: deque = deque(maxlen=120)
        self._prev_state_idx: Optional[int] = None
        self._prev_action:    Optional[int] = None
        self._prev_pnl:       float = 0.0
        self._daily_start_pnl: float = 0.0
        self._current_day:    int = -1

    # ------------------------------------------------------------------

    def _state_index(self, sv: np.ndarray) -> int:
        inv_b   = int(np.digitize(sv[0], INV_BINS))
        vol_b   = int(np.digitize(sv[1], VOL_BINS))
        mom_b   = int(np.digitize(sv[2], MOM_BINS))
        spike_b = int(np.digitize(sv[4], SPIKE_BINS))
        return inv_b * (4 * 3 * 2) + vol_b * (3 * 2) + mom_b * 2 + spike_b

    def reset_episode(self, total_pnl: float = 0.0) -> None:
        self._prev_state_idx = None
        self._prev_action    = None
        self._prev_pnl       = total_pnl
        self._daily_start_pnl = total_pnl

    def on_fill(self, timestamp: float) -> None:
        pass

    # ------------------------------------------------------------------

    def compute_quotes(
        self,
        stats: MicrostructureStats,
        inventory: float,
        timestamp: float,
        **kwargs,
    ) -> QuoteDecision:
        import datetime
        total_pnl = kwargs.get("total_pnl", self._prev_pnl)

        day = datetime.datetime.utcfromtimestamp(timestamp).toordinal()
        if day != self._current_day:
            self._current_day = day
            self.reset_episode(total_pnl)

        self._vol_history.append(stats.sigma)
        daily_pnl = total_pnl - self._daily_start_pnl
        sv = encode_state(stats, inventory, self.max_inventory,
                          daily_pnl, self.daily_loss_limit, self._vol_history)
        state_idx = self._state_index(sv)

        # Q-update
        if self._prev_state_idx is not None:
            dpnl   = total_pnl - self._prev_pnl
            reward = dpnl - self.inv_penalty * abs(inventory) * stats.sigma / (
                self.max_inventory + 1e-9)
            best_next = np.max(self.Q[state_idx])
            td_target = reward + self.discount * best_next
            self.Q[self._prev_state_idx, self._prev_action] += self.lr * (
                td_target - self.Q[self._prev_state_idx, self._prev_action])

        # Epsilon-greedy
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)
        if np.random.random() < self.epsilon:
            action = np.random.randint(N_ACTIONS)
        else:
            action = int(np.argmax(self.Q[state_idx]))

        self._prev_state_idx = state_idx
        self._prev_action    = action
        self._prev_pnl       = total_pnl

        return build_quote(action, stats, self.tick_size,
                           self.order_size, self.max_inventory, inventory)

    def select_action(self, state: np.ndarray) -> int:
        """Epsilon-greedy action selection from encoded state vector."""
        state_idx = self._state_index(state)
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)
        if np.random.random() < self.epsilon:
            return np.random.randint(N_ACTIONS)
        return int(np.argmax(self.Q[state_idx]))

    def update(self, state: np.ndarray, action: int, reward: float,
               next_state: np.ndarray, done: bool = False) -> None:
        """One Q-update step from an (s, a, r, s') transition."""
        si      = self._state_index(state)
        si_next = self._state_index(next_state)
        best_next = 0.0 if done else float(np.max(self.Q[si_next]))
        td_target = reward + self.discount * best_next
        self.Q[si, action] += self.lr * (td_target - self.Q[si, action])

    def save(self, path: str) -> None:
        np.save(path, self.Q)

    def load(self, path: str) -> None:
        self.Q   = np.load(path)
        self.epsilon = self.epsilon_end


# ---------------------------------------------------------------------------
# 2. Deep Q-Network (PyTorch)
# ---------------------------------------------------------------------------

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False


@dataclass
class _Transition:
    state:      "np.ndarray"
    action:     int
    reward:     float
    next_state: "np.ndarray"
    done:       bool


class _ReplayBuffer:
    def __init__(self, capacity: int = 50_000):
        self.buf: deque = deque(maxlen=capacity)

    def push(self, t: _Transition) -> None:
        self.buf.append(t)

    def sample(self, n: int) -> List[_Transition]:
        return random.sample(self.buf, n)

    def __len__(self) -> int:
        return len(self.buf)


class DQNMarketMaker:
    """
    Double DQN market maker with experience replay.

    Architecture: Linear(STATE_DIM → 128) → ReLU → Linear(128 → 128)
                  → ReLU → Linear(128 → 64) → ReLU → Linear(64 → N_ACTIONS)

    Online + target network; target synced every `target_update` steps.
    Gradient clipping (norm ≤ 1) for stability.

    The environment calls compute_quotes at every quoting step.
    The agent observes state, executes Q-update from the previous step,
    selects the next action, and returns a QuoteDecision.
    Order lifetime is embedded in the action (ACTION_PARAMS[a][2]); the
    environment is responsible for advancing time by that duration.
    """

    def __init__(
        self,
        tick_size: float = 0.001,
        order_size: float = 5.0,
        max_inventory: float = 100.0,
        daily_loss_limit: float = 30.0,
        hidden_dim: int = 128,
        lr: float = 3e-4,
        discount: float = 0.99,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
        epsilon_decay: float = 0.9999,
        batch_size: int = 128,
        target_update: int = 50,
        replay_capacity: int = 50_000,
        inventory_penalty: float = 0.05,
        train_mode: bool = True,
    ):
        if not _TORCH_AVAILABLE:
            raise ImportError("PyTorch required. Install: pip install torch")

        self.tick_size       = tick_size
        self.order_size      = order_size
        self.max_inventory   = max_inventory
        self.daily_loss_limit = daily_loss_limit
        self.discount        = discount
        self.epsilon         = epsilon_start
        self.epsilon_end     = epsilon_end
        self.epsilon_decay   = epsilon_decay
        self.batch_size      = batch_size
        self.target_update   = target_update
        self.inv_penalty     = inventory_penalty
        self.train_mode      = train_mode

        def _net():
            return nn.Sequential(
                nn.Linear(STATE_DIM, hidden_dim), nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim), nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim // 2), nn.ReLU(),
                nn.Linear(hidden_dim // 2, N_ACTIONS),
            )

        self.online_net = _net()
        self.target_net = _net()
        self.target_net.load_state_dict(self.online_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.Adam(self.online_net.parameters(), lr=lr)
        self.replay    = _ReplayBuffer(replay_capacity)

        self._vol_history: deque = deque(maxlen=120)
        self._step:            int = 0
        self._prev_state:      Optional[np.ndarray] = None
        self._prev_action:     Optional[int] = None
        self._prev_pnl:        float = 0.0
        self._daily_start_pnl: float = 0.0
        self._current_day:     int = -1

        self.last_loss: Optional[float] = None

    # ------------------------------------------------------------------

    def reset_episode(self, total_pnl: float = 0.0) -> None:
        self._prev_state  = None
        self._prev_action = None
        self._prev_pnl    = total_pnl
        self._daily_start_pnl = total_pnl

    def on_fill(self, timestamp: float) -> None:
        pass

    # ------------------------------------------------------------------

    def _select_action(self, state: np.ndarray) -> int:
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)
        if self.train_mode and np.random.random() < self.epsilon:
            return np.random.randint(N_ACTIONS)
        with torch.no_grad():
            sv = torch.FloatTensor(state).unsqueeze(0)
            return int(self.online_net(sv).argmax(dim=1).item())

    def _train_step(self) -> Optional[float]:
        if len(self.replay) < self.batch_size:
            return None

        batch       = self.replay.sample(self.batch_size)
        states      = torch.FloatTensor(np.vstack([t.state      for t in batch]))
        actions     = torch.LongTensor( np.array( [t.action     for t in batch]))
        rewards     = torch.FloatTensor(np.array( [t.reward     for t in batch]))
        next_states = torch.FloatTensor(np.vstack([t.next_state for t in batch]))
        dones       = torch.FloatTensor(np.array( [float(t.done) for t in batch]))

        # Double DQN
        with torch.no_grad():
            best_a  = self.online_net(next_states).argmax(dim=1)
            q_next  = self.target_net(next_states).gather(1, best_a.unsqueeze(1)).squeeze(1)
            targets = rewards + self.discount * (1.0 - dones) * q_next

        q_cur = self.online_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)
        loss  = nn.MSELoss()(q_cur, targets)

        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.online_net.parameters(), 1.0)
        self.optimizer.step()

        if self._step % self.target_update == 0:
            self.target_net.load_state_dict(self.online_net.state_dict())

        return float(loss.item())

    # ------------------------------------------------------------------

    def compute_quotes(
        self,
        stats: MicrostructureStats,
        inventory: float,
        timestamp: float,
        **kwargs,
    ) -> QuoteDecision:
        import datetime
        total_pnl = kwargs.get("total_pnl", self._prev_pnl)

        day = datetime.datetime.utcfromtimestamp(timestamp).toordinal()
        if day != self._current_day:
            self._current_day = day
            self.reset_episode(total_pnl)

        self._vol_history.append(stats.sigma)
        daily_pnl = total_pnl - self._daily_start_pnl
        sv = encode_state(stats, inventory, self.max_inventory,
                          daily_pnl, self.daily_loss_limit, self._vol_history)

        if self.train_mode and self._prev_state is not None:
            dpnl   = total_pnl - self._prev_pnl
            reward = dpnl - self.inv_penalty * abs(inventory) * stats.sigma / (
                self.max_inventory + 1e-9)
            self.replay.push(_Transition(
                state=self._prev_state, action=self._prev_action,
                reward=reward, next_state=sv, done=False,
            ))
            self._step += 1
            loss = self._train_step()
            if loss is not None:
                self.last_loss = loss

        action = self._select_action(sv)
        self._prev_state  = sv
        self._prev_action = action
        self._prev_pnl    = total_pnl

        return build_quote(action, stats, self.tick_size,
                           self.order_size, self.max_inventory, inventory)

    # ------------------------------------------------------------------

    def update(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
    ) -> Optional[float]:
        """
        Push a transition to the replay buffer and run one gradient step.
        Called by the external training loop after each env.step().
        """
        self.replay.push(_Transition(
            state=state, action=action, reward=reward,
            next_state=next_state, done=done,
        ))
        self._step += 1
        loss = self._train_step()
        if loss is not None:
            self.last_loss = loss
        return loss

    def select_action(self, state: np.ndarray) -> int:
        """Public alias for _select_action (for use in external training loops)."""
        return self._select_action(state)

    def save(self, path: str) -> None:
        torch.save({
            "online": self.online_net.state_dict(),
            "target": self.target_net.state_dict(),
            "optim":  self.optimizer.state_dict(),
            "eps":    self.epsilon,
            "step":   self._step,
        }, path)

    def load(self, path: str) -> None:
        ckpt = torch.load(path, map_location="cpu")
        self.online_net.load_state_dict(ckpt["online"])
        self.target_net.load_state_dict(ckpt["target"])
        self.optimizer.load_state_dict(ckpt["optim"])
        self.epsilon = ckpt.get("eps", self.epsilon_end)
        self._step   = ckpt.get("step", 0)
        if not self.train_mode:
            self.epsilon = self.epsilon_end
