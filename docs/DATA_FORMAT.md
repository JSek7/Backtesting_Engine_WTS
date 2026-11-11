# Public training pack format (schema version 1)

A pack has one combined `events.csv`, one `market_info.json`, and optionally a
human-readable README. This matches the organiser's participant-data exporter.
No per-asset private states or JSON event payloads are needed.

## `market_info.json`

Example only; the organiser's pack supplies the rules for your run:

```json
{
  "schema_version": 1,
  "initial_cash": 0.0,
  "runtime_bucket_ns": 100000,
  "assets": {
    "A": {
      "initial_price": 100.0,
      "n_ticks": 10000,
      "tick_size": 0.01,
      "max_position": 50,
      "max_order_size": 20,
      "fee_per_unit": 0.0,
      "dt": 1.0
    }
  }
}
```

Every selected asset shares the same horizon and `dt`. Event `time` is expressed
in tick units; a boundary advances from integer `t` to `t+1`, not by `dt`.
`dt` is descriptive for the recorded scenario, not a replay clock multiplier.
The loader accepts only these public settings. It rejects unknown fields rather
than accidentally carrying private metadata into reports. Asset IDs are strings.

## `events.csv`

Required columns (column order may differ):

```text
asset_id,tick,event_index,time,kind,sequence,dealer_id,order_id,side,price,limit_price,quantity
```

| Event kind | Required payload fields |
| --- | --- |
| `dealer_cancel` | `order_id` |
| `dealer_limit` | `dealer_id`, `order_id`, `side`, `price`, `quantity` |
| `customer_order` | `side`, `limit_price`, `quantity` |

Common fields specify the asset, zero-based tick, original event index within
that asset/tick, timestamp and generator sequence. Non-applicable payload cells
are blank. Prices are positive, finite and on the asset's price grid; quantities
are positive whole units. Dealer order IDs must be unique within their asset and
must not use reserved `BOT:` or `CUSTOMER:` prefixes. Reusing the same ID in two
different assets is allowed. Preserve strings such as `01` and `NA` literally.

Rows are grouped by asset/tick and sorted using `event_index`; each nonempty group
must have consecutive indices `0..n-1`. Ticks with no rows are valid and replay as
empty `MarketStep` objects. The metadata, not the final CSV row, determines how
many ticks are replayed. Dealer cancellations/additions belong to the integer
tick boundary. Customer timestamps may be fractional; bots cannot respond again
within that interval. The loader preserves original numeric prices and IDs.

The simulator still applies its phase ordering: cancel old bot quotes, cancel
scheduled dealer orders, refresh dealers, submit bots, then execute customers.
Within dealer phases it preserves event-index order; customer execution order is
`(time, sequence)`. Never execute the entire mixed event tape before submitting
bot quotes, or customers would get an unintended head start.

## What can be reproduced

This is an **order-event tape**, not a historical series of fills. Repeated runs
have the same external orders, but quotes, partial fills, depth and accounts
are recomputed. Different opponents or timing priorities can change executions.
Exact execution parity with the organiser engine requires identical rules,
initial state, bot decisions and scheduling. Diagnostic customer labels are not
present, and missing labels are not guessed.

The files do not determine the official final valuation. Local marks come from
the dealer-only midpoint measured before the current tick's bot submissions.
At boundary `t+1`, use the reference from interval `t`, or the last available
reference if this interval has no two-sided dealer book. Initial marks are the
public initial prices. No future reference is used to fill a missing past mark.

Do not confuse `events.csv` with `quotes.csv`, `books.jsonl` or `trades.csv` from
a finished backtest. Those are strategy-dependent output, not scenario input.
