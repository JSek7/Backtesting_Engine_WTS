import csv
import json
from pathlib import Path
from engine.public_replay import PUBLIC_EVENT_COLUMNS, load_public_markets
from engine.simulator import SimulationRunner
from models.models import BotSubmission, QuoteAction


def write_pack(directory, rows=(), assets=("A",), ticks=3, fee=0.01):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    info = {"schema_version": 1, "initial_cash": 0.0, "runtime_bucket_ns": 100000,
            "assets": {a: {"initial_price": 100.0, "n_ticks": ticks, "tick_size": 0.01,
                            "max_position": 20, "max_order_size": 10, "fee_per_unit": fee, "dt": 1.0} for a in assets}}
    (directory / "market_info.json").write_text(json.dumps(info), encoding="utf-8")
    with (directory / "events.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PUBLIC_EVENT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return directory


def event(tick, index, kind, asset="A", **kwargs):
    row = dict.fromkeys(PUBLIC_EVENT_COLUMNS, "")
    row.update(asset_id=asset, tick=tick, event_index=index, time=tick, sequence=index, kind=kind)
    row.update(kwargs)
    return row


def simple_rows(asset="A"):
    return [
        event(0, 0, "dealer_limit", asset, dealer_id="D", order_id="old_bid", side="buy", price=99.9, quantity=20),
        event(0, 1, "dealer_limit", asset, dealer_id="D", order_id="old_ask", side="sell", price=100.1, quantity=20),
        event(0, 2, "customer_order", asset, time=0.5, side="buy", limit_price=100.08, quantity=8),
        event(1, 0, "dealer_cancel", asset, order_id="old_bid"),
        event(1, 1, "dealer_cancel", asset, order_id="old_ask"),
        event(1, 2, "dealer_limit", asset, dealer_id="D", order_id="bid1", side="buy", price=99.94, quantity=20),
        event(1, 3, "dealer_limit", asset, dealer_id="D", order_id="ask1", side="sell", price=100.06, quantity=20),
        event(1, 4, "customer_order", asset, time=1.5, side="sell", limit_price=99.93, quantity=5),
    ]


class FixedRunner:
    """Test-only clock; never use mocked timing for competition evaluation."""
    def __init__(self, bot_id, policy, runtime=1000):
        self.bot_id, self.policy, self.runtime = bot_id, policy, runtime
        self.reset()
    def reset(self):
        self.observations = []
    def run(self, observation):
        self.observations.append(observation)
        return BotSubmission(self.bot_id, self.policy(observation), self.runtime)


def simulation(directory, runners):
    markets, info, _ = load_public_markets(directory)
    return SimulationRunner(markets, runners, info["assets"], info["runtime_bucket_ns"], info["initial_cash"])


def empty_policy(observation):
    return {}
