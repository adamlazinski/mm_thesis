"""
calibrate_zeta_glft_correction.py
===================================
Follow-up to Contribution 38 Part F, applying the framework of:

  Barzykin, Bergault, Gueant & Lemmel (2025), "Optimal Quoting under Adverse
  Selection and Price Reading", arXiv:2508.20225.

That paper models adverse selection as a deterministic jump in the reference
price triggered by the market maker's own fill: a fill at distance delta from
mid causes the reference price to move by zeta(delta) AGAINST the new position
(zeta >= 0, non-decreasing in delta). It then derives a first-order (small-eps)
correction to the classical GLFT optimal half-spread:

    delta*_1(q) = delta*_0 + eps * [ (q+1)/(kappa+gamma) * ((gamma+kappa)*zeta(delta*_0)
                                       - zeta'(delta*_0)) ]

For the exponential form zeta(delta) = alpha * exp(beta*delta), this collapses to:

    delta*_1(q) = delta*_0 + (q+1) * (1 - beta/(kappa+gamma)) * zeta(delta*_0)

(derivation: perturb the GLFT FOC F(delta)=lambda'(delta)[1-e^{-gamma(delta+Dtheta)}]
 + gamma*lambda(delta)*e^{-gamma(delta+Dtheta)} = 0 by replacing the fill-exponent
 delta -> delta - (q+1)*zeta(delta); implicit-function theorem at eps=0 gives the
 expression above. At q=0, zeta=0 this reduces exactly to delta*_0 = (1/gamma)
 ln(1+gamma/kappa), GLFT's own AS term -- a useful sanity check.)

This script:
  1. Re-detects fills in exp 64's _view.parquet (11 days) as in Part F, but now
     also records delta = (ask-bid)/2 (the quoted half-spread = resting distance
     from mid) at fill time, alongside the forward markout at k=1 (0.6s) and
     k=20 (12s) steps.
  2. Reports zeta_obs = E[markout | fill] at both horizons (pooled, both sides,
     sign-flipped to a common "adverse magnitude >= 0" convention).
  3. Bins fills by delta and fits log(markout) ~ beta*delta (OLS on bin means) as
     an empirical (exploratory, regime-confounded -- see caveat in output) zeta(delta).
  4. Computes delta*_0 = (1/gamma) ln(1+gamma/kappa) from the exp 64 calibration
     (gamma=30, kappa=239/$) and evaluates delta*_1/delta*_0 for q=0 (flat ->
     just-filled), both with beta=0 (conservative, "slow signal" limit) and with
     the fitted beta.

Run from master2/ root with .venv activated:
    python scripts/calibrate_zeta_glft_correction.py
"""

from __future__ import annotations

import glob

import numpy as np
import pandas as pd

RESULTS_DIR = "experiments/64_glft_calibrated/results"
GAMMA = 30.0       # exp 64 config: gamma
KAPPA = 239.0      # exp 64 config: glft_kappa, units $^-1 (239/$ = 2.39/tick)
TICK = 0.01

HORIZONS = {"0.6s": 1, "12s": 20}

files = sorted(glob.glob(f"{RESULTS_DIR}/*_view.parquet"))
print(f"Found {len(files)} days\n")

deltas = []
markouts = {h: [] for h in HORIZONS}

for f in files:
    df = pd.read_parquet(f)
    close = df["close"].values
    bid = df["bid"].values
    ask = df["ask"].values
    dinv = df["inv"].diff().values
    n = len(df)

    max_k = max(HORIZONS.values())
    buy_idx = np.where(dinv > 5e-4)[0]
    sell_idx = np.where(dinv < -5e-4)[0]
    buy_idx = buy_idx[buy_idx + max_k < n]
    sell_idx = sell_idx[sell_idx + max_k < n]

    half_spread = (ask - bid) / 2.0  # delta = resting distance from mid, in $

    for h, k in HORIZONS.items():
        # "adverse magnitude" convention (zeta >= 0):
        #  buy fill : mid falling afterwards is adverse  -> close[t]-close[t+k]
        #  sell fill: mid rising afterwards is adverse   -> close[t+k]-close[t]
        mk_b = close[buy_idx] - close[buy_idx + k]
        mk_s = close[sell_idx + k] - close[sell_idx]
        markouts[h].append(np.concatenate([mk_b, mk_s]))

    d_b = half_spread[buy_idx]
    d_s = half_spread[sell_idx]
    deltas.append(np.concatenate([d_b, d_s]))

deltas = np.concatenate(deltas)
for h in HORIZONS:
    markouts[h] = np.concatenate(markouts[h])

n_fills = len(deltas)
print(f"Total fills: {n_fills:,}")

# ------------------------------------------------------------------
# 1. zeta_obs = E[markout] pooled, at each horizon
# ------------------------------------------------------------------
print("\nPooled E[markout] (= empirical zeta, '$' price-jump units):")
for h in HORIZONS:
    print(f"  {h:>5}: zeta_obs = ${markouts[h].mean():.4f}  "
          f"(std=${markouts[h].std():.4f})")

print(f"\nQuoted half-spread (delta) at fill time:")
print(f"  mean=${deltas.mean():.5f} ({deltas.mean()/TICK:.2f} ticks)  "
      f"median=${np.median(deltas):.5f} ({np.median(deltas)/TICK:.2f} ticks)  "
      f"[{deltas.min()/TICK:.2f}, {deltas.max()/TICK:.2f}] ticks")

# ------------------------------------------------------------------
# 2. Bin by delta, fit log(markout_0.6s) ~ beta*delta  (exploratory)
# ------------------------------------------------------------------
NBINS = 10
quantiles = np.linspace(0, 1, NBINS + 1)
edges = np.quantile(deltas, quantiles)
edges[0] -= 1e-12
bin_idx = np.digitize(deltas, edges) - 1
bin_idx = np.clip(bin_idx, 0, NBINS - 1)

print(f"\nBinned by delta (quoted half-spread), {NBINS} quantile bins "
      f"-- {'0.6s':>8} / {'12s':>8} markout:")
bin_d, bin_m06, bin_n = [], [], []
for b in range(NBINS):
    mask = bin_idx == b
    if mask.sum() < 100:
        continue
    d_mean = deltas[mask].mean()
    m06 = markouts["0.6s"][mask].mean()
    m12 = markouts["12s"][mask].mean()
    bin_d.append(d_mean)
    bin_m06.append(m06)
    bin_n.append(int(mask.sum()))
    print(f"  delta~{d_mean/TICK:7.2f}t  n={mask.sum():7d}   "
          f"markout_0.6s=${m06:8.4f}   markout_12s=${m12:8.4f}")

bin_d = np.array(bin_d)
bin_m06 = np.array(bin_m06)
bin_m12 = np.array([markouts["12s"][bin_idx == b].mean()
                     for b in range(NBINS) if (bin_idx == b).sum() >= 100])

# The lowest-delta bin sits almost exactly at delta*_0 (~0.39t vs 0.394t) --
# the most direct (non-extrapolated, non-confounded-by-vol-regime) estimate
# of zeta(delta*_0).
zeta_direct_06, zeta_direct_12 = bin_m06[0], bin_m12[0]
delta_direct = bin_d[0]
n_direct = bin_n[0]
valid = bin_m06 > 0
log_m = np.log(bin_m06[valid])
A = np.vstack([bin_d[valid], np.ones(valid.sum())]).T
beta_fit, log_alpha_fit = np.linalg.lstsq(A, log_m, rcond=None)[0]
alpha_fit = np.exp(log_alpha_fit)
pred = A @ np.array([beta_fit, log_alpha_fit])
ss_res = np.sum((log_m - pred) ** 2)
ss_tot = np.sum((log_m - log_m.mean()) ** 2)
r2 = 1 - ss_res / ss_tot
print(f"\nFit zeta(delta) = alpha*exp(beta*delta) on bin means (0.6s markout):")
print(f"  alpha={alpha_fit:.5f}  beta={beta_fit:.3f} $^-1  (R^2={r2:.3f})")
print(f"  [CAVEAT: in exp 64 (kappa_from_stats=false), delta is itself a "
      f"deterministic function of sigma_$ (Part D table) -- delta and the "
      f"vol regime are collinear here, so beta partly reflects 'markout grows "
      f"with vol', not a clean structural zeta(delta) at fixed sigma. Reported "
      f"as exploratory, secondary to the beta=0 bound below.]")

# ------------------------------------------------------------------
# 3. delta*_0 from calibration, and the first-order correction ratio
# ------------------------------------------------------------------
delta0 = (1 / GAMMA) * np.log(1 + GAMMA / KAPPA)
print(f"\ndelta*_0 = (1/gamma) ln(1+gamma/kappa) = ${delta0:.6f}  "
      f"({delta0/TICK:.3f} ticks)   [gamma={GAMMA}, kappa={KAPPA}/$]")
print(f"  (cf. Part D's 10th-percentile-sigma GLFT half-spread: 0.412 ticks --"
      f" consistent, this is the sigma->0 limit of that table)")

print(f"\nFirst-order correction delta*_1(q=0) = (1 - beta/(kappa+gamma)) * "
      f"zeta(delta*_0),  vs delta*_0:")

for h in HORIZONS:
    zeta_obs = markouts[h].mean()
    # conservative bound: beta=0 ("slow signal" limit) -> zeta(delta*_0)=zeta_obs
    d1_cons = zeta_obs
    ratio_cons = d1_cons / delta0
    print(f"\n  Using zeta_obs[{h}] = ${zeta_obs:.4f}:")
    print(f"    beta=0 (conservative): delta*_1 = ${d1_cons:.4f}   "
          f"=> delta*_1/delta*_0 = {ratio_cons:,.1f}x")

# fitted-beta case, using the 0.6s zeta evaluated at delta*_0 via the fit
zeta_at_delta0 = alpha_fit * np.exp(beta_fit * delta0)
factor = 1 - beta_fit / (KAPPA + GAMMA)
d1_fit = factor * zeta_at_delta0
ratio_fit = d1_fit / delta0
print(f"\n  Using fitted (alpha,beta) at delta*_0 (zeta(delta*_0)=${zeta_at_delta0:.4f}, "
      f"factor=(1-beta/(kappa+gamma))={factor:.3f}):")
print(f"    delta*_1 = ${d1_fit:.4f}   => delta*_1/delta*_0 = {ratio_fit:,.1f}x")

# ------------------------------------------------------------------
# 4. "Direct" estimate: lowest-delta bin sits at delta ~ delta*_0
#    (~0.39t vs 0.394t) -- no extrapolation, no vol-regime confound,
#    n=74,284 fills. zeta(delta*_0) ~ zeta_direct (beta irrelevant
#    since we're evaluating exactly at delta*_0).
# ------------------------------------------------------------------
print(f"\n  Most direct estimate (fills at delta~{delta_direct/TICK:.2f}t, "
      f"~= delta*_0={delta0/TICK:.3f}t, n={n_direct:,}):")
for h, zeta_direct in (("0.6s", zeta_direct_06), ("12s", zeta_direct_12)):
    d1_direct = zeta_direct
    ratio_direct = d1_direct / delta0
    print(f"    zeta_direct[{h}] = ${zeta_direct:.4f}  ->  delta*_1 = ${d1_direct:.4f}   "
          f"=> delta*_1/delta*_0 = {ratio_direct:,.1f}x")

print("\nDone.")
