# D-Wave Kurzfrist-Signal

Eine bewusst reduzierte Streamlit-App für genau ein Instrument:

- **D-Wave Quantum Inc.**
- deutsches Börsenkürzel **RQ0**
- WKN **A3DSV9**
- ISIN **US26740W1099**
- Kurswährung **EUR**
- geplanter Trade-Horizont **5 bis 30 Minuten**

Die App führt keine Order aus. Sie zeigt eine technische Einschätzung als **Kaufen**, **Warten**, **Halten**, **Nachkaufen** oder **Verkaufen**. Das ist keine Anlageberatung und keine Erfolgs- oder Gewinngarantie.

## Was jetzt im Mittelpunkt steht

Die bisherige Navigation mit Watchlist, drei Strategiedepots, Scanner, Journal und vielen Einzelseiten wurde aus der normalen Oberfläche entfernt. Sichtbar ist nur noch:

1. der letzte deutsche D-Wave-Kurs,
2. ein einziges aktuelles Signal,
3. höchstens drei kurze Begründungen,
4. gegebenenfalls Einstiegszone, technischer Stop und technisches Ziel,
5. die Bestätigung auf 1, 5 und 15 Minuten,
6. eine frei wählbare normale Chartansicht von 1 Minute bis Monat,
7. der eigene Positionsstatus mit Einstandskurs und Stückzahl.

Die alten modularen Komponenten bleiben vorerst im Repository, werden von `app.py` aber nicht mehr als Navigation angeboten.

## Signallogik für 5–30 Minuten

Ein kurzfristiges Kaufsignal entsteht nur, wenn:

- der 1-Minuten-Chart einen Ausbruch oder bestätigten Trend-Rücksetzer zeigt,
- der 5-Minuten-Chart das Setup bestätigt,
- der 15-Minuten-Trend nicht dagegenläuft,
- Stunde und Tag keinen starken Gegentrend zeigen,
- der RSI keinen überhitzten Einstieg signalisiert,
- die jüngste abgeschlossene 1-Minuten-Kerze höchstens vier Minuten alt ist,
- der deutsche Markt geöffnet ist.

Verwendet werden nur wenige nachvollziehbare Techniken: schnelle und langsame EMA, EMA 200 soweit genügend Historie vorliegt, RSI 14, MACD-Histogramm, ATR, 20-Kerzen-Ausbruch bzw. Rücksetzer und relatives Volumen.

Stunden-, Tages-, Wochen- und Monatschart verlängern den Trade nicht. Sie sind ausschließlich Trend- und Risikofilter. Das eigentliche Timing kommt aus 1, 5 und 15 Minuten.

Bei einer gespeicherten Position gelten zusätzlich:

- **Nachkaufen** nur bei einem neuen bestätigten Signal und nur, wenn der aktuelle Kurs nicht unter dem Einstand liegt.
- **Verkaufen** bei gemeinsam kippendem 1- und 5-Minuten-Trend.
- ansonsten **Halten / Beobachten**.

## Deutsche Handelsplätze und Datenalter

Die App vergleicht kostenlose yfinance-Daten für Stuttgart (`RQ0.SG`) und Frankfurt (`RQ0.F`). Sie verwendet vollständig den deutschen Platz mit der frischeren 1-Minuten-Reihe und zeigt den gewählten Platz offen an. Zeitebenen verschiedener Plätze werden nicht gemischt; ein Wechsel auf den US-Ticker erfolgt nicht.

Bei einem wenig gehandelten deutschen Instrument kann der letzte Umsatz deutlich zurückliegen. Für einen 5–30-Minuten-Trade wäre ein solcher Preis ungeeignet. Deshalb zeigt die App in diesem Fall ausdrücklich **„Kein Signal – Kurs ist zu stark verzögert“**. Die technische Punktzahl bleibt sichtbar, wird aber nicht als Handlung freigegeben.

Kostenlose Daten können verzögert, lückenhaft oder unvollständig sein. Für eine tatsächliche kurzfristige Ausführung müssen zusätzlich der aktuelle Geld-/Briefkurs und der Spread beim eigenen Broker geprüft werden.

## Chartansichten

Der Nutzer kann zwischen folgenden Ansichten wechseln:

- 1 Minute
- 5 Minuten
- 15 Minuten
- 1 Stunde
- Tageschart
- Wochenchart
- Monatschart

Jeder Chart enthält Candlesticks, die für diese Zeitebene passenden EMA-Linien, Volumen, RSI sowie einen direkt am aktuellen Kurs angezeigten Trendhinweis. Einstiegszone, Stop und Ziel werden nur angezeigt, wenn sie für das aktuelle Signal berechnet werden können.

## Installation und Start

Voraussetzungen: Python 3.11 oder neuer und Git.

```bash
git clone https://github.com/Scorpion191180/trading-Signal-bot.git
cd trading-Signal-bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

Danach `http://localhost:8501` öffnen. Der Positionsstatus wird in der vorhandenen lokalen SQLite-Datenbank gespeichert. Es werden keine Broker-Zugangsdaten benötigt oder gespeichert.

## Tests

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q -W error
```

Die Tests prüfen unter anderem:

- nachvollziehbare Indikatoren und Signalpunkte,
- bestätigtes Kaufen auf 1/5/15 Minuten,
- Verkauf bei gemeinsamem kurzfristigem Trendbruch,
- Nachkaufsperre unterhalb des Einstands,
- vollständige Sperre bei veralteten 1-Minuten-Daten,
- Auswahl des frischeren deutschen Handelsplatzes ohne Symbolmischung,
- Wochen-/Monatsverdichtung nur aus abgeschlossenen Quellkerzen,
- weiterhin die vorhandenen Daten-, Risiko-, Datenbank- und Backtestregeln.

## Wichtige Grenze

Charttechnik kann Wahrscheinlichkeiten strukturieren, aber keine erfolgreiche Vorhersage garantieren. Besonders bei D-Wave können geringe Liquidität am deutschen Platz, große Spreads, Nachrichten und Bewegungen des US-Primärmarkts ein technisches Setup innerhalb weniger Sekunden ungültig machen. Die App nennt die technische Handlung deshalb ein **Signal**, nicht eine sichere Kauf- oder Verkaufsempfehlung.
