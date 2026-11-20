# SeoBoy – Erweiterungsspezifikation

Stand: 20.11.2026  
Zielversion: 0.15.2

## 1. Zweck

Diese Spezifikation beschreibt die Grenzen aus der bisherigen Dokumentation und wie sie
technisch, organisatorisch und rechtlich sauber erweitert werden. Sie trennt bewusst:

- lokal umsetzbare Funktionen,
- Funktionen mit externem API-Vertrag,
- Funktionen, die ohne Zugangsdaten oder Lizenz nicht belastbar messbar sind.

Grundsätze:

1. Keine erfundenen Messwerte.
2. Netzwerkzugriffe sind lesend (GET/HEAD/API-Read).
3. robots.txt, Rate-Limits und Anbieterbedingungen werden respektiert.
4. Secrets liegen außerhalb des Repositories.
5. Jede Erweiterung hat einen klaren Fehlerpfad und Tests.

## 2. Statusmatrix

| Bereich | Lokal umgesetzt | Externer Vertrag nötig | Status |
| --- | --- | --- | --- |
| Wettbewerbs-Sitemap-Modus | ja, bis Seiten-Budget | nein | umgesetzt |
| Local-SEO-Profile | URL-/Textabgleich | offizielle Profil-API optional | umgesetzt |
| Lokale Suchpositionen | CSV-Import | SERP-Anbieter | Evidenzimport |
| PageSpeed/Lighthouse | nein | Google API-Key | umgesetzt, Key nötig |
| CrUX | nein | Google API-Key | umgesetzt, Key nötig |
| Playwright | Engine-Auswahl vorhanden | Browser-Installation | Chrome/Edge-Fallback umgesetzt |
| GSC Search Analytics | Service Account/OAuth | Google-OAuth | umgesetzt |
| URL Inspection | ja | Google-OAuth + Kontingent | umgesetzt |
| GitHub-Updater | Git-Mechanik | GitHub-Remote + Auth | blockiert bis Remote |
| GEO-Antwortstichproben | DeepSeek-Adapter | API-Key | umgesetzt |
| SERP/Backlinks | nein | lizenzierter Anbieter | blockiert |

## 3. Benchmark: sitemapweiter Modus

### 3.1 Ziel

Der Benchmark bleibt eine begrenzte, robots-konforme Erhebung. Der neue Modus
--full ersetzt die bisherige „erste Sitemap und erste Kind-Sitemap“-Heuristik durch
eine sitemapweite Kandidatensuche bis zu einem expliziten Seitenbudget.

Wichtig: --full bedeutet nicht „unbegrenzt“. Es bedeutet „alle erreichbaren
Sitemap-Kandidaten bis max-pages“. Das Budget bleibt die Schutzgrenze.

### 3.2 CLI

    seoboy benchmark --full --max-pages 200 --competitor https://example.de/

Regeln:

- max-pages: 1 bis 1000, Standard 20.
- --competitor-url hat Vorrang vor der Sitemap-Auswahl.
- robots.txt wird pro Sitemap und pro Seite geprüft.
- Sitemap-Indizes werden rekursiv bis maximal 50 Dokumente verfolgt.
- Es werden höchstens max-pages Seiten je Website abgerufen.
- HTML wird nicht gespeichert; gespeichert werden Metriken, URLs und Content-Terme.

### 3.3 Ablauf

1. Startseite abrufen und finalen Origin bestimmen.
2. robots.txt laden; Sitemaps aus robots.txt lesen.
3. Sitemap-Queue aufbauen; Sitemap-Indizes rekursiv auflösen.
4. Seiten-URLs sammeln, normalisieren, deduplizieren, auf erlaubte Hosts begrenzen.
5. Kandidaten bis max-pages abrufen.
6. Metriken, Content-Terme, TF-IDF, SimHash und Bericht schreiben.

### 3.4 Bericht

- Der Bericht nennt pro Website den Modus „sitemapweite Auswahl bis Budget“.
- Sitemap-URLs werden als gefundene Kandidatenzahl ausgewiesen.
- Abgerufene Seiten können kleiner als die Sitemap-Zahl sein; das ist kein Fehler.
- Ein vollständiger Wettbewerbs-Crawl außerhalb des Budgets bleibt ausdrücklich
  nicht Teil des Befehls.

### 3.5 Akzeptanzkriterien

- Ein Sitemap-Index mit mehreren Kind-Sitemaps wird vollständig durchsucht.
- Das Seitenbudget wird nie überschritten.
- robots.txt-Sperren werden respektiert.
- Der Bericht enthält den Hinweis auf das Budget.
- Tests decken Index, Budget und robots-Sperre ab.

## 4. Local SEO

### 4.1 Standort-YAML

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

### 4.2 Prüfungen

- Standortseite: HTTP, Indexierbarkeit, H1, Schema, NAP.
- Profil: robots.txt, HTTP-Status, Titel, Textabgleich Name/Ort/Telefon.
- Lokale Messergebnisse: CSV-Import mit query,location,position,url,source,date.

### 4.3 Ausgaben

- 00_LOCAL_SEO.md
- raw_data/local_locations.csv
- raw_data/local_profiles.csv
- raw_data/local_rankings.csv

### 4.4 Grenzen

Der Profilabgleich ist ein Textabgleich, keine offizielle Google-Business-API.
Lokale Positionen werden nicht live bei einer Suchmaschine erfragt. Für echte
Profil-APIs braucht es OAuth, Property-Rechte und ein separates Kontingentkonzept.

### 4.5 Optionaler späterer Providervertrag

Falls eine offizielle Profil-API angebunden wird:

- Provider: google_business_profile
- Auth: OAuth mit geschäftlichem Property-Zugriff
- Felder: Standort-ID, Name, Adresse, Telefon, Status, letzte Änderung
- Fehler: unauthorized, quota_exceeded, not_found
- Es werden keine Bewertungen oder Konkurrenzprofile ohne Berechtigung gelesen.

## 5. Performance: PageSpeed/Lighthouse und CrUX

### 5.1 CLI

    seoboy performance --url https://example.de/ --strategy mobile --form-factor PHONE

API-Key über --api-key oder SEOBOY_PSI_API_KEY.

### 5.2 Quellen

- PageSpeed Insights v5, Kategorie performance.
- CrUX queryRecord, p75-Werte.
- Formfaktor: PHONE, DESKTOP, TABLET.

### 5.3 Ausgabe

- 00_PERFORMANCE.md
- raw_data/performance.csv

Enthalten: Performance-Score, FCP, LCP, TBT, CLS, Speed Index, TTI, CrUX-p75.

### 5.4 Fehler- und Kostenregeln

- Ohne Key: Exitcode 2, keine Schätzwerte.
- HTTP-Fehler: Quelle gilt als fehlgeschlagen; keine stillen Nullwerte.
- Ein Bericht darf eine Quelle als „nicht abgefragt“ ausweisen.
- Empfohlen: eigener API-Key nur für diesen Zweck und ein Tageslimit.

### 5.5 Akzeptanzkriterien

- Ohne Key keine Ausgabe außer einer klaren Fehlermeldung.
- Beide Quellen sind getrennt abschaltbar.
- Der Bericht kennzeichnet Labor- und Felddaten getrennt.
- Tests decken Parsing und den Key-Fehler ab.

## 6. Rendering: Playwright und Chrome-Fallback

### 6.1 Engines

- auto: Playwright, falls installiert; sonst Chrome/Edge.
- playwright: erfordert Playwright und Browser-Installation.
- chrome: nutzt einen vorhandenen Chrome/Edge per Headless-Dump.

### 6.2 CLI

    seoboy render --engine auto --browser chromium --url https://example.de/
    seoboy render --engine chrome --url https://example.de/

### 6.3 Grenzen des Chrome-Fallbacks

- Kein verlässlicher HTTP-Status und keine Response-Header.
- Finale URL wird als Eingabe-URL geführt.
- Keine echten Netzwerk-/Performance-Messwerte.
- Der Bericht markiert „Browser-Status fehlt“.
- Für die volle Matrix bleiben Playwright plus Browser-Installation nötig.

### 6.4 Akzeptanzkriterien

- auto nutzt Playwright, wenn verfügbar.
- Ohne Playwright wird Chrome/Edge gefunden und der Bericht geschrieben.
- Ohne beides erscheint eine verständliche Installationsanleitung.
- Browser und Engine stehen im Manifest.

## 7. GSC und URL Inspection

### 7.1 Zugangswege

- Service-Account-JSON (bevorzugt für Server/projektbezogene Konten)
- OAuth-Refresh-Token
- interaktiver OAuth-Login mit persistentem Token-Store

### 7.2 OAuth-Login

    seoboy gsc-auth --client-file client_secret.json

- PKCE S256
- State-Prüfung
- Loopback-Callback auf 127.0.0.1
- Scope webmasters.readonly
- Refresh-Token wird gespeichert; Access-Token nur im RAM
- Standard: %LOCALAPPDATA%\SeoBoy\gsc-oauth.json
- Überschreibbar mit SEOBOY_GSC_TOKEN_STORE

### 7.3 URL Inspection

    seoboy url-inspection --run <lauf-id> --limit 10

- Auswahl wichtiger HTML-URLs
- Persistenz in url_inspections
- 06_URL_INSPECTION.md und raw_data/url_inspections.csv
- Fehler werden als Fehlerzeile gespeichert
- Diff vergleicht Verdict, Coverage, Indexing, Robots, Fetch, Canonicals

### 7.4 Kontingente

- Standard 10, maximal 100 URLs pro Batch.
- Keine parallele Massenabfrage.
- API-Fehler werden nicht als Erfolg gespeichert.
- Property-Rechte müssen vor dem Lauf geklärt sein.

## 8. GitHub und CLI-Updater

### 8.1 Voraussetzungen

Der Updater benötigt:

- Git-Checkout mit .git
- Branch main
- Remote origin
- Upstream main
- sauberen Arbeitsbaum
- erreichbaren Remote

Die E-Mail info@wintryx.de allein reicht nicht. Benötigt werden:

1. GitHub-Repository-URL, z. B. https://github.com/wintryx/seoboy.git
2. Authentifizierung: PAT, SSH-Key oder gh login
3. Entscheidung: privates oder öffentliches Repository

### 8.2 Einrichtung

    git remote add origin https://github.com/<account>/<repo>.git
    git push -u origin main
    git branch --set-upstream-to=origin/main main

Danach:

    seoboy update --check
    seoboy update --apply

### 8.3 Updater-Regeln

- Nur Fast-Forward.
- Kein Update bei lokalem Dirty Tree.
- Kein Update ohne Upstream.
- pip install -e . und Smoke-Test.
- Rollback auf den vorherigen Commit bei Fehler.
- Keine Tokens in Remotes oder Berichten.

## 9. C2 GEO-Sampling (DeepSeek umgesetzt)

### 9.1 Anbieter

- Provider: DeepSeek
- Modell: deepseek-flash = DeepSeek-V4.1-Flash-1017
- Höhere Stufe: deepseek-v4-pro = DeepSeek-V4-Pro-0813
- Endpoint: https://api.deepseek.com/chat/completions
- Standard: Thinking enabled, reasoning_effort=max
- Optional: Thinking disabled für den günstigen Modus
- Optional: serverseitige Websuche deepseek_web_search mit Quellen/Zitaten
- API-Key: SEOBOY_GEO_API_KEY, DEEPSEEK_API_KEY oder --api-key; nie im Repo

### 9.2 CLI

    seoboy geo-sample --domain aw-audio.de --brand "AW Audio" --max-calls 6 --budget-usd 0.50

Optionen:

- --prompts YAML mit version, language, region und prompts
- --model, --temperature, --max-tokens, --thinking, --reasoning-effort
- --web-search, --search-price
- --max-calls, --budget-usd, --input-price, --output-price
- --retention-days
- --brand, --competitor, --domain
- --dry-run ohne API-Aufruf

### 9.3 Ausgabe

- 00_GEO_SAMPLING.md
- raw_data/geo_samples.csv
- raw_data/geo_citations.csv
- raw_data/geo_answers.jsonl (nur lokal, wenn retention_days > 0)
- manifest.json

### 9.4 Kosten und Fehler

- Standard: 6 Aufrufe, 8192 Output-Tokens, 1.00 USD Budget.
- Standard-Modell: DeepSeek-V4.1-Flash-1017 mit Thinking enabled und Effort max.
- Peak-Preise als konservative Schätzung: 0.30 USD/1M Input, 1.20 USD/1M Output.
- Websuche: 0.75 USD je 1.000 Suchschritte, zusätzlich zu Tokens.
- Max-Reasoning plus Websuche kann pro Prompt über 100.000 Input-Tokens erzeugen;
  das Budget stoppt weitere Aufrufe.
- 401/403 stoppt sofort.
- Drei Fehler bei mindestens der Hälfte der Versuche stoppen den Lauf.
- Eine leere Antwort ist ein Fehler, kein Erfolg.
- Der Key erscheint nie in Bericht, CSV oder Manifest.

### 9.5 Retention

Rohantworten werden lokal gespeichert. --retention-days dokumentiert die Frist; die
Löschung erfolgt manuell. retention_days=0 schreibt keine Rohantworten.

### 9.6 Berechtigungsmodell

Der Adapter ist kein autonomer Agent und hat nur diese Fähigkeiten:

- Prompt-YAML lesen,
- HTTPS-POST ausschließlich an api.deepseek.com,
- einen sauberen Report-Ordner schreiben.

Nicht möglich sind Shell, Browser, Website-Änderungen, Datenbankzugriffe, das Lesen
beliebiger lokaler Dateien oder das Ausführen von Modellantworten. Zusätzlich gelten:
Host-Allowlist, Redirect-Verbot, Modell-Allowlist, Prompt-/Antwortlimits, Budgetprüfung
vor jedem Aufruf und ein Überschreibschutz für fremde Ausgabeordner.

### 9.7 Grenzen

Die Antworten sind KI-Momentaufnahmen, keine Suchmaschinen-Rankings. Marken- und
URL-Erkennung ist Textabgleich. Für belastbare Aussagen sind Wiederholungen, weitere
Modelle und Zeitvergleiche nötig.

## 10. C3 SERP/Backlinks (blockiert)

Ein echter Adapter braucht:

- lizenzierten Anbieter oder ausdrücklich erlaubte API
- Suchanfrage, Region, Sprache, Gerät, Datum
- Top-Ergebnisse mit URL und Position
- Backlink-Quelle, Ziel, Anker, Rel-Attribut, Erst-/Letztsichtung
- Rate-Limit, Kosten und Aufbewahrung
- keine Umgehung von Bot-Schutz oder Suchmaschinen-AGB

Bis dahin bleiben die Sitemap-Stichprobe und manuelle Wettbewerbs-URLs der belastbare
Rahmen.

## 11. Datenmodell

Neue Migrationen:

- 002_url_inspections.sql: url_inspections
- 003_action_statuses.sql: action_statuses, action_status_history

Invarianten:

- action_key bleibt stabil und projektgebunden.
- URL Inspection ist pro Lauf und URL eindeutig.
- Statusänderungen werden nie überschrieben, sondern historisiert.
- Content-Terme sind aggregierte Häufigkeiten, kein Volltext.

## 12. Teststrategie

- Unit-Tests für Parser, Scores, SimHash, CSV-Validierung.
- HTTP-Fixtures für GSC, Performance, Profile und Sitemaps.
- Kein Internet in der Testsuite.
- Fehlerfälle: 401, 403, 404, 429, Timeout, ungültiges JSON.
- Migrationen von Version 1 auf die aktuelle Version.
- Updater-Tests mit lokalen Bare-Repositories.

## 13. Abnahmekriterien für die nächste Stufe

1. --full hält das Budget ein und verfolgt mehrere Sitemap-Kinder.
2. Chrome-Fallback rendert eine echte Seite ohne Playwright.
3. GSC-OAuth speichert nur den Refresh-Token und nie den Access-Token.
4. Performance ohne Key liefert Exitcode 2.
5. Local-Profile und Local-Rankings erscheinen im Bericht.
6. action-status ist projektgebunden und historisiert.
7. GEO-Sampling stoppt bei Auth-Fehlern und überschreitet das Aufrufbudget nicht.
8. Alle Tests laufen mit -W error und ohne Netzwerk.
9. Keine Secrets in Commits oder Berichten.

## 14. Offene Entscheidungen

- GitHub-Repository-URL und Sichtbarkeit.
- PageSpeed-API-Key und Tageslimit.
- DeepSeek-Budget pro Monat und Wiederholungsfrequenz für C2.
- SERP-/Backlink-Anbieter und Lizenz für C3.
- Ob der Token-Store zusätzlich per DPAPI verschlüsselt werden soll.
