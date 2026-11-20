# Keyword-Kannibalisierung – Spezifikation und Prüfmodell

Stand: 20.11.2026  
Zielversion: 0.17.0

## 1. Definition

Keyword-Kannibalisierung liegt vor, wenn mehrere indexierbare URLs eines Projekts
für dieselbe Suchintention und dieselbe Suchanfrage konkurrieren und dadurch
Sichtbarkeit, Klicks oder eine klare Zielseite verlieren.

Das ist ein **mehrdimensionales Signal**, kein einzelner Schwellenwert. Ein einzelnes
GSC-Paar oder eine Titelähnlichkeit beweist keine Kannibalisierung.

## 2. Bisherige Prüfung und ihre Grenze

Vorhanden war GSC_MULTI_URL:

- betrachtet nur GSC-Zeilen mit URL-Suchanfrage-Granularität,
- zählt URLs mit mindestens 30 Impressionen,
- meldet ab zwei URLs einen plausiblen Befund,
- prüft weder Positionen, Canonicals, Indexierbarkeit noch Title/H1-Überlappung.

Das ist ein nützlicher Kandidatentest, aber **nicht zuverlässig genug** für eine
belastbare Kannibalisierungsdiagnose.

## 3. Neue Prüfung

Die Auswertung kombiniert zwei unabhängige Evidenzquellen:

1. GSC-Suchanfrage × Zielseite aus dem aktuellen Vergleichszeitraum.
2. On-Page-Signale aus dem Crawl: Title, H1, aggregierte Content-Terme, Canonical,
   robots/noindex und Seitentyp.

Ausgabe:

- 08_KEYWORD_CANNIBALIZATION.md
- raw_data/keyword_cannibalization.csv
- Link in 00_EXECUTIVE_SUMMARY.md

## 4. Evidenzstufen

### Stufe A – stärkster Kandidat

- GSC: mindestens zwei URLs mit jeweils mindestens der konfigurierten
  Mindestimpressionzahl für dieselbe nicht-markenbezogene Suchanfrage.
- On-Page: mindestens zwei gemeinsame signifikante Title-/H1-Begriffe,
  ausreichende Title-/H1-Überlappung und inhaltliche Nähe.
- Beide URLs sind indexierbar, nicht auf dieselbe andere URL kanonisiert,
  keine Utility-/Pagination-Seite.
- Keine der beiden Positionen ist schlechter als 50.

Bedeutung: starkes Prüfsignal. Vor einer Konsolidierung müssen GSC-Verlauf,
Suchintention und interne Verlinkung geprüft werden.

### Stufe B – GSC-Signal ohne On-Page-Bestätigung

- GSC-Paar wie Stufe A,
- aber keine ausreichende Title-/H1-/Content-Überlappung.

Mögliche Ursachen:

- SERP-Diversität (Kategorie und Detailseite),
- unterschiedliche Suchintentionen,
- unvollständige Content-Terme,
- bewusste Abdeckung mehrerer Ergebnisse.

### Stufe C – On-Page-Kandidat oder schwaches GSC-Signal

- nur On-Page-Überlappung, kein belastbares GSC-Paar,
- oder GSC-Paar mit einer Position schlechter als 50.

Nur ein Hinweis, kein Nachweis.

## 5. GSC-Algorithmus

1. Nur den aktuellen page_query-Zeitraum je Property/Search-Type/Land/Gerät verwenden.
2. Nur zugeordnete Zeilen mit URL und Query berücksichtigen.
3. Zeilen mit weniger als multi_url_min_impressions je URL verwerfen.
4. Pro Query höchstens die fünf stärksten URLs paarweise vergleichen.
5. Marken-/navigationale Queries ausschließen; Brand-Tokens werden aus dem Host
   abgeleitet.
6. Kanonische Duplikate, noindex, Utility- und Pagination-Ziele ausschließen.
7. Positionen und Klicks je URL speichern.
8. Paare mit Position über 50 als Stufe C herabstufen.

Wichtig: Die GSC-Zeilen sind keine vollständige SERP. Es können nur die exportierten
oder per API abgerufenen Zeilen geprüft werden.

## 6. On-Page-Algorithmus

1. Letzte HTTP-Beobachtung je indexierbarer HTML-Seite.
2. Title und H1 tokenisieren; deutsche Stoppwörter und generische Begriffe
   (zum Beispiel dj, hochzeit, event, kontakt) entfernen.
3. Content-Terme aus dem Hauptinhalt normalisieren.
4. Mindestens zwei gemeinsame signifikante Begriffe verlangen.
5. Title-/H1-Überlappung mindestens 0,34.
6. Content-Jaccard mindestens 0,12.
7. Score = 65 Prozent Title-/H1-Überlappung plus 35 Prozent Content-Ähnlichkeit.
8. Canonical auf eine andere bekannte URL: Seite wird als konsolidiert behandelt
   und nicht als eigenständiger Kandidat geführt.
9. noindex, Utility-Pfade und typische Pagination-Pfade ausschließen.

Die Heuristik ist absichtlich konservativ. Sie ersetzt keine linguistische
Suchintentionsanalyse und speichert keinen Volltext.

## 7. Filter und Ausschlüsse

- Markenquery: Tokens des Start-Hosts, zum Beispiel aw und audio.
- noindex oder expected_indexable=false.
- Canonical auf eine andere gecrawlte URL.
- Impressum, Datenschutz, AGB, Kontakt, Login, Warenkorb, Checkout.
- typische Pfade /page/2/ oder /seite/2/.
- URLs ohne HTML-Beobachtung oder ohne Title/H1.
- identische kanonische URL.

## 8. Interpretation

- Stufe A ist kein Freibrief für eine 301-Weiterleitung.
- Stufe B kann eine bewusste SERP-Strategie sein.
- Stufe C ist ein Rechercheauftrag.
- Eine fehlende Meldung bedeutet nicht automatisch, dass keine Kannibalisierung
  vorliegt: GSC-Anonymisierung, begrenzte Exporte, fehlende URL-Zuordnung und
  unbekannte Suchintentionen bleiben Grenzen.
- Vor Änderungen: GSC-Verlauf sichern, Zielseite festlegen, Canonical und interne
  Links abstimmen, danach erneut messen.

## 9. Effizienz

- Keine zusätzlichen Netzwerkzugriffe: Die Auswertung nutzt den vorhandenen Lauf.
- Kein KI-Aufruf.
- GSC-Paare werden aus den vorhandenen page_query-Zeilen gruppiert.
- On-Page-Paare werden nur unter indexierbaren HTML-Seiten mit Title/H1 berechnet.
- Kandidaten werden auf 50 On-Page-Paare und 5 URLs je Query begrenzt.

## 10. Datenschutz und Speicherung

- Keine Volltexte, nur aggregierte Content-Terme.
- Query-Namen bleiben im lokalen Bericht, wie bei den bestehenden GSC-Berichten.
- Keine Secrets oder GSC-Rohzeilen in der KI-Review-Packung.
- Reports und Datenbank bleiben lokal und unversioniert.

## 11. Akzeptanzkriterien

1. Ein Lauf mit zwei überlappenden Title/H1-Seiten erzeugt einen Stufe-C-Kandidaten.
2. Ein GSC-Paar mit On-Page-Überlappung wird Stufe A.
3. Ein GSC-Paar ohne On-Page-Überlappung wird Stufe B.
4. Eine Position über 50 erzeugt höchstens Stufe C.
5. Markenquery, Canonical-Ziel, noindex und Utility-Seite werden ausgeschlossen.
6. Ohne GSC bleibt der Bericht ein On-Page-Hinweis und behauptet keinen Nachweis.
7. 08_KEYWORD_CANNIBALIZATION.md und CSV werden bei jedem Lauf geschrieben.
8. Der Bericht ist in der Executive Summary verlinkt.

## 12. Spätere Erweiterungen

- lizenzierte SERP-Daten für echte Ergebnisüberschneidung,
- Embedding-/Intent-Modell statt Token-Heuristik,
- zeitlicher Verlauf der Kandidaten,
- optionaler Abgleich mit internen Suchanfragen und Buchungsdaten.
