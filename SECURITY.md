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
