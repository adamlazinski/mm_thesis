"""
Market Making Environment
--------------------------
Gym-style wrapper around the backtest engine for multi-day RL training.

Each episode = one calendar day of tick data.
The environment drives the backtest, collects (state, action, reward, next_state)
transitions, and computes episode-level statistics.

Usage (manual training loop — see scripts/train_rl.py for full driver):

    env = MarketMakingEnv(day_files, cfg)
    for episode_idx in range(n_episodes):
        obs = env.reset()          # loads next day
        done = False
        while not done:
            action = agent.select_action(obs)
            obs, reward, done, info = env.step(action)
        episode_stats = env.episode_stats()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional

import numpy as np

from ..data.loader import DataLoader
from ..core.market_state import MarketState
from ..core.order_manager import OrderManager
from ..core.events import QuoteEvent, TradeEvent
from ..strategies.avellaneda_stoikov import QuoteDecision
from ..extensions.reinforcement_learning import (
    encode_state, build_quote, action_hold, N_ACTIONS, STATE_DIM
)


@dataclass
class StepInfo:
    timestamp:   float
    inventory:   float
    total_pnl:   float
    daily_pnl:   float
    action:      int
    reward:      float
    bid_price:   float
    ask_price:   float
    n_fills:     int


@dataclass
class EpisodeStats:
    date:          str
    total_pnl:     float
    max_drawdown:  float
    n_fills:       int
    mean_inventory: float
    peak_inventory: float
    mean_reward:   float
    n_steps:       int
    halts:         int
    action_counts: List[int] = field(default_factory=lambda: [0]*N_ACTIONS)


class MarketMakingEnv:
    """
    Single-asset, single-day market making environment.

    Drives the event loop directly rather than going through Backtest,
    so that the RL agent's action is applied at each quote step.

    Parameters
    ----------
    day_files : list of (trades_path, quotes_path) tuples
        All available trading days.  reset() picks the next one in order
        (or randomly if shuffle=True).
    cfg : dict
        Strategy and environment parameters (see train_rl.py for schema).
    shuffle : bool
        Whether to shuffle day order across episodes.
    """

    def __init__(
        self,
        day_files: List[Tuple[str, str]],
        cfg: dict,
        shuffle: bool = True,
    ):
        self.day_files     = day_files
        self.cfg           = cfg
        self.shuffle       = shuffle

        self.order_size      = cfg["order_size"]
        self.max_inventory   = cfg["max_inventory"]
        self.tick_size       = cfg.get("tick_size", 0.001)
        self.daily_loss_limit = cfg.get("daily_loss_limit", 9999.0)
        self.maker_fee       = cfg.get("maker_fee", 0.0)
        self.latency         = cfg.get("latency", 0.1)
        self.quote_freq      = cfg.get("quote_freq", 0.5)
        self.tolerance_ticks = cfg.get("tolerance_ticks", 0.5)
        self.vol_window      = int(cfg.get("vol_window", 120))
        self.arrival_window  = int(cfg.get("arrival_window", 60))
        self.ewma_alpha      = cfg.get("ewma_alpha", 0.9)
        self.short_gap       = cfg.get("short_gap", 2.0)
        self.long_gap        = cfg.get("long_gap", 30.0)
        self.inventory_penalty = cfg.get("inventory_penalty", 0.05)

        self._day_order   = list(range(len(day_files)))
        self._day_cursor  = 0
        self._episode_idx = 0

        self._trades: List[TradeEvent] = []
        self._quotes: List[QuoteEvent] = []
        self._t_idx: int = 0
        self._q_idx: int = 0
        self._order_manager: Optional[OrderManager] = None
        self._market_state:  Optional[MarketState]  = None
        self._current_date:  str = ""
        self._step_log:      List[StepInfo] = []
        self._vol_history    = None
        self._daily_start_pnl: float = 0.0
        self._episode_done:  bool = True

    # ------------------------------------------------------------------
    # Gym interface
    # ------------------------------------------------------------------

    def reset(self) -> np.ndarray:
        from collections import deque

        if self.shuffle and self._day_cursor == 0:
            np.random.shuffle(self._day_order)

        day_idx = self._day_order[self._day_cursor]
        self._day_cursor = (self._day_cursor + 1) % len(self.day_files)
        self._episode_idx += 1

        trades_path, quotes_path = self.day_files[day_idx]
        self._current_date = Path(trades_path).stem.split("_")[-1]

        loader = DataLoader()
        self._trades, self._quotes = loader.load_coinapi(
            trades_path=trades_path,
            quotes_path=quotes_path,
            timestamp_col=self.cfg.get("timestamp", "time_exchange"),
        )

        self._t_idx = 0
        self._q_idx = 0
        self._order_manager = OrderManager(
            maker_fee=self.maker_fee,
            latency=self.latency,
            queue_model="none",
        )
        self._market_state = MarketState(
            vol_window=self.vol_window,
            arrival_window=self.arrival_window,
            ewma_alpha=self.ewma_alpha,
        )
        self._vol_history   = deque(maxlen=self.vol_window)
        self._step_log      = []
        self._daily_start_pnl = 0.0
        self._episode_done  = False

        return self._initial_obs()

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, StepInfo]:
        if self._episode_done:
            raise RuntimeError("Call reset() before step().")

        hold = action_hold(action) or self.quote_freq
        timestamp, n_fills = self._advance_window(hold)
        done = (self._q_idx >= len(self._quotes)) or (self._t_idx >= len(self._trades))

        om   = self._order_manager
        ms   = self._market_state
        inv  = om.inventory
        pnl  = om.total_pnl
        stats = ms.stats
        mid   = stats.mid_price

        # Cancel stale quotes, submit new ones for this action
        om.cancel_all(timestamp)
        decision = build_quote(action, stats, self.tick_size,
                               self.order_size, self.max_inventory, inv)
        if decision.should_quote_bid:
            om.submit_order("bid", decision.bid_price, decision.bid_size, timestamp)
        if decision.should_quote_ask:
            om.submit_order("ask", decision.ask_price, decision.ask_size, timestamp)

        # Reward: ΔPnL minus inventory penalty (penalises holding large positions
        # in volatile markets, scales reward to the same units as PnL)
        prev_pnl = self._step_log[-1].total_pnl if self._step_log else pnl
        dpnl     = pnl - prev_pnl
        reward   = dpnl - self.inventory_penalty * abs(inv) * stats.sigma / (
            self.max_inventory + 1e-9)

        daily_pnl = pnl - self._daily_start_pnl
        if daily_pnl < -self.daily_loss_limit:
            done = True
            om.cancel_all(timestamp)
            reward -= abs(daily_pnl) * 0.1

        self._vol_history.append(stats.sigma)
        obs = encode_state(stats, inv, self.max_inventory,
                           daily_pnl, self.daily_loss_limit, self._vol_history)

        info = StepInfo(
            timestamp=timestamp,
            inventory=inv,
            total_pnl=pnl,
            daily_pnl=daily_pnl,
            action=action,
            reward=reward,
            bid_price=decision.bid_price,
            ask_price=decision.ask_price,
            n_fills=n_fills,
        )
        self._step_log.append(info)

        if done:
            if abs(inv) > 1e-9 and mid > 0:
                # Close inventory at mid
                sign = 1 if inv > 0 else -1
                om.cash += sign * abs(inv) * mid
                om.inventory -= sign * abs(inv)
            self._episode_done = True

        return obs, reward, done, info

    # ------------------------------------------------------------------

    def episode_stats(self) -> EpisodeStats:
        if not self._step_log:
            return EpisodeStats(self._current_date, 0, 0, 0, 0, 0, 0, 0, 0)
        pnls    = [s.total_pnl for s in self._step_log]
        rewards = [s.reward    for s in self._step_log]
        invs    = [abs(s.inventory) for s in self._step_log]
        actions = [s.action    for s in self._step_log]
        total_pnl = self._order_manager.total_pnl
        peak = pnls[0]
        max_dd = 0.0
        for p in pnls:
            peak = max(peak, p)
            max_dd = min(max_dd, p - peak)
        action_counts = [actions.count(a) for a in range(N_ACTIONS)]
        return EpisodeStats(
            date=self._current_date,
            total_pnl=total_pnl,
            max_drawdown=max_dd,
            n_fills=sum(s.n_fills for s in self._step_log),
            mean_inventory=float(np.mean(invs)),
            peak_inventory=float(np.max(invs)),
            mean_reward=float(np.mean(rewards)),
            n_steps=len(self._step_log),
            halts=actions.count(0),
            action_counts=action_counts,
        )

    # ------------------------------------------------------------------

    def _initial_obs(self) -> np.ndarray:
        from collections import deque as _dq
        dummy_stats = self._market_state.stats
        return encode_state(dummy_stats, 0.0, self.max_inventory,
                            0.0, self.daily_loss_limit, _dq(maxlen=10))

    def _advance_window(self, duration: float) -> Tuple[float, int]:
        """
        Consume trade + quote events for `duration` seconds.
        Returns (end_timestamp, n_fills).
        """
        q  = self._quotes
        t  = self._trades
        om = self._order_manager
        ms = self._market_state

        current_q_ts = q[self._q_idx].timestamp if self._q_idx < len(q) else (
            t[self._t_idx].timestamp if self._t_idx < len(t) else 0.0)
        next_q_ts    = current_q_ts + duration
        n_fills = 0

        while True:
            t_ts = t[self._t_idx].timestamp if self._t_idx < len(t) else float("inf")
            q_ts = q[self._q_idx].timestamp if self._q_idx < len(q) else float("inf")

            if min(t_ts, q_ts) >= next_q_ts:
                break

            if t_ts <= q_ts:
                ev = t[self._t_idx]
                self._t_idx += 1
                fills = om.process_trade(ev.timestamp, ev.price, ev.quantity, ev.side)
                n_fills += len(fills)
                ms.on_trade(ev.timestamp, ev.price, ev.quantity, ev.side)
            else:
                ev = q[self._q_idx]
                self._q_idx += 1
                ms.on_quote(ev.timestamp, ev.best_bid, ev.best_ask,
                            ev.bid_size, ev.ask_size)
                om.update_mid((ev.best_bid + ev.best_ask) / 2.0)

        # Process the boundary quote event
        if self._q_idx < len(q):
            ev = q[self._q_idx]
            ms.on_quote(ev.timestamp, ev.best_bid, ev.best_ask,
                        ev.bid_size, ev.ask_size)
            om.update_mid((ev.best_bid + ev.best_ask) / 2.0)
            self._q_idx += 1

        return next_q_ts, n_fills
