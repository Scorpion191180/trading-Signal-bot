"""Eine reduzierte Chartansicht mit direkt sichtbaren technischen Hinweisen."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .analysis import SPEC_BY_KEY, FocusPosition, IntradaySignal, TimeframeAnalysis
from .quote import LiveQuote, resample_intraday_candles


def day_signal_chart(
    data: pd.DataFrame,
    quote: LiveQuote,
    signal: IntradaySignal,
    position: FocusPosition,
    signal_events: list[dict[str, object]],
) -> go.Figure:
    """Ein einziger Tageschart mit Livekurs und den tatsächlich erzeugten Signalen."""

    visible = resample_intraday_candles(data, 5)
    visible = visible.loc[(visible["volume"] > 0) | (visible.index == visible.index[-1])].copy()
    visible.index = visible.index.tz_convert("Europe/Berlin")
    figure = go.Figure()
    figure.add_trace(
        go.Candlestick(
            x=visible.index,
            open=visible["open"],
            high=visible["high"],
            low=visible["low"],
            close=visible["close"],
            name="5-Minuten-Kerzen",
            increasing_line_color="#22c55e",
            decreasing_line_color="#ef4444",
            increasing_fillcolor="rgba(34,197,94,.72)",
            decreasing_fillcolor="rgba(239,68,68,.72)",
            increasing_line_width=2,
            decreasing_line_width=2,
            whiskerwidth=0.8,
        )
    )
    current_x = visible.index[-1]
    figure.add_trace(
        go.Scatter(
            x=[current_x],
            y=[quote.midpoint],
            mode="markers+text",
            name="Aktueller Kurs",
            text=[f"  aktuell {quote.midpoint:.3f} €"],
            textposition="middle right",
            marker={"size": 12, "color": signal.color, "line": {"width": 2, "color": "white"}},
        )
    )
    figure.add_hrect(
        y0=quote.bid,
        y1=quote.ask,
        fillcolor="rgba(56,189,248,.08)",
        line_width=0,
        annotation_text=f"Geld {quote.bid:.3f} · Brief {quote.ask:.3f}",
        annotation_position="top right",
    )

    event_styles = {
        "BUY": ("Kaufen", "#22c55e", "triangle-up"),
        "ADD": ("Nachkaufen", "#14b8a6", "triangle-up"),
        "SELL": ("Verkaufen", "#ef4444", "triangle-down"),
    }
    for action, (label, color, symbol) in event_styles.items():
        matching = [event for event in signal_events if event.get("action") == action]
        if not matching:
            continue
        figure.add_trace(
            go.Scatter(
                x=[pd.Timestamp(event["timestamp"]).tz_convert("Europe/Berlin") for event in matching],
                y=[float(event["price"]) for event in matching],
                mode="markers+text",
                name=label,
                text=[label] * len(matching),
                textposition="top center" if action != "SELL" else "bottom center",
                marker={"size": 15, "color": color, "symbol": symbol, "line": {"width": 1, "color": "white"}},
            )
        )

    day_low = float(visible["low"].min())
    day_high = float(visible["high"].max())
    day_span = max(day_high - day_low, quote.midpoint * 0.01)
    entry_is_near_chart = (
        position.average_price is not None
        and day_low - day_span * 0.25 <= position.average_price <= day_high + day_span * 0.25
    )
    if position.invested and entry_is_near_chart:
        figure.add_hline(
            y=position.average_price,
            line_dash="dot",
            line_color="#a78bfa",
            annotation_text=f"Dein Einstand {position.average_price:.3f} €",
            annotation_position="bottom left",
        )
    if signal.stop_loss is not None:
        figure.add_hline(
            y=signal.stop_loss,
            line_dash="dash",
            line_color="#ef4444",
            annotation_text="Stop",
            annotation_position="bottom right",
        )
    if signal.target is not None:
        figure.add_hline(
            y=signal.target,
            line_dash="dash",
            line_color="#22c55e",
            annotation_text="Ziel",
            annotation_position="top right",
        )

    position_text = ""
    if position.invested and position.average_price and position.quantity:
        pnl_eur = (quote.midpoint - position.average_price) * position.quantity
        pnl_pct = (quote.midpoint / position.average_price - 1) * 100
        position_text = f"<br>Position: {pnl_eur:+.2f} € · {pnl_pct:+.2f} %"
    figure.add_annotation(
        xref="paper",
        yref="paper",
        x=0.01,
        y=0.99,
        xanchor="left",
        yanchor="top",
        align="left",
        showarrow=False,
        text=(
            f"<b>{signal.headline}</b><br>"
            f"Kurs {quote.midpoint:.3f} € · Signalstärke {signal.score:.0f}/100{position_text}"
        ),
        bgcolor="rgba(15,23,42,.88)",
        bordercolor=signal.color,
        borderwidth=2,
        borderpad=10,
        font={"size": 15, "color": "white"},
    )
    figure.add_annotation(
        xref="paper",
        yref="paper",
        x=0.01,
        y=0.01,
        xanchor="left",
        yanchor="bottom",
        showarrow=False,
        text="Signalprüfung: 1 Min · 5 Min · 15 Min · Stunde · Tag · Woche · Monat",
        font={"size": 11, "color": "#94a3b8"},
    )
    figure.update_layout(
        height=720,
        margin={"l": 12, "r": 18, "t": 20, "b": 18},
        xaxis_rangeslider_visible=False,
        xaxis={"title": "Heutiger Handel · echte 5-Minuten-Candlesticks", "tickformat": "%H:%M"},
        yaxis={"title": "EUR", "side": "right", "fixedrange": False},
        hovermode="x unified",
        showlegend=True,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "x": 0.42},
        uirevision="dwave-trading-day",
    )
    return figure


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
