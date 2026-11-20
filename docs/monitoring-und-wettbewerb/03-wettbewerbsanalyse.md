# Wettbewerbsanalyse anhand konkreter Suchanfragen

## Ziel und Einordnung

SeoBoy soll zeigen, welche Seiten bei einer geschäftlich relevanten Suche gefunden werden und welche Unterschiede für die Besucherentscheidung erkennbar sind. Bestehende Sitemap-Stichproben, manuell ausgewählte Vergleichsseiten, TF-IDF und SimHash bleiben als ergänzende Datengrundlage erhalten. Der neue Bericht knüpft die Seitenauswahl an dokumentierte Suchergebnisse.

## Eingangsdaten und Auswahl

1. Die Analyse verwendet gespeicherte [Ranking-Messungen](02-lokales-keyword-monitoring.md). Jede Auswertung benennt Keywordgruppe, Profil, Zeitfenster, Quelle, beobachtete Tiefe und Zahl der erfolgreichen Stichproben.
2. Pro Suchanfrage stammen die Vergleichsseiten aus der konfigurierten Ergebnistiefe. Startwert: organische Top 10, höchstens drei Vergleichsseiten pro Anfrage und zehn eindeutige Vergleichsseiten pro Bericht. Das Local-Pack ist ein eigener Ergebnistyp. Domain-Übersicht und URL-Detailansicht erhalten jeweils ihr eigenes Aggregat.
3. Erfasse Treffer nach Seitentyp oder Betreiberrolle, zum Beispiel `anbieter`, `portal`, `location`, `ratgeber` oder `unbekannt`. Für die erste Stufe sind Projektzuordnungen und manuelle Korrekturen maßgeblich. Eine spätere automatische Zuordnung bleibt als Vorschlag sichtbar.
4. Vergleiche zuerst konkrete URLs mit derselben Suchintention. Ein Branchenportal darf als Wettbewerber in der Ergebnisliste erscheinen. Sein Inhaltsaufbau wird getrennt von einer Buchungsseite eines einzelnen Anbieters bewertet.
5. Live-Prüfungen von Konkurrenzseiten bekommen ein Seiten- und Hostbudget, respektieren robots.txt und verwenden nur GET/HEAD. Gesperrte oder nicht erreichbare URLs bleiben in der SERP-Tabelle sichtbar und erhalten keinen Inhaltsvergleich. Vorhandene SeoBoy-Abrufe werden bei kompatibler Frische und Methode wiederverwendet.

## Prüfmodell

| Frage | Beobachtbare Evidenz | Grenzen |
| --- | --- | --- |
| Wer besetzt die Suchergebnisse? | Dokumentierte URLs und Positionen pro Suchanfrage und Messprofil | Tiefe und Datum der Messung angeben |
| Welche Seite bedient die Absicht? | Title, H1, ausgewählte Inhaltsbegriffe, manuell belegter Seitentyp | Modell- oder Textähnlichkeit allein genügt nicht |
| Welche Antworten fehlen Lesern? | Belegte Themen zu etwa Einsatzgebiet, Referenzen, Preisen oder Ablauf | Begriffe sind Anhaltspunkte. Eine inhaltliche Lücke wird anhand der Seite bestätigt |
| Ist der Anfrageweg klar? | Beobachtbare Links, Wortlaut und Ziel eines CTA, optional Browserprobe ohne Formularversand | Erreichbarkeit und tatsächliche Konversion getrennt führen |
| Gibt es einen tragfähigen neuen Inhalt? | Hoher Geschäftswert, vorhandene Nachfrage-Evidenz, belegte Angebotsabdeckung und passende Referenzen | Fehlende GSC-Impressionen alleine belegen keine fehlende Nachfrage |

## Ergebnis und Entscheidung

- Pro Suchanfrage werden die Soll-Zielseite, beobachtete eigene Ergebnisse und die Vergleichs-URLs gezeigt. Ein externer Keyword-Export kann Schätzungen zu Suchvolumen oder Nachfrage liefern. Quelle, Markt und Messzeitraum werden angegeben. Fehlende Werte bleiben leer.
- Der Bericht gruppiert Vorschläge nach Suchintention und eigener Zielseite. Bei einer neuen Seite sind Nachfragequelle, praktische Differenzierung, eigenes Leistungsangebot, Nachweise und Abgrenzung zu bestehenden Seiten sichtbar.
- Entscheidungsvorschläge heißen `bestehende_seite_verbessern`, `neuen_inhalt_pruefen`, `beobachten` oder `evidenz_fehlt`. Zu jedem Vorschlag gehören ein Grund, verlinkte Belege und ein nächster Prüfschritt. Entscheidung und Status kann der Anwender lokal überschreiben. Es werden keine Inhalte veröffentlicht und keine SEO-Wirkungen aus Wortzahlen, Sitemap-Größen oder TF-IDF-Werten abgeleitet.
- Ausgaben vorgeschlagen als `COMPETITOR_SERP_COMPARISON.md`, `raw_data/serp_competitors.csv` und `raw_data/content_opportunities.csv`. Je CSV-Zeile referenziert ein stabiler Schlüssel die Suchgruppe und Soll-Zielseite, die zugrunde liegenden Messungen sind separat nachvollziehbar.

## Umsetzung und Abnahme

Zuerst die gespeicherten Ranking-Treffer gruppieren und ausgeben. Danach in derselben Ansicht Vergleichsseiten aus dem bestehenden Benchmark zuordnen. Vorschläge erst erzeugen, wenn die dafür notwendigen Felder vorliegen.

1. Ein Anbieter, ein Portal und ein Ratgeber erscheinen für dieselbe Suche. Die Rollen sind nachvollziehbar und der Inhaltsvergleich bevorzugt die passende Vergleichsseite.
2. Die eigene URL rankt bei einer Top-10-Messung nicht mit. Der Bericht zeigt „außerhalb der gemessenen Top 10“. Er zeigt für fehlende Messungen „keine Daten“.
3. Zwei Begriffe mit gleicher Absicht und Zielseite ergeben einen Vorschlag mit beiden Belegen. Zwei unterschiedliche Zielintentionen bilden getrennte Vorschläge.
4. Eine gesperrte Konkurrenzseite bleibt im Ranking sichtbar und ist im Inhaltsvergleich als ungeprüft markiert.
5. Ein Bericht mit Wettbewerbsbeispiel und Beleg für ein fehlendes Thema schlägt eine konkrete Ergänzung vor. Ohne Beleg oder Suchdaten erscheint ein Prüfhinweis. Budgets und Reihenfolge sind mit Fixtures prüfbar.

Quellen: [SISTRIX Keyword-Chancen](https://www.sistrix.de/tutorials/keyword-chancen/) · [Seobility Keyword-Recherche](https://www.seobility.net/en/keyword-tool/) · [bestehender SeoBoy-Benchmark](../erweiterungen_spezifikation.md#3-benchmark-sitemapweiter-modus).
