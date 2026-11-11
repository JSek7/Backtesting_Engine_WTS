# Training data and backtest results

Market scenario packs go in `data/market_data/`. Each backtest saves directly
under `data/runs/` in its own `backtest_<timestamp>/` folder:

```text
data/
    market_data/
        demo/
            events.csv
            market_info.json
        training_001/          # Add organiser-supplied packs here
    runs/
        backtest_<timestamp>/  # Results and reports for each run
```

`market_data/demo/` is an included, explicitly illustrative 80-tick smoke-test
tape. It is not competition data and contains no proprietary market generator.

Copy an organiser-exported public training pack to e.g.
`data/market_data/training_001/`:

```text
data/market_data/training_001/events.csv
data/market_data/training_001/market_info.json
```

Run:

```bash
python run_backtest.py --scenario data/market_data/training_001 --validate-only
python run_backtest.py --scenario data/market_data/training_001 --bot mine=bots/my_bot.py:MyBot
```

Backtest results are saved by default to `data/runs/backtest_<timestamp>/`.
Each run includes the recorded results and a `reports/` folder with offline,
interactive HTML reports and static PNG exports. Charts support zoom, pan,
hover details, a linked tick window, and Y scales that fit the visible data.
This output folder is ignored by Git. To choose a named run folder or
rebuild its reports, use:

```bash
python run_backtest.py --scenario data/market_data/demo --output data/runs/backtest_my_first_test
python run_backtest.py --report data/runs/backtest_my_first_test
```

Choose a new output directory for each backtest; existing results are never
silently overwritten. Use a market pack folder such as `data/market_data/demo/`
or `data/market_data/training_001/` for `--scenario`.

Use the saved run's full folder path when rebuilding reports with `--report`.

Do not copy private scenario directories, private run archives or source configs
into this repository. Only the deliberately exported participant pack is needed.
Add newly released packs as separate directories; no Python changes are required.
