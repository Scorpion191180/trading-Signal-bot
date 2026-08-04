"""Kompakte Plotly-Charts für kleine und große Displays."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.analysis.levels import PriceZone


def candlestick_chart(
    data: pd.DataFrame,
    *,
    symbol: str,
    zones: tuple[PriceZone, ...] = (),
    orders: list[object] | None = None,
    show_bollinger: bool = True,
) -> go.Figure:
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.75, 0.25],
    )
    figure.add_trace(
        go.Candlestick(
            x=data.index,
            open=data["open"],
            high=data["high"],
            low=data["low"],
            close=data["close"],
            name=symbol,
        ),
        row=1,
        col=1,
    )
    colors = {"ema_20": "#38bdf8", "ema_50": "#f59e0b", "ema_200": "#a78bfa", "vwap": "#f472b6"}
    for column, color in colors.items():
        if column in data:
            figure.add_trace(
                go.Scatter(x=data.index, y=data[column], name=column.upper(), line={"width": 1.2, "color": color}),
                row=1,
                col=1,
            )
    if show_bollinger and "bb_upper" in data:
        figure.add_trace(
            go.Scatter(x=data.index, y=data["bb_upper"], name="Bollinger oben", line={"width": 1, "dash": "dot"}),
            row=1,
            col=1,
        )
        figure.add_trace(
            go.Scatter(
                x=data.index,
                y=data["bb_lower"],
                name="Bollinger unten",
                line={"width": 1, "dash": "dot"},
                fill="tonexty",
                fillcolor="rgba(148,163,184,0.08)",
            ),
            row=1,
            col=1,
        )
    for zone in zones:
        color = "rgba(34,197,94,0.12)" if zone.kind == "Unterstützung" else "rgba(239,68,68,0.12)"
        figure.add_hrect(y0=zone.lower, y1=zone.upper, fillcolor=color, line_width=0, row=1, col=1)
    if orders:
        for side, marker, color in (("BUY", "triangle-up", "#22c55e"), ("SELL", "triangle-down", "#ef4444")):
            relevant = [order for order in orders if order.side == side]
            if relevant:
                figure.add_trace(
                    go.Scatter(
                        x=[order.executed_at for order in relevant],
                        y=[order.execution_price for order in relevant],
                        mode="markers",
                        marker={"symbol": marker, "size": 12, "color": color},
                        name=f"Virtuell {side}",
                    ),
                    row=1,
                    col=1,
                )
    volume_colors = [
        "#22c55e" if close >= open_ else "#ef4444"
        for open_, close in zip(data["open"], data["close"], strict=True)
    ]
    figure.add_trace(
        go.Bar(x=data.index, y=data["volume"], marker_color=volume_colors, name="Volumen"),
        row=2,
        col=1,
    )
    figure.update_layout(
        height=600,
        margin={"l": 8, "r": 8, "t": 40, "b": 8},
        xaxis_rangeslider_visible=False,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "x": 0},
        hovermode="x unified",
    )
    return figure


def component_chart(components: dict[str, float]) -> go.Figure:
    return go.Figure(
        go.Bar(
            x=list(components.values()),
            y=list(components.keys()),
            orientation="h",
            marker_color="#38bdf8",
        )
    ).update_layout(height=330, margin={"l": 8, "r": 8, "t": 20, "b": 8})
