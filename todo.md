# SeoBoy – Offene Arbeiten nach Nutzen

Stand: 20.11.2026, Version 0.11.0

## Priorisierung

Reihenfolge nach erwartetem Nutzen für Buchungsanfragen, Diagnose und Aufwand – nicht nach technischer Attraktivität.

| Rang | Vorhaben | Nutzen | Status |
| --- | --- | --- | --- |
| A1 | GSC: Suchanfrage × Zielseite, Chancen und Mehr-URL-Fälle | Zeigt, welche Seiten für welche Nachfrage tatsächlich Klicks bringen | **erledigt in 0.7.0** |
| A2 | GSC standardmäßig in jeden Lauf (Service-Account) | Macht A1 zur Routine statt zum manuellen Export | **erledigt in 0.8.0** |
| A2b | Interaktiver OAuth-Flow und persistente Token-Ablage | Komfort für Nutzer ohne Service-Account | offen |
| A3 | Maßnahmen mit gemeinsamer Ursache bündeln | CTA und 404 werden als eine Baustelle sichtbar; weniger Reportrauschen | **erledigt in 0.8.0** |
| A4 | GSC-Query-/Seitenverlauf über mehrere Läufe | Messbar machen, ob eine Änderung Klicks und Anfragen verbessert | **erledigt in 0.9.0** |
| B1 | URL Inspection in SQLite und Audit-Diff | Indexstatus und Canonical-Abweichungen dauerhaft nachvollziehen | **erledigt in 0.10.0** |
| B2 | TF-IDF-Content-Gaps aus dem Hauptinhalt | Inhaltliche Lücken belastbarer priorisieren als Titel/H1-Listen | **erledigt in 0.11.0** |
| B2b | Near-Duplicate/SimHash und manuelle Wettbewerbs-URL-Auswahl | Ähnliche Seiten und bewusst gewählte Vergleichsseiten erkennen | offen |
| B3 | Local SEO mit externen Profilen und lokalen Ergebnissen | Standortseiten an echten lokalen Signalen messen | offen |
| B4 | Performance/CrUX und Lighthouse | Conversion- und Ladezeitrisiken sichtbar machen | offen |
| C1 | Playwright-Browser-Matrix und CI | Rendering-Diagnose reproduzierbar machen | offen |
| C2 | Reproduzierbare KI-Antwortstichproben für GEO | AI-Sichtbarkeit messen statt nur Bot-Zugriff prüfen | offen |
| C3 | Vollständige Wettbewerber-Läufe, SERP-/Backlink-Adapter | Wettbewerb und Content-Lücken breiter einordnen | offen |
| C4 | Manueller Maßnahmenstatus und Verlauf | Umsetzung und Wirkung im Tool nachhalten | offen |

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
- Offen: interaktiver Desktop-OAuth-Flow, persistente Token-Ablage, Retry/Backoff und
  Quotenbegrenzung, Abgleich der API-Abdeckung mit dem CSV-Import.

Nutzen: Der wichtigste Bericht wird zur Routine, ohne manuellen Export.

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
- Offen: Near-Duplicate-/SimHash-Vergleich und manuelle URL-Auswahl je Seitentyp.
- Eigenes Seitenbudget je Wettbewerber ist über `--max-pages` vorhanden.

### B3 – Local SEO

- Standortmodell mit stabiler Standort-ID in SQLite
- Abgleich mit externen Unternehmensprofilen und Google Business
- Lokale Suchergebnisse mit Ort, Gerät, Zeitpunkt und Quelle
- Konsistenzprüfung über mehrere Seiten und Profile

### B4 – Performance

- CrUX-Felddaten und Lighthouse-Labordaten
- HTTP-Connection-Pool/Keep-Alive
- Last- und Langzeittests für große Sites

## C – Diagnose und Experimente

### C1 – Playwright

- Gepinnte Browser-Versionen und Chromium-/Firefox-/WebKit-Matrix
- CI-Test mit Browser-Image
- Screenshots und Performance-Messwerte optional
- Integration in regelmäßige Crawl-Läufe

### C2 – GEO

- Versionierte Prompt-Sätze und reproduzierbare KI-Stichproben
- Anbieter-, Modell-, Sprach-, Regions- und Suchmodus-Metadaten
- Marken-Erwähnungen und Zitierungen pro erfolgreicher Stichprobe
- Fehlerquote und Kostenbegrenzung je Lauf
- `llms.txt`-Struktur und `@id`-/sameAs-Prüfung vertiefen

### C3 – Wettbewerb

- Vollständige Wettbewerbs-Läufe mit eigener Website-ID und eigenem Lauf
- SERP- und Backlink-Adapter mit Quelle, Region, Gerät und Datum
- Wettbewerbsvergleich in den Laufordner integrieren

### C4 – Maßnahmenstatus

- Manueller Status mit Verlauf
- Einheitliche Erweiterungs-Abdeckung je Lauf
- Migrations für URL Inspection, Wettbewerber, Local SEO und GEO

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

## Bewusste Grenzen

- Der Benchmark ist eine Stichprobe, kein vollständiges Wettbewerbs-Audit.
- Local SEO und GEO sind beobachtungsbasiert und ohne externe Such- bzw. KI-APIs.
- Playwright benötigt eine separate Browser-Installation.
- GSC-API und URL Inspection benötigen gültige OAuth-Zugangsdaten.
- Der CLI-Updater setzt einen Git-Checkout mit Upstream voraus.
