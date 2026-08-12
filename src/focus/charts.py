"""Eine reduzierte Chartansicht mit direkt sichtbaren technischen Hinweisen."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .analysis import SPEC_BY_KEY, IntradaySignal, TimeframeAnalysis


def focus_chart(
    data: pd.DataFrame,
    analysis: TimeframeAnalysis,
    signal: IntradaySignal,
) -> go.Figure:
    spec = SPEC_BY_KEY[analysis.key]
    visible = data.tail(spec.chart_rows).copy()
    visible.index = visible.index.tz_convert("Europe/Berlin")
    figure = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        row_heights=[0.68, 0.14, 0.18],
    )
    figure.add_trace(
        go.Candlestick(
            x=visible.index,
            open=visible["open"],
            high=visible["high"],
            low=visible["low"],
            close=visible["close"],
            name="RQ0",
            increasing_line_color="#22c55e",
            decreasing_line_color="#ef4444",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=visible.index,
            y=visible["ema_fast"],
            name=f"EMA {spec.fast_ema}",
            line={"color": "#38bdf8", "width": 1.7},
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=visible.index,
            y=visible["ema_slow"],
            name=f"EMA {spec.slow_ema}",
            line={"color": "#f59e0b", "width": 1.7},
        ),
        row=1,
        col=1,
    )
    if visible["ema_200"].notna().any():
        figure.add_trace(
            go.Scatter(
                x=visible.index,
                y=visible["ema_200"],
                name="EMA 200",
                line={"color": "#a78bfa", "width": 1.3, "dash": "dot"},
            ),
            row=1,
            col=1,
        )
    volume_colors = [
        "#22c55e" if close >= open_ else "#ef4444"
        for open_, close in zip(visible["open"], visible["close"], strict=True)
    ]
    figure.add_trace(
        go.Bar(x=visible.index, y=visible["volume"], name="Volumen", marker_color=volume_colors),
        row=2,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=visible.index,
            y=visible["rsi_14"],
            name="RSI 14",
            line={"color": "#c084fc", "width": 1.6},
        ),
        row=3,
        col=1,
    )
    figure.add_hline(y=70, line_dash="dot", line_color="#ef4444", opacity=0.65, row=3, col=1)
    figure.add_hline(y=30, line_dash="dot", line_color="#22c55e", opacity=0.65, row=3, col=1)
    if signal.entry_low is not None and signal.entry_high is not None:
        figure.add_hrect(
            y0=signal.entry_low,
            y1=signal.entry_high,
            fillcolor="rgba(34,197,94,0.13)",
            line_width=0,
            annotation_text="Einstiegszone",
            row=1,
            col=1,
        )
    if signal.stop_loss is not None:
        figure.add_hline(
            y=signal.stop_loss,
            line_dash="dash",
            line_color="#ef4444",
            annotation_text="Stop",
            row=1,
            col=1,
        )
    if signal.target is not None:
        figure.add_hline(
            y=signal.target,
            line_dash="dash",
            line_color="#22c55e",
            annotation_text="Ziel",
            row=1,
            col=1,
        )
    figure.add_annotation(
        x=visible.index[-1],
        y=float(visible["close"].iloc[-1]),
        text=f"{analysis.trend} · {analysis.score:.0f}/100",
        showarrow=True,
        arrowhead=2,
        bgcolor="rgba(15,23,42,.85)",
        font={"color": "white"},
        row=1,
        col=1,
    )
    figure.update_yaxes(title_text="EUR", row=1, col=1)
    figure.update_yaxes(title_text="Vol.", row=2, col=1)
    figure.update_yaxes(title_text="RSI", range=[0, 100], row=3, col=1)
    figure.update_layout(
        height=690,
        margin={"l": 8, "r": 8, "t": 35, "b": 8},
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "x": 0},
    )
    return figure
