# AGENTS.md – Arbeitsanweisung für KI-Agenten

Diese Datei gilt für alle Agenten, die in diesem Repository arbeiten. Sie ergänzt die
Spezifikationen, ersetzt sie aber nicht.

## Zweck und Status

SeoBoy ist ein lokales SEO-Audit für eigene Websites. Der aktuelle Stand ist 0.16.1:
paralleler HTTP-Crawl, robots.txt, Sitemaps, URL-Normalisierung, technische Regeln,
Unterseiten-Inhaltsanalyse, Wettbewerbsbenchmark, GSC-CSV-Import, GSC-API/URL Inspection,
optionales Playwright-Rendering, Local-SEO-/NAP-Prüfung, GEO-Readiness,
Maßnahmenpriorisierung, Markdown-/CSV-Berichte, Audit-Diff, ein Batch-Modus für mehrere
Projekte und ein Git-basierter CLI-Updater.

## Nicht verhandelbare Regeln

1. **Audits sind lesend.** Gegen fremde oder eigene Websites nur GET/HEAD senden. Keine
   Formulare, POST-/PUT-/DELETE-Anfragen, Logins, Bestellungen oder Änderungen.
2. **robots.txt und Höflichkeit respektieren.** Reale Läufe nur mit konservativen Limits,
   Mindestabstand pro Host und ohne Umgehung von Sperren oder Bot-Schutz.
3. **Keine Secrets committen.** Keine Zugangsdaten, API-Schlüssel, Cookies, GSC-Rohdaten
   oder Kunden-URLs in versionierte Dateien. `.env`, `local/`, `data/`, `reports/` und
   Datenbanken sind lokal und bleiben unversioniert. Vor jedem Commit
   `python scripts/check_secrets.py --staged` und vor dem Push
   `python scripts/check_secrets.py --history` ausführen.
4. **Keine lokalen Daten in Tests oder Commits.** Testfixtures erzeugen ihre Daten in
   temporären Verzeichnissen. Echte Website-Daten gehören nicht ins Repository.
5. **Schema und IDs stabil halten.** Befund- und Maßnahmen-IDs dürfen keine Lauf-ID,
   keinen Zeitstempel und keine veränderliche Anzahl enthalten. Schemaänderungen nur als
   neue, nummerierte Migration mit `PRAGMA user_version`.
6. **Tests sind Pflicht.** Vor einem Commit muss die komplette Testsuite grün sein.
7. **Keine ungefragten Produktionsänderungen.** Dieses Repository steuert nur den
   lokalen Audit; es deployt oder verändert keine Website.

## Architektur

Die Struktur ist ein domain-orientierter modularer Monolith. Fachliche Capabilities
(Crawl, Analyse, GSC, Reporting, Benchmark, Local SEO, GEO) sind getrennt; technische Adapter liegen unter
`infrastructure`, gemeinsam genutzte Primitiven unter `shared`. Vollständiges DDD mit
Aggregaten, Repositories und Domain Events wäre für diesen lokalen Batch-Audit
unnötiger Aufwand.

| Modul | Verantwortung |
| --- | --- |
| `src/seoboy/cli.py` | Kommandozeile, Exitcodes, lokale `.env`-Defaults |
| `src/seoboy/infrastructure/config.py` | Konfiguration, Profile, Ausnahmen, Kanonisierung |
| `src/seoboy/crawl/crawler.py` | Worker-Pool, Budgets, Retries, Sitemaps, Resume |
| `src/seoboy/crawl/registry.py` | URL-, Discovery- und Jobregistrierung |
| `src/seoboy/crawl/http_client.py` | HTTP ohne Redirect-Verfolgung, begrenzte Reads |
| `src/seoboy/shared/robots.py` | robots.txt-Parser und Googlebot-Auswertung |
| `src/seoboy/crawl/html_extract.py` | Titel, Beschreibung, H1, Wörter, Bilder, Schema, Links, Content-Terme |
| `src/seoboy/crawl/rendering.py` | Playwright- oder Chrome/Edge-Renderer und DOM-Vergleich |
| `src/seoboy/shared/urls.py` | URL-Normalisierung und Pfadmuster |
| `src/seoboy/gsc/importer.py` | GSC-Manifest, CSV-Import, UI-Aufbereiter |
| `src/seoboy/gsc/api.py` | GSC-API, OAuth/Service-Account und URL Inspection |
| `src/seoboy/gsc/oauth.py` | interaktiver Desktop-OAuth-Flow und Token-Store |
| `src/seoboy/gsc/inspection_store.py` | URL-Inspection-Persistenz, Auswahl und Bericht |
| `src/seoboy/analysis/audit_data.py` | Geladene Laufdaten für Regeln und Berichte |
| `src/seoboy/analysis/rules.py` | Technische Regeln und Prüfengine |
| `src/seoboy/analysis/rules_gsc.py` | Search-Console-Regeln |
| `src/seoboy/analysis/actions.py` | Maßnahmenbildung und Priorisierung |
| `src/seoboy/reporting/run_report.py` | Markdown-/CSV-Berichte und Manifest |
| `src/seoboy/reporting/page_analysis.py` | Unterseiten- und Inhaltsanalyse |
| `src/seoboy/reporting/gsc_report.py` | GSC-Auswertung Suchanfrage × Zielseite |
| `src/seoboy/reporting/gsc_history.py` | GSC-Verlauf über mehrere Läufe |
| `src/seoboy/reporting/diff_report.py` | Vergleich zweier Läufe |
| `src/seoboy/benchmark/sampler.py` | robots-konforme Stichprobe und sitemapweiter Modus |
| `src/seoboy/benchmark/report.py` | Wettbewerbsvergleich, TF-IDF und Begriffskandidaten |
| `src/seoboy/local_seo/audit.py` | Standort-, NAP-, Profil- und Local-Result-Prüfung |
| `src/seoboy/performance/audit.py` | PageSpeed/Lighthouse und CrUX |
| `src/seoboy/geo/audit.py` | AI-Bots, llms.txt und GEO-Readiness |
| `src/seoboy/geo/sampling.py` | budgetiertes DeepSeek-GEO-Sampling |
| `src/seoboy/ai/review.py` | beratende KI-Review des Gesamtaudits |
| `src/seoboy/application/runner.py` | run/resume/inspect/report/diff, Batch und Benchmark |
| `src/seoboy/infrastructure/env.py` | Optionales Laden von `.env` |
| `src/seoboy/infrastructure/doctor.py` | Systemcheck für den Betrieb ohne Agent |
| `src/seoboy/infrastructure/update.py` | Git-basierter CLI-Updater mit Rollback |
| `migrations/001_initial.sql` | SQLite-Basisschema |
| `migrations/002_url_inspections.sql` | persistente URL-Inspection-Ergebnisse |
| `migrations/003_action_statuses.sql` | Maßnahmenstatus und Verlauf |

Die verbindlichen Anforderungen stehen in:
- `01_architektur_und_techstack_md.md`
- `02_seo_geo_und_konkurrenz_engine_md.md`
- `03_reporting_und_priorisierung_md.md`
- `04_datenmodell_sqlite_md.md`
- `docs/ki_review_spezifikation.md`
- `README.md`

## Entwicklungsumgebung

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e .
./.venv/Scripts/python.exe -m seoboy --version
```

Die Tests benötigen nur die Standardbibliothek und PyYAML. Im Quellbaum kann
`PYTHONPATH=./src` gesetzt und `python -m seoboy ...` verwendet werden.

## Tests

```powershell
./.venv/Scripts/python.exe -m compileall -q src tests
./.venv/Scripts/python.exe -m unittest discover -s tests -v
```

Die Suite deckt URL-Normalisierung, robots.txt, Konfiguration, Migrationen,
GSC-Aufbereiter/-Import, Crawl, Limits, Retries, Redirect-Schleifen, Resume,
Parallelität, Batch-Läufe, Unterseitenanalyse, Wettbewerbsbenchmark, Content-Terme/
TF-IDF, GSC-Query-/
Zielseitenbericht, GSC-Verlauf, GSC-API/URL Inspection, OAuth-Helfer,
URL-Inspection-Persistenz und -Diff, Playwright-Vergleich mit injiziertem Browser,
Local SEO-Profile/Local-Results, Performance-Adapter, Maßnahmenstatus,
GEO-Readiness und DeepSeek-Sampling, KI-Review-Packung/-Validierung/-Cache,
Einzel-URL-Prüfung,
Ausnahmen, Berichte, Diff, den Systemcheck und den Git-Updater ab. Sie nutzt lokale
HTTP-Server, lokale Git-Repositories und benötigt kein Internet.

## Lokale .env

SeoBoy lädt optional `.env` aus dem Arbeitsverzeichnis oder Projektwurzel. Bereits
gesetzte Umgebungsvariablen werden nicht überschrieben.

| Variable | Bedeutung |
| --- | --- |
| `SEOBOY_CONFIG` | Standardpfad für `--config` |
| `SEOBOY_GSC_DIR` | Standard für `seoboy run --gsc-dir`; bei `--resume` ignoriert |
| `SEOBOY_GSC_CREDENTIALS` | OAuth- oder Service-Account-JSON für den automatischen GSC-Abruf |
| `SEOBOY_GSC_PROPERTY` | GSC-Property; sonst Start-URL mit abschließendem Slash |
| `SEOBOY_GSC_ACCESS_TOKEN` | Kurzlebiger Access-Token für Tests/Notfälle; nicht speichern |
| `SEOBOY_GSC_TOKEN_STORE` | Pfad des persistenten OAuth-Token-Stores |
| `SEOBOY_OPENSSL` | Optionaler OpenSSL-Pfad für die Service-Account-Signatur |
| `SEOBOY_PSI_API_KEY` | API-Key für PageSpeed Insights und CrUX |
| `SEOBOY_GEO_API_KEY` | DeepSeek-Key für GEO-Sampling; alternativ `DEEPSEEK_API_KEY` |
| `SEOBOY_ENV_FILE` | Alternatives Env-File; muss vor dem Prozessstart gesetzt sein |

`.env.example` ist die dokumentierte Vorlage. `.env` selbst ist in `.gitignore` und darf
niemals committed werden. Explizite CLI-Optionen haben Vorrang.

## Reale Website prüfen

Nur nach ausdrücklicher Freigabe und ausschließlich lesend. Empfohlen:

1. Eigene lokale Konfiguration unter `local/<projekt>/seoboy.yaml` anlegen.
2. `max_urls`, `max_requests`, `max_runtime_seconds`, `max_workers` und
   `min_request_interval_ms` konservativ setzen (z. B. 100 URLs, 8 Worker, 1.500 ms).
3. Medien- und Admin-Pfade über `exclude_paths` ausschließen, wenn sie das Budget
   verbrauchen würden.
4. Läufe nicht wiederholen, wenn der Zweck erreicht ist. Keine Lasttests.
5. Wettbewerbsvergleiche nur als begrenzte, robots-konforme Stichprobe ausführen.
6. Befunde nur als Empfehlung formulieren; keine Website-Änderung durchführen.

## Datenmodell-Invarianten

- Laufübergreifende URL-Identität: normalisierte URL im Projekt.
- Befund: `(rule_id, subject_key)`; `subject_key` ist deterministisches JSON-Array.
- Maßnahme: `action_key` aus Regel, Fix-Art und fachlichem Schlüssel.
- Evidenz verweist auf Abruf, Beobachtung, Import oder Konfiguration.
- `not_checked`/`not_applicable` brauchen einen nicht leeren `reason_code`.
- Befunde brauchen Schweregrad, Beleglage und Evidenz.
- Ein Lauf endet als `completed`, `partial`, `paused` oder `failed`; `ended_at` ist nur
  bei den abgeschlossenen Zuständen gesetzt.
- Regelergebnisse, Evidenz und Maßnahmen werden mit der endgültigen Laufentscheidung
  in einer Transaktion gespeichert.

## Arbeitsablauf

1. Relevante Spezifikation und vorhandene Implementierung lesen.
2. Änderung klein und nachvollziehbar halten; bestehende Verträge nicht still brechen.
3. Tests ergänzen, die das neue Verhalten und den Fehlerfall abdecken.
4. Secret-Scan, `compileall` und die komplette Testsuite ausführen.
5. Bei Benutzer-sichtbaren Änderungen README/AGENTS.md aktualisieren.
6. Nur notwendige Dateien stagen; lokale Daten und `.env` ausschließen.
7. Änderungen in kleinen, logischen Schritten committen; Commit-Nachrichten auf Englisch.
8. Updates nur über `seoboy update` aus einem sauberen Git-Checkout mit Upstream;
   keine manuellen Fast-Forwards oder Installationen in laufende Audits hinein.
   Auf Windows die Neuinstallation bevorzugt mit `python -m seoboy update --apply`
   starten, damit der laufende `seoboy.exe`-Launcher nicht blockiert.

## Entscheidungsregel

Bei offenen Entscheidungsfragen gilt: nach Analyse der Spezifikation, der Datenlage und
der Risiken eine **vorläufige Empfehlung** umsetzen und die Annahme im Commit oder in der
Antwort dokumentieren. Erst bei irreversiblen, sicherheitskritischen oder rechtlich
unklaren Fragen eine Rückfrage stellen. Bestehende Nutzerdaten und fremde Websites
werden dabei nie riskiert.

## Code-Stil

- Python 3.11+, Standardbibliothek plus PyYAML; keine neuen Laufzeitabhängigkeiten ohne
  zwingenden Grund.
- Code-Kommentare und Docstrings auf Englisch; Benutzertexte, CLI-Hilfe und Berichte
  auf Deutsch. Bezeichner im Code sind englisch.
- Dataclasses, Typannotationen, kurze Funktionen, keine stillen Fallbacks bei
  ungültigen Daten.
- Zeitstempel in SQLite UTC/ISO-8601; Anzeige in Europe/Berlin.
- CSV-Exporte UTF-8 mit BOM und Formelschutz; SQLite behält den Originalwert.
- Keine Secrets in Logs, Berichten oder Fehlermeldungen.

## Neue Regel hinzufügen

1. Regel-ID und Version in `RULE_VERSIONS` ergänzen.
2. Ergebnis mit `subject_key`, `subject_kind`, `subcheck`, `scope_key` und Evidenz bauen.
3. Für `not_checked`/`not_applicable` einen stabilen Grundcode setzen.
4. Action-Gruppierung und Priorität in `actions.py` ergänzen.
5. Tests für `pass`, `finding`, `not_checked` und `not_applicable` schreiben.
6. README-Regeltabelle und ggf. `02_...` aktualisieren.

## Schema-Migration

Neue Migration als `migrations/00N_name.sql` anlegen, in `MIGRATIONS` registrieren und
`PRAGMA user_version = N` innerhalb der Transaktion setzen. Bestehende Läufe und
Ergebnisse nicht umschreiben. Migration auf leerer und vorhandener Datenbank testen.

## Bekannte MVP-Grenzen

- robots.txt- und Sitemap-Abrufe folgen keinen Weiterleitungen.
- Batch-Läufe benötigen getrennte SQLite-Datenbanken; derselbe DB-Pfad wird abgelehnt.
- Dieselbe Website (Host und Port) wird im Batch nicht parallel geprüft.
- Batch importiert keine GSC-Daten; GSC bleibt der Einzellauf mit `--gsc-dir`.
- Der Benchmark bleibt budgetiert; `--full` verfolgt Sitemap-Kandidaten bis
  `--max-pages`, ist aber kein unbegrenzter Crawl.
- Wettbewerbs-HTML wird nicht gespeichert; gespeichert werden Metriken, URLs und
  aggregierte Content-Terme.
- Content-Terme sind eine großgeschriebene Substantiv-Heuristik, keine linguistische
  Lemmatisierung.
- Der Benchmark benötigt einen abgeschlossenen eigenen Lauf mit Inhaltsmetriken.
- Der Batch nutzt Threads. Bei sehr großen, CPU-lastigen Batches wäre ein Prozess-Pool
  die nächste Ausbaustufe.
- Das Analyse-Read-Model liest SQLite direkt. Bei mehreren Bounded Contexts sollte es
  in Repository und Read-Model getrennt werden.
- Der GSC-Importer nutzt die Crawl-Registry. Die API-Anbindung liegt getrennt in
  `gsc/api.py`.
- GSC-API und URL Inspection akzeptieren Refresh-Token, Service-Account oder den
  interaktiven OAuth-Login. Der Token-Store ist dateirechtlich geschützt, aber nicht
  verschlüsselt; er enthält nur den Refresh-Token, keinen Access-Token.
- URL Inspection ist auf API-Kontingente begrenzt; der Batch-Modus prüft standardmäßig
  höchstens 10 und maximal 100 wichtige URLs.
- Playwright ist optional; ohne Playwright kann `render --engine chrome` einen
  vorhandenen Chrome/Edge ohne HTTP-Status nutzen. Node.js ist für diesen
  Chrome-Headless-Fallback nicht erforderlich.
- Local SEO prüft konfigurierte Profil-URLs per Textabgleich und importiert lokale
  Messergebnisse aus CSV; offizielle Profil-APIs und Suchmaschinenabfragen sind nicht
  angebunden.
- PageSpeed/CrUX benötigt einen API-Key; ohne Key bleibt der Befehl klar deaktiviert.
- GEO-Sampling nutzt standardmäßig DeepSeek-V4.1-Flash-1017 mit Thinking enabled
  und reasoning_effort=max; Antworten sind Momentaufnahmen und keine Rankings.
- Der GEO-Adapter und die KI-Review dürfen nur api.deepseek.com per HTTPS kontaktieren,
  keine Redirects folgen, keine Shell/Browser/Website/DB verändern und nur saubere
  Report-Ordner schreiben. Details stehen in SECURITY.md.
- Die KI-Review ist advisory: Sie ändert keine Befunde, Maßnahmen oder Prioritäten.
- KI-Review nutzt standardmäßig einen Aufruf, maximal 40 Befunde/25 Maßnahmen,
  ein Budget von 0,25 USD und einen SHA-256-Cache.
- Vollständige Wettbewerber-Audits und SERP-/Backlink-Adapter bleiben externe
  Ausbaustufen.
- Der CLI-Updater setzt einen Git-Checkout mit Upstream voraus; Wheel-/PyPI-Installationen
  werden mit pip aktualisiert.
- Die Laufzeit benötigt keinen KI-Agenten und kein LLM; `AGENTS.md` ist nur eine
  Repository-Anweisung für Coding-Agenten.
- `seoboy doctor` prüft die lokale Installation ohne Netzwerkzugriff.
- Kein globaler SEO-Score; Priorisierung erfolgt über P1–P4 und Evidenz.