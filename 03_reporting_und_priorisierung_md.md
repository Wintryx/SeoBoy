# SeoBoy – Reporting und Priorisierung

Ein Lauf liefert einen Maßnahmenplan mit überprüfbaren Befunden. Der Bericht nennt die betroffenen Seiten, schlägt eine Änderung vor und zeigt, woran sich die Behebung erkennen lässt. Er basiert auf dem [Datenmodell](01_architektur_und_techstack_md.md) und den [Prüfregeln](02_seo_geo_und_konkurrenz_engine_md.md).

## 1. Ausgabe je Lauf

SeoBoy schreibt Berichte in einen Ordner wie `reports/2026-11-20_example-de_<lauf-id>/`. Dateinamen sind stabil. Pfade innerhalb des Berichts sind relativ.

| Datei | Inhalt im MVP |
| --- | --- |
| `00_EXECUTIVE_SUMMARY.md` | Status des Laufs, Abdeckung, Datenquellen, wichtigste Maßnahmen. |
| `01_ACTION_PLAN_PRIORITIZED.md` | Priorisierte Maßnahmen mit Evidenz, URL-Beispielen, geschätztem Aufwand und Prüfschritt. |
| `02_TECHNICAL_SEO_AUDIT.md` | Messbare technische Befunde, GSC-Auswertung bei vorhandenem Import, nicht prüfbare Regeln und Grenzen der Daten. |
| `raw_data/all_urls.csv` | URL-Inventar mit Entdeckungsquellen, Abrufstatus und Profil. |
| `raw_data/rule_results.csv`, `raw_data/broken_links.csv` | Prüfergebnisse einschließlich Evidenz sowie defekte Linkziele mit Quellseiten. |
| `manifest.json` | Lauf- und Projekt-ID, Tool- und Regelversion, Zeitstempel, Status, Abbruchgrund, Crawl-Konfiguration ohne Geheimnisse und Datenquellenstatus. |

Bei aktivierten Erweiterungen kommen `03_GEO_AND_AI_READINESS.md` und `04_COMPETITOR_BENCHMARK.md` sowie passende CSV-Dateien hinzu. Der MVP zeigt geprüfte, auffällige und ungeprüfte URLs samt Bezugsgröße. Beispiel: 3 von 45 geprüften Sitemap-Zielen liefern einen Fehler, 5 weitere Ziele blieben ungeprüft. Auf einen globalen SEO-, GEO- oder Technik-Score verzichtet v0.1.

CSV-Ausgaben nutzen UTF-8 mit BOM, Kommas als Trenner und feste Spaltenüberschriften. Für Excel-Exporte werden Textwerte, die Tabellenprogramme als Formeln interpretieren könnten, als Text geschrieben. Der unveränderte Beobachtungswert bleibt in SQLite.

## 2. Befunde zu Maßnahmen bündeln

Ein Befund ist eine konkrete Regelverletzung oder eine belegte Auffälligkeit. Eine Maßnahme bündelt Befunde, für die dieselbe Änderung genügt. Mehrere Links auf dasselbe defekte Ziel ergeben beispielsweise eine Maßnahme mit einer Liste der Quellseiten. Bei vermuteter gemeinsamer Template-Ursache dürfen die Befunde erst nach einer nachvollziehbaren Zuordnung als gemeinsamer Fix erscheinen.

Die Befund-ID ergibt sich aus Regel-ID, normalisierter URL und einem optionalen, deterministischen Teilobjektschlüssel, etwa der Ziel-URL. Die Maßnahmen-ID ergibt sich aus Projekt, Regel und Art des Fixes sowie einem fachlichen Schlüssel wie betroffener URL, Linkziel oder bekanntem Template. Weder die Lauf-ID noch eine veränderliche URL-Anzahl gehören zu diesen IDs. Die Befundebene bleibt für Vergleiche erhalten, auch wenn sich die Gruppierung der Maßnahmen ändert.

## 3. Priorität und Reihenfolge

Die Priorität folgt einer festen Reihenfolge. Zuerst wird die Dringlichkeit bestimmt. Danach sortiert SeoBoy innerhalb der Klasse nach Beleglage, Geschäftsbedeutung, Reichweite und Aufwand. Es gibt keine Gesamtformel, in der geringer Aufwand einen schlechten oder unsicheren Befund zum Blocker macht.

| Klasse | Wann sie vergeben wird |
| --- | --- |
| **P1 – Blocker** | Bestätigter Abruf- oder Indexierungsblocker auf einer Seite mit hoher Geschäftsbedeutung und `expected_indexable: true`. Beispiele sind ein beobachtetes wirksames `noindex`, eine nachgewiesene Redirect-Schleife oder ein bestätigter Abruffehler gemäß `HTTP_UNAVAILABLE`. |
| **P2 – Zeitnah** | Klar belegtes technisches Problem mit konkreter Auswirkung auf wichtige Seiten oder einen relevanten Teilbereich. Dazu können fehlerhafte interne Linkziele auf wichtigen Seiten oder eine Sitemap mit mehreren kaputten Zielen gehören. |
| **P3 – Prüfen oder verbessern** | Datenbasierte Chance, vermutete Ursache oder strategische Verbesserung. Dazu gehören GSC-Chancen, mögliche Orphans und Content-Gaps. |
| **P4 – Pflege** | Redaktioneller Hinweis oder Verbesserung mit geringem erwarteten Nutzen, beispielsweise fehlende Meta-Beschreibungen auf wenig wichtigen Seiten. |

Jede Regel liefert eine Standardklasse. P1 setzt immer die oben genannten Bedingungen und einen bestätigten Befund voraus. Eine plausible, aber nicht bestätigte Ursache bleibt höchstens P3. Offene Prüfungen erscheinen bei der Abdeckung.

| Merkmal | Bewertung und Sortierrichtung |
| --- | --- |
| **Beleglage** | Bestätigt vor plausibel vor Hinweis. Ein eindeutiger HTTP- oder Headerwert ist eine direkte Beobachtung. Seine Interpretation als Problem braucht den passenden Seitenkontext. |
| **Geschäftsbedeutung** | Hoch vor normal vor niedrig. Maßgeblich ist die höchste Bedeutung unter den belegten betroffenen Seiten. |
| **Reichweite** | Anzahl der betroffenen URLs absteigend. Im Bericht steht zusätzlich die Anzahl der für dieselbe Regel prüfbaren URLs im selben Geltungsbereich. GSC-Impressionen und Klicks liefern Kontext, wenn sie vergleichbar vorliegen. |
| **Aufwand** | Klein vor mittel vor groß vor unbekannt. Grundlage ist der vorgeschlagene Fix. Ein Template-Fix kann viele Seiten betreffen und trotzdem klein sein. |
| **Gleichstand** | Stabile Maßnahmen-ID aufsteigend. |

Die Zusammenfassung zeigt zuerst die dringendsten offenen Maßnahmen. Eine zusätzliche Liste von maximal fünf Quick Wins enthält bestätigte P2-Maßnahmen mit geringem Aufwand. Ein fehlendes `llms.txt` erzeugt keinen Quick Win. Die erwartete Wirkung wird qualitativ formuliert. Vorher-Nachher-Werte aus GSC bleiben beobachtete Änderungen im angegebenen Zeitraum.

## 4. Format einer Maßnahme

```markdown
### P1 – Leistungsseite versehentlich auf noindex

- **Regel und ID:** INDEX_NOINDEX · stabile Maßnahmen-ID
- **Betroffen:** /leistungen/pa-anlage/ · 1 von 8 geprüften Leistungsseiten
- **Evidenz:** HTTP 200 und X-Robots-Tag: noindex im gespeicherten Abruf
- **Einordnung:** Die Seite ist als geschäftlich wichtig und indexierbar markiert
- **Änderung:** Regel für den X-Robots-Tag auf dieser Seite korrigieren
- **Erwartete Wirkung:** Eine unbeabsichtigte Indexierungssperre entfällt
- **Erneut prüfen:** URL abrufen und im Header und HTML nach noindex suchen
- **Aufwand:** Klein
```

Jede Maßnahme enthält außerdem die Datenquelle und den Messzeitpunkt bzw. das Messfenster. Bei mehreren URLs enthält der Text wenige Beispiele und einen relativen Link auf die passenden Rohdaten. Codebeispiele erscheinen nur bei ausreichendem Kontext. Geschäftsdaten wie offizielle Unternehmensprofile werden aus bestätigten Angaben übernommen.

## 5. Vergleich zweier Läufe

`diff` schreibt `05_AUDIT_DIFF.md` und `raw_data/audit_diff.csv` in einen eigenen Vergleichsordner je Paar aus Basis- und Ziellauf. Beide Lauf-IDs gehören in den Bericht. Der Vergleich betrachtet Befunde auf Ebene der stabilen Befund-ID. Bei neu gefundenen Linkkanten kann ein zuvor sauber geprüfter Linkbestand den Ausgangszustand belegen, sofern die betreffende Quellseite in beiden Läufen vollständig ausgewertet wurde. Regeln müssen in vergleichbaren Versionen mit geeigneten Beobachtungen und passendem Geltungsbereich ausgeführt worden sein. GSC-Vergleiche verwenden dieselbe Property und Granularität, dieselben Filter und passende Zeiträume. Änderungen an Regeln, Profilen oder Geltungsgrenzen, die die Befunde beeinflussen, erscheinen im Vergleich.

| Zustand | Bedingung |
| --- | --- |
| **Neu** | Vergleichbare Regel war im Basislauf bestanden und meldet jetzt einen Befund. |
| **Erstmals beobachtet** | Aktueller Befund ohne vergleichbare Beobachtung im Basislauf. |
| **Fortbestehend** | Derselbe Befund liegt in beiden Läufen mit vergleichbarer Evidenz vor. |
| **Behoben** | Dieselbe Regel wurde im Ziellauf mit ausreichender Evidenz erneut geprüft und bestanden. |
| **Ungeprüft** | Eine notwendige Beobachtung fehlt, etwa wegen Zeitlimit, Timeout oder Sperre. |
| **Nicht vergleichbar** | Die Regel, ihr Geltungsbereich oder ihre fachliche Anwendbarkeit hat sich so geändert, dass der Vergleich keine belastbare Aussage zulässt. |

Bei gruppierten Maßnahmen zeigt der Bericht die Zustände der einzelnen Befunde. Eine Maßnahme gilt erst als vollständig behoben, wenn alle bisherigen Befunde nachweislich behoben sind und der aktuelle Lauf innerhalb vergleichbarer Abdeckung für denselben Fix keinen weiteren Befund enthält. Neue oder abgelaufene Ausnahmen ändern die Sichtbarkeit im Maßnahmenplan. Sie ändern keine Beobachtung und gelten nicht als Reparatur.

Im nächsten Ausbau führt SeoBoy einen manuellen Status je Maßnahme mit Datum und Notiz. Eine Maßnahme kann offen, geplant, umgesetzt oder als Ausnahme akzeptiert sein. Nach einem erneuten Lauf zeigt SeoBoy zusätzlich den gemessenen Prüfstatus. Für die Erfolgsauswertung lassen sich Umsetzungsdatum und vergleichbare GSC-Zeiträume verknüpfen.

## 6. Abnahme des Reportings

- Ein bestätigtes `noindex` auf einer wichtigen Leistungsseite erscheint vor Hinweisen zur Meta-Beschreibung. Eine ausdrücklich ausgeschlossene Danke-Seite löst keinen solchen Befund aus.
- Ein defektes internes Linkziel mit drei Quellseiten belegt eine Maßnahme mit drei nachvollziehbaren Links im CSV-Export.
- Eine im Folgelauf geprüfte und korrigierte URL wird als behoben angezeigt. Eine am Crawl-Limit ausgelassene URL bleibt ungeprüft.
- Mit und ohne GSC-Import sind Berichte vollständig lesbar. Leere Quellen und unvollständige Stichproben werden sichtbar ausgewiesen. Markdown- und CSV-Exporte lassen sich über Lauf-ID und Befund-ID auf die Datenbank zurückführen.
