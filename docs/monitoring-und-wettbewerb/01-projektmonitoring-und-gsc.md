# Projektübersicht, GSC-Vergleich und Monitoring

## Ziel und erster Umfang

Ein Projekt lässt sich nach einem Blick in die Übersicht beurteilen. Neue technische Hindernisse und die wichtigsten offenen Maßnahmen stehen oben. Darunter folgt die Entwicklung der Buchungsseiten. Der erste Ausbau verbindet bestehende Audit-, Diff-, Maßnahmen- und GSC-Daten in einer lokalen HTML-Datei. Ein separater HTTP-Check überwacht ausgewählte URLs zwischen den vollständigen Crawls.

## Datenquellen und Report

- Die Übersicht liest den jüngsten **abgeschlossenen** Audit und den jüngsten kompatiblen Vergleichslauf. Ein neuerer abgebrochener oder unvollständiger Lauf erscheint mit Zeitpunkt, Status und Abdeckung.
- Jede Maßnahme zeigt betroffene URL, Problem, Evidenz, Datum, Priorität, Status und nächsten Prüfschritt. Die Gesamtübersicht zeigt bis zu drei offene, nach Geschäftswert und Evidenz sortierte Aufgaben und verlinkt die vollständige Liste. Überlappende GSC-Chancen werden in der Ansicht pro Zielseite und Suchintention zusammengefasst. Rohbefunde und gespeicherte Maßnahmenschlüssel bleiben erhalten.
- Ein URL-Detailbereich verbindet HTTP-Status, Canonical, Robots und jüngsten gespeicherten Google-Indexstand mit dem GSC-Verlauf. Crawlstatus und Googles gespeicherte Sicht sind getrennt und jeweils datiert. Messwerte zu Performance erscheinen, soweit vorhanden, mit Quelle, Gerät und Datum.
- Ausgabevorschlag `PROJECT_OVERVIEW.html` neben den bestehenden Markdown-Berichten sowie `raw_data/monitor_events.csv` für den Verlauf. Die Datei funktioniert offline, auch ohne JavaScript bleiben Inhalte und Verweise sichtbar. Filter für Befundstatus, Priorität und Seitengruppe greifen nur auf die lokale Anzeige zu.
- Projektbezogene Änderungsnotizen können aus `changes.csv` gelesen werden. Felder `date,scope,url,summary`. Wird keine URL angegeben, betrifft die Notiz das Projekt. Notizen werden am Messzeitraum angezeigt und dienen als Kontext für die Auswertung.

## GSC-Datenvertrag

1. Der automatische Abruf ermittelt einen letzten verfügbaren finalen Tag, wenn der Anbieter die Tagesdaten liefert. Standard sind danach 28 abgeschlossene Tage und die vorherigen 28 Tage. Start und Ende sind inklusive. Der Vorzeitraum endet einen Tag vor dem Hauptzeitraum und ist gleich lang. Datumsauswahl des bestehenden Imports sowie explizite CLI-Angaben bleiben nutzbar.
2. Je Zeitraum werden `page` und `page_query` getrennt gespeichert. Verglichen werden ausschließlich identische Property, Suchtyp, Land, Gerät und Granularität. Das Manifest führt den tatsächlich beobachteten Zeitraum neben dem angefragten Zeitraum sowie Abbruch- und Limitstatus. Wenn der Vorzeitraum fehlt, wird die Einzelperiode ausgewertet und die Ursache im Bericht sichtbar.
3. Die Übersicht für Zielseiten verwendet `page` für Klicks, Impressionen, CTR und Position. Die Suchanfrage-Tabelle verwendet `page_query`. Abdeckung je URL wird optional als `Summe der sichtbaren Query-Impressionen / Seiten-Impressionen` ausgewiesen, sofern beide Werte vergleichbar sind. Ein aggregiertes Suchanfrage-Ergebnis über mehrere URLs bleibt als Summe der URL-Zeilen kenntlich. Property-Werte werden aus einer passenden API-Aggregation übernommen.
4. Für Positionsänderungen klar anzeigen, ob ein kleinerer Wert eine Verbesserung bedeutet. CTR-Differenzen werden in Prozentpunkten angegeben. Bei null Impressionen bleibt die CTR leer. Fehlende Zeilen gelten als fehlende Daten. Eine API-Limitierung wird mit Grund ausgegeben.

## Leichter URL-Monitor

| Feld | Inhalt |
| --- | --- |
| `observed_at`, `project_id` | UTC-Zeitstempel und Projekt |
| `watch_key`, `url` | Stabiler Prüfschlüssel und konfigurierte URL |
| `http_status`, `final_url`, `elapsed_ms` | HTTP-Ergebnis, Ziel nach erlaubten Weiterleitungen, Laufzeit |
| `robots_directive`, `canonical_url` | Beobachtung bei auswertbarem HTML |
| `state`, `reason_code` | `ok`, `suspect`, `confirmed`, `recovered` oder `not_checked` |
| `first_seen`, `last_seen`, `event_key` | Vorgangshistorie und unveränderlicher Schlüssel innerhalb eines Ereignisses |

- Als Sollwerte dienen die Projektkonfiguration und optional explizite Erwartungen je URL. Für Veröffentlichungen werden HTTP 200, erwartetes Redirect-Ziel, Canonical und Indexierungsdirektiven separat geprüft. Bewusst umgeleitete oder per `noindex` konfigurierte Seiten sind abgedeckt.
- Ein auffälliger Check wird im nächsten geplanten Lauf oder nach dem konfigurierten Mindestabstand neu geprüft. Zwei vergleichbare Fehler bestätigen das Ereignis. Eine erneute identische Beobachtung aktualisiert `last_seen`. Der nächste belegte Sollzustand schließt das Ereignis als `recovered`.
- Temporäre DNS-/Netzfehler, 429 und nicht prüfbare Seiten erzeugen erklärbare Zustände. Hostlimit, Retry-After und Sperren gelten auch für Bestätigungsabrufe. Beim lokalen Zeitplan werden verpasste Ausführungen nicht als Ausfälle gewertet. Die Ansicht zeigt den Zeitpunkt der letzten tatsächlichen Messung.
- MVP mit manuellem oder extern geplantem `seoboy monitor check --config …`, lokaler Ausgabe und maschinenlesbarem Zustand. E-Mail oder Webhooks sind spätere, explizit konfigurierte Ausgaben. Wiederholte identische Ereignisse erzeugen höchstens einen Alarm je Phase.

## Umsetzung und Abnahme

Reihenfolge: GSC-Bericht korrigieren, Zweiperioden-Abruf ergänzen, HTML-Übersicht erzeugen, URL-Monitor umsetzen. Auswertung nutzt die bestehenden Reportdaten und `diff`. Der leichte Monitor erhält eine eigene Beobachtungstabelle und löst keinen vollständigen Crawl aus.

- Synthetische Seite mit 120 Impressionen in `page` und 95 in `page_query`. Die Übersicht zeigt 120 Gesamtimpressionen und einen getrennt gekennzeichneten Teilbestand von 95.
- Ein vollständig verfügbarer 28-Tage-Abruf erzeugt zwei vergleichbare Zeiträume. Teilfehler, explizite Datumsgrenzen und fehlende Daten liefern jeweils dokumentierte Ergebnisse.
- Ein einmaliger 503 bleibt verdächtig. Zwei vergleichbare Fehler lösen genau ein Ereignis aus. Wiederherstellung wird im nächsten erfolgreichen Check ausgewiesen.
- Ein absichtlich gesetztes `noindex` bleibt ein Sollzustand. Ein unerwartetes `noindex` auf einer Buchungsseite wird erkannt. Ein lokaler Netzausfall ohne erfolgreiche Wiederholung bleibt als solcher erkennbar.
- HTML-Test mit einer URL und einem Titel mit Sonderzeichen. Ausgabe ist offline lesbar, Verweise zeigen in den passenden Lauf und die bestehende Markdown-/CSV-Ausgabe bleibt kompatibel.

Quellen: [Search Console API](https://developers.google.com/webmaster-tools/v1/searchanalytics/query) · [Seobility Website Audit](https://www.seobility.net/de/website-audit/) · [Seobility Uptime Monitoring](https://help.seobility.net/de/article/uptime-monitoring).
