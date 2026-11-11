# TradSoc Market-Making Starter

A local Python backtester for the Trading Society mini-tournament. Write one bot,
quote several assets, replay an organiser-supplied public training pack, and inspect
your trades, inventory, quotes and P&L.

**Start here:** edit [`bots/my_bot.py`](bots/my_bot.py), then run `python run_backtest.py`.
The default run uses a deliberately small **demo tape** in `data/market_data/demo/`,
not competition training data.
Replace it with the pack provided by the organisers for meaningful strategy testing.

> **What this does and does not reproduce**
>
> The execution core uses the organiser's matching, risk and accounting rules.
> Your bot uses the same `get_quotes(observation, memory)` interface. No market
> generation code, private scenario states or private configuration files are needed.
> All local P&L uses **public reference prices**, so it is not the official score.
> A default run contains only your bot, background dealers and customer flow.
> There is **no rival competitor unless you explicitly add one**. Solo practice is
> usually less competitive than the actual head-to-head tournament, not a forecast
> of how much you will earn there.

## 1. Install and run

Use Python **3.10 or newer**. Extract/download the repository, open a terminal in
its root directory (the directory containing this README and `run_backtest.py`).
No service, database, API key or account connection is needed.

The included InventoryBot practice opponent currently supports **CPython 3.12
on 64-bit Windows**. The editable starter and ExampleBot support Python 3.10
or newer.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_backtest.py
```

These commands do not require PowerShell activation permissions. To use the
shorter `python` commands below, activate with `.\.venv\Scripts\Activate.ps1`,
or keep substituting `.\.venv\Scripts\python.exe` for `python`.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_backtest.py
```

The runner prints a summary and the path to `report.html`. Open that HTML file
in your browser. Its interactive charts resize with the window and work offline.
Internet access is only needed to install dependencies initially, not to replay
a pack or open a saved report. After updating an existing installation, rerun
`python -m pip install -r requirements.txt` to install any new dependencies.

Keep market scenario packs and saved backtests in these folders:

```text
data/
    market_data/
        demo/                  # Included demo pack
        training_001/          # Add an organiser-supplied pack here
    runs/
        backtest_<timestamp>/  # Results and reports for each run
```

### Validate a training pack without running a bot

```bash
python run_backtest.py --scenario data/market_data/training_001 --validate-only
```

### Run your bot on the actual training pack

Copy the **contents** of the organiser's exported pack into a folder such as:

```text
data/market_data/training_001/
    events.csv
    market_info.json
    README.md           # Optional pack-specific guide
```

Then run:

```bash
python run_backtest.py --scenario data/market_data/training_001 --bot mine=bots/my_bot.py:MyBot --output data/runs/backtest_my_first_test
```

`mine` is the local name used in results. `bots/my_bot.py` is the file, and `MyBot`
is the class inside it. Paths containing spaces should be quoted as one argument:
`--bot "mine=path with spaces/my_bot.py:MyBot"`.

**Choose a new output directory for each run.** Existing results are never
silently overwritten. Omit `--output` to get a timestamped directory under
`data/runs/` in the project root, named `backtest_<timestamp>`.
Use `--output` to choose a different location or name.

### Test against InventoryBot

Add InventoryBot as a practice opponent by supplying a second `--bot` argument:

```bash
python run_backtest.py --scenario data/market_data/training_001 --bot mine=bots/my_bot.py:MyBot --bot benchmark=bots/inventory_bot.py:InventoryBot --output data/runs/backtest_with_opponent
```

Both bots then compete in the **same** books for the same flow. This is different
from running each bot alone and comparing totals. The benchmark is only a practice
opponent; it does not represent the full field of tournament submissions.

To try it with the bundled demo data:

```powershell
python run_backtest.py --scenario data/market_data/demo --bot mine=bots/my_bot.py:MyBot --bot inventory=bots/inventory_bot.py:InventoryBot
```

Keep the `:InventoryBot` class suffix as shown. You can also use
`bots/example_bot.py:ExampleBot` as a simpler fixed-spread opponent.
Neither benchmark is an optimal strategy or a target score you must beat.

### Other commands

```bash
python run_backtest.py --help
python run_backtest.py --scenario data/market_data/training_001 --asset A --no-charts
python run_backtest.py --report data/runs/backtest_my_first_test
python -m unittest discover -s tests -v
```

`--no-charts` still saves data, JSON reports and HTML tables, omitting interactive
charts and PNG exports. `--asset` can be repeated; omitting it runs every asset
in the pack. A cross-asset strategy should
normally be tested on the full pack. `--report` regenerates reports from saved
results without calling any strategy or replaying the market.

## 2. How your bot must be formatted

Put the strategy in a Python file. Import the shared API classes, subclass
`BaseBot`, and implement exactly this entry point:

```python
from bots.base import BaseBot
from models.models import QuoteAction

class MyBot(BaseBot):
    def get_quotes(self, observation, memory):
        quotes = {}

        for asset_id, market in observation.markets.items():
            # Example only: retrieve the most recent available public reference.
            price = next((p for p in reversed(market.price_history) if p is not None), None)
            if price is None:
                continue

            # This simple example assumes the public tick size is 0.01.
            # bots/my_bot.py handles instrument-specific grids and limits.
            quotes[asset_id] = QuoteAction(
                bid_price=round(price - 0.05, 2),
                bid_size=5,
                ask_price=round(price + 0.05, 2),
                ask_size=5,
            )

        return quotes, memory
```

The required return value is a **two-element tuple**:

```python
quotes, updated_memory
```

`quotes` is a dictionary mapping the exact asset IDs in `observation.markets` to
`QuoteAction` objects. `updated_memory` is a dictionary. Do **not** define your own
`QuoteAction` dataclass: import `models.models.QuoteAction`, because validation
checks that shared type.

One bot is called **once per tick for all assets**, not once per asset. You may
use information about A when quoting B. Your file can contain helper methods and
additional classes. `get_quotes` is simply the method the engine calls:

```python
def estimate_price(self, market):
    return market.book["mid"]

# Inside get_quotes:
estimate_a = self.estimate_price(observation.markets["A"])
```

Keep your submitted class constructible without required arguments. The local
runner can additionally pass public `tick_sizes`, `position_limits` and
`max_order_sizes` dictionaries when your class explicitly declares optional
constructor parameters with those names. The included bots support this. These
are instrument rules from `market_info.json`, not secret market parameters.
Do not assume other constructor extensions exist on the official platform.

### Disabling quotes

```python
QuoteAction(None, 0, 100.10, 5)  # Only an ask
QuoteAction(99.90, 5, None, 0)   # Only a bid
QuoteAction(None, 0, None, 0)    # No orders for this asset
```

Omitting an asset from `quotes` also means no new orders in that asset. **It does
not keep your old orders alive.** Old bot quotes are cancelled at every refresh.
Returning `{}` means no new quotes anywhere for that tick.

### Persistent memory

The runner starts with `{}` and passes back whatever memory you return on the
next call. Use it for EWMAs, rolling statistics, fitted coefficients and your own
fill history. It can hold both per-asset and shared estimates:

```python
memory = {
    "A": {"ewma": 100.01},
    "B": {"ewma": 99.98},
    "shared": {"signal": 0.0},
}
```

The supplied `MyBot` demonstrates an EWMA that processes each new observation
once. Missing references do not become zeros. Prefer basic serialisable values
for portability. The local runner resets both memory and the strategy instance
between runs. Memory is **not** account state: changing it cannot alter your
cash, positions or execution records.

## 3. Available observations and how to access them

`observation` is a fresh **argument**, not an attribute you must create on your
bot. Pass it, an asset observation, or just its book to your own helper methods.

```python
market = observation.markets["A"]
```

| Expression | Meaning |
| --- | --- |
| `observation.tick` | Current integer decision tick, starting at 0 |
| `observation.cash` | Your shared cash balance across all assets; not your P&L |
| `observation.markets` | Dictionary of all available assets |
| `market.price_history` | Tuple of public dealer-reference prices; may contain `None` |
| `market.book` | Current surviving book from the previous completed interval |
| `market.book["best_bid"]` | Highest resting bid, or `None` |
| `market.book["best_ask"]` | Lowest resting ask, or `None` |
| `market.book["mid"]` | Midpoint if both sides are present, otherwise `None` |
| `market.book["bids"]` | Up to five highest bid price levels, best first |
| `market.book["asks"]` | Up to five lowest ask price levels, best first |
| `market.position` | Your signed position in this asset: positive long, negative short |
| `market.recent_fills` | Your own executions since the previous decision |

Each displayed level looks like `{"price": 99.98, "quantity": 20}`. Quantities
are aggregated at a price. The book includes dealer and bot liquidity but does
not identify the owner of each level. Five **price levels** is not five orders.

Always check that a side exists before indexing it:

```python
bids = market.book["bids"]
if bids:
    best_bid_price = bids[0]["price"]
    best_bid_quantity = bids[0]["quantity"]

for fill in market.recent_fills:
    print(fill.time, fill.side, fill.price, fill.quantity, fill.order_id)
```

The historical reference is the dealer-only best-bid/best-ask midpoint measured
after dealer refresh and before new bot orders. It is **not** a trade price, the
full-book midpoint, or a guaranteed fundamental value. At tick 0, the book is
empty and the history contains the public initial price. At decision tick `t`,
the latest appended reference is from completed interval `t-1`.

References can be missing when the dealer book is one-sided or empty. A missing
value remains `None` in observations. Be careful when calculating returns:
dropping all missing values joins prices separated by several ticks.

Your observation does not contain future event rows, another bot's account,
private labels, or the organiser's valuation data. Public instrument settings
are in `market_info.json`; they are not extra fields on `AssetObservation`.

## 4. Exact tick sequence and matching rules

All bots decide using information available at tick `t` **before** that tick's
market events are applied. Their returned quotes are processed during `[t, t+1)`;
they see the resulting market and their fills on the next call at `t+1`.

For each asset the runner then:

1. Cancels **every bot's** previous remaining quotes and scheduled dealer orders.
2. Submits refreshed dealer limit orders in their recorded order.
3. Measures the dealer reference and validates all competitor quotes.
4. Submits each accepted bot bid/ask side in its assigned priority order.
5. Saves the **pre-customer** book snapshot.
6. Processes customer orders ordered by `(time, sequence)`.
7. Saves the **post-customer** book, applies fees, records results and advances.

Accounts are updated after each matching action, not only at the end. Dealer
and bot submissions can generate fills themselves when prices cross.

**Bots and dealers use GTC limit orders.** Each incoming order first matches
against acceptable opposing prices already in the book. A remaining GTC quantity
rests in the book. It is not converted to IOC merely because part of it traded.

**Customers use IOC limit orders.** They consume acceptable opposing liquidity;
any unfilled remainder is discarded. A buy limit is the maximum payment, a sell
limit is the minimum sale price. Executions occur at each resting order's price,
not automatically at the incoming limit. A single order can create several fills.

Best price has priority: highest bid or lowest ask. At a price, earlier resting
order time and insertion sequence win. Newly submitted bot sides are scheduled
by runtime bucket, then larger accepted side size, then bot ID and side. The
bucket width comes from `market_info.json`. This rule is applied **per side**,
not to the total size of a bot's two-sided quote. Dealers refresh before bots.
Wall-clock timing depends on your machine, so multi-bot results can differ
slightly between runs even on a fixed tape. Local IDs can break remaining ties;
official IDs and timing conditions are organiser-controlled.

A self-trade encounter discards the incoming bot order's remaining quantity.
It does not trade with the bot's own resting order. Quote validation also rejects
an active bid greater than or equal to the bot's own active ask.

### Risk and fees

For position `q`, position limit `L`, and order cap `M`, the maximum sizes are:

```text
bid_size <= min(M, L - q)
ask_size <= min(M, L + q)
```

Buy and sell headroom are checked separately; anticipated future sales do not
finance extra buy capacity. Limits are per asset per bot. Short positions and
negative cash can occur; there is no additional cash limit in this starter.

Sizes must be nonnegative native Python `int` values. Cast NumPy sizes with
`int(size)`. Positive sizes need positive finite prices on the asset's tick grid.
Oversized valid quantities are clipped. Invalid prices/sizes or self-crossing
quotes reject the asset's quote and are recorded in `errors.csv`. A bot-call
exception gives that bot no new quotes for the tick, and old quotes are still
cancelled. Omitted and zero-sized sides are valid, not errors.

`fee_per_unit` is charged on **every executed unit**, on buys and sells, to each
participating bot. It is not a flat charge per order or fill. Buying 10 units and
later selling 10 at a fee of 0.005 costs `20 * 0.005 = 0.10` in total.

## 5. Reading the results

Every completed run contains:

```text
data/runs/backtest_my_first_test/
    summary.json                 # Aggregate local results per bot
    metadata.json                # Public settings, selected assets, tape checksums
    quotes.csv                   # Submitted and accepted quotes, including no-fill ticks
    trades.csv                   # Each bot-side execution and post-trade account state
    equity.csv                   # Boundary cash, positions, marks and local equity
    errors.csv                   # Bot failures and rejected quotes
    quotes.jsonl                 # Canonical full records
    trades.jsonl
    equity.jsonl
    books.jsonl                  # Pre/post-customer snapshots and flow counters
    fills.jsonl                  # Underlying two-party matching executions
    errors.jsonl
    reports/<bot_name_and_hash>/
        report.json              # Per-bot report tables
        report.html              # Offline interactive dashboard
        charts/*.png             # Static exports
```

A short hash is added to report directory names to prevent filename collisions.
The terminal prints the exact path. The archive can contain every bot you ran
locally; each per-bot report contains that bot's trades, plus shared book snapshots.

### Explore the interactive charts

The HTML report includes accepted quotes and fills, quoted spreads, portfolio
and per-asset public-reference P&L, and inventory. Drag across a chart or scroll
to zoom; the tick window stays linked across all panels. Each Y axis fits the
visible data, so small price moves remain readable when you zoom in. The range
slider at the bottom also changes the shared tick window.

Hover for values and fill details. Use the toolbar to pan, reset the view, or
save an image. Double-click a chart to reset its zoom. Click a legend entry to
hide or show a series; the Y scales adjust to the remaining visible series.
Charts resize to the browser width. Everything needed is embedded in the HTML,
so no server or internet connection is required.

To update an existing run's report without rerunning its bots:

```powershell
python run_backtest.py --report data/runs/backtest_my_first_test
```

The Matplotlib plotting helpers and PNG exports remain available for static
images. Browsers with JavaScript disabled show the embedded PNG fallbacks.

### Local valuation is not the official score

At the end of each interval we value inventory using that interval's published
dealer reference. If it is missing, the previous usable reference is carried
forward; before the first valid reference, the public initial price is used.

```text
Equity = cash + sum(position[asset] * public_mark[asset])
P&L    = equity - initial_cash
```

Fees are already deducted from cash. Do not subtract `fees_paid` again.
Positions are **marked, not forcibly liquidated**, at the end of a run.
A large final cash balance can simply mean you sold assets short. It is not profit.

The official engine can use different, unavailable valuation marks. Therefore
cash, positions and fills can agree for the same tape and order schedule while
the official marked P&L differs. No official score is calculated or predicted
here. Missing marks can leave local P&L temporarily stale; `mark_age_ticks` in
equity records tells you how many consecutive intervals have lacked a new mark.

| Metric | Interpretation |
| --- | --- |
| `pnl`, `final_equity`, `per_asset_pnl` | Public-reference valuation, net of configured fees |
| `fill_count` | Bot-side executions, not unique orders or ticks |
| `traded_volume` | Total units bought plus sold; a round trip counts twice |
| `max_drawdown` | Largest peak-to-trough decline in boundary equity, not intratick equity |
| `peak_abs_position` | Largest absolute **boundary** position per asset; inspect trades for intratick positions |
| `average_spread` | Mean accepted ask minus bid when both sides exist, not realised profit per trade |
| `ticks_clipped_by_risk` | Valid quotes reduced in size; not rejected quotes or all time spent at the limit |
| Runtime metrics | Local measured decision time across all assets, not official latency |

The quote plot shows **accepted submission prices**, not a promise those orders
remained resting for the whole interval. Crossing orders may execute immediately.
The dealer reference drawn at the same tick was measured after that bot decision;
it is included for analysis, not as information the bot had in advance. The
post-customer book is what survives into the next observation. The pre-customer
snapshot is historical quoted liquidity, not a replacement for that live state.
A one-sided quote has an undefined spread, shown as a gap rather than zero.

### Explore in Python or a notebook

Run from the repository root, or install the project with `python -m pip install -e .`.

```python
from backtesting.runner import BacktestingRunner
from bots.my_bot import MyBot
from reporting.reports import generate_report
from storage.results import save_results, load_results

output = BacktestingRunner("data/market_data/training_001", {"mine": MyBot}).run()
print(output.results.bot_results["mine"].pnl)
save_results(output, "data/runs/backtest_python_test")

report = generate_report(output, "mine")
print(report.summary)
print(report.trades.head())       # pandas DataFrame
print(report.timeline.head())     # Quotes, fill counts and filled quantities
print(report.asset_pnl.head())    # Per-asset public P&L history

figure = report.plot_quotes("A", start=100, end=200)
figure.savefig("zoomed_quotes.png")
report.plot_pnl()
report.plot_inventory()
report.plot_diagnostics().show()   # Interactive Plotly figure

loaded = load_results("data/runs/backtest_python_test")  # No market rerun
```

At each tick the summary has one runtime measurement per bot decision, although
it is repeated on the asset quote rows. Do not count it three times when analysing
three-asset runs. The supplied summary removes that duplication.

## 6. What to submit and what not to rely on

For the mini-tournament, prepare a self-contained Python strategy file with your
class and `get_quotes` method. Follow the organiser's submission instructions for
naming and permitted dependencies. Do not submit modified matching/risk code or
local result files as the strategy. Preserve the shared import paths shown above.
The starter makes no guarantee that optional libraries beyond the published
competition environment will be installed on the official runner.

The full training tape is intentionally available for offline analysis. Python
running locally can read it; this repository cannot enforce that a deliberately
written bot avoids future CSV rows. **Do not use future rows or memorised tick
answers in your strategy.** Private evaluation uses different scenarios, and the
strategy should make decisions only from its observation and past memory.
Good training P&L is not evidence of out-of-sample performance.

This CLI executes uploaded Python **directly on your computer**. There is no
sandbox, network restriction or enforced hard timeout. Run only trusted bots;
interrupt an infinite loop with Ctrl+C. This is not the hosted submission service.

## 7. Repository map and troubleshooting

| Path | Purpose |
| --- | --- |
| `bots/base.py` | Official-style strategy interface |
| `bots/my_bot.py` | Editable starter with explicit memory |
| `bots/example_bot.py` | Fixed-spread benchmark copied from execution project |
| `bots/inventory_bot.py` | InventoryBot practice opponent |
| `models/models.py` | Public observation, action, order and account objects |
| `engine/public_replay.py` | Validates and replays a public event pack |
| `engine/matching.py`, `risk.py`, `accounting.py` | Execution rules |
| `engine/simulator.py` | Tick coordinator and public marking |
| `competition/bot_runner.py` | Timed trusted-code calls and per-run memory reset |
| `backtesting/runner.py` | Pack/bot setup, no second matching algorithm |
| `reporting/reports.py` | DataFrames, figures and offline HTML |
| `storage/results.py` | JSONL/CSV persistence and reloading |
| `data/market_data/` | Demo and organiser-supplied market scenario packs |
| `data/runs/` | Saved results and reports in `backtest_<timestamp>/` folders (ignored by Git) |
| `docs/DATA_FORMAT.md` | Exact pack schema and replay semantics |
| `tests/` | Execution, replay, timing, storage and report checks |

**`ModuleNotFoundError`**: use the correct virtual environment, install the
requirements and run from the repository root. Do not execute `bots/my_bot.py`
as a standalone program; the backtester calls it.

**No trades**: inspect `errors.csv`, accepted sizes and quote prices. Check for
empty sides, position clipping, very wide quotes and insufficient customer limits.
A working strategy is not guaranteed to get filled.

**`Expected QuoteAction`**: import the provided class instead of defining a new
one or returning a plain dictionary for each asset.

**Pack fails to load**: point `--scenario` at the directory holding the combined
`events.csv` and `market_info.json`. A book-snapshot CSV, a result archive, or a
private per-asset scenario folder is a different format. Use `--validate-only`.

**Results change slightly between runs**: timing-sensitive order priority and
strategy randomness can change fills; the event tape itself is fixed. Start
with a deterministic solo bot. Replaying the same pack does not create new data. The Python API retains a
`run(seed=...)` argument as a run label; it does not reseed the saved tape or
a strategy's own random-number generator.

**Very strong results on the bundled demo**: that tape is a small, repeated smoke
test, not a challenging market. Use the organiser's actual training packs.

The test suite covers the execution rules and this public-data implementation.
It is not a guarantee that later changes to the organiser's engine will stay
compatible. Use the starter version supplied for your event.
