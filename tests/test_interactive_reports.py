"""Interactive charts preserve public data and work as standalone HTML."""

from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import unittest

from models.models import QuoteAction
from reporting.reports import generate_report, save_reports
from tests.support import FixedRunner, empty_policy, simple_rows, simulation, write_pack


class ScriptSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('src'):
            self.sources.append(dict(attrs)['src'])


class InteractiveReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        pack = write_pack(self.path / 'pack', simple_rows())
        runner = FixedRunner('mine', lambda obs: {'A': QuoteAction(99.95, 5, 100.05, 5)} if obs.tick == 0 else {})
        self.output = simulation(pack, {'mine': runner}).run()
        self.report = generate_report(self.output, 'mine')

    def test_interactive_data_matches_saved_fills_and_public_equity(self):
        figure = self.report.plot_diagnostics()
        traces = figure.data
        pnl = next(trace for trace in traces if trace.meta['kind'] == 'pnl')
        self.assertEqual(list(pnl.x), self.report.equity.tick.tolist())
        self.assertEqual(list(pnl.y), self.report.equity.pnl.tolist())
        fill = next(trace for trace in traces if trace.meta['kind'] == 'fills' and len(trace.x))
        self.assertEqual(list(fill.x), self.report.trades.time.tolist())
        self.assertEqual(list(fill.y), self.report.trades.price.tolist())
        self.assertEqual(fill.customdata[0][0], self.report.trades.quantity.iloc[0])
        self.assertEqual(figure.layout.xaxis.matches, 'x5')
        self.assertTrue(figure.layout.xaxis5.rangeslider.visible)
        self.assertIsNone(figure.layout.width)

    def test_one_sided_and_missing_quotes_remain_gaps(self):
        pack = write_pack(self.path / 'silent')
        output = simulation(pack, {'silent': FixedRunner('silent', empty_policy)}).run()
        figure = json.loads(generate_report(output).plot_diagnostics().to_json())
        price_lines = [trace for trace in figure['data'] if trace['meta']['kind'] in ('accepted_bid', 'accepted_ask', 'spread')]
        self.assertTrue(price_lines)
        for trace in price_lines:
            self.assertEqual(trace['y'], [None, None, None])
            self.assertFalse(trace['connectgaps'])

    def test_html_embeds_interactive_runtime_without_external_scripts(self):
        self.report.bot_id = '<script>alert(1)</script>'
        page = self.report.save_html(self.path / 'interactive.html')
        text = page.read_text(encoding='utf-8')
        parser = ScriptSources()
        parser.feed(text)
        self.assertEqual(parser.sources, [])
        self.assertIn('Plotly.newPlot', text)
        self.assertIn('"scrollZoom": true', text)
        self.assertIn('"responsive": true', text)
        self.assertIn("graph.on('plotly_relayout'", text)
        self.assertNotIn('<script>alert(1)</script>', text)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', text)

    def test_no_charts_writes_tables_without_javascript_or_pngs(self):
        directory = save_reports(self.output, self.path / 'tables', charts=False)['mine']
        text = (directory / 'report.html').read_text(encoding='utf-8')
        self.assertIn('First 100 trades', text)
        self.assertNotIn('<script', text)
        self.assertNotIn('Plotly.newPlot', text)
        self.assertFalse((directory / 'charts').exists())

    def test_empty_report_has_valid_interactive_figure(self):
        for name in ('quotes', 'trades', 'equity'):
            setattr(self.report, name, getattr(self.report, name).iloc[:0])
        figure = self.report.plot_diagnostics()
        self.assertEqual(len(figure.layout.annotations), 3)
        self.assertEqual(list(figure.data[0].x), [])
        self.assertIn('Plotly.newPlot', self.report.save_html(self.path / 'empty.html').read_text(encoding='utf-8'))
