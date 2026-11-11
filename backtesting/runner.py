"""Thin participant wrapper: public tape + fresh bots + shared execution rules."""
from __future__ import annotations
from copy import deepcopy
from functools import partial
import inspect
from pathlib import Path

from competition.bot_runner import BotRunner
from engine.public_replay import load_public_markets
from engine.simulator import SimulationRunner


def configure_factory(factory, asset_configs):
    """Supply public settings only when a bot CLASS explicitly accepts them.

    Zero-argument factories are used unchanged. Custom bots need not accept any
    constructor arguments; the get_quotes interface is the only required method.
    """
    if not callable(factory):
        raise TypeError("Pass a bot class or zero-argument factory, not an instance")
    if not inspect.isclass(factory):
        return factory
    parameters = inspect.signature(factory).parameters
    public_args = {
        "tick_sizes": {a: c["tick_size"] for a, c in asset_configs.items()},
        "position_limits": {a: c["max_position"] for a, c in asset_configs.items()},
        "max_order_sizes": {a: c["max_order_size"] for a, c in asset_configs.items()},
    }
    kwargs = {name: value for name, value in public_args.items() if name in parameters
              and parameters[name].kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)}
    return partial(factory, **kwargs)


class BacktestingRunner:
    def __init__(self, scenario_dir: str | Path, bots: dict, asset_ids: list[str] | None = None):
        self.scenario_dir = Path(scenario_dir)
        markets, info, checksums = load_public_markets(self.scenario_dir)
        if asset_ids is not None:
            if not asset_ids or len(asset_ids) != len(set(asset_ids)) or set(asset_ids) - set(markets):
                raise ValueError("Select unique asset IDs present in market_info.json")
            markets = {a: m for a, m in markets.items() if a in asset_ids}
        if not bots or any(not isinstance(bot, str) or not bot.strip() for bot in bots):
            raise ValueError("Supply at least one bot with a nonblank string ID")
        self.markets = markets
        self.market_info = info
        self.checksums = checksums
        self.asset_configs = {a: deepcopy(info["assets"][a]) for a in markets}
        self.bot_factories = {bot: configure_factory(factory, self.asset_configs) for bot, factory in bots.items()}
        self.last_output = None

    @property
    def assets(self):
        return tuple(self.markets)

    def run(self, seed=42):
        runners = {bot: BotRunner(bot, factory) for bot, factory in self.bot_factories.items()}
        for bot, runner in runners.items():
            if not callable(getattr(runner.bot, "get_quotes", None)):
                raise TypeError(f"Bot {bot!r} must implement get_quotes(observation, memory)")
        simulation = SimulationRunner(
            self.markets, runners, self.asset_configs,
            initial_cash=self.market_info["initial_cash"],
            runtime_bucket_ns=self.market_info["runtime_bucket_ns"],
            metadata={"scenario_name": self.scenario_dir.name, "source_checksums": self.checksums,
                      "selected_assets": list(self.markets), "mode": "public_replay"},
        )
        self.last_output = simulation.run(seed)
        return self.last_output
