# SeoBoy – KI-Review-Spezifikation

Stand: 20.11.2026  
Zielversion: 0.16.0

## 1. Ziel

Der deterministische SeoBoy-Audit bleibt die faktenbasierte Grundlage. Eine neue
KI-Review-Schicht prüft danach das Gesamtergebnis auf:

- Widersprüche zwischen Befunden, Maßnahmen und Abdeckung,
- übersehene Zusammenhänge zwischen mehreren Befunden,
- unplausible Prioritäten oder fehlende Quick Wins,
- Datenlücken und nicht geprüfte Bereiche,
- zusätzliche sinnvolle Analysen.

Die KI ersetzt keine Regel und keine Messung. Sie liefert eine **advisory Review**, die
im Bericht klar als solche gekennzeichnet wird.

## 2. Abgrenzung

Nicht Teil der KI-Review:

- keine neuen Crawls oder Website-Zugriffe,
- keine Änderung von Befunden, Maßnahmen oder Prioritäten in SQLite,
- keine erfundenen Messwerte oder Rankings,
- keine Freigabe von Maßnahmen,
- keine Ausführung von Modellantworten,
- keine Websuche und keine externen Fakten.

Jede KI-Aussage muss auf eine vorhandene Befund-ID, Maßnahmen-ID oder Abdeckungszahl
verweisen. Nicht belegte Aussagen werden als ungeprüft markiert oder verworfen.

## 3. Prozess

### Stufe 1 – deterministischer Audit

Bestehender Crawl, Regeln, Maßnahmen und Berichte bleiben unverändert die Quelle der
Wahrheit.

### Stufe 2 – kompakte Evidenzpackung

SeoBoy baut aus dem gespeicherten Lauf eine kleine JSON-Packung:

- Projekt, Lauf-ID, Status, Start-URL, Regelversion,
- Abdeckung: Ergebnisse je Outcome, ungeprüfte Gründe, URL-/Request-Zahlen,
- Befunde: maximal 40, sortiert nach Schweregrad und Konfidenz,
- Maßnahmen: maximal 25, sortiert nach Priorität,
- je Befund: kurze Evidenz, betroffene URLs ohne Query-String, Maßnahmenbezug,
- je Maßnahme: Titel, Priorität, Aufwand, erwartete Wirkung, Verifikation,
- Datenqualität: fehlende GSC-Daten, Limits, nicht geprüfte Fälle.

Nicht enthalten: HTML, vollständige GSC-Zeilen, Secrets, Cookies, Dateiinhalte oder
personenbezogene Daten. Query-Namen können nur dann enthalten sein, wenn sie bereits
Teil eines vorhandenen Befunds oder seiner Evidenz sind; komplette GSC-Rohzeilen werden
nicht übermittelt.

### Stufe 3 – ein strukturierter KI-Aufruf

Pro Lauf gibt es standardmäßig **einen** Aufruf. Das Modell erhält:

- eine feste Review-Anweisung,
- die Evidenzpackung,
- ein JSON-Schema für die Antwort.

Kein Tool-Aufruf, keine Websuche, keine Dateioperation. Das Modell antwortet nur mit
JSON.

### Stufe 4 – Validierung

SeoBoy prüft:

- gültiges JSON und Pflichtfelder,
- referenzierte Befund- und Maßnahmen-IDs existieren,
- Prioritäten liegen zwischen P1 und P4,
- Aussagen sind auf die Packung begrenzt,
- Längen und Anzahl der Vorschläge bleiben im Limit.

Unbekannte Referenzen werden nicht in den Hauptteil übernommen, sondern unter
"Ungeprüfte Aussagen" ausgewiesen.

### Stufe 5 – separater Bericht

Der Review wird als 07_AI_REVIEW.md geschrieben. Der Abschnitt heißt:

"Der SeoBoy KI-Agent hat darüber hinaus folgendes analysiert"

Die deterministischen Berichte 00 bis 06 bleiben inhaltlich unverändert.

## 4. Evidenzpackung

Beispielstruktur:

    {
      "schema_version": "1",
      "project_id": "...",
      "run_id": "...",
      "status": "completed",
      "start_url": "https://example.de/",
      "coverage": {
        "findings": 12,
        "not_checked": 4,
        "pass": 80,
        "actions": 7,
        "urls": 120,
        "requests": 145
      },
      "findings": [
        {
          "id": "f_ab12cd34ef56",
          "rule_id": "LINK_BROKEN",
          "subject_kind": "link",
          "severity": "high",
          "confidence": "confirmed",
          "subcheck": "target_status",
          "url": "/kontakt/",
          "evidence": "HTTP 404 für /leistungen/",
          "action_refs": ["a_1234567890ab"]
        }
      ],
      "actions": [
        {
          "id": "a_1234567890ab",
          "priority": 2,
          "effort": "small",
          "title": "Defekten CTA reparieren",
          "expected_effect": "Weniger verlorene Buchungsanfragen",
          "verification": "CTA erneut prüfen",
          "finding_refs": ["f_ab12cd34ef56"]
        }
      ],
      "data_quality": [
        "GSC-Daten fehlen für 4 wichtige URLs"
      ],
      "truncated": false
    }

IDs sind deterministisch aus Regel plus Subject-Key beziehungsweise Action-Key
abgeleitet. Sie enthalten keinen Zeitstempel.

## 5. KI-Antwortschema

    {
      "overall_assessment": "Kurze Gesamteinordnung",
      "confidence": "low|medium|high",
      "cross_cutting_issues": [
        {
          "title": "...",
          "explanation": "...",
          "evidence_refs": ["f_..."],
          "action_refs": ["a_..."],
          "suggested_priority": 1
        }
      ],
      "priority_adjustments": [
        {
          "action_ref": "a_...",
          "current_priority": 3,
          "suggested_priority": 2,
          "reason": "...",
          "confidence": "low|medium|high"
        }
      ],
      "data_quality_issues": [
        {
          "issue": "...",
          "impact": "...",
          "evidence_refs": []
        }
      ],
      "additional_analyses": [
        {
          "question": "...",
          "why": "...",
          "suggested_check": "...",
          "priority": 3
        }
      ],
      "limitations": ["..."]
    }

Die Antwort wird auf maximal 10 Cross-Cutting-Issues, 10 Prioritätsvorschläge,
10 Datenqualitätsfragen und 10 zusätzliche Analysen begrenzt.

## 6. Effizienz

- Ein Aufruf pro Lauf, nicht ein Aufruf pro Befund.
- Standardmodell: deepseek-flash, Thinking disabled, Effort none, max_tokens 4096.
- Optional: deepseek-v4-pro oder höhere Reasoning-Stufen über
  SEOBOY_AI_REVIEW_THINKING und SEOBOY_AI_REVIEW_REASONING_EFFORT.
- Reasoning bleibt bei der strukturierten Review standardmäßig aus, weil JSON-Zuverlässigkeit
  und Kosten wichtiger sind als maximale Denktiefe.
- Standardbudget: 0,25 USD pro Review.
- Harte Grenzen: 40 Befunde, 25 Maßnahmen, 60.000 Zeichen Packung.
- Cache-Schlüssel: SHA-256 aus Packung, Modell, Prompt-Version und Schema-Version.
- Cache-Ablage: lokaler Datenbankordner unter ai_review_cache; nicht versioniert.
- Cache-Treffer kosten keinen API-Aufruf; --refresh erzwingt einen neuen Aufruf.
- Kein Retry bei Fehlern; ein zweiter Aufruf nur bewusst über --refresh.
- Keine Websuche:Review nutzt nur lokale Audit-Evidenz.

## 7. CLI und Integration

Neuer Befehl:

    seoboy ai-review --run <lauf-id> --config <seoboy.yaml>

Optionen:

- --model deepseek-flash|deepseek-v4-pro
- --max-findings 40
- --max-actions 25
- --max-tokens 4096
- --budget-usd 0.25
- --no-cache
- --refresh
- --dry-run

Optional beim Lauf:

    seoboy run --ai-review

Der Review ist opt-in, weil er einen externen API-Aufruf und Kosten verursacht.
Schlägt der Review fehl, bleibt der deterministische Lauf gültig; der Fehler wird
als Warnung ausgegeben.

## 8. Bericht

07_AI_REVIEW.md enthält:

1. Advisory-Hinweis und Modell-/Kostenmetadaten,
2. "Der SeoBoy KI-Agent hat darüber hinaus folgendes analysiert",
3. Gesamteinordnung,
4. übergreifende Zusammenhänge,
5. Prioritätsvorschläge mit aktueller und vorgeschlagener Priorität,
6. Datenqualitätsfragen,
7. zusätzliche Analysen,
8. ungeprüfte oder verworfene Aussagen,
9. Grenzen und Cache-Status.

Rohdaten: raw_data/ai_review.json und raw_data/ai_review_suggestions.csv.

## 9. Sicherheit

- gleiche Host-Allowlist wie GEO-Sampling: nur api.deepseek.com,
- keine Redirects,
- keine Shell, kein Browser, keine Website-Änderung,
- keine Datenbankmutation,
- Ausgabe nur in den bestehenden Report-Ordner,
- API-Key nur aus .env/Umgebung, nie im Bericht,
- Prompt- und Antwortgrößen begrenzt,
- Markdown- und CSV-Injektion wird bereinigt.

## 10. Akzeptanzkriterien

1. Ein Lauf mit Befunden erzeugt 07_AI_REVIEW.md und JSON/CSV.
2. Der Bericht enthält den geforderten KI-Abschnitt.
3. Erfundene Referenzen erscheinen nicht als bestätigte Aussage.
4. Ein Cache-Treffer erzeugt keinen zweiten API-Aufruf.
5. Ein nicht erreichbarer oder fehlerhafter KI-Aufruf lässt den Audit unverändert.
6. Deterministische Prioritäten werden nicht automatisch geändert.
7. Ohne API-Key bleibt der Befehl mit klarer Meldung stehen.
8. Alle Tests laufen ohne Netzwerk.

## 11. Offene Entscheidungen

- Ob eine spätere Version bestätigte Prioritätsvorschläge auf Knopfdruck übernehmen darf.
- Ob GSC-Suchanfragen optional und redigiert in die Packung dürfen.
- Ob ein zweiter Review-Pass nur für als kritisch markierte Befunde sinnvoll ist.
