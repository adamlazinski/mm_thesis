import unittest

from hft_market_maker.core.l2_features import BookSnapshot, L2BookTracker
from hft_market_maker.core.order_manager import OrderManager


def snapshot(timestamp=10.0):
    return BookSnapshot(
        timestamp=timestamp,
        best_bid_price=99.0,
        best_ask_price=101.0,
        best_bid_depth=3.0,
        best_ask_depth=4.0,
        obi_l1=0.0,
        obi_l3=0.0,
        obi_l5=0.0,
        obi_l10=0.0,
        total_bid_depth=8.0,
        total_ask_depth=10.0,
        bid_levels=((99.0, 3.0), (98.0, 5.0)),
        ask_levels=((101.0, 4.0), (102.0, 6.0)),
    )


class L2Tests(unittest.TestCase):
    def test_advance_never_returns_a_future_snapshot(self):
        tracker = L2BookTracker([snapshot(10.0)])
        self.assertIsNone(tracker.advance(9.0))
        self.assertEqual(tracker.advance(10.0).timestamp, 10.0)

    def test_queue_uses_depth_through_actual_order_price(self):
        snap = snapshot()
        self.assertEqual(snap.queue_ahead(99.0, "bid"), 3.0)
        self.assertEqual(snap.queue_ahead(98.0, "bid"), 8.0)
        self.assertEqual(snap.queue_ahead(101.0, "ask"), 4.0)
        self.assertEqual(snap.queue_ahead(102.0, "ask"), 10.0)


class ActivationTests(unittest.TestCase):
    def test_post_only_cross_is_rejected(self):
        manager = OrderManager(latency=0.1, order_type="post_only")
        manager.update_book(99.0, 101.0, 0.0)
        manager.submit_order("bid", 102.0, 1.0, 0.0)

        fills = manager.check_activation(0.1)

        self.assertEqual(fills, [])
        self.assertEqual(manager.n_active, 0)
        self.assertEqual(manager.fills, [])

    def test_plain_limit_crosses_at_opposing_touch(self):
        manager = OrderManager(
            latency=0.1,
            order_type="limit",
            taker_fee=0.001,
        )
        manager.update_book(99.0, 101.0, 0.0)
        manager.process_trade(0.05, 98.0, 1.0, "sell")
        manager.submit_order("bid", 102.0, 1.0, 0.0)

        fills = manager.check_activation(0.1)

        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0].price, 101.0)
        self.assertTrue(fills[0].is_taker)

    def test_queue_is_assigned_at_activation(self):
        manager = OrderManager(latency=0.1, queue_model="l2")
        manager.update_book(99.0, 101.0, 0.0)
        order_id = manager.submit_order("bid", 99.0, 1.0, 0.0)

        manager.check_activation(0.1, lambda order, ts: 7.0)

        order = manager.orders[order_id]
        self.assertEqual(order.queue_ahead, 7.0)


class FillTests(unittest.TestCase):
    def test_trade_side_is_enforced(self):
        manager = OrderManager(queue_model="none")
        manager.update_book(99.0, 101.0, 0.0)
        manager.submit_order("bid", 99.0, 1.0, 0.0)
        manager.check_activation(0.0)

        self.assertEqual(manager.process_trade(1.0, 99.0, 1.0, "buy"), [])
        self.assertEqual(len(manager.process_trade(2.0, 99.0, 1.0, "sell")), 1)

    def test_trade_volume_is_not_reused_across_orders(self):
        manager = OrderManager(queue_model="none")
        manager.update_book(99.0, 101.0, 0.0)
        manager.submit_order("bid", 99.0, 1.0, 0.0)
        manager.submit_order("bid", 99.0, 1.0, 0.1)
        manager.check_activation(0.1)

        fills = manager.process_trade(1.0, 99.0, 1.25, "sell")

        self.assertEqual(len(fills), 2)
        self.assertAlmostEqual(sum(fill.quantity for fill in fills), 1.25)


if __name__ == "__main__":
    unittest.main()
