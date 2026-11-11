# Validation included with this release

Run from the repository root:

```bash
python -m unittest discover -s tests -v
```

37 tests passed during packaging. They cover:

- Public pack validation, empty ticks, ID preservation, ordering and rewinding.
- Price/time/sequence priority, partial fills, GTC remainders, IOC cancellation,
  self-trade prevention, book aggregation and liquidity accounting.
- Position clipping, fee accounting, multi-asset accounts, stale-quote cancellation,
  per-side priority and observations without future updates.
- Rejected submissions, memory reset, missing reference handling and result parity
  across deterministic runs with fixed test timings.
- Save/load round trips, empty log schemas, malformed submission logging,
  CSV exports, HTML/PNG reporting and the CLI.
- Fingerprints of the retained organiser-core execution methods.

The build also compared the trimmed matching core with the source implementation
on a deterministic sequence of 1,950 actions and 1,321 fills. Economic results,
books, flow counters and accounts agreed; diagnostic labels are not part of that
comparison. This does not promise exact official scores or compatibility with
future organiser-engine revisions.

The demo data is intentionally simple and does not validate strategy quality.
Tests were run on Python 3.13 with NumPy 2.3.5, pandas 2.2.3 and Matplotlib 3.10.8.
Use the actual event-supplied training packs for strategy development.
