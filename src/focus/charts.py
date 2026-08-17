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


def _trading_minute_target(timestamp: pd.Timestamp, minutes: int) -> pd.Timestamp:
    """Verschiebt einen Horizont über die L&S-Handelspause auf die nächste Sitzung."""

    cursor = pd.Timestamp(timestamp)
    remaining = max(int(minutes), 0)
    while remaining:
        if cursor.weekday() >= 5 or cursor.hour >= 23:
            cursor = (
                cursor.normalize()
                + pd.Timedelta(1, unit="D")
                + pd.Timedelta(450, unit="min")
            )
            while cursor.weekday() >= 5:
                cursor += pd.Timedelta(1, unit="D")
            continue
        session_open = cursor.normalize() + pd.Timedelta(450, unit="min")
        if cursor < session_open:
            cursor = session_open
        session_close = cursor.normalize() + pd.Timedelta(23, unit="h")
        available = max(int((session_close - cursor).total_seconds() // 60), 0)
        if remaining < available:
            return cursor + pd.Timedelta(remaining, unit="min")
        if remaining == available:
            return session_close - pd.Timedelta(1, unit="s")
        remaining -= available
        cursor = session_close
    return cursor


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
    historical_forecasts: list[dict[str, object]] | None = None,
    forecast_horizon_minutes: int = 60,
    forecast_quality: dict[int, dict[str, object]] | None = None,
    axis_ranges: dict[str, list[object]] | None = None,
) -> go.Figure:
    """Professioneller Kurschart mit Livekurs, Werkzeugen und erklärbaren Signalen."""

    if candle_minutes not in CANDLE_INTERVAL_LABELS:
        raise ValueError("Das Kerzenintervall wird nicht unterstützt.")
    if chart_style not in {"Kerzen", "Linie"}:
        raise ValueError("Diese Chartdarstellung wird nicht unterstützt.")
    active_overlays = overlays if overlays is not None else {"Prognose", "Signale", "Position"}
    quality_by_horizon = forecast_quality or {}
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
                showlegend=False,
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
                showlegend=False,
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
                showlegend=False,
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
            showlegend=False,
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
    if "Prognose" in active_overlays and signal.trend_forecasts and period_label == "Intraday":
        forecast_x = [current_x] + [
            _trading_minute_target(current_x, int(item.minutes))
            for item in signal.trend_forecasts
        ]
        forecast_y = [quote.bid] + [item.expected_price for item in signal.trend_forecasts]
        upper_error = [0.0] + [
            item.expected_high - item.expected_price for item in signal.trend_forecasts
        ]
        lower_error = [0.0] + [
            item.expected_price - item.expected_low for item in signal.trend_forecasts
        ]
        released_now = []
        hover_text = ["Aktueller L&S Bid"]
        for item in signal.trend_forecasts:
            validation = quality_by_horizon.get(item.minutes, {})
            threshold = validation.get("threshold")
            released = bool(
                validation.get("qualified")
                and threshold is not None
                and item.confidence >= float(threshold)
            )
            released_now.append(released)
            verified_accuracy = validation.get("verification_accuracy")
            verified_samples = int(validation.get("verification_samples") or 0)
            status = (
                f"75%-freigegeben · {float(verified_accuracy):.1f} % / "
                f"{verified_samples} spätere Fälle"
                if released and verified_accuracy is not None
                else "Nicht als Vorhersage freigegeben · 75 % noch nicht bestätigt"
            )
            hover_text.append(
                f"{item.minutes}-Minuten-Ziel {item.expected_price:.3f} €<br>"
                f"{item.direction.title()} · Modellstärke {item.confidence:.0f} %<br>{status}"
            )
        any_released = any(released_now)
        path_color = "#22d3ee" if any_released else "#94a3b8"
        figure.add_trace(
            go.Scatter(
                x=forecast_x,
                y=forecast_y,
                mode="lines+markers+text",
                name=(
                    "Aktuelle Prognose · 75%-freigegeben"
                    if any_released
                    else "Modelltest · keine Vorhersage"
                ),
                text=[""] + [f"{item.minutes}m" for item in signal.trend_forecasts],
                textposition=("top center", "top left", "bottom left", "top center", "bottom center", "middle right"),
                textfont={"size": 11, "color": path_color},
                line={
                    "color": path_color,
                    "width": 4.2 if any_released else 2.6,
                    "dash": "solid" if any_released else "dot",
                },
                marker={
                    "size": 10,
                    "color": [path_color]
                    + ["#22d3ee" if released else "#64748b" for released in released_now],
                    "line": {"width": 1.5, "color": "#ecfeff"},
                },
                error_y={
                    "type": "data",
                    "symmetric": False,
                    "array": upper_error,
                    "arrayminus": lower_error,
                    "color": "rgba(148,163,184,.62)" if not any_released else "rgba(34,211,238,.62)",
                    "thickness": 1.5,
                    "width": 4,
                },
                hovertext=hover_text,
                hovertemplate="%{hovertext}<extra></extra>",
            )
        )
    forecast_points = historical_forecasts or []
    if "Prognose" in active_overlays and forecast_points:
        target_times = [pd.Timestamp(item["target_at"]).tz_convert("Europe/Berlin") for item in forecast_points]
        expected_prices = [float(item["expected_price"]) for item in forecast_points]
        marker_colors = [
            "#94a3b8"
            if not item.get("released")
            else "#22c55e"
            if item.get("direction_hit") is True
            else "#ef4444"
            if item.get("direction_hit") is False
            else "#94a3b8"
            for item in forecast_points
        ]
        hover_text = []
        for item, target_at in zip(forecast_points, target_times, strict=True):
            forecast_at = pd.Timestamp(item["forecast_at"]).tz_convert("Europe/Berlin")
            observed = item.get("observed_price")
            verdict = (
                "Nur rückwirkende Prüfung – kein freigegebenes Signal"
                if not item.get("released")
                else "Richtung getroffen"
                if item.get("direction_hit") is True
                else "Richtung verfehlt"
                if item.get("direction_hit") is False
                else "noch offen"
            )
            observed_text = f"{float(observed):.3f} €" if observed is not None else "noch offen"
            hover_text.append(
                f"Prognose von {forecast_at:%d.%m. %H:%M}<br>"
                f"Zielzeit {target_at:%d.%m. %H:%M}<br>"
                f"Erwartet {float(item['expected_price']):.3f} € "
                f"({item['direction']})<br>"
                f"Zone {float(item['expected_low']):.3f}–{float(item['expected_high']):.3f} €<br>"
                f"Tatsächlich {observed_text}<br>{verdict}"
            )
        completed = [item for item in forecast_points if item.get("direction_hit") is not None]
        released_completed = [item for item in completed if item.get("released")]
        hits = sum(item.get("direction_hit") is True for item in released_completed)
        accuracy = hits / len(released_completed) * 100 if released_completed else None
        raw_hits = sum(item.get("direction_hit") is True for item in completed)
        raw_accuracy = raw_hits / len(completed) * 100 if completed else None
        comparison_name = f"Ziel nach {forecast_horizon_minutes} Min"
        model_versions = {str(item.get("model_version", "")) for item in forecast_points}
        if len(model_versions) == 1:
            version = next(iter(model_versions)).replace("focus-market-", "")
            if version:
                comparison_name += f" · {version}"
        if accuracy is not None:
            comparison_name += f" · freigegeben {hits}/{len(released_completed)} ({accuracy:.0f} %)"
        else:
            comparison_name += " · 0 freigegeben"
        if raw_accuracy is not None:
            comparison_name += f" · Prüfung {raw_hits}/{len(completed)} ({raw_accuracy:.0f} %)"
        figure.add_trace(
            go.Scatter(
                x=target_times,
                y=expected_prices,
                mode="lines+markers",
                name=comparison_name,
                line={"color": "#ddd6fe", "width": 4.0, "dash": "dash"},
                marker={
                    "size": 6,
                    "color": marker_colors,
                    "line": {"width": 0.9, "color": "#f5f3ff"},
                },
                text=hover_text,
                hovertemplate="%{text}<extra></extra>",
            )
        )
        issued_times = [
            pd.Timestamp(item["forecast_at"]).tz_convert("Europe/Berlin")
            for item in forecast_points
        ]
        figure.add_trace(
            go.Scatter(
                x=issued_times,
                y=[
                    float(item.get("entry_price", item["expected_price"]))
                    for item in forecast_points
                ],
                mode="markers",
                name=f"Erstellt · Ziel +{forecast_horizon_minutes} Min",
                marker={
                    "size": 5,
                    "symbol": "diamond-open",
                    "color": "#94a3b8",
                    "line": {"width": 1.0, "color": "#cbd5e1"},
                },
                text=[
                    f"Hier um {issued_at:%H:%M} erstellt<br>"
                    f"Zielpunkt um {target_at:%H:%M}"
                    for issued_at, target_at in zip(issued_times, target_times, strict=True)
                ],
                hovertemplate="%{text}<extra></extra>",
            )
        )
    if "Zonen" in active_overlays:
        if signal.demand_low is not None and signal.demand_high is not None:
            figure.add_hrect(
                y0=signal.demand_low,
                y1=signal.demand_high,
                fillcolor="rgba(34,197,94,.10)",
                line={"color": "rgba(34,197,94,.55)", "width": 1},
                annotation_text="Nachfrage / Orderblock",
                annotation_position="bottom right",
            )
        if signal.liquidity_high is not None:
            figure.add_hline(
                y=signal.liquidity_high,
                line_color="rgba(244,114,182,.50)",
                line_dash="dot",
                annotation_text="Liquidität oben",
                annotation_position="top left",
            )
        if signal.liquidity_low is not None:
            figure.add_hline(
                y=signal.liquidity_low,
                line_color="rgba(45,212,191,.45)",
                line_dash="dot",
                annotation_text="Liquidität unten",
                annotation_position="top left",
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
    selected_validation = quality_by_horizon.get(forecast_horizon_minutes, {})
    selected_forecast = next(
        (
            item
            for item in signal.trend_forecasts
            if item.minutes == forecast_horizon_minutes
        ),
        None,
    )
    selected_threshold = selected_validation.get("threshold")
    selected_released = bool(
        selected_forecast is not None
        and selected_validation.get("qualified")
        and selected_threshold is not None
        and selected_forecast.confidence >= float(selected_threshold)
    )
    verification_accuracy = selected_validation.get("verification_accuracy")
    verification_samples = int(selected_validation.get("verification_samples") or 0)
    total_quality_samples = int(selected_validation.get("total") or 0)
    raw_quality_accuracy = selected_validation.get("raw_accuracy")
    if selected_released and verification_accuracy is not None:
        forecast_status = (
            f"75%-FREIGEGEBEN · {forecast_horizon_minutes} Min · "
            f"{float(verification_accuracy):.1f} % / {verification_samples} spätere Fälle"
        )
        forecast_border_color = "#22d3ee"
    else:
        measured = (
            f" · bisher {float(raw_quality_accuracy):.1f} % / {total_quality_samples} Fälle"
            if raw_quality_accuracy is not None
            else f" · {total_quality_samples}/60 Fälle"
        )
        forecast_status = (
            f"KEINE VORHERSAGE · {forecast_horizon_minutes} Min · Ziel 75 % noch nicht bestätigt"
            f"{measured}"
        )
        forecast_border_color = "#64748b"
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
            f"<b>{signal.headline}</b> · {forecast_status} · {signal.score:.0f}/100"
        ),
        bgcolor="rgba(17,23,25,.86)",
        bordercolor=forecast_border_color,
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
    forecast_times: list[pd.Timestamp] = []
    forecast_bounds: list[float] = []
    if "Prognose" in active_overlays and signal.trend_forecasts and period_label == "Intraday":
        forecast_times.extend(
            _trading_minute_target(current_x, int(item.minutes))
            for item in signal.trend_forecasts
        )
        forecast_bounds.extend(
            value
            for item in signal.trend_forecasts
            for value in (item.expected_low, item.expected_high)
        )
    if "Prognose" in active_overlays and forecast_points:
        forecast_times.extend(
            pd.Timestamp(item["target_at"]).tz_convert("Europe/Berlin") for item in forecast_points
        )
        forecast_bounds.extend(
            value
            for item in forecast_points
            for value in (float(item["expected_low"]), float(item["expected_high"]))
        )

    time_candidates = [pd.Timestamp(visible.index[0]), pd.Timestamp(visible.index[-1]), *forecast_times]
    first_visible_time = min(time_candidates)
    last_visible_time = max(time_candidates)
    candle_delta = pd.Timedelta(int(max(candle_minutes, 1)), unit="min")
    time_span = max(
        last_visible_time - first_visible_time,
        candle_delta,
    )
    time_padding = max(
        candle_delta / 2,
        time_span * 0.015,
    )
    default_x_range: list[object] = [
        first_visible_time - time_padding,
        last_visible_time + time_padding,
    ]

    price_candidates = [
        float(visible["low"].min()),
        float(visible["high"].max()),
        quote.bid,
        quote.ask,
        *forecast_bounds,
    ]
    visible_price_low = min(price_candidates)
    visible_price_high = max(price_candidates)
    visible_price_span = max(visible_price_high - visible_price_low, quote.bid * 0.004)
    visible_price_center = (visible_price_low + visible_price_high) / 2
    price_half_range = visible_price_span * 0.62
    default_y_range: list[object] = [
        visible_price_center - price_half_range,
        visible_price_center + price_half_range,
    ]

    xaxis: dict[str, object] = {
        "title": "",
        "uirevision": f"dwave-x-{period_label}-{candle_minutes}-{chart_style}",
        "autorange": False,
        "range": default_x_range,
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
    stored_ranges = axis_ranges or {}
    stored_x = stored_ranges.get("x", [])
    if len(stored_x) == 2:
        stored_x_span = pd.Timestamp(stored_x[1]) - pd.Timestamp(stored_x[0])
        candle_x_span = pd.Timestamp(visible.index[-1]) - pd.Timestamp(visible.index[0])
        if stored_x_span < candle_x_span * 0.75:
            xaxis["range"] = stored_x
    yaxis: dict[str, object] = {
        "title": "",
        "side": "right",
        "uirevision": f"dwave-y-{period_label}-{candle_minutes}-{chart_style}",
        "autorange": False,
        "range": default_y_range,
        "fixedrange": False,
        "tickformat": ".3f",
        "showgrid": True,
        "gridcolor": "rgba(100,116,139,.20)",
        "showspikes": True,
        "spikemode": "across",
        "spikesnap": "cursor",
        "spikecolor": "rgba(226,232,240,.75)",
        "spikethickness": 1,
    }
    stored_y = stored_ranges.get("y", [])
    if len(stored_y) == 2:
        stored_y_span = abs(float(stored_y[1]) - float(stored_y[0]))
        default_y_span = abs(float(default_y_range[1]) - float(default_y_range[0]))
        if stored_y_span < default_y_span * 0.75:
            yaxis["range"] = stored_y
    figure.update_layout(
        height=525,
        margin={"l": 10, "r": 54, "t": 10, "b": 12},
        xaxis_rangeslider_visible=False,
        xaxis=xaxis,
        yaxis=yaxis,
        hovermode="x",
        hoverdistance=50,
        spikedistance=-1,
        hoverlabel={"bgcolor": "#1c2529", "font": {"color": "#f8fafc"}},
        showlegend="EMA" in active_overlays
        or (
            "Prognose" in active_overlays
            and (bool(forecast_points) or bool(signal.trend_forecasts))
        ),
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
