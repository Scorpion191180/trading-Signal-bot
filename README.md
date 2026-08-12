# D-Wave Tageschart mit Kurzfrist-Signalen

Eine bewusst reduzierte Streamlit-App für genau ein Instrument:

- **D-Wave Quantum Inc.**
- deutsches Börsenkürzel **RQ0**
- WKN **A3DSV9**
- ISIN **US26740W1099**
- geplanter Trade-Horizont **5 bis 30 Minuten**

Die sichtbare Oberfläche besteht im Wesentlichen nur aus einem automatisch aktualisierten Tageschart. Die App führt keine Order aus. Ihre technischen Signale sind keine Anlageberatung und keine Erfolgs- oder Gewinngarantie.

## Was im Chart sichtbar ist

- alle heute bei Tradegate ausgeführten Umsätze als Ein-Minuten-Kerzen,
- der laufende Mittelpunkt zwischen Geld- und Briefkurs,
- der aktuelle Geld-/Briefbereich,
- das aktuelle Signal direkt im Chart,
- bei einer gespeicherten Position der Einstandskurs und der ungefähre Gewinn oder Verlust,
- Stop und technisches Ziel, wenn die aktuelle Handlung diese Marken benötigt,
- Kaufen-, Nachkaufen- und Verkaufen-Markierungen, die während der geöffneten Sitzung tatsächlich erzeugt wurden.

Die komplette Anzeige und die Signallogik werden bei geöffneter App automatisch alle zehn Sekunden neu ausgeführt. Außerhalb der Tradegate-Handelszeit bleibt der letzte Handelstag sichtbar; über Nacht entstehen keine neuen deutschen Kurse.

## Was mit der Position geschieht

Die Positionseingabe ist absichtlich zugeklappt. Sie beeinflusst die Handlung im Chart:

- ohne Position: **Kaufen** oder **Warten**,
- mit Position und stabilem Trend: **Halten**,
- erneute Bestätigung oberhalb des Einstands: **Nachkaufen**,
- kippender kurzfristiger Trend: **Verkaufen**,
- unterhalb des Einstands: kein automatisches Verbilligen.

Aus Einstandskurs und Stückzahl berechnet der Chart außerdem den ungefähren laufenden Gewinn oder Verlust. Gebühren und der tatsächliche Ausführungskurs des Brokers sind darin nicht enthalten.

## Signallogik im Hintergrund

Obwohl nur ein Chart sichtbar ist, prüft die App weiterhin mehrere Zeitebenen:

- 1 Minute erzeugt den Auslöser,
- 5 Minuten bestätigt den Auslöser,
- 15 Minuten prüft den unmittelbaren Intraday-Trend,
- Stunde und Tag verhindern einen Trade gegen einen starken Gegentrend,
- Woche und Monat dienen nur als Risiko- und Kontextfilter.

Verwendet werden EMA-Trend, RSI 14, MACD-Histogramm, ATR, 20-Kerzen-Struktur und relatives Volumen. Ein Kaufsignal benötigt kurzfristige Volumenbestätigung. Die längeren Ebenen verlängern den geplanten Trade nicht.

## Datenquellen

**Tradegate BSX** liefert den laufenden Level-1-Kurs sowie die heutigen tatsächlichen Umsätze. Daraus baut die App den sichtbaren Tageschart und die aktuellen 1-, 5- und 15-Minuten-Ebenen auf. Wenn am frühen Morgen noch nicht genügend heutige Kerzen existieren, bleibt die vorhandene deutsche Yahoo-Zeitebene vorübergehend als Kontext erhalten.

**yfinance** liefert die längeren deutschen Kontextreihen für Stunde, Tag, Woche und Monat. Diese Ebenen werden nicht mehr einzeln angezeigt.

Ein alter letzter Umsatz ist nicht automatisch ein alter Markt: Geld und Brief können sich ändern, obwohl in einer Minute kein Handel zustande kommt. Deshalb zeigt der Chart den laufenden Geld-/Briefmittelpunkt separat. Ein Kaufsignal verlangt trotzdem echte kurzfristige Handelsaktivität.

Tradegate kann vom Handelsplatz des eigenen Brokers abweichen. Vor einer tatsächlichen Ausführung müssen Geld, Brief, Spread und Handelsplatz im Broker geprüft werden.

## Installation und Start

```bash
git clone https://github.com/Scorpion191180/trading-Signal-bot.git
cd trading-Signal-bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

Danach `http://localhost:8501` öffnen. Der Positionsstatus wird in der lokalen SQLite-Datenbank gespeichert. Broker-Zugangsdaten werden nicht benötigt oder gespeichert.

## Tests

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q -W error
```

Die Tests prüfen unter anderem den Tradegate-Geld-/Briefkurs, das Einlesen der Tagesumsätze ohne doppelte Auftragszeilen, lückenlose Ein-Minuten-Kerzen, den Livekurs im Positionssignal, Kaufen/Verkaufen/Nachkaufen, die Nachkaufsperre unterhalb des Einstands sowie die vorhandenen Daten-, Risiko-, Datenbank- und Backtestregeln.
