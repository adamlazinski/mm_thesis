"""Diagnostic: trace H(tau) evolution inside ShiftedGLFTNumerical._solve."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from hft_market_maker import ShiftedGLFTNumerical

m = ShiftedGLFTNumerical(min_spread_bps=0.0)
gamma = m.gamma
q_vals = m.q_grid.astype(float) * m.order_size
mid = m.q_max  # index of q=0

for sigma_dollar in (0.0022, 1.2352, 15.389):
    print(f"\n=== sigma_$ = {sigma_dollar} ===")
    H = np.zeros(len(m.q_grid))
    for step in range(m.n_steps):
        dh_b, dh_a = m._neighbor_diffs(H)
        delta_b = m._solve_foc(dh_b, m.A_liq)
        delta_a = m._solve_foc(dh_a, m.A_liq)
        gsb = m._g_star(delta_b, dh_b, m.A_liq)
        gsa = m._g_star(delta_a, dh_a, m.A_liq)
        rhs = 0.5 * sigma_dollar ** 2 * gamma * q_vals ** 2 - (gsb + gsa) / gamma
        H = H - m.dt * rhs

        if step in (0, 1, 2, 5, 10, 50, 100, 599):
            print(f"step={step:4d}  H[0]={H[mid-1]: .6e}  H_mid={H[mid]: .6e}  "
                  f"H[+1]={H[mid+1]: .6e}  dh_b[mid]={dh_b[mid]: .6e}  "
                  f"delta_b[mid]={delta_b[mid]: .6e}  gsb[mid]={gsb[mid]: .6e}  "
                  f"gsb[mid-1]={gsb[mid-1]: .6e}")

    print(f"final delta_bid[mid]={delta_b[mid]/m.tick_size:.4f} ticks, "
          f"delta_bid[mid+1]={delta_b[mid+1]/m.tick_size:.4f} ticks, "
          f"delta_bid[0]={delta_b[0]/m.tick_size:.4f} ticks")
