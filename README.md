# SeoBoy

SeoBoy ist ein lokales SEO-Audit für eigene Websites. Es crawlt eine Site, speichert
jede Beobachtung in SQLite, wertet technische Regeln aus und verbindet die Befunde mit
Daten aus der Google Search Console. Das Ergebnis ist ein priorisierter Maßnahmenplan
mit nachvollziehbarer Evidenz sowie ein Vergleich zweier Läufe.

Aktueller Stand: 0.6.3 mit einer Website pro Projekt, parallelem HTTP-Crawl,
GSC-CSV-Import und GSC-API/URL Inspection, technischen Kernregeln,
Unterseiten-Inhaltsanalyse, Wettbewerbsbenchmark, optionalem Playwright-Rendering,
Local-SEO-/NAP-Prüfung, GEO-Readiness, Markdown-/CSV-Berichten, Audit-Diff, Batch-Modus
und Git-basiertem CLI-Updater. Alle Prüfungen arbeiten ausschließlich lesend.

## Funktionsumfang

- HTTP-Crawl mit robots.txt, XML-Sitemaps, Sitemap-Indizes, internen Links und Redirects
- Parallele Seitenabrufe mit globalem Worker-Pool, Host-Limit und Mindestabstand
- Batch-Modus für mehrere Projekte mit getrennten SQLite-Datenbanken
- Sicherer Git-basierter CLI-Updater mit Prüfung, Fast-Forward, Smoke-Test und Rollback
- Selbstständiger Systemcheck mit `seoboy doctor`
- URL-Normalisierung mit stabilen Identitäten und nachvollziehbaren Herkunftsarten
- Budgets für URLs, Anfragen und Laufzeit; Wiederaufnahme nach Pause oder Abbruch
- Wiederholungen bei 429, 5xx und Timeouts, inklusive Retry-After
- Regeln für HTTP, Indexierung, Canonicals, Sitemaps, interne Links und Metadaten
- Unterseitenanalyse mit Titel-/Beschreibungslänge, H1, Wortzahl, Bild-Alt-Texten und Schema
- PDFs, HTTP-Fehler und Weiterleitungen werden als „nicht bewertet“ statt als Inhaltsfehler geführt
- Wettbewerbsbenchmark mit begrenzter, robots-konformer Seitenstichprobe
- GSC-Import mit Manifest, Seiten- und URL-Suchanfrage-Granularität
- GSC-API-Abruf über Refresh-Token und URL Inspection API
- Aufbereiter für den deutschen GSC-UI-Seitenexport (Semikolon, Dezimalkomma)
- Optionales Playwright-Rendering mit HTTP-/Browser-DOM-Vergleich
- Local-SEO-Prüfung für Standorte, NAP und LocalBusiness-Schema
- GEO-Readiness für AI-Bots, llms.txt und vorhandene Content-/Schema-Signale
- Priorisierte Maßnahmen (P1 bis P4), Quick Wins und Evidenz je Befund
- Markdown-Berichte, CSV-Rohdaten und Manifest je Lauf
- Vergleich zweier Läufe mit den Zuständen neu, erstmals beobachtet, fortbestehend,
  behoben, ungeprüft und nicht vergleichbar

Nicht in dieser Stufe: interaktiver OAuth-Browserflow, vollständige
Wettbewerber-Crawls, SERP-/Backlink-Adapter, lokale Suchergebnisse, KI-Antwortstichproben,
Performance-/CrUX-Messungen und ein manueller Maßnahmenstatus.

## Voraussetzungen

- Python 3.11 oder neuer (getestet mit Python 3.12)
- SQLite 3.38 oder neuer (JSON-Funktionen, STRICT-Tabellen)
- PyYAML 6

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\seoboy.exe --version
```

Für einen Lauf ohne Installation im Quellbaum kann `$env:PYTHONPATH = ".\src"` gesetzt
und `python -m seoboy ...` verwendet werden. Die Tests brauchen nur die Standardbibliothek
und PyYAML.

## Nutzung ohne KI-Agent

SeoBoy ist ein normales lokales CLI-Werkzeug und benötigt zur Laufzeit keinen KI-Agenten,
kein LLM, kein Konto und keine API-Schlüssel. Der Kernbetrieb braucht nur Python, PyYAML
und eine YAML-Konfiguration.

```powershell
seoboy doctor --config .\seoboy.yaml
```

`doctor` prüft Python, SQLite inklusive JSON-Funktionen, PyYAML, Git, Playwright,
Konfiguration, Datenbank-/Berichtsverzeichnisse und optional den GSC-API-Zugang. Fehlende
optionale Komponenten erscheinen als Hinweis; erforderliche Fehler führen zu Exitcode 2.
Mit `--strict` werden auch Hinweise zu Fehlern.

Optional und nur bei Bedarf:

- **GSC-API/URL Inspection:** OAuth-Zugangsdatei mit Refresh-Token.
- **Playwright-Rendering:** zusätzliche Installation von Playwright und Chromium.
- **CLI-Updater:** Git-Checkout mit Upstream.
- **GSC-CSV:** ein normalisierter Importordner.

`AGENTS.md` ist ausschließlich eine Arbeitsanweisung für Coding-Agenten und wird von der
SeoBoy-Laufzeit nicht gelesen. Die Bedienung erfolgt vollständig über die CLI und die
dokumentierten YAML-/JSON-Dateien.

## CLI aktualisieren

SeoBoy aktualisiert sich aus dem lokalen Git-Checkout:

```powershell
seoboy update --check
seoboy update --apply
```

`--check` ruft den Upstream ab und zeigt Version, Commit, Branch und den Abstand zum
Remote. `--apply` führt ausschließlich einen Fast-Forward aus, installiert das Paket
anschließend mit `pip install -e .` und prüft `seoboy --version` in einem neuen Prozess.

Voraussetzungen und Sicherheitsregeln:

- Der Checkout benötigt einen Git-Branch mit konfiguriertem Upstream.
- Lokale Änderungen oder untracked Dateien blockieren das Update.
- Divergierte Branches werden nicht automatisch zusammengeführt.
- Schlägt Installation oder Smoke-Test fehl, wird der alte Commit wiederhergestellt.
- `--no-install` überspringt die Neuinstallation für extern verwaltete Umgebungen.
- Auf Windows mit aktivem `seoboy.exe` die Neuinstallation über
  `python -m seoboy update --apply` starten oder `--no-install` verwenden.
- Nicht während eines laufenden Audits aktualisieren.
- Datenbankmigrationen laufen beim nächsten normalen SeoBoy-Befehl.
- Ohne konfigurierten Upstream meldet der Updater einen Fehler; dann zuerst
  `git branch --set-upstream-to=origin/main` setzen.
- Der Updater ist für Git-Checkouts gedacht. Bei einer Wheel-/PyPI-Installation wird
  stattdessen `pip install --upgrade seoboy` verwendet.

## Lokale Umgebung (.env)

SeoBoy liest optional eine `.env` aus dem Arbeitsverzeichnis oder der Projektwurzel.
Bereits gesetzte Umgebungsvariablen werden nicht überschrieben. Die Datei ist für lokale
Pfade und optionale Datenquellen gedacht; Secrets gehören nicht hinein.

```powershell
Copy-Item .env.example .env
notepad .env
```

| Variable | Bedeutung |
| --- | --- |
| `SEOBOY_CONFIG` | Standardpfad für `--config`, z. B. `./local/projekt/seoboy.yaml` |
| `SEOBOY_GSC_DIR` | Standard für `seoboy run --gsc-dir`; bei `--resume` ignoriert |
| `SEOBOY_ENV_FILE` | Alternatives Env-File; muss vor dem Prozessstart gesetzt sein |

Explizite CLI-Optionen haben Vorrang. `.env` ist in `.gitignore` und wird nicht
versioniert; `.env.example` ist die dokumentierte Vorlage. Lokale Konfigurationen,
Datenbanken und Berichte können unter `local/` liegen, das ebenfalls ignoriert wird.

Hinweise für Agenten und Mitentwickler stehen in [AGENTS.md](AGENTS.md).

## Schnellstart

```powershell
seoboy init --url https://example.de/
seoboy migrate
seoboy run
seoboy run --gsc-dir .\imports\gsc
seoboy batch --config .\projekt-a\seoboy.yaml --config .\projekt-b\seoboy.yaml --workers 2
seoboy benchmark --config .\seoboy.yaml --competitor https://wettbewerb.de/ --max-pages 20
seoboy inspect https://example.de/leistungen/
seoboy diff --base <lauf-id> --target <lauf-id>
seoboy report --run <lauf-id>
```

`init` legt `seoboy.yaml` an und überschreibt keine vorhandene Datei. `migrate` legt die
SQLite-Datenbank an oder aktualisiert das Schema. Relative Pfade in der Konfiguration
beziehen sich auf das Verzeichnis der Konfigurationsdatei.

Exitcodes: `0` erfolgreich, `1` verwendbarer Teillauf oder pausierter Lauf, `2` Fehler
ohne verwendbares Ergebnis. Die Priorität eines Befunds beeinflusst den Exitcode nicht.

## Projektkonfiguration

```yaml
project_id: example-de
start_url: https://example.de/
allowed_hosts: [example.de]
database: ./data/seoboy.db
reports_dir: ./reports

crawl:
  max_urls: 500
  max_requests: 1500
  max_runtime_seconds: 900
  max_parallel_per_host: 2
  max_workers: 8
  min_request_interval_ms: 500
  max_redirects: 10
  request_timeout_seconds: 15
  max_response_bytes: 5000000
  remove_query_params: [utm_*, gclid, fbclid]
  exclude_paths: [/wp-admin/**, /wp-login.php, /feed/**]

seeds: []

priority_pages:
  - path: /leistungen/**
    page_type: service
    business_value: high
    expected_indexable: true
  - path: /danke/
    page_type: utility
    business_value: low
    expected_indexable: false

rule_exceptions:
  - rule_id: INDEX_NOINDEX
    path: /danke/
    reason: Danke-Seite soll nicht indexiert werden
    expires: 2026-12-31

link_depth_limit: 3

gsc:
  near_top_min_impressions: 100
  near_top_position_min: 5
  near_top_position_max: 20
  decline_min_previous_clicks: 20
  decline_min_clicks: 10
  decline_min_ratio: 0.25
  ctr_min_impressions: 100
  ctr_min_drop: 0.02
  ctr_max_position_delta: 1.0
  multi_url_min_impressions: 30
  multi_url_min_urls: 2
```

Erläuterungen:

- `allowed_hosts` enthält exakte Hostnamen. Subdomains müssen ausdrücklich genannt werden.
- Pfadmuster beginnen mit `/`. `*` gilt innerhalb eines Segments, `**` kann mehrere
  Segmente umfassen. Die erste passende Regel in `priority_pages` gewinnt.
- Die Startseite gilt ohne eigenes Profil als geschäftlich wichtig und indexierbar.
  Andere Seiten ohne Profil haben Bedeutung `normal`, Seitentyp und Soll-Indexierbarkeit
  sind unbekannt.
- `rule_exceptions` unterdrücken nur die Maßnahme. Der Befund bleibt mit Ausnahme im
  Prüfergebnis sichtbar; das Ablaufdatum gilt bis einschließlich des Kalendertags.
- `remove_query_params` entfernt passende Query-Parameter vollständig (Muster mit `*`).
- `max_workers` begrenzt die parallelen Seitenabrufe im gesamten Lauf.
  `max_parallel_per_host` begrenzt zusätzlich die gleichzeitigen Anfragen pro Host.
  `min_request_interval_ms` erzwingt den Mindestabstand zwischen Startzeitpunkten.
- Die GSC-Schwellen sind optional und entsprechen den Vorgaben aus Teil 2.

## Crawl-Verhalten

- **Entdeckung:** Startseite, `seeds`, interne Links, robots.txt-Sitemaps, rekursive
  Sitemap-Indizes und optional GSC-URLs. Alle Herkunftsarten werden je URL gespeichert.
- **Reihenfolge:** Startseite und manuelle Start-URLs zuerst, danach verlinkte Seiten
  nach Klicktiefe, zuletzt unverlinkte Sitemap- und GSC-URLs. Bei Gleichstand entscheidet
  die normalisierte URL.
- **URL-Identität:** Schema und Host werden kleingeschrieben, Standardports, Fragmente
  und Tracking-Parameter entfernt. Pfadschreibweise, abschließender Slash und übrige
  Query-Parameter bleiben erhalten. Canonicals führen nicht zum Zusammenlegen von URLs.
- **Robots:** SeoBoy respektiert robots.txt für den eigenen Agenten `SeoBoy`. Die
  Googlebot-Auswertung für `INDEX_ROBOTS_BLOCKED` erfolgt getrennt aus derselben Datei.
  Ein nicht erreichbarer robots.txt-Abruf wird als `unreachable` gespeichert; die
  Googlebot-Prüfung bleibt dann ungeprüft.
- **Parallelität:** Bis zu `max_workers` Seiten werden gleichzeitig abgerufen,
  pro Host höchstens `max_parallel_per_host`. SQLite-Schreibvorgänge bleiben auf dem
  Hauptthread serialisiert; dadurch bleiben Transaktionen und IDs konsistent.
- **Budgets:** `max_urls` zählt zugelassene Seiten, `max_requests` jede reservierte
  Anfrage einschließlich Hilfsabrufen, Redirects und Wiederholungen. Sitemap- und
  robots-Abrufe belegen keinen Seitenplatz. Bei ausgeschöpftem Gesamtbudget endet der
  Lauf als Teillauf mit `deferred`-URLs.
- **Wiederholungen:** bis zu drei Versuche bei 429, 5xx und Timeouts. Retry-After und die
  Mindestpause pro Origin bleiben über Pausen hinweg gespeichert.
- **Hilfsabrufe:** robots.txt und Sitemap-Dokumente werden im MVP ohne Verfolgung von
  Weiterleitungen geladen. Ein Redirect wird als nicht verfügbar bzw. ungültig ausgewiesen.
- **Wiederaufnahme:** `run --resume <lauf-id>` prüft Konfigurationshash und Versionen.
  Bei Abweichung endet der Aufruf mit Code 2, ohne den Lauf zu verändern. Unterbrochene
  Versuche bleiben im Anfragebudget und werden erneut eingeplant.
- **Berichte:** Ein pausierter Lauf erzeugt noch keine Berichte. Nach dem Abschluss
  schreibt `run` die Berichte; `report --run <lauf-id>` kann sie erneut rendern.

## Parallelität und Batch

Seitenabrufe laufen in einem Thread-Pool. Die Netzwerk-Ebene arbeitet parallel, während
SQLite-Schreibvorgänge, Budgetprüfung und Zustandsübergänge auf dem Hauptthread bleiben.
So bleiben Transaktionen, IDs und Resume-Semantik deterministisch.

```yaml
crawl:
  max_workers: 8              # globale parallele Seitenabrufe
  max_parallel_per_host: 2    # gleichzeitige Anfragen pro Host
  min_request_interval_ms: 500
```

Für mehrere Projekte gibt es `batch`:

```powershell
seoboy batch --config .\projekt-a\seoboy.yaml --config .\projekt-b\seoboy.yaml --workers 2
```

Jede Konfiguration benötigt eine **eigene SQLite-Datenbank**; derselbe Datenbankpfad wird
im Batch bewusst abgelehnt, weil SQLite nur einen Schreiber gleichzeitig zulässt. Auch
dieselbe Website (Host und Port) wird nicht parallel geprüft, um die Last pro Server zu
begrenzen. GSC-Daten werden im Batch nicht importiert; dafür bleibt `run --gsc-dir` der
richtige Weg. Der Batch-Exitcode ist `0`, wenn alle Läufe erfolgreich sind, `1` bei
mindestens einem Teillauf und `2` bei einem Fehler.

## Wettbewerbsvergleich

`benchmark` vergleicht den letzten abgeschlossenen eigenen Lauf mit einer begrenzten
Stichprobe öffentlich erreichbarer Wettbewerbsseiten:

```powershell
seoboy benchmark `
  --config .\seoboy.yaml `
  --competitor https://wettbewerb-a.de/ `
  --competitor https://wettbewerb-b.de/ `
  --max-pages 20
```

- Grundlage ist der letzte `completed`-Lauf der eigenen Konfiguration.
- Je Wettbewerber werden höchstens `--max-pages` Seiten aus robots.txt-Sitemaps oder
  Startseitenlinks geladen; robots.txt wird respektiert.
- Der Vergleich ist eine Stichprobe, kein vollständiges Wettbewerbs-Audit.
- Ausgegeben werden `04_COMPETITOR_BENCHMARK.md`, `raw_data/benchmark_pages.csv`
  und `manifest.json` in einem eigenen Berichtsordner.
- Verglichen werden unter anderem Indexierbarkeit, Titel-/Beschreibungslängen, H1,
  Wortzahl, strukturierte Daten, Bild-Alt-Texte und interne Links.
- Wettbewerbs-HTML wird nicht gespeichert; gespeichert werden nur Metriken und URLs.

## Google Search Console

Der MVP liest einen normalisierten CSV-Import. Das Verzeichnis enthält eine
`manifest.json` und die genannten Dateien:

```json
{
  "property": "sc-domain:example.de",
  "search_type": "web",
  "country": null,
  "device": null,
  "periods": [
    {
      "start": "2026-10-01",
      "end": "2026-10-28",
      "source_format": "gsc_ui_csv",
      "pages": "2026-10_pages.csv",
      "page_queries": "2026-10_queries.csv"
    },
    {
      "start": "2026-09-03",
      "end": "2026-09-30",
      "pages": "2026-09_pages.csv"
    }
  ]
}
```

Pflichtspalten: `page,clicks,impressions,position` für den Seitenbericht;
`page,query,clicks,impressions,position` für den optionalen URL-Suchanfragenbericht.
Die Dateien sind UTF-8 (optional mit BOM), kommagetrennt und verwenden einen Punkt als
Dezimalzeichen. Ungültige Zeilen machen die betreffende Datei unverwendbar; der Lauf
läuft mit Status `partial` oder `unavailable` weiter und weist Fehler mit Zeile und Grund
aus. Nicht zuordenbare oder mehrdeutige Seiten werden je Zeile ausgewiesen. Position `0`
aus einer `gsc_ui_csv`-Quelle wird als unbekannt übernommen.

### Aufbereiter für den GSC-UI-Export

`gsc-prepare` überführt einen Seitenexport aus der Search Console in das normalisierte
Format. Fehlende oder mehrdeutige Spalten werden gemeldet. Das Spaltenmapping ist optional
und kann deutsche Header explizit zuordnen:

```powershell
seoboy gsc-prepare `
  --input .\exports\seiten_okt_2026.csv `
  --out .\imports\gsc `
  --property sc-domain:example.de `
  --start 2026-10-01 --end 2026-10-28
```

Erkannt werden unter anderem `Top-Seiten`/`Top pages`, `Klicks`/`Clicks`,
`Impressionen`/`Impressions` und `Durchschnittliche Position`/`Average position`.
Trennzeichen (`;`, `,`, Tab) und Dezimalzeichen (`,` oder `.`) werden erkannt oder über
`--delimiter` und `--decimal` gesetzt. Das Manifest wird angelegt oder um den Zeitraum
ergänzt; abweichende Property- oder Filterangaben führen zu einem Fehler.

### GSC-API und URL Inspection

Für die direkte Search-Console-Anbindung wird eine Zugangsdatei außerhalb des Repositories
benötigt. Sie enthält OAuth-Client und Refresh-Token:

```json
{
  "client_id": "...",
  "client_secret": "...",
  "refresh_token": "..."
}
```

Der Pfad kann über `--credentials` oder `SEOBOY_GSC_CREDENTIALS` gesetzt werden.
`gsc-fetch` schreibt einen normalisierten Importordner, den `run --gsc-dir` direkt liest:

```powershell
seoboy gsc-fetch `
  --property sc-domain:example.de `
  --start 2026-10-01 --end 2026-10-31 `
  --out .\imports\gsc-api
seoboy run --gsc-dir .\imports\gsc-api
```

`url-inspection` fragt Googles gespeicherten Indexstand für eine URL ab und schreibt JSON
und Markdown:

```powershell
seoboy url-inspection `
  --property sc-domain:example.de `
  --url https://example.de/leistungen/
```

Ein interaktiver OAuth-Browserflow und die dauerhafte Token-Ablage sind noch offen;
aktuell wird ein vorhandener Refresh-Token verwendet. Zugangsdaten gehören nicht ins
Repository und nicht in Berichte.

### Playwright-Rendering

Rendering ist optional und benötigt Playwright plus Chromium:

```powershell
.\venv\Scripts\python.exe -m pip install -e ".[rendering]"
.\venv\Scripts\playwright.exe install chromium
seoboy render --url https://example.de/ --url https://example.de/leistungen/
```

Der Bericht vergleicht HTTP-Dokument und Browser-DOM (Titel, Beschreibung, H1, Wörter,
Links, Schema). Ohne installierten Browser endet der Befehl mit einer verständlichen
Fehlermeldung.

### Local SEO

Standorte werden in einer YAML-Datei gepflegt:

```yaml
locations:
  - label: Köln
    url: https://example.de/standort/koeln/
    name: Beispiel DJ
    street: Musterweg 1
    postal_code: "50667"
    city: Köln
    region: NRW
    country: DE
    phone: "+49 221 123456"
```

```powershell
seoboy local --locations .\local\standorte.yaml
```

Geprüft werden Erreichbarkeit, Indexierbarkeit, H1, Schema und die Konsistenz von Name,
Adresse und Telefon im LocalBusiness-/Organization-JSON-LD. Die Prüfung ist
beobachtungsbasiert; externe Unternehmensprofile und lokale Suchergebnisse folgen später.

### GEO und AI-Readiness

```powershell
seoboy geo --config .\seoboy.yaml
```

Der Bericht prüft robots.txt für Googlebot, Google-Extended, GPTBot, OAI-SearchBot,
PerplexityBot und ClaudeBot, das Vorhandensein von `llms.txt` sowie Content-/Schema-Signale
aus dem letzten abgeschlossenen Lauf. Es werden keine KI-Antworten abgefragt und kein
GEO-Score berechnet.

## Regeln

| Regel | Inhalt | Standardpriorität |
| --- | --- | --- |
| `HTTP_UNAVAILABLE` | 4xx/5xx, Timeouts und 429 mit Abrufstatus; bestätigte Blocker auf wichtigen indexierbaren Seiten | P1 bei Blocker, sonst P2/P3 |
| `HTTP_REDIRECT` | Schleifen, Hop-Grenzen und Ketten mit mehr als zwei Weiterleitungen | P1 bei bestätigter Schleife auf wichtiger Seite, sonst P2/P3 |
| `INDEX_ROBOTS_BLOCKED` | Googlebot-Sperre für eine Seite, die indexierbar sein soll | P1 bei wichtiger Seite, sonst P2/P3 |
| `INDEX_NOINDEX` | wirksames `noindex` auf einer indexierbaren Seite | P1 bei wichtiger Seite, sonst P2/P3 |
| `CANONICAL_TARGET` | widersprüchliche, defekte, externe oder auf andere Seiten zeigende Canonicals | P2/P3 |
| `SITEMAP_TARGET` | Sitemap-Eintrag mit Redirect, Fehlerstatus oder `noindex` | P2/P3 |
| `LINK_BROKEN` | interner Link auf ein geprüftes 404- oder 410-Ziel | P2/P3 |
| `LINK_ORPHAN_CANDIDATE` | Sitemap-/GSC-/Seed-Seite ohne beobachteten eingehenden Link | P3 |
| `LINK_DEPTH` | wichtiges Ziel oberhalb der konfigurierten Klicktiefe | P4 |
| `META_TITLE` | fehlender oder doppelter Titel | P3 auf wichtigen, sonst P4 |
| `META_DESCRIPTION` | fehlende oder doppelte Beschreibung | P4 |
| `GSC_NEAR_TOP` | 100+ Impressionen und Position 5 bis 20 | P3 |
| `GSC_DECLINE` | Klickrückgang von mindestens 10 und 25 % bei vorher 20+ Klicks | P3 |
| `GSC_CTR_REVIEW` | CTR-Rückgang ab 2 Prozentpunkten bei vergleichbarer Position | P3 |
| `GSC_MULTI_URL` | zwei oder mehr belegte URLs für dieselbe Suchanfrage | P3 |

Ergebnisse sind `pass`, `finding`, `not_checked` oder `not_applicable`. Für
`not_checked` und `not_applicable` wird immer ein Grundcode gespeichert, etwa
`url_limit_reached`, `robots_disallowed`, `fetch_timeout`, `missing_gsc_data` oder
`incomplete_link_graph`. Ausnahmen werden im Prüfergebnis gespeichert, unterdrücken aber
nur die Maßnahme.

## Berichte

Ein Lauf schreibt in `reports/<datum>_<projekt-id>_<lauf-id>/`:

| Datei | Inhalt |
| --- | --- |
| `00_EXECUTIVE_SUMMARY.md` | Status, Abdeckung, Datenquellen, wichtigste Maßnahmen |
| `01_ACTION_PLAN_PRIORITIZED.md` | priorisierte Maßnahmen mit Evidenz, Beispielen, Aufwand und Prüfschritt |
| `02_TECHNICAL_SEO_AUDIT.md` | Abdeckung je Regel, Grundcodes, Befunde, GSC-Zusammenfassung |
| `03_PAGE_ANALYSIS.md` | Unterseitenanalyse mit Titel-/Beschreibungslänge, H1, Wörtern, Alt-Texten und Schema |
| `raw_data/all_urls.csv` | URL-Inventar mit Herkunft, Status, Profil, HTTP-Status |
| `raw_data/pages.csv` | Seitenmetriken je Unterseite |
| `raw_data/rule_results.csv` | vollständige Prüfergebnisse inklusive Evidenzverweisen |
| `raw_data/broken_links.csv` | defekte Linkziele mit Quellseiten |
| `raw_data/gsc_metrics.csv` | alle gespeicherten GSC-Zeilen mit Granularität und Zuordnung |
| `manifest.json` | Lauf-, Tool- und Regelversionen, Status, Abdeckung, Datenquellen |

CSV-Dateien sind UTF-8 mit BOM. Textwerte, die wie eine Tabellenformel beginnen, werden
im Export mit einem führenden Apostroph geschützt; der Beobachtungswert in SQLite bleibt
unverändert.

`diff` schreibt in einen eigenen Ordner `05_AUDIT_DIFF.md` und
`raw_data/audit_diff.csv`. Verglichen werden stabile Befund-IDs; Regelversion,
Geltungsbereich und Anwendbarkeit werden geprüft. Ein fehlender Linkdatensatz gilt nur
dann als behoben, wenn die Quellseite im Ziellauf vollständig ausgewertet wurde.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Die Tests decken URL-Normalisierung, robots.txt, Konfiguration, Migrationen,
GSC-Aufbereiter und -Import, den vollständigen Crawl, Limits, Wiederholungen,
Redirect-Schleifen, Wiederaufnahme, Parallelität, Batch-Läufe, Unterseitenanalyse,
Wettbewerbsbenchmark, GSC-API/URL Inspection, Playwright-Vergleich (mit injiziertem
Browser), Local SEO, GEO, Einzel-URL-Prüfung, Ausnahmen, Berichte, den Lauf-Vergleich und
den Systemcheck und den Git-Updater ab. Sie verwenden lokale HTTP-Server und benötigen
kein Netzwerk; die Updater-Tests nutzen lokale Git-Repositories.

## Projektstruktur

Die Struktur ist ein domain-orientierter modularer Monolith. Fachliche Capabilities
(Crawl, Analyse, GSC, Reporting, Benchmark, Local SEO, GEO) sind getrennt; technische Adapter liegen unter
`infrastructure`, gemeinsam genutzte Primitiven unter `shared`. Die Abhängigkeitsrichtung
läuft von `application`/CLI über die Capabilities zu `shared`; Reporting und Analyse
kennen keine HTTP- oder CLI-Details. Vollständiges DDD mit Aggregaten, Repositories und
Domain Events wäre für diesen lokalen Batch-Audit unnötiger Aufwand.

```text
migrations/001_initial.sql     SQLite-Schema
AGENTS.md                       Arbeitsanweisung für KI-Agenten
.env.example                    dokumentierte lokale Umgebungsvariablen
local/                          lokale Konfigurationen und Laufdaten (ignoriert)
src/seoboy/
  cli.py                       Kommandozeile
  __main__.py                  python -m seoboy
  application/runner.py        run/resume/inspect/report/diff, Batch und Benchmark
  analysis/
    audit_data.py              geladenes Read-Model je Lauf
    rules.py                   technische Regeln und Prüfengine
    rules_gsc.py               Search-Console-Regeln
    actions.py                 Maßnahmenbildung und Priorisierung
  crawl/
    crawler.py                 Worker-Pool, Budgets, Wiederaufnahme
    http_client.py             HTTP ohne Redirect-Verfolgung
    html_extract.py            HTML-Extraktion
    rendering.py               optionaler Playwright-/Browser-Vergleich
    registry.py                URL-, Discovery- und Jobregistrierung
  gsc/
    api.py                     GSC-API und URL Inspection
    importer.py                GSC-Import und UI-Aufbereiter
  infrastructure/
    config.py                  Konfiguration und Kanonisierung
    database.py                SQLite und Migrationen
    env.py                     optionales Laden der .env
    lock.py                    exklusive Datenbanksperre
    doctor.py                  Systemcheck ohne KI-Agent
    update.py                  Git-basierter CLI-Updater
  reporting/
    run_report.py              Markdown-/CSV-Berichte
    page_analysis.py           Unterseiten- und Inhaltsanalyse
    diff_report.py             Lauf-Vergleich
  benchmark/
    sampler.py                 robots-konforme Wettbewerbsstichprobe
    report.py                  Wettbewerbsvergleich und Begriffskandidaten
  local_seo/
    audit.py                   Standort-, NAP- und Schema-Prüfung
  geo/
    audit.py                   Bot-Zugriff, llms.txt und AI-Readiness
  shared/
    agents.py                  Googlebot-/SeoBoy-Agenten
    robots.py                  robots.txt-Parser
    urls.py                    URL-Normalisierung und Pfadmuster
    util.py                    Zeit-, Hash- und CSV-Hilfen
    version.py                 Tool-, Crawler- und Regelsatzversionen
tests/                          Unit- und End-to-End-Tests
```

## Daten und Datenschutz

Die Datenbank und die Berichte bleiben lokal. HTML-Volltexte werden nicht gespeichert;
gespeichert werden Statuswerte, Metadaten, Links, Evidenz und Auszüge. Zugangsdaten und
API-Schlüssel gehören nicht in die Projektkonfiguration, in Berichte oder in Logs.
Response-Header werden ohne `Set-Cookie` gespeichert. Der Audit verändert keine Website.
Wettbewerbsseiten werden nur für die Benchmark-Metriken gelesen; ihr HTML wird nicht
gespeichert. Lokale `.env`-Dateien, Konfigurationen unter `local/`, Datenbanken und
Berichte werden nicht versioniert.

## Nächste Ausbaustufen

- Interaktiver Desktop-OAuth-Flow und sichere Token-Ablage
- Persistente Migrationen für URL Inspection, Wettbewerber, Local SEO und GEO
- Vollständige Wettbewerber-Läufe, TF-IDF-Content-Gaps, SERP- und Backlink-Adapter
- Playwright-Browser-Matrix, Screenshots und Performance-/CrUX-Messungen
- Reproduzierbare KI-Antwortstichproben für GEO
- Manueller Maßnahmenstatus mit Verlauf

Die detaillierte offene Liste steht in [todo.md](todo.md).

Die verbindlichen Anforderungen stehen in den Spezifikationen
[Architektur](01_architektur_und_techstack_md.md),
[Regeln](02_seo_geo_und_konkurrenz_engine_md.md),
[Reporting](03_reporting_und_priorisierung_md.md) und
[Datenmodell](04_datenmodell_sqlite_md.md).