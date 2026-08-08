# Trading-Signal-Agent 0.1

Eine modular aufgebaute Streamlit-Web-App für **experimentelle technische Marktanalysen** und ein vollständig getrenntes Spielgeld-Depot. Sie überwacht die vom Nutzer gepflegte Watchlist, berechnet nachvollziehbare Indikatoren, erzeugt regelbasierte BUY/HOLD/SELL-Einschätzungen und kann virtuelle Positionen führen.

> **Wichtiger Hinweis:** Das Projekt ist keine Anlageberatung, gibt keine Erfolgs- oder Gewinngarantie und führt niemals echte Wertpapierorders aus. Es besitzt keine Trade-Republic-Anbindung, keine Browser-Automatisierung und keine Steuerung einer Broker-App. Reale Transaktionen bleiben vollständig manuell beim Nutzer.

## Funktionsumfang 0.1

- kompakte, für kleine Browserbreiten optimierte Streamlit-Oberfläche mit zwölf Bereichen
- editierbare Watchlist mit Priorität, Analyseintervall und expliziter Spielgeld-Freigabe
- manuell pflegbares echtes Depot, ausschließlich für Analysen und Hinweise
- automatische Realdatenkette: `yfinance`, optional Alpaca Market Data und Twelve Data
- Candlestick-Chart mit Volumen, EMA 20/50/200, VWAP, Bollinger-Bändern und Preiszonen
- RSI 14, MACD/Signallinie/Histogramm, ATR und relatives Volumen
- vorsichtige Unterstützungs-/Widerstandszonen sowie erster Candlestick-Kontext
- transparentes, versioniertes 100-Punkte-Modell mit positiven und negativen Faktoren
- Modi Defensiv, Normal und Aggressiv in getrennten virtuellen Unterdepots
- ausschließlich simulierte Käufe, Teil-/Gesamtverkäufe, Stop-Loss und Take-Profit
- Ausführungsmodell mit konfigurierbarer Gebühr, Spread und Slippage
- harte Risikoregeln: Positionsgröße, Stop-Risiko, Positionslimit, Datenalter, Volumen, Spread, Tagesverlust und Verlustserie
- Trade-Journal und persistente Signal-/Agentenlauf-Historie mit Daten- und Nachrichtenherkunft
- ereignisbasierter Backtest mit Folgekerzen-Ausführung, Equity-Kurve und Buy-and-Hold-Vergleich
- kostenlose echte Watchlist-Nachrichten über yfinance, dedupliziert und vorsichtig regelbasiert bewertet
- SQLite über SQLAlchemy; die Schicht kann später mit PostgreSQL betrieben werden
- deterministische Offline-Tests und GitHub Actions

## Was die App ausdrücklich nicht kann

- keine echten Orders oder Ordervorschläge direkt an einen Broker senden
- keine offizielle oder inoffizielle Trade-Republic-Verbindung herstellen
- keine vollständigen, garantierten oder zwingend Echtzeit-Kursdaten liefern
- keine vollständige, garantierte oder zwingend aktuelle Nachrichtenabdeckung bieten
- keine verlässliche Bedeutung einer Schlagzeile „verstehen“; die Bewertung ist eine begrenzte Heuristik
- keine Handelsgewinne vorhersagen oder versprechen
- keine Strategieparameter selbstständig ändern
- nicht alle bei einem Broker handelbaren Instrumente kennen

Bei fehlenden, zu alten oder widersprüchlichen Daten blockiert das Signalmodell eine Einschätzung. Die normale App besitzt keinen Demo-Schalter. Synthetische Daten sind ausschließlich über `DATA_PROVIDER=mock` für Offline-Tests aktivierbar und werden technisch von Realdatenpositionen getrennt.

## Installation unter macOS/Linux

Voraussetzungen: Python 3.11 oder neuer und Git.

```bash
git clone https://github.com/Scorpion191180/trading-Signal-bot.git
cd trading-Signal-bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Die App liest `.env` nicht automatisch ein; Werte können vor dem Start exportiert oder über eine Shell-/Hosting-Konfiguration gesetzt werden. Für den normalen Realdatenbetrieb genügt:

```bash
export DATA_PROVIDER=auto
streamlit run app.py
```

Danach die von Streamlit angezeigte lokale Adresse öffnen. Beim ersten Start werden Verzeichnis, die neue Realdatenbank `data/trading_signal_live.db`, Tabellen, Standard-Watchlist, Strategien und drei Spielgeld-Unterdepots automatisch angelegt. Eine ältere `data/trading_signal.db` wird weder gelöscht noch übernommen, damit frühere Demo- und Realdatensätze nicht vermischt werden.

## Bedienung des Spielgeld-Depots

1. In **Watchlist** ein Symbol hinzufügen oder direkt einstellen.
2. **Spielgeld erlaubt** bewusst aktivieren. Ohne Freigabe wird nur analysiert.
3. In **Aktienanalyse** Datenqualität, Punkte, Gründe, Stop und Ziel prüfen.
4. Ein regelkonformer BUY kann virtuell bestätigt werden; alternativ prüft **Agenten-Depot → Agentenlauf jetzt starten** die gesamte Liste.
5. Virtuelle Verkäufe entstehen durch Stop-Loss, Take-Profit, SELL-Signal oder einen manuellen virtuellen Verkauf.
6. Ergebnisse stehen im **Trade-Journal**. Sie sind kein Nachweis für zukünftige Resultate.

Jede Strategie beginnt standardmäßig mit 10.000 Euro. Beim Zurücksetzen werden nur Orders, Positionen und Trades des ausdrücklich gewählten virtuellen Unterdepots gelöscht. Ein Reset erfordert eine Bestätigung in der Oberfläche.

## Strategiestandards

Alle Werte liegen zentral in `src/config.py`, sind als Version `v1` in der Datenbank gespeichert und werden in der App angezeigt.

| Modus | BUY ab | SELL bis | Max. Position | Risiko/Trade | Max. Positionen | Stop (ATR) | Ziel (ATR) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Defensiv | 75 | 35 | 10 % | 0,3 % | 3 | 2,2 | 4,4 |
| Normal | 65 | 40 | 15 % | 0,5 % | 5 | 1,8 | 3,2 |
| Aggressiv | 58 | 42 | 20 % | 0,8 % | 7 | 1,4 | 2,4 |

Zusätzlich gelten standardmäßig ein tägliches Verlustlimit von 2 %, eine Pause nach drei Verlusttrades in Folge, ein Nachkaufverbot im MVP, eine Datenalter-Sperre und Mindestanforderungen an Volumen, Spread und Chance-Risiko-Verhältnis. Diese Schutzregeln sind nicht Teil eines später lernenden Parametersatzes.

### Punkteverteilung

| Komponente | Maximum |
|---|---:|
| Übergeordneter Trend | 15 |
| Intraday-Trend | 15 |
| Momentum | 10 |
| Volumen | 15 |
| Unterstützung/Widerstand | 10 |
| Muster | 10 |
| Nachrichten | 15 |
| Markt/Branche | 10 |

Nachrichten werden aus bestätigten Watchlist-Bezügen vorsichtig positiv, negativ oder neutral bewertet. Unklare, gemischte und fehlende Meldungen bleiben neutral; ältere Meldungen erhalten weniger Gewicht. Markt/Branche bleibt in 0.1 neutral. Weder die Nachrichtenkomponente noch ein späteres Sprachmodell darf allein eine Orderentscheidung auslösen.

## Agentenlauf

Ein manueller Lauf ist in der App möglich. Derselbe Einstiegspunkt eignet sich für Render Cron, einen Background Worker oder einen geplanten Prozess:

```bash
export DATA_PROVIDER=auto
python -m src.agent.cli
```

`mock` ist ausschließlich für Offline-Tests und den ausdrücklich benannten Demo-Workflow bestimmt.

Der Agent bildet einen eindeutigen 30-Minuten-Zeitschlüssel. Ein zweiter Lauf im gleichen Zeitfenster erzeugt keine doppelten virtuellen Orders. Zu kurze Kursreihen werden verworfen. Scheitert yfinance bei Kursen, versucht die App konfigurierte Alpaca- und Twelve-Data-Quellen. Sind keine passenden Realdaten verfügbar, wird das Symbol blockiert und der Grund protokolliert. Aktuelle Nachrichten werden vor jeder Symbolanalyse geladen und mit dem Signal, einem Einstieg sowie einem Ausstieg verknüpft. Fällt der Nachrichtenabruf aus, bleibt nur diese Komponente neutral; der Fehler erzeugt keinen erfundenen Inhalt und keinen eigenständigen Trade.

Der optionale GitHub-Workflow **Manueller Demo-Agentenlauf** ist bewusst nur per `workflow_dispatch` startbar und verwendet deterministische Demo-Daten. Eine kurzlebige CI-Datenbank eignet sich nicht für ein dauerhaftes Depot.

## Backtesting

Der Backtest berechnet ein Signal nur aus der bis dahin verfügbaren, abgeschlossenen Kerze `t` und führt frühestens am Open von `t+1` aus. Spread, Slippage und Gebühren verschlechtern den simulierten Ausführungspreis. Treffen Stop und Ziel innerhalb derselben Kerze theoretisch zusammen, wird konservativ zuerst der Stop geprüft.

Trotzdem bleibt das MVP vereinfacht: keine historische Geld-/Brief-Tickserie, kein Delisting-Modell, keine vollständige Liquiditätsmodellierung, keine Dividenden-/Split-Benchmark und keine Währungsumrechnung. Ergebnisse sind daher experimentell und keine belastbare Renditeprognose.

## Konfiguration

| Variable | Standard | Bedeutung |
|---|---|---|
| `DATABASE_URL` | `sqlite:///data/trading_signal_live.db` | getrennte SQLAlchemy-Verbindung für Realdatenläufe |
| `DATA_PROVIDER` | `auto` | Realdaten-Fallbackkette; `mock` nur für Offline-Tests |
| `APCA_API_KEY_ID` | leer | optionaler kostenloser Alpaca-IEX-Fallback |
| `APCA_API_SECRET_KEY` | leer | zugehöriges Alpaca-Secret |
| `TWELVE_DATA_API_KEY` | leer | optionaler kostenloser Intraday-Fallback |
| `APP_TIMEZONE` | `Europe/Berlin` | Anzeige-/Planungszeitzone |
| `STALE_AFTER_MINUTES` | `20` | Sperrgrenze für alte Intraday-Daten |
| `STARTING_CAPITAL` | `10000` | Startkapital je Strategie |
| `ORDER_FEE` | `1.00` | virtuelle Gebühr pro Order |
| `SPREAD_PCT` | `0.001` | gesamter simulierter Spread |
| `SLIPPAGE_PCT` | `0.0005` | zusätzliche virtuelle Slippage |

Zugangsdaten und API-Schlüssel gehören ausschließlich in lokale Umgebungsvariablen, GitHub Secrets oder Render Secrets. `.env` ist ignoriert. Es gibt keine notwendigen kostenpflichtigen APIs.

## Datenquellen und Einschränkungen

Die Reihenfolge im Standardmodus ist:

1. **yfinance:** primäre kostenlose Quelle für Intraday- und Tagesdaten. Intraday-Historie ist auf die letzten 60 Tage begrenzt und Verfügbarkeit, Aktualität, Vor-/Nachbörse sowie Börsenabdeckung sind nicht garantiert.
2. **Alpaca Market Data:** optionaler echter Fallback für US-Aktien. Der kostenlose Tarif bietet derzeit IEX-Daten, mehr als sieben Jahre Historie und bis zu 200 API-Abrufe pro Minute. Er benötigt `APCA_API_KEY_ID` und `APCA_API_SECRET_KEY` aus einem kostenlosen Konto. IEX ist nur eine Börse und das Volumen weicht deshalb vom vollständigen US-Gesamtmarkt ab.
3. **Twelve Data:** optionaler echter Intraday-Fallback mit breiterer Instrumentenabdeckung. Der kostenlose Basic-Tarif umfasst derzeit 8 API-Credits pro Minute und 800 pro Tag. Er benötigt einen persönlichen Schlüssel in `TWELVE_DATA_API_KEY`.

Für Nachrichten verwendet die App die yfinance-Suche pro Watchlist-Symbol. Sie benötigt keinen API-Schlüssel, liefert Titel, Quelle, Zeitpunkt, Link und bestätigte Symbolbezüge und wird in der lokalen Datenbank dedupliziert. Meldungen ohne bestätigten Bezug zu einem Watchlist-Symbol werden nicht gewertet. Eine Schlagzeilen-Heuristik reagiert nur auf explizite Ereignisbegriffe; gemischte oder unbekannte Texte bleiben neutral. Der separat angebotene `Ticker.get_news`-Feed wird nicht als automatischer Fallback gewertet, weil seine Antwort den Symbolbezug nicht durchgehend ausweist und in Live-Prüfungen auch allgemeine Meldungen enthalten kann.

Stooq wurde geprüft, aber nicht integriert: Der frühere CSV-Zugang verlangt inzwischen eine JavaScript-Verifikation und ist damit keine verlässliche automatisierte Rückfallebene. Alpha Vantage bleibt mit 25 kostenlosen Abrufen pro Tag und kostenpflichtigem Intraday für diesen 30-Minuten-Agenten zu knapp. Finnhub bietet im kostenlosen Tarif keine ausreichende OHLC-Historie für das EMA-200-Modell.

Jede Antwort wird auf OHLCV-Spalten, abgeschlossene Kerzen, positive Preise, Volumen und mindestens 200 Datenpunkte geprüft. Die tatsächlich verwendete Quelle wird an Signal, Position, virtueller Order und Trade gespeichert. Ein Wechsel zwischen Demo- und Realdaten ist blockiert. Wechselt eine reale Quelle bei offener Position und weicht der Kurs um mehr als 25 Prozent vom zuletzt gespeicherten Kurs ab, stoppt die App statt einen Gewinn oder Verlust zu buchen.

Kostenlos bedeutet nicht garantiert echtzeitfähig oder für jeden Verwendungszweck lizenziert. Nutzungsbedingungen und Börsenrechte der jeweiligen Anbieter gelten weiterhin. `MockMarketDataProvider` und `MockNewsProvider` bleiben nur für deterministische Offline-Tests im Quellcode; die normale Oberfläche zeigt keine synthetischen Kurse oder Nachrichten.

## Tests und Qualitätsprüfung

```bash
pytest -q
ruff check .
```

Die Tests benötigen keine Netzwerkverbindung und prüfen unter anderem:

- Indikatoren, Punkte, Stop und Ziel
- Datenalter- und Volumensperren
- Positionsgröße und harte Risikoregeln
- Gebühr, Spread und Slippage
- virtuelle Käufe, Verkäufe, Journal und Deduplizierung
- Strategie-/Gewichtsversionierung und Reset
- Fallbackreihenfolge, Quellenherkunft und Schutz vor Demo-/Realdatenmischung
- echte Nachrichten-Normalisierung, Relevanzfilter, Deduplizierung, Altersabschlag und neutraler Fehlerfall
- Backtesting mit Ausführung auf der Folgekerze
- Agentenlauf-Deduplizierung

GitHub Actions führt bei Pushes und Pull Requests Linting und Tests mit Python 3.12 aus. Secrets sind nicht im Workflow hinterlegt.

## Render-Bereitstellung

`render.yaml` beschreibt den Streamlit-Webdienst. Vor einem dauerhaften Betrieb:

1. Repository in Render verbinden.
2. `DATABASE_URL` als Secret auf eine PostgreSQL-Datenbank setzen.
3. weitere Anbieter-Keys ausschließlich als Secrets setzen.
4. einen Cron Job oder Background Worker mit `python -m src.agent.cli` konfigurieren.
5. persistente Logs, Monitoring, Zeitzonen und Marktzeiten ergänzen.

SQLite auf dem flüchtigen Dateisystem eines einfachen Render-Webdienstes ist nicht für dauerhafte Depotdaten geeignet. Der Webdienst allein garantiert auch keinen 30-Minuten-Hintergrundlauf.

## Projektstruktur

```text
app.py                         Streamlit-Einstieg und Navigation
src/config.py                  zentrale Strategien, Gewichte, Umgebung
src/data/                      Anbieter-Vertrag, Realdaten-Fallbacks, Offline-Testdaten
src/analysis/                  Indikatoren, Zonen, Muster, Signale
src/strategies/                versionierter Strategiekatalog
src/portfolio/                 Risiko, virtuelle Ausführung, Backtest
src/database/                  SQLAlchemy-Modelle, Sessions, Transaktionen
src/news/                      echter Nachrichtenanbieter, Bewertung und Offline-Testanbieter
src/agent/                     idempotente 30-Minuten-Orchestrierung und CLI
src/notifications/             vorbereiteter Kanal-Vertrag
src/ui/                        mobile Seiten und Plotly-Charts
tests/                         deterministische Offline-Tests
.github/workflows/             CI und manueller Demo-Lauf
data/                          lokale, ignorierte SQLite-Daten
```

## Geplante Ausbaustufen

1. zusätzliche seriöse Nachrichten-/RSS-Quelle als unabhängiger Fallback und Unternehmensnamensauflösung
2. Mehr-Zeitebenen-Bestätigung, Markt-/Branchenkontext, ADX, Stochastic RSI, MFI und umfangreichere vorsichtige Muster
3. Börsenkalender, Währungsumrechnung, historische Quotes und realistischere Liquiditäts-/Ausführungsmodelle
4. PostgreSQL-Migrationen, Authentifizierung, Render Worker/Cron und Benachrichtigungskanäle
5. rein statistische Strategieauswertung; erst ab ausreichender Stichprobe kontrollierte, reversible Gewichtsversionen
6. Walk-forward-/Out-of-sample-Validierung, Benchmarks und Schutz vor Overfitting

Selbständernder Programmcode ist ausdrücklich nicht vorgesehen.
