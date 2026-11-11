"""Interactive, offline charts for the participant's public backtest data."""

import html

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# Plotly keeps Y ranges when the shared tick window changes. Fit each panel to
# its visible traces, including step/line values crossing the window boundaries.
AUTO_SCALE_SCRIPT = r"""
(function () {
    const graph = document.getElementById('{plot_id}');
    const finite = value => typeof value === 'number' && Number.isFinite(value);
    let pending = false;

    function fitVisibleY() {
        const extents = new Map();
        for (const trace of graph.data) {
            if (trace.visible === false || trace.visible === 'legendonly') continue;
            const xaxis = 'xaxis' + (trace.xaxis || 'x').slice(1);
            const yaxis = 'yaxis' + (trace.yaxis || 'y').slice(1);
            const range = graph._fullLayout[xaxis].range;
            const low = Math.min(...range), high = Math.max(...range);
            const extent = extents.get(yaxis) || [Infinity, -Infinity];
            const include = value => {
                if (finite(value)) {
                    extent[0] = Math.min(extent[0], value);
                    extent[1] = Math.max(extent[1], value);
                }
            };
            const xs = trace.x || [], ys = trace.y || [];
            const lines = (trace.mode || 'lines').includes('lines');
            for (let i = 0; i < xs.length; i++) {
                const x = xs[i], y = ys[i];
                if (!finite(x)) continue;
                if (x >= low && x <= high) include(y);
                if (!lines || i === 0 || !finite(y) || !finite(ys[i - 1])) continue;
                const previousX = xs[i - 1], previousY = ys[i - 1];
                if (!finite(previousX) || x <= previousX) continue;
                for (const edge of [low, high]) {
                    if (previousX < edge && x > edge) {
                        include(trace.line && trace.line.shape === 'hv' ? previousY :
                            previousY + (y - previousY) * (edge - previousX) / (x - previousX));
                    }
                }
            }
            extents.set(yaxis, extent);
        }
        const update = {};
        for (const [axis, [low, high]] of extents) {
            if (!finite(low) || !finite(high)) continue;
            const padding = (high - low) * 0.06 || Math.max(Math.abs(low) * 0.001, 0.01);
            update[axis + '.range'] = [low - padding, high + padding];
            update[axis + '.autorange'] = false;
        }
        if (Object.keys(update).length) Plotly.relayout(graph, update);
    }

    function scheduleFit() {
        if (pending) return;
        pending = true;
        requestAnimationFrame(() => { pending = false; fitVisibleY(); });
    }

    graph.on('plotly_relayout', update => {
        if (Object.keys(update).some(key => /^xaxis\d*\.(range(\[[01]\])?|autorange)$/.test(key))) {
            scheduleFit();
        }
    });
    graph.on('plotly_restyle', scheduleFit);
    scheduleFit();
})();
"""


def plot_diagnostics(report):
    """Linked tick axes for quotes/fills, spreads, P&L, and inventory."""
    assets = set(report.quotes.asset_id) | set(report.trades.asset_id)
    for marks in report.equity.mark_prices:
        assets.update(marks)
    assets = sorted(assets)
    titles = []
    heights = []
    for asset in assets:
        titles.extend((f"{html.escape(asset)}: quotes and fills", f"{html.escape(asset)}: accepted spread"))
        heights.extend((380, 230))
    titles.extend(("Public-reference P&L", "Public-reference P&L per asset", "Inventory"))
    heights.extend((300, 300, 300))
    height = sum(heights) + 65 * (len(titles) - 1) + 180
    figure = make_subplots(rows=len(titles), cols=1, shared_xaxes=True,
                          subplot_titles=titles, row_heights=heights,
                          vertical_spacing=65 / height)

    def add_line(x, y, name, row, kind, asset=None, *, color=None, step=False, legend=True):
        figure.add_trace(go.Scatter(
            x=list(x), y=list(y), mode="lines", name=name,
            legendgroup=name, showlegend=legend, connectgaps=False,
            line=dict(color=color, shape="hv" if step else "linear", width=1.5),
            meta=dict(kind=kind, asset_id=asset),
            hovertemplate="Tick: %{x}<br>Value: %{y:.6g}<extra>%{fullData.name}</extra>",
        ), row=row, col=1)

    for index, asset in enumerate(assets):
        row = 2 * index + 1
        quotes = report._quotes_for(asset)
        for column, label, color in (("accepted_bid", "Accepted bid", "#16a34a"),
                                      ("accepted_ask", "Accepted ask", "#dc2626"),
                                      ("reference_price", "Dealer reference during interval", "#64748b")):
            add_line(quotes.tick, pd.to_numeric(quotes[column], errors="coerce"),
                     label, row, column, asset, color=color, step=True, legend=index == 0)
        trades = report.trades.loc[report.trades.asset_id == asset].sort_values("time")
        for side, color, symbol in (("buy", "#16a34a", "triangle-up"), ("sell", "#dc2626", "triangle-down")):
            fills = trades.loc[trades.side == side]
            figure.add_trace(go.Scatter(
                x=fills.time.tolist(), y=fills.price.tolist(), mode="markers", name=f"Filled {side}",
                legendgroup=f"Filled {side}", showlegend=index == 0,
                marker=dict(color=color, symbol=symbol, size=8),
                customdata=[[int(fill.quantity), fill.liquidity_role] for fill in fills.itertuples()],
                meta=dict(kind="fills", asset_id=asset),
                hovertemplate="Time: %{x}<br>Price: %{y:.6g}<br>Quantity: %{customdata[0]}"
                              "<br>Role: %{customdata[1]}<extra>%{fullData.name}</extra>",
            ), row=row, col=1)
        add_line(quotes.tick, pd.to_numeric(quotes.accepted_spread, errors="coerce"),
                 "Accepted spread", row + 1, "spread", asset, color="#2563eb", step=True, legend=False)
        figure.update_yaxes(title_text="Price", row=row, col=1)
        figure.update_yaxes(title_text="Ask minus bid", row=row + 1, col=1)

    pnl_row = len(assets) * 2 + 1
    equity = report.equity.sort_values("tick")
    add_line(equity.tick, equity.pnl, "Portfolio P&L", pnl_row, "pnl", color="#7c3aed")
    asset_pnl = report.asset_pnl
    colors = ("#2563eb", "#d97706", "#0891b2", "#db2777", "#65a30d")
    for index, asset in enumerate(assets):
        label = html.escape(asset)
        color = colors[index % len(colors)]
        series = asset_pnl.loc[asset_pnl.asset_id == asset]
        add_line(series.tick, series.pnl, f"{label} P&L", pnl_row + 1, "asset_pnl", asset, color=color)
        add_line(equity.tick, [positions.get(asset, 0) for positions in equity.positions],
                 f"{label} inventory", pnl_row + 2, "inventory", asset, color=color, step=True)
    figure.update_yaxes(title_text="Local P&L", row=pnl_row, col=1)
    figure.update_yaxes(title_text="Local P&L", row=pnl_row + 1, col=1)
    figure.update_yaxes(title_text="Position (units)", row=pnl_row + 2, col=1)
    figure.update_layout(template="plotly_white", height=height, autosize=True,
                         hovermode="x unified", dragmode="zoom", uirevision="tick-window",
                         legend=dict(orientation="h", y=1.01, yanchor="bottom", groupclick="togglegroup"),
                         margin=dict(t=140, b=90, l=80, r=35))
    figure.update_yaxes(automargin=True, tickformat=".6~g", exponentformat="none")
    figure.update_xaxes(title_text="Tick", showticklabels=True, automargin=True)
    figure.update_xaxes(rangeslider=dict(visible=True, thickness=0.025), row=len(titles), col=1)
    return figure


def chart_html(report):
    """Embed Plotly itself so a saved report needs no server or connection."""
    return plot_diagnostics(report).to_html(
        full_html=False, include_plotlyjs=True, div_id="backtest-charts",
        config=dict(responsive=True, scrollZoom=True, displaylogo=False,
                    doubleClick="reset+autosize", toImageButtonOptions=dict(format="png", filename="backtest-chart")),
        post_script=AUTO_SCALE_SCRIPT,
    )
