"""Compare GSC query/page metrics across runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import csv
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterable

from seoboy.analysis.audit_data import RunData
from seoboy.gsc.importer import period_length
from seoboy.reporting.gsc_report import (
    Pair,
    Segment,
    pairs_for_dataset,
    segments,
)
from seoboy.shared.urls import relative_url
from seoboy.shared.util import excel_safe


@dataclass(frozen=True)
class Comparison:
    segment: Segment
    previous_run_id: str
    previous: dict[str, Any]
    previous_pairs: list[Pair]


def _segment_key(dataset: dict[str, Any]) -> str:
    return "|".join(
        [
            dataset["property"],
            dataset["search_type"],
            dataset["country"] or "",
            dataset["device"] or "",
        ]
    )


def _prior_run_ids(
    connection: sqlite3.Connection, data: RunData
) -> list[str]:
    rows = connection.execute(
        """
        SELECT r.run_id, MAX(r.started_at) AS started_at
        FROM runs r
        JOIN gsc_datasets g ON g.run_id = r.run_id
        WHERE r.project_id = ? AND r.site_id = ? AND r.run_id <> ?
          AND r.status IN ('completed', 'partial')
          AND g.grain = 'page_query'
        GROUP BY r.run_id
        ORDER BY started_at DESC
        LIMIT 20
        """,
        (data.config.project_id, data.run["site_id"], data.run_id),
    )
    return [str(row["run_id"]) for row in rows]


def find_history(
    connection: sqlite3.Connection, data: RunData
) -> list[Comparison]:
    current_segments = segments(data)
    if not current_segments:
        return []
    prior_ids = _prior_run_ids(connection, data)
    if not prior_ids:
        return []
    prior_cache: dict[str, RunData] = {}
    result: list[Comparison] = []
    for segment in current_segments:
        key = _segment_key(segment.dataset)
        length = period_length(
            segment.dataset["period_start"], segment.dataset["period_end"]
        )
        current_start = segment.dataset["period_start"]
        selected: tuple[RunData, dict[str, Any]] | None = None
        for run_id in prior_ids:
            prior = prior_cache.get(run_id)
            if prior is None:
                try:
                    prior = RunData(connection, data.config, run_id)
                except (sqlite3.Error, KeyError, TypeError, ValueError):
                    continue
                prior_cache[run_id] = prior
            candidates = [
                dataset
                for dataset in prior.datasets
                if dataset["grain"] == "page_query"
                and _segment_key(dataset) == key
                and dataset["period_end"] < current_start
                and period_length(
                    dataset["period_start"], dataset["period_end"]
                )
                == length
            ]
            if candidates:
                dataset = max(
                    candidates,
                    key=lambda item: (item["period_end"], item["period_start"]),
                )
                selected = (prior, dataset)
                break
        if selected is None:
            continue
        prior, dataset = selected
        result.append(
            Comparison(
                segment=segment,
                previous_run_id=prior.run_id,
                previous=dataset,
                previous_pairs=pairs_for_dataset(prior, dataset),
            )
        )
    return result


def _aggregate(
    pairs: list[Pair], key: Callable[[Pair], Any]
) -> dict[Any, dict[str, Any]]:
    result: dict[Any, dict[str, Any]] = {}
    for pair in pairs:
        item = result.setdefault(
            key(pair),
            {
                "url": pair.url,
                "query": pair.query,
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
        item["ctr"] = (
            item["clicks"] / item["impressions"]
            if item["impressions"]
            else None
        )
        item["position"] = (
            item["position_weight"] / item["position_impressions"]
            if item["position_impressions"]
            else None
        )
    return result


def _totals(pairs: list[Pair]) -> dict[str, Any]:
    clicks = sum(pair.clicks for pair in pairs)
    impressions = sum(pair.impressions for pair in pairs)
    weight = sum(
        (pair.position or 0.0) * pair.impressions
        for pair in pairs
        if pair.position is not None and pair.impressions
    )
    position_impressions = sum(
        pair.impressions
        for pair in pairs
        if pair.position is not None and pair.impressions
    )
    return {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": clicks / impressions if impressions else None,
        "position": weight / position_impressions
        if position_impressions
        else None,
    }


def _comparison_rows(
    current: dict[Any, dict[str, Any]],
    previous: dict[Any, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in set(current) | set(previous):
        now = current.get(key)
        before = previous.get(key)
        if now is None:
            status = "lost"
            base = before or {}
        elif before is None:
            status = "new"
            base = now
        else:
            status = "common"
            base = now
        now_clicks = now["clicks"] if now is not None else None
        before_clicks = before["clicks"] if before is not None else None
        now_impressions = now["impressions"] if now is not None else None
        before_impressions = before["impressions"] if before is not None else None
        rows.append(
            {
                "status": status,
                "url": base.get("url", ""),
                "query": base.get("query", ""),
                "current": now,
                "previous": before,
                "clicks_delta": (
                    now_clicks - before_clicks
                    if now_clicks is not None and before_clicks is not None
                    else None
                ),
                "impressions_delta": (
                    now_impressions - before_impressions
                    if now_impressions is not None and before_impressions is not None
                    else None
                ),
                "position_delta": (
                    now["position"] - before["position"]
                    if now is not None
                    and before is not None
                    and now["position"] is not None
                    and before["position"] is not None
                    else None
                ),
            }
        )
    return rows


def _fmt_int(value: int | None) -> str:
    return "–" if value is None else str(value)


def _fmt_ctr(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.1f} %"


def _fmt_position(value: float | None) -> str:
    return "–" if value is None else f"{value:.1f}"


def _fmt_delta(value: int | None) -> str:
    if value is None:
        return "–"
    return f"+{value}" if value > 0 else str(value)


def _fmt_pp(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value * 100:+.1f} pp"


def _fmt_position_delta(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value:+.1f}"


def _md(value: Any) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def _display(data: RunData, url: str) -> str:
    return relative_url(url, data.config.allowed_hosts)


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    result = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    result.extend("| " + " | ".join(row) + " |" for row in rows)
    return result


def _segment_label(dataset: dict[str, Any]) -> str:
    return (
        f"{dataset['property']} · {dataset['search_type']} · "
        f"{dataset['country'] or 'alle Länder'} · {dataset['device'] or 'alle Geräte'}"
    )


def _write_csv(path: Path, header: list[str], rows: Iterable[Iterable[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow([excel_safe(value) for value in row])


def _render_segment(data: RunData, comparison: Comparison) -> list[str]:
    current = comparison.segment.dataset
    previous = comparison.previous
    current_pairs = comparison.segment.pairs
    previous_pairs = comparison.previous_pairs
    current_totals = _totals(current_pairs)
    previous_totals = _totals(previous_pairs)
    gap = (
        date.fromisoformat(current["period_start"])
        - date.fromisoformat(previous["period_end"])
    ).days
    lines = [
        f"## {_segment_label(current)}",
        "",
        "| | Aktuell | Vorher |",
        "| --- | --- | --- |",
        f"| Lauf | {data.run_id} | {comparison.previous_run_id} |",
        f"| Zeitraum | {current['period_start']} bis {current['period_end']} | "
        f"{previous['period_start']} bis {previous['period_end']} |",
        f"| Länge | {period_length(current['period_start'], current['period_end'])} Tage | "
        f"{period_length(previous['period_start'], previous['period_end'])} Tage |",
        f"| Abstand | {gap} Tag(e) zwischen den Zeiträumen | – |",
        "",
        "### Gesamt",
        "",
        "| Kennzahl | Aktuell | Vorher | Änderung |",
        "| --- | ---: | ---: | ---: |",
        f"| Klicks | {current_totals['clicks']} | {previous_totals['clicks']} | "
        f"{_fmt_delta(current_totals['clicks'] - previous_totals['clicks'])} |",
        f"| Impressionen | {current_totals['impressions']} | "
        f"{previous_totals['impressions']} | "
        f"{_fmt_delta(current_totals['impressions'] - previous_totals['impressions'])} |",
        f"| CTR | {_fmt_ctr(current_totals['ctr'])} | "
        f"{_fmt_ctr(previous_totals['ctr'])} | "
        f"{_fmt_pp((current_totals['ctr'] or 0.0) - (previous_totals['ctr'] or 0.0))} |",
        f"| Ø Position | {_fmt_position(current_totals['position'])} | "
        f"{_fmt_position(previous_totals['position'])} | "
        f"{_fmt_position_delta((current_totals['position'] or 0.0) - (previous_totals['position'] or 0.0))} |",
        "",
    ]
    current_pages = _aggregate(current_pairs, lambda pair: pair.url)
    previous_pages = _aggregate(previous_pairs, lambda pair: pair.url)
    page_rows = _comparison_rows(current_pages, previous_pages)
    page_rows.sort(
        key=lambda row: (
            -abs(row["clicks_delta"] or 0),
            -(row["current"]["impressions"] if row["current"] else 0),
            row["url"],
        )
    )
    page_table = [
        [
            _md(_display(data, row["url"])),
            _fmt_int(row["previous"]["clicks"] if row["previous"] else None),
            _fmt_int(row["current"]["clicks"] if row["current"] else None),
            _fmt_delta(row["clicks_delta"]),
            _fmt_int(row["previous"]["impressions"] if row["previous"] else None),
            _fmt_int(row["current"]["impressions"] if row["current"] else None),
            _fmt_pp(
                (row["current"]["ctr"] if row["current"] else None)
                - (row["previous"]["ctr"] if row["previous"] else None)
                if row["current"] and row["previous"]
                and row["current"]["ctr"] is not None
                and row["previous"]["ctr"] is not None
                else None
            ),
            _fmt_position(row["previous"]["position"] if row["previous"] else None),
            _fmt_position(row["current"]["position"] if row["current"] else None),
        ]
        for row in page_rows[:15]
    ]
    lines.extend(
        [
            "### Seiten",
            "",
            *_table(
                [
                    "Seite",
                    "Klicks vorher",
                    "Klicks aktuell",
                    "Δ Klicks",
                    "Impr. vorher",
                    "Impr. aktuell",
                    "Δ CTR",
                    "Pos. vorher",
                    "Pos. aktuell",
                ],
                page_table,
            ),
            "",
        ]
    )

    current_queries = _aggregate(current_pairs, lambda pair: pair.query)
    previous_queries = _aggregate(previous_pairs, lambda pair: pair.query)
    query_rows = _comparison_rows(current_queries, previous_queries)
    query_rows.sort(
        key=lambda row: (
            -abs(row["clicks_delta"] or 0),
            -(row["current"]["impressions"] if row["current"] else 0),
            row["query"],
        )
    )
    query_table = [
        [
            _md(row["query"]),
            _fmt_int(row["previous"]["clicks"] if row["previous"] else None),
            _fmt_int(row["current"]["clicks"] if row["current"] else None),
            _fmt_delta(row["clicks_delta"]),
            _fmt_int(row["previous"]["impressions"] if row["previous"] else None),
            _fmt_int(row["current"]["impressions"] if row["current"] else None),
            _fmt_position(row["previous"]["position"] if row["previous"] else None),
            _fmt_position(row["current"]["position"] if row["current"] else None),
        ]
        for row in query_rows[:15]
    ]
    lines.extend(
        [
            "### Suchanfragen",
            "",
            *_table(
                [
                    "Suchanfrage",
                    "Klicks vorher",
                    "Klicks aktuell",
                    "Δ Klicks",
                    "Impr. vorher",
                    "Impr. aktuell",
                    "Pos. vorher",
                    "Pos. aktuell",
                ],
                query_table,
            ),
            "",
        ]
    )

    current_pairs_map = _aggregate(
        current_pairs, lambda pair: (pair.url, pair.query)
    )
    previous_pairs_map = _aggregate(
        previous_pairs, lambda pair: (pair.url, pair.query)
    )
    pair_rows = _comparison_rows(current_pairs_map, previous_pairs_map)
    pair_rows.sort(
        key=lambda row: (
            -abs(row["clicks_delta"] or 0),
            -(row["current"]["impressions"] if row["current"] else 0),
            row["query"],
            row["url"],
        )
    )
    pair_table = [
        [
            _md(row["query"]),
            _md(_display(data, row["url"])),
            _fmt_int(row["previous"]["clicks"] if row["previous"] else None),
            _fmt_int(row["current"]["clicks"] if row["current"] else None),
            _fmt_delta(row["clicks_delta"]),
            _fmt_int(row["previous"]["impressions"] if row["previous"] else None),
            _fmt_int(row["current"]["impressions"] if row["current"] else None),
            _fmt_position(row["previous"]["position"] if row["previous"] else None),
            _fmt_position(row["current"]["position"] if row["current"] else None),
        ]
        for row in pair_rows[:20]
    ]
    lines.extend(
        [
            "### Suchanfrage × Zielseite",
            "",
            "Die Tabelle zeigt die stärksten Veränderungen nach absolutem Klick-Delta. "
            "Neue Paare haben keinen Vorzeitraum, verlorene Paare keinen aktuellen Wert.",
            "",
            *_table(
                [
                    "Suchanfrage",
                    "Zielseite",
                    "Klicks vorher",
                    "Klicks aktuell",
                    "Δ Klicks",
                    "Impr. vorher",
                    "Impr. aktuell",
                    "Pos. vorher",
                    "Pos. aktuell",
                ],
                pair_table,
            ),
            "",
        ]
    )

    new_pairs = [row for row in pair_rows if row["status"] == "new"]
    lost_pairs = [row for row in pair_rows if row["status"] == "lost"]
    for title, members in (("Neue Paare", new_pairs), ("Verlorene Paare", lost_pairs)):
        lines.extend([f"### {title} ({len(members)})", ""])
        if not members:
            lines.extend(["Keine.", ""])
            continue
        for row in members[:10]:
            lines.append(
                f"- **{_md(row['query'])}** · {_md(_display(data, row['url']))} – "
                f"{_fmt_int(row['current']['impressions'] if row['current'] else None)} "
                "Impressionen aktuell"
            )
        if len(members) > 10:
            lines.append(f"- … {len(members) - 10} weitere laut CSV")
        lines.append("")
    return lines


def render_history(data: RunData, connection: sqlite3.Connection) -> str:
    comparisons = find_history(connection, data)
    lines = [
        "# SeoBoy – GSC-Verlauf",
        "",
        f"**Aktueller Lauf:** {data.run_id}",
        "",
        "Dieser Bericht vergleicht den aktuellen GSC-Zeitraum mit dem jüngsten "
        "früheren Lauf desselben Projekts, derselben Property und derselben "
        "Filterkombination. Verglichen werden nur gleich lange, nicht "
        "überlappende Zeiträume.",
        "",
    ]
    if not comparisons:
        lines.extend(
            [
                "## Kein Vergleichslauf",
                "",
                "Es gibt noch keinen früheren Lauf mit einem vergleichbaren "
                "GSC-Query-/Seitenzeitraum. Der Bericht wird beim nächsten Lauf "
                "automatisch gefüllt.",
                "",
            ]
        )
        return "\n".join(lines)
    for comparison in comparisons:
        lines.extend(_render_segment(data, comparison))
    lines.extend(
        [
            "## Grenzen",
            "",
            "- Der Vergleich ist eine Momentaufnahme der GSC-Daten, keine "
            "Kausalitätsanalyse. Änderungen an Titel, Inhalt, CTA, Saisonalität "
            "und Wettbewerb können gleichzeitig wirken.",
            "- Nur gleich lange, nicht überlappende Zeiträume werden verglichen.",
            "- Positionsänderungen sind Durchschnittswerte; einzelne Tage oder "
            "Geräte können abweichen.",
            "- Neue und verlorene Paare können auch durch die begrenzte "
            "GSC-Datenmenge oder Zuordnung entstehen.",
            "",
            "## Rohdaten",
            "",
            "- [GSC-Verlauf](raw_data/gsc_history.csv)",
            "",
        ]
    )
    return "\n".join(lines)


def has_history(data: RunData) -> bool:
    return any(dataset["grain"] == "page_query" for dataset in data.datasets)


def write_gsc_history_csv(path: Path, data: RunData, connection: sqlite3.Connection) -> None:
    rows: list[list[Any]] = []
    for comparison in find_history(connection, data):
        current = comparison.segment.dataset
        previous = comparison.previous
        current_pairs = comparison.segment.pairs
        previous_pairs = comparison.previous_pairs
        current_map = _aggregate(current_pairs, lambda pair: (pair.url, pair.query))
        previous_map = _aggregate(previous_pairs, lambda pair: (pair.url, pair.query))
        for row in _comparison_rows(current_map, previous_map):
            now = row["current"]
            before = row["previous"]
            rows.append(
                [
                    current["property"],
                    current["search_type"],
                    current["country"] or "",
                    current["device"] or "",
                    data.run_id,
                    comparison.previous_run_id,
                    current["period_start"],
                    current["period_end"],
                    previous["period_start"],
                    previous["period_end"],
                    row["status"],
                    row["url"],
                    row["query"],
                    "" if before is None else before["clicks"],
                    "" if now is None else now["clicks"],
                    "" if row["clicks_delta"] is None else row["clicks_delta"],
                    "" if before is None else before["impressions"],
                    "" if now is None else now["impressions"],
                    "" if row["impressions_delta"] is None else row["impressions_delta"],
                    "" if before is None or before["ctr"] is None else round(before["ctr"], 6),
                    "" if now is None or now["ctr"] is None else round(now["ctr"], 6),
                    "" if before is None or before["position"] is None else before["position"],
                    "" if now is None or now["position"] is None else now["position"],
                    "" if row["position_delta"] is None else row["position_delta"],
                ]
            )
    _write_csv(
        path,
        [
            "property",
            "search_type",
            "country",
            "device",
            "current_run_id",
            "previous_run_id",
            "current_period_start",
            "current_period_end",
            "previous_period_start",
            "previous_period_end",
            "status",
            "url",
            "query",
            "previous_clicks",
            "current_clicks",
            "clicks_delta",
            "previous_impressions",
            "current_impressions",
            "impressions_delta",
            "previous_ctr",
            "current_ctr",
            "previous_position",
            "current_position",
            "position_delta",
        ],
        rows,
    )


def write_gsc_history_report(
    folder: Path, data: RunData, connection: sqlite3.Connection
) -> bool:
    if not has_history(data):
        return False
    (folder / "raw_data").mkdir(parents=True, exist_ok=True)
    (folder / "05_GSC_HISTORY.md").write_text(
        render_history(data, connection).rstrip() + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_gsc_history_csv(folder / "raw_data" / "gsc_history.csv", data, connection)
    return True
