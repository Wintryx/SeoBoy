"""Backlink observations and regional link opportunities."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any

from seoboy.analysis.audit_data import RunData
from seoboy.infrastructure.config import ProjectConfig
from seoboy.shared.util import excel_safe


def _observations(connection: sqlite3.Connection, config: ProjectConfig) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM backlink_observations WHERE project_id = ? "
            "ORDER BY observed_at, source_url, target_url",
            (config.project_id,),
        )
    ]


def _rows_by_snapshot(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = f"{row['dataset_source']}|{row['snapshot_id']}"
        result.setdefault(key, []).append(row)
    return result


def _latest_run(connection: sqlite3.Connection, config: ProjectConfig) -> RunData | None:
    row = connection.execute(
        "SELECT run_id FROM runs WHERE project_id = ? AND mode = 'crawl' "
        "AND status = 'completed' ORDER BY ended_at DESC LIMIT 1",
        (config.project_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        return RunData(connection, config, row["run_id"])
    except (ValueError, sqlite3.Error):
        return None


def _csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(
            [
                "source_url",
                "target_url",
                "dataset_source",
                "snapshot_id",
                "observed_at",
                "anchor_text",
                "rel",
                "entity_role",
                "review_state",
                "review_note",
                "first_seen_by_provider",
                "last_seen_by_provider",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    excel_safe(row["source_url"]),
                    excel_safe(row["target_url"]),
                    excel_safe(row["dataset_source"]),
                    excel_safe(row["snapshot_id"]),
                    row["observed_at"],
                    excel_safe(row["anchor_text"]),
                    excel_safe(row["rel"]),
                    row["entity_role"],
                    row["review_state"],
                    excel_safe(row["review_note"]),
                    row["first_seen_by_provider"],
                    row["last_seen_by_provider"],
                ]
            )


def write_backlink_report(
    connection: sqlite3.Connection,
    config: ProjectConfig,
    out: Path | None = None,
) -> Path:
    folder = out or (config.reports_dir / "backlinks")
    folder.mkdir(parents=True, exist_ok=True)
    rows = _observations(connection, config)
    by_snapshot = _rows_by_snapshot(rows)
    latest_by_source: dict[str, str] = {}
    latest_at: dict[str, str] = {}
    for key, items in by_snapshot.items():
        dataset = key.split("|", 1)[0]
        observed = max(row["observed_at"] for row in items)
        if dataset not in latest_at or observed > latest_at[dataset]:
            latest_at[dataset] = observed
            latest_by_source[dataset] = key
    latest_keys = set(latest_by_source.values())
    latest_pairs: set[tuple[str, str]] = set()
    for key in latest_keys:
        for row in by_snapshot[key]:
            latest_pairs.add((row["source_url"], row["target_url"]))
    earlier_pairs: set[tuple[str, str]] = set()
    for key, items in by_snapshot.items():
        if key in latest_keys:
            continue
        for row in items:
            earlier_pairs.add((row["source_url"], row["target_url"]))
    not_reobserved = earlier_pairs - latest_pairs

    opportunities: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["entity_role"] != "competitor":
            continue
        opportunities.setdefault(row["source_url"], []).append(row)
    regional = [
        (source, items)
        for source, items in opportunities.items()
        if len({row["target_url"] for row in items}) >= 2
    ]

    run = _latest_run(connection, config)
    target_status: dict[str, tuple[int | None, str | None]] = {}
    if run is not None:
        for info in run.urls.values():
            target_status[info.url] = (run.final_status(info.url_id), run.final_error(info.url_id))

    lines = [
        "# SeoBoy – Backlink-Beobachtungen und Linkchancen",
        "",
        f"**Projekt:** {config.project_id}  ",
        f"**Beobachtungen:** {len(rows)} · **Quellen:** {len({row['source_url'] for row in rows})}",
        "",
        "## Verlauf",
        "",
        "| Kennzahl | Wert |",
        "| --- | --- |",
        f"| Beobachtungen gesamt | {len(rows)} |",
        f"| nicht erneut beobachtet | {len(not_reobserved)} |",
        f"| Quellen mit mindestens zwei Wettbewerber-Zielen | {len(regional)} |",
        "",
        "„Nicht erneut beobachtet“ ist keine bestätigte Entfernung. Dafür wäre eine "
        "erfolgreiche Prüfung der Quellseite nötig; diese Stufe führt keine Live-Prüfung aus.",
        "",
        "## Eigene Zielseiten mit Problemen",
        "",
    ]
    problem_rows = []
    for row in rows:
        if row["entity_role"] != "own":
            continue
        status, error = target_status.get(row["target_url"], (None, None))
        if status is not None and 200 <= status < 300:
            continue
        if status is None and error is None:
            continue
        problem_rows.append((row, status, error))
    if problem_rows:
        lines.extend(
            [
                "| Quelle | Ziel | Status | Fehler | Review |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for row, status, error in problem_rows:
            lines.append(
                f"| {row['source_url']} | {row['target_url']} | "
                f"{status if status is not None else '–'} | {error or '–'} | "
                f"{row['review_state']} |"
            )
    else:
        lines.append("Keine bekannten Zielprobleme aus dem letzten Crawl.")

    lines.extend(["", "## Regionale Linkchancen", ""])
    if regional:
        for source, items in regional[:20]:
            targets = ", ".join(sorted({row["target_url"] for row in items}))
            lines.append(f"- **{source}** verlinkt: {targets}")
    else:
        lines.append("Keine Quelle mit mindestens zwei Wettbewerber-Zielen importiert.")

    lines.extend(
        [
            "",
            "## Grenzen",
            "",
            "- Keine Live-Prüfung von Quellseiten in dieser Stufe.",
            "- Keine automatische Bewertung von Regionalität, Partnern oder Linkqualität.",
            "- Review-Status und Notiz bleiben lokal und werden nicht aus dem Export überschrieben.",
            "",
        ]
    )
    (folder / "BACKLINK_OPPORTUNITIES.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )
    _csv(folder / "raw_data" / "backlink_observations.csv", rows)
    return folder
