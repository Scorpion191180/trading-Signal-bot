# D-Wave Tageschart mit Kurzfrist-Signalen

Eine bewusst reduzierte Streamlit-App für genau ein Instrument:

- **D-Wave Quantum Inc.**
- deutsches Börsenkürzel **RQ0**
- WKN **A3DSV9**
- ISIN **US26740W1099**
- geplanter Trade-Horizont **5 bis 30 Minuten**

Die sichtbare Oberfläche besteht im Wesentlichen nur aus einem automatisch aktualisierten, professionellen Kurschart. Die App führt keine Order aus. Ihre technischen Signale sind keine Anlageberatung und keine Erfolgs- oder Gewinngarantie.

## Was im Chart sichtbar ist

- alle heute bei Lang & Schwarz ausgeführten Umsätze als auswählbare Candlesticks mit Körper und Dochten,
- der laufende Mittelpunkt zwischen Geld- und Briefkurs,
- der aktuelle Geld-/Briefbereich,
- das aktuelle Signal direkt im Chart,
- bei einer gespeicherten Position der Einstandskurs und der ungefähre Gewinn oder Verlust,
- Stop und technisches Ziel, wenn die aktuelle Handlung diese Marken benötigt,
- Kaufen-, Nachkaufen- und Verkaufen-Markierungen, die während der geöffneten Sitzung tatsächlich erzeugt wurden.

Die Bedienung orientiert sich an der fotografierten professionellen Chartansicht: oben stehen Marktüberblick, Instrument, Handelsplatz und Livekurs; im Chart stehen OHLC-Werte und das aktuelle Kurzfristsignal; Kurs und Preisachse liegen rechts. Der Zeitraum kann unten zwischen **Intraday, 1 Woche, 1/3/6 Monaten, 1/3/5/10 Jahren, YTD und Max** gewechselt werden. Je nach Zeitraum bietet die App nur sinnvolle echte Kerzenebenen von **1 Minute bis 1 Monat** an. Sie erzeugt keine vermeintlichen Minutenkurse aus Tagesdaten.

Über dem Chart lassen sich Kerzen- und Linienansicht sowie EMA 8/21, Prognosezone, Signale und Position einzeln ein- oder ausblenden. Die schwebende Plotly-Werkzeugleiste bietet Zoomen, Verschieben, Fadenkreuz, Linien/freie Pfade/Rechtecke zeichnen, Zeichnungen löschen, Achsen zurücksetzen, Vollbild über die Streamlit-Ansicht und PNG-Export. Mit Mausrad oder Trackpad wird gezoomt; bei aktiver Verschiebung lässt sich der Zeitraum horizontal bewegen. Zeichnungen sind Arbeitshilfen in der laufenden Browseransicht und keine gespeicherten Handelsregeln.

Das Intraday-Kerzenintervall kann direkt über dem Chart auf **1, 5, 15 oder 30 Minuten** sowie **1, 2 oder 5 Stunden** gestellt werden. Stundenkerzen beginnen passend zur L&S-Sitzung um 07:30 Uhr statt an einer willkürlichen vollen Uhrzeit. Die Auswahl verändert nur die Darstellung; die Signallogik prüft weiterhin unabhängig ihre festen Zeitebenen.

Die 1-Minuten-Ansicht startet bei höchstens den letzten 90 tatsächlich aktiven Handelsminuten; bei einem ruhigen Tag wird dadurch automatisch mehr vom Tag gezeigt. Ein dezenter Stufenverlauf verbindet die einzelnen Abschlüsse. Herauszoomen zeigt weiterhin den kompletten Handelstag. Minuten ohne eigenen L&S-Abschluss werden mit dem zuletzt gehandelten Kurs fortgeführt, damit die Zeitachse nicht aus großen Löchern besteht; das Volumen dieser Minuten bleibt null.

Für Positionswert und Plus/Minus verwendet die App den **L&S-Geldkurs**, weil dieser für einen sofortigen Verkauf maßgeblich ist. Für einen Kauf ist dagegen der Briefkurs relevant. Beide Werte stehen getrennt im Chart; ihre Mitte dient nur als technische Orientierung.

Die sichtbaren Kerzen werden aus echten Open-, High-, Low- und Close-Werten des gewählten Zeitraums gebaut. Der Körper reicht von Eröffnung bis Schluss; die Dochte reichen bis zum höchsten und niedrigsten tatsächlich beobachteten Kurs. Eine Kerze kann deshalb bei einem echten Doji oder einem Intervall ohne zusätzliche Preisspanne naturgemäß sehr schmal sein.

Die komplette Anzeige und die Signallogik werden bei geöffneter App automatisch alle zehn Sekunden neu ausgeführt. Die primäre L&S-Sitzung läuft werktags von 07:30 bis 23:00 Uhr. Danach bleibt der letzte Handelstag sichtbar; über Nacht entstehen keine neuen Kurse.

## Was mit der Position geschieht

Die Positionseingabe ist absichtlich zugeklappt. Sie beeinflusst die Handlung im Chart:

- ohne Position: **Kaufen** oder **Warten**,
- mit Position und stabilem Trend: **Halten**,
- erneute Bestätigung oberhalb des Einstands: **Nachkaufen**,
- kippender kurzfristiger Trend: **Verkaufen**,
- unterhalb des Einstands: kein automatisches Verbilligen.

Aus Einstandskurs und Stückzahl zeigt der Signalkasten außerdem jederzeit den investierten Betrag, den aktuellen Positionswert sowie den ungefähren laufenden Gewinn oder Verlust in Euro und Prozent. Gebühren und der tatsächliche Ausführungskurs des Brokers sind darin nicht enthalten.

## Signallogik im Hintergrund

Die 5–30-Minuten-Prognose kombiniert fünf Ansätze, statt sich auf einen einzelnen Indikator zu verlassen:

- **Trend:** EMA-Richtung über 1, 5, 15 und 60 Minuten,
- **Momentum:** RSI und Veränderung des MACD-Histogramms,
- **Ausbruch:** Lage in der jüngsten Handelsspanne und Volumenbestätigung,
- **Rücklauf:** Abstand zum 20-Kerzen-Mittelwert in einer Seitwärtsphase,
- **Kontext:** Stunde, Tag, Woche und Monat als Filter gegen Trades in einen starken Gegentrend.

Die Gewichtung wechselt zwischen Trend-, Seitwärts- und hoher Volatilitätsphase. Der laufende Geld-/Brief-Spread und – sofern vorhanden – das Verhältnis der angebotenen Stückzahlen wirken als Liquiditätsfilter. Ab 0,6 Prozent Spread wird kein neuer 5–30-Minuten-Einstieg freigegeben. Die angezeigte Zone ist ein ATR-basierter technischer Schwankungsbereich und keine Kursgarantie. Der Modellwert von 0 bis 100 ist ausdrücklich **keine kalibrierte Trefferwahrscheinlichkeit**; seine Qualität muss mit künftigen echten Signalen weiter außerhalb der Entwicklungsdaten geprüft werden.

## Echte Vorwärtsprüfung

Während die App geöffnet ist, speichert sie höchstens eine unveränderliche Prognose pro Fünf-Minuten-Block und aktiver Kursquelle. Nach 5, 15 und 30 Minuten wird diese Prognose ausschließlich mit dem dann später eingetroffenen Kurs derselben Quelle bewertet. L&S- und Tradegate-Verläufe werden dabei nicht vermischt. Fehlende Zeitpunkte – etwa weil die App geschlossen war oder die Sitzung endete – werden nicht mit Kursen des nächsten Tages ersetzt.

Die kompakte Prüfzeile unter dem Chart zeigt zunächst nur den Aufbau der Stichprobe. Erst ab 20 abgeschlossenen 15-Minuten-Fällen blendet sie Richtungstreffer und den Anteil der Kurse innerhalb der prognostizierten Zone ein. Für einen Richtungstreffer muss die Kursbewegung außerdem den beim Signal gespeicherten Geld-/Brief-Spread überwinden. Alte Prognosen werden bei späteren Strategieänderungen nicht nachträglich umgeschrieben.

Obwohl nur ein Chart sichtbar ist, prüft die App weiterhin mehrere Zeitebenen:

- 1 Minute erzeugt den Auslöser,
- 5 Minuten bestätigt den Auslöser,
- 15 Minuten prüft den unmittelbaren Intraday-Trend,
- Stunde und Tag verhindern einen Trade gegen einen starken Gegentrend,
- Woche und Monat dienen nur als Risiko- und Kontextfilter.

Verwendet werden EMA-Trend, RSI 14, MACD-Histogramm, ATR, 20-Kerzen-Struktur und relatives Volumen. Ein Kaufsignal benötigt kurzfristige Volumenbestätigung. Die längeren Ebenen verlängern den geplanten Trade nicht.

Methodisch berücksichtigt die Umsetzung sowohl die dokumentierte Trendfortsetzung als auch deren Grenzen und kurzfristige Rückläufe: [Time Series Momentum (Journal of Financial Economics)](https://www.sciencedirect.com/science/article/pii/S0304405X11002613), [Short-Horizon Return Reversals and the Bid-Ask Spread (Journal of Financial Intermediation)](https://www.sciencedirect.com/science/article/pii/S1042957385710066). Eine spätere echte Kalibrierung darf nur zeitlich vorwärts testen; zufällig gemischte Trainings- und Testdaten würden Informationen aus der Zukunft einschleusen. Dafür ist ein Walk-forward-Verfahren wie [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) vorgesehen.

## Datenquellen

**Lang & Schwarz** ist die Hauptquelle. Die App liest von der öffentlichen D-Wave-Instrumentseite den laufenden Geld-/Briefkurs, dessen Kurszeit sowie die heutigen tatsächlichen Abschlüsse. Daraus baut sie den sichtbaren Tageschart und die aktuellen 1-, 5- und 15-Minuten-Ebenen auf. Wenn am frühen Morgen noch nicht genügend heutige Kerzen existieren, bleibt die vorhandene deutsche Yahoo-Zeitebene vorübergehend als Kontext erhalten.

**Tradegate BSX** bleibt als automatische Ersatzquelle aktiv, falls Lang & Schwarz vorübergehend nicht erreichbar oder unvollständig ist. Die gerade verwendete Quelle steht jederzeit direkt unter dem Chart. Für Tradegate endet die Signalfreigabe bereits um 22:00 Uhr.

**yfinance** liefert die deutschen historischen Reihen für die auswählbaren längeren Chartzeiträume sowie den übergeordneten Stunden-, Tages-, Wochen- und Monatskontext der Signallogik. Die App kennzeichnet L&S trotzdem eindeutig als Quelle des laufenden Kurses; historische Yahoo-Kerzen werden nicht als L&S-Ticks ausgegeben.

Ein alter letzter Umsatz ist nicht automatisch ein alter Markt: Geld und Brief können sich ändern, obwohl in einer Minute kein Handel zustande kommt. Deshalb zeigt der Chart den laufenden Geld-/Briefmittelpunkt separat. Ein Kaufsignal verlangt trotzdem echte kurzfristige Handelsaktivität.

Auch Lang & Schwarz kann vom in Trade Republic angezeigten Bestpreis abweichen, weil Trade Republic je nach Ausführungsmodus mehrere Handelsplätze vergleichen kann. Vor einer tatsächlichen Ausführung müssen Geld, Brief, Spread und Handelsplatz im Broker geprüft werden.

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

Die Tests prüfen unter anderem den L&S-Geld-/Briefkurs, die L&S-Abschlüsse ab 07:30 Uhr, den Tradegate-Fallback, die auswählbaren Minuten-, Stunden-, Tages-, Wochen- und Monatskerzen, die Zeitraumbegrenzung, die quellspezifischen Handelszeiten, den Livekurs im Positionssignal, Kaufen/Verkaufen/Nachkaufen, die Nachkaufsperre unterhalb des Einstands sowie die vorhandenen Daten-, Risiko-, Datenbank- und Backtestregeln.
