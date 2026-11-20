"""Subpage and content analysis for a stored run."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

from seoboy.analysis.audit_data import RunData
from seoboy.shared.urls import relative_url
from seoboy.shared.util import excel_safe

STATUS_LABELS = {
    "running": "Läuft",
    "paused": "Pausiert",
    "completed": "Abgeschlossen",
    "partial": "Teillauf",
    "failed": "Fehlgeschlagen",
}


def _display(data: RunData, url: str) -> str:
    return relative_url(url, data.config.allowed_hosts)


def _md(value: Any) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def _content_label(row: dict[str, Any]) -> str:
    if row["is_html"]:
        return "HTML"
    content_type = row["content_type"] or ""
    if "pdf" in content_type:
        return "PDF"
    if content_type:
        return content_type.split(";", 1)[0]
    return "–"


def _index_label(value: bool | None) -> str:
    if value is True:
        return "ja"
    if value is False:
        return "nein"
    return "nicht bewertet"


def _write_csv(path: Path, header: list[str], rows: Iterable[Iterable[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow([excel_safe(value) for value in row])


def page_analysis_rows(data: RunData) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for url_id in sorted(data.page_url_ids, key=lambda value: data.url_string(value)):
        info = data.urls.get(url_id)
        if info is None:
            continue
        attempt = data.final_attempt(url_id)
        observation = data.observation(url_id)
        signals = observation.signals if observation else {}
        status = attempt.status_code if attempt is not None else None
        content_type = (attempt.content_type or "").lower() if attempt is not None else ""
        is_html = observation is not None
        title = observation.title if observation is not None else None
        description = observation.meta_description if observation is not None else None
        has_metrics = "h1_count" in signals
        if is_html and has_metrics:
            evaluation = "html"
        elif is_html:
            evaluation = "html_without_metrics"
        elif status is not None and 200 <= status < 300 and content_type:
            evaluation = "non_html"
        elif status is not None and 300 <= status < 400:
            evaluation = "redirect"
        elif status is not None and status >= 400:
            evaluation = "http_error"
        else:
            evaluation = "not_fetched"
        indexable: bool | None = None
        if is_html and status is not None and 200 <= status < 300:
            indexable = not bool(signals.get("noindex"))
        canonicals = signals.get("canonical")
        canonical = str(canonicals[0]) if isinstance(canonicals, list) and canonicals else None
        schema_types = signals.get("schema_types")
        rows.append(
            {
                "url": info.url,
                "page_type": info.page_type or "–",
                "business_value": info.business_value,
                "status": status,
                "content_type": content_type or None,
                "evaluation": evaluation,
                "is_html": is_html,
                "indexable": indexable,
                "title": title,
                "title_length": int(signals.get("title_length", len(title or "")) or 0),
                "description_length": int(
                    signals.get("description_length", len(description or "")) or 0
                ),
                "h1": signals.get("h1") if has_metrics else None,
                "h1_count": int(signals.get("h1_count", 0) or 0) if has_metrics else None,
                "word_count": int(signals.get("word_count", 0) or 0) if has_metrics else None,
                "image_count": int(signals.get("image_count", 0) or 0) if has_metrics else None,
                "images_missing_alt": (
                    int(signals.get("images_missing_alt", 0) or 0) if has_metrics else None
                ),
                "schema_types": (
                    tuple(str(value) for value in schema_types if value)
                    if isinstance(schema_types, list)
                    else ()
                ),
                "internal_links": int(signals.get("link_count", 0) or 0),
                "click_depth": info.click_depth,
                "canonical": canonical,
                "has_metrics": has_metrics,
            }
        )
    return rows


def render_page_analysis(data: RunData) -> str:
    run = data.run
    rows = page_analysis_rows(data)
    html_rows = [row for row in rows if row["has_metrics"]]
    html_targets = [row for row in rows if row["is_html"]]
    indexable = sum(1 for row in rows if row["indexable"] is True)
    non_html = sum(1 for row in rows if row["evaluation"] == "non_html")
    not_evaluated = sum(
        1
        for row in rows
        if row["evaluation"] in {"http_error", "redirect", "not_fetched"}
    )
    missing_title = sum(1 for row in html_rows if not row["title"])
    short_title = sum(1 for row in html_rows if row["title"] and row["title_length"] < 30)
    long_title = sum(1 for row in html_rows if row["title"] and row["title_length"] > 60)
    missing_description = sum(1 for row in html_rows if row["description_length"] == 0)
    short_description = sum(1 for row in html_rows if 0 < row["description_length"] < 70)
    long_description = sum(1 for row in html_rows if row["description_length"] > 160)
    missing_h1 = sum(1 for row in html_rows if row["h1_count"] == 0)
    multiple_h1 = sum(1 for row in html_rows if (row["h1_count"] or 0) > 1)
    thin = sum(1 for row in html_rows if (row["word_count"] or 0) < 300)
    average_words = (
        round(sum(int(row["word_count"] or 0) for row in html_rows) / len(html_rows))
        if html_rows
        else 0
    )
    with_schema = sum(1 for row in html_rows if row["schema_types"])
    missing_alt = sum(int(row["images_missing_alt"] or 0) for row in html_rows)

    lines = [
        "# SeoBoy – Unterseiten- und Inhaltsanalyse",
        "",
        f"**Lauf:** {run['run_id']} · **Status:** {STATUS_LABELS.get(run['status'], run['status'])}",
        "",
        "Die Analyse bewertet jede zugelassene Seite anhand des gespeicherten HTML-Extrakts. "
        "Titel- und Beschreibungslängen sind Heuristiken, keine Google-Grenzwerte. "
        "Seiten ohne HTML-Beobachtung werden nicht als Inhaltsfehler gezählt.",
        "",
    ]
    if not html_rows:
        lines.extend(
            [
                "Hinweis: Dieser Lauf enthält noch keine Inhaltsmetriken. Bitte mit "
                "SeoBoy 0.4.0 oder neuer neu crawlen.",
                "",
            ]
        )
    lines.extend(
        [
        "## Übersicht",
        "",
        "| Kennzahl | Wert |",
        "| --- | ---: |",
        f"| Seiten im Lauf | {len(rows)} |",
        f"| HTML-Seiten mit Inhaltsmetriken | {len(html_rows)} |",
        f"| technisch indexierbar | {indexable} von {len(html_targets)} HTML-Seiten |",
        f"| Nicht-HTML-Ziele (nicht bewertet) | {non_html} |",
        f"| HTTP-Fehler/Weiterleitungen (nicht bewertet) | {not_evaluated} |",
        f"| Titel fehlt | {missing_title} |",
        f"| Titel kürzer als 30 Zeichen | {short_title} |",
        f"| Titel länger als 60 Zeichen | {long_title} |",
        f"| Meta-Beschreibung fehlt | {missing_description} |",
        f"| Beschreibung kürzer als 70 Zeichen | {short_description} |",
        f"| Beschreibung länger als 160 Zeichen | {long_description} |",
        f"| H1 fehlt | {missing_h1} |",
        f"| mehrere H1 | {multiple_h1} |",
        f"| weniger als 300 Wörter | {thin} |",
        f"| durchschnittliche Wortzahl | {average_words} |",
        f"| Seiten mit strukturierten Daten | {with_schema} |",
        f"| Bilder ohne nicht-leeren Alt-Text | {missing_alt} |",
        "",
        "## Auffällige Seiten",
        "",
        ]
    )
    groups = [
        ("Titel fehlt", [row for row in html_rows if not row["title"]], lambda row: "–"),
        (
            "Titel zu kurz (< 30 Zeichen)",
            [row for row in html_rows if row["title"] and row["title_length"] < 30],
            lambda row: f"{row['title_length']} Zeichen",
        ),
        (
            "Titel zu lang (> 60 Zeichen)",
            [row for row in html_rows if row["title"] and row["title_length"] > 60],
            lambda row: f"{row['title_length']} Zeichen",
        ),
        (
            "Meta-Beschreibung fehlt",
            [row for row in html_rows if row["description_length"] == 0],
            lambda row: "–",
        ),
        (
            "H1 fehlt",
            [row for row in html_rows if row["h1_count"] == 0],
            lambda row: "kein H1",
        ),
        (
            "Mehrere H1",
            [row for row in html_rows if (row["h1_count"] or 0) > 1],
            lambda row: f"{row['h1_count']} H1",
        ),
        (
            "Weniger als 300 Wörter",
            [row for row in html_rows if (row["word_count"] or 0) < 300],
            lambda row: f"{row['word_count']} Wörter",
        ),
        (
            "Bilder ohne Alt-Text",
            [row for row in html_rows if (row["images_missing_alt"] or 0) > 0],
            lambda row: f"{row['images_missing_alt']} Bild(er)",
        ),
    ]
    for title, members, detail in groups:
        lines.extend([f"### {title} ({len(members)})", ""])
        if not members:
            lines.extend(["Keine Auffälligkeiten.", ""])
            continue
        for row in members[:15]:
            lines.append(f"- {_display(data, row['url'])} – {detail(row)}")
        if len(members) > 15:
            lines.append(f"- … {len(members) - 15} weitere laut CSV")
        lines.append("")

    lines.extend(
        [
            "## Seitenübersicht",
            "",
            "| Seite | Typ | Inhalt | HTTP | Indexierbar | Titel | Beschreibung | H1 | Wörter | Alt fehlt | Schema | Tiefe |",
            "| --- | --- | --- | ---: | :---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
        ]
    )
    for row in rows[:100]:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(_display(data, row["url"])),
                    _md(row["page_type"]),
                    _md(_content_label(row)),
                    str(row["status"] if row["status"] is not None else "–"),
                    _index_label(row["indexable"]),
                    str(row["title_length"]) if row["is_html"] else "–",
                    str(row["description_length"]) if row["is_html"] else "–",
                    str(row["h1_count"] if row["h1_count"] is not None else "–"),
                    str(row["word_count"] if row["word_count"] is not None else "–"),
                    str(row["images_missing_alt"] if row["images_missing_alt"] is not None else "–"),
                    ", ".join(row["schema_types"]) or "–",
                    str(row["click_depth"] if row["click_depth"] is not None else "–"),
                ]
            )
            + " |"
        )
    if len(rows) > 100:
        lines.append(f"| … {len(rows) - 100} weitere Seiten in raw_data/pages.csv | | | | | | | | | | |")
    lines.extend(
        [
            "",
            "## Rohdaten",
            "",
            "- [Seitenmetriken](raw_data/pages.csv)",
            "",
            "Die Wortzahl umfasst den sichtbaren Body-Text ohne Script-, Style- und "
            "JSON-LD-Inhalte. Titel- und Beschreibungslängen zählen Zeichen, nicht Pixel.",
            "Nicht-HTML-Ziele wie PDFs sowie HTTP-Fehler und Weiterleitungen werden "
            "nicht als Inhalts- oder Indexierungsfehler bewertet und erscheinen als "
            "'nicht bewertet'.",
            "",
        ]
    )
    return "\n".join(lines)


def write_page_analysis_csv(path: Path, data: RunData) -> None:
    rows = page_analysis_rows(data)
    _write_csv(
        path,
        [
            "url",
            "page_type",
            "business_value",
            "http_status",
            "content_type",
            "evaluation",
            "indexable",
            "title",
            "title_length",
            "description_length",
            "h1",
            "h1_count",
            "word_count",
            "image_count",
            "images_missing_alt",
            "schema_types",
            "internal_links",
            "click_depth",
            "canonical",
        ],
        [
            [
                row["url"],
                row["page_type"],
                row["business_value"],
                row["status"] if row["status"] is not None else "",
                row["content_type"] or "",
                row["evaluation"],
                "1" if row["indexable"] is True else "0" if row["indexable"] is False else "",
                row["title"] or "",
                row["title_length"],
                row["description_length"],
                row["h1"] or "",
                row["h1_count"] if row["h1_count"] is not None else "",
                row["word_count"] if row["word_count"] is not None else "",
                row["image_count"] if row["image_count"] is not None else "",
                row["images_missing_alt"] if row["images_missing_alt"] is not None else "",
                "|".join(row["schema_types"]),
                row["internal_links"],
                row["click_depth"] if row["click_depth"] is not None else "",
                row["canonical"] or "",
            ]
            for row in rows
        ],
    )
