"""TradSoc local participant backtester. Imports and executes trusted Python only."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import inspect
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
DEFAULT_SCENARIO = ROOT / "data" / "market_data" / "demo"
BACKTEST_RUNS_ROOT = ROOT / "data" / "runs"


def _bot_factory(specification):
    # Format matches the organiser CLI. rpartition also supports drive letters.
    if "=" not in specification:
        raise ValueError("--bot requires ID=path/to/bot.py:ClassName")
    bot_id, location = specification.split("=", 1)
    if not bot_id.strip() or not location.strip():
        raise ValueError("Bot ID and path must be nonblank")
    filename, separator, class_name = location.rpartition(":")
    if separator and class_name.isidentifier() and Path(filename).suffix.lower() == ".py":
        path = Path(filename)
    else:
        path, class_name = Path(location), ""
    if not path.is_file() or path.suffix.lower() != ".py":
        raise FileNotFoundError(f"Bot Python file not found: {path}")
    digest = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
    name = "tradsoc_local_bot_" + digest
    spec = spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if class_name:
        candidate = getattr(module, class_name, None)
    else:
        candidates = [cls for _, cls in inspect.getmembers(module, inspect.isclass)
                      if cls.__module__ == module.__name__ and not inspect.isabstract(cls)
                      and callable(getattr(cls, "get_quotes", None))]
        if len(candidates) != 1:
            raise ValueError("Specify :ClassName when the file has several strategy classes")
        candidate = candidates[0]
    if not inspect.isclass(candidate) or inspect.isabstract(candidate) or not callable(getattr(candidate, "get_quotes", None)):
        raise ValueError("Bot class must implement get_quotes(observation, memory)")
    return bot_id.strip(), candidate


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, help="Public pack directory with events.csv and market_info.json (default: data/market_data/demo)")
    parser.add_argument("--bot", action="append", metavar="ID=FILE.py:CLASS", help="Repeat for optional practice opponents; default: bots/my_bot.py:MyBot")
    parser.add_argument("--asset", action="append", help="Select an asset; repeat to select several (default: all)")
    parser.add_argument("--output", type=Path, help="NEW run directory; defaults to data/runs/backtest_<timestamp>")
    parser.add_argument("--no-charts", action="store_true", help="Save data and HTML tables without interactive charts or PNG exports")
    parser.add_argument("--no-csv", action="store_true", help="Save canonical JSON/JSONL only, not CSV convenience copies")
    parser.add_argument("--validate-only", action="store_true", help="Validate the public pack without importing or running a bot")
    parser.add_argument("--report", type=Path, metavar="SAVED_RUN", help="Rebuild reports from an existing local run without executing bots")
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        # Headless plots work on servers as well as local desktop machines.
        import matplotlib
        matplotlib.use("Agg")
        from reporting.reports import save_reports
        from storage.results import save_results, load_results
        if args.report is not None:
            if args.bot or args.scenario or args.asset or args.validate_only:
                raise ValueError("--report cannot be combined with simulation options")
            output = load_results(args.report)
            directory = args.output or args.report / "reports"
            for bot, path in save_reports(output, directory, not args.no_charts).items():
                print(f"{bot}: {path / 'report.html'}")
            return 0

        scenario = args.scenario or DEFAULT_SCENARIO
        if args.validate_only:
            from engine.public_replay import load_public_markets
            markets, info, _ = load_public_markets(scenario)
            print(f"Valid public pack: {len(markets)} assets, {next(iter(markets.values())).n_ticks} ticks")
            print("Assets:", ", ".join(markets))
            return 0
        directory = args.output or BACKTEST_RUNS_ROOT / ("backtest_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f"))
        if directory.exists():
            raise FileExistsError(f"Output already exists: {directory}. Choose a new directory.")
        print("Local trusted-code execution only. This is not a sandbox.")
        if scenario.resolve() == DEFAULT_SCENARIO.resolve():
            print("DEMO tape: tests installation only; not competition training data.")
        bots = {}
        specifications = args.bot or [f"mybot={ROOT / 'bots' / 'my_bot.py'}:MyBot"]
        for specification in specifications:
            bot_id, factory = _bot_factory(specification)
            if bot_id in bots:
                raise ValueError(f"Duplicate bot ID: {bot_id}")
            bots[bot_id] = factory
        from backtesting.runner import BacktestingRunner
        backtest = BacktestingRunner(scenario, bots, asset_ids=args.asset)
        output = backtest.run()
        save_results(output, directory, export_csv=not args.no_csv)
        reports = save_reports(output, directory / "reports", charts=not args.no_charts)
        print(f"Saved run: {directory}")
        print("PUBLIC-reference results; not the official evaluation score.")
        print(f"{'Bot':<20} {'Local P&L':>14} {'Drawdown':>14} {'Fills':>10} {'Errors':>10}")
        for bot, result in output.results.bot_results.items():
            count = sum(error.bot_id == bot for error in output.log.errors)
            print(f"{bot:<20} {result.pnl:14.4f} {result.max_drawdown:14.4f} {result.fill_count:10d} {count:10d}")
            print(f"  Report: {reports[bot] / 'report.html'}")
        return 0
    except (ValueError, TypeError, KeyError, OSError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
