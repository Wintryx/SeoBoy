"""Optionales Laden einer lokalen .env-Datei ohne Zusatzabhängigkeit."""

from __future__ import annotations

import os
from pathlib import Path
import re

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def find_env_file() -> Path | None:
    """Bevorzugt SEOBOY_ENV_FILE, sonst .env im Arbeits- oder Projektverzeichnis."""
    explicit = os.environ.get("SEOBOY_ENV_FILE")
    if explicit:
        candidate = Path(explicit).expanduser()
        return candidate if candidate.is_file() else None
    for candidate in (
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ):
        if candidate.is_file():
            return candidate
    return None


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not _KEY.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def load_env(path: Path | str | None = None) -> dict[str, str]:
    """Lädt die .env-Datei, ohne bereits gesetzte Umgebungsvariablen zu überschreiben."""
    env_path = Path(path) if path is not None else find_env_file()
    if env_path is None or not env_path.is_file():
        return {}
    try:
        text = env_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return {}
    loaded: dict[str, str] = {}
    for key, value in parse_env(text).items():
        if key in os.environ:
            continue
        os.environ[key] = value
        loaded[key] = value
    return loaded
