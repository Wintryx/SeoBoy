"""Markdown and CSV output for the competitor benchmark."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

from seoboy.benchmark.sampler import PageMetric, SiteSnapshot
from seoboy.shared.util import excel_safe


def _content_pages(snapshot: SiteSnapshot) -> list[PageMetric]:
    return [page for page in snapshot.pages if page.has_content]


def _percent(value: int, total: int) -> str:
    if total == 0:
        return "–"
    return f"{value / total * 100:.0f} %"


def _summary(snapshot: SiteSnapshot) -> dict[str, Any]:
    pages = _content_pages(snapshot)
    total = len(pages)
    return {
        "fetched": len(snapshot.pages),
        "pages": total,
        "indexable": sum(1 for page in pages if page.indexable),
        "title_missing": sum(1 for page in pages if page.title_length == 0),
        "title_short": sum(1 for page in pages if 0 < page.title_length < 30),
        "title_long": sum(1 for page in pages if page.title_length > 60),
        "description_missing": sum(1 for page in pages if page.description_length == 0),
        "description_short": sum(1 for page in pages if 0 < page.description_length < 70),
        "description_long": sum(1 for page in pages if page.description_length > 160),
        "h1_missing": sum(1 for page in pages if page.h1_count == 0),
        "h1_multiple": sum(1 for page in pages if page.h1_count > 1),
        "thin": sum(1 for page in pages if page.word_count < 300),
        "schema": sum(1 for page in pages if page.schema_types),
        "missing_alt": sum(page.images_missing_alt for page in pages),
        "average_words": round(sum(page.word_count for page in pages) / total) if total else 0,
        "average_links": round(sum(page.internal_links for page in pages) / total) if total else 0,
        "sitemap_urls": snapshot.sitemap_urls,
    }


def _value(summary: dict[str, Any], key: str) -> str:
    total = int(summary["pages"])
    if key in {"pages", "fetched", "sitemap_urls", "average_words", "average_links", "missing_alt"}:
        return str(summary[key])
    return _percent(int(summary[key]), total)


def render_benchmark(
    own: SiteSnapshot,
    competitors: list[SiteSnapshot],
    *,
    run_id: str,
    max_pages: int,
) -> str:
    snapshots = [own, *competitors]
    summaries = [_summary(snapshot) for snapshot in snapshots]
    header = "| Kennzahl | " + " | ".join(snapshot.label for snapshot in snapshots) + " |"
    separator = "| --- | " + " | ".join("---:" for _ in snapshots) + " |"
    lines = [
        "# SeoBoy – Wettbewerbsvergleich",
        "",
        f"**Eigener Lauf:** {run_id}",
        f"**Stichprobe:** bis zu {max_pages} Seiten je Website, rein lesend, robots.txt wird respektiert.",
        "",
        "Der Vergleich ist eine Momentaufnahme der öffentlich erreichbaren Seiten. "
        "Wettbewerbsseiten werden nicht vollständig gecrawlt, sondern als Stichprobe "
        "aus Sitemap bzw. Startseitenlinks gezogen. Prozentwerte beziehen sich auf die "
        "jeweils ausgewerteten HTML-Seiten.",
        "",
        "## Kennzahlen",
        "",
        header,
        separator,
    ]
    rows = [
        ("abgerufene Seiten", "fetched"),
        ("HTML-Seiten ausgewertet", "pages"),
        ("technisch indexierbar", "indexable"),
        ("Titel fehlt", "title_missing"),
        ("Titel kürzer als 30 Zeichen", "title_short"),
        ("Titel länger als 60 Zeichen", "title_long"),
        ("Meta-Beschreibung fehlt", "description_missing"),
        ("Beschreibung kürzer als 70 Zeichen", "description_short"),
        ("Beschreibung länger als 160 Zeichen", "description_long"),
        ("H1 fehlt", "h1_missing"),
        ("mehrere H1", "h1_multiple"),
        ("weniger als 300 Wörter", "thin"),
        ("Seiten mit strukturierten Daten", "schema"),
        ("Bilder ohne Alt-Text", "missing_alt"),
        ("durchschnittliche Wortzahl", "average_words"),
        ("durchschnittliche Links", "average_links"),
        ("Sitemap-URLs", "sitemap_urls"),
    ]
    for label, key in rows:
        lines.append("| " + label + " | " + " | ".join(_value(summary, key) for summary in summaries) + " |")

    lines.extend(["", "## Einordnung", ""])
    for snapshot, summary in zip(snapshots, summaries):
        lines.append(f"### {snapshot.label}")
        lines.append("")
        if snapshot.error:
            lines.append(f"Nicht auswertbar: {snapshot.error}.")
            lines.append("")
            continue
        lines.append(
            f"- Start: {snapshot.start_url} · final: {snapshot.final_url}"
        )
        lines.append(
            f"- {summary['pages']} HTML-Seiten, {summary['indexable']} technisch indexierbar, "
            f"Ø {summary['average_words']} Wörter, Ø {summary['average_links']} Links"
        )
        lines.append(
            f"- H1 fehlt: {summary['h1_missing']}, mehrere H1: {summary['h1_multiple']}, "
            f"unter 300 Wörter: {summary['thin']}, Bilder ohne Alt: {summary['missing_alt']}"
        )
        pages = _content_pages(snapshot)
        issues = [
            page
            for page in pages
            if page.h1_count == 0
            or page.word_count < 300
            or page.title_length == 0
            or page.title_length < 30
            or page.title_length > 60
            or page.description_length == 0
            or page.images_missing_alt > 0
        ]
        if issues:
            lines.extend(["", "Auffällige Seiten:", ""])
            for page in issues[:10]:
                reasons: list[str] = []
                if page.title_length == 0:
                    reasons.append("Titel fehlt")
                elif page.title_length < 30:
                    reasons.append("Titel kurz")
                elif page.title_length > 60:
                    reasons.append("Titel lang")
                if page.description_length == 0:
                    reasons.append("Beschreibung fehlt")
                if page.h1_count == 0:
                    reasons.append("H1 fehlt")
                elif page.h1_count > 1:
                    reasons.append("mehrere H1")
                if page.word_count < 300:
                    reasons.append(f"{page.word_count} Wörter")
                if page.images_missing_alt:
                    reasons.append(f"{page.images_missing_alt} Bilder ohne Alt")
                lines.append(f"- {page.url} – {', '.join(reasons)}")
            if len(issues) > 10:
                lines.append(f"- … {len(issues) - 10} weitere laut CSV")
        lines.append("")

    lines.extend(
        [
            "## Rohdaten",
            "",
            "- [Seitenmetriken](raw_data/benchmark_pages.csv)",
            "",
            "Die Stichprobe ersetzt kein vollständiges Audit der Wettbewerbsseiten. "
            "Sie dient der relativen Einordnung von Inhaltstiefe, Metadaten, H1-Struktur "
            "und strukturierten Daten.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_csv(path: Path, header: list[str], rows: Iterable[Iterable[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow([excel_safe(value) for value in row])


def write_benchmark_csv(path: Path, snapshots: list[SiteSnapshot]) -> None:
    rows: list[list[Any]] = []
    for snapshot in snapshots:
        for page in snapshot.pages:
            rows.append(
                [
                    snapshot.label,
                    page.url,
                    page.status if page.status is not None else "",
                    "1" if page.has_content else "0",
                    "1" if page.indexable else "0",
                    page.title_length,
                    page.description_length,
                    page.h1_count,
                    page.word_count,
                    page.image_count,
                    page.images_missing_alt,
                    "|".join(page.schema_types),
                    page.internal_links,
                ]
            )
    _write_csv(
        path,
        [
            "site",
            "url",
            "http_status",
            "has_content",
            "indexable",
            "title_length",
            "description_length",
            "h1_count",
            "word_count",
            "image_count",
            "images_missing_alt",
            "schema_types",
            "links",
        ],
        rows,
    )
