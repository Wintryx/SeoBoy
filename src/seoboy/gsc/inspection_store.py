"""Persistence and reporting for GSC URL Inspection results."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from seoboy.analysis.audit_data import RunData
from seoboy.shared.urls import relative_url
from seoboy.shared.util import excel_safe


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _index(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("indexStatusResult")
    return value if isinstance(value, dict) else {}


def store_inspection(
    connection: sqlite3.Connection,
    run_id: str,
    url_id: int,
    property_name: str,
    inspection_url: str,
    result: dict[str, Any],
    *,
    language_code: str = "de-DE",
    error_code: str | None = None,
    inspected_at: str | None = None,
) -> None:
    index = _index(result)
    timestamp = inspected_at or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    raw = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    connection.execute(
        """
        INSERT INTO url_inspections (
            run_id, url_id, property, inspection_url, language_code,
            inspected_at, verdict, coverage_state, indexing_state,
            robots_txt_state, page_fetch_state, google_canonical,
            user_canonical, last_crawl_time, error_code, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, url_id) DO UPDATE SET
            property = excluded.property,
            inspection_url = excluded.inspection_url,
            language_code = excluded.language_code,
            inspected_at = excluded.inspected_at,
            verdict = excluded.verdict,
            coverage_state = excluded.coverage_state,
            indexing_state = excluded.indexing_state,
            robots_txt_state = excluded.robots_txt_state,
            page_fetch_state = excluded.page_fetch_state,
            google_canonical = excluded.google_canonical,
            user_canonical = excluded.user_canonical,
            last_crawl_time = excluded.last_crawl_time,
            error_code = excluded.error_code,
            raw_json = excluded.raw_json
        """,
        (
            run_id,
            url_id,
            property_name,
            inspection_url,
            language_code,
            timestamp,
            _text(result.get("verdict") or index.get("verdict")),
            _text(index.get("coverageState")),
            _text(index.get("indexingState")),
            _text(index.get("robotsTxtState")),
            _text(index.get("pageFetchState")),
            _text(index.get("googleCanonical")),
            _text(index.get("userCanonical")),
            _text(index.get("lastCrawlTime")),
            error_code,
            raw,
        ),
    )


def store_error(
    connection: sqlite3.Connection,
    run_id: str,
    url_id: int,
    property_name: str,
    inspection_url: str,
    error_code: str,
    *,
    language_code: str = "de-DE",
) -> None:
    store_inspection(
        connection,
        run_id,
        url_id,
        property_name,
        inspection_url,
        {},
        language_code=language_code,
        error_code=error_code,
    )


def load_inspections(
    connection: sqlite3.Connection, run_id: str
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT i.*, u.normalized_url AS url
        FROM url_inspections i
        JOIN urls u ON u.url_id = i.url_id
        WHERE i.run_id = ?
        ORDER BY i.inspected_at, u.normalized_url
        """,
        (run_id,),
    )
    return [dict(row) for row in rows]


def select_targets(
    data: RunData, limit: int = 10
) -> list[tuple[int, str]]:
    if limit < 1:
        return []
    limit = min(limit, 100)
    candidates: list[tuple[int, int, int, str, int]] = []
    for url_id in data.page_url_ids:
        info = data.urls.get(url_id)
        if info is None:
            continue
        observation = data.observation(url_id)
        attempt = data.final_attempt(url_id)
        if observation is None or attempt is None:
            continue
        if attempt.status_code is None or not 200 <= attempt.status_code < 300:
            continue
        if info.state != "finished":
            continue
        business_rank = {"high": 0, "normal": 1, "low": 2}.get(
            info.business_value, 1
        )
        depth = info.click_depth if info.click_depth is not None else 999
        candidates.append(
            (business_rank, depth, url_id, info.url, url_id)
        )
    candidates.sort(key=lambda item: (item[0], item[1], item[3]))
    return [(item[2], item[3]) for item in candidates[:limit]]


def _display(data: RunData, url: str) -> str:
    return relative_url(url, data.config.allowed_hosts)


def _md(value: Any) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def _canonical_mismatch(row: dict[str, Any]) -> bool:
    google = row.get("google_canonical")
    user = row.get("user_canonical")
    return bool(google and user and google.rstrip("/") != user.rstrip("/"))


def _write_csv(path: Path, header: list[str], rows: Iterable[Iterable[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow([excel_safe(value) for value in row])


def write_url_inspection_report(
    folder: Path,
    data: RunData,
    inspections: list[dict[str, Any]],
) -> None:
    if not inspections:
        for stale in (
            folder / "06_URL_INSPECTION.md",
            folder / "raw_data" / "url_inspections.csv",
        ):
            if stale.exists():
                stale.unlink()
        return
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / "raw_data"
    raw.mkdir(parents=True, exist_ok=True)
    errors = sum(1 for row in inspections if row.get("error_code"))
    passed = sum(1 for row in inspections if row.get("verdict") == "PASS")
    mismatches = sum(1 for row in inspections if _canonical_mismatch(row))
    lines = [
        "# SeoBoy – URL Inspection",
        "",
        f"**Lauf:** {data.run_id}",
        "",
        "Die URL Inspection zeigt Googles gespeicherten Indexstand. Sie ist eine "
        "Momentaufnahme und ersetzt keinen Live-Abruf der Seite.",
        "",
        "## Übersicht",
        "",
        "| Kennzahl | Wert |",
        "| --- | ---: |",
        f"| geprüfte URLs | {len(inspections)} |",
        f"| Verdict PASS | {passed} |",
        f"| Fehler | {errors} |",
        f"| Canonical-Abweichung | {mismatches} |",
        "",
        "## Ergebnisse",
        "",
        "| Seite | Verdict | Coverage | Indexing | Canonical (Google) | Canonical (Seite) | Letzter Crawl | Fehler |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in inspections:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(_display(data, row["url"])),
                    _md(row.get("verdict") or "–"),
                    _md(row.get("coverage_state") or "–"),
                    _md(row.get("indexing_state") or "–"),
                    _md(row.get("google_canonical") or "–"),
                    _md(row.get("user_canonical") or "–"),
                    _md(row.get("last_crawl_time") or "–"),
                    _md(row.get("error_code") or "–"),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Canonical-Hinweis",
            "",
            "Eine Abweichung zwischen Google- und Seiten-Canonical ist ein Prüfhinweis, "
            "kein automatischer Fehler. Sie kann durch Redirects, Canonical-Tags, "
            "Sitemaps oder die Auswahl einer anderen Variante entstehen.",
            "",
            "## Rohdaten",
            "",
            "- [URL-Inspection-Zeilen](raw_data/url_inspections.csv)",
            "",
        ]
    )
    (folder / "06_URL_INSPECTION.md").write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n"
    )
    _write_csv(
        raw / "url_inspections.csv",
        [
            "url",
            "property",
            "inspected_at",
            "verdict",
            "coverage_state",
            "indexing_state",
            "robots_txt_state",
            "page_fetch_state",
            "google_canonical",
            "user_canonical",
            "last_crawl_time",
            "error_code",
        ],
        [
            [
                row["url"],
                row["property"],
                row["inspected_at"],
                row.get("verdict") or "",
                row.get("coverage_state") or "",
                row.get("indexing_state") or "",
                row.get("robots_txt_state") or "",
                row.get("page_fetch_state") or "",
                row.get("google_canonical") or "",
                row.get("user_canonical") or "",
                row.get("last_crawl_time") or "",
                row.get("error_code") or "",
            ]
            for row in inspections
        ],
    )
