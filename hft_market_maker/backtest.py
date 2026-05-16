"""
Event-Driven Backtest Engine
------------------------------

This is the core orchestration layer. It:
  1. Loads raw tick data (trades + quotes) from CSV/Parquet
  2. Merges them into a single chronological event stream
  3. Processes each event through market state → strategy → order manager
  4. Tracks performance metrics
  5. Returns a rich results object for analysis

Usage
-----
    from hft_market_maker.backtest import Backtest
    from hft_market_maker.strategies.avellaneda_stoikov import AvellanedaStoikov
    from hft_market_maker.data.loader import DataLoader

    loader = DataLoader()
    trades, quotes = loader.load_csv("trades.csv", "quotes.csv")

    strategy = AvellanedaStoikov(gamma=0.1, T=3600, order_size=0.01)
    bt = Backtest(strategy)
    results = bt.run(trades, quotes)
    results.plot()
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Any
import numpy as np
import pandas as pd
from collections import defaultdict

from .core.events import EventType, TradeEvent, QuoteEvent
from .core.market_state import MarketState
from .core.order_manager import OrderManager
from .core.vol_guardrail import VolRiskManager, GuardrailState


@dataclass
class GapClosure:
    """
    Records a position reset triggered by a data gap.
    Stored in BacktestResults.gap_log for analysis.
    """
    timestamp: float
    gap_seconds: float
    inventory_closed: float   # signed inventory that was reset to zero
    close_price: float        # last mid price used to mark to market
    pnl_realised: float       # cash impact of the closure (inventory * price)
    pnl_before: float         # total PnL just before the gap
    pnl_after: float          # total PnL just after (should equal pnl_before if Option A)


@dataclass
class BacktestResults:
    """Full results from a backtest run."""
    equity_curve: pd.Series
    inventory_curve: pd.Series
    pnl_curve: pd.Series
    trade_log: pd.DataFrame
    quote_log: pd.DataFrame
    metrics: dict
    gap_log: List["GapClosure"] = field(default_factory=list)
    regime_log: Optional[pd.DataFrame] = None

    def summary(self) -> str:
        m = self.metrics
        lines = [
            "=" * 50,
            "BACKTEST RESULTS SUMMARY",
            "=" * 50,
            f"Total PnL:            {m.get('total_pnl', 0):.4f}",
            f"Sharpe Ratio:         {m.get('sharpe', 0):.3f}",
            f"Max Drawdown:         {m.get('max_drawdown', 0):.4f}",
            f"Total Fills:          {m.get('total_fills', 0)}",
            f"Fill Rate:            {m.get('fill_rate', 0):.1%}",
            f"Avg Spread Quoted:    {m.get('avg_spread_bps', 0):.2f} bps",
            f"Avg Abs Inventory:    {m.get('avg_abs_inventory', 0):.4f}",
            f"Max Abs Inventory:    {m.get('max_abs_inventory', 0):.4f}",
            f"Total Fees Paid:      {m.get('total_fees', 0):.6f}",
            f"Runtime (events):     {m.get('n_events', 0):,}",
            f"Data Gaps (short):    {m.get('n_short_gaps', 0)}",
            f"Data Gaps (long):     {m.get('n_long_gaps', 0)}",
            f"PnL from gap closures:{m.get('gap_closure_pnl', 0):.4f}",
            f"MM-only PnL:          {m.get('mm_only_pnl', 0):.4f}",
            f"Hysteresis skips:     {m.get('n_hysteresis_skips', 0):,}  "
            f"({m.get('hysteresis_skip_rate', 0):.1%} of recomputes)",
            "=" * 50,
        ]
        return "\n".join(lines)

    def plot(self) -> None:
        """Quick plot of key curves. Requires matplotlib."""
        try:
            import matplotlib.pyplot as plt
            fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

            self.equity_curve.plot(ax=axes[0], title="Total PnL", color="steelblue")
            axes[0].set_ylabel("PnL (quote asset)")
            axes[0].axhline(0, color="gray", linestyle="--", alpha=0.5)

            self.inventory_curve.plot(ax=axes[1], title="Inventory", color="darkorange")
            axes[1].set_ylabel("Inventory (base asset)")
            axes[1].axhline(0, color="gray", linestyle="--", alpha=0.5)

            self.pnl_curve.diff().fillna(0).rolling(50).mean().plot(
                ax=axes[2], title="Rolling PnL (50-event MA)", color="seagreen"
            )
            axes[2].set_ylabel("PnL change")
            axes[2].axhline(0, color="gray", linestyle="--", alpha=0.5)

            # Mark gap closure events on all panels
            for gap in self.gap_log:
                gap_dt = pd.to_datetime(gap.timestamp, unit="s")
                for ax in axes:
                    ax.axvline(gap_dt, color="red", linestyle=":", alpha=0.6, linewidth=0.8)

            if self.gap_log:
                axes[0].legend(
                    [plt.Line2D([0],[0], color="red", linestyle=":")],
                    [f"Gap closure ({len(self.gap_log)} events)"],
                    loc="upper left", fontsize=8
                )

            plt.tight_layout()
            plt.show()
        except ImportError:
            print("matplotlib not installed. Run: pip install matplotlib")


class Backtest:
    """
    Event-driven backtesting engine.

    Parameters
    ----------
    strategy : Any
        Any strategy with a .compute_quotes(stats, inventory, timestamp) method.
    market_state : MarketState
        Market state estimator (uses defaults if not provided).
    order_manager : OrderManager
        Order lifecycle manager (uses defaults if not provided).
    requote_on_fill : bool
        If True, immediately requote after a fill.
    requote_interval : float
        Minimum seconds between requotes (prevents thrashing).
    verbose : bool
        Print progress every N events.
    """

    def __init__(
        self,
        strategy: Any,
        market_state: Optional[MarketState] = None,
        order_manager: Optional[OrderManager] = None,
        requote_on_fill: bool = True,
        requote_interval: float = 0.1,
        verbose: bool = True,
        verbose_interval: int = 10_000,
        vol_risk_manager: Optional[VolRiskManager] = None,
        short_gap_threshold: float = 2.0,
        long_gap_threshold: float = 30.0,
        tolerance_ticks: float = 8,
        tick_size: float = 0.01,
        kappa_force_interval: float = 60.0,
    ):
        self.strategy = strategy
        self.market_state = market_state or MarketState()
        self.order_manager = order_manager or OrderManager()
        self.requote_on_fill = requote_on_fill
        self.requote_interval = requote_interval
        self.verbose = verbose
        self.verbose_interval = verbose_interval
        self.vol_risk_manager = vol_risk_manager
        self.short_gap_threshold = short_gap_threshold
        self.long_gap_threshold = long_gap_threshold
        self.tolerance_ticks = tolerance_ticks
        self.tick_size = tick_size
        self.kappa_force_interval = kappa_force_interval

    def run(
        self,
        trades: List[TradeEvent],
        quotes: List[QuoteEvent],
    ) -> BacktestResults:
        """
        Main backtest loop.

        Parameters
        ----------
        trades : list of TradeEvent
        quotes : list of QuoteEvent
        """

        # Merge and sort events
        events = []
        for t in trades:
            events.append((t.timestamp, 0, "trade", t))  # 0 = trade priority (fills first)
        for q in quotes:
            events.append((q.timestamp, 1, "quote", q))  # 1 = quote
        events.sort(key=lambda x: (x[0], x[1]))

        # Logging containers
        equity_log: list[tuple[float, float]] = []
        inventory_log: list[tuple[float, float]] = []
        pnl_log: list[tuple[float, float]] = []
        quote_records: list[dict] = []
        fill_records: list[dict] = []
        gap_closures: list[GapClosure] = []

        last_requote_time: float = 0.0
        last_quote_event: Optional[QuoteEvent] = None
        last_event_timestamp: Optional[float] = None
        last_mid: float = 0.0
        n_short_gaps: int = 0
        n_long_gaps: int = 0
        n_events = len(events)
        self._n_hysteresis_skips: int = 0
        self._current_half_spread: float = 0.0   # half-spread of currently live quotes
        self._last_kappa_update: float = 0.0     # timestamp of last force_kappa_update

        for i, (timestamp, _, etype, event_data) in enumerate(events):
            if self.verbose and i % self.verbose_interval == 0:
                print(f"  Processing event {i:,} / {n_events:,}  "
                      f"({100*i/n_events:.1f}%)  "
                      f"PnL: {self.order_manager.total_pnl:.4f}  "
                      f"Inv: {self.order_manager.inventory:.4f}")

            # ----------------------------------------------------------------
            # Gap detection — runs before anything else on every event
            # ----------------------------------------------------------------
            if last_event_timestamp is not None:
                gap = timestamp - last_event_timestamp

                if gap >= self.long_gap_threshold:
                    n_long_gaps += 1
                    om = self.order_manager

                    # Cancel all open orders immediately
                    om.cancel_all()

                    # Close position at last known mid (Option A: realise P&L)
                    inv = om.inventory
                    close_price = last_mid if last_mid > 0 else 0.0
                    pnl_before = om.total_pnl

                    if abs(inv) > 0 and close_price > 0:
                        # Mark inventory to market: cash += inventory * mid
                        # This is equivalent to a synthetic fill at last mid
                        closure_cash = inv * close_price
                        om.cash += closure_cash
                        om.inventory = 0.0
                        pnl_after = om.total_pnl

                        gap_closures.append(GapClosure(
                            timestamp=timestamp,
                            gap_seconds=gap,
                            inventory_closed=inv,
                            close_price=close_price,
                            pnl_realised=pnl_after-pnl_before,
                            pnl_before=pnl_before,
                            pnl_after=pnl_after,
                        ))

                        if self.verbose:
                            direction = "long" if inv > 0 else "short"
                            print(
                                f"  [GAP {gap:.0f}s] Closed {direction} {abs(inv):.4f} "
                                f"@ {close_price:.2f} | "
                                f"PnL impact: {closure_cash:+.4f} | "
                                f"Total PnL: {pnl_after:.4f}"
                            )
                    else:
                        gap_closures.append(GapClosure(
                            timestamp=timestamp,
                            gap_seconds=gap,
                            inventory_closed=0.0,
                            close_price=close_price,
                            pnl_realised=0.0,
                            pnl_before=pnl_before,
                            pnl_after=pnl_before,
                        ))

                    # Full market state reset — pre-gap estimates are stale
                    self.market_state = MarketState(
                        vol_window=self.market_state.vol_window,
                        arrival_window=self.market_state.arrival_window,
                        ewma_alpha=self.market_state.ewma_alpha,
                    )
                    # Reset vol guardrail history too
                    if self.vol_risk_manager is not None:
                        max_inv = getattr(
                            getattr(self.strategy, "base", self.strategy),
                            "max_inventory", 1.0
                        )
                        from .core.vol_guardrail import VolRiskManager
                        self.vol_risk_manager = VolRiskManager(
                            soft_threshold=self.vol_risk_manager.guardrail.soft_threshold,
                            hard_threshold=self.vol_risk_manager.guardrail.hard_threshold,
                            min_size_multiplier=self.vol_risk_manager.guardrail.min_size_multiplier,
                            max_spread_multiplier=self.vol_risk_manager.guardrail.max_spread_multiplier,
                        )

                    last_requote_time = timestamp  # prevent immediate requote

                elif gap >= self.short_gap_threshold:
                    n_short_gaps += 1
                    # Cancel orders — state is slightly stale
                    self.order_manager.cancel_all()
                    last_requote_time = timestamp  # small cooldown before requoting

            last_event_timestamp = timestamp

            if etype == "trade":
                t: TradeEvent = event_data

                # 1. Update market state
                self.market_state.on_trade(t.timestamp, t.price, t.quantity, t.side)

                # 2. Check fills against our open orders
                fills = self.order_manager.process_trade(t.timestamp, t.price, t.quantity, t.side)

                # 3. Log fills and notify kappa estimator
                for fill in fills:
                    fill_records.append({
                        "timestamp": fill.timestamp,
                        "side": fill.side,
                        "price": fill.price,
                        "quantity": fill.quantity,
                        "fee": fill.fee,
                    })

                    # Notify RL agent of fill if applicable
                    if hasattr(self.strategy, "on_fill"):
                        self.strategy.on_fill(timestamp)

                    # Notify kappa estimator: fill at current quoted half-spread
                    if self._current_half_spread > 0:
                        self.market_state.on_mm_fill(fill.timestamp, self._current_half_spread)

                # 4. Requote after fill
                if fills and self.requote_on_fill and last_quote_event is not None:
                    if timestamp - last_requote_time >= self.requote_interval:
                        self._requote(timestamp, last_quote_event, quote_records)
                        last_requote_time = timestamp

            else:  # quote event
                q: QuoteEvent = event_data
                last_quote_event = q
                last_mid = q.mid  # track for gap closure price

                # 1. Update market state
                self.market_state.on_quote(q.timestamp, q.best_bid, q.best_ask,
                                           q.bid_size, q.ask_size)
                self.order_manager.update_mid(q.mid)

                # 2. Periodic kappa MLE update (prevents stale estimates in quiet periods)
                if timestamp - self._last_kappa_update >= self.kappa_force_interval:
                    self.market_state.force_kappa_update(timestamp)
                    self._last_kappa_update = timestamp

                # 3. Requote on every quote event (throttled)
                if (self.market_state.is_ready and
                        timestamp - last_requote_time >= self.requote_interval):
                    self._requote(timestamp, q, quote_records)
                    last_requote_time = timestamp

            # Log state every 100 events (or adjust as needed)
            if i % 100 == 0:
                equity_log.append((timestamp, self.order_manager.total_pnl))
                inventory_log.append((timestamp, self.order_manager.inventory))
                pnl_log.append((timestamp, self.order_manager.total_pnl))

        # Build results
        return self._compile_results(
            equity_log, inventory_log, pnl_log,
            fill_records, quote_records, n_events,
            gap_closures=gap_closures,
            n_short_gaps=n_short_gaps,
            n_long_gaps=n_long_gaps,
            n_hysteresis_skips=self._n_hysteresis_skips,
        )

    def _requote(self, timestamp: float, quote: QuoteEvent,
                 quote_records: list) -> None:
        """Place new quotes if optimal prices have moved beyond tolerance."""
        ms = self.market_state
        om = self.order_manager

        if not ms.is_ready:
            return

        inventory = om.inventory
        stats = ms.stats

        # 1. Strategy decision (computed before any cancellation)
        result = self.strategy.compute_quotes(stats, inventory, timestamp,
                                              total_pnl=om.total_pnl)
        if isinstance(result, tuple):
            decision, _ = result
        else:
            decision = result

        # 2. Inventory-based quoting limits.
        # GLFT embeds should_quote_bid/ask in the decision object itself;
        # A-S exposes a should_quote() method on the strategy.
        if hasattr(decision, "should_quote_bid"):
            quote_bid = decision.should_quote_bid
            quote_ask = decision.should_quote_ask
        elif hasattr(self.strategy, "should_quote"):
            base_strategy = getattr(self.strategy, "base", self.strategy)
            quote_bid, quote_ask = base_strategy.should_quote(inventory)
        else:
            quote_bid = quote_ask = True

        # 3. Vol guardrail — applied after strategy decision, before submission
        guardrail = None
        if self.vol_risk_manager is not None and self.vol_risk_manager.is_ready:
            max_inv = getattr(
                getattr(self.strategy, "base", self.strategy),
                "max_inventory", 1.0
            )
            guardrail = self.vol_risk_manager.on_quote(
                timestamp=timestamp,
                mid=stats.mid_price,
                best_bid=quote.best_bid,
                best_ask=quote.best_ask,
                inventory=inventory,
                max_inventory=max_inv,
            )

            decision.bid_size *= guardrail.bid_size_multiplier
            decision.ask_size *= guardrail.ask_size_multiplier

            if guardrail.spread_multiplier > 1.0:
                half_spread = (decision.ask_price - decision.bid_price) / 2.0
                extra = half_spread * (guardrail.spread_multiplier - 1.0)
                decision.bid_price -= extra
                decision.ask_price += extra

            if not guardrail.should_quote_bid:
                quote_bid = False
            if not guardrail.should_quote_ask:
                quote_ask = False

        elif self.vol_risk_manager is not None:
            # Guardrail not yet ready — update rolling state, skip quoting
            max_inv = getattr(
                getattr(self.strategy, "base", self.strategy),
                "max_inventory", 1.0
            )
            self.vol_risk_manager.on_quote(
                timestamp=timestamp,
                mid=stats.mid_price,
                best_bid=quote.best_bid,
                best_ask=quote.best_ask,
                inventory=inventory,
                max_inventory=max_inv,
            )
            return

        # 4. Sanity check: bid must be below ask
        if decision.bid_price >= decision.ask_price:
            return

        # 5. Hysteresis: skip cancel+resubmit if both quotes are within tolerance.
        #    Only applied when quoting both sides — a forced one-sided cancel always
        #    goes through to avoid leaving a stale order on the suppressed side.
        if self.tolerance_ticks > 0 and quote_bid and quote_ask:
            tolerance = self.tolerance_ticks * self.tick_size
            active = {o.side: o for o in om.get_active_orders()
                      if o.status in ("open", "partially_filled")}
            if "bid" in active and "ask" in active:
                bid_moved = abs(decision.bid_price - active["bid"].price) > tolerance
                ask_moved = abs(decision.ask_price - active["ask"].price) > tolerance
                if not bid_moved and not ask_moved:
                    self._n_hysteresis_skips += 1
                    return

        # 6. Cancel existing orders and submit new ones
        om.cancel_all(timestamp)

        submitted_bid = quote_bid and decision.bid_size > 0
        submitted_ask = quote_ask and decision.ask_size > 0

        if submitted_bid:
            om.submit_order("bid", decision.bid_price, decision.bid_size, timestamp)
        if submitted_ask:
            om.submit_order("ask", decision.ask_price, decision.ask_size, timestamp)

        # Only notify the kappa estimator and log when at least one side is live.
        # In regime-paused cycles (should_quote_bid/ask both False) we cancel but
        # do not record a quote event — preserving fill_rate denominator integrity.
        if not submitted_bid and not submitted_ask:
            return

        # Notify kappa estimator; convert to ticks so kappa_as is in 1/tick units,
        # consistent with offline calibration (thesis: kappa ≈ 0.311/tick full-day).
        half_spread_ticks = (decision.ask_price - decision.bid_price) / 2.0 / self.tick_size
        self.market_state.notify_quote_posted(timestamp, half_spread_ticks)
        self._current_half_spread = half_spread_ticks

        # 7. Log
        spread_bps = (decision.ask_price - decision.bid_price) / max(stats.mid_price, 1e-6) * 10_000
        quote_records.append({
            "timestamp": timestamp,
            "bid": decision.bid_price,
            "ask": decision.ask_price,
            "mid": stats.mid_price,
            "reservation": getattr(decision, "reservation_price",
                                   getattr(decision, "reservation", None)),
            "spread_bps": spread_bps,
            "inventory": inventory,
            "sigma": stats.sigma,
            "kappa": stats.kappa_as,
            "A_hat": stats.A_hat,
            "ofi": stats.ofi,
            "vol_composite": guardrail.vol_percentile if guardrail else None,
            "vol_percentile": guardrail.vol_percentile if guardrail else None,
            "bid_size_mult": guardrail.bid_size_multiplier if guardrail else 1.0,
            "ask_size_mult": guardrail.ask_size_multiplier if guardrail else 1.0,
            "spread_mult": guardrail.spread_multiplier if guardrail else 1.0,
            "guardrail_trigger": guardrail.trigger_reason if guardrail else "none",
        })

    def _compile_results(
        self,
        equity_log, inventory_log, pnl_log,
        fill_records, quote_records, n_events,
        gap_closures=None, n_short_gaps=0, n_long_gaps=0,
        n_hysteresis_skips=0,
    ) -> BacktestResults:
        def to_series(log, name):
            if not log:
                return pd.Series(name=name, dtype=float)
            df = pd.DataFrame(log, columns=["timestamp", name])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
            return df.set_index("timestamp")[name]

        equity = to_series(equity_log, "pnl")
        inventory = to_series(inventory_log, "inventory")
        pnl = to_series(pnl_log, "pnl")

        fills_df = pd.DataFrame(fill_records)
        quotes_df = pd.DataFrame(quote_records)

        # Compute metrics
        metrics = self._compute_metrics(equity, inventory, fills_df, quotes_df, n_events,
                                          gap_closures=gap_closures,
                                          n_short_gaps=n_short_gaps,
                                          n_long_gaps=n_long_gaps,
                                          n_hysteresis_skips=n_hysteresis_skips)

        return BacktestResults(
            equity_curve=equity,
            inventory_curve=inventory,
            pnl_curve=pnl,
            trade_log=fills_df,
            quote_log=quotes_df,
            metrics=metrics,
            gap_log=gap_closures or [],
        )

    def _compute_metrics(self, equity, inventory, fills_df, quotes_df, n_events,
                          gap_closures=None, n_short_gaps=0, n_long_gaps=0,
                          n_hysteresis_skips=0) -> dict:
        metrics = {"n_events": n_events}

        # PnL
        metrics["total_pnl"] = float(equity.iloc[-1]) if len(equity) > 0 else 0.0

        # Sharpe (annualised from per-step returns)
        if len(equity) > 2:
            rets = equity.diff().dropna()
            mean_ret = rets.mean()
            std_ret = rets.std()
            metrics["sharpe"] = float(mean_ret / std_ret * np.sqrt(len(rets))) if std_ret > 0 else 0.0
        else:
            metrics["sharpe"] = 0.0

        # Drawdown
        if len(equity) > 0:
            running_max = equity.cummax()
            drawdown = equity - running_max
            metrics["max_drawdown"] = float(drawdown.min())
        else:
            metrics["max_drawdown"] = 0.0

        # Fills
        metrics["total_fills"] = len(fills_df)
        if len(quotes_df) > 0:
            metrics["fill_rate"] = len(fills_df) / max(len(quotes_df) * 2, 1)
            metrics["avg_spread_bps"] = float(quotes_df["spread_bps"].mean())
        else:
            metrics["fill_rate"] = 0.0
            metrics["avg_spread_bps"] = 0.0

        # Inventory
        if len(inventory) > 0:
            metrics["avg_abs_inventory"] = float(inventory.abs().mean())
            metrics["max_abs_inventory"] = float(inventory.abs().max())
        else:
            metrics["avg_abs_inventory"] = 0.0
            metrics["max_abs_inventory"] = 0.0

        metrics["total_fees"] = self.order_manager.total_fees

        # Gap metrics
        metrics["n_short_gaps"] = n_short_gaps
        metrics["n_long_gaps"] = n_long_gaps
        gap_closures = gap_closures or []
        metrics["n_gap_closures"] = len([g for g in gap_closures if g.inventory_closed != 0])
        gap_pnl = sum(g.pnl_realised for g in gap_closures)
        metrics["gap_closure_pnl"] = gap_pnl
        metrics["mm_only_pnl"] = metrics["total_pnl"] - gap_pnl

        # Hysteresis
        n_requotes = len(quotes_df)  # actual cancel+resubmit cycles
        n_total_recomputes = n_requotes + n_hysteresis_skips
        metrics["n_hysteresis_skips"] = n_hysteresis_skips
        metrics["hysteresis_skip_rate"] = (
            n_hysteresis_skips / n_total_recomputes if n_total_recomputes > 0 else 0.0
        )

        return metrics
