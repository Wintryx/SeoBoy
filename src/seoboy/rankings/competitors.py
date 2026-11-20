"""SERP competitor grouping from stored ranking snapshots."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from seoboy.infrastructure.config import ProjectConfig
from seoboy.rankings.report import _expected_url, _profiles, _snapshots
from seoboy.shared.urls import normalize_url
from seoboy.shared.util import excel_safe


def _on_domain(profile: Any, result: dict[str, Any], config: ProjectConfig) -> bool:
    try:
        host = (urlsplit(normalize_url(result["url"]).url).hostname or "").casefold()
    except ValueError:
        return False
    return host in {value.casefold() for value in config.allowed_hosts}


def _decision(profile: Any, own_position: int | None, measured: bool) -> tuple[str, str]:
    if not measured:
        return "evidenz_fehlt", "Keine erfolgreiche Messung im Profil."
    if not profile.target_active:
        return "beobachten", "Soll-Zielseite ist noch nicht aktiv."
    if own_position is None:
        return "evidenz_fehlt", "Kein eigener Treffer; Nachfrage- und Angebotsbeleg fehlt."
    if own_position <= 3:
        return "beobachten", "Eigene Seite ist bereits in den Top 3; Veränderung beobachten."
    return (
        "bestehende_seite_verbessern",
        "Eigene Zielseite ist sichtbar, aber nicht in den Top 3.",
    )


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow([excel_safe(value) for value in row])


def write_competitor_report(
    connection: sqlite3.Connection,
    config: ProjectConfig,
    out: Path | None = None,
) -> Path:
    folder = out or (config.reports_dir / "competitors")
    folder.mkdir(parents=True, exist_ok=True)
    competitor_rows: list[list[Any]] = []
    opportunity_rows: list[list[Any]] = []
    sections: list[str] = []
    decisions: list[str] = []
    successful = 0
    for profile in _profiles(connection, config):
        snapshots = _snapshots(connection, config, profile)
        measured = [item for item in snapshots if item["status"] in {"ok", "no_match"}]
        latest = measured[-1] if measured else None
        if latest is None:
            decision, reason = _decision(profile, None, False)
            opportunity_rows.append(
                [
                    profile.id,
                    profile.query,
                    profile.expected_target,
                    "",
                    "",
                    decision,
                    reason,
                    "",
                ]
            )
            decisions.append(
                f"- **{profile.query}** ({profile.id}): {decision} – {reason}"
            )
            continue
        successful += 1
        results = latest["results"]
        own_result = next(
            (item for item in results if _on_domain(profile, item, config)), None
        )
        own_position = int(own_result["position"]) if own_result else None
        decision, reason = _decision(profile, own_position, True)
        competitors = [
            item for item in results if not _on_domain(profile, item, config)
        ][:3]
        opportunity_rows.append(
            [
                profile.id,
                profile.query,
                profile.expected_target,
                own_result["url"] if own_result else "",
                own_position or "",
                decision,
                reason,
                latest["observed_at"],
            ]
        )
        decisions.append(
            f"- **{profile.query}** ({profile.id}): {decision} – {reason}"
        )
        rows = []
        for item in competitors:
            competitor_rows.append(
                [
                    profile.id,
                    profile.query,
                    latest["observed_at"],
                    latest["depth"],
                    profile.result_type,
                    own_position or "",
                    item["position"],
                    item["url"],
                    item["domain"],
                    "unbekannt",
                    decision,
                ]
            )
            rows.append(
                f"| {item['position']} | {item['url']} | {item['domain'] or '–'} | unbekannt |"
            )
        sections.extend(
            [
                f"### {profile.query} ({profile.id})",
                "",
                f"**Messung:** {latest['observed_at']} · **Tiefe:** {latest['depth']} · "
                f"**Ergebnistyp:** {profile.result_type} · **Quelle:** {latest['source']}",
                "",
                "**Eigene Position:** "
                + (
                    f"{own_position}"
                    if own_position is not None
                    else "außerhalb der gemessenen Tiefe"
                ),
                "",
                "| Position | Vergleichs-URL | Domain | Rolle |",
                "| --- | --- | --- | --- |",
                *(
                    rows
                    or [
                        "| – | Keine Vergleichsseiten in den gespeicherten Treffern. | – | – |"
                    ]
                ),
                "",
            ]
        )
    lines = [
        "# SeoBoy – Wettbewerber je Suchanfrage",
        "",
        f"**Projekt:** {config.project_id}  ",
        f"**Erfolgreich gemessene Profile:** {successful}",
        "",
        "Diese erste Stufe gruppiert die gespeicherten Ranking-Treffer. Es werden keine "
        "Konkurrenzseiten live abgerufen und keine Inhalte automatisch verglichen. "
        "Rollen sind mangels manueller Zuordnung als unbekannt markiert.",
        "",
        "## Entscheidungen",
        "",
        *(decisions or ["Keine Ranking-Profile vorhanden."]),
        "",
        "## Suchanfragen und Vergleichsseiten",
        "",
        *(sections or ["Keine erfolgreichen Ranking-Snapshots vorhanden."]),
        "## Grenzen",
        "",
        "- Vergleichsseiten stammen ausschließlich aus den importierten Trefferzeilen.",
        "- Ohne Nachfrage-/GSC-Beleg wird keine neue Inhaltsseite empfohlen.",
        "- Es werden keine Website-Änderungen veröffentlicht.",
        "",
    ]
    (folder / "COMPETITOR_SERP_COMPARISON.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )
    _write_csv(
        folder / "raw_data" / "serp_competitors.csv",
        [
            "keyword_id",
            "query",
            "observed_at",
            "depth",
            "result_type",
            "own_position",
            "competitor_position",
            "url",
            "domain",
            "role",
            "decision",
        ],
        competitor_rows,
    )
    _write_csv(
        folder / "raw_data" / "content_opportunities.csv",
        [
            "keyword_id",
            "query",
            "expected_target",
            "actual_url",
            "own_position",
            "decision",
            "reason",
            "observed_at",
        ],
        opportunity_rows,
    )
    return folder
