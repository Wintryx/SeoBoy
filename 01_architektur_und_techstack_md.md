# SeoBoy – Architektur und Tech-Stack

**Version:** 0.1 (Entwurf)  
**Zielplattform:** Windows 10/11 mit PowerShell 7  
**Einsatz:** Lokales SEO-Tool für den Eigenbedarf

SeoBoy prüft eigene Websites, verbindet technische Befunde mit Daten aus der Google Search Console (GSC) und erstellt einen priorisierten Maßnahmenplan. Wiederholte Audits zeigen, welche Probleme neu sind, fortbestehen oder nachweislich behoben wurden. Ein Audit ist lesend und ändert keine Website.

Die [Prüfregeln](02_seo_geo_und_konkurrenz_engine_md.md) und das [Reporting](03_reporting_und_priorisierung_md.md) bauen auf dem hier beschriebenen Datenmodell auf.

## 1. Umfang und Ausbaustufen

| Stufe | Lieferumfang |
| --- | --- |
| **MVP** | Eine eigene Website pro Projekt, HTTP-Crawl, SQLite, technische Kernregeln, optionaler GSC-CSV-Import, Markdown- und CSV-Berichte, Audit-Vergleich. |
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

```powershell
seoboy init --url https://example.de/
seoboy run --config ./seoboy.yaml
seoboy run --config ./seoboy.yaml --gsc-dir ./imports/gsc
seoboy run --config ./seoboy.yaml --resume <lauf-id>
seoboy inspect https://example.de/leistungen/ --config ./seoboy.yaml
seoboy diff --config ./seoboy.yaml --base <lauf-id> --target <lauf-id>
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
- **URL-Identität.** Relative Links werden gegen die Dokumentbasis aufgelöst. Das Schema und der Host werden kleingeschrieben, Standardports und Fragmente entfernt. Pfadschreibweise, Slash am Ende und übrige Query-Parameter bleiben erhalten. Die angefragte URL, die normalisierte Identität und das endgültige Redirect-Ziel bleiben nachvollziehbar. Canonical-Angaben führen nicht zum Zusammenlegen von URLs.
- **Geltungsbereich.** Nur HTTP und HTTPS für zugelassene Hosts und Pfade abrufen. Jeder Redirect wird vor dem Folgen erneut geprüft. Externe Ziele werden als Referenz erfasst. Pro Origin prüft SeoBoy `robots.txt` für den eigenen User-Agent nach RFC 9309 und wertet Regeln für andere Bots separat aus. [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309)
- **Limits.** `max_urls` begrenzt verschiedene zum Abruf zugelassene Seiten-URLs, einschließlich gefolgter interner Weiterleitungen. `max_requests` begrenzt sämtliche HTTP-Anfragen des Laufs, einschließlich Sitemap, Robots, Redirects und Wiederholungen. Anfrage-Timeouts, Größenlimits für Antworten sowie Grenzen für Sitemap-Indizes und URL-Varianten pro Pfad halten einzelne Fälle klein. Bei `429`, `5xx` und Timeouts folgen bis zu zwei Wiederholungen mit zunehmender Wartezeit. Bei vorhandenem `Retry-After` wartet der betroffene Host bis zum angegebenen Zeitpunkt oder bis zum Ende des Laufzeitbudgets.
- **Wiederaufnahme.** Warteschlange, Ergebnisse und Zähler werden fortlaufend gespeichert. Ein abgebrochener oder am Zeitlimit pausierter Lauf kann mit derselben Konfiguration und Regelversion fortgesetzt werden. Bereits abgeschlossene Abrufe werden wiederverwendet. Das Zeitbudget gilt je Ausführung, URL- und Anfragelimits gelten für den gesamten Lauf. Ein erreichtes Gesamtlimit beendet den Lauf mit Teilabdeckung.
- **Abdeckung.** Jeder Lauf unterscheidet entdeckte, geprüfte, gesperrte, ausgeschlossene und noch offene URLs. Bei einer blockierten oder fehlgeschlagenen Seite bleiben inhaltsabhängige Regeln ungeprüft. Teilabdeckung und Abbruchgrund erscheinen im Bericht.

Beim späteren Rendering vergleicht SeoBoy das HTTP-Dokument mit dem Browser-DOM einer ausgewählten URL. Beide Beobachtungen behalten ihre Herkunft. Der Vergleich kann Änderungen durch JavaScript sichtbar machen. Googles Rendering hat eigene Grenzen. [Google zu JavaScript und Rendering](https://developers.google.com/search/docs/crawling-indexing/javascript/fix-search-javascript)

## 5. Datenmodell

| Tabelle | Inhalt und Identität |
| --- | --- |
| `runs` | Lauf-ID, Projekt-ID, Start/Ende, Status, Limits, Abbruchgrund, bereinigte Konfiguration, Regel- und Toolversion. |
| `urls` | Lauf-ID, normalisierte URL, Herkunft(en), Profil, Zustand und Grund bei Ausschluss oder fehlender Abdeckung. |
| `fetches` | Lauf-ID, URL, Abrufweg (HTTP oder Browser), Zeit, Versuch, Status, Redirect-Hops, Header und Extrakt. |
| `links` | Lauf-ID, Quell- und Ziel-URL, Linkart, optional Ankertext und Extraktionsquelle. |
| `source_imports`, `gsc_metrics` | Herkunft, Property, Zeitraum, Filter, Granularität, Importstatus und Messwerte je URL bzw. URL und Suchanfrage. |
| `rule_results` | Lauf-ID, Regel-ID und Regelversion, URL und optionales Teilobjekt, Ergebnis, Evidenz und Grund für fehlende Prüfbarkeit. |
| `actions`, `action_findings` | Maßnahmen je Lauf mit stabiler Maßnahmen-ID, Zuordnung zu Befunden und berechneter Priorität. Der manuelle Bearbeitungsstatus folgt im nächsten Ausbau. |

Beobachtungen sind pro Lauf getrennt. `diff` verwendet stabile Regel- und URL-Identitäten sowie vergleichbare Prüfergebnisse. Details zu den Vergleichsregeln stehen in [Teil 3](03_reporting_und_priorisierung_md.md).

## 6. GSC-Import und API-Adapter

Der MVP liest pro GSC-Berichtszeitraum eine normalisierte, UTF-8-kodierte CSV pro Granularität. Die Dateien verwenden Kommas als Trenner und einen Punkt als Dezimalzeichen. Eine `manifest.json` nennt Property, Suchtyp, Länder- und Gerätefilter, Start- und Enddatum je Zeitraum und die zugehörigen Dateien. Die relative Dateiangabe bezieht sich auf das Verzeichnis des Manifests. `null` bezeichnet einen unsegmentierten Länder- bzw. Gerätefilter.

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
      "pages": "2026-10_pages.csv",
      "page_queries": "2026-10_page_queries.csv"
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
- Ein gültiger GSC-Import ordnet bekannte URLs eindeutig zu. Ungültige und nicht zuordenbare Werte werden nachvollziehbar gemeldet. Ohne GSC bleiben technische Prüfungen verfügbar.
- Jeder Befund lässt sich auf einen gespeicherten Abruf oder Import zurückführen. Zwei gespeicherte Läufe sind anhand ihrer IDs vergleichbar.
