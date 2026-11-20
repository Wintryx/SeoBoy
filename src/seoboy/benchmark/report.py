"""Markdown and CSV output for the competitor benchmark."""

from __future__ import annotations

from collections import Counter
import csv
import math
from pathlib import Path
import re
from typing import Any, Iterable

from seoboy.benchmark.sampler import PageMetric, SiteSnapshot
from seoboy.shared.util import excel_safe

_STOPWORDS = {
    "aber", "alle", "alles", "auch", "auf", "aus", "bei", "beim", "bin", "bis",
    "bist", "dann", "das", "dass", "dem", "den", "der", "des", "die", "dies",
    "doch", "dort", "ein", "eine", "einem", "einen", "einer", "eines", "für",
    "hat", "hier", "ich", "im", "in", "ist", "ja", "kann", "mit", "nach",
    "nicht", "noch", "nur", "oder", "ohne", "sich", "sie", "sind", "so",
    "über", "und", "uns", "von", "vor", "war", "was", "wenn", "wer", "wie",
    "wird", "wo", "zu", "zum", "zur", "the", "and", "for", "with", "from",
    "this", "that", "your", "you", "our", "are", "was", "were", "has", "have",
    "not", "but", "all", "can", "will", "more", "one", "two", "der", "die",
    "kreis", "buchen", "seite", "seiten", "mehr", "unsere", "unser", "deine",
    "dein", "eure", "euer", "wird", "werden", "sind", "haben", "können",
    "sowie", "dich", "dir", "mich", "mir", "als", "wir", "ihr", "schon",
    "sehr", "diese", "dieser", "dieses", "hier", "dort", "ohne", "unter",
    "über", "durch", "gegen", "wenn", "dann", "aber", "auch", "euch", "eure",
    "euren", "eurem", "eurer", "deine", "deinen", "deinem", "deiner", "meine",
    "meinen", "meinem", "meiner", "keine", "keinen", "keinem", "keiner",
    "dabei", "jetzt", "selbst", "wann", "warum", "welche", "welcher", "welches",
    "diesem", "diesen", "kann", "können", "muss", "müssen", "soll", "sollen",
    "will", "wollen", "habe", "haben", "hat", "hatte", "hatten", "bin", "bist",
    "war", "waren", "wäre", "wären", "sich", "uns", "ihnen", "ihm", "ihn",
    "ihre", "ihren", "ihrem", "ihrer", "mein", "dein", "euer", "unser",
    "kopieren", "tipp", "tipps", "wirklich", "schnell", "erste", "ersten",
    "richtige", "richtigen", "machen", "macht", "könnt", "möglichkeiten",
    "besonders", "viele", "viel", "teil", "voraus", "wochen", "platz",
    "unterschied", "abschnitt", "meta", "media",
}


def _terms(snapshot: SiteSnapshot) -> Counter[str]:
    counts: Counter[str] = Counter()
    for page in snapshot.pages:
        if not page.has_content:
            continue
        text = " ".join(value for value in (page.title, page.h1) if value)
        for term in re.findall(r"[A-Za-zÄÖÜäöüß0-9]{4,}", text.casefold()):
            if term not in _STOPWORDS and not term.isdigit():
                counts[term] += 1
    return counts


def content_gaps(
    own: SiteSnapshot, competitors: list[SiteSnapshot]
) -> list[tuple[str, int, list[int]]]:
    own_terms = _terms(own)
    competitor_terms = [_terms(snapshot) for snapshot in competitors]
    brand_terms = {
        term
        for snapshot in competitors
        for term in re.findall(r"[A-Za-zÄÖÜäöüß0-9]{4,}", snapshot.label.casefold())
    }
    candidates: list[tuple[int, str, list[int]]] = []
    for term in {term for counts in competitor_terms for term in counts}:
        if own_terms[term] > 0 or term in brand_terms:
            continue
        frequencies = [counts[term] for counts in competitor_terms]
        score = sum(frequencies)
        if score:
            candidates.append((score, term, frequencies))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [(term, own_terms[term], frequencies) for _, term, frequencies in candidates[:20]]


def _brand_terms(competitors: list[SiteSnapshot]) -> set[str]:
    return {
        term
        for snapshot in competitors
        for term in re.findall(r"[A-Za-zÄÖÜäöüß0-9]{4,}", snapshot.label.casefold())
    }


def _term_stats(snapshot: SiteSnapshot) -> tuple[Counter[str], Counter[str], int]:
    counts: Counter[str] = Counter()
    page_counts: Counter[str] = Counter()
    pages = 0
    for page in snapshot.pages:
        if not page.has_content or not page.content_terms:
            continue
        pages += 1
        for term, count in page.content_terms.items():
            if count <= 0:
                continue
            counts[term] += count
            page_counts[term] += 1
    return counts, page_counts, pages


def content_gaps_tfidf(
    own: SiteSnapshot, competitors: list[SiteSnapshot]
) -> list[dict[str, Any]]:
    own_counts, own_pages, own_total = _term_stats(own)
    competitor_stats = [_term_stats(snapshot) for snapshot in competitors]
    if own_total == 0 or not any(item[2] for item in competitor_stats):
        return []
    total_pages = own_total + sum(item[2] for item in competitor_stats)
    brand_terms = _brand_terms(competitors)
    terms: set[str] = set()
    for _counts, page_counts, _total in competitor_stats:
        terms.update(page_counts)
    candidates: list[dict[str, Any]] = []
    for term in terms:
        if term in _STOPWORDS or term.isdigit() or len(term) < 4 or term in brand_terms:
            continue
        comp_counts = [item[0][term] for item in competitor_stats]
        comp_pages = [item[1][term] for item in competitor_stats]
        comp_totals = [item[2] for item in competitor_stats]
        coverage = sum(1 for value in comp_pages if value > 0) / len(
            competitor_stats
        )
        comp_rate = sum(comp_counts) / max(1, sum(comp_totals))
        if own_pages[term] > 0:
            continue
        if coverage < 0.5:
            continue
        df = (1 if own_pages[term] > 0 else 0) + sum(
            1 for value in comp_pages if value > 0
        )
        idf = math.log((1 + total_pages) / (1 + df)) + 1
        score = coverage * math.log1p(comp_rate) * idf
        if score <= 0:
            continue
        candidates.append(
            {
                "term": term,
                "own_count": own_counts[term],
                "own_pages": own_pages[term],
                "competitor_pages": comp_pages,
                "competitor_counts": comp_counts,
                "coverage": coverage,
                "tfidf": score,
            }
        )
    candidates.sort(
        key=lambda item: (-item["tfidf"], -item["coverage"], item["term"])
    )
    return candidates[:30]


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

    gaps = content_gaps(own, competitors)
    if gaps:
        lines.extend(
            [
                "## Begriffskandidaten aus Titeln und H1",
                "",
                "Begriffe, die in den Wettbewerber-Titeln/-H1 vorkommen, in der eigenen "
                "Stichprobe aber nicht. Diese Liste ist oberflächlich; die inhaltliche "
                "Gewichtung steht im folgenden TF-IDF-Abschnitt.",
                "",
                "| Begriff | Eigene Seite | " + " | ".join(snapshot.label for snapshot in competitors) + " |",
                "| --- | ---: | " + " | ".join("---:" for _ in competitors) + " |",
            ]
        )
        for term, own_count, frequencies in gaps:
            lines.append(
                f"| {term} | {own_count} | "
                + " | ".join(str(value) for value in frequencies)
                + " |"
            )
        lines.append("")

    content = content_gaps_tfidf(own, competitors)
    lines.extend(
        [
            "## Inhaltliche Begriffe (TF-IDF)",
            "",
            "Gewichtung aus den Termhäufigkeiten des Hauptinhalts. Gezeigt werden "
            "Begriffe, die bei mindestens der Hälfte der Wettbewerber vorkommen, in "
            "der eigenen Stichprobe aber fehlen. Marken- und Navigationsbegriffe "
            "werden gefiltert.",
            "",
        ]
    )
    if content:
        lines.extend(
            [
                "| Begriff | Eigene Seiten | "
                + " | ".join(snapshot.label for snapshot in competitors)
                + " | TF-IDF |",
                "| --- | ---: | "
                + " | ".join("---:" for _ in competitors)
                + " | ---: |",
            ]
        )
        for item in content:
            lines.append(
                f"| {item['term']} | {item['own_pages']} | "
                + " | ".join(str(value) for value in item["competitor_pages"])
                + f" | {item['tfidf']:.2f} |"
            )
        lines.append("")
    else:
        lines.extend(
            [
                "Keine auswertbaren Content-Terme vorhanden. Für diese Auswertung "
                "muss der eigene Lauf mit einem Crawler ab Version 5 neu erstellt "
                "werden.",
                "",
            ]
        )

    lines.extend(
        [
            "## Rohdaten",
            "",
            "- [Seitenmetriken](raw_data/benchmark_pages.csv)",
            "- [Begriffskandidaten](raw_data/benchmark_terms.csv)",
            "- [TF-IDF-Begriffe](raw_data/benchmark_content_terms.csv)",
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


def write_benchmark_terms_csv(
    path: Path, own: SiteSnapshot, competitors: list[SiteSnapshot]
) -> None:
    gaps = content_gaps(own, competitors)
    _write_csv(
        path,
        ["term", "own_count", *[snapshot.label for snapshot in competitors]],
        [
            [term, own_count, *frequencies]
            for term, own_count, frequencies in gaps
        ],
    )


def write_benchmark_content_terms_csv(
    path: Path, own: SiteSnapshot, competitors: list[SiteSnapshot]
) -> None:
    rows = content_gaps_tfidf(own, competitors)
    header = [
        "term",
        "own_pages",
        "own_count",
        "coverage",
        "tfidf",
        *[f"{snapshot.label}_pages" for snapshot in competitors],
        *[f"{snapshot.label}_count" for snapshot in competitors],
    ]
    _write_csv(
        path,
        header,
        [
            [
                item["term"],
                item["own_pages"],
                item["own_count"],
                item["coverage"],
                round(item["tfidf"], 6),
                *item["competitor_pages"],
                *item["competitor_counts"],
            ]
            for item in rows
        ],
    )


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
