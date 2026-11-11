import unittest
from engine.matching import MatchingEngine
from engine.risk import validate_quote
from engine.accounting import apply_fills, calculate_equity
from models.models import BookOrder, BotAccount, QuoteAction


class MatchingTests(unittest.TestCase):
    def setUp(self): self.engine = MatchingEngine("A")
    def order(self, oid, side, price, size, tif="GTC", owner="dealer", bot="D"):
        return BookOrder(oid, owner, bot, side, price, size, 0.0, self.engine._next_sequence(), tif)

    def test_price_then_time_then_sequence_and_partial_fill(self):
        e = self.engine
        e.submit_order(self.order("high", "sell", 100.05, 10))
        e.submit_order(self.order("low1", "sell", 100.03, 7))
        e.submit_order(self.order("low2", "sell", 100.03, 9))
        fills = e.submit_order(self.order("C", "buy", 100.04, 12, "IOC", "customer"))
        self.assertEqual([(f.sell_order_id, f.price, f.quantity) for f in fills], [("low1", 100.03, 7), ("low2", 100.03, 5)])
        self.assertEqual(e.orders["low2"].remaining, 4)
        self.assertNotIn("C", e.orders)

    def test_crossing_gtc_rests_remainder_and_ioc_does_not(self):
        e = self.engine
        e.submit_order(self.order("ask", "sell", 100.05, 4))
        buy = self.order("bid", "buy", 100.08, 7)
        fills = e.submit_order(buy)
        self.assertEqual([(f.price, f.quantity) for f in fills], [(100.05, 4)])
        self.assertEqual(e.orders["bid"].remaining, 3)
        self.assertEqual(e.submit_order(self.order("ioc", "sell", 100.10, 9, "IOC", "customer")), [])
        self.assertNotIn("ioc", e.orders)

    def test_cancel_bot_quotes_and_already_filled_cancel(self):
        e = self.engine
        e.submit_bot_quotes("one", QuoteAction(99.95, 5, 100.05, 5), 0)
        e.submit_order(self.order("C", "buy", 100.05, 2, "IOC", "customer"))
        e.cancel_bot_quotes("one")
        e.cancel_order("does_not_exist")
        self.assertEqual(e.orders, {})
        self.assertNotIn("one", e.bot_order_ids)

    def test_self_trade_prevention(self):
        e = self.engine
        e.submit_order(self.order("own", "sell", 100.0, 3, owner="bot", bot="one"))
        incoming = self.order("incoming", "buy", 100.1, 5, owner="bot", bot="one")
        self.assertEqual(e.submit_order(incoming), [])
        self.assertEqual(incoming.remaining, 0)
        self.assertEqual(e.orders["own"].remaining, 3)

    def test_snapshot_aggregated_top_five_and_detached(self):
        e = self.engine
        for i in range(7): e.submit_order(self.order(str(i), "buy", 100 - i * .01, i + 1))
        e.submit_order(self.order("extra", "buy", 100, 5))
        snapshot = e.get_book_snapshot()
        self.assertEqual(len(snapshot["bids"]), 5)
        self.assertEqual(snapshot["bids"][0]["quantity"], 6)
        self.assertIsNone(snapshot["mid"])
        snapshot["bids"][0]["quantity"] = 0
        self.assertEqual(e.get_book_snapshot()["bids"][0]["quantity"], 6)

    def test_liquidity_conservation(self):
        e = self.engine
        e.submit_bot_quotes("one", QuoteAction(99.95, 5, 100.05, 5), 0)
        e.submit_order(self.order("C", "buy", 100.05, 3, "IOC", "customer"))
        e.cancel_bot_quotes("one")
        s = e.get_liquidity_snapshot()
        self.assertEqual(s["provided"] - s["consumed"] - s["withdrawn"], s["depth"])

    def test_two_bot_accounts_and_fee_conservation(self):
        e = self.engine
        e.submit_bot_quotes("seller", QuoteAction(None, 0, 100.05, 4), 0)
        fills = e.submit_bot_quotes("buyer", QuoteAction(100.10, 4, None, 0), 0)
        accounts = {b: BotAccount() for b in ("buyer", "seller")}
        apply_fills(accounts, fills, 0.01)
        self.assertEqual(accounts["buyer"].positions["A"], 4)
        self.assertEqual(accounts["seller"].positions["A"], -4)
        self.assertAlmostEqual(sum(a.cash for a in accounts.values()), -.08)
        self.assertAlmostEqual(sum(calculate_equity(a, {"A":100}) for a in accounts.values()), -.08)

    def test_risk_clips_each_side_without_netting(self):
        config = dict(max_position=20, max_order_size=10, tick_size=.01)
        account = BotAccount(positions={"A":18, "B":-10})
        q = validate_quote(QuoteAction(99.9, 10, 100.1, 10), account, "A", config)
        self.assertEqual((q.bid_size, q.ask_size), (2,10))
        account.positions["A"] = 20
        self.assertIsNone(validate_quote(q, account, "A", config).bid_price)
        self.assertEqual(account.positions["B"], -10)

    def test_risk_rejects_malformed_quotes(self):
        config = dict(max_position=20, max_order_size=10, tick_size=.01)
        for q in (QuoteAction(100, -1, None, 0), QuoteAction(100, 1.5, None, 0),
                  QuoteAction(float('nan'), 1, None, 0), QuoteAction(99.995, 1, None, 0),
                  QuoteAction(100.1, 1, 100, 1)):
            with self.subTest(q=q), self.assertRaises((TypeError,ValueError)):
                validate_quote(q, BotAccount(), "A", config)
