"""Validated, deduplicated backlink CSV import."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from seoboy.infrastructure.config import ProjectConfig
from seoboy.infrastructure.database import transaction
from seoboy.shared.urls import normalize_url
from seoboy.shared.util import iso_utc


class BacklinkImportError(ValueError):
    """The backlink import is invalid."""


@dataclass(frozen=True)
class BacklinkImportSummary:
    observations: int
    skipped: int


FIELDS = (
    "source_url",
    "target_url",
    "dataset_source",
    "snapshot_id",
    "observed_at",
    "anchor_text",
    "rel",
    "first_seen_by_provider",
    "last_seen_by_provider",
    "entity_role",
    "review_state",
    "review_note",
)
ROLES = {"own", "competitor", "unknown"}
REVIEW_STATES = {"open", "reviewed", "ignored"}


def _timestamp(value: str, line: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise BacklinkImportError(
            f"Zeile {line}: observed_at ist kein ISO-Zeitstempel."
        ) from None
    if parsed.tzinfo is None:
        raise BacklinkImportError(f"Zeile {line}: observed_at braucht eine Zeitzone.")
    return value


def _rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            headers = reader.fieldnames or []
            missing = [field for field in FIELDS if field not in headers]
            if missing:
                raise BacklinkImportError(
                    f"{path.name}: fehlende Spalten: {', '.join(missing)}"
                )
            result = []
            for line, row in enumerate(reader, start=2):
                item = {key: (value or "").strip() for key, value in row.items()}
                if not any(item.values()):
                    continue
                item["_line"] = str(line)
                result.append(item)
            return result
    except OSError as error:
        raise BacklinkImportError(f"CSV nicht lesbar: {path}") from error


def import_backlinks(
    connection: Any, config: ProjectConfig, csv_path: Path
) -> BacklinkImportSummary:
    rows = _rows(Path(csv_path))
    if not rows:
        raise BacklinkImportError("Die Backlink-Datei enthält keine Zeilen.")
    imported = 0
    skipped = 0
    with transaction(connection):
        now = iso_utc()
        for row in rows:
            if not row["source_url"] or not row["target_url"]:
                raise BacklinkImportError(
                    f"Zeile {row['_line']}: source_url und target_url sind Pflicht."
                )
            try:
                source = normalize_url(row["source_url"]).url
                target = normalize_url(row["target_url"]).url
            except ValueError as error:
                raise BacklinkImportError(
                    f"Zeile {row['_line']}: ungültige URL: {error}"
                ) from None
            if not row["dataset_source"] or not row["snapshot_id"]:
                raise BacklinkImportError(
                    f"Zeile {row['_line']}: dataset_source und snapshot_id sind Pflicht."
                )
            observed_at = _timestamp(row["observed_at"], row["_line"])
            role = row["entity_role"] or "unknown"
            review_state = row["review_state"] or "open"
            if role not in ROLES:
                raise BacklinkImportError(
                    f"Zeile {row['_line']}: entity_role muss one of {sorted(ROLES)} sein."
                )
            if review_state not in REVIEW_STATES:
                raise BacklinkImportError(
                    f"Zeile {row['_line']}: review_state ist ungültig."
                )
            payload = {
                "source": source,
                "target": target,
                "dataset": row["dataset_source"],
                "snapshot": row["snapshot_id"],
                "observed": observed_at,
                "anchor": row["anchor_text"],
                "rel": row["rel"],
            }
            event_key = hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            cursor = connection.execute(
                "INSERT OR IGNORE INTO backlink_observations(project_id, source_url, "
                "target_url, source_original, target_original, dataset_source, snapshot_id, "
                "observed_at, anchor_text, rel, first_seen_by_provider, "
                "last_seen_by_provider, entity_role, review_state, review_note, event_key, "
                "imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    config.project_id,
                    source,
                    target,
                    row["source_url"],
                    row["target_url"],
                    row["dataset_source"],
                    row["snapshot_id"],
                    observed_at,
                    row["anchor_text"],
                    row["rel"],
                    row["first_seen_by_provider"],
                    row["last_seen_by_provider"],
                    role,
                    review_state,
                    row["review_note"],
                    event_key,
                    now,
                ),
            )
            if cursor.rowcount:
                imported += 1
            else:
                skipped += 1
    return BacklinkImportSummary(observations=imported, skipped=skipped)
