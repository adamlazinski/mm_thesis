"""
myopic_objective.py
====================
Explore the gamma -> 0 (risk-neutral) limit of the optimal-spread problem:

    delta* = argmax_{delta >= 0}  lambda(delta) * delta

for the calibrated two-component intensity lambda(delta) = A_liq*exp(-kappa*delta)
+ max(a - b*delta, 0). This is "maximize expected profit per tick" -- no sigma,
no gamma, no inventory; a single number computed once.

Reports:
  - the global argmax of f(delta) = lambda(delta)*delta
  - the argmax restricted to the A_liq (exponential) component alone
  - the argmax restricted to the floor (a - b*delta) component alone
  - how much each component contributes to f at the global argmax

Run from master2/ root with .venv activated:
    python scripts/myopic_objective.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from hft_market_maker import ShiftedGLFTNumerical

m = ShiftedGLFTNumerical(min_spread_bps=0.0)  # calibrated defaults
TICK = m.tick_size

cutoff = m.a / m.b
print(f"kappa = {m.kappa:.4f} /$  (cutoff = a/b = {cutoff:.4f} $ = {cutoff / TICK:.1f} ticks)")
print(f"A_liq = {m.A_liq}, a = {m.a}, b = {m.b:.6f}")
print()

delta = np.linspace(1e-6, cutoff, 2_000_001)
lam, _, _ = m._intensity_and_derivs(delta, m.A_liq)
exp_term = m.A_liq * np.exp(-m.kappa * delta)
floor_term = np.clip(m.a - m.b * delta, 0.0, None)

f_total = lam * delta
f_exp = exp_term * delta
f_floor = floor_term * delta

for name, f in (("full lambda", f_total), ("A_liq exp only", f_exp), ("floor only", f_floor)):
    i = np.argmax(f)
    print(f"{name:>16}: delta* = {delta[i]:.6f} $ = {delta[i] / TICK:8.2f} ticks   "
          f"f(delta*) = {f[i]:.6f}")

i_star = np.argmax(f_total)
d_star = delta[i_star]
print()
print(f"At the global argmax delta*={d_star:.4f}$ ({d_star/TICK:.1f} ticks):")
print(f"  A_liq*exp(-kappa*delta*)        = {exp_term[i_star]:.6e}  "
      f"({100*exp_term[i_star]/lam[i_star]:.4f}% of lambda)")
print(f"  max(a-b*delta*,0)               = {floor_term[i_star]:.6e}  "
      f"({100*floor_term[i_star]/lam[i_star]:.4f}% of lambda)")

# closed forms for sanity
d_exp_cf = 1.0 / m.kappa
d_floor_cf = cutoff / 2.0
print()
print(f"Closed form check: 1/kappa = {d_exp_cf:.6f}$ ({d_exp_cf/TICK:.3f} ticks), "
      f"a/(2b) = cutoff/2 = {d_floor_cf:.6f}$ ({d_floor_cf/TICK:.1f} ticks)")
print(f"f_exp(1/kappa)   analytic = A_liq/(kappa*e) = {m.A_liq/(m.kappa*np.e):.6f}")
print(f"f_floor(a/2b)    analytic = a^2/(4b)        = {m.a**2/(4*m.b):.6f}")
print(f"ratio floor/exp peak                        = {(m.a**2/(4*m.b)) / (m.A_liq/(m.kappa*np.e)):.2f}x")
