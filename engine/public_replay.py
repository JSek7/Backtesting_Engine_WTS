"""Load the organiser's public events.csv + market_info.json training format.

No market generator, private price states, payload JSON, or private metadata is
required. Loading constructs one rewindable event stream per independent book.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path

from models.models import MarketEvent, MarketStep

PUBLIC_EVENT_COLUMNS = (
    "asset_id", "tick", "event_index", "time", "kind", "sequence",
    "dealer_id", "order_id", "side", "price", "limit_price", "quantity",
)
PUBLIC_ASSET_FIELDS = {
    "initial_price", "n_ticks", "tick_size", "max_position", "max_order_size",
    "fee_per_unit", "dt",
}
EVENT_KINDS = {"dealer_cancel", "dealer_limit", "customer_order"}


def _reject_constant(value):
    raise ValueError(f"Non-finite JSON value: {value}")


def _finite(value, name, *, positive=False):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{name} must be {'positive and ' if positive else ''}finite")
    return result


def _integer(value, name, minimum=0):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer >= {minimum}")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number != number.to_integral_value():
            raise ValueError
        result = int(number)
    except (InvalidOperation, ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{name} must be an integer >= {minimum}") from exc
    if result < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return result


def _identifier(value, name):
    # Do not coerce IDs to numbers: '01' and 'NA' are legitimate identifiers.
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")
    return value


def _read_info(path: Path):
    info = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=_reject_constant)
    allowed = {"schema_version", "initial_cash", "runtime_bucket_ns", "assets"}
    if not isinstance(info, dict) or set(info) != allowed or info["schema_version"] != 1:
        raise ValueError("Expected a version-1 PUBLIC market_info.json, not private scenario metadata")
    info["initial_cash"] = _finite(info["initial_cash"], "initial_cash")
    info["runtime_bucket_ns"] = _integer(info["runtime_bucket_ns"], "runtime_bucket_ns", 1)
    if not isinstance(info["assets"], dict) or not info["assets"]:
        raise ValueError("market_info.json must define at least one asset")
    for asset_id, config in info["assets"].items():
        _identifier(asset_id, "asset_id")
        if not isinstance(config, dict) or set(config) - PUBLIC_ASSET_FIELDS:
            raise ValueError(f"Unexpected/private asset configuration for {asset_id}")
        required = PUBLIC_ASSET_FIELDS - {"dt"}
        if required - set(config):
            raise ValueError(f"Missing public settings for {asset_id}: {sorted(required - set(config))}")
        for field in ("initial_price", "tick_size"):
            config[field] = _finite(config[field], field, positive=True)
        config["dt"] = _finite(config.get("dt", 1.0), "dt", positive=True)
        for field, minimum in (("n_ticks", 1), ("max_position", 0), ("max_order_size", 1)):
            config[field] = _integer(config[field], field, minimum)
        config["fee_per_unit"] = _finite(config["fee_per_unit"], "fee_per_unit")
    clocks = {(c["n_ticks"], c["dt"]) for c in info["assets"].values()}
    if len(clocks) != 1:
        raise ValueError("All assets must have the same n_ticks and dt")
    return info


class PublicReplayMarket:
    """One asset's fixed public orders, replayed once per decision interval."""

    def __init__(self, asset_id: str, config: dict, steps: tuple[MarketStep, ...]):
        self.asset_id = asset_id
        self.config = deepcopy(config)
        self._steps = deepcopy(steps)
        self.n_ticks = self.config["n_ticks"]
        if len(steps) != self.n_ticks:
            raise ValueError("Expected one MarketStep for every tick, including empty ticks")
        self.reset()

    def reset(self, seed=None, global_scenario=None):
        if global_scenario is not None:
            raise ValueError("A public tape is already fixed; do not supply a global scenario")
        self.tick = 0

    def step(self) -> MarketStep:
        if self.tick >= self.n_ticks:
            raise StopIteration("Backtest complete")
        result = deepcopy(self._steps[self.tick])
        self.tick += 1
        return result

    def get_public_state(self):
        return {"tick": self.tick}


def load_public_markets(directory: str | Path):
    """Return ({asset_id: PublicReplayMarket}, public_info, file_checksums).

    The pack must contain the complete event tape, not sampled book snapshots.
    Reads the combined CSV once and builds empty ticks from the declared horizon.
    """
    directory = Path(directory)
    info_path, events_path = directory / "market_info.json", directory / "events.csv"
    if not info_path.is_file() or not events_path.is_file():
        raise FileNotFoundError(f"{directory}: expected events.csv AND market_info.json")
    info = _read_info(info_path)
    by_asset = {asset: [[] for _ in range(c["n_ticks"])] for asset, c in info["assets"].items()}
    seen_order_ids = {asset: set() for asset in by_asset}

    with events_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("Missing or duplicate CSV column names")
        if set(reader.fieldnames) != set(PUBLIC_EVENT_COLUMNS):
            raise ValueError("Expected the public export columns only; do not supply private events/payload_json")
        for line, row in enumerate(reader, 2):
            try:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("Incorrect number of CSV cells")
                asset = row["asset_id"]
                if asset not in by_asset:
                    raise ValueError(f"Unknown asset {asset!r}")
                tick = _integer(row["tick"], "tick")
                if tick >= len(by_asset[asset]):
                    raise ValueError("Tick is outside the declared horizon")
                index = _integer(row["event_index"], "event_index")
                sequence = _integer(row["sequence"], "sequence")
                time = _finite(row["time"], "time")
                if not tick <= time <= tick + 1:
                    raise ValueError("Event time is outside its tick interval")
                kind = row["kind"]
                if kind not in EVENT_KINDS:
                    raise ValueError(f"Unknown event kind {kind!r}")
                if kind != "customer_order" and time != tick:
                    raise ValueError("This matching schedule requires dealer refreshes at the tick boundary")
                if kind == "dealer_cancel":
                    data = {"order_id": _identifier(row["order_id"], "order_id")}
                else:
                    side = row["side"]
                    if side not in ("buy", "sell"):
                        raise ValueError("Order side must be buy or sell")
                    price_field = "price" if kind == "dealer_limit" else "limit_price"
                    price = _finite(row[price_field], price_field, positive=True)
                    units = price / info["assets"][asset]["tick_size"]
                    if not math.isclose(units, round(units), rel_tol=0.0, abs_tol=1e-6):
                        raise ValueError("Event price is not on the asset tick grid")
                    data = {"side": side, price_field: price, "quantity": _integer(row["quantity"], "quantity", 1)}
                    if kind == "dealer_limit":
                        order_id = _identifier(row["order_id"], "order_id")
                        if order_id in seen_order_ids[asset] or order_id.startswith(("BOT:", "CUSTOMER:")):
                            raise ValueError("Dealer order ID is duplicated or uses a reserved prefix")
                        seen_order_ids[asset].add(order_id)
                        data.update(order_id=order_id, dealer_id=_identifier(row["dealer_id"], "dealer_id"))
                by_asset[asset][tick].append((index, MarketEvent(time, kind, data, sequence)))
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f"events.csv line {line}: {exc}") from exc

    markets = {}
    for asset, rows_by_tick in by_asset.items():
        steps = []
        for tick, rows in enumerate(rows_by_tick):
            rows.sort(key=lambda x: x[0])
            if [index for index, _ in rows] != list(range(len(rows))):
                raise ValueError(f"Asset {asset}, tick {tick}: missing/duplicate event_index")
            steps.append(MarketStep(tick, tick + 1, tuple(event for _, event in rows)))
        markets[asset] = PublicReplayMarket(asset, info["assets"][asset], tuple(steps))
    checksums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (info_path, events_path)}
    return markets, info, checksums
