# Backlink-Import, Verlauf und regionale Linkchancen

## Ziel und erster Umfang

Bestehende, berechtigt exportierte Linkdaten in SeoBoy vergleichen und zu überprüfbaren Aufgaben für die eigene Website verdichten. Erste Anwendungsfälle sind defekte verlinkte Zielseiten, wiederholt auftauchende Quellen der Konkurrenz und mögliche Empfehlungen durch belegte Partner wie Locations oder Fotografen.

## Importformat

Kommandovorschlag `seoboy backlinks import --config … --csv …`. Quellen dürfen aus eigenen GSC-Exporten, berechtigt verwendeten Anbieterexporten und manuell recherchierten Links stammen. Anderes CSV-Layout wird über ausdrücklich zugeordnete Spalten importiert. Unvollständige Anbieterexporte behalten ihren Messumfang.

| Feld | Inhalt |
| --- | --- |
| `source_url`, `target_url` | Beobachtete Quell- und Zieladresse |
| `dataset_source`, `snapshot_id`, `observed_at` | Herkunft, Importcharge und Beobachtungszeitpunkt |
| `anchor_text`, `rel` | Optionaler Linktext sowie etwa `nofollow`, `ugc`, `sponsored` |
| `first_seen_by_provider`, `last_seen_by_provider` | Optionale Zeitpunkte aus dem Anbieterexport |
| `entity_role` | Eigene Domain, Wettbewerber oder unbekannt |
| `review_state`, `review_note` | Lokaler Bearbeitungsstand und Notiz, getrennt vom importierten Datensatz |

- Die Normalisierung vermeidet Dubletten, bewahrt aber die Ursprungsadressen und unterscheidet fachlich relevante Query-Parameter. Anbieterbeobachtungen bleiben unabhängig. Identische Importe werden dedupliziert.
- Ein Linkstatus aus einem Export wird als Providerbeobachtung gespeichert. Ein Link, der in einem späteren Teil-Export fehlt, gilt als **„nicht erneut beobachtet“**. Als bestätigt entfernt gilt er erst nach einer erfolgreichen, inhaltlich vergleichbaren Prüfung der Quellseite. Eine blockierte Quellseite bleibt ungeprüft.
- Der optionale Nachprüfbefehl arbeitet mit einer ausgewählten Quellenliste, einem Hostbudget und robots.txt. Zielseitige Redirect-Ketten oder Fehler werden separat geprüft. Temporäre Fehler und fehlende Sichtbarkeit im ausgelieferten HTML erhalten einen Grundcode. Kein automatischer Outreach, kein Versand und keine Änderung an Drittsystemen.

## Priorisierung und Bericht

- **Eigene verlinkte Zielseiten mit Problem.** Tatsächlich beobachteter externer Link, betroffene Zielseite und HTTP-Befund. Prüfschritt kann ein passendes neues Ziel, eine Korrektur beim Partner oder ein gezielter Redirect sein. Je Ziel wird eine Aufgabe mit allen Quellbelegen gebildet.
- **Regionale Linkchancen.** Quellen, die mehrere ausgewählte Wettbewerber verlinken, werden zusammengeführt. SeoBoy zeigt Quell-URL, verlinkte Seiten, Bezug zum Angebot und eine vorgeschlagene eigene, bereits veröffentlichte Zielseite. Ein regional relevanter Partner mit belegter Zusammenarbeit ist von einem allgemeinen Verzeichnis zu unterscheiden.
- **Verlauf.** Neu gesehen, wieder gesehen, nicht erneut beobachtet und bestätigt entfernt werden getrennt gezählt. Zeitpunkt, Quelle, Abdeckung und fehlende Prüfungen sind sichtbar.
- Erster Bericht `BACKLINK_OPPORTUNITIES.md` und `raw_data/backlink_observations.csv`. Statusänderungen folgen dem bestehenden Konzept für Maßnahmenhistorie. Schätzwerte eines Anbieters behalten ihren Namen und ihre Quelle. Eine eigene allgemeine Autoritätskennzahl ist für diesen Umfang nicht erforderlich.
- Eine spätere API-Anbindung ist optional. Sie nutzt einen zugelassenen Anbieter und führt Kosten, Kontingent, Lizenzgrenzen und Frische mit. Der CSV-Import bleibt als unabhängiger Weg nutzbar.

## Abnahme

1. Dieselbe Datei zweimal importieren. Die Zahl der Beobachtungen bleibt gleich. Ein späterer Import mit einer abweichenden Quelle überschreibt keine ältere Evidenz.
2. Ein Go-live ersetzt eine verlinkte URL. Im Bericht erscheinen der tatsächlich beobachtete Link, das erreichbare beziehungsweise fehlerhafte Ziel und ein gemeinsamer Vorgang je Ziel.
3. Ein Link fehlt in einem begrenzten Folgeexport. SeoBoy zeigt „nicht erneut beobachtet“. Erst eine erfolgreiche Quellprüfung bestätigt eine Entfernung. Ein 403 bleibt ungeprüft.
4. Eine regionale Quellseite verlinkt zwei Wettbewerber. Der Bericht nennt beide Belege und kann eine vorhandene eigene Leistungsseite zuordnen. Ein manuelles Urteil bleibt als solches erkennbar.
5. Die Tests verwenden lokale Fixtures und enthalten Fälle mit Redirect, blockierter Quelle und CSV-Zellen mit Formeleinleitung.

Quellen: [SISTRIX Link-Chancen](https://www.sistrix.de/support/handbuch/links/link-chancen) · [Seobility Backlink-Monitoring](https://www.seobility.net/de/backlink-monitoring/) · [bestehender Providervertrag](../erweiterungen_spezifikation.md#10-c3-serpbacklinks-blockiert).
