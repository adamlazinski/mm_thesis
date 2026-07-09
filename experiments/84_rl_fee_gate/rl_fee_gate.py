"""
rl_fee_gate.py
==============
Exp 84 — DQN gate controller optimised for 0.02% maker fee.

Rule-based GatedSpotSkewMM (alpha=4 gate=1.5) earns +$80/day gross but only
+$21/day net at 0.02% maker fee. The gate fires whenever |ideal - last| > 1.5 ticks
regardless of signal quality or fee cost.

A DQN agent learns a state-dependent cancel policy:
  HOLD            — preserve queue priority, no fee cost
  CANCEL(alpha=4) — aggressive OBI lean (confident signal)
  CANCEL(alpha=2) — moderate lean
  CANCEL(alpha=0) — symmetric repost (only mid-drift forced update)

Reward per step: delta mark-to-market – 0.02% × fill_notional

Training:  simplified 100ms-step environment on IS days (Apr 2026)
           DQN with replay buffer, ε-greedy exploration
Eval:      trained DQN plugged into real Backtest engine at 10ms
           compared against rule-based at same 0.02% fee

Run from master2/:
    python experiments/84_rl_fee_gate/rl_fee_gate.py
"""
from __future__ import annotations

import glob
import json
import random
import re
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hft_market_maker.backtest import Backtest
from hft_market_maker.core.l2_features import BookSnapshot, L2BookTracker
from hft_market_maker.core.market_state import MarketState
from hft_market_maker.core.order_manager import OrderManager
from hft_market_maker.data.loader import DataLoader
from hft_market_maker.strategies.avellaneda_stoikov import QuoteDecision

DATA = ROOT / "data" / "real"
OUT  = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

# ── Asset constants ────────────────────────────────────────────────────────────
TICK             = 0.001
ORDER_SIZE       = 5.0
MAX_INV          = 38.0
LATENCY          = 0.01
REQUOTE_INTERVAL = 0.01   # 10ms real backtest
TAKER_FEE        = 0.00045
MAKER_FEE        = 0.0002  # 0.02% target
QUEUE_FRACTION   = 0.5
MID_DRIFT_TICKS  = 5

# ── RL constants ───────────────────────────────────────────────────────────────
TRAIN_STEP_S   = 0.10        # 100ms env step for fast training
STATE_DIM      = 7
# Action space — ordered from aggressive (inside-spread lean) to wide (deep book):
#   0  HOLD             — keep current quotes, preserve queue priority
#   1  CANCEL(α=+4)     — aggressive OBI lean: bid ~3 ticks inside spread
#   2  CANCEL(α=+2)     — moderate lean: bid ~4 ticks inside spread
#   3  CANCEL(α= 0)     — symmetric: bid at mid (~5 ticks inside), widest inside-spread
#   4  CANCEL(α=-4)     — anti-lean: bid shifted toward best_bid (~1-2 ticks inside)
#   5  POST_AT_TOUCH    — bid=best_bid, ask=best_ask (standard queue, ~5-tick capture)
N_ACTIONS      = 6
ALPHAS         = [4.0, 2.0, 0.0, -4.0]   # for actions 1-4; action 5 = at-touch

BATCH_SIZE     = 256
LR             = 1e-3
GAMMA          = 0.995       # high because reward is sparse
TAU            = 0.005       # soft target-network update
REPLAY_CAP     = 300_000
UPDATE_FREQ    = 32          # gradient step every N env steps
TARGET_FREQ    = 500         # target-network sync every N gradient steps
N_EPOCHS       = 4           # passes through IS data

EPS_START      = 1.0
EPS_END        = 0.05
OBI_HIST_LEN   = 100         # 10 s at 100ms
CANCEL_NORM    = 300.0       # seconds (normaliser for time-since-cancel)

DEVICE = torch.device("cpu")


# ── Data preprocessing ─────────────────────────────────────────────────────────

def preprocess_day(trades_path: str, quotes_path: str,
                   step_s: float = TRAIN_STEP_S) -> dict:
    """
    Bin raw tick data into fixed time steps.
    Returns numpy arrays indexed by step for efficient env stepping.
    """
    tdf = pd.read_parquet(trades_path,
                          columns=["time_exchange", "price", "size"])
    qdf = pd.read_parquet(quotes_path,
                          columns=["time_exchange", "bid_price", "ask_price",
                                   "bid_size", "ask_size"])

    q_ts = qdf["time_exchange"].values.astype("datetime64[ns]").astype("int64") / 1e9
    t_ts = tdf["time_exchange"].values.astype("datetime64[ns]").astype("int64") / 1e9

    t0 = min(q_ts[0], t_ts[0])
    t1 = max(q_ts[-1], t_ts[-1])
    steps = np.arange(t0, t1 + step_s, step_s)
    n = len(steps)

    # Forward-fill quotes onto step grid
    q_idx = np.searchsorted(q_ts, steps, side="right") - 1
    q_idx = np.clip(q_idx, 0, len(q_ts) - 1)
    best_bid  = qdf["bid_price"].values[q_idx].astype(np.float32)
    best_ask  = qdf["ask_price"].values[q_idx].astype(np.float32)
    bid_depth = qdf["bid_size"].values[q_idx].astype(np.float32)
    ask_depth = qdf["ask_size"].values[q_idx].astype(np.float32)

    # Aggregate trades into steps via pandas groupby
    trade_step = np.searchsorted(steps, t_ts, side="right") - 1
    trade_step = np.clip(trade_step, 0, n - 1)
    tdf2 = pd.DataFrame({"step": trade_step,
                          "price": tdf["price"].values.astype(float),
                          "size":  tdf["size"].values.astype(float)})
    min_price = np.full(n, np.inf,  dtype=np.float32)
    max_price = np.full(n, -np.inf, dtype=np.float32)
    vol       = np.zeros(n, dtype=np.float32)

    if len(tdf2) > 0:
        gmin = tdf2.groupby("step")["price"].min()
        gmax = tdf2.groupby("step")["price"].max()
        gvol = tdf2.groupby("step")["size"].sum()
        min_price[gmin.index] = gmin.values.astype(np.float32)
        max_price[gmax.index] = gmax.values.astype(np.float32)
        vol[gvol.index]       = gvol.values.astype(np.float32)

    total_d = bid_depth + ask_depth
    obi   = np.where(total_d > 0, (bid_depth - ask_depth) / total_d, 0.0).astype(np.float32)
    mid   = ((best_bid + best_ask) / 2).astype(np.float32)
    spread = (best_ask - best_bid).astype(np.float32)

    return dict(n=n, ts=steps, mid=mid, spread=spread,
                best_bid=best_bid, best_ask=best_ask, bid_depth=bid_depth,
                obi=obi, min_price=min_price, max_price=max_price, vol=vol)


# ── Simplified RL environment ──────────────────────────────────────────────────

class SpreadEnv:
    """
    100ms-step environment for LINK spot inside-spread MM.
    Faithful to the key mechanism: inside-spread → queue_ahead=0 → fills on trade.
    """

    def __init__(self, maker_fee: float = MAKER_FEE):
        self.maker_fee = maker_fee
        self.d: dict | None = None
        self._obi_hist  = np.zeros(OBI_HIST_LEN, dtype=np.float32)
        self._obi_ptr   = 0

    def load_day(self, preprocessed: dict) -> None:
        self.d = preprocessed

    def reset(self) -> np.ndarray:
        self.t                = 0
        self.inv              = 0.0
        self.cash             = 0.0
        self.active_bid: float | None = None
        self.active_ask: float | None = None
        self.last_mid: float | None   = None
        self.secs_since_cancel        = 0.0
        self._obi_hist[:] = 0.0
        self._obi_ptr     = 0
        self.ep_gross_pnl  = 0.0
        self.ep_fee        = 0.0
        self.ep_fills      = 0
        self.ep_cancels    = 0
        return self._obs()

    def _obs(self) -> np.ndarray:
        t   = min(self.t, self.d["n"] - 1)
        d   = self.d
        obi = float(d["obi"][t])

        self._obi_hist[self._obi_ptr % OBI_HIST_LEN] = obi
        self._obi_ptr += 1
        obi_std = float(np.std(self._obi_hist))

        inv_norm    = np.clip(self.inv / MAX_INV, -1.0, 1.0)
        cancel_norm = min(self.secs_since_cancel / CANCEL_NORM, 1.0)

        mid = float(d["mid"][t])
        if self.last_mid is not None:
            mid_drift_norm = min(abs(mid - self.last_mid) / (20 * TICK), 1.0)
        else:
            mid_drift_norm = 0.0

        # Rolling vol: std of mid changes over last OBI_HIST_LEN steps
        i0 = max(0, t - OBI_HIST_LEN)
        mid_window = d["mid"][i0:t + 1]
        if len(mid_window) > 2:
            log_vol = float(np.log1p(np.std(np.diff(mid_window)) / TICK))
        else:
            log_vol = 0.0

        tod = float(d["ts"][t] % 86400) / 86400.0

        return np.array([obi, obi_std, inv_norm, cancel_norm,
                         mid_drift_norm, log_vol, tod], dtype=np.float32)

    def step(self, action: int):
        d   = self.d
        t   = self.t
        n   = d["n"]

        if t >= n:
            return self._obs(), 0.0, True

        mid      = float(d["mid"][t])
        spread   = float(d["spread"][t])
        best_bid = float(d["best_bid"][t])
        best_ask = float(d["best_ask"][t])
        bid_dep  = float(d["bid_depth"][t])
        obi      = float(d["obi"][t])

        half = spread / 2.0 if spread > 0 else 5 * TICK

        # Force-cancel if mid has drifted
        force = (self.last_mid is not None and
                 abs(mid - self.last_mid) > MID_DRIFT_TICKS * TICK)

        if action == 0 and self.active_bid is not None and not force:
            bid, ask = self.active_bid, self.active_ask
        elif action == 5 and not force:  # POST_AT_TOUCH: bid=best_bid, ask=best_ask
            bid = best_bid
            ask = best_ask
            self.active_bid = bid
            self.active_ask = ask
            self.last_mid   = mid
            self.secs_since_cancel = 0.0
            self.ep_cancels += 1
        else:
            alpha = ALPHAS[action - 1] if (action > 0 and not force) else 4.0
            shift = alpha * obi * TICK
            bid = round((mid - half + shift) / TICK) * TICK
            ask = round((mid + half + shift) / TICK) * TICK
            if ask <= bid:
                ask = bid + TICK
            # post_only: reject if marketable
            if bid >= best_ask:
                bid = best_bid
            if ask <= best_bid:
                ask = best_ask
            self.active_bid = bid
            self.active_ask = ask
            self.last_mid   = mid
            self.secs_since_cancel = 0.0
            self.ep_cancels += 1

        # Fill simulation (price-only model, same as backtest)
        reward     = 0.0
        min_tp     = float(d["min_price"][t])
        max_tp     = float(d["max_price"][t])

        # Bid fill
        if self.active_bid is not None and self.inv < MAX_INV and min_tp <= self.active_bid:
            if self.active_bid > best_bid + 1e-9:     # inside spread → full priority
                fq = ORDER_SIZE
            elif abs(self.active_bid - best_bid) < 1e-9:  # at best bid → partial
                fq = ORDER_SIZE * QUEUE_FRACTION
            else:
                fq = 0.0
            if fq > 0:
                fp  = self.active_bid
                fee = self.maker_fee * fp * fq
                self.inv  += fq
                self.cash -= fp * fq + fee
                gross      = fq * (mid - fp)   # spread-captured
                self.ep_gross_pnl += gross
                self.ep_fee       += fee
                reward            += gross - fee
                self.ep_fills     += 1

        # Ask fill
        if self.active_ask is not None and self.inv > -MAX_INV and max_tp >= self.active_ask:
            if self.active_ask < best_ask - 1e-9:
                fq = ORDER_SIZE
            elif abs(self.active_ask - best_ask) < 1e-9:
                fq = ORDER_SIZE * QUEUE_FRACTION
            else:
                fq = 0.0
            if fq > 0:
                fp  = self.active_ask
                fee = self.maker_fee * fp * fq
                self.inv  -= fq
                self.cash += fp * fq - fee
                gross      = fq * (fp - mid)
                self.ep_gross_pnl += gross
                self.ep_fee       += fee
                reward            += gross - fee
                self.ep_fills     += 1

        self.secs_since_cancel += TRAIN_STEP_S
        self.t += 1
        done = (self.t >= n)

        return self._obs(), reward, done


# ── DQN ───────────────────────────────────────────────────────────────────────

class DQN(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(STATE_DIM, 64), nn.ReLU(),
            nn.Linear(64, 64),        nn.ReLU(),
            nn.Linear(64, N_ACTIONS),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class ReplayBuffer:
    def __init__(self, capacity: int = REPLAY_CAP):
        self.buf = deque(maxlen=capacity)

    def push(self, s, a, r, s2, done):
        self.buf.append((s, a, float(r), s2, float(done)))

    def sample(self, n: int):
        batch = random.sample(self.buf, n)
        s, a, r, s2, d = zip(*batch)
        return (torch.FloatTensor(np.array(s)).to(DEVICE),
                torch.LongTensor(a).to(DEVICE),
                torch.FloatTensor(r).to(DEVICE),
                torch.FloatTensor(np.array(s2)).to(DEVICE),
                torch.FloatTensor(d).to(DEVICE))

    def __len__(self):
        return len(self.buf)


# ── Training ──────────────────────────────────────────────────────────────────

def train(is_days: list[str]) -> DQN:
    policy = DQN().to(DEVICE)
    target = DQN().to(DEVICE)
    target.load_state_dict(policy.state_dict())
    target.eval()

    opt    = optim.Adam(policy.parameters(), lr=LR)
    buf    = ReplayBuffer()
    env    = SpreadEnv(maker_fee=MAKER_FEE)

    total_eps = len(is_days) * N_EPOCHS
    eps_step  = 0
    grad_step = 0
    t_start   = time.time()

    print(f"\nTraining DQN on {len(is_days)} IS days × {N_EPOCHS} epochs "
          f"({total_eps} episodes)")
    print(f"100ms env steps, MAKER_FEE={MAKER_FEE*100:.2f}%\n")

    for epoch in range(N_EPOCHS):
        ep_results = []
        for ep_i, date in enumerate(is_days):
            global_ep = epoch * len(is_days) + ep_i
            eps = max(EPS_END,
                      EPS_START - (EPS_START - EPS_END) * global_ep / (total_eps * 0.8))

            d = preprocess_day(
                str(DATA / f"trades_LINK_{date}.parquet"),
                str(DATA / f"quotes_LINK_{date}.parquet"),
                step_s=TRAIN_STEP_S)
            env.load_day(d)
            obs = env.reset()

            while True:
                if random.random() < eps:
                    action = random.randrange(N_ACTIONS)
                else:
                    with torch.no_grad():
                        q = policy(torch.FloatTensor(obs).unsqueeze(0).to(DEVICE))
                        action = q.argmax().item()

                obs2, reward, done = env.step(action)
                buf.push(obs, action, reward, obs2, done)
                obs = obs2
                eps_step += 1

                if len(buf) >= BATCH_SIZE and eps_step % UPDATE_FREQ == 0:
                    s, a, r, s2, d_done = buf.sample(BATCH_SIZE)
                    with torch.no_grad():
                        q_next = target(s2).max(1)[0]
                        q_tgt  = r + GAMMA * q_next * (1 - d_done)
                    q_pred = policy(s).gather(1, a.unsqueeze(1)).squeeze()
                    loss   = nn.functional.smooth_l1_loss(q_pred, q_tgt)
                    opt.zero_grad()
                    loss.backward()
                    nn.utils.clip_grad_norm_(policy.parameters(), 1.0)
                    opt.step()
                    grad_step += 1

                    if grad_step % TARGET_FREQ == 0:
                        for p, t_ in zip(policy.parameters(), target.parameters()):
                            t_.data.copy_(TAU * p.data + (1 - TAU) * t_.data)

                if done:
                    break

            net = env.ep_gross_pnl - env.ep_fee
            ep_results.append(net)
            cr  = env.ep_cancels / max(env.ep_fills + env.ep_cancels, 1)
            print(f"  ep{global_ep+1:3}/{total_eps}  {date}  "
                  f"ε={eps:.2f}  net={net:+.2f}  fills={env.ep_fills}  "
                  f"cancel%={100*cr:.1f}  buf={len(buf)}")

        print(f"  ── epoch {epoch+1} mean net pnl/day: "
              f"{np.mean(ep_results):+.2f}  "
              f"elapsed {time.time()-t_start:.0f}s\n")

    return policy


# ── RL strategy (plugs into real Backtest) ────────────────────────────────────

class RLGatedMM:
    """Trained DQN wrapped as a Backtest-compatible strategy."""

    def __init__(self, net: DQN):
        self.net = net
        self.net.eval()

        self._last_bid: float | None = None
        self._last_ask: float | None = None
        self._last_mid: float | None = None
        self._secs_since_cancel = 0.0
        self._last_ts: float | None = None

        self._obi_hist = np.zeros(OBI_HIST_LEN, dtype=np.float32)
        self._obi_ptr  = 0
        self._mid_hist = deque(maxlen=OBI_HIST_LEN)

        self.n_recomputes = 0
        self.n_cancels    = 0
        self.action_counts = [0] * N_ACTIONS

    def _obs(self, stats, inv, ts) -> np.ndarray:
        obi = float(stats.obi)

        self._obi_hist[self._obi_ptr % OBI_HIST_LEN] = obi
        self._obi_ptr += 1
        obi_std = float(np.std(self._obi_hist))

        inv_norm    = float(np.clip(inv / MAX_INV, -1.0, 1.0))
        cancel_norm = min(self._secs_since_cancel / CANCEL_NORM, 1.0)

        mid = stats.mid_price
        if self._last_mid is not None:
            mid_drift_norm = min(abs(mid - self._last_mid) / (20 * TICK), 1.0)
        else:
            mid_drift_norm = 0.0

        self._mid_hist.append(mid)
        if len(self._mid_hist) > 2:
            log_vol = float(np.log1p(
                np.std(np.diff(list(self._mid_hist))) / TICK))
        else:
            log_vol = 0.0

        tod = float(ts % 86400) / 86400.0

        return np.array([obi, obi_std, inv_norm, cancel_norm,
                         mid_drift_norm, log_vol, tod], dtype=np.float32)

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        self.n_recomputes += 1

        # Update time-since-cancel
        if self._last_ts is not None:
            self._secs_since_cancel += ts - self._last_ts
        self._last_ts = ts

        mid  = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else 5 * TICK

        obs = self._obs(stats, inv, ts)
        with torch.no_grad():
            q   = self.net(torch.FloatTensor(obs).unsqueeze(0))
            act = int(q.argmax().item())
        self.action_counts[act] += 1

        force = (self._last_mid is not None and
                 abs(mid - self._last_mid) > MID_DRIFT_TICKS * TICK)

        if act == 0 and self._last_bid is not None and not force:
            bid, ask = self._last_bid, self._last_ask
        elif act == 5 and not force:  # POST_AT_TOUCH: bid=best_bid, ask=best_ask
            bid = round((mid - half) / TICK) * TICK
            ask = round((mid + half) / TICK) * TICK
            if ask <= bid:
                ask = bid + TICK
            self.n_cancels        += 1
            self._last_bid         = bid
            self._last_ask         = ask
            self._last_mid         = mid
            self._secs_since_cancel = 0.0
        else:
            alpha = ALPHAS[act - 1] if (act > 0 and not force) else 4.0
            shift = alpha * stats.obi * TICK
            bid   = round((mid - half + shift) / TICK) * TICK
            ask   = round((mid + half + shift) / TICK) * TICK
            if ask <= bid:
                ask = bid + TICK
            self.n_cancels        += 1
            self._last_bid         = bid
            self._last_ask         = ask
            self._last_mid         = mid
            self._secs_since_cancel = 0.0

        return QuoteDecision(
            bid_price=bid, ask_price=ask,
            reservation_price=mid + stats.obi * TICK,
            optimal_spread=ask - bid,
            bid_size=ORDER_SIZE, ask_size=ORDER_SIZE,
        )

    def should_quote(self, inv):
        return (inv < MAX_INV, inv > -MAX_INV)


# ── Rule-based baseline (for comparison) ─────────────────────────────────────

class RuleGatedMM:
    def __init__(self, alpha=4.0, gate=1.5):
        self.alpha = alpha
        self.gate  = gate
        self._last_bid = self._last_ask = self._last_mid = None
        self.n_recomputes = self.n_cancels = 0

    def compute_quotes(self, stats, inv, ts, t_remaining=None, **kw):
        self.n_recomputes += 1
        mid  = stats.mid_price
        half = stats.spread / 2.0 if stats.spread > 0 else 5 * TICK
        shift = self.alpha * stats.obi * TICK
        bid = round((mid - half + shift) / TICK) * TICK
        ask = round((mid + half + shift) / TICK) * TICK
        if ask <= bid:
            ask = bid + TICK

        if self._last_bid is None:
            cancel = True
        else:
            cancel = (abs(bid - self._last_bid) > self.gate * TICK or
                      abs(ask - self._last_ask) > self.gate * TICK or
                      abs(mid - self._last_mid) > MID_DRIFT_TICKS * TICK)
        if cancel:
            self.n_cancels += 1
            self._last_bid, self._last_ask, self._last_mid = bid, ask, mid
        else:
            bid, ask = self._last_bid, self._last_ask

        return QuoteDecision(bid_price=bid, ask_price=ask,
                             reservation_price=mid + shift,
                             optimal_spread=ask - bid,
                             bid_size=ORDER_SIZE, ask_size=ORDER_SIZE)

    def should_quote(self, inv):
        return (inv < MAX_INV, inv > -MAX_INV)


# ── Backtest runner ───────────────────────────────────────────────────────────

def quote_l2(quotes_path: str) -> L2BookTracker:
    df  = pd.read_parquet(quotes_path,
                          columns=["time_exchange", "bid_price", "ask_price",
                                   "bid_size", "ask_size"])
    ts  = df["time_exchange"].values.astype("datetime64[ns]").astype("int64") / 1e9
    bp  = df["bid_price"].values.astype(float)
    ap  = df["ask_price"].values.astype(float)
    bsz = df["bid_size"].values.astype(float)
    asz = df["ask_size"].values.astype(float)
    d   = bsz + asz
    obi = np.where(d > 0, (bsz - asz) / d, 0.0)
    return L2BookTracker([
        BookSnapshot(timestamp=float(ts[i]),
                     best_bid_price=bp[i], best_ask_price=ap[i],
                     best_bid_depth=bsz[i], best_ask_depth=asz[i],
                     obi_l1=obi[i], obi_l3=obi[i], obi_l5=obi[i], obi_l10=obi[i],
                     total_bid_depth=bsz[i], total_ask_depth=asz[i],
                     bid_levels=((bp[i], bsz[i]),), ask_levels=((ap[i], asz[i]),))
        for i in range(len(ts))
    ])


def run_day(strat, date: str, ld: DataLoader) -> dict:
    tr, qt = ld.load_coinapi(str(DATA / f"trades_LINK_{date}.parquet"),
                              str(DATA / f"quotes_LINK_{date}.parquet"))
    qp  = str(DATA / f"quotes_LINK_{date}.parquet")
    l2  = quote_l2(qp)
    om  = OrderManager(maker_fee=0.0, taker_fee=0.0, latency=LATENCY,
                       queue_model="l2")
    om.queue_fraction = QUEUE_FRACTION
    ms  = MarketState(120, 60, 0.9)
    res = Backtest(strat, market_state=ms, order_manager=om,
                   requote_on_fill=True,
                   requote_interval=REQUOTE_INTERVAL,
                   tolerance_ticks=0,
                   tick_size=TICK,
                   verbose=False).run(tr, qt, l2_tracker=l2)
    gross = float(res.metrics.get("total_pnl", 0.0))
    takers = [f for f in om.fills if getattr(f, "is_taker", False)]
    taker_fees = TAKER_FEE * sum(f.quantity * f.price for f in takers)
    maker_fees = MAKER_FEE * sum(f.quantity * f.price for f in om.fills
                                  if not getattr(f, "is_taker", False))
    net = gross - taker_fees - maker_fees
    cr  = strat.n_cancels / max(strat.n_recomputes, 1)
    return dict(date=date, gross=gross, net=net, fills=len(om.fills),
                cancel_rate=cr)


def eval_window(label: str, strategy_fn, dates: list[str], ld: DataLoader) -> dict:
    results = []
    print(f"\n{label} ({len(dates)} days)")
    for i, d in enumerate(dates):
        strat = strategy_fn()
        r = run_day(strat, d, ld)
        results.append(r)
        # Print action dist if RL
        extra = ""
        if hasattr(strat, "action_counts"):
            tot = sum(strat.action_counts) or 1
            pcts = [100 * c / tot for c in strat.action_counts]
            extra = (f"  acts=[H:{pcts[0]:.0f}% a+4:{pcts[1]:.0f}% a+2:{pcts[2]:.0f}% "
                     f"a0:{pcts[3]:.0f}% a-4:{pcts[4]:.0f}% tch:{pcts[5]:.0f}%]")
        print(f"  [{i+1:3}/{len(dates)}] {d}  "
              f"gross={r['gross']:+.2f}  net={r['net']:+.2f}  "
              f"fills={r['fills']}  cancel%={100*r['cancel_rate']:.1f}%{extra}")

    nets   = np.array([r["net"]   for r in results])
    gross  = np.array([r["gross"] for r in results])
    fills  = np.array([r["fills"] for r in results])
    crs    = np.array([r["cancel_rate"] for r in results])
    print(f"  ── {label}  net: {nets.mean():+.2f}±{nets.std():.2f}  "
          f"days+: {100*(nets>0).mean():.0f}%  "
          f"gross: {gross.mean():+.2f}  cancel%: {100*crs.mean():.1f}%")
    return dict(mean_net=float(nets.mean()), std_net=float(nets.std()),
                days_positive_pct=float(100*(nets>0).mean()),
                mean_gross=float(gross.mean()),
                mean_fills=float(fills.mean()),
                mean_cancel_pct=float(100*crs.mean()),
                per_day=[dict(date=r["date"], net=r["net"], gross=r["gross"])
                         for r in results])


def get_dates(months_pattern: str) -> list[str]:
    qt = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "quotes_LINK_*.parquet"))
          if "PERP" not in f}
    tr = {re.search(r"(\d{4}-\d{2}-\d{2})", f).group(1)
          for f in glob.glob(str(DATA / "trades_LINK_*.parquet"))
          if "PERP" not in f}
    return sorted(d for d in qt & tr if re.match(months_pattern, d))


def main():
    # Date windows
    is_dates  = get_dates(r"2026-04-\d{2}")
    oos_dates = [d for d in get_dates(r"2025-0[67]-\d{2}")
                 if "2025-06-11" <= d <= "2025-07-10"]
    # Use 2 fresh-OOS months as spot-check (avoid re-running all 182)
    foos_dates = get_dates(r"2025-1[12]-\d{2}")[:20]  # Nov 2025, 20 days

    print(f"Exp 84 — RL fee-gate controller @ {MAKER_FEE*100:.2f}% maker fee")
    print(f"IS: {len(is_dates)} days  OOS: {len(oos_dates)} days  "
          f"FreshOOS sample: {len(foos_dates)} days")

    # Train
    net = train(is_dates)
    torch.save(net.state_dict(), OUT / "dqn_weights.pt")
    print(f"\nWeights saved → {OUT / 'dqn_weights.pt'}")

    ld = DataLoader()

    rule_fn = lambda: RuleGatedMM(alpha=4.0, gate=1.5)
    rl_fn   = lambda: RLGatedMM(net)

    results = {}
    for window, dates in [("IS_Apr2026", is_dates),
                           ("OOS_JunJul2025", oos_dates),
                           ("FreshOOS_NovDec2025", foos_dates)]:
        results[window] = {}
        results[window]["rule"] = eval_window(
            f"[RULE] {window}", rule_fn, dates, ld)
        results[window]["rl"]   = eval_window(
            f"[RL]   {window}", rl_fn,  dates, ld)

    # Summary table
    print("\n" + "=" * 68)
    print(f"SUMMARY  (maker_fee={MAKER_FEE*100:.2f}%)")
    print("=" * 68)
    print(f"{'Window':<24} {'Strategy':<8} {'Net/day':>9} {'Days+':>7} "
          f"{'Gross/day':>10} {'Cancel%':>8}")
    print("-" * 68)
    for window, v in results.items():
        for tag, r in v.items():
            print(f"  {window:<22} {tag:<8} {r['mean_net']:>+8.2f}  "
                  f"{r['days_positive_pct']:>6.0f}%  "
                  f"{r['mean_gross']:>+9.2f}  "
                  f"{r['mean_cancel_pct']:>7.1f}%")

    out_path = OUT / "rl_fee_gate.json"
    with open(out_path, "w") as fh:
        json.dump({"maker_fee": MAKER_FEE, "results": results}, fh, indent=2)
    print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
