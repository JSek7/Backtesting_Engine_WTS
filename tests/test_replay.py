import csv
import json
from pathlib import Path
import tempfile
import unittest
from engine.public_replay import load_public_markets, PUBLIC_EVENT_COLUMNS
from tests.support import event, simple_rows, write_pack


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()

    def test_empty_ticks_and_stop(self):
        write_pack(self.path)
        markets, _, _ = load_public_markets(self.path)
        market = markets["A"]
        for t in range(3):
            step = market.step()
            self.assertEqual((step.start_time, step.end_time, step.events), (t, t + 1, ()))
        with self.assertRaises(StopIteration): market.step()
        self.assertFalse(hasattr(market, "fair_price"))

    def test_reset_is_exact_and_events_are_copies(self):
        write_pack(self.path, simple_rows())
        market = load_public_markets(self.path)[0]["A"]
        original = market.step()
        market.reset(seed=999)
        self.assertEqual(market.step(), original)
        original.events[0].data["quantity"] = 999
        market.reset()
        self.assertEqual(market.step().events[0].data["quantity"], 20)
        with self.assertRaises(ValueError): market.reset(global_scenario=object())

    def test_preserves_string_ids_and_asset_namespaces(self):
        rows = [event(0, 0, "dealer_limit", a, dealer_id="NA", order_id="001", side="buy", price=99.99, quantity="4.0") for a in ("01", "NA")]
        write_pack(self.path, rows, assets=("01", "NA"))
        markets, _, _ = load_public_markets(self.path)
        self.assertEqual(tuple(markets), ("01", "NA"))
        for market in markets.values():
            self.assertEqual(market.step().events[0].data["dealer_id"], "NA")
            market.reset()
            self.assertEqual(market.step().events[0].data["order_id"], "001")

    def test_out_of_order_rows_reordered_by_event_index(self):
        write_pack(self.path, list(reversed(simple_rows())))
        step = load_public_markets(self.path)[0]["A"].step()
        self.assertEqual([e.kind for e in step.events], ["dealer_limit", "dealer_limit", "customer_order"])

    def test_bad_fields_fail_with_line_number(self):
        for change in (dict(quantity=-1), dict(price="NaN"), dict(side="BUY"), dict(tick=4), dict(price=99.999), dict(time=0.5)):
            row = event(0, 0, "dealer_limit", dealer_id="D", order_id="D1", side="buy", price=99.99, quantity=5)
            row.update(change)
            write_pack(self.path, [row])
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "line 2"):
                load_public_markets(self.path)

    def test_duplicate_indices_and_order_ids_rejected(self):
        base = event(0, 0, "dealer_limit", dealer_id="D", order_id="D1", side="buy", price=99.99, quantity=5)
        for second in ({**base, "order_id": "D2"}, {**base, "event_index": 1}):
            write_pack(self.path, [base, second])
            with self.assertRaises(ValueError): load_public_markets(self.path)

    def test_private_columns_and_private_metadata_rejected(self):
        write_pack(self.path)
        (self.path / "events.csv").write_text(",".join(PUBLIC_EVENT_COLUMNS) + ",payload_json\n")
        with self.assertRaises(ValueError): load_public_markets(self.path)
        write_pack(self.path)
        info = json.loads((self.path / "market_info.json").read_text())
        info["assets"]["A"]["private_parameter"] = 123
        (self.path / "market_info.json").write_text(json.dumps(info))
        with self.assertRaises(ValueError): load_public_markets(self.path)

    def test_clock_mismatch_rejected(self):
        write_pack(self.path, assets=("A", "B"))
        info = json.loads((self.path / "market_info.json").read_text())
        info["assets"]["B"]["n_ticks"] = 4
        (self.path / "market_info.json").write_text(json.dumps(info))
        with self.assertRaises(ValueError): load_public_markets(self.path)

    def test_demo_loads(self):
        root = Path(__file__).resolve().parents[1]
        markets, info, hashes = load_public_markets(root / "data/market_data/demo")
        self.assertEqual(set(markets), {"A", "B", "C"})
        self.assertEqual(info["assets"]["A"]["n_ticks"], 80)
        self.assertEqual(len(hashes["events.csv"]), 64)
