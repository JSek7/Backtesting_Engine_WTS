"""Save/reload public-reference runs. Adapted from organiser storage/results.py.

Canonical JSONL preserves nested records. CSV is an optional tabular convenience.
This local format is intentionally distinct from private organiser archives.
"""
from __future__ import annotations
import csv
import json
import math
import shutil
import tempfile
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import Any
from models.models import Fill
from models.results import BookRecord, BotErrorRecord, BotResult, EquityRecord, QuoteRecord, RunLog, SimulationOutput, SimulationResult, TradeRecord

SCHEMA_VERSION = 1
FORMAT = "tradsoc_public_backtest"
RECORD_MODELS = {"quotes": QuoteRecord, "books": BookRecord, "trades": TradeRecord,
                 "fills": Fill, "equity": EquityRecord, "errors": BotErrorRecord}
CSV_EXPORTS = ("quotes", "trades", "equity", "errors")


def _json_default(value: Any):
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item") and callable(value.item):
        return value.item()
    raise TypeError(f"Cannot serialise {type(value).__name__}")


def _encode(value):
    return json.dumps(value, default=_json_default, allow_nan=False, separators=(",", ":"))


def _record_data(record):
    data = asdict(record)
    if isinstance(record, QuoteRecord):
        for key in ("submitted_bid", "submitted_bid_size", "submitted_ask", "submitted_ask_size"):
            value = data[key]
            if isinstance(value, float) and not math.isfinite(value):
                data[key] = str(value)
    return data


def _write_jsonl(path, records):
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            if not is_dataclass(record) or isinstance(record, type):
                raise TypeError("Expected a dataclass record")
            handle.write(_encode(_record_data(record)) + "\n")


def _write_csv(path, records, record_type):
    columns = [field.name for field in fields(record_type)]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            row = _record_data(record)
            for key, value in row.items():
                if isinstance(value, (dict, list, tuple)):
                    row[key] = _encode(value)
                elif isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
                    row[key] = "'" + value  # Prevent formulas in spreadsheet viewers.
            writer.writerow(row)


def save_results(output: SimulationOutput, directory: str | Path, export_csv=True, metadata=None) -> Path:
    if output.results.valuation != "public_reference":
        raise ValueError("This writer accepts public-reference runs only")
    destination = Path(directory)
    if destination.exists():
        raise FileExistsError(f"Run output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}_tmp_", dir=destination.parent))
    try:
        summary = {"format": FORMAT, "schema_version": SCHEMA_VERSION, **asdict(output.results)}
        (temporary / "summary.json").write_text(json.dumps(summary, indent=2, default=_json_default, allow_nan=False) + "\n", encoding="utf-8")
        (temporary / "metadata.json").write_text(json.dumps({**(metadata or {}), **output.metadata}, indent=2, default=_json_default, allow_nan=False) + "\n", encoding="utf-8")
        for name, model in RECORD_MODELS.items():
            records = getattr(output.log, name)
            _write_jsonl(temporary / f"{name}.jsonl", records)
            if export_csv and name in CSV_EXPORTS:
                _write_csv(temporary / f"{name}.csv", records, model)
        if destination.exists():
            raise FileExistsError(f"Run output already exists: {destination}")
        temporary.rename(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination


def _invalid_constant(value):
    raise ValueError(f"Non-finite JSON constant: {value}")


def _read_jsonl(path, model):
    result = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                result.append(model(**json.loads(line, parse_constant=_invalid_constant)))
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError(f"Invalid {model.__name__} in {path.name} at line {number}") from exc
    return result


def load_run_metadata(directory):
    path = Path(directory) / "metadata.json"
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=_invalid_constant) if path.exists() else {}


def load_results(directory: str | Path) -> SimulationOutput:
    source = Path(directory)
    data = json.loads((source / "summary.json").read_text(encoding="utf-8"), parse_constant=_invalid_constant)
    if data.get("format") != FORMAT or data.get("schema_version") != SCHEMA_VERSION or data.get("valuation") != "public_reference":
        raise ValueError("Not a supported public-reference backtest archive")
    bots = {bot: BotResult(**{**record, "equity_history": tuple(record["equity_history"])})
            for bot, record in data["bot_results"].items()}
    result = SimulationResult(data["seed"], data["n_ticks"], bots, data["valuation"])
    log = RunLog(**{name: _read_jsonl(source / f"{name}.jsonl", model) for name, model in RECORD_MODELS.items()})
    return SimulationOutput(result, log, load_run_metadata(source))
