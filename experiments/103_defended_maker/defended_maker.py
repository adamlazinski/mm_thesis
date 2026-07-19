"""
defended_maker.py
=================
Exp 103 — The one affirmative maker configuration the results map does not rule
out: quote both sides of HL_LINK (the only measured book whose adverse-selection
horizon is seconds, not milliseconds — exp 93: 3.4s, realized@1s positive) at a
rebate-tier venue, defended by three signals that are each *free* when used to
pull a quote (C57: gating works, crossing doesn't):

  A  consensus gate   leader-vs-HL dev (exp 99 series): dev > gate => price
                      about to rise => pull the ask (it would sell into the
                      rise); symmetric for the bid.
  W  withdrawal gate  one-sided touch collapse (exp 102 detector): other
                      makers pulled a side => pull ours too, hold GATE_HOLD_S.
  T  toxic-tier gate  informed-set signed-flow (exp 101 series, trained on the
                      prior day): toxic tier is buying => pull the ask.

Fill simulation (exp 100 machinery, project-standard): we join the prevailing
touch on both (ungated) sides continuously; a tape trade strictly through our
price fills at weight 1.0, at our price at weight qf=0.5. Accounting is the
C59-family per-fill realized half-spread at horizons (mark-to-mid diagnostic —
the C60 caveat applies; on a book with a 3.4s horizon and two-sided quoting the
passive exit assumption is at its most defensible, but an inventory-aware
round-trip sim remains the confirmation step). Net = realized + maker fee tier
(HL: +1.5bps base fee, 0.0 mid, -0.3 rebate at top tier).

Ablation: none / A / W / T / A+W / A+W+T.

Run: python experiments/103_defended_maker/defended_maker.py \
        --train 2026-07-15 --date 2026-07-16 --asset HL_LINK --leader CB_LINK
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "live" / "processed"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)

QF = 0.5
HORIZONS = (1.0, 5.0, 30.0)
MAKER_FEES_BPS = (1.5, 0.0, -0.3)
CAP_USD = 1_000.0
QUOTE_TOL_S = 5.0

CONS_GATE_BPS = 2.0       # A: |dev| above this gates the exposed side
WD_HOLD_S = 5.0           # W: gate hold after a withdrawal event
TOX_Q = 0.95              # T: train-day quantile of |S| -> gate bar
TOX_TOP_K = 100
TOX_MIN_FILLS = 10        # LINK has fewer traders than BTC
TOX_SCORE_H = 60.0
TOX_WIN_S = 30.0


def _mod(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def load_quotes(asset, date):
    q = pd.read_parquet(PROC / f"quotes_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    q["mid"] = (q["bid_price"] + q["ask_price"]) / 2.0
    t = q["time_exchange"].astype("int64").to_numpy() / 1e9
    keep = np.concatenate([[True], np.diff(t) > 0])
    return q[keep].reset_index(drop=True)


def load_trades(asset, date):
    t = pd.read_parquet(PROC / f"trades_{asset}_{date}.parquet").sort_values(
        "time_exchange").reset_index(drop=True)
    t["ts"] = t["time_exchange"].astype("int64").to_numpy() / 1e9
    t["d"] = np.where(t["taker_side"].str.upper() == "BUY", 1.0, -1.0)
    t["usd"] = t["price"] * t["size"]
    return t


def interval_state(ev_times, hold_s, sides):
    """(times, sides) of gate events -> sorted arrays for asof state checks."""
    order = np.argsort(ev_times)
    return np.asarray(ev_times)[order], np.asarray(sides)[order]


def gated_at(t, ev_t, ev_s, hold_s, side):
    """Is `side` (+1 ask / -1 bid) gated at time t by any event within hold?"""
    i = np.searchsorted(ev_t, t, side="right") - 1
    while i >= 0 and t - ev_t[i] <= hold_s:
        if ev_s[i] == side:
            return True
        i -= 1
    return False


FILL_CAP_USD = 500.0      # per-fill notional clip (inventory mode)
MAX_INV_USD = 2_000.0     # pull the loading side beyond this exposure


def inventory_sim(tt, tpx, tsz, tbuy, tusd, i_q, qt, qb, qa, qm,
                  gates, qf=QF):
    """
    Round-trip P&L: maintain position; join both touches unless gated or
    inventory-capped; fills at qf weight; mark to mid continuously.
    Returns dict with gross P&L (fee-free), maker notional, inventory stats.
    """
    eps = 1e-9
    cash = 0.0; inv = 0.0
    notional = 0.0; n_fills = 0.0
    max_abs_inv_usd = 0.0
    min_eq = np.inf; max_eq = -np.inf
    for k in range(len(tt)):
        iq = i_q[k]
        if iq < 0 or (tt[k] - qt[iq]) > QUOTE_TOL_S:
            continue
        mid = qm[iq]
        inv_usd = inv * mid
        if tbuy[k]:
            # taker BUY hits our ask (we sell) — skip if short-capped or gated
            if inv_usd <= -MAX_INV_USD or any(g(tt[k], 1) for g in gates):
                pass
            else:
                if tpx[k] > qa[iq] + eps:
                    w = 1.0
                elif abs(tpx[k] - qa[iq]) <= eps * max(tpx[k], 1):
                    w = qf
                else:
                    w = 0.0
                if w > 0:
                    fill_usd = min(tusd[k], FILL_CAP_USD) * w
                    units = fill_usd / tpx[k]
                    inv -= units; cash += fill_usd
                    notional += fill_usd; n_fills += w
        else:
            if inv_usd >= MAX_INV_USD or any(g(tt[k], -1) for g in gates):
                pass
            else:
                if tpx[k] < qb[iq] - eps:
                    w = 1.0
                elif abs(tpx[k] - qb[iq]) <= eps * max(tpx[k], 1):
                    w = qf
                else:
                    w = 0.0
                if w > 0:
                    fill_usd = min(tusd[k], FILL_CAP_USD) * w
                    units = fill_usd / tpx[k]
                    inv += units; cash -= fill_usd
                    notional += fill_usd; n_fills += w
        eq = cash + inv * qm[iq]
        min_eq = min(min_eq, eq); max_eq = max(max_eq, eq)
        max_abs_inv_usd = max(max_abs_inv_usd, abs(inv * qm[iq]))
    final = cash + inv * qm[-1]
    return {"gross_pnl": final, "maker_notional": notional,
            "weighted_fills": n_fills, "max_abs_inv_usd": max_abs_inv_usd,
            "end_inv_usd": inv * qm[-1], "min_equity": min_eq,
            "max_equity": max_eq}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--asset", default="HL_LINK")
    ap.add_argument("--leader", default="CB_LINK")
    ap.add_argument("--inventory", action="store_true",
                    help="run the inventory-aware round-trip sim (bankability)")
    ap.add_argument("--qf", type=float, default=QF)
    args = ap.parse_args()

    ol = _mod("ol", "experiments/99_oracle_lag/oracle_lag.py")
    wl = _mod("wl", "experiments/102_withdrawal_lead/withdrawal_lead.py")
    tb = _mod("tb", "experiments/101_toxic_burst/toxic_burst.py")

    q = load_quotes(args.asset, args.date)
    tr = load_trades(args.asset, args.date)
    mid0 = float(np.median(q["mid"]))
    qt = q["time_exchange"].astype("int64").to_numpy() / 1e9
    qb = q["bid_price"].to_numpy(); qa = q["ask_price"].to_numpy()
    qm = q["mid"].to_numpy()
    day_h = (qt[-1] - qt[0]) / 3600

    # ── gate A: consensus dev series (skipped if no leader venue) ─────────────
    have_leader = (PROC / f"quotes_{args.leader}_{args.date}.parquet").exists()
    if have_leader:
        lead_q = ol.load_quotes(args.leader, args.date)
        tl = lead_q["time_exchange"].astype("int64").to_numpy() / 1e9
        k_l = (tl >= qt[0]) & (tl <= qt[-1])
        td, dv = ol.dev_series(tl[k_l], lead_q["mid"].to_numpy()[k_l], qt, qm)
        cons_thr = CONS_GATE_BPS * 1e-4 * mid0

        def gate_A(t, side):
            i = np.searchsorted(td, t, side="right") - 1
            if i < 0:
                return False
            d = dv[i]
            # dev>0: HL below consensus, price about to rise -> pull ask (side=+1)
            return (d > cons_thr and side == 1) or (d < -cons_thr and side == -1)
    else:
        def gate_A(t, side):
            return False

    # ── gate W: withdrawal events (exp 102 detector) ─────────────────────────
    wd_ev = wl.find_withdrawals(q)      # (t, sgn): sgn=+1 asks pulled (up)
    wd_t = np.array([e[0] for e in wd_ev])
    wd_s = np.array([e[1] for e in wd_ev])   # +1 => pull our ask

    def gate_W(t, side):
        i = np.searchsorted(wd_t, t, side="right") - 1
        while i >= 0 and t - wd_t[i] <= WD_HOLD_S:
            if wd_s[i] == side:
                return True
            i -= 1
        return False

    # ── gate T: toxic-tier flow (exp 101 series, trained on prior day) ──────
    tb.SCORE_H = TOX_SCORE_H
    tb.MIN_FILLS = TOX_MIN_FILLS
    tb.WINDOW_S = TOX_WIN_S
    tr_train = load_trades(args.asset, args.train)
    q_train = load_quotes(args.asset, args.train)
    g = tb.wallet_scores(tr_train, q_train)
    gk = g[g["count"] >= TOX_MIN_FILLS].sort_values("mean", ascending=False)
    informed = set(gk.head(TOX_TOP_K).index)
    ts_tox_tr, S_tr = tb.burst_series(tr_train, informed)
    tox_bar = (float(np.quantile(np.abs(S_tr), TOX_Q)) if len(S_tr) else np.inf)
    ts_tox, S_tox = tb.burst_series(tr, informed)

    def gate_T(t, side):
        i = np.searchsorted(ts_tox, t, side="right") - 1
        if i < 0 or (t - ts_tox[i]) > TOX_WIN_S:
            return False
        s = S_tox[i]
        # toxic tier buying (s>0): price rising -> pull ask
        return (s > tox_bar and side == 1) or (s < -tox_bar and side == -1)

    print(f"=== {args.asset} {args.date}  ({day_h:.1f}h)  leader={args.leader}")
    print(f"  gates: A |dev|>{CONS_GATE_BPS}bps  W hold={WD_HOLD_S}s "
          f"({len(wd_ev)} events)  T |S|>${tox_bar:,.0f} "
          f"(informed={len(informed)}, train q{TOX_Q})")

    # ── fill simulation over the tape ────────────────────────────────────────
    tt = tr["ts"].to_numpy(); tpx = tr["price"].to_numpy()
    tsz = tr["size"].to_numpy(); tbuy = tr["d"].to_numpy() > 0
    tusd = tr["usd"].to_numpy()
    i_q = np.searchsorted(qt, tt, side="right") - 1
    ok = i_q >= 0
    eps = 1e-9

    if args.inventory:
        out = {"asset": args.asset, "date": args.date, "mode": "inventory",
               "qf": args.qf, "fill_cap_usd": FILL_CAP_USD,
               "max_inv_usd": MAX_INV_USD, "day_h": day_h, "configs": {}}
        for name, gates in [("none", []), ("A+W", [gate_A, gate_W])]:
            r = inventory_sim(tt, tpx, tsz, tbuy, tusd, i_q, qt, qb, qa, qm,
                              gates, qf=args.qf)
            scale = 24 / day_h
            r["gross_pnl_day"] = round(r["gross_pnl"] * scale, 2)
            r["net_pnl_day"] = {
                f"fee_{f:g}": round((r["gross_pnl"] - f * 1e-4 * r["maker_notional"])
                                    * scale, 2)
                for f in MAKER_FEES_BPS}
            r["rt_bps_gross"] = round(1e4 * r["gross_pnl"] / r["maker_notional"], 3) \
                if r["maker_notional"] else None
            out["configs"][name] = r
            print(f"  INV {name:5s} qf={args.qf:g}: gross={r['gross_pnl_day']:+9.2f}/day "
                  f"({r['rt_bps_gross']:+.2f}bps of ${r['maker_notional']:,.0f}) "
                  f"net: base={r['net_pnl_day']['fee_1.5']:+8.2f} "
                  f"zero={r['net_pnl_day']['fee_0']:+8.2f} "
                  f"rebate={r['net_pnl_day']['fee_-0.3']:+8.2f}  "
                  f"max|inv|=${r['max_abs_inv_usd']:,.0f} end=${r['end_inv_usd']:+,.0f}")
        tag = f"{args.asset}_{args.date}_inv_qf{args.qf:g}"
        with open(OUT / f"defended_maker_{tag}.json", "w") as fh:
            json.dump(out, fh, indent=2)
        print(f"Saved -> {OUT}/defended_maker_{tag}.json")
        return

    # horizon mids per trade (shared across configs)
    mid_h = {}
    for h in HORIZONS:
        j = np.searchsorted(qt, tt + h, side="right") - 1
        good = (j >= 0) & (j < len(qt))
        mh = np.full(len(tt), np.nan)
        mh[good] = qm[j[good]]
        mid_h[h] = mh

    configs = {"none": [], "A": [gate_A], "W": [gate_W], "T": [gate_T],
               "A+W": [gate_A, gate_W], "A+W+T": [gate_A, gate_W, gate_T]}
    out = {"asset": args.asset, "date": args.date, "train": args.train,
           "leader": args.leader, "day_h": day_h, "n_wd_events": len(wd_ev),
           "tox_bar_usd": tox_bar, "configs": {}}

    for name, gates in configs.items():
        w_arr = np.zeros(len(tt))      # fill weight per tape trade
        side_arr = np.zeros(len(tt))   # +1 we sold (ask filled), -1 we bought
        for k in range(len(tt)):
            if not ok[k]:
                continue
            iq = i_q[k]
            if (tt[k] - qt[iq]) > QUOTE_TOL_S:
                continue
            if tbuy[k]:
                # taker BUY at/above our ask (we quote at the touch qa)
                if tpx[k] > qa[iq] + eps:
                    w = 1.0
                elif abs(tpx[k] - qa[iq]) <= eps * max(tpx[k], 1):
                    w = QF
                else:
                    continue
                side = 1
            else:
                if tpx[k] < qb[iq] - eps:
                    w = 1.0
                elif abs(tpx[k] - qb[iq]) <= eps * max(tpx[k], 1):
                    w = QF
                else:
                    continue
                side = -1
            if any(gfn(tt[k], side) for gfn in gates):
                continue
            w_arr[k] = w
            side_arr[k] = side

        m = w_arr > 0
        n_wfills = float(w_arr[m].sum())
        notion = np.minimum(tusd[m] * w_arr[m], CAP_USD)
        rec = {"weighted_fills": round(n_wfills, 1),
               "fills_per_day": round(n_wfills * 24 / day_h, 1)}
        for h in HORIZONS:
            mh = mid_h[h][m]
            good = ~np.isnan(mh)
            if good.sum() == 0:
                continue
            # maker realized: we sold at tpx (side=+1) => tpx - mid_h
            rh = 1e4 * side_arr[m][good] * (tpx[m][good] - mh[good]) / mid0
            wgt = w_arr[m][good]
            rec[f"rh_{h:g}s_bps"] = float(np.average(rh, weights=wgt))
        rh5 = rec.get("rh_5s_bps")
        if rh5 is not None:
            rec["net_5s_bps"] = {f"fee_{f:g}": round(rh5 - f, 3)
                                 for f in MAKER_FEES_BPS}
            # PnL/day at cap, top-tier rebate
            good = ~np.isnan(mid_h[5.0][m])
            rh = 1e4 * side_arr[m][good] * (tpx[m][good] - mid_h[5.0][m][good]) / mid0
            pnl = float(np.sum(notion[good] * (rh * 1e-4 + 0.3e-4)))
            rec["pnl_day_rebate_cap1k"] = round(pnl * 24 / day_h, 2)
        out["configs"][name] = rec
        nets = rec.get("net_5s_bps", {})
        print(f"  {name:6s} fills/day={rec['fills_per_day']:8.1f}  "
              f"rh@1s={rec.get('rh_1s_bps', float('nan')):+6.3f}  "
              f"rh@5s={rec.get('rh_5s_bps', float('nan')):+6.3f}  "
              f"rh@30s={rec.get('rh_30s_bps', float('nan')):+6.3f}  "
              f"net@5s: base={nets.get('fee_1.5')}  rebate={nets.get('fee_-0.3')}  "
              f"pnl/day(reb,$1k)={rec.get('pnl_day_rebate_cap1k')}")

    tag = f"{args.asset}_{args.date}"
    with open(OUT / f"defended_maker_{tag}.json", "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"Saved -> {OUT}/defended_maker_{tag}.json")


if __name__ == "__main__":
    main()
