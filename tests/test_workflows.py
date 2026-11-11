from pathlib import Path
from importlib.util import find_spec
import json
import subprocess
import sys
import tempfile
import unittest
import matplotlib
matplotlib.use("Agg")
from backtesting.runner import BacktestingRunner
from bots.my_bot import MyBot
from bots.example_bot import ExampleBot
from competition.bot_runner import BotRunner
from models.models import Observation, QuoteAction
from reporting.reports import generate_report, save_reports
from storage.results import save_results, load_results
from tests.support import FixedRunner, empty_policy, simple_rows, simulation, write_pack

ROOT=Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()

    def output(self):
        pack=write_pack(self.path/'pack',simple_rows())
        bot=FixedRunner('mine',lambda o:{'A':QuoteAction(99.95,5,100.05,5)} if o.tick==0 else {})
        return simulation(pack,{'mine':bot}).run()

    def test_save_reload_exact_and_no_overwrite(self):
        output=self.output();dest=save_results(output,self.path/'run')
        self.assertEqual(load_results(dest),output)
        with self.assertRaises(FileExistsError):save_results(output,dest)
        self.assertTrue((dest/'trades.csv').is_file())

    def test_zero_trades_keep_table_schema(self):
        pack=write_pack(self.path/'pack')
        output=simulation(pack,{'silent':FixedRunner('silent',empty_policy)}).run()
        dest=save_results(output,self.path/'empty')
        report=generate_report(load_results(dest))
        self.assertTrue(report.trades.empty)
        self.assertIn('price',report.trades.columns)
        self.assertTrue((dest/'trades.csv').read_text().startswith('tick,time,'))
        self.assertEqual(report.timeline.filled_quantity.tolist(),[0,0,0])

    def test_rejected_nan_does_not_break_saving(self):
        pack=write_pack(self.path/'pack')
        bot=FixedRunner('bad',lambda o:{'A':QuoteAction(float('nan'),1,None,0)})
        output=simulation(pack,{'bad':bot}).run()
        loaded=load_results(save_results(output,self.path/'run'))
        self.assertEqual(len(loaded.log.errors),3)
        self.assertIsInstance(loaded.log.quotes[0].submitted_bid,str)

    def test_private_archive_not_accepted(self):
        dest=self.path/'bad';dest.mkdir()
        (dest/'summary.json').write_text(json.dumps({'schema_version':1,'valuation':'private'}))
        with self.assertRaises(ValueError):load_results(dest)

    def test_reports_data_and_charts(self):
        output=self.output();report=generate_report(output,'mine')
        self.assertEqual(report.timeline.filled_quantity.tolist(),[5,0,0])
        self.assertAlmostEqual(report.asset_pnl.iloc[-1].pnl,output.results.bot_results['mine'].pnl)
        paths=report.save_charts(self.path/'charts')
        self.assertEqual(len(paths),4)
        self.assertTrue(all(p.read_bytes().startswith(b'\x89PNG') for p in paths))
        page=report.save_html(self.path/'report.html',paths)
        text=page.read_text(encoding='utf-8')
        self.assertIn('data:image/png;base64,',text)
        self.assertIn('Plotly.newPlot',text)
        self.assertIn('not an official score',text)

    def test_multi_asset_runner_injects_public_grids(self):
        runner=BacktestingRunner(ROOT/'data/market_data/demo',{'example':ExampleBot})
        output=runner.run()
        self.assertEqual(output.log.errors,[])
        self.assertEqual(set(output.results.bot_results['example'].final_positions),{'A','B','C'})

    def test_bot_memory_persists_and_resets_instance(self):
        class Stateful:
            def __init__(self):self.calls=0
            def get_quotes(self,obs,memory):
                self.calls+=1
                memory['calls']=memory.get('calls',0)+1
                return {},memory
        runner=BotRunner('state',Stateful)
        runner.run(Observation(0,{},0));runner.run(Observation(1,{},0))
        self.assertEqual(runner.memory['calls'],2)
        runner.reset()
        self.assertEqual(runner.memory,{})
        self.assertEqual(runner.bot.calls,0)

    def test_failed_memory_update_not_committed(self):
        class Broken:
            def get_quotes(self,obs,memory):
                memory['bad']=True
                raise ValueError('broken')
        runner=BotRunner('bad',Broken)
        with self.assertRaises(ValueError):runner.run(Observation(0,{},0))
        self.assertEqual(runner.memory,{})

    def test_cli_backtest_report_and_validate(self):
        dest=self.path/'cli'
        result=subprocess.run([sys.executable,'run_backtest.py','--output',str(dest),'--no-charts'],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('not the official',result.stdout)
        self.assertTrue(list((dest/'reports').rglob('report.html')))
        report=subprocess.run([sys.executable,'run_backtest.py','--report',str(dest),'--no-charts'],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(report.returncode,0,report.stderr)
        valid=subprocess.run([sys.executable,'run_backtest.py','--validate-only'],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(valid.returncode,0,valid.stderr)

    def test_mybot_has_no_errors_and_safe_positions(self):
        output=BacktestingRunner(ROOT/'data/market_data/demo',{'mine':MyBot}).run()
        self.assertEqual(output.log.errors,[])
        self.assertTrue(all(abs(t.position_after)<=20 for t in output.log.trades))
        result=output.results.bot_results['mine']
        self.assertAlmostEqual(result.pnl,sum(result.per_asset_pnl.values()))

    @unittest.skipUnless(find_spec("bots.compiled._inventory_core"), "No compatible InventoryBot binary supplied")
    def test_compiled_inventory_wrapper_and_multi_bot_cli(self):
        from bots.inventory_bot import InventoryBot

        self.assertEqual(InventoryBot.__module__, "bots.compiled._inventory_core")
        runner=BacktestingRunner(ROOT/'data/market_data/demo',{'inventory':InventoryBot})
        configured=runner.bot_factories['inventory']()
        self.assertEqual(configured.tick_sizes,{a:c['tick_size'] for a,c in runner.asset_configs.items()})
        self.assertEqual(configured.position_limits,{a:c['max_position'] for a,c in runner.asset_configs.items()})
        dest=self.path/'compiled_cli'
        result=subprocess.run([sys.executable,'run_backtest.py','--bot','mine=bots/my_bot.py:MyBot',
                               '--bot','inventory=bots/inventory_bot.py:InventoryBot',
                               '--output',str(dest),'--no-charts'],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        output=load_results(dest)
        self.assertEqual(set(output.results.bot_results),{'mine','inventory'})
        self.assertEqual(output.log.errors,[])
        self.assertEqual(len(list((dest/'reports').rglob('report.html'))),2)
