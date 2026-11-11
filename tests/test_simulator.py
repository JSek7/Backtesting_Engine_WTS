from pathlib import Path
import tempfile
import unittest
from models.models import QuoteAction
from tests.support import FixedRunner, empty_policy, event, simple_rows, simulation, write_pack


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()

    def test_golden_fills_cash_and_no_future_observation(self):
        write_pack(self.path, simple_rows())
        def policy(obs):
            return {"A": QuoteAction(99.95,5,100.05,5)} if obs.tick == 0 else {}
        runner = FixedRunner("mine", policy)
        s = simulation(self.path, {"mine":runner})
        out = s.run()
        trades = out.log.trades
        self.assertEqual(len(trades), 1)
        self.assertEqual((trades[0].side,trades[0].quantity,trades[0].price), ("sell",5,100.05))
        self.assertAlmostEqual(out.results.bot_results["mine"].final_cash, 500.2)
        self.assertAlmostEqual(out.results.bot_results["mine"].pnl, .2)
        self.assertEqual(runner.observations[0].markets["A"].price_history,(100.0,))
        self.assertEqual(runner.observations[0].markets["A"].book["asks"], [])
        self.assertEqual(len(runner.observations[1].markets["A"].recent_fills),1)
        self.assertEqual(runner.observations[2].markets["A"].recent_fills,())
        self.assertNotIn("mine", s.matching["A"].bot_order_ids)
        self.assertEqual(out.log.books[0].liquidity["customer_unfilled"],3)

    def test_crossing_bot_uses_fresh_not_stale_dealer_quotes(self):
        rows = simple_rows()
        # Ignore initial customer, then move the dealer ask well above the old one.
        rows = [r for r in rows if r["kind"] != "customer_order"]
        for r in rows:
            if r["order_id"]=="ask1": r["price"]=100.50
        # Reindex after removing rows.
        for t in (0,1):
            for i,r in enumerate(r for r in rows if r["tick"]==t): r["event_index"]=i
        write_pack(self.path,rows)
        runner=FixedRunner("mine",lambda obs:{"A":QuoteAction(100.2,5,None,0)} if obs.tick==1 else {})
        output=simulation(self.path,{"mine":runner}).run()
        self.assertEqual(output.log.trades,[])

    def test_runtime_size_priority_is_per_side(self):
        rows=[event(0,0,"customer_order",time=.2,side="buy",limit_price=101,quantity=8),
              event(0,1,"customer_order",time=.3,side="sell",limit_price=99,quantity=8)]
        write_pack(self.path,rows,ticks=1,fee=0)
        bots={"alpha":FixedRunner("alpha",lambda o:{"A":QuoteAction(99.95,8,100.05,1)}),
              "beta":FixedRunner("beta",lambda o:{"A":QuoteAction(99.95,1,100.05,8)})}
        out=simulation(self.path,bots).run()
        self.assertEqual([(t.bot_id,t.side,t.quantity) for t in out.log.trades],[("beta","sell",8),("alpha","buy",8)])

    def test_assets_have_separate_orderbooks_and_one_account(self):
        write_pack(self.path,simple_rows("A")+simple_rows("B"),assets=("A","B"))
        bot=FixedRunner("mine",lambda o:{a:QuoteAction(99.95,5,100.05,5) for a in o.markets} if o.tick==0 else {})
        out=simulation(self.path,{"mine":bot}).run()
        result=out.results.bot_results["mine"]
        self.assertEqual(result.final_positions,{"A":-5,"B":-5})
        self.assertAlmostEqual(result.pnl,.4)
        self.assertAlmostEqual(sum(result.per_asset_pnl.values()),result.pnl)
        self.assertTrue(all(len(o.markets)==2 for o in bot.observations))

    def test_marks_carry_forward_but_price_history_keeps_none(self):
        rows=[event(0,0,"dealer_limit",dealer_id="D",order_id="b",side="buy",price=100.9,quantity=1),
              event(0,1,"dealer_limit",dealer_id="D",order_id="a",side="sell",price=101.1,quantity=1),
              event(1,0,"dealer_cancel",order_id="a")]
        write_pack(self.path,rows)
        runner=FixedRunner("mine",empty_policy)
        out=simulation(self.path,{"mine":runner}).run()
        self.assertEqual(runner.observations[2].markets["A"].price_history,(100.0,101.0,None))
        self.assertEqual(out.log.equity[-1].mark_prices["A"],101.0)
        self.assertEqual(out.log.equity[-1].mark_age_ticks["A"],2)

    def test_invalid_quote_rejected_without_stopping_other_assets(self):
        write_pack(self.path,[],assets=("A","B"))
        bot=FixedRunner("bad",lambda o:{"A":QuoteAction(float('nan'),1,None,0),"B":QuoteAction(99,1,101,1)})
        out=simulation(self.path,{"bad":bot}).run()
        self.assertEqual(len(out.log.errors),3)
        self.assertEqual([q.accepted_bid_size for q in out.log.quotes if q.asset_id=="A"],[0,0,0])
        self.assertEqual([q.accepted_bid_size for q in out.log.quotes if q.asset_id=="B"],[1,1,1])

    def test_all_observations_are_prebuilt_and_independent(self):
        write_pack(self.path,[])
        def mutate(obs):
            obs.markets["A"].book["bids"].append({"price":999,"quantity":9})
            return {}
        first=FixedRunner("a",mutate);second=FixedRunner("b",empty_policy)
        simulation(self.path,{"a":first,"b":second}).run()
        self.assertEqual(second.observations[0].markets["A"].book["bids"],[])

    def test_repeated_fixed_timing_runs_match_and_snapshots_stay_detached(self):
        write_pack(self.path,simple_rows())
        bot=FixedRunner("mine",lambda o:{"A":QuoteAction(99.95,5,100.05,5)})
        s=simulation(self.path,{"mine":bot})
        a,b=s.run(),s.run()
        self.assertEqual(a,b)
        s.matching["A"].reset()
        self.assertTrue(a.log.books[0].pre_customer["asks"])
        with self.assertRaises(StopIteration): s.step()
