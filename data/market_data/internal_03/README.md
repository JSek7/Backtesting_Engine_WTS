# Public training market tape

`events.csv` combines all assets in one fixed background market scenario.
It contains orders/cancellations, not executed trades or a particular bot's
results. It has no bot submissions, fills, inventories, or performance data.
`market_info.json` contains public initial conditions, tick sizes and rules.

## Load in pandas

```python
import json
import pandas as pd

events = pd.read_csv(
    "events.csv", float_precision="round_trip", keep_default_na=False,
    na_values={name: [""] for name in ("price", "limit_price", "quantity")},
    converters={name: str for name in ("asset_id", "dealer_id", "order_id")},
)
with open("market_info.json", encoding="utf-8") as f:
    market_info = json.load(f)

asset_a = events.loc[events["asset_id"] == "A"]
dealer_quotes = events.loc[events["kind"] == "dealer_limit"]
```

## Columns

| Column | Meaning |
| --- | --- |
| asset_id | Asset/book identifier; keep separate books per asset. |
| tick | Zero-based decision interval [tick, tick + 1]. |
| event_index | Original event order within that tick and asset. |
| time | Event time in tick units, including fractional customer arrival times. |
| kind | dealer_cancel, dealer_limit, or customer_order. |
| sequence | Generator tie-breaker for events at the same time. |
| dealer_id | Dealer identifier, where applicable. |
| order_id | Dealer order identifier; scoped to its asset, not globally unique. |
| side | buy or sell, from the incoming order's perspective. |
| price | Dealer limit price; blank for other event types. |
| limit_price | Customer limit price; blank for other event types. |
| quantity | Submitted size; blank for cancellations. |

Blank cells mean not applicable. A cancellation identifies its target by
asset_id and order_id. Customer orders have no persistent order_id.
Rows are sorted by tick, asset_id, event_index. Asset order in the combined
file is only a presentation order, not a cross-asset execution sequence.

## Replay timing and matching

Start with empty books, zero inventory, and the supplied initial cash. Every
asset's initial_price is public and starts its reference-price history.
For each tick:

1. Call every bot once BEFORE applying this tick's events. Give it the previous
   completed books, reference history, cash, positions and its recent fills.
   Never give it future rows from this historical training tape during a run.
2. For each asset, cancel all remaining bot quotes from the previous tick.
3. Apply dealer_cancel events, then dealer_limit events, retaining event_index
   order within each phase. Dealer limits are GTC and can match immediately.
4. Compute the dealer-only best bid/ask midpoint before inserting bot orders.
   If either side is missing, this tick's reference is missing.
5. Validate and clip bot quotes, then submit them. Valid prices must be positive
   and on the tick grid; active bids must be below active asks. Each side is
   capped at max_order_size and its available position headroom. Invalid quotes
   are rejected. Multi-bot submission priority sorts by runtime bucket (measured
   nanoseconds // runtime_bucket_ns), descending accepted side size, bot ID,
   then side. Each side is a separate submission.
6. Capture the pre_customer book. Process customer_order events sorted by
   (time, sequence). They are IOC limit orders: match at acceptable prices and
   discard unfilled quantity. Capture the post_customer book.
7. Append this tick's dealer reference to history; expose fills at the next
   decision. Update cash and positions for every fill, charging fee_per_unit
   per unit to each participating bot.

Matching uses best price, then resting-order time, then insertion sequence.
Trades execute at the resting order's price. Bot order timestamps are the tick
start. If a bot order would match its own order, its remaining incoming quantity
is discarded. Public snapshots aggregate quantities at the best five distinct
prices on each side, including dealer and bot orders, with best_bid, best_ask
and mid. pre_customer is after bot submissions; post_customer is after all
customer orders. Snapshots are not a full event-by-event book history.

The CSV contains the complete historical training tape for offline analysis.
It does not include true prices, customer classifications, tolerance settings,
market regimes, generation seeds or private configs. You can reconstruct
executions and value P&L using public references. The official final true-value
score requires the organiser's hidden final marks and cannot be reproduced
exactly from this pack. Measured runtime and other competing bots can also
change executions. The pack is not a private ReplayMarket scenario directory.
