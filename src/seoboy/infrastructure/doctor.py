"""Environment diagnostics for standalone SeoBoy usage."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

from seoboy.infrastructure.config import ConfigError, load_config
from seoboy.infrastructure.database import MIN_SQLITE_VERSION, schema_version
from seoboy.shared.version import __version__


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    version: str
    checks: list[Check]

    @property
    def errors(self) -> list[Check]:
        return [item for item in self.checks if item.status == "error"]

    @property
    def warnings(self) -> list[Check]:
        return [item for item in self.checks if item.status == "warning"]


def _check(name: str, status: str, detail: str) -> Check:
    return Check(name=name, status=status, detail=detail)


def _config_checks(config_path: Path) -> list[Check]:
    checks: list[Check] = []
    if not config_path.is_file():
        checks.append(
            _check(
                "Projektkonfiguration",
                "warning",
                f"{config_path} fehlt; mit 'seoboy init --url ...' anlegen.",
            )
        )
        return checks
    try:
        config = load_config(config_path)
    except (ConfigError, OSError, ValueError) as error:
        checks.append(_check("Projektkonfiguration", "error", str(error)))
        return checks
    checks.append(
        _check(
            "Projektkonfiguration",
            "ok",
            f"{config.project_id}: {config.start_url}",
        )
    )
    database = config.database
    directory = database.parent
    if not directory.exists():
        checks.append(
            _check(
                "Datenbankverzeichnis",
                "warning",
                f"{directory} fehlt; wird bei 'seoboy migrate' angelegt.",
            )
        )
    elif not directory.is_dir():
        checks.append(
            _check("Datenbankverzeichnis", "error", f"{directory} ist kein Verzeichnis.")
        )
    elif not os.access(directory, os.W_OK):
        checks.append(
            _check("Datenbankverzeichnis", "error", f"{directory} ist nicht beschreibbar.")
        )
    else:
        checks.append(_check("Datenbankverzeichnis", "ok", str(directory)))
    if database.is_file():
        try:
            connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                version = schema_version(connection)
            finally:
                connection.close()
            if version == 0:
                checks.append(
                    _check("Datenbankschema", "warning", "noch nicht migriert")
                )
            else:
                checks.append(
                    _check("Datenbankschema", "ok", f"Version {version}")
                )
        except sqlite3.Error as error:
            checks.append(_check("Datenbankschema", "error", str(error)))
    else:
        checks.append(
            _check(
                "Datenbankschema",
                "warning",
                "Datenbank fehlt; wird bei 'seoboy migrate' angelegt.",
            )
        )
    reports = config.reports_dir
    if not reports.exists():
        checks.append(
            _check("Berichtsverzeichnis", "warning", f"{reports} fehlt; wird angelegt.")
        )
    elif not reports.is_dir():
        checks.append(
            _check("Berichtsverzeichnis", "error", f"{reports} ist kein Verzeichnis.")
        )
    elif not os.access(reports, os.W_OK):
        checks.append(
            _check("Berichtsverzeichnis", "error", f"{reports} ist nicht beschreibbar.")
        )
    else:
        checks.append(_check("Berichtsverzeichnis", "ok", str(reports)))
    return checks


def _credential_check() -> Check:
    raw = os.environ.get("SEOBOY_GSC_CREDENTIALS")
    if not raw:
        return _check(
            "GSC-API-Zugang",
            "warning",
            "nicht konfiguriert; GSC-API und URL Inspection sind optional.",
        )
    path = Path(raw).expanduser()
    if not path.is_file():
        return _check("GSC-API-Zugang", "warning", f"{path} fehlt.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return _check("GSC-API-Zugang", "warning", f"nicht lesbar: {error}")
    if isinstance(payload, dict) and (
        payload.get("type") == "service_account"
        or (payload.get("client_email") and payload.get("private_key"))
    ):
        return _check("GSC-API-Zugang", "ok", f"{path} (Service-Account)")
    required = {"client_id", "client_secret", "refresh_token"}
    if not isinstance(payload, dict) or not required.issubset(payload):
        return _check(
            "GSC-API-Zugang",
            "warning",
            "weder Service-Account noch client_id/client_secret/refresh_token vorhanden.",
        )
    return _check("GSC-API-Zugang", "ok", f"{path} (OAuth)")


def run_doctor(config_path: Path | str) -> DoctorReport:
    checks: list[Check] = []
    if sys.version_info >= (3, 11):
        checks.append(
            _check("Python", "ok", f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
        )
    else:
        checks.append(
            _check("Python", "error", "Python 3.11 oder neuer wird benötigt.")
        )
    if sqlite3.sqlite_version_info >= MIN_SQLITE_VERSION:
        checks.append(_check("SQLite", "ok", sqlite3.sqlite_version))
    else:
        checks.append(
            _check("SQLite", "error", f"{sqlite3.sqlite_version} ist zu alt.")
        )
    try:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("SELECT json_valid('{}')").fetchone()
        finally:
            connection.close()
        checks.append(_check("SQLite JSON", "ok", "json_valid verfügbar"))
    except sqlite3.Error as error:
        checks.append(_check("SQLite JSON", "error", str(error)))
    if importlib.util.find_spec("yaml") is not None:
        checks.append(_check("PyYAML", "ok", "installiert"))
    else:
        checks.append(_check("PyYAML", "error", "PyYAML fehlt."))
    git = shutil.which("git")
    checks.append(
        _check(
            "Git",
            "ok" if git else "warning",
            git or "nicht gefunden; nur der CLI-Updater benötigt Git.",
        )
    )
    playwright = importlib.util.find_spec("playwright") is not None
    checks.append(
        _check(
            "Playwright",
            "ok" if playwright else "warning",
            "installiert" if playwright else "optional; nur 'seoboy render' benötigt Playwright.",
        )
    )
    checks.extend(_config_checks(Path(config_path).expanduser()))
    checks.append(_credential_check())
    return DoctorReport(version=__version__, checks=checks)
