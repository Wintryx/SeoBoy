# Security Policy

## Grundsatz

SeoBoy ist ein öffentliches Repository. Es enthält keine API-Keys, OAuth-Tokens,
Service-Account-Schlüssel, Kunden-URLs oder lokalen Auditdaten.

## Secrets

- Keys werden ausschließlich über Umgebungsvariablen oder lokale, ignorierte Dateien
  bereitgestellt.
- .env, local/, secrets/, credentials*, *.pem, *.key und OAuth-/Service-Account-JSONs
  sind in .gitignore ausgeschlossen.
- Vor jedem Commit und in CI läuft scripts/check_secrets.py über Arbeitsbaum, Index
  und die vollständige Git-Historie.
- scripts/install_hooks.ps1 aktiviert pre-commit und pre-push lokal.
- Ein Treffer lässt den Build fehlschlagen. Es wird nur Datei und Musterkategorie
  ausgegeben, nie der geheime Wert.

## KI-Agent: GEO-Sampling

Der DeepSeek-Adapter ist bewusst kein autonomer Agent. Seine Berechtigungen sind:

| Erlaubt | Nicht erlaubt |
| --- | --- |
| Prompt-YAML lesen | Beliebige Dateien oder Secrets lesen |
| HTTPS-POST an api.deepseek.com | Andere Hosts, HTTP oder Redirects |
| Einen neuen Report-Ordner schreiben | Fremde Verzeichnisse überschreiben |
| Antworten als Daten auswerten | Antworten ausführen oder als Anweisung befolgen |
| Websuche des Anbieters nutzen | Lokale Shell, Browser oder Website ändern |

Zusätzliche Grenzen:

- maximal 50 Prompts, je 4.000 Zeichen,
- Modell-Allowlist: deepseek-flash und deepseek-v4-pro,
- maximal 8.192 Output-Tokens und 1,00 USD Standardbudget,
- Budgetprüfung vor jedem Aufruf und Stopp nach jeder tatsächlichen Nutzung,
- maximal 5 MB API-Antwort,
- Ausgabeordner darf keine fremden Dateien oder Symlinks enthalten,
- Markdown-/CSV-Zellen werden gegen Tabellen- und Formelinjektion bereinigt,
- API-Fehler werden von Steuerzeichen bereinigt und auf 300 Zeichen begrenzt.

Residualrisiko: Der DeepSeek-Key ist kontobezogen und kann bis zum Anbieterlimit
Kosten verursachen. Für den Agenten sollte ein eigener Key mit Ausgabenlimit verwendet
werden. Der Anbieter sieht die übermittelten Prompts; dort niemals Secrets oder
personenbezogene Daten eintragen.

## KI-Agent: Audit-Review

Die beratende KI-Review hat zusätzlich nur diese Fähigkeiten:

| Erlaubt | Nicht erlaubt |
| --- | --- |
| Gespeicherte Audit-Evidenz als kompakte JSON-Packung lesen | Website crawlen oder HTML lesen |
| Einen HTTPS-POST an api.deepseek.com senden | Websuche oder andere Hosts |
| 07_AI_REVIEW.md und Cache schreiben | Befunde, Maßnahmen oder DB verändern |
| Vorschläge und Referenzen validieren | Modellantworten ausführen |

Zusätzliche Grenzen:

- ein Aufruf pro Lauf, keine automatische Wiederholung,
- maximal 40 Befunde und 25 Maßnahmen in der Packung,
- maximal 60.000 Zeichen,
- Standardbudget 0,25 USD,
- Modell-Allowlist und Host-Allowlist wie beim GEO-Sampling,
- keine vollständigen GSC-Zeilen; Query-Namen nur aus vorhandenen Befunden/Evidenz,
- Cache nur lokal unter dem Datenbankordner, nicht versioniert,
- unbekannte Befund-/Maßnahmen-Referenzen werden als ungeprüft ausgewiesen.

## Wenn ein Key versehentlich committed wurde

1. Key sofort beim Anbieter widerrufen und ersetzen.
2. Den Commit nicht nur lokal löschen, sondern die Historie bereinigen.
3. Force-Push nur nach Abstimmung, weil er die Historie anderer Klone verändert.
4. GitHub Secret Scanning und ggf. den Anbieter informieren.
5. Vor dem erneuten Push den Scanner über die komplette Historie laufen lassen.

## Schwachstellen melden

Bitte Sicherheitslücken nicht öffentlich als Issue mit ausnutzbaren Details melden.
Kontakt: info@wintryx.de. Bitte Reproduktionsschritte, betroffene Version und mögliche
Auswirkungen angeben.

## Unterstützte Versionen

Sicherheitsfixes werden für die aktuelle main-Version bereitgestellt.
