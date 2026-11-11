"""Public-only reports adapted from the organiser's DataFrame/plotting helpers.

No official-score overlays or private-state plots. HTML embeds interactive
offline charts; Matplotlib helpers remain available for static PNG exports.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, fields
from pathlib import Path
import base64
import hashlib
import html
import json
import re
import pandas as pd
from models.models import Fill
from models.results import BookRecord, BotErrorRecord, EquityRecord, QuoteRecord, TradeRecord


def _table(records, model, bot_id=None, asset_id=None):
    rows = []
    for record in records:
        if bot_id is not None:
            if isinstance(record, Fill):
                if bot_id not in (record.buyer_bot, record.seller_bot):
                    continue
            elif getattr(record, "bot_id", None) != bot_id:
                continue
        if asset_id is not None and getattr(record, "asset_id", None) != asset_id:
            continue
        rows.append(asdict(record))
    return pd.DataFrame.from_records(rows, columns=[f.name for f in fields(model)])


def quotes_dataframe(log, bot_id=None, asset_id=None):
    return _table(log.quotes, QuoteRecord, bot_id, asset_id)


def trades_dataframe(log, bot_id=None, asset_id=None):
    return _table(log.trades, TradeRecord, bot_id, asset_id)


def equity_dataframe(log, bot_id=None):
    frame = _table(log.equity, EquityRecord, bot_id)
    if not frame.empty:
        frame["pnl"] = frame["equity"] - frame.groupby("bot_id")["equity"].transform("first")
    else:
        frame["pnl"] = pd.Series(dtype=float)
    return frame


def books_dataframe(log, asset_id=None):
    return _table(log.books, BookRecord, asset_id=asset_id)


def errors_dataframe(log, bot_id=None):
    return _table(log.errors, BotErrorRecord, bot_id)


def _safe_filename(name):
    """Readable, non-traversing, collision-resistant filenames."""
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name).strip("._")[:60] or "unnamed"
    return clean + "_" + hashlib.sha256(name.encode()).hexdigest()[:8]


@dataclass
class BacktestReport:
    bot_id: str
    summary: pd.DataFrame
    quotes: pd.DataFrame
    trades: pd.DataFrame
    equity: pd.DataFrame
    books: pd.DataFrame
    errors: pd.DataFrame

    @property
    def timeline(self):
        """One row per asset/decision with total fill quantities (not order count)."""
        frame = self.quotes.copy()
        if self.trades.empty:
            frame["fill_count"], frame["filled_quantity"] = 0, 0
        else:
            totals = self.trades.groupby(["tick", "asset_id"]).agg(fill_count=("quantity", "size"), filled_quantity=("quantity", "sum"))
            frame = frame.merge(totals, on=["tick", "asset_id"], how="left")
            for column in ("fill_count", "filled_quantity"):
                frame[column] = frame[column].fillna(0).astype(int)
        frame["was_filled"] = frame["fill_count"] > 0
        return frame

    @property
    def asset_pnl(self):
        """Positions and public-marked P&L by asset at each completed boundary."""
        cash = {}
        flows = {}
        for trade in self.trades.itertuples():
            key = (trade.tick + 1, trade.asset_id)
            flows[key] = flows.get(key, 0.0) + trade.cash_change
        rows = []
        for record in self.equity.sort_values("tick").itertuples():
            for asset, mark in record.mark_prices.items():
                cash[asset] = cash.get(asset, 0.0) + flows.get((record.tick, asset), 0.0)
                position = record.positions.get(asset, 0)
                rows.append(dict(tick=record.tick, asset_id=asset, position=position,
                                 mark_price=mark, pnl=cash[asset] + position * mark))
        return pd.DataFrame(rows, columns=["tick", "asset_id", "position", "mark_price", "pnl"])

    def to_dict(self):
        payload = {"bot_id": self.bot_id, "valuation": "public_reference"}
        for name in ("summary", "quotes", "trades", "equity", "books", "errors", "timeline", "asset_pnl"):
            payload[name] = json.loads(getattr(self, name).to_json(orient="records", double_precision=15))
        return payload

    @staticmethod
    def _figure(title, ylabel):
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.set(title=title, xlabel="Tick", ylabel=ylabel)
        ax.grid(alpha=0.25)
        ax.ticklabel_format(axis="y", style="plain", useOffset=False)
        return fig, ax

    def _quotes_for(self, asset_id, start=None, end=None):
        frame = self.quotes.loc[self.quotes["asset_id"] == asset_id].sort_values("tick")
        if start is not None:
            frame = frame.loc[frame.tick >= start]
        if end is not None:
            frame = frame.loc[frame.tick <= end]
        return frame

    def plot_quotes(self, asset_id, show_trades=True, start=None, end=None):
        fig, ax = self._figure(f"{self.bot_id}: quotes, {asset_id}", "Price")
        frame = self._quotes_for(asset_id, start, end)
        for column, label in (("accepted_bid", "Submitted bid (accepted)"), ("accepted_ask", "Submitted ask (accepted)"),
                              ("reference_price", "Dealer reference during interval")):
            if not frame.empty:
                ax.step(frame.tick, pd.to_numeric(frame[column], errors="coerce"), where="post", label=label)
        if show_trades:
            trades = self.trades.loc[self.trades.asset_id == asset_id]
            if start is not None:
                trades = trades.loc[trades.time >= start]
            if end is not None:
                trades = trades.loc[trades.time <= end + 1]
            for side, marker in (("buy", "^"), ("sell", "v")):
                subset = trades.loc[trades.side == side]
                if not subset.empty:
                    ax.scatter(subset.time, subset.price, marker=marker, s=22, label=f"Filled {side}", zorder=4)
        if ax.get_legend_handles_labels()[0]:
            ax.legend(loc="best", fontsize=9)
        fig.tight_layout()
        return fig

    def plot_spreads(self, asset_id):
        fig, ax = self._figure(f"{self.bot_id}: quoted spread, {asset_id}", "Ask minus bid")
        frame = self._quotes_for(asset_id)
        if not frame.empty:
            ax.plot(frame.tick, pd.to_numeric(frame.accepted_spread, errors="coerce"))
        fig.tight_layout()
        return fig

    def plot_pnl(self):
        fig, ax = self._figure(f"{self.bot_id}: PUBLIC-reference P&L", "Local P&L (not official score)")
        if not self.equity.empty:
            frame = self.equity.sort_values("tick")
            ax.plot(frame.tick, frame.pnl)
        fig.tight_layout()
        return fig

    def plot_equity(self):
        fig, ax = self._figure(f"{self.bot_id}: public-reference equity", "Equity")
        if not self.equity.empty:
            ax.plot(self.equity.tick, self.equity.equity)
        fig.tight_layout()
        return fig

    def plot_inventory(self, asset_id=None):
        fig, ax = self._figure(f"{self.bot_id}: inventory", "Position (units)")
        assets = sorted({a for marks in self.equity.mark_prices for a in marks})
        for asset in ([asset_id] if asset_id is not None else assets):
            ax.step(self.equity.tick, self.equity.positions.map(lambda p: p.get(asset, 0)), where="post", label=asset)
        if assets:
            ax.legend(loc="best", fontsize=9)
        fig.tight_layout()
        return fig

    def save_charts(self, directory):
        import matplotlib.pyplot as plt
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        paths = []
        jobs = [("pnl", self.plot_pnl), ("inventory", self.plot_inventory)]
        for asset in sorted(self.quotes.asset_id.unique()):
            name = _safe_filename(asset)
            jobs += [(name + "_quotes", lambda a=asset: self.plot_quotes(a)),
                     (name + "_spreads", lambda a=asset: self.plot_spreads(a))]
        for name, make in jobs:
            figure = make()
            path = directory / f"{name}.png"
            figure.savefig(path, dpi=140)
            plt.close(figure)
            paths.append(path)
        return paths

    def plot_diagnostics(self):
        """Interactive quotes/fills, spreads, P&L, and inventory with linked ticks."""
        from reporting.interactive import plot_diagnostics
        return plot_diagnostics(self)

    def save_html(self, path, chart_paths=(), *, charts=True):
        """Offline interactive report, with optional PNGs for browsers without JS."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        title = html.escape(self.bot_id)
        charts_html = ""
        if charts:
            from reporting.interactive import chart_html
            charts_html = ('<h2>Interactive charts</h2><p>Drag to zoom; scroll to zoom in or out. '
                           'Use the toolbar to pan or reset, or double-click to reset. '
                           'The tick window is shared across panels; Y scales fit visible data. '
                           'Click legend entries to hide or show lines.</p>' + chart_html(self))
            images = []
            for chart in chart_paths:
                encoded = base64.b64encode(Path(chart).read_bytes()).decode("ascii")
                images.append(f'<img alt="{html.escape(Path(chart).stem)}" src="data:image/png;base64,{encoded}">')
            charts_html += '<noscript><p>Enable JavaScript to use interactive charts.</p>' + ''.join(images) + '</noscript>'
        summary = self.summary.drop(columns=["equity_history"], errors="ignore").T
        text = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>TradSoc: {title}</title>
<style>body{{font:16px system-ui;margin:36px auto;max-width:1400px;padding:0 16px}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:7px;border:1px solid #ddd;text-align:left}}img{{max-width:100%}}.scroll{{overflow-x:auto}}.notice{{padding:14px;background:#f3f3f3}}#backtest-charts{{width:100%;min-width:0}}</style>
<h1>TradSoc backtest: {title}</h1><p class="notice"><strong>Local public-reference valuation, not an official score.</strong>
Final inventory is marked, not liquidated. Solo runs contain no rival competitor; optional practice opponents are not official opponents.
Quotes use the previous observation. The reference plotted alongside a quote is recorded later in that interval.</p>
<h2>Summary</h2><div class="scroll">{summary.to_html(header=False, escape=True)}</div>
{charts_html}<h2>First 100 trades</h2><p>See trades.csv for every execution.</p>
<div class="scroll">{self.trades.head(100).to_html(index=False, escape=True)}</div>
<h2>Errors (first 100)</h2><div class="scroll">{self.errors.head(100).to_html(index=False, escape=True)}</div>
</html>'''
        path.write_text(text, encoding="utf-8")
        return path


def generate_report(output, bot_id=None):
    if output.results.valuation != "public_reference":
        raise ValueError("Expected a local public-reference result")
    if bot_id is None:
        if len(output.results.bot_results) != 1:
            raise ValueError("Choose bot_id when a run contains several bots")
        bot_id = next(iter(output.results.bot_results))
    if bot_id not in output.results.bot_results:
        raise KeyError(f"Unknown bot: {bot_id}")
    return BacktestReport(bot_id, pd.DataFrame([asdict(output.results.bot_results[bot_id])]),
                          quotes_dataframe(output.log, bot_id), trades_dataframe(output.log, bot_id),
                          equity_dataframe(output.log, bot_id), books_dataframe(output.log),
                          errors_dataframe(output.log, bot_id))


def generate_reports(output):
    return {bot: generate_report(output, bot) for bot in output.results.bot_results}


def save_reports(output, directory, charts=True):
    directory = Path(directory)
    directories = {}
    for bot, report in generate_reports(output).items():
        dest = directory / _safe_filename(bot)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "report.json").write_text(json.dumps(report.to_dict(), allow_nan=False) + "\n", encoding="utf-8")
        paths = report.save_charts(dest / "charts") if charts else []
        report.save_html(dest / "report.html", paths, charts=charts)
        directories[bot] = dest
    return directories
