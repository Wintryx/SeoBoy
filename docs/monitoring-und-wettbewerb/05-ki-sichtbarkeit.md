# KI-Antworten im Zeitverlauf

## Ziel

SeoBoys vorhandenes, budgetiertes GEO-Sampling zu wiederholbaren Beobachtungen ausbauen. Der Bericht beantwortet, bei welchen typischen Kundenfragen eine Marke genannt, empfohlen oder mit einer eigenen URL zitiert wird und welche Drittquellen in den erhaltenen Antworten wiederkehren. Technische Bot-Zugänglichkeit bleibt ein eigener Bericht.

## Messprofile

- Verwende die vorhandenen Prompt-Dateien. Jeder Prompt hat eine stabile ID, eine Versionskennung, Sprache, Markt beziehungsweise Region und Suchabsicht. Zum Pilot reichen 10–15 echte Kundenfragen aus mehreren Geschäftsfeldern. Konfigurierbare Markenvarianten und Wettbewerberdomain-Zuordnungen unterstützen die Auswertung.
- Jede Ausführung speichert `prompt_id`, `prompt_version`, `platform`, `provider`, `model`, `web_search_mode`, `market`, `language`, `observed_at`, `sample_id`, `status` und gegebenenfalls beobachtete Kosten. Falls eine Region lediglich im Prompt steht und der Anbieter keine Standortsteuerung bietet, steht im Bericht „Region im Prompt“.
- Profil und Antwortquelle sind getrennt. Eine API-Stichprobe ist als solche gekennzeichnet. Aussagen über ChatGPT, Gemini, Perplexity oder Google AI Overviews benötigen Daten aus der jeweils bezeichneten Plattform. Der vorhandene DeepSeek-Adapter ist die erste Quelle. Weitere Plattformen können später über berechtigte Exporte oder eigene Adapter hinzukommen.
- In Stufe 1 werden vorhandene lokale GEO-Manifeste und Antwortberichte eingelesen. Der Vergleich muss auch ohne API-Key möglich sein. Fehlende Pflichtmerkmale älterer Läufe kennzeichnen diese als eingeschränkt vergleichbar. Eine zweite Stufe ergänzt geplante Wiederholungen mit ausdrücklichem Projektbudget.

## Auswertungsregeln

| Merkmal | Definition und Beleg |
| --- | --- |
| **Erwähnung** | Eindeutig zuordenbarer Name oder Domain im Antworttext. Markenalias, Treffertext und Fundstelle sind festgehalten. |
| **Empfehlung** | Die Antwort schlägt die Entität im Kontext des Prompts als passende Wahl vor. Status `ja`, `nein` oder `unklar`, mit begründender Textstelle. Eine neutrale Aufzählung oder Mehrdeutigkeit reicht allein nicht. |
| **Eigenes Zitat** | Eigene URL als belegte Quelle in Provider-Zitaten oder eindeutig zugeordnetem Quellenblock. Ein freier Link im Antworttext erhält eine eigene Kennzeichnung. |
| **Drittquelle** | Quell-URL, Domain, Promptgruppe, Trefferzahl und tatsächlicher Beleg. Registrierbare Domain bei der Gruppierung berücksichtigen. |
| **Nicht auswertbar** | Fehlgeschlagene oder abgebrochene Ausführung, unvollständige Antwort oder nicht verfügbare Zitierdaten. Grund getrennt speichern. |

- Kennzahlen zeigen Zähler und Nenner, etwa „Erwähnung in 3 von 12 auswertbaren Antworten“. Fehler, übersprungene Aufrufe und Antworten ohne verfügbare Zitationsdaten sind separat ausgewiesen. Für die Zitatquote zählen ausschließlich Antworten, für die der Modus eine belastbare Zitierprüfung zulässt.
- Vergleiche nur dasselbe Prompt-Set beziehungsweise dieselbe Prompt-Teilmenge, Plattform, Modell, Region, Sprache und Websucheinstellung. Änderungen werden als Methodenwechsel sichtbar. Bei kleinen Stichproben werden Werte und Anzahl gezeigt. Mehrere Stichproben je Profil ermöglichen eine robustere Aussage als eine Einzelantwort.
- Eine häufig zitierte Drittquelle ist ein Recherchehinweis. Für die Verknüpfung mit [Linkchancen](04-backlinks-und-linkchancen.md) braucht es eine eigene Prüfung. Auf eine Quellenliste mit tatsächlichen Zitaten folgen passende, überprüfbare Handlungsvorschläge.
- Ausgabevorschlag `GEO_TRENDS.md` und `raw_data/geo_observations.csv`. Rohantworten bleiben in der bestehenden lokalen Ablage mit ihrer Aufbewahrung. Für lange Zeitreihen genügen die strukturierten Beobachtungen und begrenzte Belegauszüge nach der Projektkonfiguration.

## Budget und Ausführung

Zeitgesteuerte Messungen sind optional. Ein Plan definiert Höchstzahl der Aufrufe, Wiederholungen, Tokenlimits, Kostenlimit und Ablaufzeit. Aufrufbudgets werden vor der Ausführung geprüft und Authentifizierungs- sowie Quotenfehler lösen den bestehenden Stopp aus. Fehlerhafte Aufrufe bleiben in der Abdeckung erkennbar. Providerzugangsdaten und private Rohtexte erscheinen weder im geteilten Übersichtsbericht noch in Netzwerkanfragen außerhalb des konfigurierten Anbieters.

## Abnahme

1. Zwei gespeicherte Läufe mit demselben Profil ergeben einen dokumentierten Vergleich ohne Netzwerkanfrage. Eine neue Promptversion oder deaktivierte Websuche erzeugt einen gekennzeichneten Methodenwechsel.
2. Eine Antwort nennt eine Marke neutral, eine empfiehlt sie und eine listet ihre URL als Quelle. Die drei Merkmale werden unabhängig erfasst.
3. Ein Text enthält eine bloße URL und ein zweiter Datensatz enthält nachweisbare Provider-Zitate. Die Zitatzählung unterscheidet beide. Bei unklaren Empfehlungsfällen bleibt die Klassifikation nachvollziehbar.
4. Bei zwölf geplanten Aufrufen mit neun verwertbaren Antworten erscheinen neun als Nenner der Erwähnungsquote und drei als fehlgeschlagen oder ausgelassen.
5. Ein importierter Testdatensatz enthält einen Namen, der mehreren Unternehmen entsprechen kann. Der Abgleich erzeugt keine bestätigte Empfehlung allein aufgrund dieses Namens. Kostenlimits und Aufbewahrung bleiben mit den vorhandenen GEO-Tests kompatibel.

Quellen: [SISTRIX Prompt-Monitoring](https://www.sistrix.de/ai/prompt-monitoring) · [Seobility KI-Tracking](https://help.seobility.net/de/article/ai-visibility-tracking) · [SeoBoy-GEO-Sampling](../erweiterungen_spezifikation.md#9-c2-geo-sampling-deepseek-umgesetzt).
