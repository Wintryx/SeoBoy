# SeoBoy – Architektur und Tech-Stack

**Version:** 0.1 (Entwurf)  
**Zielplattform:** Windows 10/11 mit PowerShell 7  
**Einsatz:** Lokales SEO-Tool für den Eigenbedarf

SeoBoy prüft eigene Websites, verbindet technische Befunde mit Daten aus der Google Search Console (GSC) und erstellt einen priorisierten Maßnahmenplan. Wiederholte Audits zeigen, welche Probleme neu sind, fortbestehen oder nachweislich behoben wurden. Ein Audit ist lesend und ändert keine Website.

Die [Prüfregeln](02_seo_geo_und_konkurrenz_engine_md.md) und das [Reporting](03_reporting_und_priorisierung_md.md) verwenden das [SQLite-Datenmodell](04_datenmodell_sqlite_md.md).

## 1. Umfang und Ausbaustufen

| Stufe | Lieferumfang |
| --- | --- |
| **MVP** | Eine eigene Website pro Projekt, HTTP-Crawl, SQLite, technische Kernregeln, optionaler GSC-CSV-Import mit kleinem Seitenexport-Aufbereiter, Markdown- und CSV-Berichte, Audit-Vergleich. |
| **Nächster Ausbau** | Direkte GSC-Anbindung, URL Inspection für ausgewählte Seiten, gezieltes Playwright-Rendering, Performance-Stichproben, erweiterte Link- und Content-Analysen, Maßnahmenstatus. |
| **Wettbewerb und Local SEO** | Vergleich ausgewählter Seitentypen, SERP-Daten über einen optionalen Anbieter, getrennte Local-SEO-Auswertungen bei Bedarf. |
| **Experimentelles GEO** | Bot-Regeln, beobachtbare Inhaltsmerkmale und wiederholbare Stichproben aus KI-Suchsystemen. |

Der MVP funktioniert ohne Konto, API-Schlüssel oder Browser. Suchvolumen, Backlinks und Rankings von Wettbewerbern setzen jeweils eine passende externe Datenquelle voraus. SERP-Daten stammen aus manuell bereitgestellten Dateien oder einem vorgesehenen API-Adapter.

## 2. Tech-Stack und Datenfluss

Für v0.1 ist **Python** mit einer schlanken CLI, HTTP-Client, HTML-Parser, YAML-Konfiguration und SQLite vorgesehen. Eine SQLite-Datei pro Projekt speichert dessen Läufe. Versionierte Migrationen verwalten das Schema. Die Windows-Installation nutzt zunächst eine virtuelle Umgebung. Playwright kommt als optionales Modul mit separat installiertem Browser hinzu. [Playwright-Browser-Installation](https://playwright.dev/docs/browsers)

1. **Crawl** lädt Sitemaps und Seiten, verfolgt zugelassene URLs und schreibt die Ergebnisse fortlaufend in SQLite.
2. **Extraktion** speichert HTTP-Status, Weiterleitungen, relevante Header, Metadaten und interne Links. Jeder Befund verweist auf die beobachtete Quelle.
3. **Anreicherung** übernimmt GSC-Dateien und später API-Daten. Jeder Datensatz trägt Quelle, Zeitraum und Erfassungsstatus.
4. **Regeln** werten die gespeicherten Beobachtungen aus. Die Auswertung verwendet feste Regel-IDs und eine versionierte Regelmenge.
5. **Reporting** gruppiert Befunde, priorisiert Maßnahmen und exportiert die Ergebnisse eines gespeicherten Laufs.

HTML-Volltexte werden standardmäßig nicht gespeichert. Für Befunde genügen relevante Auszüge, Headerwerte oder Referenzen auf verarbeitete Daten. Webseiteninhalte gelten bei späteren KI-Auswertungen als Daten. API-Schlüssel und Anmeldedaten bleiben außerhalb von Projektkonfiguration, Berichten und Logs.

## 3. CLI und Projektkonfiguration

Der aktuelle MVP unterstützt `init`, `migrate`, `run` inklusive `--resume`, `inspect`, `diff`, `report` und `gsc-prepare`. Details und Beispiele stehen in der [README](README.md).

```powershell
seoboy init --url https://example.de/
seoboy migrate --config ./seoboy.yaml
seoboy run --config ./seoboy.yaml
seoboy run --config ./seoboy.yaml --gsc-dir ./imports/gsc
seoboy run --config ./seoboy.yaml --resume <lauf-id>
seoboy inspect https://example.de/leistungen/ --config ./seoboy.yaml
seoboy diff --config ./seoboy.yaml --base <lauf-id> --target <lauf-id>
seoboy report --config ./seoboy.yaml --run <lauf-id>
seoboy gsc-prepare --input ./exports/seiten.csv --out ./imports/gsc --property sc-domain:example.de --start 2026-10-01 --end 2026-10-28
```

`inspect` prüft eine einzelne URL und kennzeichnet Regeln, die den Linkgraphen oder weitere Seiten benötigen, als ungeprüft. CLI-Exitcodes sind `0` für erfolgreiche Ausführung, `1` für einen verwendbaren Teillauf und `2` für einen Fehler ohne verwendbares Ergebnis. Die Priorität eines Befunds beeinflusst den Exitcode der CLI nicht.

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
rule_exceptions: []
```

Relative Pfade beziehen sich auf die Konfigurationsdatei. `allowed_hosts` enthält genaue Hostnamen. Die erste passende Seitenprofilregel gewinnt. `seeds` kann konkrete URLs für den Crawl enthalten. `*` in Pfadmustern gilt innerhalb eines Segments, `**` kann mehrere Segmente erfassen. Die Startseite gilt standardmäßig als geschäftlich wichtig und soll indexierbar sein, sofern kein Profil etwas anderes bestimmt. Bei anderen URLs ohne Profil gelten Seitentyp und erwartete Indexierbarkeit als unbekannt und die Geschäftsbedeutung als normal. Ausnahmen nennen Regel-ID, URL oder Pfadmuster und Begründung. Ein optionales Ablaufdatum gilt bis einschließlich des angegebenen Kalendertags.

## 4. Crawl-Vertrag

- **Entdeckung.** Die Warteschlange startet mit der Startseite und konkret benannten wichtigen URLs. Interne Links, rekursive XML-Sitemap-Indizes und optional GSC-URLs ergänzen den Bestand. SeoBoy speichert alle bekannten Herkunftsarten je URL. Die Warteschlange priorisiert zuerst Startseite und manuelle Start-URLs, dann verlinkte Seiten nach bekannter Klicktiefe. Unverlinkte Sitemap- und GSC-URLs folgen. Bei gleicher Priorität entscheidet die normalisierte URL. Eine URL aus der Sitemap erhält ihre Klicktiefe erst aus dem von der Startseite erreichbaren Linkgraphen.
- **URL-Identität.** Relative Links werden gegen die Dokumentbasis aufgelöst. Schema und Host werden kleingeschrieben, Standardports, Fragmente und konfigurierte Tracking-Parameter entfernt. Pfadschreibweise, Slash am Ende und übrige Query-Parameter bleiben erhalten. SeoBoy speichert die entdeckte Schreibweise getrennt von der normalisierten Abruf-URL. Canonical-Angaben führen nicht zum Zusammenlegen von URLs.
- **Reihenfolge.** Nach der Normalisierung prüft SeoBoy Schema und Host, Pfadausschlüsse und anschließend `robots.txt` für die tatsächliche Abruf-URL. Erst nach bestandenen Filtern und der Prüfung der URL-Varianten pro Pfad belegt eine Seiten-URL einen Platz im Limit. Jeder Redirect durchläuft die Prüfung erneut. Externe Ziele werden als Referenz erfasst. Robots- und Sitemap-Abrufe haben eigene Warteschlangeneinträge. Die Abfrage von `robots.txt` selbst braucht keine vorherige Robots-Erlaubnis. [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309)
- **Limits.** `max_urls` zählt jede normalisierte URL einmal, sobald sie als Seite zum Abruf zugelassen wurde. Das gilt für interne Redirect-Ziele und für URLs, die sich erst beim Abruf als Nicht-HTML herausstellen. Hilfsabrufe für Robots und Sitemaps belegen keinen Seitenplatz. `max_requests` zählt jede reservierte HTTP-Anfrage einschließlich Hilfsabrufen, Redirects und Wiederholungen. Bilder, Skripte und Stylesheets werden im MVP nicht als Ressourcen nachgeladen. Bei `429`, `5xx` und Timeouts folgen bis zu zwei Wiederholungen. `Retry-After` und der nächste zulässige Abrufzeitpunkt bleiben über Pausen erhalten.
- **Wiederaufnahme.** SeoBoy speichert die wirksame Konfiguration, Versionen und Eingaben beim Start. Bei inkompatibler Konfiguration oder Regelversion bricht `--resume` mit Exitcode `2` ab. Die Fehlermeldung nennt die Lauf-ID und den Grund. Der gespeicherte Lauf bleibt unverändert. Ein Audit mit den geänderten Einstellungen wird durch einen eigenen Aufruf ohne `--resume` gestartet. Ein vor dem HTTP-Abruf reservierter Versuch bleibt auch bei einem Prozessabbruch im Budget. Die Wiederaufnahme kennzeichnet Versuche ohne gespeichertes Ergebnis als unterbrochen und plant sie innerhalb der Limits erneut ein. Erfolgreich gespeicherte Arbeit wird weiterverwendet. Das Zeitbudget gilt je Ausführung. Die URL- und Anfragelimits gelten für den gesamten Lauf. Nach Ausschöpfung eines Gesamtlimits wird der Lauf als Teillauf abgeschlossen. Die einzelnen Transaktionen sind im [Datenmodell](04_datenmodell_sqlite_md.md) beschrieben.
- **Abdeckung.** Jeder Lauf unterscheidet entdeckte, geprüfte, gesperrte, ausgeschlossene und noch offene URLs. Bei einer blockierten oder fehlgeschlagenen Seite bleiben inhaltsabhängige Regeln ungeprüft. Teilabdeckung und Abbruchgrund erscheinen im Bericht.

Beim späteren Rendering vergleicht SeoBoy das HTTP-Dokument mit dem Browser-DOM einer ausgewählten URL. Beide Beobachtungen behalten ihre Herkunft. Der Vergleich kann Änderungen durch JavaScript sichtbar machen. Googles Rendering hat eigene Grenzen. [Google zu JavaScript und Rendering](https://developers.google.com/search/docs/crawling-indexing/javascript/fix-search-javascript)

## 5. Datenmodell

Das [SQLite-Datenmodell](04_datenmodell_sqlite_md.md) definiert Schlüssel, Status, Transaktionsgrenzen und die Erweiterungspunkte. Die [erste Migration](migrations/001_initial.sql) legt das Schema an. Dauerhafte URL-Identitäten stehen getrennt von Daten eines einzelnen Laufs. `diff` verwendet stabile Befundschlüssel und vergleichbare Prüfergebnisse gemäß [Teil 3](03_reporting_und_priorisierung_md.md).

## 6. GSC-Import und API-Adapter

Der MVP liest pro GSC-Berichtszeitraum eine normalisierte, UTF-8-kodierte CSV pro Granularität. Die Dateien verwenden Kommas als Trenner und einen Punkt als Dezimalzeichen. Eine `manifest.json` nennt Property, Suchtyp, Länder- und Gerätefilter, Start- und Enddatum je Zeitraum und die zugehörigen Dateien. Die relative Dateiangabe bezieht sich auf das Verzeichnis des Manifests. `null` bezeichnet einen unsegmentierten Länder- bzw. Gerätefilter.

Ein vorgelagerter Aufbereiter übernimmt den Seitenexport aus dem GSC-Leistungsbericht. Er verwendet ein Spaltenmapping und ein angegebenes Zahlen- und Trennzeichenformat, meldet fehlende oder mehrdeutige Felder und übernimmt bestätigte Property, Filter und Zeitraum in das Manifest. Ein deutscher Seitenexport dient als erster Abnahmefall. Der Aufbereiter erzeugt keine künstlichen URL-Suchanfrage-Paare. Das optionale Feld `source_format` je Zeitraum trägt beim Aufbereiter den Wert `gsc_ui_csv`. Der Import kennzeichnet diese Quelle als potenziell abgeschnitten und hält fest, dass fehlende Anzeigewerte beim Export als Nullen ausgegeben werden können. Eine Position `0` aus dieser Quelle wird als unbekannt übernommen. Fehlende Zeilen bleiben unbekannt. [Google zum Export von Search-Console-Berichten](https://support.google.com/webmasters/answer/12919797)

| Datei je Zeitraum | Pflichtspalten |
| --- | --- |
| Seitenbericht | `page,clicks,impressions,position` |
| Seiten- und Suchanfragenbericht (optional) | `page,query,clicks,impressions,position` |

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
      "pages": "2026-10_pages.csv"
    },
    {
      "start": "2026-09-03",
      "end": "2026-09-30",
      "pages": "2026-09_pages.csv"
    }
  ]
}
```

Die Daten gelten je Zeitraum einschließlich Start- und Enddatum. Klicks und Impressionen sind nichtnegative ganze Zahlen. Eine fehlende Position bleibt leer. Die Seitenzeilen bilden eine Granularität für sich. Der Seiten- und Suchanfragenbericht ergänzt sie, falls die Quelle eine gemeinsame Dimension liefert. Für einen ersten Lauf reicht eine normalisierte Datei mit Seitenwerten. Der Pfad zur zweiten Granularität ist optional. Separate Seiten- und Keyword-Exporte lassen sich nicht zu URL-Keyword-Paaren zusammensetzen. Je Datei muss der Dimensionsschlüssel eindeutig sein. Ungültige Zeilen machen den betreffenden Import unverwendbar und werden mit Zeilennummer und Grund gemeldet. Die URL-Normalisierung dient zur Zuordnung. Mehrdeutige oder nicht zuordenbare Zeilen werden samt Grund ausgewiesen. Datenlücken bleiben als solche erhalten.

Die spätere GSC-API-Anbindung nutzt Desktop-OAuth mit Lesezugriff auf die konfigurierte Property. Jeder Adapter liefert Daten, Quellenangaben und einen Status wie `ok`, `partial`, `unavailable` oder `disabled`. Optionale kostenpflichtige Adapter laufen nur bei expliziter Aktivierung und mit einem Limit pro Lauf. [Google Desktop-OAuth](https://developers.google.com/identity/protocols/oauth2/native-app) · [Search Analytics API](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)

## 7. Abnahme des MVP

- Ein Testauftritt mit Sitemap, internen Links und Redirects lässt sich ohne Zugangsdaten auditieren. Ausgeschlossene Hosts und Pfade werden nicht abgerufen.
- Ein abgebrochener Lauf setzt offene Arbeit fort und bleibt innerhalb der konfigurierten URL- und Anfragelimits. Der Bericht nennt fehlende Abdeckung und den Grund.
- `--resume` mit einer inkompatiblen Konfiguration beendet den Aufruf mit Exitcode `2`. Laufliste, Warteschlange und Anfragebudget bleiben unverändert.
- Ein deutscher GSC-Seitenexport lässt sich in das interne Format überführen und bekannten URLs zuordnen. Ungültige und nicht zuordenbare Werte werden nachvollziehbar gemeldet. Ohne GSC bleiben technische Prüfungen verfügbar.
- Jeder Befund lässt sich auf einen gespeicherten Abruf oder Import zurückführen. Zwei gespeicherte Läufe sind anhand ihrer IDs vergleichbar.
