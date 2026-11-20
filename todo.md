# SeoBoy – Offene Arbeiten nach Nutzen

Stand: 20.11.2026, Version 0.18.0

## Priorisierung

Reihenfolge nach erwartetem Nutzen für Buchungsanfragen, Diagnose und Aufwand – nicht nach technischer Attraktivität. Die verbindliche Detail-Spezifikation steht in [docs/erweiterungen_spezifikation.md](docs/erweiterungen_spezifikation.md).

Die nächsten Umsetzungsschritte mit Datenverträgen und Abnahmekriterien stehen in [Monitoring und Wettbewerbsanalyse](docs/monitoring-und-wettbewerb/README.md).

| Rang | Vorhaben | Nutzen | Status |
| --- | --- | --- | --- |
| A1 | GSC: Suchanfrage × Zielseite, Chancen und Mehr-URL-Fälle | Zeigt, welche Seiten für welche Nachfrage tatsächlich Klicks bringen | **erledigt in 0.7.0** |
| A2 | GSC standardmäßig in jeden Lauf (Service-Account) | Macht A1 zur Routine statt zum manuellen Export | **erledigt in 0.8.0** |
| A2b | Interaktiver OAuth-Flow und persistente Token-Ablage | Komfort für Nutzer ohne Service-Account | **erledigt in 0.12.0** |
| A3 | Maßnahmen mit gemeinsamer Ursache bündeln | CTA und 404 werden als eine Baustelle sichtbar; weniger Reportrauschen | **erledigt in 0.8.0** |
| A4 | GSC-Query-/Seitenverlauf über mehrere Läufe | Messbar machen, ob eine Änderung Klicks und Anfragen verbessert | **erledigt in 0.9.0** |
| B1 | URL Inspection in SQLite und Audit-Diff | Indexstatus und Canonical-Abweichungen dauerhaft nachvollziehen | **erledigt in 0.10.0** |
| B2 | TF-IDF-Content-Gaps aus dem Hauptinhalt | Inhaltliche Lücken belastbarer priorisieren als Titel/H1-Listen | **erledigt in 0.11.0** |
| B2b | Near-Duplicate/SimHash und manuelle Wettbewerbs-URL-Auswahl | Ähnliche Seiten und bewusst gewählte Vergleichsseiten erkennen | **erledigt in 0.12.0** |
| B3 | Local SEO mit Profilen und lokalen Ergebnissen | Standortseiten an lokalen Signalen messen | **erledigt in 0.13.0** |
| B4 | Performance/CrUX und Lighthouse | Conversion- und Ladezeitrisiken sichtbar machen | **erledigt in 0.13.0** |
| C1 | Playwright-Browser-Auswahl | Chromium/Firefox/WebKit gezielt prüfen | **erledigt in 0.13.0** |
| C1b | GitHub-Actions-Testlauf | Änderungen automatisch prüfen | **erledigt in 0.14.0** |
| C1c | Playwright-Browser-Matrix mit gepinnten Browsern und Screenshots | Rendering-Diagnose reproduzierbar machen | offen |
| C2 | Reproduzierbare KI-Antwortstichproben für GEO | AI-Sichtbarkeit messen statt nur Bot-Zugriff prüfen | **erledigt in 0.15.0** |
| C3 | Vollständige Wettbewerber-Läufe, SERP-/Backlink-Adapter | Wettbewerb und Content-Lücken breiter einordnen | blockiert: SERP-/Backlink-Zugang |
| C4 | Manueller Maßnahmenstatus und Verlauf | Umsetzung und Wirkung im Tool nachhalten | **erledigt in 0.13.0** |
| D1 | KI-Review des Gesamtaudits | Widersprüche, Datenlücken und Prioritätsfehler finden | **erledigt in 0.16.0** |
| D2 | Keyword-Kannibalisierung | GSC- und On-Page-Evidenz statt bloßer URL-Zählung verbinden | **erledigt in 0.17.0** |

## A – Direkter Buchungsnutzen

### A1 – GSC Suchanfrage × Zielseite (erledigt)

Seit 0.7.0 schreibt jeder Lauf mit GSC-Seiten-Suchanfragen zusätzlich:

- `04_GSC_QUERY_PAGES.md`
- `raw_data/gsc_query_pages.csv`

Der Bericht enthält stärkste Zielseiten und Suchanfragen, Query-/Seitenpaare,
Chancen auf Position 5–20 mit CTR unter 5 Prozent, Mehr-URL-Fälle und Klickveränderungen
zum Vorzeitraum. Nur eindeutig zugeordnete Zeilen werden ausgewertet.

### A2 – GSC automatisieren (Service-Account erledigt)

- **Umgesetzt:** `seoboy run` holt GSC-Daten bei konfigurierten Zugangsdaten automatisch,
  importiert sie in einen temporären Ordner und schreibt danach den Query-/Zielseitenbericht.
- **Umgesetzt:** OAuth-Refresh-Token und Service-Account-JSON; Service-Account-Signatur
  über cryptography oder OpenSSL; Access-Token-Cache nur im Arbeitsspeicher.
- **Umgesetzt:** Property-, Zeitraum- und Tagesoptionen; `SEOBOY_GSC_CREDENTIALS` und
  `SEOBOY_GSC_PROPERTY`.
- Offen: Retry/Backoff und Quotenbegrenzung, Abgleich der API-Abdeckung mit dem CSV-Import.

Nutzen: Der wichtigste Bericht wird zur Routine, ohne manuellen Export.

### A2b – Interaktiver OAuth-Login (erledigt)

- `seoboy gsc-auth --client-file client_secret.json` startet den Loopback-Login.
- PKCE, State-Prüfung und lokaler Callback sind implementiert.
- Der Refresh-Token wird unter `%LOCALAPPDATA%\SeoBoy\gsc-oauth.json` oder
  `SEOBOY_GSC_TOKEN_STORE` gespeichert; Dateirechte restriktiv, keine Verschlüsselung.
- `load_credentials` nutzt den Store automatisch, wenn keine andere Quelle gesetzt ist.
- Access-Tokens bleiben nur im Arbeitsspeicher.

### A3 – Ursachen bündeln (erledigt)

- Der Maßnahmenplan markiert bei einem defekten Link das zusätzliche
  `HTTP_UNAVAILABLE`-Ergebnis als **gemeinsame Ursache**.
- Die Executive Summary zählt die durch dieselbe Ziel-URL verbundenen Befunde.
- Die getrennten Regel-IDs bleiben für Diagnose und Historie erhalten.

Nutzen: Ein defekter Button ist eine Baustelle, nicht drei.

### A4 – Verlauf und Wirkung (erledigt)

- Jeder GSC-Lauf schreibt `05_GSC_HISTORY.md` und `raw_data/gsc_history.csv`.
- Verglichen wird mit dem jüngsten früheren Lauf desselben Projekts, derselben
  Property und derselben Filterkombination.
- Voraussetzung sind gleich lange, nicht überlappende Zeiträume.
- Der Bericht zeigt Gesamt-, Seiten-, Suchanfrage- und Paarveränderungen sowie neue
  und verlorene Paare.
- Klicks, Impressionen, CTR und Position werden getrennt ausgewiesen.

Nutzen: Nach dem nächsten 28-Tage-Fenster ist sichtbar, ob eine Änderung an Titel,
H1, Inhalt oder CTA tatsächlich Klicks und Anfragen verändert hat.

## B – Conversion und Diagnose

### B1 – URL Inspection (erledigt)

- Migration 002 speichert Inspection-Ergebnisse in `url_inspections`.
- `seoboy url-inspection --run <id>` wählt wichtige HTML-URLs automatisch aus.
- Einzel-URL-Modus bleibt für schnelle Ad-hoc-Prüfungen erhalten.
- `06_URL_INSPECTION.md` und `raw_data/url_inspections.csv` werden pro Lauf geschrieben.
- Der Audit-Diff vergleicht Verdict, Coverage, Indexing, Robots, Fetch und Canonicals.
- Fehlgeschlagene API-Aufrufe werden als Fehlerzeile gespeichert, nicht als Erfolg.
- Property-Berechtigungen und API-Kontingente bleiben Laufzeitgrenzen.

### B2 – Content-Gaps (TF-IDF erledigt)

- **Umgesetzt:** Hauptinhalt wird als großgeschriebene Substantiv-Heuristik erfasst;
  gespeichert werden nur Termhäufigkeiten, keine Volltexte.
- **Umgesetzt:** TF-IDF gewichtet Begriffe, die bei mindestens der Hälfte der
  Wettbewerber vorkommen, in der eigenen Stichprobe aber fehlen.
- **Umgesetzt:** Ausgabe in `04_COMPETITOR_BENCHMARK.md` und
  `raw_data/benchmark_content_terms.csv`.
- Eigenes Seitenbudget je Wettbewerber ist über `--max-pages` vorhanden.

### B2b – Near-Duplicate und manuelle URLs (erledigt)

- **Umgesetzt:** SimHash über Content-Terme; Paare mit Hamming-Distanz ≤ 3 werden
  in `04_COMPETITOR_BENCHMARK.md` und `raw_data/benchmark_similar_pages.csv` gezeigt.
- **Umgesetzt:** `--competitor-url` erlaubt manuell ausgewählte Wettbewerbsseiten
  je Website und umgeht die Sitemap-Stichprobe.
- **Umgesetzt:** Die Auswahl wird im Bericht und im Benchmark-Manifest ausgewiesen.
- **Umgesetzt:** `--full` verfolgt mehrere Sitemap-Kinder bis zum expliziten
  `--max-pages`-Budget; das bleibt eine budgetierte Erhebung.
- Grenze: SimHash ist ein Ähnlichkeitshinweis, kein Duplicate-Content-Urteil.

### B3 – Local SEO (erledigt)

- **Umgesetzt:** Standort-YAML unterstützt externe Profil-URLs.
- **Umgesetzt:** Profilseiten werden robots-konform geladen und per Textabgleich auf
  Name, Ort und Telefon geprüft.
- **Umgesetzt:** Lokale Suchpositionen können als CSV
  `query,location,position,url,source,date` beigestellt werden.
- **Umgesetzt:** `local_profiles.csv` und `local_rankings.csv` im Report.
- Grenze: keine offizielle Google-Business- oder Suchmaschinen-API; die Evidenz ist
  beigestellt und nachvollziehbar.

### B4 – Performance (erledigt)

- **Umgesetzt:** PageSpeed Insights/Lighthouse über API-Key.
- **Umgesetzt:** CrUX-Felddaten mit p75-Werten und Formfaktor.
- **Umgesetzt:** `00_PERFORMANCE.md` und `raw_data/performance.csv`.
- Ohne API-Key bricht der Befehl mit Exitcode 2 ab; es werden keine Werte geschätzt.
- Offen: HTTP-Connection-Pool/Keep-Alive und Last-/Langzeittests.

## C – Diagnose und Experimente

### C1 – Playwright (Browser-Auswahl und Chrome-Fallback erledigt)

- **Umgesetzt:** `--browser chromium|firefox|webkit`.
- **Umgesetzt:** `--engine auto|playwright|chrome`.
- **Umgesetzt:** Ohne Playwright nutzt auto einen vorhandenen Chrome/Edge headless;
  der Bericht markiert den fehlenden HTTP-Status.
- **Umgesetzt:** GitHub-Actions-Testlauf auf Windows.
- Offen: gepinnte Playwright-Browser-Versionen, Browser-Matrix im CI, Screenshots,
  Performance-Messwerte und Integration in regelmäßige Crawl-Läufe.

### C2 – GEO-Sampling (erledigt)

- **Umgesetzt:** DeepSeek-Adapter mit `deepseek-flash` im Non-Thinking-Modus.
- **Umgesetzt:** versionierte Prompt-Sätze, Sprache, Region und Intent.
- **Umgesetzt:** Marken-Erwähnungen, eigene/fremde URL-Zitate und Wettbewerber-Zählung.
- **Umgesetzt:** Aufruf-, Token- und Kostenbudget; Stopp bei Auth- und Fehlerrate.
- **Umgesetzt:** lokale Rohantworten, CSV-Auswertung und Manifest.
- **Live, ohne Websuche:** 6/6 erfolgreich, 3312 Tokens, ca. 0,004 USD;
  AW Audio wurde in dieser Runde nicht genannt oder zitiert.
- **Live, mit Websuche:** 6/6 erfolgreich, 70493 Tokens, ca. 0,030 USD;
  AW Audio/Arne Winter wurde 1/6 genannt, aw-audio.de 1/6 zitiert.
- **Live, Max-Modus:** DeepSeek-V4.1-Flash-1017, Thinking enabled, Effort max;
  ein Prompt mit 6978 Tokens, ein Prompt mit Websuche und 180518 Tokens.
- Standard ist jetzt Max-Modus; `--thinking disabled` bleibt der günstige Modus.
- Grenze: eine Momentaufnahme, keine Rankings; Wiederholungen und weitere Modelle nötig.
- Offen: `llms.txt`-Struktur und `@id`-/sameAs-Prüfung vertiefen.

### C3 – Wettbewerb (blockiert)

- Vollständige Wettbewerbs-Läufe mit eigener Website-ID und eigenem Lauf
- SERP- und Backlink-Adapter mit Quelle, Region, Gerät und Datum
- Wettbewerbsvergleich in den Laufordner integrieren

Blockiert: SERP- und Backlink-Daten benötigen einen lizenzierten Anbieter oder eine
ausdrücklich erlaubte API. Stichprobe und manuelle URLs sind vorhanden; ein vollständiger
Wettbewerbs-Crawl wäre ohne eigene Budgets und Rechtsprüfung nicht vertretbar.

### C4 – Maßnahmenstatus (erledigt)

- **Umgesetzt:** Migration 003 mit `action_statuses` und `action_status_history`.
- **Umgesetzt:** `seoboy action-status --list/--history`.
- **Umgesetzt:** Status `open`, `in_progress`, `done`, `ignored` mit Notiz und Zeitstempel.
- **Umgesetzt:** Status erscheint im Maßnahmenplan und wird bei `report` neu gerendert.
- Offen: einheitliche Erweiterungs-Abdeckung je Lauf.

## D – KI-Review

### D1 – Beratende Review des Gesamtaudits (erledigt)

- **Umgesetzt:** `seoboy ai-review --run <id>` und `seoboy run --ai-review`.
- **Umgesetzt:** kompakte Evidenzpackung statt HTML oder Rohdatenbank.
- **Umgesetzt:** strukturierte JSON-Antwort mit Evidenz- und Maßnahmenreferenzen.
- **Umgesetzt:** Validierung unbekannter Referenzen als ungeprüft.
- **Umgesetzt:** nur ein API-Aufruf, 40 Befunde/25 Maßnahmen, 0,25 USD Budget.
- **Umgesetzt:** SHA-256-Cache; Cache-Treffer kosten keinen Aufruf.
- **Umgesetzt:** 07_AI_REVIEW.md, JSON, CSV und Link in der Executive Summary.
- **Live:** aw-audio-Review mit 20 Befunden/20 Maßnahmen, gültige Referenzen,
  ca. 0,0065 USD.
- Grenze: KI-Review ist advisory und ändert keine Prioritäten automatisch.

### D2 – Keyword-Kannibalisierung (erledigt)

- **Umgesetzt:** eigener Bericht 08_KEYWORD_CANNIBALIZATION.md und CSV.
- **Umgesetzt:** GSC-Query-/URL-Paare mit Impressionen, Klicks und Positionen.
- **Umgesetzt:** Title-/H1- und Content-Überlappung als zweite Evidenzquelle.
- **Umgesetzt:** Evidenzstufen A, B und C statt pauschaler Kannibalisierungsbehauptung.
- **Umgesetzt:** Ausschluss von Markenqueries, noindex, Canonical-Zielen, Utility-
  und Pagination-Seiten.
- **Umgesetzt:** ohne GSC nur On-Page-Hinweise, ausdrücklich als solche gekennzeichnet.
- **Live:** aw-audio zeigt ein GSC-Paar für /hochzeit-dj/ und /dj-koeln/ auf Stufe B
  sowie ein schwaches Paar auf Stufe C; keine On-Page-Bestätigung.
- Grenze: keine lizenzierte SERP-Überschneidung und keine Volltext-Embeddings.

## Erledigt

- Lokaler HTTP-Crawl mit robots.txt, Sitemaps, Redirects, Budgets und Resume
- Technische Kernregeln und GSC-CSV-Regeln mit P1–P4-Priorisierung
- GSC-CSV-Import, deutscher GSC-UI-Aufbereiter und URL-Zuordnung
- Markdown-/CSV-Berichte, Manifest, Abdeckung und Audit-Diff
- Paralleler Crawl, Batch-Modus und SQLite-Performanceoptimierungen
- Unterseitenanalyse mit H1, Wortzahl, Bild-Alt-Texten und Schema
- Begrenzter Wettbewerbsbenchmark plus Begriffskandidaten aus Titel/H1
- GSC-API-Abruf per Refresh-Token in das vorhandene Importformat
- GSC-Auswertung Suchanfrage × Zielseite mit Chancen und Mehr-URL-Erkennung
- URL-Inspection-Abfrage mit JSON-/Markdown-Bericht
- Optionaler Playwright-Renderer mit HTTP-/Browser-DOM-Vergleich
- Local-SEO-Prüfung für Standortseiten, NAP und LocalBusiness-Schema
- GEO-Readiness für AI-Bots, `llms.txt` und Schema-Signale
- Git-basierter CLI-Updater mit Fast-Forward, Smoke-Test und Rollback
- Selbstständiger Systemcheck mit `seoboy doctor`
- PDFs und andere Nicht-HTML-Ziele werden als „nicht bewertet“ geführt
- Local-SEO-Profile und beigestellte lokale Messergebnisse
- PageSpeed/Lighthouse- und CrUX-Adapter
- Playwright-Browser-Auswahl für Chromium, Firefox und WebKit
- Maßnahmenstatus mit Verlauf und Projektbindung
- DeepSeek-GEO-Sampling mit Budget, Zitaten und Marken-Auswertung

## Bewusste Grenzen

- Der Benchmark ist eine Stichprobe, kein vollständiges Wettbewerbs-Audit.
- Local SEO und GEO sind beobachtungsbasiert und ohne externe Such- bzw. KI-APIs.
- Playwright benötigt eine separate Browser-Installation.
- GSC-API und URL Inspection benötigen gültige OAuth-Zugangsdaten.
- Der CLI-Updater setzt einen Git-Checkout mit Upstream voraus.
