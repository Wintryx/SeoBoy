# AGENTS.md – Arbeitsanweisung für KI-Agenten

Diese Datei gilt für alle Agenten, die in diesem Repository arbeiten. Sie ergänzt die
Spezifikationen, ersetzt sie aber nicht.

## Zweck und Status

SeoBoy ist ein lokales SEO-Audit für eigene Websites. Der aktuelle Stand ist der MVP
0.3.0: paralleler HTTP-Crawl, robots.txt, Sitemaps, URL-Normalisierung, technische Regeln,
GSC-CSV-Import, Maßnahmenpriorisierung, Markdown-/CSV-Berichte, Audit-Diff und ein
Batch-Modus für mehrere Projekte.

## Nicht verhandelbare Regeln

1. **Audits sind lesend.** Gegen fremde oder eigene Websites nur GET/HEAD senden. Keine
   Formulare, POST-/PUT-/DELETE-Anfragen, Logins, Bestellungen oder Änderungen.
2. **robots.txt und Höflichkeit respektieren.** Reale Läufe nur mit konservativen Limits,
   Mindestabstand pro Host und ohne Umgehung von Sperren oder Bot-Schutz.
3. **Keine Secrets committen.** Keine Zugangsdaten, API-Schlüssel, Cookies, GSC-Rohdaten
   oder Kunden-URLs in versionierte Dateien. `.env`, `local/`, `data/`, `reports/` und
   Datenbanken sind lokal und bleiben unversioniert.
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
(Crawl, Analyse, GSC, Reporting) sind getrennt; technische Adapter liegen unter
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
| `src/seoboy/crawl/html_extract.py` | Titel, Beschreibung, Robots-Signale, Canonicals, Links |
| `src/seoboy/shared/urls.py` | URL-Normalisierung und Pfadmuster |
| `src/seoboy/gsc/importer.py` | GSC-Manifest, CSV-Import, UI-Aufbereiter |
| `src/seoboy/analysis/audit_data.py` | Geladene Laufdaten für Regeln und Berichte |
| `src/seoboy/analysis/rules.py` | Technische Regeln und Prüfengine |
| `src/seoboy/analysis/rules_gsc.py` | Search-Console-Regeln |
| `src/seoboy/analysis/actions.py` | Maßnahmenbildung und Priorisierung |
| `src/seoboy/reporting/run_report.py` | Markdown-/CSV-Berichte und Manifest |
| `src/seoboy/reporting/diff_report.py` | Vergleich zweier Läufe |
| `src/seoboy/application/runner.py` | run/resume/inspect/report/diff und Batch |
| `src/seoboy/infrastructure/env.py` | Optionales Laden von `.env` |
| `migrations/001_initial.sql` | SQLite-Schema |

Die verbindlichen Anforderungen stehen in:
- `01_architektur_und_techstack_md.md`
- `02_seo_geo_und_konkurrenz_engine_md.md`
- `03_reporting_und_priorisierung_md.md`
- `04_datenmodell_sqlite_md.md`
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
Parallelität, Batch-Läufe, Einzel-URL-Prüfung, Ausnahmen, Berichte und Diff ab. Sie
nutzt einen lokalen HTTP-Server und benötigt kein Internet.

## Lokale .env

SeoBoy lädt optional `.env` aus dem Arbeitsverzeichnis oder Projektwurzel. Bereits
gesetzte Umgebungsvariablen werden nicht überschrieben.

| Variable | Bedeutung |
| --- | --- |
| `SEOBOY_CONFIG` | Standardpfad für `--config` |
| `SEOBOY_GSC_DIR` | Standard für `seoboy run --gsc-dir`; bei `--resume` ignoriert |
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
5. Befunde nur als Empfehlung formulieren; keine Website-Änderung durchführen.

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
4. `compileall` und die komplette Testsuite ausführen.
5. Bei Benutzer-sichtbaren Änderungen README/AGENTS.md aktualisieren.
6. Nur notwendige Dateien stagen; lokale Daten und `.env` ausschließen.
7. Commit mit klarer deutscher oder englischer Zusammenfassung.

## Entscheidungsregel

Bei offenen Entscheidungsfragen gilt: nach Analyse der Spezifikation, der Datenlage und
der Risiken eine **vorläufige Empfehlung** umsetzen und die Annahme im Commit oder in der
Antwort dokumentieren. Erst bei irreversiblen, sicherheitskritischen oder rechtlich
unklaren Fragen eine Rückfrage stellen. Bestehende Nutzerdaten und fremde Websites
werden dabei nie riskiert.

## Code-Stil

- Python 3.11+, Standardbibliothek plus PyYAML; keine neuen Laufzeitabhängigkeiten ohne
  zwingenden Grund.
- Deutsche Benutzertexte und Berichte, englische Bezeichner im Code.
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
- Der Batch nutzt Threads. Bei sehr großen, CPU-lastigen Batches wäre ein Prozess-Pool
  die nächste Ausbaustufe.
- Das Analyse-Read-Model liest SQLite direkt. Bei mehreren Bounded Contexts sollte es
  in Repository und Read-Model getrennt werden.
- Der GSC-Importer nutzt die Crawl-Registry. Eine spätere API-Anbindung sollte über einen
  eigenen Adapter mit klarer Abhängigkeitsrichtung laufen.
- Keine GSC-API, kein Playwright-Rendering, keine Wettbewerber-/Local-SEO-/GEO-Module.
- Kein globaler SEO-Score; Priorisierung erfolgt über P1–P4 und Evidenz.