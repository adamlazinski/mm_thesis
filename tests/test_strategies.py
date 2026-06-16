import math
import unittest

from hft_market_maker.core.market_state import MicrostructureStats
from hft_market_maker.strategies.avellaneda_stoikov import AvellanedaStoikov
from hft_market_maker.strategies.glft import GLFTMarketMaker


class AvellanedaStoikovTests(unittest.TestCase):
    def test_formula_returns_full_spread_and_quotes_split_it_once(self):
        gamma = 0.2
        kappa = 0.5
        strategy = AvellanedaStoikov(
            gamma=gamma,
            T=60.0,
            min_spread_bps=0.0,
            tick_size=0.0,
            kappa_as_min=0.0,
        )
        stats = MicrostructureStats(
            mid_price=100.0,
            sigma=0.0,
            kappa_as=kappa,
        )

        decision = strategy.compute_quotes(stats, inventory=0.0, timestamp=0.0)
        expected = (2.0 / gamma) * math.log1p(gamma / kappa)

        self.assertAlmostEqual(decision.optimal_spread, expected)
        self.assertAlmostEqual(decision.ask_price - decision.bid_price, expected)

    def test_reservation_price_uses_price_volatility(self):
        strategy = AvellanedaStoikov(gamma=0.1, tick_size=0.0)
        reservation = strategy.reservation_price(
            mid=100.0,
            inventory=2.0,
            sigma=0.01,
            t_remaining=5.0,
        )
        self.assertAlmostEqual(reservation, 99.0)


class GLFTTests(unittest.TestCase):
    def test_asymptotic_formula_uses_gamma_over_kappa(self):
        gamma = 0.2
        kappa = 0.5
        sigma = 0.01
        mid = 100.0
        arrival_rate = 2.0
        strategy = GLFTMarketMaker(
            gamma=gamma,
            kappa=kappa,
            A=arrival_rate,
            min_spread_bps=0.0,
            tick_size=0.0,
            kappa_from_stats=False,
        )

        half_spread, adverse, inventory_term = strategy.optimal_half_spread(
            sigma, mid, arrival_rate
        )
        power = (1.0 + gamma / kappa) ** (1.0 + kappa / gamma)
        inventory_step = math.sqrt(
            (sigma * mid) ** 2 * gamma / (2.0 * arrival_rate * kappa) * power
        )

        self.assertAlmostEqual(adverse, math.log1p(gamma / kappa) / gamma)
        self.assertAlmostEqual(inventory_term, inventory_step / 2.0)
        self.assertAlmostEqual(half_spread, adverse + inventory_step / 2.0)
        self.assertAlmostEqual(
            strategy.reservation_price(mid, 3.0, sigma, arrival_rate),
            mid - 3.0 * inventory_step,
        )


if __name__ == "__main__":
    unittest.main()
