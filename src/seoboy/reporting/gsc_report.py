"""GSC query-by-landing-page report.

The report is intentionally independent from the rule engine: it shows the
actual query/page pairs that drive clicks and impressions so content decisions
are based on search demand instead of URL counts.
"""

from __future__ import annotations

from dataclasses import dataclass
import csv
from pathlib import Path
from typing import Any, Iterable

from seoboy.analysis.audit_data import RunData
from seoboy.gsc.importer import select_comparison_periods
from seoboy.shared.urls import relative_url
from seoboy.shared.util import excel_safe


@dataclass(frozen=True)
class Pair:
    url_id: int
    url: str
    query: str
    clicks: int
    impressions: int
    position: float | None

    @property
    def ctr(self) -> float | None:
        if self.impressions <= 0:
            return None
        return self.clicks / self.impressions


@dataclass(frozen=True)
class Segment:
    dataset: dict[str, Any]
    previous: dict[str, Any] | None
    pairs: list[Pair]
    previous_pairs: list[Pair]


def _pairs(data: RunData, dataset: dict[str, Any]) -> list[Pair]:
    result: list[Pair] = []
    for row in data.metrics.get(int(dataset["dataset_id"]), []):
        if row["mapping_status"] != "matched" or row["url_id"] is None:
            continue
        query = str(row["query"] or "").strip()
        if not query:
            continue
        position = row["position"]
        result.append(
            Pair(
                url_id=int(row["url_id"]),
                url=data.url_string(int(row["url_id"])),
                query=query,
                clicks=int(row["clicks"]),
                impressions=int(row["impressions"]),
                position=None if position is None else float(position),
            )
        )
    return result


def pairs_for_dataset(data: RunData, dataset: dict[str, Any]) -> list[Pair]:
    return _pairs(data, dataset)


def segments(data: RunData) -> list[Segment]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for dataset in data.datasets:
        if dataset["grain"] != "page_query":
            continue
        key = "|".join(
            [
                dataset["property"],
                dataset["search_type"],
                dataset["country"] or "",
                dataset["device"] or "",
            ]
        )
        groups.setdefault(key, []).append(dataset)
    result: list[Segment] = []
    for key in sorted(groups):
        latest, previous = select_comparison_periods(groups[key])
        if latest is None:
            continue
        result.append(
            Segment(
                dataset=latest,
                previous=previous,
                pairs=_pairs(data, latest),
                previous_pairs=_pairs(data, previous) if previous is not None else [],
            )
        )
    return result


def _segment_label(dataset: dict[str, Any]) -> str:
    return (
        f"{dataset['property']} · {dataset['search_type']} · "
        f"{dataset['country'] or 'alle Länder'} · {dataset['device'] or 'alle Geräte'}"
    )


def _display(data: RunData, url: str) -> str:
    return relative_url(url, data.config.allowed_hosts)


def _format_ctr(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.1f} %"


def _format_position(value: float | None) -> str:
    return "–" if value is None else f"{value:.1f}"


def _format_delta(current: int, previous: int | None) -> str:
    if previous is None:
        return "–"
    difference = current - previous
    if difference > 0:
        return f"+{difference}"
    if difference < 0:
        return f"−{abs(difference)}"
    return "0"


def _md(value: Any) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def _write_csv(path: Path, header: list[str], rows: Iterable[Iterable[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow([excel_safe(value) for value in row])


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    result = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    result.extend("| " + " | ".join(row) + " |" for row in rows)
    return result


def _page_rows(segment: Segment) -> list[dict[str, Any]]:
    current: dict[int, dict[str, Any]] = {}
    for pair in segment.pairs:
        item = current.setdefault(
            pair.url_id,
            {
                "url": pair.url,
                "clicks": 0,
                "impressions": 0,
                "position_weight": 0.0,
                "position_impressions": 0,
                "queries": set(),
            },
        )
        item["clicks"] += pair.clicks
        item["impressions"] += pair.impressions
        item["queries"].add(pair.query)
        if pair.position is not None and pair.impressions:
            item["position_weight"] += pair.position * pair.impressions
            item["position_impressions"] += pair.impressions
    previous: dict[int, tuple[int, int]] = {}
    for pair in segment.previous_pairs:
        clicks, impressions = previous.get(pair.url_id, (0, 0))
        previous[pair.url_id] = (clicks + pair.clicks, impressions + pair.impressions)
    for url_id, item in current.items():
        item["previous_clicks"], item["previous_impressions"] = previous.get(
            url_id, (None, None)
        )
        item["position"] = (
            item["position_weight"] / item["position_impressions"]
            if item["position_impressions"]
            else None
        )
    return sorted(
        current.values(),
        key=lambda item: (-item["impressions"], -item["clicks"], item["url"]),
    )


def _query_rows(segment: Segment) -> list[dict[str, Any]]:
    current: dict[str, dict[str, Any]] = {}
    for pair in segment.pairs:
        item = current.setdefault(
            pair.query,
            {
                "query": pair.query,
                "clicks": 0,
                "impressions": 0,
                "position_weight": 0.0,
                "position_impressions": 0,
                "urls": set(),
            },
        )
        item["clicks"] += pair.clicks
        item["impressions"] += pair.impressions
        item["urls"].add(pair.url_id)
        if pair.position is not None and pair.impressions:
            item["position_weight"] += pair.position * pair.impressions
            item["position_impressions"] += pair.impressions
    previous: dict[str, tuple[int, int]] = {}
    for pair in segment.previous_pairs:
        clicks, impressions = previous.get(pair.query, (0, 0))
        previous[pair.query] = (clicks + pair.clicks, impressions + pair.impressions)
    for query, item in current.items():
        item["previous_clicks"], item["previous_impressions"] = previous.get(
            query, (None, None)
        )
        item["position"] = (
            item["position_weight"] / item["position_impressions"]
            if item["position_impressions"]
            else None
        )
    return sorted(
        current.values(),
        key=lambda item: (-item["impressions"], -item["clicks"], item["query"]),
    )


def _pair_rows(segment: Segment) -> list[dict[str, Any]]:
    previous = {(pair.url_id, pair.query): pair for pair in segment.previous_pairs}
    result: list[dict[str, Any]] = []
    for pair in segment.pairs:
        before = previous.get((pair.url_id, pair.query))
        result.append(
            {
                "pair": pair,
                "previous_clicks": before.clicks if before is not None else None,
            }
        )
    return sorted(
        result,
        key=lambda item: (
            -item["pair"].impressions,
            -item["pair"].clicks,
            item["pair"].query,
            item["pair"].url,
        ),
    )


def _opportunities(segment: Segment, data: RunData) -> list[Pair]:
    thresholds = data.config.gsc
    result = [
        pair
        for pair in segment.pairs
        if pair.position is not None
        and thresholds.near_top_position_min
        <= pair.position
        <= thresholds.near_top_position_max
        and pair.impressions >= thresholds.near_top_min_impressions
        and (pair.ctr is None or pair.ctr < 0.05)
    ]
    return sorted(
        result, key=lambda pair: (-pair.impressions, pair.position or 999, pair.query)
    )


def _cannibalization(segment: Segment, data: RunData) -> list[dict[str, Any]]:
    thresholds = data.config.gsc
    by_query: dict[str, list[Pair]] = {}
    for pair in segment.pairs:
        by_query.setdefault(pair.query, []).append(pair)
    result: list[dict[str, Any]] = []
    for query, pairs in by_query.items():
        urls = {pair.url_id for pair in pairs}
        impressions = sum(pair.impressions for pair in pairs)
        if (
            len(urls) < thresholds.multi_url_min_urls
            or impressions < thresholds.multi_url_min_impressions
        ):
            continue
        result.append(
            {
                "query": query,
                "urls": len(urls),
                "impressions": impressions,
                "clicks": sum(pair.clicks for pair in pairs),
                "best_position": min(
                    (pair.position for pair in pairs if pair.position is not None),
                    default=None,
                ),
                "pairs": sorted(
                    pairs, key=lambda pair: (-pair.impressions, pair.url)
                ),
            }
        )
    return sorted(result, key=lambda item: (-item["impressions"], item["query"]))


def render_gsc_query_pages(data: RunData) -> str:
    run = data.run
    items = segments(data)
    lines = [
        "# SeoBoy – GSC: Suchanfragen und Zielseiten",
        "",
        f"**Lauf:** {run['run_id']} · **Status:** {run['status']}",
        "",
        "Diese Auswertung verbindet Search-Console-Suchanfragen mit den tatsächlich "
        "zugeordneten Zielseiten. Sie ergänzt die technischen Regeln um Nachfrage- und "
        "Buchungssignale. Nur Zeilen mit eindeutiger URL-Zuordnung werden ausgewertet.",
        "",
    ]
    if not items:
        lines.extend(
            [
                "## Keine Query-/Seitendaten",
                "",
                "Für diesen Lauf liegt kein GSC-Datensatz mit Granularität "
                "page_query vor. Notwendig ist ein Seiten-Suchanfragen-Export "
                "(page,query,clicks,impressions,position).",
                "",
            ]
        )
        return "\n".join(lines)
    lines.extend(
        [
            "## Datenbasis",
            "",
            "| Property | Suchtyp | Land | Gerät | Zeitraum | Vorzeitraum |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for segment in items:
        dataset = segment.dataset
        previous = segment.previous
        lines.append(
            f"| {_md(dataset['property'])} | {_md(dataset['search_type'])} | "
            f"{_md(dataset['country'] or 'alle')} | {_md(dataset['device'] or 'alle')} | "
            f"{dataset['period_start']} bis {dataset['period_end']} | "
            + (
                f"{previous['period_start']} bis {previous['period_end']}"
                if previous is not None
                else "–"
            )
            + " |"
        )
    lines.append("")
    for segment in items:
        dataset = segment.dataset
        lines.extend([f"## {_segment_label(dataset)}", ""])
        lines.append(
            f"**Zeitraum:** {dataset['period_start']} bis {dataset['period_end']} · "
            f"**Zeilen:** {len(segment.pairs)}"
        )
        if segment.previous is not None:
            lines.append(
                f"**Vorzeitraum:** {segment.previous['period_start']} bis "
                f"{segment.previous['period_end']}"
            )
        lines.append("")
        if not segment.pairs:
            lines.extend(["Keine zugeordneten Query-/Seitenzeilen.", ""])
            continue

        pages = _page_rows(segment)
        page_table = [
            [
                _md(_display(data, row["url"])),
                str(row["clicks"]),
                str(row["impressions"]),
                _format_ctr(
                    row["clicks"] / row["impressions"] if row["impressions"] else None
                ),
                _format_position(row["position"]),
                str(len(row["queries"])),
                _format_delta(row["clicks"], row["previous_clicks"]),
            ]
            for row in pages[:15]
        ]
        lines.extend(
            [
                "### Stärkste Zielseiten",
                "",
                *_table(
                    [
                        "Zielseite",
                        "Klicks",
                        "Impressionen",
                        "CTR",
                        "Ø Position",
                        "Anfragen",
                        "Δ Klicks",
                    ],
                    page_table,
                ),
                "",
            ]
        )

        queries = _query_rows(segment)
        query_table = [
            [
                _md(row["query"]),
                str(row["clicks"]),
                str(row["impressions"]),
                _format_ctr(
                    row["clicks"] / row["impressions"] if row["impressions"] else None
                ),
                _format_position(row["position"]),
                str(len(row["urls"])),
                _format_delta(row["clicks"], row["previous_clicks"]),
            ]
            for row in queries[:15]
        ]
        lines.extend(
            [
                "### Stärkste Suchanfragen",
                "",
                *_table(
                    [
                        "Suchanfrage",
                        "Klicks",
                        "Impressionen",
                        "CTR",
                        "Ø Position",
                        "URLs",
                        "Δ Klicks",
                    ],
                    query_table,
                ),
                "",
            ]
        )

        pairs = _pair_rows(segment)
        pair_table = [
            [
                _md(row["pair"].query),
                _md(_display(data, row["pair"].url)),
                str(row["pair"].clicks),
                str(row["pair"].impressions),
                _format_ctr(row["pair"].ctr),
                _format_position(row["pair"].position),
                _format_delta(row["pair"].clicks, row["previous_clicks"]),
            ]
            for row in pairs[:20]
        ]
        lines.extend(
            [
                "### Suchanfrage × Zielseite",
                "",
                *_table(
                    [
                        "Suchanfrage",
                        "Zielseite",
                        "Klicks",
                        "Impressionen",
                        "CTR",
                        "Position",
                        "Δ Klicks",
                    ],
                    pair_table,
                ),
                "",
            ]
        )

        opportunities = _opportunities(segment, data)
        opportunity_table = [
            [
                _md(pair.query),
                _md(_display(data, pair.url)),
                str(pair.impressions),
                _format_ctr(pair.ctr),
                _format_position(pair.position),
            ]
            for pair in opportunities[:15]
        ]
        lines.extend(
            [
                "### Chancen mit vorhandenen Impressionen",
                "",
                "Position 5–20, mindestens die konfigurierte Impressionen-Schwelle "
                "und eine CTR unter 5 %. Das ist eine Priorisierungshilfe, keine "
                "Rankinggarantie.",
                "",
                *_table(
                    [
                        "Suchanfrage",
                        "Zielseite",
                        "Impressionen",
                        "CTR",
                        "Position",
                    ],
                    opportunity_table,
                ),
                "",
            ]
        )

        cannibalization = _cannibalization(segment, data)
        cannibalization_table = [
            [
                _md(item["query"]),
                str(item["urls"]),
                str(item["impressions"]),
                str(item["clicks"]),
                _format_position(item["best_position"]),
            ]
            for item in cannibalization[:15]
        ]
        lines.extend(
            [
                "### Mehrere URLs für dieselbe Suchanfrage",
                "",
                "Mehrere belegte Zielseiten können auf Kannibalisierung oder auf "
                "legitime Varianten hindeuten. Die Entscheidung braucht Kontext, "
                "nicht nur die Anzahl der URLs.",
                "",
                *_table(
                    [
                        "Suchanfrage",
                        "URLs",
                        "Impressionen",
                        "Klicks",
                        "beste Position",
                    ],
                    cannibalization_table,
                ),
                "",
            ]
        )
        for item in cannibalization[:10]:
            links = ", ".join(
                _md(_display(data, pair.url)) for pair in item["pairs"][:5]
            )
            lines.append(f"- **{_md(item['query'])}:** {links}")
        if cannibalization:
            lines.append("")

    lines.extend(
        [
            "## Grenzen",
            "",
            "- Nur eindeutig zugeordnete GSC-Zeilen werden gezeigt; nicht zuordenbare "
            "oder mehrdeutige Zeilen stehen im technischen Audit.",
            "- CTR ist Klicks geteilt durch Impressionen, keine erwartete CTR.",
            "- Die Position ist der GSC-Durchschnitt, keine tägliche Rangposition.",
            "- Ohne Vergleichszeitraum entfallen Delta-Werte.",
            "- Die Auswertung ersetzt keine Suchintentions- oder Wettbewerbsanalyse.",
            "",
            "## Rohdaten",
            "",
            "- [Query-/Seitenzeilen](raw_data/gsc_query_pages.csv)",
            "",
        ]
    )
    return "\n".join(lines)


def write_gsc_query_pages_csv(path: Path, data: RunData) -> None:
    rows: list[list[Any]] = []
    for segment in segments(data):
        previous = {
            (pair.url_id, pair.query): pair for pair in segment.previous_pairs
        }
        dataset = segment.dataset
        for pair in segment.pairs:
            before = previous.get((pair.url_id, pair.query))
            rows.append(
                [
                    dataset["property"],
                    dataset["search_type"],
                    dataset["country"] or "",
                    dataset["device"] or "",
                    dataset["period_start"],
                    dataset["period_end"],
                    pair.url,
                    pair.query,
                    pair.clicks,
                    pair.impressions,
                    "" if pair.ctr is None else round(pair.ctr, 6),
                    "" if pair.position is None else pair.position,
                    "" if before is None else before.clicks,
                    "" if before is None else before.impressions,
                    "" if before is None or before.ctr is None else round(before.ctr, 6),
                    "" if before is None or before.position is None else before.position,
                ]
            )
    _write_csv(
        path,
        [
            "property",
            "search_type",
            "country",
            "device",
            "period_start",
            "period_end",
            "url",
            "query",
            "clicks",
            "impressions",
            "ctr",
            "position",
            "previous_clicks",
            "previous_impressions",
            "previous_ctr",
            "previous_position",
        ],
        rows,
    )


def write_gsc_query_report(folder: Path, data: RunData) -> None:
    (folder / "raw_data").mkdir(parents=True, exist_ok=True)
    (folder / "04_GSC_QUERY_PAGES.md").write_text(
        render_gsc_query_pages(data).rstrip() + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_gsc_query_pages_csv(folder / "raw_data" / "gsc_query_pages.csv", data)
