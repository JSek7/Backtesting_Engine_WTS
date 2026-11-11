"""Participant simulator adapted from the organiser's multi-asset coordinator.

Execution phases and order scheduling are retained. Generation and private-state
recording are removed. Every equity value is marked at a PUBLIC dealer reference.
"""
from copy import deepcopy
import math
import numpy as np

from models.models import AssetObservation, BotAccount, BotSubmission, Observation, OwnFill, QuoteAction
from models.results import BookRecord, BotErrorRecord, BotResult, EquityRecord, QuoteRecord, RunLog, SimulationOutput, SimulationResult, TradeRecord
from .accounting import apply_fills, calculate_equity
from .matching import MatchingEngine
from .risk import validate_quote


def _audit_scalar(value):
    """Preserve valid values; represent malformed submissions safely in logs."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value if math.isfinite(value) else str(value)
    return repr(value)[:300]


class SimulationRunner:
    def __init__(self, markets, bots, asset_configs, runtime_bucket_ns=100_000,
                 initial_cash=0.0, metadata=None):
        if not markets or not bots:
            raise ValueError("At least one asset and one bot are required")
        if set(markets) != set(asset_configs):
            raise ValueError("Every asset needs public configuration")
        if type(runtime_bucket_ns) is not int or runtime_bucket_ns < 1:
            raise ValueError("runtime_bucket_ns must be positive")
        if not math.isfinite(initial_cash):
            raise ValueError("initial_cash must be finite")
        clocks = {(m.config["n_ticks"], m.config.get("dt", 1.0)) for m in markets.values()}
        if len(clocks) != 1:
            raise ValueError("All assets must share n_ticks and dt")
        self.markets, self.bots = markets, bots
        self.asset_configs = deepcopy(asset_configs)
        self.n_ticks = next(iter(clocks))[0]
        self.runtime_bucket_ns = runtime_bucket_ns
        self.initial_cash = float(initial_cash)
        self.metadata = deepcopy(metadata or {})
        self.matching = {asset: MatchingEngine(asset) for asset in markets}
        self._reset_done = False

    def reset(self, seed=42):
        for asset, market in self.markets.items():
            market.reset()  # Rewind; never generate data or change the tape.
            self.matching[asset].reset()
        for runner in self.bots.values():
            runner.reset()
        self.seed, self.tick = seed, 0
        self.accounts = {bot: BotAccount(cash=self.initial_cash) for bot in self.bots}
        self.price_history = {a: [float(c["initial_price"])] for a, c in self.asset_configs.items()}
        self.mark_prices = {a: h[0] for a, h in self.price_history.items()}
        self.mark_age_ticks = dict.fromkeys(self.markets, 0)
        self.recent_fills = {b: {a: [] for a in self.markets} for b in self.bots}
        self.equity_history = {b: [self.initial_cash] for b in self.bots}
        self.log = RunLog()
        for bot, account in self.accounts.items():
            self.log.equity.append(EquityRecord(0, bot, account.cash, {}, self.initial_cash,
                                                dict(self.mark_prices), dict(self.mark_age_ticks)))
        self._reset_done = True

    def _make_observation(self, bot_id):
        account = self.accounts[bot_id]
        markets = {}
        for asset in self.markets:
            markets[asset] = AssetObservation(
                price_history=tuple(self.price_history[asset]),
                book=deepcopy(self.matching[asset].get_book_snapshot()),
                position=account.positions.get(asset, 0),
                recent_fills=tuple(self.recent_fills[bot_id][asset]),
            )
        return Observation(self.tick, markets, account.cash)

    def _collect_submissions(self):
        observations = {bot: self._make_observation(bot) for bot in self.bots}
        submissions = []
        for bot, runner in self.bots.items():
            try:
                submission = runner.run(observations[bot])
                if submission.bot_id != bot or not isinstance(submission.quotes, dict):
                    raise ValueError("Invalid BotSubmission")
                if type(submission.runtime_ns) is not int or submission.runtime_ns < 0:
                    raise ValueError("Invalid runtime")
                unknown = set(submission.quotes) - set(self.markets)
                if unknown:
                    self.log.errors.append(BotErrorRecord(self.tick, bot, None,
                                           f"Unknown asset IDs ignored: {sorted(map(str, unknown))}"))
            except Exception as exc:
                self.log.errors.append(BotErrorRecord(self.tick, bot, None,
                                       f"Bot call failed: {type(exc).__name__}: {str(exc)[:1000]}"))
                submission = BotSubmission(bot, {}, 0)
            submissions.append(submission)
        self.recent_fills = {b: {a: [] for a in self.markets} for b in self.bots}
        return submissions

    @staticmethod
    def _empty_quote():
        return QuoteAction(None, 0, None, 0)

    def _prepare_orders(self, asset_id, submissions, reference_price):
        scheduled = []
        config = self.asset_configs[asset_id]
        for submission in submissions:
            submitted = submission.quotes.get(asset_id, self._empty_quote())
            accepted, error = self._empty_quote(), None
            try:
                if not isinstance(submitted, QuoteAction):
                    raise TypeError("Expected QuoteAction imported from models.models")
                accepted = validate_quote(submitted, self.accounts[submission.bot_id], asset_id, config)
            except (TypeError, ValueError, OverflowError) as exc:
                error = f"{type(exc).__name__}: {exc}"
                self.log.errors.append(BotErrorRecord(self.tick, submission.bot_id, asset_id, error))
                if not isinstance(submitted, QuoteAction):
                    submitted = self._empty_quote()
            spread = accepted.ask_price - accepted.bid_price if accepted.bid_size and accepted.ask_size else None
            self.log.quotes.append(QuoteRecord(
                tick=self.tick, asset_id=asset_id, bot_id=submission.bot_id, reference_price=reference_price,
                submitted_bid=_audit_scalar(submitted.bid_price), submitted_bid_size=_audit_scalar(submitted.bid_size),
                submitted_ask=_audit_scalar(submitted.ask_price), submitted_ask_size=_audit_scalar(submitted.ask_size),
                accepted_bid=accepted.bid_price, accepted_bid_size=accepted.bid_size,
                accepted_ask=accepted.ask_price, accepted_ask_size=accepted.ask_size,
                accepted_spread=spread, runtime_ns=submission.runtime_ns, error=error,
            ))
            bucket = submission.runtime_ns // self.runtime_bucket_ns
            if accepted.bid_size > 0:
                scheduled.append((bucket, -accepted.bid_size, submission.bot_id, "buy",
                                  QuoteAction(accepted.bid_price, accepted.bid_size, None, 0)))
            if accepted.ask_size > 0:
                scheduled.append((bucket, -accepted.ask_size, submission.bot_id, "sell",
                                  QuoteAction(None, 0, accepted.ask_price, accepted.ask_size)))
        scheduled.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
        return [(bot, quote) for _, _, bot, _, quote in scheduled]

    @staticmethod
    def _dealer_reference(matching):
        orders = [o for o in matching.orders.values() if o.owner_type == "dealer" and o.remaining > 0]
        bids = [o.price for o in orders if o.side == "buy"]
        asks = [o.price for o in orders if o.side == "sell"]
        return (max(bids) + min(asks)) / 2 if bids and asks else None

    def _process_fills(self, fills, fee_per_unit):
        for fill in fills:
            apply_fills(self.accounts, [fill], fee_per_unit)
            self.log.fills.append(fill)
            participants = ((fill.buyer_bot, "buy", fill.buy_order_id, -1),
                            (fill.seller_bot, "sell", fill.sell_order_id, 1))
            for bot, side, order_id, cash_sign in participants:
                if bot is None:
                    continue
                account = self.accounts[bot]
                position = account.positions.get(fill.asset_id, 0)
                # Fail on engine bugs; never retrospectively clip a matched trade.
                if abs(position) > self.asset_configs[fill.asset_id]["max_position"]:
                    raise RuntimeError("Execution violated position limit: check order admission/reservations")
                fee = fill.quantity * fee_per_unit
                self.log.trades.append(TradeRecord(
                    tick=self.tick, time=fill.time, asset_id=fill.asset_id, bot_id=bot,
                    side=side, price=fill.price, quantity=fill.quantity, order_id=order_id,
                    fee=fee, cash_change=cash_sign * fill.quantity * fill.price - fee,
                    cash_after=account.cash, position_after=position,
                    counterparty_kind=fill.seller_kind if side == "buy" else fill.buyer_kind,
                    liquidity_role="unknown" if fill.taker_side is None else "taker" if side == fill.taker_side else "maker",
                ))
                self.recent_fills[bot][fill.asset_id].append(OwnFill(fill.time, side, fill.price, fill.quantity, order_id))

    def _process_asset_tick(self, asset_id, market_step, submissions):
        matching = self.matching[asset_id]
        fee = float(self.asset_configs[asset_id]["fee_per_unit"])
        opening = matching.get_liquidity_snapshot()
        for bot in self.bots:
            matching.cancel_bot_quotes(bot)
        for event in market_step.events:
            if event.kind == "dealer_cancel":
                matching.process_event(event)
        for event in market_step.events:
            if event.kind == "dealer_limit":
                self._process_fills(matching.process_event(event), fee)
        reference = self._dealer_reference(matching)
        dealer_book = matching.get_book_snapshot(owner_type="dealer")
        for bot, quote in self._prepare_orders(asset_id, submissions, reference):
            self._process_fills(matching.submit_bot_quotes(bot, quote, market_step.start_time), fee)
        pre_customer = deepcopy(matching.get_book_snapshot())
        customers = sorted((e for e in market_step.events if e.kind == "customer_order"),
                           key=lambda e: (e.time, e.sequence))
        customer_filled = 0
        for event in customers:
            fills = matching.process_event(event)
            customer_filled += sum(fill.quantity for fill in fills)
            self._process_fills(fills, fee)
        post_customer = deepcopy(matching.get_book_snapshot())
        closing = matching.get_liquidity_snapshot()
        liquidity = {k: closing[k] - opening[k] for k in ("provided", "consumed", "withdrawn")}
        requested = sum(e.data["quantity"] for e in customers)
        liquidity.update(opening_depth=opening["depth"], closing_depth=closing["depth"],
                         customer_requested=requested, customer_filled=customer_filled,
                         customer_unfilled=requested - customer_filled)
        dealer_quotes = {k: dealer_book[k] for k in ("best_bid", "best_ask")}
        return BookRecord(self.tick, asset_id, reference, pre_customer, post_customer, dealer_quotes, liquidity)

    def _record_step(self, records):
        for asset, record in records.items():
            self.log.books.append(record)
            self.price_history[asset].append(record.reference_price)
            if record.reference_price is None:
                self.mark_age_ticks[asset] += 1
            else:
                self.mark_prices[asset] = record.reference_price
                self.mark_age_ticks[asset] = 0
        for bot, account in self.accounts.items():
            value = calculate_equity(account, self.mark_prices)
            self.equity_history[bot].append(value)
            self.log.equity.append(EquityRecord(self.tick + 1, bot, account.cash, dict(account.positions),
                                                value, dict(self.mark_prices), dict(self.mark_age_ticks)))

    def step(self):
        if not self._reset_done:
            raise RuntimeError("Call reset() first, or use run()")
        if self.tick >= self.n_ticks:
            raise StopIteration("Backtest complete")
        submissions = self._collect_submissions()
        steps = {asset: market.step() for asset, market in self.markets.items()}
        for asset, step in steps.items():
            if (step.start_time, step.end_time) != (self.tick, self.tick + 1):
                raise ValueError(f"Asset {asset} is not aligned to the decision tick")
        records = {asset: self._process_asset_tick(asset, steps[asset], submissions) for asset in self.markets}
        self._record_step(records)
        self.tick += 1
        return records

    def run(self, seed=42):
        self.reset(seed)
        for _ in range(self.n_ticks):
            self.step()
        return self._build_output()

    def _build_output(self):
        if self.tick != self.n_ticks:
            raise RuntimeError("Backtest has not finished")
        results = {}
        for bot, account in self.accounts.items():
            trades = [x for x in self.log.trades if x.bot_id == bot]
            quotes = [x for x in self.log.quotes if x.bot_id == bot]
            equity = [x for x in self.log.equity if x.bot_id == bot]
            history = self.equity_history[bot]
            per_asset = {a: sum(x.cash_change for x in trades if x.asset_id == a)
                            + account.positions.get(a, 0) * self.mark_prices[a] for a in self.markets}
            peak, drawdown = history[0], 0.0
            for value in history:
                peak = max(peak, value)
                drawdown = max(drawdown, peak - value)
            metrics = {k: {} for k in ("peak_abs_position", "buy_executions", "sell_executions",
                                       "per_asset_traded_volume", "average_spread", "ticks_clipped_by_risk")}
            for asset in self.markets:
                ts = [x for x in trades if x.asset_id == asset]
                qs = [x for x in quotes if x.asset_id == asset]
                spreads = [x.accepted_spread for x in qs if x.accepted_spread is not None]
                metrics["peak_abs_position"][asset] = max(abs(x.positions.get(asset, 0)) for x in equity)
                metrics["buy_executions"][asset] = sum(x.side == "buy" for x in ts)
                metrics["sell_executions"][asset] = sum(x.side == "sell" for x in ts)
                metrics["per_asset_traded_volume"][asset] = sum(x.quantity for x in ts)
                metrics["average_spread"][asset] = float(np.mean(spreads)) if spreads else None
                metrics["ticks_clipped_by_risk"][asset] = sum(x.error is None and
                    (x.accepted_bid_size < x.submitted_bid_size or x.accepted_ask_size < x.submitted_ask_size) for x in qs)
            times = [v / 1000 for v in {x.tick: x.runtime_ns for x in quotes}.values()]
            results[bot] = BotResult(
                bot_id=bot, pnl=history[-1] - history[0], final_equity=history[-1], final_cash=account.cash,
                final_positions={a: account.positions.get(a, 0) for a in self.markets}, per_asset_pnl=per_asset,
                fees_paid=account.fees_paid, fill_count=len(trades), traded_volume=sum(x.quantity for x in trades),
                max_drawdown=drawdown, equity_history=tuple(history), **metrics,
                median_runtime_us=float(np.median(times)) if times else None,
                p99_runtime_us=float(np.quantile(times, 0.99)) if times else None,
            )
        metadata = {**deepcopy(self.metadata), "valuation": "public_reference", "initial_cash": self.initial_cash,
                    "runtime_bucket_ns": self.runtime_bucket_ns, "assets": deepcopy(self.asset_configs),
                    "final_mark_prices": dict(self.mark_prices), "final_mark_age_ticks": dict(self.mark_age_ticks)}
        return SimulationOutput(SimulationResult(self.seed, self.n_ticks, results), self.log, metadata)
