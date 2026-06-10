"""
Reinforcement Learning Extension
---------------------------------
Replaces the A-S/GLFT quote decision with a learned policy.

Two approaches:
  1. TabularQLearning  — discrete state+action, interpretable baseline
  2. DQNMarketMaker    — PyTorch DQN, continuous state, experience replay

Both share the same action space and state encoder.

Action spaces
-------------
Two named action tables are provided:

  ACTION_PARAMS ("link" default, N=19)
    Designed for LINK/USDT with a 10-tick natural spread.
    Actions 1–4 post INSIDE the market (3–4 ticks from mid vs 5-tick half-spread).
    Actions 8–11 sit AT the market.  Actions 12–18 sit outside.

  BTC_ACTION_PARAMS ("btc", N=19)
    Designed for BTC/USDT with a 1-tick natural spread.
    With mid at X.005 (half-way between ticks):
      bid_ticks=0 → floor(mid)   = natural bid (AT TOUCH)
      ask_ticks=0 → ceil(mid)    = natural ask (AT TOUCH)
      bid_ticks=1 → 1 tick below natural bid (just outside)
    Actions 1–5 are at-touch or just-outside (the critical missing range in exp 46).
    Actions 6–18 extend out to 5 ticks for high-vol or directional regimes.

Each entry: (bid_half_ticks, ask_half_ticks, hold_sec)
bid_half_ticks = 0 means halt (action 0 only) OR at-touch (actions 1+).

  LINK action table (N_ACTIONS = 19)
  ID  Name                bid  ask  hold   Fill regime (LINK, 5-tick half-spread)
  --  ----                ---  ---  ----   ----------------------------------------
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

  BTC action table (N_BTC_ACTIONS = 19)
  ID  Name                bid  ask  hold   Fill regime (BTC, 0.5-tick half-spread)
  --  ----                ---  ---  ----   ----------------------------------------
   0  halt                 —    —   —      no quotes
   1  at_touch_fast        0    0   0.25s  at natural bid/ask, quick repost
   2  at_touch             0    0   0.50s  at natural bid/ask, normal
   3  at_touch_patient     0    0   1.00s  at touch, patient (fewer cancel events)
   4  lean_bid_touch       0    1   0.25s  bid at touch, ask 1-tick out (sell long)
   5  lean_ask_touch       1    0   0.25s  ask at touch, bid 1-tick out (buy short)
   6  near_sym_fast        1    1   0.25s  1 tick outside each side, aggressive
   7  near_sym             1    1   0.50s  1 tick outside each side, normal
   8  near_lean_bid        0    2   0.25s  touch bid, ask 2-out (inventory reduction)
   9  near_lean_ask        2    0   0.25s  touch ask, bid 2-out (inventory reduction)
  10  mid_sym              2    2   0.50s  2 ticks outside, balanced
  11  mid_sym_patient      2    2   1.00s  2 ticks outside, patient
  12  mid_lean_bid         1    3   0.50s  lean sell (tight bid)
  13  mid_lean_ask         3    1   0.50s  lean buy (tight ask)
  14  wide_sym             3    3   1.00s  3 ticks outside each side
  15  wide_sym_patient     3    3   2.00s  3 ticks outside, patient
  16  wide_lean_bid        2    4   1.00s  lean sell, wider spread
  17  wide_lean_ask        4    2   1.00s  lean buy, wider spread
  18  vwide_sym            5    5   2.00s  5 ticks out, tail-event catch

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
# Action 0 is always halt (bid_ticks=0 in the halt slot means no quotes).
# For non-halt actions, bid_ticks=0 means "post at natural bid" (floor of mid).

# LINK action table — calibrated for 10-tick natural spread
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

# BTC action table v2 — wide sweep (5–80 ticks) + lean variants for inventory management.
#
# Design rationale:
#   If BTC fill curve is flat from ~2 ticks (A_mom dominated), fill frequency is constant
#   across all distances. Wider spreads then earn more per fill. The 50–80 tick bins test
#   the "overshoot hypothesis": large BTC moves (~$0.50–$0.80 from mid) may mean-revert,
#   making these fills net-positive.  If exponential holds, those bins simply never fill.
#   Lean variants let the agent learn directional inventory management at each spread level.
#
#   Distance bins and exponential fill estimates (κ=0.31/tick):
#     5t ≈ 21%,  10t ≈ 5%,  20t ≈ 0.2%,  50t ≈ 5e-7,  80t ≈ 5e-11
#   Under flat fill curve: all bins fill at rate A_mom — agent discovers actual economics.
BTC_ACTION_PARAMS: List[Tuple[int, int, float]] = [
    (0,  0,  0.0 ),   #  0: halt
    # Close (5 ticks each side): ~21% exp fill, $0.001 RT on 0.01 BTC
    (5,  5,  0.25),   #  1: close_sym_fast
    (5,  5,  0.50),   #  2: close_sym
    (4,  6,  0.25),   #  3: close_lean_bid     (tighter bid → sell longs)
    (6,  4,  0.25),   #  4: close_lean_ask     (tighter ask → buy shorts)
    (5,  5,  2.00),   #  5: close_patient
    # Mid (10 ticks each side): ~5% exp fill, $0.002 RT
    (10, 10, 0.50),   #  6: mid_sym
    (9,  11, 0.50),   #  7: mid_lean_bid
    (11, 9,  0.50),   #  8: mid_lean_ask
    (10, 10, 2.00),   #  9: mid_patient
    # Wide (20 ticks each side): ~0.2% exp fill, $0.004 RT
    (20, 20, 1.00),   # 10: wide_sym
    (19, 21, 1.00),   # 11: wide_lean_bid
    (21, 19, 1.00),   # 12: wide_lean_ask
    (20, 20, 2.00),   # 13: wide_patient
    # Very-wide (50 ticks each side): ~5e-7 exp fill, $0.010 RT; tests flat-fill hypothesis
    (50, 50, 1.00),   # 14: vwide_sym
    (48, 52, 1.00),   # 15: vwide_lean_bid
    (52, 48, 1.00),   # 16: vwide_lean_ask
    (50, 50, 2.00),   # 17: vwide_patient
    # Extreme (70–80 ticks each side): ~$0.70–$0.80 from mid, overshoot / crash catch
    (70, 70, 2.00),   # 18: xwide_sym         $0.014 RT on 0.01 BTC
    (80, 80, 2.00),   # 19: xxwide_sym        $0.016 RT on 0.01 BTC
    # Inventory-off (asymmetric lean at mid and wide distances)
    (8,  12, 0.50),   # 20: mid_hard_lean_bid   aggressive sell-long
    (12, 8,  0.50),   # 21: mid_hard_lean_ask   aggressive buy-short
    (15, 25, 1.00),   # 22: wide_hard_lean_bid  wide sell-long
    (25, 15, 1.00),   # 23: wide_hard_lean_ask  wide buy-short
    # One-sided quotes: post only one side to limit inventory accumulation.
    # -1 means "suppress this side" (handled in build_quote).
    (5,  -1, 0.50),   # 24: bid_only            bid at 5t, no ask
    (-1, 5,  0.50),   # 25: ask_only            ask at 5t, no bid
    (10, -1, 1.00),   # 26: wide_bid_only       bid at 10t, no ask
]
N_BTC_ACTIONS = len(BTC_ACTION_PARAMS)

BTC_ACTION_NAMES = [
    "halt",
    "close_sym_fast", "close_sym", "close_lean_bid", "close_lean_ask", "close_patient",
    "mid_sym", "mid_lean_bid", "mid_lean_ask", "mid_patient",
    "wide_sym", "wide_lean_bid", "wide_lean_ask", "wide_patient",
    "vwide_sym", "vwide_lean_bid", "vwide_lean_ask", "vwide_patient",
    "xwide_sym", "xxwide_sym",
    "mid_hard_lean_bid", "mid_hard_lean_ask",
    "wide_hard_lean_bid", "wide_hard_lean_ask",
    "bid_only", "ask_only", "wide_bid_only",
]

def make_action_space(
    natural_spread_ticks: int,
    min_delta: int = 0,
    max_delta: Optional[int] = None,
    n_levels: int = 4,
    n_lean: int = 1,
    include_patient: bool = True,
    include_onesided: bool = False,
) -> Tuple[List[Tuple[int, int, float]], List[str]]:
    """
    Build an action table from parameters instead of hardcoding asset-specific values.

    Parameters
    ----------
    natural_spread_ticks : int
        Half-spread of the natural market in ticks. Used as the anchor for
        level spacing. E.g. 5 for LINK (5-tick half-spread), 0 for BTC at-touch.
    min_delta : int
        Minimum half-spread in ticks (0 = at-touch, natural_spread_ticks = at market).
    max_delta : int or None
        Maximum half-spread. Defaults to max(natural_spread_ticks * 3, min_delta + 10).
    n_levels : int
        Number of distance levels between min_delta and max_delta (log-spaced).
    n_lean : int
        Lean variants per symmetric action. 0 = symmetric only; 1 = add lean_bid +
        lean_ask at ±1 tick; 2 = add ±2 tick lean as well.
    include_patient : bool
        Add a patient (2 s hold) variant at each level.
    include_onesided : bool
        Add bid_only / ask_only actions at the tightest level.

    Returns
    -------
    params : list of (bid_ticks, ask_ticks, hold_sec)
    names  : list of str
    """
    if max_delta is None:
        max_delta = max(natural_spread_ticks * 3, min_delta + 10)

    # Log-spaced levels rounded to nearest int, deduplicated
    raw = np.logspace(np.log10(max(min_delta, 1)), np.log10(max_delta), n_levels)
    levels: List[int] = []
    seen = set()
    if min_delta == 0:
        levels.append(0)
        seen.add(0)
    for v in raw:
        iv = int(round(v))
        if iv not in seen:
            levels.append(iv)
            seen.add(iv)

    params: List[Tuple[int, int, float]] = [(0, 0, 0.0)]
    names: List[str] = ["halt"]

    hold_normal = 0.5
    hold_fast   = 0.25
    hold_patient = 2.0

    for d in levels:
        label = f"d{d}"
        # Symmetric fast
        params.append((d, d, hold_fast))
        names.append(f"{label}_sym_fast")
        # Symmetric normal
        params.append((d, d, hold_normal))
        names.append(f"{label}_sym")
        # Lean variants
        for lean in range(1, n_lean + 1):
            params.append((d - lean, d + lean, hold_normal))
            names.append(f"{label}_lean_bid_l{lean}")
            params.append((d + lean, d - lean, hold_normal))
            names.append(f"{label}_lean_ask_l{lean}")
        # Patient
        if include_patient:
            params.append((d, d, hold_patient))
            names.append(f"{label}_patient")

    if include_onesided and levels:
        d0 = levels[0]
        params.append((d0, -1, hold_normal))
        names.append(f"d{d0}_bid_only")
        params.append((-1, d0, hold_normal))
        names.append(f"d{d0}_ask_only")

    return params, names


# ---------------------------------------------------------------------------
# LINK honest expanded action space ("link_honest_xl")
# ---------------------------------------------------------------------------
# For the honest-fill-model RL demonstration (exp 58). Every quoting leg is
# >= 5 ticks from mid (= at-touch on LINK's 10-tick natural spread) or
# suppressed (-1). Rationale: under queue_model='l2' the backtest only assigns
# queue_ahead to quotes at-or-behind the touch — an inside-spread quote gets
# queue_ahead=0 and keeps the first-touch artifact. Excluding inside legs makes
# every fill pass through the real L2 queue.
#
# The space is deliberately LARGE (~3x the original 19-action table): a dense
# distance grid, fast/normal/patient/very-patient holds, soft and hard leans,
# and one-sided quotes — so that a failure to find profit in-sample cannot be
# attributed to a thin action menu.

def _build_link_honest_xl() -> Tuple[List[Tuple[int, int, float]], List[str]]:
    params: List[Tuple[int, int, float]] = [(0, 0, 0.0)]
    names: List[str] = ["halt"]

    # 5 = at-touch (thinnest honestly-priceable level on LINK's 10-tick spread;
    # anything inside re-opens the C30 first-touch artifact). 80/150 reach the
    # deep-reversion zone tested in exp 57.
    levels = [5, 6, 7, 8, 10, 12, 15, 20, 30, 50, 80, 150]
    for d in levels:
        for hold, tag in [(0.25, "fast"), (0.50, "sym"), (2.00, "patient")]:
            params.append((d, d, hold))
            names.append(f"d{d}_{tag}")
    # Very patient at-touch / near
    for d in [5, 10]:
        params.append((d, d, 5.00))
        names.append(f"d{d}_vpatient")
    # Soft leans (+/-2 ticks, min leg stays >= 5)
    for d in [5, 6, 8, 10, 15, 20]:
        params.append((d, d + 2, 0.50))
        names.append(f"d{d}_lean_bid")
        params.append((d + 2, d, 0.50))
        names.append(f"d{d}_lean_ask")
    # Hard leans: tight on the unwind side, far on the accumulating side
    for near, far in [(5, 10), (5, 15), (5, 30)]:
        params.append((near, far, 0.50))
        names.append(f"d{near}_{far}_hard_lean_bid")
        params.append((far, near, 0.50))
        names.append(f"d{near}_{far}_hard_lean_ask")
    # One-sided quotes
    for d in [5, 8, 15]:
        params.append((d, -1, 0.50))
        names.append(f"d{d}_bid_only")
        params.append((-1, d, 0.50))
        names.append(f"d{d}_ask_only")

    assert all(p[0] >= 5 or p[0] == -1 for p in params[1:]), "inside-spread bid leg"
    assert all(p[1] >= 5 or p[1] == -1 for p in params[1:]), "inside-spread ask leg"
    return params, names


LINK_HONEST_XL_PARAMS, LINK_HONEST_XL_NAMES = _build_link_honest_xl()
N_LINK_HONEST_XL_ACTIONS = len(LINK_HONEST_XL_PARAMS)

# Mapping from config "action_space" key to (params, names)
ACTION_SPACES = {
    "link": (ACTION_PARAMS, ACTION_NAMES),
    "btc":  (BTC_ACTION_PARAMS, BTC_ACTION_NAMES),
    "link_honest_xl": (LINK_HONEST_XL_PARAMS, LINK_HONEST_XL_NAMES),
}

# Default hold time if action is halt (how long to stay quiet)
HALT_HOLD_SEC = 0.5


def action_hold(action: int, action_params: List[Tuple[int, int, float]] = None) -> float:
    """Return the hold duration in seconds for a given action index."""
    params = action_params if action_params is not None else ACTION_PARAMS
    if action == 0:
        return HALT_HOLD_SEC
    return params[action][2]


# ---------------------------------------------------------------------------
# State encoder (shared by all agents)
# ---------------------------------------------------------------------------

STATE_DIM = 9  # 6 base + 3 L2 features (obi_l1, obi_l3, depth_imbalance)


def encode_state(
    stats: MicrostructureStats,
    inventory: float,
    max_inventory: float,
    daily_pnl: float,
    daily_loss_limit: float,
    vol_history: deque,
) -> np.ndarray:
    """
    Encode market observables into a normalised 9-dim state vector.

    Dims 0-5: base features (unchanged)
    Dims 6-8: L2 book features (zero if no L2 data loaded)
      6: obi_l1  — top-of-book imbalance [-1, 1]
      7: obi_l3  — 3-level imbalance [-1, 1]
      8: depth_ratio — ask_depth / (bid_depth + ask_depth), [0, 1];
                       > 0.5 = ask-heavy (sell pressure), < 0.5 = bid-heavy
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

    # L2 features — zero when L2 data not available
    obi_l1 = np.clip(stats.obi_l1, -1.0, 1.0)
    obi_l3 = np.clip(stats.obi_l3, -1.0, 1.0)
    total  = stats.bid_depth_touch + stats.ask_depth_touch
    depth_ratio = (stats.ask_depth_touch / total) if total > 0 else 0.5

    return np.array([inv_ratio, vol_ratio, momentum, ofi, spike_ratio, pnl_draw,
                     obi_l1, obi_l3, depth_ratio],
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
    action_params: List[Tuple[int, int, float]] = None,
) -> QuoteDecision:
    """
    Build a QuoteDecision from the action index.

    bid/ask prices are mid ± (N ticks × tick_size), rounded to tick.
    Returns a halt decision (should_quote_bid/ask = False) for action 0.
    Pass action_params to use a non-default action table (e.g. BTC_ACTION_PARAMS).
    """
    params = action_params if action_params is not None else ACTION_PARAMS
    bid_ticks, ask_ticks, _ = params[action]
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

    # bid_ticks < 0 means "suppress bid side" (one-sided quote action).
    # ask_ticks < 0 means "suppress ask side".
    # Use absolute value for price calculation; suppress flag overrides later.
    eff_bid = abs(bid_ticks) if bid_ticks >= 0 else 5  # placeholder price for suppressed side
    eff_ask = abs(ask_ticks) if ask_ticks >= 0 else 5

    bid_price = _floor(mid - eff_bid * tick_size)
    ask_price = _ceil(mid  + eff_ask * tick_size)
    if ask_price <= bid_price:
        ask_price = bid_price + tick_size

    spread_ticks = (abs(bid_ticks) if bid_ticks >= 0 else 0) + (abs(ask_ticks) if ask_ticks >= 0 else 0)
    d = QuoteDecision(
        bid_price=bid_price,
        ask_price=ask_price,
        reservation_price=mid,
        optimal_spread=spread_ticks * tick_size,
        bid_size=order_size,
        ask_size=order_size,
    )
    d.should_quote_bid = (inventory < max_inventory) and (bid_ticks >= 0)
    d.should_quote_ask = (inventory > -max_inventory) and (ask_ticks >= 0)
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
        action_params: List[Tuple[int, int, float]] = None,
    ):
        self.tick_size        = tick_size
        self.order_size       = order_size
        self.max_inventory    = max_inventory
        self.daily_loss_limit = daily_loss_limit
        self.lr               = learning_rate
        self.discount         = discount
        self.epsilon          = epsilon_start
        self.epsilon_end      = epsilon_end
        self.epsilon_decay    = epsilon_decay
        self.inv_penalty      = inventory_penalty
        self._action_params   = action_params if action_params is not None else ACTION_PARAMS
        self._n_actions       = len(self._action_params)

        self.Q = np.zeros((N_STATES, self._n_actions), dtype=np.float64)

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
            action = np.random.randint(self._n_actions)
        else:
            action = int(np.argmax(self.Q[state_idx]))

        self._prev_state_idx = state_idx
        self._prev_action    = action
        self._prev_pnl       = total_pnl

        return build_quote(action, stats, self.tick_size,
                           self.order_size, self.max_inventory, inventory,
                           action_params=self._action_params)

    def select_action(self, state: np.ndarray) -> int:
        """Epsilon-greedy action selection from encoded state vector."""
        state_idx = self._state_index(state)
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)
        if np.random.random() < self.epsilon:
            return np.random.randint(self._n_actions)
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
        action_params: List[Tuple[int, int, float]] = None,
    ):
        if not _TORCH_AVAILABLE:
            raise ImportError("PyTorch required. Install: pip install torch")

        self.tick_size        = tick_size
        self.order_size       = order_size
        self.max_inventory    = max_inventory
        self.daily_loss_limit = daily_loss_limit
        self.discount         = discount
        self.epsilon          = epsilon_start
        self.epsilon_end      = epsilon_end
        self.epsilon_decay    = epsilon_decay
        self.batch_size       = batch_size
        self.target_update    = target_update
        self.inv_penalty      = inventory_penalty
        self.train_mode       = train_mode
        self._action_params   = action_params if action_params is not None else ACTION_PARAMS
        self._n_actions       = len(self._action_params)

        def _net():
            return nn.Sequential(
                nn.Linear(STATE_DIM, hidden_dim), nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim), nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim // 2), nn.ReLU(),
                nn.Linear(hidden_dim // 2, self._n_actions),
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
            return np.random.randint(self._n_actions)
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
                           self.order_size, self.max_inventory, inventory,
                           action_params=self._action_params)

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
