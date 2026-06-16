import math
import unittest

import numpy as np

from hft_market_maker.core.market_state import MicrostructureStats
from hft_market_maker.strategies.shifted_glft_numerical import ShiftedGLFTNumerical


class IntensityTests(unittest.TestCase):
    def test_pure_exponential_when_a_and_b_zero(self):
        m = ShiftedGLFTNumerical(
            gamma=0.2, A_liq=2.0, kappa=0.5, a=0.0, b=0.0, tick_size=1.0,
        )
        delta = np.array([0.0, 1.0, 3.0])
        lam, lam_p, lam_pp = m._intensity_and_derivs(delta, m.A_liq)

        expected_lam = 2.0 * np.exp(-0.5 * delta)
        np.testing.assert_allclose(lam, expected_lam)
        np.testing.assert_allclose(lam_p, -0.5 * expected_lam)
        np.testing.assert_allclose(lam_pp, 0.25 * expected_lam)

    def test_linear_decay_floor_with_cutoff(self):
        m = ShiftedGLFTNumerical(
            gamma=0.2, A_liq=2.0, kappa=0.5, a=0.3, b=0.05, tick_size=1.0,
        )
        cutoff = m.a / m.b  # = 6.0
        below, above = 3.0, 10.0

        lam, lam_p, _ = m._intensity_and_derivs(np.array([below, above]), m.A_liq)

        exp_below = 2.0 * np.exp(-0.5 * below)
        exp_above = 2.0 * np.exp(-0.5 * above)

        # Below cutoff: floor a-b*delta is active and contributes -b to lambda'.
        self.assertAlmostEqual(lam[0], exp_below + (0.3 - 0.05 * below))
        self.assertAlmostEqual(lam_p[0], -0.5 * exp_below - 0.05)

        # Above cutoff: floor is clipped to 0 and contributes nothing to lambda'.
        self.assertAlmostEqual(lam[1], exp_above + 0.0)
        self.assertAlmostEqual(lam_p[1], -0.5 * exp_above)
        self.assertGreater(above, cutoff)

    def test_kappa_and_b_converted_from_per_tick_to_per_dollar(self):
        m = ShiftedGLFTNumerical(kappa=2.39, b=1.0, tick_size=0.01)
        self.assertAlmostEqual(m.kappa, 239.0)
        self.assertAlmostEqual(m.b, 100.0)

    def test_default_cutoff_is_1000_ticks(self):
        m = ShiftedGLFTNumerical()  # calibrated defaults
        cutoff_dollars = m.a / m.b
        self.assertAlmostEqual(cutoff_dollars, 1000 * m.tick_size)

        lam = m.intensity(np.array([cutoff_dollars, cutoff_dollars + 1.0]))
        np.testing.assert_allclose(lam, 0.0, atol=1e-10)


class FOCSolverTests(unittest.TestCase):
    """
    For lambda(delta) = A*exp(-kappa*delta) (a=b=0), the FOC
        F(delta) = lambda'(delta)*(1-z) + gamma*lambda(delta)*z = 0
    has the closed form delta* = (1/gamma)*ln(1+gamma/kappa) - dh, which
    is exactly GLFTMarketMaker.optimal_half_spread's adverse-selection term
    at dh=0. The Newton warm start *is* this closed form, so for a=b=0 the
    solver should reproduce it to floating-point precision for any dh.
    """

    def setUp(self):
        self.gamma = 0.2
        self.kappa = 0.5
        self.m = ShiftedGLFTNumerical(
            gamma=self.gamma, A_liq=2.0, kappa=self.kappa, a=0.0, b=0.0, tick_size=1.0,
        )

    def test_matches_glft_closed_form_at_zero_dh(self):
        delta = self.m._solve_foc(np.array([0.0]), self.m.A_liq)[0]
        expected = (1.0 / self.gamma) * math.log1p(self.gamma / self.kappa)
        self.assertAlmostEqual(delta, expected, places=10)

    def test_matches_closed_form_for_nonzero_dh(self):
        for dh in (-0.1, 0.05, 0.2):
            delta = self.m._solve_foc(np.array([dh]), self.m.A_liq)[0]
            expected = (1.0 / self.gamma) * math.log1p(self.gamma / self.kappa) - dh
            self.assertAlmostEqual(delta, expected, places=8)

    def test_thousand_tick_cutoff_is_noop_near_the_touch(self):
        """
        b = a/1000 (cutoff = 1000 ticks = $10) is a tail regularizer: at the
        calibrated scale the near-touch optimum is ~0.5 ticks, so exp(-kappa*
        cutoff) =~ 0 and the cutoff must not move delta* relative to the
        (locally well-posed) constant-floor b=0 case.
        """
        common = dict(gamma=30.0, A_liq=4.87, kappa=2.39, a=0.0871, tick_size=0.01)
        m_floor = ShiftedGLFTNumerical(b=0.0, **common)
        m_cutoff = ShiftedGLFTNumerical(b=0.0871 / 1000.0, **common)  # default

        delta_floor = m_floor._solve_foc(np.array([0.0]), m_floor.A_liq)[0]
        delta_cutoff = m_cutoff._solve_foc(np.array([0.0]), m_cutoff.A_liq)[0]

        self.assertAlmostEqual(delta_floor, delta_cutoff, places=6)

    def test_foc_residual_near_zero_with_floor_and_decay(self):
        """With a>0, b>0 the closed form no longer applies exactly, but
        Newton should still drive the FOC residual F(delta*) to ~0."""
        m = ShiftedGLFTNumerical(
            gamma=0.2, A_liq=2.0, kappa=0.5, a=0.3, b=0.05, tick_size=1.0,
        )
        dh = 0.1
        delta = m._solve_foc(np.array([dh]), m.A_liq)

        lam, lam_p, _ = m._intensity_and_derivs(delta, m.A_liq)
        z = np.exp(-m.gamma * (delta + dh))
        F = lam_p * (1 - z) + m.gamma * lam * z
        self.assertAlmostEqual(F[0], 0.0, places=6)


class PolicyTests(unittest.TestCase):
    """Tests on the full PDE solution (ergodic policy across the q-grid)."""

    def setUp(self):
        self.m = ShiftedGLFTNumerical(
            gamma=0.2, A_liq=2.0, kappa=0.5, a=0.1, b=0.0,
            order_size=0.001, max_inventory=0.003, q_buffer=2,
            tick_size=1.0, min_spread_bps=0.0,
        )
        self.delta_bid, self.delta_ask = self.m._policy(sigma_dollar=0.01, A_liq=self.m.A_liq)
        self.mid_idx = self.m.q_max  # q = 0

    def test_symmetric_at_zero_inventory(self):
        self.assertAlmostEqual(
            self.delta_bid[self.mid_idx], self.delta_ask[self.mid_idx], places=8
        )

    def test_long_inventory_tightens_ask_and_widens_bid(self):
        q_pos = self.mid_idx + 1  # q = +1 lot (long)

        self.assertLess(self.delta_ask[q_pos], self.delta_ask[self.mid_idx])
        self.assertGreater(self.delta_bid[q_pos], self.delta_bid[self.mid_idx])

    def test_short_inventory_is_mirror_image_of_long(self):
        q_pos = self.mid_idx + 1
        q_neg = self.mid_idx - 1

        self.assertAlmostEqual(self.delta_bid[q_pos], self.delta_ask[q_neg], places=8)
        self.assertAlmostEqual(self.delta_ask[q_pos], self.delta_bid[q_neg], places=8)


class ComputeQuotesTests(unittest.TestCase):
    def test_returns_sane_quote_decision(self):
        m = ShiftedGLFTNumerical(
            gamma=30.0, A_liq=4.87, kappa=2.39, a=0.087, b=0.0,
            order_size=0.001, max_inventory=0.005, tick_size=0.01,
            min_spread_bps=0.1,
        )
        stats = MicrostructureStats(mid_price=100000.0, sigma=2.9e-5, A_hat=4.87)

        decision = m.compute_quotes(stats, inventory=0.0, timestamp=0.0)

        self.assertLess(decision.bid_price, decision.ask_price)
        self.assertGreaterEqual(decision.ask_price - decision.bid_price, m.tick_size)
        self.assertEqual(decision.bid_size, m.order_size)
        self.assertEqual(decision.ask_size, m.order_size)
        self.assertTrue(decision.should_quote_bid)
        self.assertTrue(decision.should_quote_ask)

    def test_long_inventory_skews_reservation_below_mid(self):
        m = ShiftedGLFTNumerical(
            gamma=30.0, A_liq=4.87, kappa=2.39, a=0.087, b=0.0,
            order_size=0.001, max_inventory=0.005, tick_size=0.01,
            min_spread_bps=0.0,
        )
        stats = MicrostructureStats(mid_price=100000.0, sigma=2.9e-5, A_hat=4.87)

        flat = m.compute_quotes(stats, inventory=0.0, timestamp=0.0)
        long = m.compute_quotes(stats, inventory=2 * m.order_size, timestamp=0.0)

        self.assertLess(long.reservation, flat.reservation)

    def test_max_inventory_disables_one_side(self):
        m = ShiftedGLFTNumerical(
            gamma=30.0, A_liq=4.87, kappa=2.39, a=0.087, b=0.0,
            order_size=0.001, max_inventory=0.005, tick_size=0.01,
        )
        stats = MicrostructureStats(mid_price=100000.0, sigma=2.9e-5, A_hat=4.87)

        long_at_limit = m.compute_quotes(stats, inventory=m.max_inventory, timestamp=0.0)
        short_at_limit = m.compute_quotes(stats, inventory=-m.max_inventory, timestamp=0.0)

        self.assertFalse(long_at_limit.should_quote_bid)
        self.assertTrue(long_at_limit.should_quote_ask)
        self.assertTrue(short_at_limit.should_quote_bid)
        self.assertFalse(short_at_limit.should_quote_ask)


if __name__ == "__main__":
    unittest.main()
