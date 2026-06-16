"""
exact_jump_validation.py
=========================
Closed-form Monte Carlo validation of the T(delta)+B(delta) PnL decomposition,
independent of the discretized synthetic_validation.py engine -- NO tick grid,
NO fixed-dt price path. Each population has its own Poisson clock with EXACT
exponential inter-arrival times; population I's price jump is an EXACT
Brownian increment over that exact elapsed time (sigma*sqrt(dt)*Z). Zero
discretization error by construction.

Population L (uninformed / liquidity takers), rate lambda_L(delta) =
2*A_liq*exp(-kappa*delta) (both sides combined). Each such fill earns exactly
+delta (pure theta -- the reference price didn't move, someone just crossed
our resting quote).
    T(delta) = 2*A_liq*delta*exp(-kappa*delta)

Population I (informed / permanent impact), rate A_inf (constant). At each
event the reference price jumps by xi ~ N(0, sigma^2*dt), dt ~ Exp(A_inf)
(exact). We're filled iff |xi| > delta (the jump overshoots our quote),
earning delta - |xi| (negative = adverse).
    sigma_trade = sigma / sqrt(A_inf),  z = delta / sigma_trade
    B(delta) = 2*A_inf*sigma_trade*[z*Phi(-z) - phi(z)]   (<= 0 always)

Part 1: B(delta) only, sweep z (same sigma=0.20 as the grid_resolution_check
        sweep). Tests whether B(delta) -- as a function of z alone -- is smooth
        and monotonically -> 0 in a CONTINUOUS-price world. If it is, the
        non-monotonic dip seen at z=1.414 (dt=0.005) in grid_resolution_check
        is a tick-quantization artifact of that generator, not a real
        continuous-price effect.

Part 2: T(delta)+B(delta) combined, sweep delta (-> z) at fixed sigma_trade,
        for three values of R = A_liq/A_inf. kappa is fixed so that
        kappa*sigma_trade = K(1) ~= 2.904 (the claimed K(z) minimum at z=1).
        For R = R_crit ~= 1.5, PnL(delta*) should be ~0; for R > R_crit,
        PnL(delta*) > 0; for R < R_crit, PnL(delta*) < 0. Also checks
        delta* > 1/kappa (the FOC result).

Run from master2/ root with .venv activated:
    python experiments/59_synthetic_engine_validation/exact_jump_validation.py
"""
from __future__ import annotations

import numpy as np
from scipy.stats import norm


def g(z):
    return norm.pdf(z) - z * norm.sf(z)  # phi(z) - z*Phi(-z), > 0 for z > 0


def B_closed_form(delta, sigma_trade, A_inf):
    z = delta / sigma_trade
    return 2 * A_inf * sigma_trade * (z * norm.sf(z) - norm.pdf(z))  # = -2*A_inf*sigma_trade*g(z)


def T_closed_form(delta, A_liq, kappa):
    return 2 * A_liq * delta * np.exp(-kappa * delta)


def K_of_z(z):
    return 1.0 / z + norm.sf(z) / g(z)


def simulate_B(delta, sigma, A_inf, n_events, rng):
    """Exact-jump MC for population I. Returns mean PnL rate ($/s)."""
    dt = rng.exponential(1.0 / A_inf, n_events)
    xi = sigma * np.sqrt(dt) * rng.standard_normal(n_events)
    pnl = np.where(np.abs(xi) > delta, delta - np.abs(xi), 0.0)
    return pnl.sum() / dt.sum()


def simulate_T(delta, A_liq, kappa, n_events, rng):
    """Exact-clock MC for population L. Returns mean PnL rate ($/s)."""
    rate = 2 * A_liq * np.exp(-kappa * delta)
    dt = rng.exponential(1.0 / rate, n_events)
    pnl = np.full(n_events, delta)
    return pnl.sum() / dt.sum()


def main():
    rng = np.random.default_rng(0)
    N = 1_000_000

    sigma = 0.20      # same as synthetic_validation BM_SIGMA_HI
    A_inf = 2.0       # informed-fill clock rate (1/s)
    sigma_trade = sigma / np.sqrt(A_inf)

    # ------------------------------------------------------------
    # Part 1: B(delta) only -- sweep z, exact jumps, no tick grid
    # ------------------------------------------------------------
    print("Part 1: B(delta)-only, exact-jump MC (no tick grid, no fixed-dt path)")
    print(f"  sigma={sigma}, A_inf={A_inf}/s -> sigma_trade={sigma_trade:.5f}\n")
    print(f"{'z':>6} {'delta':>9} {'B_mc':>10} {'B_closed':>10} {'rel.err':>8}")
    zs1 = [0.2, 0.316, 0.447, 0.707, 1.000, 1.414, 2.000, 3.000]
    for z in zs1:
        delta = z * sigma_trade
        b_mc = simulate_B(delta, sigma, A_inf, N, rng)
        b_cf = B_closed_form(delta, sigma_trade, A_inf)
        print(f"{z:6.3f} {delta:9.5f} {b_mc:10.5f} {b_cf:10.5f} {abs(b_mc - b_cf) / abs(b_cf):8.3%}")

    # ------------------------------------------------------------
    # Part 2: T(delta)+B(delta) -- sweep delta at fixed sigma_trade,
    # for several R = A_liq/A_inf, with kappa*sigma_trade = K(1)
    # ------------------------------------------------------------
    K1 = K_of_z(1.0)
    kappa = K1 / sigma_trade
    print(f"\nPart 2: T(delta)+B(delta), kappa*sigma_trade = K(1) = {K1:.4f}  "
          f"-> kappa = {kappa:.3f}/$")
    print(f"  1/kappa = ${1 / kappa:.5f}  (z at 1/kappa = {1 / (kappa * sigma_trade):.3f})")

    zs2 = [0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0]
    for R in [1.0, 1.5, 2.5]:
        A_liq = R * A_inf
        print(f"\n  R = A_liq/A_inf = {R}  (A_liq={A_liq}, A_inf={A_inf})")
        print(f"  {'z':>6} {'delta':>9} {'T_mc':>10} {'B_mc':>10} {'PnL_mc':>10} {'PnL_cf':>10}")
        pnl_mc_list, pnl_cf_list = [], []
        for z in zs2:
            delta = z * sigma_trade
            b_mc = simulate_B(delta, sigma, A_inf, N, rng)
            t_mc = simulate_T(delta, A_liq, kappa, N, rng)
            b_cf = B_closed_form(delta, sigma_trade, A_inf)
            t_cf = T_closed_form(delta, A_liq, kappa)
            pnl_mc_list.append(t_mc + b_mc)
            pnl_cf_list.append(t_cf + b_cf)
            print(f"  {z:6.3f} {delta:9.5f} {t_mc:10.5f} {b_mc:10.5f} "
                  f"{t_mc + b_mc:10.5f} {t_cf + b_cf:10.5f}")

        pnl_mc_arr = np.array(pnl_mc_list)
        pnl_cf_arr = np.array(pnl_cf_list)
        i_mc, i_cf = np.argmax(pnl_mc_arr), np.argmax(pnl_cf_arr)
        print(f"  argmax (MC):     z*={zs2[i_mc]:.2f}  delta*=${zs2[i_mc] * sigma_trade:.5f}  "
              f"PnL={pnl_mc_arr[i_mc]:+.5f}  kappa*delta*={kappa * zs2[i_mc] * sigma_trade:.3f}")
        print(f"  argmax (closed): z*={zs2[i_cf]:.2f}  delta*=${zs2[i_cf] * sigma_trade:.5f}  "
              f"PnL={pnl_cf_arr[i_cf]:+.5f}  kappa*delta*={kappa * zs2[i_cf] * sigma_trade:.3f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
