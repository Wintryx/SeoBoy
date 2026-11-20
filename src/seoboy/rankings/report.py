"""Latest ranking state and Soll/Ist deviations."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

from seoboy.analysis.audit_data import RunData
from seoboy.infrastructure.config import ProjectConfig
from seoboy.rankings.config import KeywordProfile
from seoboy.reporting.gsc_report import segments
from seoboy.shared.urls import normalize_url
from seoboy.shared.util import excel_safe


def _profiles(connection: sqlite3.Connection, config: ProjectConfig) -> list[KeywordProfile]:
    result: list[KeywordProfile] = []
    for row in connection.execute(
        "SELECT * FROM ranking_keywords WHERE project_id = ? ORDER BY keyword_id",
        (config.project_id,),
    ):
        result.append(
            KeywordProfile(
                id=row["keyword_id"],
                query=row["query"],
                intent=row["intent"],
                tags=tuple(),
                market=row["market"],
                language=row["language"],
                location_key=row["location_key"],
                engine=row["engine"],
                device=row["device"],
                result_type=row["result_type"],
                expected_target=row["expected_target"],
                target_active=bool(row["target_active"]),
                business_value=row["business_value"],
            )
        )
    return result


def _latest_run_data(
    connection: sqlite3.Connection, config: ProjectConfig
) -> RunData | None:
    for row in connection.execute(
        "SELECT run_id FROM runs WHERE project_id = ? AND mode = 'crawl' "
        "AND status = 'completed' ORDER BY ended_at DESC LIMIT 20",
        (config.project_id,),
    ):
        try:
            return RunData(connection, config, row["run_id"])
        except (ValueError, sqlite3.Error):
            continue
    return None


def _gsc_map(data: RunData | None) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    if data is None:
        return result
    for segment in segments(data):
        for pair in segment.pairs:
            try:
                url = normalize_url(pair.url).url
            except ValueError:
                continue
            key = (pair.query.casefold(), url)
            item = result.setdefault(
                key,
                {
                    "clicks": 0,
                    "impressions": 0,
                    "position_weight": 0.0,
                    "position_impressions": 0,
                },
            )
            item["clicks"] += pair.clicks
            item["impressions"] += pair.impressions
            if pair.position is not None and pair.impressions:
                item["position_weight"] += pair.position * pair.impressions
                item["position_impressions"] += pair.impressions
    for item in result.values():
        item["position"] = (
            item["position_weight"] / item["position_impressions"]
            if item["position_impressions"]
            else None
        )
    return result


def _alias_map(data: RunData | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if data is None:
        return result
    for url_id, observations in data.observations.items():
        info = data.urls.get(url_id)
        if info is None or not observations:
            continue
        canonical = observations[-1].signals.get("canonical") or []
        if not isinstance(canonical, list) or not canonical:
            continue
        try:
            source = normalize_url(info.url).url
            target = normalize_url(str(canonical[0])).url
        except ValueError:
            continue
        if source != target:
            result[source] = target
    return result


def _is_target(
    observed: str | None, expected: str | None, aliases: dict[str, str]
) -> bool:
    if observed is None or expected is None:
        return False
    return observed == expected or aliases.get(observed) == expected


def _expected_url(profile: KeywordProfile, config: ProjectConfig) -> str | None:
    if profile.result_type != "organic" or not profile.expected_target:
        return None
    value = profile.expected_target
    if value.startswith("/"):
        value = config.start_url.rstrip("/") + value
    try:
        return normalize_url(value).url
    except ValueError:
        return None


def _snapshots(
    connection: sqlite3.Connection, config: ProjectConfig, profile: KeywordProfile
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM ranking_snapshots WHERE project_id = ? AND keyword_id = ? "
        "AND engine = ? AND market = ? AND language = ? AND location_key = ? "
        "AND device = ? AND result_type = ? ORDER BY observed_at",
        (
            config.project_id,
            profile.id,
            profile.engine,
            profile.market,
            profile.language,
            profile.location_key,
            profile.device,
            profile.result_type,
        ),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["results"] = [
            dict(value)
            for value in connection.execute(
                "SELECT position, url, profile_id, domain, title FROM ranking_results "
                "WHERE project_id = ? AND snapshot_id = ? ORDER BY position",
                (config.project_id, row["snapshot_id"]),
            )
        ]
        result.append(item)
    return result


def _own_position(
    profile: KeywordProfile, snapshot: dict[str, Any], config: ProjectConfig
) -> tuple[int | None, str | None]:
    if profile.result_type == "local_pack":
        for result in snapshot["results"]:
            if profile.expected_target and result["profile_id"] == profile.expected_target:
                return int(result["position"]), result["url"]
        return None, None
    own: list[tuple[int, str]] = []
    for result in snapshot["results"]:
        try:
            observed = normalize_url(result["url"]).url
        except ValueError:
            continue
        host = (urlsplit(observed).hostname or "").casefold()
        if host in {value.casefold() for value in config.allowed_hosts}:
            own.append((int(result["position"]), observed))
    if not own:
        return None, None
    own.sort(key=lambda item: item[0])
    return own[0]


def _latest_rows(
    connection: sqlite3.Connection,
    config: ProjectConfig,
    gsc: dict[tuple[str, str], dict[str, Any]],
    aliases: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for profile in _profiles(connection, config):
        snapshots = _snapshots(connection, config, profile)
        successful = [item for item in snapshots if item["status"] in {"ok", "no_match"}]
        latest = snapshots[-1] if snapshots else None
        measured = successful[-1] if successful else None
        previous = successful[-2] if len(successful) >= 2 else None
        position = None
        actual = None
        if measured is not None:
            position, actual = _own_position(profile, measured, config)
        previous_position = None
        if previous is not None:
            previous_position, _ = _own_position(profile, previous, config)
        expected = _expected_url(profile, config)
        mismatch = bool(
            position is not None
            and expected is not None
            and actual is not None
            and not _is_target(normalize_url(actual).url, expected, aliases)
        )
        gsc_item = gsc.get((profile.query.casefold(), actual or "")) or gsc.get(
            (profile.query.casefold(), expected or "")
        )
        delta = (
            previous_position - position
            if previous_position is not None and position is not None
            else None
        )
        if latest is None:
            state = "nie gemessen"
        elif latest["status"] == "failed":
            state = "Messung fehlgeschlagen"
        elif latest["status"] == "blocked":
            state = "Messung blockiert"
        elif not profile.target_active:
            state = "geplant"
        elif position is None:
            state = f"außerhalb Top {measured['depth'] if measured else latest['depth']}"
        else:
            state = f"Position {position}"
        rows.append(
            {
                "profile": profile,
                "latest": latest,
                "measured": measured,
                "position": position,
                "actual": actual,
                "expected": expected,
                "previous_position": previous_position,
                "delta": delta,
                "mismatch": mismatch,
                "gsc_clicks": gsc_item.get("clicks") if gsc_item else None,
                "gsc_impressions": gsc_item.get("impressions") if gsc_item else None,
                "gsc_position": gsc_item.get("position") if gsc_item else None,
                "state": state,
                "target_active": profile.target_active,
            }
        )
    return rows


def write_rankings_report(
    connection: sqlite3.Connection,
    config: ProjectConfig,
    out: Path | None = None,
) -> Path:
    folder = out or (config.reports_dir / "rankings")
    folder.mkdir(parents=True, exist_ok=True)
    run_data = _latest_run_data(connection, config)
    gsc = _gsc_map(run_data)
    aliases = _alias_map(run_data)
    rows = _latest_rows(connection, config, gsc, aliases)
    measured = [
        row for row in rows if row["measured"] is not None and row["target_active"]
    ]
    top3 = sum(1 for row in measured if row["position"] is not None and row["position"] <= 3)
    top10 = sum(1 for row in measured if row["position"] is not None and row["position"] <= 10)
    found = sum(1 for row in measured if row["position"] is not None)
    lines = [
        "# SeoBoy – lokales Keyword-Monitoring",
        "",
        f"**Projekt:** {config.project_id}  ",
        f"**Profile:** {len(rows)} · **erfolgreich gemessen:** {len(measured)}",
        "",
        "## Überblick",
        "",
        "| Kennzahl | Wert |",
        "| --- | --- |",
        f"| Top 3 | {top3} / {len(measured)} |",
        f"| Top 10 | {top10} / {len(measured)} |",
        f"| eigener Treffer | {found} / {len(measured)} |",
        f"| nicht gemessen/fehlend | {len(rows) - len(measured)} |",
        "",
        "Die Nenner zählen nur Profile mit einer erfolgreichen Messung. Fehlgeschlagene, "
        "blockierte oder noch nie gemessene Profile erscheinen separat.",
        "",
        "## Profile",
        "",
        "| Keyword | Ort | Gerät | Typ | Zustand | Soll | Ist | Δ | GSC-Klicks | GSC-Impr. | GSC-Pos. | Messung |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        profile = row["profile"]
        measured_at = row["measured"]["observed_at"] if row["measured"] else "–"
        gsc_clicks = row["gsc_clicks"] if row["gsc_clicks"] is not None else "–"
        gsc_impressions = (
            row["gsc_impressions"] if row["gsc_impressions"] is not None else "–"
        )
        gsc_position = (
            f"{row['gsc_position']:.1f}" if row["gsc_position"] is not None else "–"
        )
        lines.append(
            f"| {profile.query} | {profile.location_key or '–'} | {profile.device} | "
            f"{profile.result_type} | {row['state']} | {profile.expected_target or '–'} | "
            f"{row['actual'] or '–'} | {row['delta'] if row['delta'] is not None else '–'} | "
            f"{gsc_clicks} | {gsc_impressions} | {gsc_position} | {measured_at} |"
        )

    mismatches = [row for row in rows if row["mismatch"] and row["target_active"]]
    outside = [
        row
        for row in rows
        if row["target_active"]
        and row["measured"] is not None
        and row["position"] is None
    ]
    lines.extend(["## Soll-/Ist-Abweichungen", ""])
    if mismatches:
        for row in mismatches:
            profile = row["profile"]
            lines.append(
                f"- **{profile.query}**: erwartet {row['expected']}, tatsächlich "
                f"{row['actual']} (Position {row['position']})."
            )
    else:
        lines.append("Keine abweichende eigene Ziel-URL bei den gemessenen Profilen.")
    if outside:
        lines.extend(["", "### Außerhalb der gemessenen Tiefe", ""])
        for row in outside:
            profile = row["profile"]
            depth = row["measured"]["depth"]
            lines.append(
                f"- **{profile.query}**: kein eigener Treffer in Top {depth} "
                f"(erwartet {profile.expected_target or '–'})."
            )
    if not mismatches and not outside:
        lines.append("Alle aktiven Profile haben einen passenden eigenen Treffer.")

    lines.extend(
        [
            "",
            "## Messhinweise",
            "",
            "- Positionen werden je Ergebnistyp und Messprofil getrennt ausgewertet.",
            "- Ein fehlender eigener Treffer ist keine Position 11, sondern außerhalb der Tiefe.",
            "- Δ ist die Verbesserung der Position gegenüber der vorherigen erfolgreichen Messung.",
            "- Anbieter-, Geräte-, Orts- und Tiefenwechsel sind nur innerhalb eines Profils vergleichbar.",
            "- GSC-Werte stammen aus dem jüngsten abgeschlossenen Audit mit passender Suchanfrage "
            "und eigener Ziel-URL. Fehlende Zeilen bleiben leer.",
            "",
        ]
    )
    (folder / "rankings_overview.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )
    raw = folder / "raw_data"
    raw.mkdir(parents=True, exist_ok=True)
    with (raw / "rankings_snapshots.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            [
                "keyword_id",
                "query",
                "market",
                "language",
                "location_key",
                "device",
                "result_type",
                "state",
                "position",
                "expected_target",
                "actual_url",
                "delta",
                "observed_at",
                "status",
                "depth",
                "gsc_clicks",
                "gsc_impressions",
                "gsc_position",
            ]
        )
        for row in rows:
            profile = row["profile"]
            measured = row["measured"]
            writer.writerow(
                [
                    excel_safe(profile.id),
                    excel_safe(profile.query),
                    profile.market,
                    profile.language,
                    excel_safe(profile.location_key),
                    profile.device,
                    profile.result_type,
                    excel_safe(row["state"]),
                    "" if row["position"] is None else row["position"],
                    excel_safe(profile.expected_target),
                    excel_safe(row["actual"] or ""),
                    "" if row["delta"] is None else row["delta"],
                    measured["observed_at"] if measured else "",
                    measured["status"] if measured else "",
                    measured["depth"] if measured else "",
                    "" if row["gsc_clicks"] is None else row["gsc_clicks"],
                    "" if row["gsc_impressions"] is None else row["gsc_impressions"],
                    "" if row["gsc_position"] is None else row["gsc_position"],
                ]
            )
    return folder
