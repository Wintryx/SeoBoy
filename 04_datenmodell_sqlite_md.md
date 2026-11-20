# SeoBoy – SQLite-Datenmodell und Migrationen

Das ausführbare Schema für v0.1 liegt in [`migrations/001_initial.sql`](migrations/001_initial.sql). Die [Architektur](01_architektur_und_techstack_md.md) beschreibt den Ausbau, das [Regelwerk](02_seo_geo_und_konkurrenz_engine_md.md) die Prüfungen und das [Reporting](03_reporting_und_priorisierung_md.md) die Auswertung.

## 1. Identitäten und Beziehungen

| Bereich | Tabellen und Verantwortung |
| --- | --- |
| Projekt und Website | `projects` und `sites` trennen Projekt und Prüfziel. Eine SQLite-Datei enthält im MVP ein Projekt mit eigener Website. Ein späterer Wettbewerber bekommt eine eigene Website-ID und eigene Läufe. |
| Lauf | `runs` enthält Prüfziel, Modus, Status, Zeit, Budgets, wirksame Konfiguration, Eingaben sowie Versionen von Crawler, Regeln und Normalisierung. |
| URL | `urls` hält die normalisierte Identität im Projekt. `run_urls` speichert je Lauf Profil, Klicktiefe, Zustand und Zulassung zum Seitenbudget. `url_discoveries` bewahrt die ursprüngliche Schreibweise und Herkunft. |
| Abruf | `crawl_jobs` speichert die Warteschlange je URL und Zweck. `http_attempts` belegt jede reservierte Anfrage und enthält Status, Fehler und Redirect-Ziel. `crawl_origins` hält Robots-Beobachtung und Abrufpause pro Origin. |
| Beobachtung | `page_observations` trennt HTTP- und spätere Browser-Extrakte. `links` bildet Verweise je Extrakt ab. Mehrere HTML-Links derselben Quellseite auf dasselbe Ziel sind für den Graphen eine Kante. `links_complete` bestätigt, dass die Linkextraktion für diesen Abruf vollständig war. |
| Datenquelle | `source_imports` protokolliert Anbieter, Status, Erfassungszeit, Dateihash und Angaben zur Abdeckung. `gsc_datasets` und `gsc_metrics` speichern Segment, Zeitfenster und Werte samt Zuordnungsstatus. |
| Prüfung | `rule_results` speichert Regelversion, Untercheck, Geltungsbereich, Ergebnis, Schweregrad und Beleglage. `result_urls` verbindet Prüfungen mit betroffenen URLs, Quellen und Zielen. `rule_evidence` verweist auf Abrufe, Extrakte oder Importe und enthält Messzeit und konkrete Belege. |
| Maßnahme | `actions` enthält Priorität, Aufwand, Änderung, erwartete Wirkung und Prüfschritt. `action_findings` ordnet der Maßnahme die Befunde desselben Laufs zu. |

URL-IDs sind interne Datenbankschlüssel. Laufübergreifende Identitäten verwenden normalisierte URLs und fachliche Schlüssel. Ein Gegenstandsschlüssel wird deterministisch als JSON-Array aufgebaut, etwa `["url","https://example.de/leistung/","duplicate"]` oder `["link","https://example.de/","https://example.de/alt/"]`. Bei GSC kommen Property, Suchtyp, Land und Gerät hinzu, bei Bedarf auch die URL und Suchanfrage. Messfenster gehören in die Evidenz. Der führende Elementtyp und die Reihenfolge je Typ sind Teil des Versionsvertrags. Die Bericht-ID stützt sich zusätzlich auf Projekt, Website und Regel-ID. Gleiches gilt für Maßnahmen mit ihrer eigenen Art des Fixes und ihrem fachlichen Schlüssel.

Fremdschlüssel mit Lauf-ID verhindern Verweise auf Beobachtungen, Einträge oder Befunde eines anderen Laufs. Jeder zusammengesetzte Fremdschlüssel verweist auf einen passenden Primär- oder `UNIQUE`-Schlüssel, etwa `(run_id, url_id)` in `run_urls`. Zeitstempel werden in UTC als ISO-8601 mit einheitlichem Format gespeichert und erst im Bericht lokal angezeigt. GSC-Zeiträume speichern die vom Import angegebenen Kalendertage einschließlich beider Grenzen. Bei einem unsegmentierten Datensatz stehen leere Länder- und Gerätewerte für „alle“. Eine leere Suchanfrage ist ausschließlich der Schlüssel des Seitenberichts. Der Import prüft diese Invarianten und die eindeutige Zuordnung normalisierter URLs vor der Auswertung.

Benannte Felder tragen Identitäten, Status, Zeiträume und Werte für Filter und Vergleiche. JSON steht in `TEXT`-Spalten mit `json_valid`-Prüfung. Flags verwenden `INTEGER` mit `0` und `1`. `signals_json` bewahrt insbesondere Robots-Direktiven und Canonical-Ziele mit Angabe ihrer Herkunft. `facts_json` enthält bei importbasierten Prüfungen die beteiligten Datensatz- und Zeilenschlüssel. SQLite verlangt einen gesetzten `reason_code` für `not_checked` und `not_applicable`. Die Anwendung prüft zusätzlich, dass der Code nicht leer und für Regel und Ergebnis definiert ist. Vor Abschluss prüft sie, dass jeder Befund Evidenz besitzt, Maßnahmen nur zu Befunden ohne wirksame Ausnahme führen und ein HTTP-Extrakt zum zugehörigen Abruf und zur URL passt.

## 2. Transaktionen für Crawl und Wiederaufnahme

1. **Lauf anlegen.** Aus der aufgelösten Konfiguration inklusive Standardwerten eine kanonische JSON-Darstellung und deren SHA-256 bilden. `inputs_json` hält die Inhalte nicht erneut, sondern ihre Bezeichner und Hashes. GSC-Dateien werden vor dem Crawl anhand dieser Hashes geprüft und als geparster Snapshot übernommen. Die Speicherung von Lauf, Eingabedaten und initialer Warteschlange erfolgt in einer Transaktion.
2. **URL zulassen.** Erst die URL- und Robots-Filter auswerten. Dann in einer kurzen `BEGIN IMMEDIATE`-Transaktion den Seitenplatz reservieren, sofern `admitted_at` noch leer ist und das Seitenlimit Platz bietet. Job und Zulassung werden gemeinsam gespeichert. Das Seitenbudget ergibt sich aus der Zahl zugelassener `run_urls`, das Anfragelimit aus der Zahl der `http_attempts`.
3. **Anfrage reservieren.** Unter derselben Art Transaktion einen fälligen `pending`-Job und das verbleibende Anfragelimit prüfen. Versuch mit `reserved` eintragen, Job auf `in_flight` setzen und committen. Erst danach erfolgt der HTTP-Abruf. HTTP-Weiterleitungen werden vom Client nicht automatisch gefolgt. Ein Redirect liefert lediglich eine beobachtete Kante. Ein weiterer Job entsteht, wenn eine zulässige Kette mit verbleibenden Hops dessen Ziel erreicht. Bereits gespeicherte Antworten desselben Zwecks und derselben URL bleiben wiederverwendbar. Schleife und Hop-Limit werden je Ausgangs-URL ausgewertet.
4. **Ergebnis speichern.** Antwort oder Transportfehler, Extrakt, entdeckte URLs und den nächsten Zustand des Jobs gemeinsam committen. Für einen erneuten Versuch erhält der Job `not_before_at`. Die Origin-Pause aus `Retry-After` wird in derselben Transaktion aktualisiert. Vor dem Dispatch gilt der spätere der beiden Zeitpunkte. Der Auswerter liest nur gespeicherte Antworten.
5. **Fortsetzen.** Der Prozess hält während eines Laufs eine exklusive Betriebssystem-Sperre je Projektdatenbank. Nach deren Erwerb prüft `--resume` Lauf-ID, Modus, Status, Konfigurationshash und die für die Wiederaufnahme relevanten Versionen. Fortsetzbar sind Crawl-Läufe mit `paused` oder `running`, sofern kein anderer Prozess mehr die Sperre hält. Schlägt die Prüfung fehl, meldet die CLI Lauf-ID und Grund mit Exitcode `2`, bevor sie Lauf, Jobs oder Versuche ändert. Für den Start mit geänderten Einstellungen ist ein Aufruf ohne `--resume` erforderlich. Bei erfolgreicher Prüfung wird der gespeicherte GSC-Snapshot wiederverwendet. In einer Transaktion werden übrig gebliebene `reserved`-Versuche als `interrupted` abgeschlossen und die zugehörigen Jobs auf `pending` gesetzt. Frühere Anfragen bleiben im Gesamtbudget. Ein unterbrochener Versuch zählt als reservierte Anfrage und liefert keinen belegten `5xx`-Fehler. Bereits gespeicherte Wartezeiten bleiben wirksam.
6. **Audit abschließen.** `paused` steht für einen fortsetzbaren Zwischenstand, etwa am Ende des Zeitbudgets. `completed`, `partial` und `failed` sind abgeschlossen. Bei einem ausgeschöpften Gesamtbudget bleiben ausstehende URLs als `deferred` sichtbar. Regelergebnisse, Evidenz und Maßnahmen werden gemeinsam mit der endgültigen Laufentscheidung gespeichert. `diff` vergleicht abgeschlossene `completed`- und `partial`-Läufe. Ein Abbruch beim Export lässt sich aus dem gespeicherten Lauf durch erneutes Rendern der Berichte beheben.

Ein Prozess kann nach dem Senden einer Anfrage und vor dem Speichern der Antwort abbrechen. Beim Fortsetzen kann der HTTP-Abruf deshalb erneut erfolgen. Die Reservierung bleibt erhalten, damit dieser Fall das Anfragebudget nicht unterschlägt.

## 3. Vergleich und Abdeckung

Der Vergleich lädt Basis und Ziel für dieselbe Website. Regeln mit abweichender Semantik, veränderte Profile und neue Normalisierungsregeln werden auf Vergleichbarkeit geprüft. Ein im Ziellauf fehlender Datensatz wird als ungeprüft eingeordnet, soweit kein ausdrücklicher Nachweis für „bestanden“ vorliegt. Beispiel für eine Linkkante: Eine entfernte Kante kann als behoben gelten, wenn ein vollständig ausgewerteter Extrakt der Quellseite ihr Fehlen belegt. Bei einem fehlenden Extrakt bleibt die Kante ungeprüft.

Für die Abdeckung zählt der Bericht je Regel, Untercheck und Geltungsbereich eindeutige URLs mit `pass` oder `finding`. Bei Suchanfragen und anderen Gegenständen wird die Bezugsgröße in der passenden Granularität angegeben. Unterdrückte Befunde bleiben in den Messdaten. Eine Ausnahme ändert den Maßnahmenplan und bleibt im Vergleich als Ausnahme sichtbar.

## 4. Erweiterungen per Migration

| Modul | Geplante Ergänzung |
| --- | --- |
| Rendering und Performance | Browser-Extrakte mit eigener Methode und Kontext, Messprofile und separate Performance-Beobachtungen mit Quelle, Gerät, URL oder Origin, Zeitraum und Messwert. |
| URL Inspection und strukturierte Daten | Typisierte Beobachtungen pro URL und Lauf. URL Inspection speichert gemeldeten Indexstatus und Google-Canonical getrennt von HTTP- und Browser-Signalen. |
| Wettbewerb und SERPs | Eigene Läufe je Website. Ein Vergleich referenziert die beteiligten Lauf-IDs, Stichprobe, Seitentypen und Auswahlmethode. SERP-Datensätze erhalten Suchanfrage, Markt, Gerät, Oberfläche und Zeitpunkt. |
| Local SEO | Standorttabelle je Projekt mit stabiler Standort-ID, Zielgebiet und optionaler Standortseite. Lokale Ergebnisbeobachtungen referenzieren Standort und Suchkontext. |
| Experimentelles GEO | Versionierte Prompts und einzelne Ausführungen mit Anbieter, Modell oder Oberfläche, Land, Sprache, Suchmodus, Ergebnisstatus und verlinkten Quellen. Marken-Erwähnungen und Zitierungen werden pro erfolgreicher Stichprobe ausgewertet. |
| Maßnahmenstatus | Änderungsverlauf je Projekt, Website und Maßnahmen-ID mit Status, Zeitpunkt und Notiz. So bleibt der Status vom gemessenen Befund getrennt und lässt sich über mehrere Audits verfolgen. |

Neue Datenquellen verwenden `source_imports` für Herkunft und Erfassungsstatus. Wiederholt abgefragte Daten erhalten typisierte Tabellen mit Modulschlüsseln. Spätere Befundarten können zusätzliche Gegenstandstypen und Evidenzreferenzen über eine Migration hinzufügen. Historische Läufe behalten ihre ursprünglichen Versionen und Ergebnisse.

## 5. SQLite-Betrieb und Abnahme

Die Anwendung setzt auf jeder Verbindung `PRAGMA foreign_keys = ON` und prüft die verfügbare SQLite-Version sowie die JSON-Funktionen. SQLite unterstützt `STRICT` seit 3.37.0. SeoBoy setzt mindestens 3.38.0 voraus, weil JSON-Funktionen ab dieser Version standardmäßig enthalten sind. Migrationen werden in Reihenfolge ausgeführt und setzen `PRAGMA user_version` innerhalb der Transaktion. Eine unbekannte neuere Datenbankversion wird mit einer verständlichen Fehlermeldung abgelehnt. Die Anwendung bewahrt bei späteren Schema-Upgrades die vorhandenen Laufdaten. [SQLite-Fremdschlüssel](https://sqlite.org/foreignkeys.html) · [STRICT-Tabellen](https://sqlite.org/stricttables.html) · [SQLite-JSON](https://sqlite.org/json1.html)

Die Datenbank und ihre Journaldateien sind lokale Laufdaten. Spezifikationen, Migrationen und anonymisierte Beispieldaten können versioniert werden.

- Migration auf leerer SQLite-Datei ausführen und Schema-Version, Fremdschlüssel und Integrität prüfen.
- Beim simulierten Abbruch bleibt ein reservierter Versuch im Budget. Die neue Ausführung verwendet fertige Antworten und setzt offene Jobs unter derselben Lauf-ID fort.
- Laufübergreifende Evidenzreferenzen und doppelte Reservierungen desselben Jobs werden abgelehnt.
- Zwei Audits vergleichen dieselbe Regel mit den drei Fällen „behoben“, „fortbestehend“ und „nicht erneut geprüft“.
- Getrennte GSC-Seitenwerte und URL-Suchanfrage-Paare, Zeiträume und Filter bleiben getrennt abfragbar. Eine fehlende Zeile liefert keinen impliziten Nullwert.
