# Lokales Keyword-Monitoring und erwartete Zielseiten

## Ziel

Ein festes Keywordset beantwortet, welche URL für eine Buchungsanfrage aus welchem Ort sichtbar ist. Der erste Ausbau importiert vorhandene Suchergebnis-Messungen. Er ergänzt GSC und den bestehenden Import in `seoboy local` um konsistente Messprofile, Soll-Ziele und Zeitvergleiche.

## Projektkonfiguration

Die Liste liegt in einer separaten lokalen Datei, beispielsweise `keywords.yaml`. Zu Beginn reichen 20–30 priorisierte Begriffe. Konfiguration enthält:

| Feld | Zweck |
| --- | --- |
| `id` | Stabile ID des Suchbegriffs im Projekt |
| `query`, `intent`, `tags` | Suchtext, etwa `booking` oder `brand`, und Projektgruppen |
| `market`, `language`, `location_key` | Land, Sprache und eindeutig konfigurierte Stadt beziehungsweise Messpunkt |
| `engine`, `device`, `result_type` | Suchmaschine, Gerät und `organic` oder `local_pack` |
| `expected_target` | Kanonischer Pfad für organische Treffer oder eindeutige Profil-ID für das Local-Pack |
| `target_active`, `business_value` | Sollziel aktiv oder geplant sowie Bedeutung für das Projekt |

Ein Begriff kann mehrere Messprofile haben. Unterschiedliche Orte, Geräte und Ergebnistypen werden getrennt ausgewertet. Das Keyword „DJ Beispielstadt“ kann zunächst mit einer geplanten Seite verknüpft sein. Der Bericht markiert diese Zuordnung als geplant und erzeugt bis zur Aktivierung keinen Fehler.

## CSV-Vertrag und Import

- Kommandovorschlag `seoboy rankings import --config … --csv …`. Für das neue Format nimmt `--csv` die Kopfdatei entgegen. Optional enthält `--results` die Trefferdatei. Bei einem erfolgreichen Snapshot ohne Treffer bleibt die Kopfzeile erhalten. Ein Export aus dem vorhandenen Local-CSV-Format darf über einen Adapter eingelesen werden. Fehlende Profilmerkmale werden aus eindeutiger Konfiguration ergänzt oder mit Zeilenhinweis beanstandet.
- Das neue Format hat pro Messung einen Kopfdatensatz mit `snapshot_id,keyword_id,observed_at,source,engine,market,language,location_key,device,result_type,depth,status`. Trefferzeilen enthalten `snapshot_id,position,url,profile_id,domain,title`. Aus dem Top-Treffer einer Domain ergibt sich deren Position, weitere Treffer bleiben sichtbar.
- Position zählt innerhalb des jeweiligen Ergebnistyps und beginnt bei 1. Eine erfolgreiche Messung ohne eigenen Treffer wird als **„außerhalb der gemessenen Top N“** angezeigt. Eine fehlgeschlagene, blockierte oder fehlende Messung bleibt ohne Positionswert. Ein partieller Datensatz gibt die tatsächlich abgedeckte Tiefe an.
- Der Import prüft Zeitstempel, Schema, Ergebnistyp, URLs und eindeutige Profile. Ungültige Batch-Dateien verändern keine Daten. Identische Importe sind idempotent. Widersprüchliche Messdaten unter derselben ID werden abgewiesen. Historische Messungen aus einem anderen Anbieter bleiben mit Quellkennung erhalten.
- URL-Zuordnung verwendet die Projektregeln zur Normalisierung und bekannte kanonische Aliasse. Die Anzeige behält die beobachtete Original-URL. Für das Local-Pack erfolgt der Abgleich über eine eindeutige Profil-ID. Ein bloßer Namensgleichklang bleibt prüfbedürftig.

## Auswertung

- Je Profil jüngste erfolgreiche Position, bestes eigenes Ergebnis, erwartete Zielseite, letzte Vergleichsmessung und Positionsänderung anzeigen. Soll-/Ist-Abweichungen als getrennten Befund ausweisen.
- Geräte, Orte, Ergebnistypen, Quellen und abgedeckte Tiefen kenntlich machen. Ein Anbieterwechsel oder eine geänderte Tiefe wird ausdrücklich markiert. Positionsdifferenzen dürfen nur verwendet werden, wenn beide Positionen in einem vergleichbaren Profil beobachtet wurden.
- Startwerte für die Ansicht: **Top 3 / Top 10 / gemessen** als transparentes Verhältnis der erfolgreichen Messungen. Nenner und Anzahl fehlender Messungen werden ausgewiesen. Ein gewählter Filter verändert den Nenner sichtbar.
- GSC ergänzt Klicks und Impressionen derselben Suchanfrage und Zielseite im gewählten Segment. GSC liefert dabei die beobachtete durchschnittliche Position. Die importierte Punktmessung erscheint daneben mit Ort und Gerät.
- Das neuere Kannibalisierungsmodul kann später eine Zeitreihe der führenden URLs als Evidenz nutzen. Ein einmaliger URL-Wechsel bleibt eine Beobachtung. Die Analyse berücksichtigt aktive Soll-Zielseiten, Suchintention, die bestehende Evidenzstufe und mehrere vergleichbare Messungen.
- Ergebnisvorschlag `rankings_overview.md`, `raw_data/rankings_snapshots.csv` und ein Abschnitt in der Projektübersicht. Ein späterer Provideradapter liefert dasselbe Messformat. Er bekommt ein explizites Anfragen- und Kostenlimit und wird erst nach Wahl einer zulässigen Datenquelle aktiviert.

## Abnahme

1. Dieselbe Anfrage aus zwei Städten mit Desktop und Mobile ergibt vier vergleichbare Zeitreihen innerhalb ihres Profils. Organische Position 4 und Local-Pack-Position 2 erscheinen getrennt.
2. Erfolgreiche Top-10-Messung ohne eigenen Treffer, Anbietertimeout und noch nie gemessener Begriff haben drei verschiedene Anzeigen. Bei späterem Treffer wird kein rechnerischer Sprung von Position 11 behauptet.
3. Erwartet ist `/dienstleistung/`, rankend ist `/blog/`. Der Report zeigt die Abweichung, die Ziel-URL und den Beleg, auch wenn die Position gleich geblieben ist.
4. Ein kanonischer Alias zählt als passende URL, solange die Aliasbeziehung belegt ist. Weitere Treffer derselben Domain bleiben Klickziele der Detailansicht.
5. Ein erneuter identischer Import verdoppelt keine Zeilen. Ein Importfehler erzeugt einen verständlichen Zeilenhinweis. Alle Tests laufen mit synthetischen Daten.

Quellen: [SISTRIX-Projekt-Rankings](https://www.sistrix.de/support/optimizer/einstellungen) · [Seobility Ranking Monitoring](https://help.seobility.net/de/article/ranking-monitoring-in-seobility) · [SeoBoy-Kannibalisierung](../keyword_kannibalisierung.md).
