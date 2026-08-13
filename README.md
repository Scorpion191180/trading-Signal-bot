# D-Wave Tageschart mit Kurzfrist-Signalen

Eine bewusst reduzierte Streamlit-App für genau ein Instrument:

- **D-Wave Quantum Inc.**
- deutsches Börsenkürzel **RQ0**
- WKN **A3DSV9**
- ISIN **US26740W1099**
- geplanter Trade-Horizont **5 bis 30 Minuten**

Die sichtbare Oberfläche besteht im Wesentlichen nur aus einem automatisch aktualisierten, professionellen Kurschart. Ein getrenntes Papierkonto testet die Signale mit 2.000 € Spielgeld; die App führt keine echte Order aus. Ihre technischen Signale sind keine Anlageberatung und keine Erfolgs- oder Gewinngarantie.

## Was im Chart sichtbar ist

- den heutigen L&S-Bid-Verlauf als auswählbare Candlesticks mit Körper und Dochten,
- den laufenden L&S-Geldkurs sowie den getrennt ausgewiesenen Briefkurs,
- der aktuelle Geld-/Briefbereich,
- das aktuelle Signal direkt im Chart,
- bei einer gespeicherten Position der Einstandskurs und der ungefähre Gewinn oder Verlust,
- Stop und technisches Ziel, wenn die aktuelle Handlung diese Marken benötigt,
- persistente Kaufen- und Verkaufen-Markierungen der tatsächlich vorwärts ausgeführten Papierorders.

Die Bedienung orientiert sich an der fotografierten professionellen Chartansicht: oben stehen Marktüberblick, Instrument, Handelsplatz und Livekurs; im Chart stehen OHLC-Werte und das aktuelle Kurzfristsignal; Kurs und Preisachse liegen rechts. Eine schmale Leiste über dem Chart wechselt zwischen **Heute, 1 Woche, 1/3/6 Monaten, Seit Jahresanfang, 1/3/5/10 Jahren und der gesamten Historie**. Daneben wählt ein kompaktes Menü die Kerzengröße; Linienansicht und Einblendungen liegen platzsparend unter **Mehr**. Je nach Zeitraum bietet die App nur sinnvolle echte Kerzenebenen von **1 Minute bis 1 Monat** an. Sie erzeugt keine vermeintlichen Minutenkurse aus Tagesdaten.

Wird die Kerzengröße erhöht, sinkt bei unverändertem Zeitraum zwangsläufig die Anzahl der Kerzen: Eine Stundenkerze fasst bis zu 60 Minutenkerzen zusammen, eine Tageskerze den gesamten Börsentag und eine Wochenkerze mehrere Handelstage. Eine Statuszeile nennt deshalb stets den gewählten Zeitraum, die Größe jeder Kerze und die tatsächlich sichtbare Kerzenzahl.

Über dem Chart lassen sich Kerzen- und Linienansicht sowie EMA 8/21, Prognosezone, Signale und Position einzeln ein- oder ausblenden. Die schwebende Plotly-Werkzeugleiste bietet Zoomen, Verschieben, Fadenkreuz, Linien/freie Pfade/Rechtecke zeichnen, Zeichnungen löschen, Achsen zurücksetzen, Vollbild über die Streamlit-Ansicht und PNG-Export. Mit Mausrad oder Trackpad wird gezoomt; bei aktiver Verschiebung lässt sich der Zeitraum horizontal bewegen. Zeichnungen sind Arbeitshilfen in der laufenden Browseransicht und keine gespeicherten Handelsregeln.

Das Intraday-Kerzenintervall kann direkt über dem Chart auf **1, 5, 15 oder 30 Minuten** sowie **1, 2 oder 5 Stunden** gestellt werden. Stundenkerzen beginnen passend zur L&S-Sitzung um 07:30 Uhr statt an einer willkürlichen vollen Uhrzeit. Die Auswahl verändert nur die Darstellung; die Signallogik prüft weiterhin unabhängig ihre festen Zeitebenen.

Die 1-Minuten-Ansicht zeigt den kompletten gelieferten Handelstag ab 07:30 Uhr und zoomt nicht mehr automatisch auf einen kleinen Ausschnitt. Ein dezenter Verlauf verbindet die gelieferten L&S-Bid-Kerzen. Die Voreinstellung **Heute** bündelt diese Daten zu 5-Minuten-Kerzen; **1 Woche** verwendet 30-Minuten-Kerzen über die gesamte Handelswoche. Nächte und Wochenenden werden auf den feinen Ansichten ausgeblendet, damit zwischen zwei Sitzungen keine künstlich großen leeren Flächen entstehen.

Für Positionswert und Plus/Minus verwendet die App den **L&S-Geldkurs**, weil dieser für einen sofortigen Verkauf maßgeblich ist. Für einen Kauf ist dagegen der Briefkurs relevant. Beide Werte stehen getrennt im Chart; ihre Mitte dient nur als technische Orientierung.

Die sichtbaren Kerzen werden aus echten Open-, High-, Low- und Close-Werten des gewählten Zeitraums gebaut. Der Körper reicht von Eröffnung bis Schluss; die Dochte reichen bis zum höchsten und niedrigsten tatsächlich beobachteten Kurs. Eine Kerze kann deshalb bei einem echten Doji oder einem Intervall ohne zusätzliche Preisspanne naturgemäß sehr schmal sein.

Die komplette Anzeige und die Signallogik werden bei geöffneter App automatisch alle zehn Sekunden neu ausgeführt. Die primäre L&S-Sitzung läuft werktags von 07:30 bis 23:00 Uhr. Danach bleibt der letzte Handelstag sichtbar; über Nacht entstehen keine neuen Kurse.

## Private Position und unabhängiger Signal-Bot

Die eingetragene private Position dient ausschließlich zur Anzeige ihres ungefähren Werts und Gewinns oder Verlusts zum L&S-Geldkurs. Sie verändert das neutrale **KAUFEN / WARTEN / VERKAUFEN**-Marktsignal nicht. Dadurch bleibt ein Kaufsignal sichtbar, selbst wenn bereits eine private D-Wave-Position besteht oder ihr Einstand über dem aktuellen Kurs liegt.

Daneben besitzt der Signal-Bot ein dauerhaft gespeichertes Papierkonto mit **2.000 € Startkapital**. Bei einem bestätigten Kaufsignal investiert er das verfügbare Spielgeld in D-Wave; ein bestätigtes Verkaufssignal, Stop-Loss oder technisches Ziel schließt die virtuelle Position. Bereits vergangene Chartabschnitte werden nicht nachträglich gehandelt. Das Papierkonto beginnt erst mit Signalen, die nach Aktivierung dieser Funktion in der geöffneten App eintreffen.

Das Ausführungsmodell bildet eine Trade-Republic-Standardorder konservativ nach:

- Kauf nahe dem aktuellen L&S-Briefkurs und Verkauf nahe dem Geldkurs,
- **1 € Abwicklungskosten je Transaktion** gemäß der [offiziellen Trade-Republic-Preisübersicht](https://traderepublic.com/de-de/about?openModal=pricing-scheme),
- tatsächlicher laufender L&S-Geld-/Brief-Spread,
- zusätzlicher Ausführungspuffer von 0,05 % für eine mögliche ungünstigere Ausführung.

Bei mehr als 0,6 % Spread bleibt das technische Kaufsignal sichtbar, der Papier-Bot wartet jedoch mit der Ausführung. Die Kontozeile zeigt Depotwert, Nettoergebnis und bisher modellierte Gebühren-, Spread- und Ausführungskosten. Steuern, persönliche Freibeträge und nicht vorab bekannte Sonder-/Drittkosten sind nicht enthalten.

## Signallogik im Hintergrund

Die 5–30-Minuten-Prognose kombiniert fünf Ansätze, statt sich auf einen einzelnen Indikator zu verlassen:

- **Trend:** EMA-Richtung über 1, 5, 15 und 60 Minuten,
- **Momentum:** RSI und Veränderung des MACD-Histogramms,
- **Ausbruch:** Lage in der jüngsten Handelsspanne und Volumenbestätigung,
- **Rücklauf:** Abstand zum 20-Kerzen-Mittelwert in einer Seitwärtsphase,
- **Kontext:** Stunde, Tag, Woche und Monat als Filter gegen Trades in einen starken Gegentrend.

Die Gewichtung wechselt zwischen Trend-, Seitwärts- und hoher Volatilitätsphase. Der laufende Geld-/Brief-Spread und – sofern vorhanden – das Verhältnis der angebotenen Stückzahlen wirken als Liquiditätsfilter. Ab 0,6 Prozent Spread wird ein Kaufsignal zwar weiterhin als technisches Testsignal angezeigt, aber nicht im Papierkonto ausgeführt. Die angezeigte Zone ist ein ATR-basierter technischer Schwankungsbereich und keine Kursgarantie. Der Modellwert von 0 bis 100 ist ausdrücklich **keine kalibrierte Trefferwahrscheinlichkeit**; seine Qualität muss mit künftigen echten Signalen weiter außerhalb der Entwicklungsdaten geprüft werden.

## Echte Vorwärtsprüfung

Während die App geöffnet ist, speichert sie höchstens eine unveränderliche Prognose pro Fünf-Minuten-Block und aktiver Kursquelle. Nach 5, 15 und 30 Minuten wird diese Prognose ausschließlich mit dem dann später eingetroffenen Kurs derselben Quelle bewertet. L&S- und Tradegate-Verläufe werden dabei nicht vermischt. Fehlende Zeitpunkte – etwa weil die App geschlossen war oder die Sitzung endete – werden nicht mit Kursen des nächsten Tages ersetzt.

Die kompakte Prüfzeile unter dem Chart zeigt zunächst nur den Aufbau der Stichprobe. Erst ab 20 abgeschlossenen 15-Minuten-Fällen blendet sie Richtungstreffer und den Anteil der Kurse innerhalb der prognostizierten Zone ein. Für einen Richtungstreffer muss die Kursbewegung außerdem den beim Signal gespeicherten Geld-/Brief-Spread überwinden. Alte Prognosen werden bei späteren Strategieänderungen nicht nachträglich umgeschrieben.

Obwohl nur ein Chart sichtbar ist, prüft die App weiterhin mehrere Zeitebenen:

- 1 Minute erzeugt den Auslöser,
- 5 Minuten bestätigt den Auslöser,
- 15 Minuten prüft den unmittelbaren Intraday-Trend,
- Stunde und Tag verhindern einen Trade gegen einen starken Gegentrend,
- Woche und Monat dienen nur als Risiko- und Kontextfilter.

Verwendet werden EMA-Trend, RSI 14, MACD-Histogramm, ATR und die 20-Kerzen-Struktur. Falls die Kursquelle echtes Volumen liefert, wird zusätzlich relatives Volumen verlangt. Die L&S-Bid-Quote-Historie enthält kein Handelsvolumen; dort übernehmen eine starke gemeinsame 1-/5-/15-Minuten-Preisbestätigung und mindestens drei positive Strategiestimmen diese Prüfung. Die längeren Ebenen verlängern den geplanten Trade nicht.

Methodisch berücksichtigt die Umsetzung sowohl die dokumentierte Trendfortsetzung als auch deren Grenzen und kurzfristige Rückläufe: [Time Series Momentum (Journal of Financial Economics)](https://www.sciencedirect.com/science/article/pii/S0304405X11002613), [Short-Horizon Return Reversals and the Bid-Ask Spread (Journal of Financial Intermediation)](https://www.sciencedirect.com/science/article/pii/S1042957385710066). Eine spätere echte Kalibrierung darf nur zeitlich vorwärts testen; zufällig gemischte Trainings- und Testdaten würden Informationen aus der Zukunft einschleusen. Dafür ist ein Walk-forward-Verfahren wie [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) vorgesehen.

## Datenquellen

**Lang & Schwarz Bid über stock3** ist die Hauptquelle. Die App liest aus dem frei sichtbaren [stock3-Chart für D-Wave Quantum](https://stock3.com/aktien/d-wave-quantum-61824087) den laufenden L&S-Geld-/Briefkurs und die dort öffentlich ausgelieferten L&S-Bid-Kerzen. Genau dadurch entsprechen **Heute / 5 Minuten** und **1 Woche / 30 Minuten** der Logik der gezeigten stock3-Vorlage: Es werden Quote-Kerzen angezeigt und nicht nur die deutlich selteneren tatsächlich ausgeführten Abschlüsse.

Für die auswählbaren Ansichten bis etwa drei Jahre werden die verfügbaren L&S-Bid-Historien in 5 Minuten, 1 Stunde und 1 Tag verwendet und je nach Auswahl sauber zu 15/30 Minuten, Wochen oder Monaten verdichtet. Das öffentliche stock3-Format ist keine vertraglich garantierte API und kann sich ändern; deshalb prüft die App jede Antwort auf gültige Zeitstempel und plausible OHLC-Werte, bevor sie diese anzeigt.

**Tradegate BSX** bleibt als automatische Ersatzquelle aktiv, falls Lang & Schwarz vorübergehend nicht erreichbar oder unvollständig ist. Die gerade verwendete Quelle steht jederzeit direkt unter dem Chart. Für Tradegate endet die Signalfreigabe bereits um 22:00 Uhr.

**yfinance** bleibt als historische Kontext- und Reservequelle erhalten, falls eine benötigte öffentliche L&S-Historie zeitweise nicht abrufbar ist. Yahoo-Kerzen werden nicht als L&S-Bid-Daten ausgegeben.

Ein alter letzter Umsatz ist nicht automatisch ein alter Markt: Geld und Brief können sich ändern, obwohl in einer Minute kein Handel zustande kommt. Deshalb basiert der Hauptchart nun auf den Veränderungen des L&S-Geldkurses. Der Briefkurs und der Spread bleiben als Kauf- und Liquiditätsprüfung getrennt erhalten.

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

Die Tests prüfen unter anderem das Deltaformat der öffentlichen stock3-L&S-Bid-Kerzen, die Auswahl des richtigen L&S-Handelsplatzes, den Geld-/Briefkurs, den Tradegate-Fallback, die Chartzeiträume, das von der privaten Position unabhängige Kaufen/Verkaufen-Signal sowie das 2.000-€-Papierkonto mit realem Spread, 1-€-Orderkosten, Ausführungspuffer, doppelter Ordervermeidung und Verkaufsjournal.
