"""Validated, idempotent CSV import for local ranking snapshots."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Iterable

from seoboy.infrastructure.config import ProjectConfig
from seoboy.infrastructure.database import transaction
from seoboy.rankings.config import KeywordProfile
from seoboy.shared.urls import normalize_url
from seoboy.shared.util import iso_utc


class RankingImportError(ValueError):
    """The ranking import is invalid or conflicts with stored data."""


@dataclass(frozen=True)
class RankingImportSummary:
    snapshots: int
    snapshots_skipped: int
    results: int
    keywords: int


SNAPSHOT_FIELDS = (
    "snapshot_id",
    "keyword_id",
    "observed_at",
    "source",
    "engine",
    "market",
    "language",
    "location_key",
    "device",
    "result_type",
    "depth",
    "status",
)
RESULT_FIELDS = ("snapshot_id", "position", "url", "profile_id", "domain", "title")
STATUSES = {"ok", "no_match", "failed", "blocked"}


def _read(path: Path, fields: Iterable[str]) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            headers = reader.fieldnames or []
            missing = [field for field in fields if field not in headers]
            if missing:
                raise RankingImportError(
                    f"{path.name}: fehlende Spalten: {', '.join(missing)}"
                )
            rows = []
            for line, row in enumerate(reader, start=2):
                item = {key: (value or "").strip() for key, value in row.items()}
                if not any(item.values()):
                    continue
                item["_line"] = str(line)
                rows.append(item)
            return rows
    except OSError as error:
        raise RankingImportError(f"CSV nicht lesbar: {path}") from error


def _timestamp(value: str, field: str, line: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise RankingImportError(f"Zeile {line}: {field} ist kein ISO-Zeitstempel.") from None
    if parsed.tzinfo is None:
        raise RankingImportError(f"Zeile {line}: {field} braucht eine Zeitzone.")
    return value


def _dimension(
    row: dict[str, str], profile: KeywordProfile, field: str
) -> str:
    value = row.get(field, "").strip()
    expected = str(getattr(profile, field))
    if value and value != expected:
        raise RankingImportError(
            f"Zeile {row['_line']}: {field} passt nicht zum Keyword-Profil "
            f"({value!r} statt {expected!r})."
        )
    return expected


def import_rankings(
    connection: Any,
    config: ProjectConfig,
    profiles: tuple[KeywordProfile, ...],
    csv_path: Path,
    results_path: Path | None = None,
) -> RankingImportSummary:
    by_id = {profile.id: profile for profile in profiles}
    rows = _read(Path(csv_path), SNAPSHOT_FIELDS)
    if not rows:
        raise RankingImportError("Die Snapshot-Datei enthält keine Zeilen.")

    snapshots: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row["snapshot_id"]:
            raise RankingImportError(f"Zeile {row['_line']}: snapshot_id fehlt.")
        if row["snapshot_id"] in snapshots:
            raise RankingImportError(
                f"Zeile {row['_line']}: snapshot_id {row['snapshot_id']} ist doppelt."
            )
        profile = by_id.get(row["keyword_id"])
        if profile is None:
            raise RankingImportError(
                f"Zeile {row['_line']}: unbekannte keyword_id {row['keyword_id']!r}."
            )
        status = row.get("status") or "ok"
        if status not in STATUSES:
            raise RankingImportError(
                f"Zeile {row['_line']}: status muss {', '.join(sorted(STATUSES))} sein."
            )
        try:
            depth = int(row.get("depth") or "0")
        except ValueError:
            raise RankingImportError(f"Zeile {row['_line']}: depth ist keine Zahl.") from None
        if depth < 1 or depth > 1000:
            raise RankingImportError(f"Zeile {row['_line']}: depth muss 1 bis 1000 sein.")
        snapshots[row["snapshot_id"]] = {
            "snapshot_id": row["snapshot_id"],
            "keyword_id": profile.id,
            "observed_at": _timestamp(row.get("observed_at", ""), "observed_at", row["_line"]),
            "source": row.get("source") or "import",
            "engine": _dimension(row, profile, "engine"),
            "market": _dimension(row, profile, "market"),
            "language": _dimension(row, profile, "language"),
            "location_key": _dimension(row, profile, "location_key"),
            "device": _dimension(row, profile, "device"),
            "result_type": _dimension(row, profile, "result_type"),
            "depth": depth,
            "status": status,
        }

    results: dict[str, list[dict[str, Any]]] = {}
    if results_path is not None:
        for row in _read(Path(results_path), RESULT_FIELDS):
            snapshot_id = row["snapshot_id"]
            if snapshot_id not in snapshots:
                raise RankingImportError(
                    f"Zeile {row['_line']}: unbekannte snapshot_id {snapshot_id!r}."
                )
            try:
                position = int(row["position"])
            except ValueError:
                raise RankingImportError(
                    f"Zeile {row['_line']}: position ist keine Zahl."
                ) from None
            if position < 1:
                raise RankingImportError(f"Zeile {row['_line']}: position muss positiv sein.")
            try:
                url = normalize_url(row["url"]).url
            except ValueError as error:
                raise RankingImportError(
                    f"Zeile {row['_line']}: ungültige URL: {error}"
                ) from None
            item = {
                "snapshot_id": snapshot_id,
                "position": position,
                "url": url,
                "profile_id": row.get("profile_id", ""),
                "domain": row.get("domain", ""),
                "title": row.get("title", ""),
            }
            results.setdefault(snapshot_id, []).append(item)
        for snapshot_id, items in results.items():
            positions = [item["position"] for item in items]
            if len(positions) != len(set(positions)):
                raise RankingImportError(
                    f"Snapshot {snapshot_id}: Positionen sind nicht eindeutig."
                )
            items.sort(key=lambda item: item["position"])

    imported = 0
    skipped = 0
    result_count = 0
    with transaction(connection):
        now = iso_utc()
        for profile in profiles:
            connection.execute(
                "INSERT INTO ranking_keywords(project_id, keyword_id, query, intent, tags_json, "
                "market, language, location_key, engine, device, result_type, expected_target, "
                "target_active, business_value, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(project_id, keyword_id) DO UPDATE SET query=excluded.query, "
                "intent=excluded.intent, tags_json=excluded.tags_json, market=excluded.market, "
                "language=excluded.language, location_key=excluded.location_key, "
                "engine=excluded.engine, device=excluded.device, "
                "result_type=excluded.result_type, expected_target=excluded.expected_target, "
                "target_active=excluded.target_active, business_value=excluded.business_value, "
                "updated_at=excluded.updated_at",
                (
                    config.project_id,
                    profile.id,
                    profile.query,
                    profile.intent,
                    json.dumps(list(profile.tags), ensure_ascii=False),
                    profile.market,
                    profile.language,
                    profile.location_key,
                    profile.engine,
                    profile.device,
                    profile.result_type,
                    profile.expected_target,
                    1 if profile.target_active else 0,
                    profile.business_value,
                    now,
                ),
            )
        for snapshot_id, item in snapshots.items():
            existing = connection.execute(
                "SELECT * FROM ranking_snapshots WHERE project_id = ? AND snapshot_id = ?",
                (config.project_id, snapshot_id),
            ).fetchone()
            if existing is not None:
                stored_results = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT position, url, profile_id, domain, title FROM ranking_results "
                        "WHERE project_id = ? AND snapshot_id = ? ORDER BY position",
                        (config.project_id, snapshot_id),
                    )
                ]
                expected_results = [
                    {key: value for key, value in row.items() if key != "snapshot_id"}
                    for row in results.get(snapshot_id, [])
                ]
                comparable = {key: item[key] for key in SNAPSHOT_FIELDS}
                stored = {key: existing[key] for key in SNAPSHOT_FIELDS if key in existing.keys()}
                if comparable != stored or stored_results != expected_results:
                    raise RankingImportError(
                        f"Snapshot {snapshot_id} existiert bereits mit anderen Daten."
                    )
                skipped += 1
                continue
            connection.execute(
                "INSERT INTO ranking_snapshots(project_id, snapshot_id, keyword_id, observed_at, "
                "source, engine, market, language, location_key, device, result_type, depth, "
                "status, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    config.project_id,
                    snapshot_id,
                    item["keyword_id"],
                    item["observed_at"],
                    item["source"],
                    item["engine"],
                    item["market"],
                    item["language"],
                    item["location_key"],
                    item["device"],
                    item["result_type"],
                    item["depth"],
                    item["status"],
                    now,
                ),
            )
            for result in results.get(snapshot_id, []):
                connection.execute(
                    "INSERT INTO ranking_results(project_id, snapshot_id, position, url, "
                    "profile_id, domain, title) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        config.project_id,
                        snapshot_id,
                        result["position"],
                        result["url"],
                        result["profile_id"],
                        result["domain"],
                        result["title"],
                    ),
                )
                result_count += 1
            imported += 1
    return RankingImportSummary(
        snapshots=imported,
        snapshots_skipped=skipped,
        results=result_count,
        keywords=len(profiles),
    )
