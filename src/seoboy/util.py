"""Kleine, abhängigkeitsfreie Hilfsfunktionen für SeoBoy."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import re
from typing import Any, Iterable

UTC = timezone.utc

# Deutsche Zeitangaben werden ohne tzdata-Paket berechnet. Die EU-Sommerzeit
# beginnt am letzten Sonntag im März und endet am letzten Sonntag im Oktober,
# jeweils um 01:00 UTC.
_CEST = timezone(timedelta(hours=2), "MESZ")
_CET = timezone(timedelta(hours=1), "MEZ")


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_utc(moment: datetime | None = None) -> str:
    """Einheitliches UTC-Format mit Sekunden, z. B. 2026-11-20T08:32:00Z."""
    value = moment or utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _last_sunday(year: int, month: int) -> date:
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() + 1) % 7)


def _summer_time_bounds(year: int) -> tuple[datetime, datetime]:
    start = datetime.combine(_last_sunday(year, 3), datetime.min.time(), UTC) + timedelta(hours=1)
    end = datetime.combine(_last_sunday(year, 10), datetime.min.time(), UTC) + timedelta(hours=1)
    return start, end


def berlin_time(moment: datetime) -> tuple[datetime, str]:
    """Liefert Berliner Lokalzeit und die deutsche Abkürzung (MEZ/MESZ)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    moment = moment.astimezone(UTC)
    start, end = _summer_time_bounds(moment.year)
    if start <= moment < end:
        return moment.astimezone(_CEST), "MESZ"
    return moment.astimezone(_CET), "MEZ"


def format_local(moment: datetime | None) -> str:
    """Format wie im Reporting-Beispiel: 20.11.2026 um 09:32 Uhr MEZ."""
    if moment is None:
        return "unbekannt"
    local, suffix = berlin_time(moment)
    return f"{local:%d.%m.%Y} um {local:%H:%M} Uhr {suffix}"


def format_local_date(moment: datetime | None) -> str:
    if moment is None:
        return "unbekannt"
    local, _ = berlin_time(moment)
    return f"{local:%d.%m.%Y}"


def local_now_date() -> date:
    local, _ = berlin_time(utc_now())
    return local.date()


def local_date_from_utc(text: str) -> date:
    local, _ = berlin_time(parse_utc(text))
    return local.date()


def stable_json(value: Any) -> str:
    """Kompakte, sortierte JSON-Darstellung für Schlüssel und Hashes."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(stable_json(value))


def read_json(path) -> Any:
    from pathlib import Path

    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value: Any) -> None:
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def normalize_whitespace(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def parse_retry_after(value: str | None, now: datetime) -> int | None:
    """Retry-After als Sekunden; unterstützt Sekunden und HTTP-Datum."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return max(0, int(value))
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0, int((moment - now).total_seconds()))


def excel_safe(value: Any) -> Any:
    """Schützt Textwerte vor Formelinterpretation in Tabellenprogrammen.

    Der unveränderte Wert bleibt in SQLite gespeichert; nur der Export erhält
    ein führendes Apostroph.
    """
    if not isinstance(value, str) or not value:
        return value
    if value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def truncate(text: str, limit: int = 300) -> str:
    text = normalize_whitespace(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def unique(items: Iterable[Any]) -> list[Any]:
    """Reihenfolgeerhaltende Eindeutigkeit für hashbare Werte."""
    seen: set[Any] = set()
    result: list[Any] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
