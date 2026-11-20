# SeoBoy – SEO-, GEO- und Wettbewerbsanalyse

Die Regeln verwenden die Beobachtungen aus [Teil 1](01_architektur_und_techstack_md.md). Der MVP konzentriert sich auf reproduzierbare technische Befunde und die Auswertung eigener GSC-Daten. Erweiterungen sind in den jeweiligen Abschnitten gekennzeichnet.

## 1. Prüfvertrag

Jede Regel hat eine feste ID, eine eigene Version, einen Geltungsbereich und definierte Eingaben. Das Ergebnis wird je Regel und Gegenstand gespeichert, etwa je URL, Linkkante oder Suchanfrage. Ein Befund speichert den Schweregrad (`critical`, `high`, `medium`, `low`, `info`), die Beleglage (`confirmed`, `plausible`, `hint`) und seine Evidenz getrennt. Die Maßnahmenpriorität berücksichtigt zusätzlich den Projektkontext. Nicht ausgeführte oder fachlich unpassende Prüfungen erhalten einen Grundcode.

| Ergebnis | Bedeutung |
| --- | --- |
| `pass` | Die Regel wurde mit ausreichenden Daten geprüft und hat keinen Befund ergeben. |
| `finding` | Die Bedingung für einen Befund ist erfüllt. Die Evidenz wird gespeichert. |
| `not_checked` | Eine nötige Beobachtung fehlt, etwa wegen Sperre, Timeout, Teilcrawl oder fehlenden Imports. |
| `not_applicable` | Die Regel gilt für diese Seite oder dieses Teilobjekt fachlich nicht. |

Ausnahmen unterdrücken eine Empfehlung und bleiben im Prüfergebnis sichtbar. Der beobachtete Befund bleibt erhalten. Bei URLs ohne konfiguriertes Soll zur Indexierbarkeit meldet SeoBoy widersprüchliche Signale zur Prüfung. Ein bestätigter Indexierungsblocker setzt eine nachvollziehbare Sollvorgabe voraus.

## 2. Technische Kernregeln im MVP

| ID | Befund und Bewertung |
| --- | --- |
| `HTTP_UNAVAILABLE` | Endgültiges `4xx` oder `5xx` nach den vorgesehenen Wiederholungen, soweit der Status feststellbar ist. Ein `404` oder `410` auf einer ausdrücklich wichtigen und indexierbaren Seite ist ein Blocker. Bei `5xx` muss der Fehler auch bei beiden vorgesehenen Wiederholungen auftreten, damit er als Blocker gilt. Fehlende Wiederholungen, Timeouts und `429` werden mit Zeitpunkt und Abrufstatus ausgewiesen. |
| `HTTP_REDIRECT` | Interne Schleifen, erreichte Hop-Grenzen und Ketten mit mehr als zwei Weiterleitungen. Nur bestätigte Schleifen auf ausdrücklich wichtigen, erwartbar indexierbaren Seiten sind Blocker. Ein Abbruch am Host- oder Crawl-Limit erhält den entsprechenden Grund. |
| `INDEX_ROBOTS_BLOCKED` | Eine robots.txt-Regel sperrt Googlebot für eine URL, die laut Profil indexierbar sein soll. Die passende Regel und ihr Geltungsbereich bilden die Evidenz. |
| `INDEX_NOINDEX` | Beobachtetes `noindex` in einem wirksamen Robots-Meta-Tag oder `X-Robots-Tag` auf einer URL, die laut Profil indexierbar sein soll. Erwarteter Ausschluss auf einer Danke- oder Filterseite löst diese Regel nicht aus. Bei unbekanntem Soll erscheint `noindex` als Beobachtung. |
| `CANONICAL_TARGET` | Widersprüchliche Canonical-Angaben, belegte Schleifen, Weiterleitungsziele, `4xx`/`5xx`, Nicht-HTML, Googlebot-Sperre oder `noindex` am Ziel. Eine für die eigene Indexierung vorgesehene Seite mit abweichendem Canonical erhält einen Hinweis auf den Profilkonflikt. Ein ungeprüftes oder externes Ziel bleibt als solches sichtbar. |
| `SITEMAP_TARGET` | Sitemap-Eintrag liefert eine Weiterleitung, einen bestätigten Fehlerstatus oder ein beobachtetes `noindex`. Die Evidenz nennt die Sitemap und die Prüfung des Ziels. |
| `LINK_BROKEN` | Ein interner Link verweist auf ein geprüftes `404`- oder `410`-Ziel. Die Ausgabe nennt die Ziel-URL und alle bekannten verlinkenden Seiten. Nicht geprüfte und zugriffsbeschränkte Ziele werden getrennt ausgewiesen. |
| `LINK_ORPHAN_CANDIDATE` | Sitemap-, GSC- oder manuell eingebrachte HTML-Zielseite ohne beobachteten eingehenden internen Link von einer anderen Seite. Die Startseite ist ausgenommen. Die Ausgabe nennt den geprüften Linkgraphen und dessen Abdeckung. |
| `LINK_DEPTH` | Ein wichtiges Ziel liegt oberhalb der konfigurierten Klicktiefe, standardmäßig drei Links. Mindesttiefe wird aus internen Linkpfaden ab der Startseite bestimmt. Ohne beobachteten Pfad bleibt die Tiefe unbekannt. Dies ist ein Hinweis. |
| `META_TITLE` | Fehlender oder identischer, normalisierter Titel auf verschiedenen prüfbaren, für die Suche vorgesehenen oder plausibel geeigneten HTML-Seiten. Bewusst kanonische Varianten bleiben aus der Duplikatgruppe heraus. |
| `META_DESCRIPTION` | Fehlende oder identische Beschreibung für dieselbe Auswahl. Die Regel liefert einen Hinweis auf die Darstellung in Suchergebnissen. Sie prognostiziert keine Positionsänderung. |

Für `META_TITLE` und `META_DESCRIPTION` gilt eine Seite bei der Duplikatsuche nur dann als kanonische Variante, wenn HTML und HTTP-Header zusammen genau ein eindeutiges, abweichendes Canonical-Ziel ergeben. Das Ziel muss innerhalb des Projekts liegen, im Lauf direkt `200 OK` mit HTML liefern, für Googlebot laut Robots-Auswertung abrufbar sein und darf weder `noindex` noch einen abweichenden oder widersprüchlichen Canonical enthalten. Erwartet das Profil für die Quellseite eigenständige Indexierbarkeit, bleibt sie in der Prüfung. Ungültige oder ungeprüfte Ziele führen zu keiner Unterdrückung. Der Ausschluss gilt nur für den Duplikat-Untercheck. [Google zur Canonical-Auswahl](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls)

Crawl-Erlaubnis, deklarierte Robots- und Canonical-Signale und Googles gemeldeter Indexstatus sind eigene Felder. Ist ein Abruf gesperrt, kann SeoBoy eine auf der URL gesetzte `noindex`-Direktive nicht überprüfen. Im nächsten Ausbau kann URL Inspection für ausgewählte eigene URLs den gemeldeten Indexstatus und den von Google gewählten Canonical liefern. Der Datensatz erhält einen Zeitstempel und bildet Googles gespeicherten Stand ab. [Google zu `noindex`](https://developers.google.com/search/docs/crawling-indexing/block-indexing) · [URL Inspection API](https://developers.google.com/webmaster-tools/v1/urlInspection.index/inspect)

Die Regeln liefern folgende Standardklassen für das [Reporting](03_reporting_und_priorisierung_md.md):

- **P2:** Belegte Fehler in HTTP-Zielen, Redirects, Indexierungssignalen, Canonicals, Sitemaps oder internen Links, wenn mindestens eine wichtige Seite oder mindestens drei URLs mit derselben behebbbaren Ursache betroffen sind. Bei Linkbefunden zählen Ziel und betroffene Quellseiten für die Geschäftsbedeutung.
- **P3:** Sonstige technische Befunde, die geprüft oder korrigiert werden sollten, mögliche Orphans und fehlende oder gleiche Titel auf wichtigen Seiten.
- **P4:** Klicktiefe als Hinweis, Meta-Beschreibungen und Titelhinweise auf übrigen Seiten.
- **P1:** Überschreibt die Standardklasse bei einem bestätigten Blocker. Zusätzlich zu den bedingten HTTP- und Redirect-Fällen kann eine Sperre durch robots.txt oder ein beobachtetes `noindex` auf einer ausdrücklich wichtigen, indexierbaren Seite einen Blocker auslösen.

## 3. Chancen aus der Search Console im MVP

Die Auswertung verwendet je Vergleich denselben Suchtyp und dieselben Länder- und Gerätefilter. Trends nutzen zwei abgeschlossene Zeiträume gleicher Länge. Die Berichte nennen Zeitraum, Granularität, Filter und verfügbare Abdeckung. Die Maßnahmen beginnen in P3. Die folgenden Schwellen sind Projektvorgaben für eine erste Sichtung und lassen sich pro Projekt ändern.

| ID | Voraussetzung und Vorschlag |
| --- | --- |
| `GSC_NEAR_TOP` | Standardmäßig mindestens 100 Impressionen im Zeitraum und mittlere Position zwischen 5 und 20 einschließlich. Zeigt Seiten oder belegte URL-Suchanfrage-Paare zur Prüfung von Suchintention, Snippet und internem Linkziel. Die mittlere Position ist ein aggregierter Messwert. |
| `GSC_DECLINE` | Vorperiode mit mindestens 20 Klicks und Rückgang um mindestens 10 Klicks sowie 25 Prozent. Die Ausgabe zeigt beide Messwerte und die Änderung bei Impressionen. Bei fehlender Vergleichszeile bleibt der Trend unbekannt. |
| `GSC_CTR_REVIEW` | Berechnet Klicks geteilt durch Impressionen. Markiert einen Rückgang um mindestens zwei Prozentpunkte für dasselbe URL-Suchanfrage-Paar bei mindestens 100 Impressionen je Zeitraum und höchstens einem Positionspunkt Unterschied. Suchtyp, Länder- und Gerätefilter müssen übereinstimmen. Ohne passenden Vergleich zeigt SeoBoy nur den Messwert. |
| `GSC_MULTI_URL` | Zwei oder mehr belegte URLs mit jeweils mindestens 30 Impressionen für dieselbe Suchanfrage und dasselbe Segment. Gibt eine Kandidatenliste zur manuellen Prüfung aus. Die gemeinsame Suchanfrage allein belegt keinen Schaden durch Kannibalisierung. |

Als Vergleichsperioden dienen standardmäßig die beiden jüngsten vollständigen, nicht überlappenden Importzeiträume gleicher Länge. Fehlende Daten sind unbekannt. Sichtbare Nullen gehören zum Datensatz. Rankings, die aus einem festen SERP-Keywordset stammen, werden später getrennt von GSC-Werten ausgewiesen. Die GSC-API kann Zeilen auslassen. [Search Analytics API](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)

## 4. Erweiterte Technik, Inhalt und Performance

- **Linkgraph und Internationalisierung.** Valide hreflang-Kombinationen und Rückverweise prüfen, soweit alle beteiligten Seiten abrufbar sind. Ein späterer interner PageRank beschreibt die Verteilung im beobachteten Linkgraphen. Er dient als Zusatzinformation zur internen Verlinkung.
- **Content und Medien.** Wortzahl, Titellänge, Überschriftenstruktur und Bildgrößen sind Hinweise je Seitentyp. Exakte Duplikate werden im normalisierten Hauptinhalt gesucht. Near-Duplicates via SimHash oder MinHash ergeben Kandidaten zur Prüfung. Bildbefunde berücksichtigen die Funktion eines Bildes, das ausgelieferte Format und seine Abmessungen. Ein leerer Alt-Text ist für dekorative Bilder zulässig. [Google SEO Starter Guide](https://developers.google.com/search/docs/fundamentals/seo-starter-guide)
- **Performance.** Für wichtige Seitentypen werden repräsentative URLs ausgewählt. CrUX-Felddaten zeigen LCP, INP und CLS mit Gerät, Zeitraum und Granularität (URL oder Origin). Der Bericht kennzeichnet die Origin ausdrücklich, wenn sie als Ausweichwert dient. Lighthouse-Labordaten dokumentieren Messprofil, LCP, CLS, TTFB und TBT, soweit erhoben. Ein normaler Labortest verwendet TBT als Anhaltspunkt für Interaktivität. INP im Labor setzt einen gezielten Interaktionstest voraus. [Web Vitals](https://web.dev/articles/vitals) · [CrUX-Methodik](https://developer.chrome.com/docs/crux/methodology)

## 5. Experimentelles GEO

- **Zugänglichkeit je System.** Prüft relevante robots.txt-Regeln pro Bot und trennt Aussagen über Suchzugriff und Training. `OAI-SearchBot` und `GPTBot` haben unterschiedliche Zwecke. `Google-Extended` ist ein Produkt-Token mit eigener Bedeutung und beeinflusst die Aufnahme in Google Search nicht. Die Nutzerabsicht entscheidet, welche Freigabe sinnvoll ist. [OpenAI-Crawler](https://developers.openai.com/api/docs/bots) · [Google-Crawler und Google-Extended](https://developers.google.com/crawling/docs/crawlers-fetchers/google-common-crawlers)
- **Strukturierte Daten und Inhalt.** Unterscheidet JSON-LD-Syntax, Schema.org-Typen und Eigenschaften sowie optional die Anforderungen einer konkreten Google-Suchfunktion. `@id`, `sameAs` und Autoren- oder Herausgeberangaben werden dort geprüft, wo sie für den Inhalt passen. Nur verifizierte Profile in Vorschlägen verwenden. Quellen, klare Antwortabschnitte, Tabellen oder Autorenangaben sind beobachtbare Merkmale. Ein E-E-A-T- oder Zitier-Score lässt sich daraus nicht ableiten. [Google-Richtlinien für strukturierte Daten](https://developers.google.com/search/docs/appearance/structured-data/sd-policies)
- **`llms.txt`.** Vorhandensein und gegebenenfalls Struktur nach dokumentierter Konvention als optionale Information ausgeben. Google verlangt für AI Overviews und AI Mode weder solche Dateien noch spezielles Schema. [Google zu AI-Funktionen und Websites](https://developers.google.com/search/docs/appearance/ai-features)
- **Beobachtete Erwähnungen und Quellen.** Nutzt einen versionierten Prompt-Satz mit festgelegter Sprache, Region, Oberfläche bzw. API, Modell und Suchmodus, soweit der Anbieter das freigibt. Speichert Zeitpunkt, Anzahl der Wiederholungen, Antworten bzw. Referenzen, Kriterien zur Markenauflösung und verlinkte Zieldomains. Der Bericht zeigt Erwähnungen und Zitierungen jeweils als Anzahl pro erfolgreicher Stichprobe und nennt Fehler separat. Ergebnisse einer API repräsentieren den gewählten API-Modus. Kosten sind pro Lauf begrenzt. Sentiment bleibt eine optionale manuelle Einordnung.

## 6. Wettbewerb und Local SEO

- **Vergleichsgruppe.** Startet je Wettbewerber mit manuell ausgewählten URLs pro Seitentyp oder Suchintention. Weitere Seiten dürfen aus deren internen Links oder ausgewählten Sitemap-Pfaden folgen. Ein eigenes Seiten- und Anfragelimit je Wettbewerber begrenzt die Stichprobe. Der Bericht nennt Auswahlmethode, Domain, Seitentypen und prüfbare URLs je Kennzahl. Der Vergleich funktioniert ohne SERP-Dienst.
- **Content-Gaps.** TF-IDF aus Titeln, Überschriften und extrahiertem Hauptinhalt findet Kandidaten. Die manuelle Prüfung berücksichtigt Angebot, Suchintention und vorhandene Zielseiten. Ein Kandidat führt zu „bestehende Seite verbessern“, „neue Seite prüfen“ oder „für das Projekt ohne Relevanz“.
- **SERP und Backlinks.** SERP-Vergleiche basieren auf einem festen Keywordset mit dokumentierter Region, Sprache, Gerät, Anbieter und Datum. Backlinks und Suchvolumen erfordern einen eigenen Datensatz mit Quelle und Abdeckung. Diese Werte sind nur bei verfügbarer Quelle Bestandteil des Reports.
- **Local SEO.** Lokale Projekte konfigurieren einen oder mehrere benannte Standorte mit Zielgebiet und optionaler Standortseite. Ein eigenes Modul kann Standortseiten, Konsistenz öffentlich sichtbarer Unternehmensdaten und ausgewählte lokale Suchergebnisse prüfen. Lokale Messungen speichern Standort, Suchanfrage, Ort bzw. Koordinate, Gerät, Zeitpunkt und Quelle.
