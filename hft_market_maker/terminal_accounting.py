"""
terminal_accounting.py
======================
Average-cost position accounting with an honest terminal treatment.

Motivation (thesis Ch3 §7, rule on terminal marks; Ch5 §5, the third mirage).
An inventory-aware round-trip simulator that ends the day with an open position
has to value it somehow. Valuing it at the final *mid* credits the simulator
with half a spread it never earned, on a position it never closed. On the thin
books of Ch8 the residual sits at or near the inventory cap on most days, so the
choice is not cosmetic and must be reported rather than assumed away.

This module books P&L on matched volume only, and reports the residual twice:

    pnl_realized     matched volume, average-cost basis. Banked.
    unrealized_mid   residual marked at the final mid.      Optimistic.
    unrealized_liq   residual crossed out at the final touch (bid if long, ask
                     if short).                              Bankable.

By construction `pnl_realized + unrealized_mid` equals the naive
`cash + inv * final_mid`, so the optimistic number remains reproducible and the
difference between the two treatments is explicit.
"""
from __future__ import annotations


def book(inv: float, avg_px: float, dq: float, px: float):
    """
    Average-cost position update for a signed fill.

    inv     current position in units (+ long, - short)
    avg_px  average cost basis of that position (0.0 when flat)
    dq      signed fill size in units (+ bought, - sold)
    px      fill price

    Returns (inv', avg_px', realized_delta). A fill in the direction of the
    position moves the basis and books nothing; a fill against it books
    realized P&L on the overlapping units and, if it flips the sign, re-bases
    the remainder at the fill price.
    """
    if dq == 0.0:
        return inv, avg_px, 0.0
    if inv == 0.0 or (inv > 0) == (dq > 0):
        new_inv = inv + dq
        avg = (avg_px * inv + px * dq) / new_inv if new_inv != 0.0 else 0.0
        return new_inv, avg, 0.0
    closed = min(abs(inv), abs(dq))
    realized = closed * (px - avg_px) * (1.0 if inv > 0 else -1.0)
    new_inv = inv + dq
    if new_inv == 0.0:
        return 0.0, 0.0, realized
    if (new_inv > 0) != (inv > 0):
        return new_inv, px, realized        # flipped: new basis is the fill
    return new_inv, avg_px, realized        # partial close: basis unchanged


def terminal(cash: float, inv: float, avg_px: float, realized: float,
             final_bid: float, final_ask: float):
    """
    Close out an open position two ways and return the comparison.

    `final_bid`/`final_ask` are the last observed touch — the only book the
    simulator can claim to see. A long exits at the bid, a short at the ask.
    """
    final_mid = (final_bid + final_ask) / 2.0
    exit_px = final_bid if inv > 0 else (final_ask if inv < 0 else final_mid)
    unreal_mid = inv * (final_mid - avg_px)
    unreal_liq = inv * (exit_px - avg_px)
    naive = cash + inv * final_mid              # == realized + unreal_mid
    return {
        "pnl_realized": realized,
        "unrealized_mid": unreal_mid,
        "unrealized_liq": unreal_liq,
        "gross_pnl": naive,                     # mid-marked (optimistic)
        "gross_pnl_liq": realized + unreal_liq,  # liquidated (bankable)
        "liq_haircut_usd": unreal_mid - unreal_liq,
        "end_inv_usd": inv * final_mid,
        "final_spread_bps": (1e4 * (final_ask - final_bid) / final_mid
                             if final_mid else None),
        "mid_mark_identity_err": abs(naive - (realized + unreal_mid)),
    }


def bps_split(res: dict, notional: float) -> dict:
    """Express the terminal split in bps of maker notional."""
    if not notional:
        return {}
    b = lambda x: round(1e4 * x / notional, 3)
    return {"rt_bps_gross": b(res["gross_pnl"]),
            "rt_bps_liq": b(res["gross_pnl_liq"]),
            "rt_bps_realized": b(res["pnl_realized"]),
            "rt_bps_unrealized_mid": b(res["unrealized_mid"]),
            "rt_bps_unrealized_liq": b(res["unrealized_liq"])}
