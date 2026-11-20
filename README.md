# SeoBoy

[![tests](https://github.com/Wintryx/SeoBoy/actions/workflows/tests.yml/badge.svg)](https://github.com/Wintryx/SeoBoy/actions/workflows/tests.yml)

SeoBoy ist ein lokales SEO-Audit für eigene Websites. Es crawlt eine Site, speichert
jede Beobachtung in SQLite, wertet technische Regeln aus und verbindet die Befunde mit
Daten aus der Google Search Console. Das Ergebnis ist ein priorisierter Maßnahmenplan
mit nachvollziehbarer Evidenz sowie ein Vergleich zweier Läufe.

Aktueller Stand: 0.15.0 mit einer Website pro Projekt, parallelem HTTP-Crawl,
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
- TF-IDF-Content-Gaps aus dem Hauptinhalt, ohne Volltextspeicherung
- GSC-Import mit Manifest, Seiten- und URL-Suchanfrage-Granularität
- GSC-Auswertung Suchanfrage × Zielseite mit Chancen und Mehr-URL-Erkennung
- GSC-Verlauf zwischen Läufen mit Klick-, Impressions-, CTR- und Positionsdelta
- GSC-API-Abruf über Refresh-Token, Service-Account oder interaktiven OAuth-Login
- Persistenter GSC-Token-Store mit restriktiven Dateirechten
- Persistente URL-Inspection-Ergebnisse, 06-Bericht und Audit-Diff
- Aufbereiter für den deutschen GSC-UI-Seitenexport (Semikolon, Dezimalkomma)
- Optionales Playwright-Rendering mit Chromium/Firefox/WebKit
- Local-SEO-Prüfung für Standorte, NAP, Profile und lokale Messevidenz
- Performance-Bericht für PageSpeed/Lighthouse und CrUX
- Maßnahmenstatus mit Verlauf
- GEO-Readiness für AI-Bots, llms.txt und vorhandene Content-/Schema-Signale
- Budgetiertes GEO-Sampling über DeepSeek mit Marken-/Zitat-Auswertung
- Priorisierte Maßnahmen (P1 bis P4), Quick Wins und Evidenz je Befund
- Markdown-Berichte, CSV-Rohdaten und Manifest je Lauf
- Vergleich zweier Läufe mit den Zuständen neu, erstmals beobachtet, fortbestehend,
  behoben, ungeprüft und nicht vergleichbar

Nicht in dieser Stufe: vollständige Wettbewerber-Crawls, SERP-/Backlink-Adapter,
lokale Suchergebnisse, KI-Antwortstichproben, Performance-/CrUX-Messungen und ein
manueller Maßnahmenstatus.

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

- **GSC-API/URL Inspection:** Refresh-Token, Service-Account oder interaktiver OAuth-Login.
- **Playwright-Rendering:** zusätzliche Installation von Playwright und Chromium.
- **CLI-Updater:** Git-Checkout mit Upstream.
- **GSC-CSV:** ein normalisierter Importordner.

`AGENTS.md` ist ausschließlich eine Arbeitsanweisung für Coding-Agenten und wird von der
SeoBoy-Laufzeit nicht gelesen. Die Bedienung erfolgt vollständig über die CLI und die
dokumentierten YAML-/JSON-Dateien.

## Secrets und öffentliches Repository

Dieses Repository ist öffentlich. API-Keys, OAuth-Tokens, Service-Account-JSONs und
lokale Zugangsdateien gehören niemals in den Arbeitsbaum oder in die Git-Historie.

Hooks einmalig installieren:

```powershell
.\scripts\install_hooks.ps1
```

Danach prüft `pre-commit` den Index und `pre-push` die vollständige Historie.
Manuell:

```powershell
.\.venv\Scripts\python.exe .\scripts\check_secrets.py --staged
.\.venv\Scripts\python.exe .\scripts\check_secrets.py --history
```

Die GitHub-Actions-Pipeline führt den History-Scan ebenfalls aus und blockiert den
Build bei einem Treffer. `.env`, `local/`, `secrets/`, `credentials*`, `*.pem` und
`*.key` sind ignoriert. Weitere Hinweise stehen in [SECURITY.md](SECURITY.md).

## GitHub-Upstream einrichten

Ein E-Mail-Konto allein reicht für den Updater nicht. Benötigt werden Repository-URL und
eine funktionierende Git-Authentifizierung (PAT, SSH-Key oder gh login).

```powershell
.\scripts\setup_github.ps1 -RepoUrl https://github.com/<account>/<repo>.git -Branch main
seoboy update --check
```

Das Skript verweigert einen unsauberen Arbeitsbaum und überschreibt keinen abweichenden
Remote. Zugangsdaten gehören weder in die URL noch in die Konfiguration.

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
Bereits gesetzte Umgebungsvariablen werden nicht überschrieben. Die Datei ist lokal und
wird nicht versioniert; dort können auch API-Keys für lokale Läufe liegen. Niemals
committen und niemals in `.env.example` eintragen.

```powershell
Copy-Item .env.example .env
notepad .env
```

| Variable | Bedeutung |
| --- | --- |
| `SEOBOY_CONFIG` | Standardpfad für `--config`, z. B. `./local/projekt/seoboy.yaml` |
| `SEOBOY_GSC_DIR` | Standard für `seoboy run --gsc-dir`; bei `--resume` ignoriert |
| `SEOBOY_GSC_CREDENTIALS` | OAuth- oder Service-Account-JSON für den automatischen Abruf |
| `SEOBOY_GSC_PROPERTY` | GSC-Property; sonst Start-URL mit abschließendem Slash |
| `SEOBOY_GSC_TOKEN_STORE` | Pfad des persistenten OAuth-Token-Stores |
| `SEOBOY_OPENSSL` | Optionaler OpenSSL-Pfad für die Service-Account-Signatur |
| `SEOBOY_PSI_API_KEY` | API-Key für PageSpeed Insights und CrUX |
| `SEOBOY_GEO_API_KEY` | DeepSeek-Key für GEO-Sampling; alternativ `DEEPSEEK_API_KEY` |
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
- Ausgegeben werden `04_COMPETITOR_BENCHMARK.md`, `raw_data/benchmark_pages.csv`,
  `raw_data/benchmark_terms.csv`, `raw_data/benchmark_content_terms.csv`,
  `raw_data/benchmark_similar_pages.csv` und `manifest.json` in einem eigenen
  Berichtsordner.
- Mit `--competitor-url` lassen sich einzelne Wettbewerbsseiten manuell auswählen;
  die Sitemap-Stichprobe wird dann für diese Website umgangen. Die Startseite wird
  zusätzlich geladen, sofern sie nicht selbst ausgewählt wurde.
- Mit `--full` werden alle Sitemap-Kandidaten bis zum expliziten `--max-pages`-Budget
  verfolgt. Das ist keine unbegrenzte Crawl-Freigabe; das Budget bleibt die Schutzgrenze.
- Verglichen werden unter anderem Indexierbarkeit, Titel-/Beschreibungslängen, H1,
  Wortzahl, strukturierte Daten, Bild-Alt-Texte und interne Links.
- Der TF-IDF-Abschnitt gewichtet Begriffe aus dem Hauptinhalt und zeigt Konzepte, die
  bei mindestens der Hälfte der Wettbewerber vorkommen, in der eigenen Stichprobe aber
  fehlen. Marken- und Navigationsbegriffe werden gefiltert.
- Der SimHash-Abschnitt markiert Seitenpaare mit sehr ähnlichen Content-Termen
  (Hamming-Distanz ≤ 3 von 64 Bit). Das ist ein Hinweis, kein Duplicate-Content-Urteil.
- Die Content-Terme sind eine großgeschriebene Substantiv-Heuristik; gespeichert werden
  nur Termhäufigkeiten, keine Volltexte.
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

### Suchanfrage × Zielseite

Enthält der Import einen Seiten-Suchanfragenbericht (`page_queries`), schreibt jeder Lauf
zusätzlich `04_GSC_QUERY_PAGES.md` und `raw_data/gsc_query_pages.csv`. Der Bericht zeigt:

- stärkste Zielseiten und Suchanfragen nach Impressionen und Klicks,
- die konkreten Paare aus Suchanfrage und Zielseite,
- Chancen auf Position 5–20 mit mindestens der konfigurierten Impressionen-Schwelle
  und einer CTR unter 5 Prozent,
- Suchanfragen, für die mehrere Zielseiten Impressionen erhalten,
- Klickveränderungen gegenüber dem gleich langen Vorzeitraum.

Ausgewertet werden nur eindeutig zugeordnete Zeilen. Nicht zuordenbare oder mehrdeutige
Zeilen bleiben im technischen Audit sichtbar. Der Bericht ist eine Nachfrage- und
Priorisierungshilfe, keine Rankinggarantie.

### Verlauf zwischen Läufen

SeoBoy vergleicht den aktuellen GSC-Zeitraum automatisch mit dem jüngsten früheren Lauf
desselben Projekts, derselben Property und derselben Filterkombination. Voraussetzung sind
zwei gleich lange, nicht überlappende Zeiträume. Der Bericht schreibt
`05_GSC_HISTORY.md` und `raw_data/gsc_history.csv` mit:

- Gesamtvergleich für Klicks, Impressionen, CTR und durchschnittliche Position,
- Veränderungen je Zielseite, Suchanfrage und Query-/Seitenpaar,
- neuen und verlorenen Paaren,
- dem Abstand zwischen den Vergleichszeiträumen.

Der Vergleich ist eine Messhilfe, keine Kausalitätsanalyse. Saisonalität, Wettbewerb und
parallel geänderte Inhalte können das Ergebnis beeinflussen.

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

Neben Refresh-Token und Service-Account gibt es einen interaktiven Browser-Login:

    seoboy gsc-auth --client-file .\client_secret.json

Die Google-Desktop-Clientdatei enthält client_id und client_secret. SeoBoy startet
einen lokalen Loopback-Server, öffnet die Zustimmungsseite und speichert den
Refresh-Token anschließend unter

    %LOCALAPPDATA%\SeoBoy\gsc-oauth.json

oder unter SEOBOY_GSC_TOKEN_STORE. Der Token-Store ist nicht verschlüsselt, wird aber
mit restriktiven Dateirechten angelegt und enthält niemals einen Access-Token. Ohne
--credentials nutzt SeoBoy diesen Store automatisch. Zugangsdaten gehören nicht ins
Repository und nicht in Berichte.

### URL Inspection für einen Lauf

Neben der Einzel-URL-Abfrage kann SeoBoy die wichtigsten HTML-URLs eines Laufs
automatisch prüfen und dauerhaft speichern:

    seoboy url-inspection --run <LAUF-ID> --limit 10

Die Auswahl bevorzugt geschäftlich wichtige, erreichbare HTML-Seiten. Die Ergebnisse
landen in der SQLite-Tabelle url_inspections und im Laufbericht:

- 06_URL_INSPECTION.md
- raw_data/url_inspections.csv

Standard sind 10 URLs, maximal 100. Eine fehlgeschlagene API-Abfrage wird als Fehlerzeile
gespeichert, nicht als erfolgreicher Indexstatus. Die Property wird aus der Start-URL
abgeleitet oder über --property gesetzt; Zugangsdaten kommen aus
SEOBOY_GSC_CREDENTIALS/--credentials.

Der Audit-Diff vergleicht gespeicherte Inspection-Ergebnisse derselben URL und ergänzt
05_AUDIT_DIFF.md um Verdict, Coverage, Indexing, Robots, Fetch und Canonicals.

### Service-Account und automatischer GSC-Lauf

Neben OAuth-Refresh-Tokens wird eine Google-Service-Account-JSON unterstützt, wie sie
unter anderem im Aw-audio-Projekt liegt. Die Datei bleibt außerhalb des Repositories.

Für die Service-Account-Signatur wird entweder das optionale Paket cryptography oder
OpenSSL benötigt:

    .\.venv\Scripts\python.exe -m pip install -e ".[gsc-service-account]"

Auf Windows wird ein vorhandenes OpenSSL aus Git automatisch gefunden; alternativ kann
der Pfad über SEOBOY_OPENSSL gesetzt werden.

Ein Lauf kann die GSC-Daten direkt holen und danach crawlen:

    seoboy run `
      --gsc-credentials C:\secrets\google-service-account.json `
      --gsc-property https://example.de/ `
      --gsc-start 2026-10-01 --gsc-end 2026-10-31

Ohne Start-/Enddatum werden die letzten 28 Tage bis gestern verwendet; --gsc-days ändert
den Zeitraum. SEOBOY_GSC_CREDENTIALS und SEOBOY_GSC_PROPERTY können die Optionen ersetzen.
--gsc-dir hat Vorrang vor dem automatischen Abruf. Bei --resume wird kein GSC-Abruf
ausgeführt.

Der Refresh-Token wird im persistenten OAuth-Token-Store abgelegt; der Access-Token
bleibt nur im Arbeitsspeicher und wird nie in Berichte oder Logs geschrieben.

### Playwright-Rendering

Rendering ist optional und benötigt Playwright plus Chromium:

```powershell
.\venv\Scripts\python.exe -m pip install -e ".[rendering]"
.\venv\Scripts\playwright.exe install chromium
seoboy render --url https://example.de/ --url https://example.de/leistungen/
seoboy render --browser firefox --url https://example.de/
seoboy render --engine chrome --url https://example.de/
```

Der Bericht vergleicht HTTP-Dokument und Browser-DOM (Titel, Beschreibung, H1, Wörter,
Links, Schema). `--engine auto` nutzt Playwright, falls installiert, sonst einen
vorhandenen Chrome/Edge-Headless-Browser. Der Chrome-Fallback liefert keinen
verlässlichen HTTP-Status; das wird im Bericht ausgewiesen.

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
    profiles:
      - https://www.google.com/maps/place/...
      - https://www.example-verzeichnis.de/profil
```

```powershell
seoboy local --locations .\local\standorte.yaml
seoboy local --locations .\local\standorte.yaml --local-results .\local\rankings.csv
```

Geprüft werden Erreichbarkeit, Indexierbarkeit, H1, Schema und die Konsistenz von Name,
Adresse und Telefon im LocalBusiness-/Organization-JSON-LD. Zusätzlich werden
konfigurierte Profil-URLs per Textabgleich auf Name, Ort und Telefon geprüft.

Lokale Suchpositionen können als CSV mit
`query,location,position,url,source,date` beigestellt werden. SeoBoy fragt keine
Suchmaschine und keine offizielle Profil-API live ab; die Werte bleiben nachvollziehbare
Messevidenz.

### Performance

PageSpeed Insights/Lighthouse und CrUX werden über einen API-Key abgefragt:

```powershell
$env:SEOBOY_PSI_API_KEY = "..."
seoboy performance --url https://example.de/ --out .\reports\performance
```

Der Bericht enthält den Lighthouse-Performance-Score, FCP, LCP, TBT, CLS, Speed Index
und TTI sowie CrUX-p75-Felddaten. Ohne API-Key endet der Befehl mit Exitcode 2. Es werden
keine Werte geschätzt.

### GEO und AI-Readiness

```powershell
seoboy geo --config .\seoboy.yaml
```

Der Bericht prüft robots.txt für Googlebot, Google-Extended, GPTBot, OAI-SearchBot,
PerplexityBot und ClaudeBot, das Vorhandensein von `llms.txt` sowie Content-/Schema-Signale
aus dem letzten abgeschlossenen Lauf.

### GEO-Sampling mit DeepSeek

`seoboy geo-sample` erzeugt echte, budgetierte KI-Antwortstichproben:

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."
seoboy geo-sample `
  --domain aw-audio.de `
  --brand "AW Audio" `
  --brand "Arne Winter" `
  --max-calls 6 `
  --budget-usd 0.50 `
  --web-search
```

Der Bericht enthält Marken-Erwähnungen, eigene und fremde URL-Zitate, Wettbewerber-
Erwähnungen, Tokens und eine konservative Kosten-Schätzung. Standardmäßig werden sechs
deutsche Prompts im Non-Thinking-Modus mit `deepseek-flash` verwendet. Eigene Prompt-Sets
lassen sich per YAML mit `--prompts` übergeben.

`--web-search` aktiviert die serverseitige DeepSeek-Websuche. Das Modell entscheidet,
ob es sucht, und liefert Quellen und Zitate; die Suche kostet zusätzlich 0,75 USD je
1.000 Suchschritte. Ohne `--web-search` wird nur Modellwissen gemessen.

Rohantworten werden nur lokal unter `reports/.../raw_data/geo_answers.jsonl` gespeichert;
`--retention-days` dokumentiert die Aufbewahrungsfrist, die Löschung erfolgt manuell.
Ein API-Key wird nie in Berichte, Logs oder Commits geschrieben.

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
| `04_GSC_QUERY_PAGES.md` | Suchanfragen, Zielseiten, Chancen und Mehr-URL-Fälle bei GSC-Daten |
| `05_GSC_HISTORY.md` | Vergleich des GSC-Zeitraums mit dem jüngsten vergleichbaren Lauf |
| `06_URL_INSPECTION.md` | Gespeicherte URL-Inspection-Ergebnisse für wichtige URLs |
| `raw_data/all_urls.csv` | URL-Inventar mit Herkunft, Status, Profil, HTTP-Status |
| `raw_data/pages.csv` | Seitenmetriken je Unterseite |
| `raw_data/rule_results.csv` | vollständige Prüfergebnisse inklusive Evidenzverweisen |
| `raw_data/broken_links.csv` | defekte Linkziele mit Quellseiten |
| `raw_data/gsc_metrics.csv` | alle gespeicherten GSC-Zeilen mit Granularität und Zuordnung |
| `raw_data/gsc_query_pages.csv` | Query-/Zielseitenzeilen inklusive Vorzeitraum und CTR |
| `raw_data/gsc_history.csv` | Seiten-/Query-/Paarvergleich zwischen zwei Läufen |
| `raw_data/url_inspections.csv` | gespeicherte Inspection-Ergebnisse je Lauf |
| `manifest.json` | Lauf-, Tool- und Regelversionen, Status, Abdeckung, Datenquellen |

CSV-Dateien sind UTF-8 mit BOM. Textwerte, die wie eine Tabellenformel beginnen, werden
im Export mit einem führenden Apostroph geschützt; der Beobachtungswert in SQLite bleibt
unverändert.

`diff` schreibt in einen eigenen Ordner `05_AUDIT_DIFF.md` und
`raw_data/audit_diff.csv`. Verglichen werden stabile Befund-IDs; Regelversion,
Geltungsbereich und Anwendbarkeit werden geprüft. Ein fehlender Linkdatensatz gilt nur
dann als behoben, wenn die Quellseite im Ziellauf vollständig ausgewertet wurde.

## Maßnahmenstatus

Der Bearbeitungsstand einer Maßnahme wird projektweit über den stabilen
`action_key` gepflegt:

```powershell
seoboy action-status --list
seoboy action-status --action-key "..." --status in_progress --note "Umsetzung läuft"
seoboy action-status --action-key "..." --history
```

Zulässig sind `open`, `in_progress`, `done` und `ignored`. Jede Änderung wird
in `action_status_history` protokolliert und im Maßnahmenplan des Laufs angezeigt.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Die Tests decken URL-Normalisierung, robots.txt, Konfiguration, Migrationen,
GSC-Aufbereiter und -Import, den vollständigen Crawl, Limits, Wiederholungen,
Redirect-Schleifen, Wiederaufnahme, Parallelität, Batch-Läufe, Unterseitenanalyse,
Wettbewerbsbenchmark, Content-Terme/TF-IDF, SimHash und manuelle Wettbewerbs-URLs,
GSC-API/URL Inspection, OAuth-Helfer, GSC-Query-/Zielseitenbericht, GSC-Verlauf,
URL-Inspection-Persistenz und -Diff, Playwright-Vergleich (mit injiziertem Browser),
Local-SEO-Profile/-Messergebnisse, Performance-Adapter, Maßnahmenstatus mit Verlauf,
GEO-Readiness und DeepSeek-Sampling, Einzel-URL-Prüfung, Ausnahmen, Berichte, den
Lauf-Vergleich, den Systemcheck und den Git-Updater ab. Sie verwenden lokale HTTP-Server und benötigen
kein Netzwerk; die Updater-Tests nutzen lokale Git-Repositories.

## Projektstruktur

Die Struktur ist ein domain-orientierter modularer Monolith. Fachliche Capabilities
(Crawl, Analyse, GSC, Reporting, Benchmark, Local SEO, GEO) sind getrennt; technische Adapter liegen unter
`infrastructure`, gemeinsam genutzte Primitiven unter `shared`. Die Abhängigkeitsrichtung
läuft von `application`/CLI über die Capabilities zu `shared`; Reporting und Analyse
kennen keine HTTP- oder CLI-Details. Vollständiges DDD mit Aggregaten, Repositories und
Domain Events wäre für diesen lokalen Batch-Audit unnötiger Aufwand.

```text
migrations/001_initial.sql     SQLite-Basisschema
migrations/002_url_inspections.sql  persistente URL-Inspection-Ergebnisse
migrations/003_action_statuses.sql  Maßnahmenstatus und Verlauf
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
    oauth.py                   interaktiver Desktop-OAuth-Flow
    importer.py                GSC-Import und UI-Aufbereiter
    inspection_store.py        URL-Inspection-Persistenz und Bericht
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
    gsc_report.py              GSC-Auswertung Suchanfrage × Zielseite
    gsc_history.py             GSC-Verlauf über mehrere Läufe
    diff_report.py             Lauf-Vergleich
  benchmark/
    sampler.py                 robots-konforme Wettbewerbsstichprobe
    report.py                  Wettbewerbsvergleich, TF-IDF und Begriffskandidaten
  local_seo/
    audit.py                   Standort-, NAP-, Profil- und Local-Result-Prüfung
  performance/
    audit.py                   PageSpeed/Lighthouse und CrUX
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
gespeichert werden Statuswerte, Metadaten, Links, Evidenz, Auszüge und aggregierte
Termhäufigkeiten des Hauptinhalts. Zugangsdaten und
API-Schlüssel gehören nicht in die Projektkonfiguration, in Berichte oder in Logs.
Response-Header werden ohne `Set-Cookie` gespeichert. Der Audit verändert keine Website.
Wettbewerbsseiten werden nur für die Benchmark-Metriken gelesen; ihr HTML wird nicht
gespeichert. Lokale `.env`-Dateien, Konfigurationen unter `local/`, Datenbanken und
Berichte werden nicht versioniert.

## Nächste Ausbaustufen

- Retry/Backoff und Quotenbegrenzung für GSC-API-Aufrufe
- Persistente Migrationen für Wettbewerber, Local SEO und GEO
- Vollständige Wettbewerber-Läufe, SERP- und Backlink-Adapter
- Playwright-CI mit gepinnten Browser-Versionen und Screenshots
- Reproduzierbare KI-Antwortstichproben für GEO

Die detaillierte offene Liste steht in [todo.md](todo.md).

Die detaillierte Erweiterungsspezifikation mit API-Verträgen, Grenzen und
Abnahmekriterien steht in [docs/erweiterungen_spezifikation.md](docs/erweiterungen_spezifikation.md).

Die verbindlichen Anforderungen stehen in den Spezifikationen
[Architektur](01_architektur_und_techstack_md.md),
[Regeln](02_seo_geo_und_konkurrenz_engine_md.md),
[Reporting](03_reporting_und_priorisierung_md.md) und
[Datenmodell](04_datenmodell_sqlite_md.md).