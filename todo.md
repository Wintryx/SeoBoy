# SeoBoy – Offene Arbeiten

Stand: 20.11.2026, Version 0.6.2

## Erledigt

- Lokaler HTTP-Crawl mit robots.txt, Sitemaps, Redirects, Budgets und Resume
- Technische Kernregeln und GSC-CSV-Regeln mit P1–P4-Priorisierung
- GSC-CSV-Import, deutscher GSC-UI-Aufbereiter und URL-Zuordnung
- Markdown-/CSV-Berichte, Manifest, Abdeckung und Audit-Diff
- Paralleler Crawl, Batch-Modus und SQLite-Performanceoptimierungen
- Unterseitenanalyse mit H1, Wortzahl, Bild-Alt-Texten und Schema
- Begrenzter Wettbewerbsbenchmark plus Begriffskandidaten aus Titel/H1
- GSC-API-Abruf per Refresh-Token in das vorhandene Importformat
- URL-Inspection-Abfrage mit JSON-/Markdown-Bericht
- Optionaler Playwright-Renderer mit HTTP-/Browser-DOM-Vergleich
- Local-SEO-Prüfung für Standortseiten, NAP und LocalBusiness-Schema
- GEO-Readiness für Googlebot, Google-Extended, GPTBot, OAI-SearchBot,
  PerplexityBot und ClaudeBot sowie llms.txt und Schema-Signale
- Git-basierter CLI-Updater mit Fast-Forward, Smoke-Test und Rollback
- Selbstständiger Systemcheck mit seoboy doctor für den Betrieb ohne KI-Agent

## Offen

### GSC-API

- Interaktiver Desktop-OAuth-Flow mit lokalem Redirect
- Verschlüsselte oder OS-geschützte Token-Ablage
- Automatische Token-Erneuerung mit Caching und sicherem Fehlerpfad
- Retry/Backoff, Quoten- und Kostenbegrenzung
- Automatische API-Übergabe an einen Lauf ohne CSV-Zwischenschritt
- Abgleich der API-Abdeckung mit dem CSV-Import

### URL Inspection

- Persistenz in SQLite statt nur JSON/Markdown
- Automatische Auswahl wichtiger URLs je Lauf
- Vergleich HTTP-Canonical, Google-Canonical und Indexstatus
- Integration in den Audit-Diff
- Berücksichtigung von Property-Berechtigungen und Kontingenten

### Playwright-Rendering

- Echte Browser-Installation und gepinnte Browser-Versionen
- Chromium-/Firefox-/WebKit-Matrix
- CI-Test mit gepinntem Browser-Image
- Screenshots und Performance-Messwerte optional
- Integration in regelmäßige Crawl-Läufe statt separatem Befehl

### Wettbewerb

- Vollständige Wettbewerbs-Läufe mit eigener Website-ID und eigenem Lauf
- Manuelle URL-Auswahl je Seitentyp und Suchintention
- Eigenes Seiten- und Anfragebudget je Wettbewerber
- TF-IDF-Content-Gaps aus Hauptinhalt statt nur Titel/H1
- Near-Duplicate-/SimHash-Vergleich
- SERP- und Backlink-Adapter mit Quelle, Region, Gerät und Datum

### Local SEO

- Standortmodell mit stabiler Standort-ID in SQLite
- Abgleich mit externen Unternehmensprofilen und Google Business
- Lokale Suchergebnisse mit Ort, Gerät, Zeitpunkt und Quelle
- Standortseiten und Zielgebiete je Projekt konfigurierbar machen
- Konsistenzprüfung über mehrere Seiten und Profile

### GEO

- Versionierte Prompt-Sätze und reproduzierbare KI-Stichproben
- Anbieter-, Modell-, Sprach-, Regions- und Suchmodus-Metadaten
- Zählung von Marken-Erwähnungen und Zitierungen pro erfolgreicher Stichprobe
- Fehlerquote und Kostenbegrenzung je Lauf
- Optionales Sentiment nur als manuelle Einordnung
- llms.txt-Struktur und @id-/sameAs-Prüfung vertiefen

### Performance und Betrieb

- CrUX-Felddaten und Lighthouse-Labordaten
- HTTP-Connection-Pool/Keep-Alive
- Per-Wettbewerber-Request-Budget
- Last- und Langzeittests für große Sites
- Update-Kanal für signierte Releases oder PyPI

### Reporting und Datenmodell

- Migrationen für URL Inspection, Wettbewerber, Local SEO und GEO
- 03_GEO_AND_AI_READINESS.md als vollständiger Run-Bericht
- 04_COMPETITOR_BENCHMARK.md in den Laufordner integrieren
- Manueller Maßnahmenstatus mit Verlauf
- Einheitliche Erweiterungs-Abdeckung je Lauf

## Bewusste Grenzen

- Der Benchmark ist eine Stichprobe, kein vollständiges Wettbewerbs-Audit.
- Local SEO und GEO sind beobachtungsbasiert und ohne externe Such- bzw. KI-APIs.
- Playwright benötigt eine separate Browser-Installation.
- GSC-API und URL Inspection benötigen gültige OAuth-Zugangsdaten.
- Der CLI-Updater setzt einen Git-Checkout mit Upstream voraus.
