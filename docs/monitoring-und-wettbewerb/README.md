# SeoBoy – Spezifikationen für Monitoring und Wettbewerbsanalyse

Stand 20.11.2026 · Grundlage ist der Repository-Stand 0.21.0. Stufe 1 ist umgesetzt; die übrigen Schnittstellen sind Entwürfe für die Umsetzung.

## Reihenfolge und Umfang

| Reihenfolge | Spezifikation | Erste nutzbare Stufe | Externe Daten |
| --- | --- | --- | --- |
| 1 | [Projektübersicht, GSC-Vergleich und Monitoring](01-projektmonitoring-und-gsc.md) | Lokaler HTML-Bericht, zwei vergleichbare GSC-Zeiträume, bestätigte Änderungen an wichtigen URLs – **umgesetzt in 0.21.0** | Bestehender GSC-Zugang optional |
| 2 | [Lokales Keyword-Monitoring](02-lokales-keyword-monitoring.md) | Feste Keywordliste, CSV-Import, Soll-/Ist-URL und Verlauf | Eigene Messungen oder berechtigte Exporte |
| 3 | [Wettbewerbsanalyse nach Suchanfrage](03-wettbewerbsanalyse.md) | Wettbewerber aus den importierten Suchergebnissen ableiten und passende Seiten vergleichen | SERP-Import aus Stufe 2 |
| 4a | [Backlink-Import und Linkchancen](04-backlinks-und-linkchancen.md) | Eigene Exportdateien zusammenführen und relevante Quellen manuell nachprüfen | Eigene oder berechtigt exportierte Backlinkdaten |
| 4b | [KI-Antworten im Zeitverlauf](05-ki-sichtbarkeit.md) | Bestehende Stichproben vergleichen, Erwähnungen, Empfehlungen und Zitate getrennt auswerten | DeepSeek-Zugang optional für neue Messungen |

Stufe 1 hat den größten unmittelbaren Nutzen. Stufen 2 und 3 bilden zusammen eine Grundlage für Entscheidungen über bestehende Buchungsseiten und neue Inhalte. Stufen 4a und 4b können unabhängig voneinander folgen. Startwerte in den Fachspezifikationen dienen der Erprobung und sind je Projekt konfigurierbar, wenn sich der Bedarf bestätigt.

## Gemeinsame Anforderungen

- Vorhandene Befund- und Maßnahmen-IDs, CLI-Befehle und Reportpfade gelten weiter. Neue Kennzahlen erscheinen zunächst zusätzlich. Änderungen an der Berechnung erhalten eine ausgewiesene Methodenversion.
- Jede Beobachtung führt Quelle, Erfassungszeit, Projekt und Messumfang. Bei einem Vergleich müssen Segment und Messmethode passen. Fehlende, gesperrte, unvollständige und bestätigte Messungen erhalten eigene Zustände.
- Lokale Daten liegen unter den bereits vorgesehenen Projekt-, Daten- und Reportpfaden. Neue SQLite-Felder werden über nummerierte Migrationen ergänzt. Ein Import schreibt in einer Transaktion, doppelte Eingaben bleiben reproduzierbar. Historische Rohbeobachtungen bleiben nachvollziehbar.
- Website-Audits bleiben lesend und halten robots.txt und Hostbudgets ein. Externe Datenimporte sind standardmäßig lokal. Provider-Aufrufe werden separat konfiguriert und protokolliert. Ein CSV-Import braucht keine Zugangsdaten und sendet keine Daten.
- Reportinhalte aus Websites, CSVs und Modellantworten gelten als Daten. HTML-Ausgaben maskieren diese Texte und verwenden sichere Links. CSV-Exporte übernehmen den bestehenden Formelschutz. Reports werden lokal erzeugt.
- Abnahme mit synthetischen Fixtures, lokalen HTTP-Servern und temporären Datenbanken. Ein späterer Realtest nutzt ein ausdrücklich ausgewähltes eigenes Projekt und dessen vorhandene Crawl- und API-Budgets.

Grundlagen: [bestehende Erweiterungsspezifikation](../erweiterungen_spezifikation.md), [Kannibalisierungsprüfung](../keyword_kannibalisierung.md) und [KI-Review](../ki_review_spezifikation.md).
