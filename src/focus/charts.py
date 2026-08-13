"""Eine reduzierte Chartansicht mit direkt sichtbaren technischen Hinweisen."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .analysis import SPEC_BY_KEY, FocusPosition, IntradaySignal, TimeframeAnalysis
from .quote import LiveQuote, resample_intraday_candles

CANDLE_INTERVAL_LABELS = {
    1: "1 Minute",
    5: "5 Minuten",
    15: "15 Minuten",
    30: "30 Minuten",
    60: "1 Stunde",
    120: "2 Stunden",
    300: "5 Stunden",
    1440: "1 Tag",
    10080: "1 Woche",
    43200: "1 Monat",
}


def _candle_trace_label(minutes: int) -> str:
    if minutes < 60:
        value, unit = minutes, "Minute" if minutes == 1 else "Minuten"
    elif minutes < 1440:
        value, unit = minutes // 60, "Stunde" if minutes == 60 else "Stunden"
    elif minutes < 10080:
        value, unit = minutes // 1440, "Tag" if minutes == 1440 else "Tage"
    elif minutes < 43200:
        value, unit = minutes // 10080, "Woche" if minutes == 10080 else "Wochen"
    else:
        value, unit = minutes // 43200, "Monat" if minutes == 43200 else "Monate"
    return f"{value}-{unit}-Kerzen"


def day_signal_chart(
    data: pd.DataFrame,
    quote: LiveQuote,
    signal: IntradaySignal,
    position: FocusPosition,
    signal_events: list[dict[str, object]],
    candle_minutes: int = 5,
    *,
    period_label: str = "Intraday",
    data_is_resampled: bool = False,
    chart_style: str = "Kerzen",
    overlays: set[str] | None = None,
) -> go.Figure:
    """Professioneller Kurschart mit Livekurs, Werkzeugen und erklärbaren Signalen."""

    if candle_minutes not in CANDLE_INTERVAL_LABELS:
        raise ValueError("Das Kerzenintervall wird nicht unterstützt.")
    if chart_style not in {"Kerzen", "Linie"}:
        raise ValueError("Diese Chartdarstellung wird nicht unterstützt.")
    active_overlays = overlays if overlays is not None else {"Prognose", "Signale", "Position"}
    candle_label = _candle_trace_label(candle_minutes)
    visible = data.copy() if data_is_resampled else resample_intraday_candles(data, candle_minutes)
    visible.index = visible.index.tz_convert("Europe/Berlin")
    figure = go.Figure()
    if chart_style == "Kerzen":
        figure.add_trace(
            go.Candlestick(
                x=visible.index,
                open=visible["open"],
                high=visible["high"],
                low=visible["low"],
                close=visible["close"],
                name=candle_label,
                increasing_line_color="#66d28a",
                decreasing_line_color="#e15f64",
                increasing_fillcolor="#66d28a",
                decreasing_fillcolor="#e15f64",
                increasing_line_width=1.25,
                decreasing_line_width=1.25,
                whiskerwidth=0.65,
            )
        )
    else:
        figure.add_trace(
            go.Scatter(
                x=visible.index,
                y=visible["close"],
                mode="lines",
                name="Kurs",
                line={"color": "#66d28a", "width": 2},
            )
        )
    if candle_minutes == 1:
        figure.add_trace(
            go.Scatter(
                x=visible.index,
                y=visible["close"],
                mode="lines",
                name="Minutenverlauf",
                line={"color": "rgba(148,163,184,.55)", "width": 1, "shape": "hv"},
                hoverinfo="skip",
            )
        )
    if "EMA" in active_overlays:
        figure.add_trace(
            go.Scatter(
                x=visible.index,
                y=visible["close"].ewm(span=8, adjust=False).mean(),
                mode="lines",
                name="EMA 8",
                line={"color": "#38bdf8", "width": 1.4},
            )
        )
        figure.add_trace(
            go.Scatter(
                x=visible.index,
                y=visible["close"].ewm(span=21, adjust=False).mean(),
                mode="lines",
                name="EMA 21",
                line={"color": "#f59e0b", "width": 1.4},
            )
        )
    current_x = visible.index[-1]
    figure.add_trace(
        go.Scatter(
            x=[current_x],
            y=[quote.bid],
            mode="markers",
            name="L&S Bid",
            marker={"size": 9, "color": signal.color, "line": {"width": 1.5, "color": "white"}},
            hovertemplate=f"L&S Bid {quote.bid:.3f} €<extra></extra>",
        )
    )
    figure.add_hrect(
        y0=quote.bid,
        y1=quote.ask,
        fillcolor="rgba(56,189,248,.08)",
        line_width=0,
    )
    if "Prognose" in active_overlays and signal.forecast_low is not None and signal.forecast_high is not None:
        figure.add_hrect(
            y0=signal.forecast_low,
            y1=signal.forecast_high,
            fillcolor="rgba(56,189,248,.055)",
            line={"color": "rgba(56,189,248,.38)", "width": 1, "dash": "dot"},
        )

    event_styles = {
        "BUY": ("Kaufen", "#22c55e", "triangle-up"),
        "ADD": ("Nachkaufen", "#14b8a6", "triangle-up"),
        "SELL": ("Verkaufen", "#ef4444", "triangle-down"),
    }
    for action, (label, color, symbol) in event_styles.items() if "Signale" in active_overlays else ():
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
    day_span = max(day_high - day_low, quote.bid * 0.01)
    entry_is_near_chart = (
        position.average_price is not None
        and day_low - day_span * 0.25 <= position.average_price <= day_high + day_span * 0.25
    )
    if "Position" in active_overlays and position.invested and entry_is_near_chart:
        figure.add_hline(
            y=position.average_price,
            line_dash="dot",
            line_color="#a78bfa",
            annotation_text=f"Dein Einstand {position.average_price:.3f} €",
            annotation_position="bottom left",
        )
    if "Signale" in active_overlays and signal.stop_loss is not None:
        figure.add_hline(
            y=signal.stop_loss,
            line_dash="dash",
            line_color="#ef4444",
            annotation_text="Stop",
            annotation_position="bottom right",
        )
    if "Signale" in active_overlays and signal.target is not None:
        figure.add_hline(
            y=signal.target,
            line_dash="dash",
            line_color="#22c55e",
            annotation_text="Ziel",
            annotation_position="top right",
        )

    position_text = ""
    if "Position" in active_overlays and position.invested and position.average_price and position.quantity:
        invested_eur = position.average_price * position.quantity
        current_value = quote.bid * position.quantity
        pnl_eur = (quote.bid - position.average_price) * position.quantity
        pnl_pct = (quote.bid / position.average_price - 1) * 100
        position_text = (
            f"Investiert {invested_eur:.2f} € · Verkaufswert {current_value:.2f} € · "
            f"Plus/Minus {pnl_eur:+.2f} € ({pnl_pct:+.2f} %)"
        )
    latest = visible.iloc[-1]
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
            f"<b>D-Wave Quantum · {candle_label}</b> · "
            f"O: {float(latest['open']):.3f} · H: {float(latest['high']):.3f} · "
            f"L: {float(latest['low']):.3f} · C: {float(latest['close']):.3f}"
        ),
        bgcolor="rgba(17,23,25,.78)",
        borderpad=4,
        font={"size": 11, "color": "#cbd5e1"},
    )
    figure.add_annotation(
        xref="paper",
        yref="paper",
        x=0.01,
        y=0.925,
        xanchor="left",
        yanchor="top",
        align="left",
        showarrow=False,
        text=(
            f"<b>{signal.headline}</b> · 5–30 Min {signal.forecast_direction} · "
            f"{signal.score:.0f}/100"
        ),
        bgcolor="rgba(17,23,25,.86)",
        bordercolor=signal.color,
        borderwidth=1,
        borderpad=5,
        font={"size": 11, "color": "white"},
    )
    if position_text:
        figure.add_annotation(
            xref="paper",
            yref="paper",
            x=0.01,
            y=0.01,
            xanchor="left",
            yanchor="bottom",
            showarrow=False,
            text=position_text,
            bgcolor="rgba(17,23,25,.76)",
            borderpad=4,
            font={"size": 10, "color": "#cbd5e1"},
        )
    price_color = "#22a06b" if (quote.change_percent or 0) >= 0 else "#c74850"
    figure.add_annotation(
        xref="paper",
        yref="y",
        x=1.0,
        y=quote.bid,
        xanchor="left",
        showarrow=False,
        text=f" {quote.bid:.3f} ",
        bgcolor=price_color,
        bordercolor=price_color,
        font={"size": 11, "color": "white"},
    )
    xaxis: dict[str, object] = {
        "title": "",
        "tickformat": (
            "%H:%M"
            if period_label == "Intraday"
            else "%d.%m<br>%H:%M"
            if candle_minutes < 1440
            else "%d.%m.%Y"
        ),
        "showgrid": True,
        "gridcolor": "rgba(100,116,139,.20)",
        "showspikes": True,
        "spikemode": "across",
        "spikesnap": "cursor",
        "spikecolor": "rgba(226,232,240,.75)",
        "spikethickness": 1,
    }
    if period_label in {"Intraday", "1W", "1M"} and candle_minutes < 1440:
        xaxis["rangebreaks"] = [
            {"bounds": [23, 7.5], "pattern": "hour"},
            {"bounds": ["sat", "mon"]},
        ]
    figure.update_layout(
        height=690,
        margin={"l": 10, "r": 54, "t": 10, "b": 12},
        xaxis_rangeslider_visible=False,
        xaxis=xaxis,
        yaxis={
            "title": "",
            "side": "right",
            "fixedrange": False,
            "tickformat": ".3f",
            "showgrid": True,
            "gridcolor": "rgba(100,116,139,.20)",
            "showspikes": True,
            "spikemode": "across",
            "spikesnap": "cursor",
            "spikecolor": "rgba(226,232,240,.75)",
            "spikethickness": 1,
        },
        hovermode="x",
        hoverdistance=50,
        spikedistance=-1,
        hoverlabel={"bgcolor": "#1c2529", "font": {"color": "#f8fafc"}},
        showlegend="EMA" in active_overlays,
        legend={"orientation": "h", "yanchor": "top", "y": 0.90, "x": 0.01},
        uirevision=f"dwave-professional-{period_label}-{candle_minutes}-{chart_style}",
        plot_bgcolor="#12191c",
        paper_bgcolor="#12191c",
        font={"color": "#cbd5e1", "family": "Inter, Arial, sans-serif"},
        dragmode="pan",
        newshape={"line": {"color": "#94a3b8", "width": 1.5, "dash": "dot"}},
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
