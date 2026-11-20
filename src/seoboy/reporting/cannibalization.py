"""Keyword cannibalization analysis from GSC and on-page evidence."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
import csv
import re
from typing import Any, Iterable
from urllib.parse import urlsplit

from seoboy.analysis.audit_data import RunData
from seoboy.reporting.gsc_report import Pair, segments
from seoboy.shared.urls import resolve_url
from seoboy.shared.util import excel_safe

STOPWORDS = {
    "aber", "alle", "allem", "allen", "aller", "alles", "als", "also", "am", "an",
    "auch", "auf", "aus", "bei", "beim", "bin", "bis", "bist", "da", "damit",
    "dann", "das", "dass", "dein", "deine", "dem", "den", "der", "des", "die",
    "dies", "diese", "diesem", "diesen", "dieser", "dieses", "doch", "dort", "du",
    "durch", "ein", "eine", "einem", "einen", "einer", "eines", "er", "es", "für",
    "hat", "hier", "ich", "ihm", "ihn", "ihnen", "ihr", "ihre", "im", "in", "ist",
    "ja", "jede", "jeden", "jeder", "jedes", "kann", "kein", "keine", "mit", "nach",
    "nicht", "noch", "nur", "oder", "ohne", "über", "um", "und", "uns", "unser",
    "unsere", "unter", "vom", "von", "vor", "war", "was", "wenn", "wer", "wie",
    "wieder", "wir", "wird", "wo", "zu", "zum", "zur",
    "dj", "hochzeit", "hochzeiten", "event", "events", "veranstaltung",
    "startseite", "home", "kontakt", "impressum", "datenschutz", "agb",
}
UTILITY_PATHS = {
    "/impressum", "/datenschutz", "/agb", "/cookie-richtlinie", "/cookies",
    "/kontakt", "/login", "/warenkorb", "/checkout",
}
TOKEN_RE = re.compile(r"[a-z0-9äöüß][a-z0-9äöüß-]{2,}")


@dataclass(frozen=True)
class PageProfile:
    url_id: int
    url: str
    title_terms: frozenset[str]
    h1_terms: frozenset[str]
    content_terms: frozenset[str]
    canonical: tuple[str, ...]


@dataclass(frozen=True)
class OnPagePair:
    url_a: PageProfile
    url_b: PageProfile
    shared: tuple[str, ...]
    overlap: float
    content: float
    score: int


@dataclass(frozen=True)
class GscPair:
    query: str
    url_a: Pair
    url_b: Pair
    level: str
    onpage: OnPagePair | None


def _terms(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(
        token for token in TOKEN_RE.findall(value.casefold()) if token not in STOPWORDS
    )


def _path(value: str) -> str:
    try:
        return urlsplit(value).path.casefold().rstrip("/") or "/"
    except ValueError:
        return value.casefold().rstrip("/") or "/"


def _canonical(value: str | None) -> str:
    return (value or "").casefold().rstrip("/")


def _page_profiles(data: RunData) -> list[PageProfile]:
    profiles: list[PageProfile] = []
    all_urls = {_canonical(item.url) for item in data.urls.values()}
    for url_id, info in data.urls.items():
        if url_id not in data.page_url_ids or info.expected_indexable is False:
            continue
        observation = data.observation(url_id)
        if observation is None:
            continue
        signals = observation.signals or {}
        if signals.get("noindex"):
            continue
        path = _path(info.url)
        if path in UTILITY_PATHS or re.search(r"/(?:page|seite)/\d+/?$", path):
            continue
        raw_canonicals = list(signals.get("canonical") or []) + list(
            signals.get("canonical_header") or []
        )
        canonical = tuple(
            value
            for item in raw_canonicals
            if (value := resolve_url(info.url, str(item)))
        )
        consolidated = any(
            _canonical(value) in all_urls
            and _canonical(value) != _canonical(info.url)
            for value in canonical
        )
        if consolidated:
            continue
        title_terms = _terms(observation.title)
        h1_terms = _terms(signals.get("h1"))
        content_terms = frozenset(
            token.casefold()
            for token in (signals.get("content_terms") or {}).keys()
            if token.casefold() not in STOPWORDS
        )
        if not (title_terms or h1_terms):
            continue
        profiles.append(
            PageProfile(
                url_id=url_id,
                url=info.url,
                title_terms=title_terms,
                h1_terms=h1_terms,
                content_terms=content_terms,
                canonical=canonical,
            )
        )
    return profiles


def _onpage_pairs(profiles: list[PageProfile]) -> dict[tuple[int, int], OnPagePair]:
    result: dict[tuple[int, int], OnPagePair] = {}
    for left, right in combinations(profiles, 2):
        left_terms = left.title_terms | left.h1_terms
        right_terms = right.title_terms | right.h1_terms
        shared = tuple(sorted(left_terms & right_terms))
        if len(shared) < 2 or _canonical(left.url) == _canonical(right.url):
            continue
        overlap = len(shared) / max(1, min(len(left_terms), len(right_terms)))
        content = len(left.content_terms & right.content_terms) / max(
            1, len(left.content_terms | right.content_terms)
        )
        if overlap < 0.34 or content < 0.12:
            continue
        score = round(100 * (0.65 * overlap + 0.35 * content))
        key = tuple(sorted((left.url_id, right.url_id)))
        candidate = OnPagePair(left, right, shared, overlap, content, score)
        current = result.get(key)
        if current is None or candidate.score > current.score:
            result[key] = candidate
    return result


def _brand_terms(data: RunData) -> frozenset[str]:
    host = (urlsplit(data.config.start_url).hostname or "").casefold()
    return frozenset(part for part in re.split(r"[.\-]", host) if part)


def _is_brand_query(query: str, brands: frozenset[str]) -> bool:
    tokens = set(TOKEN_RE.findall(query.casefold()))
    meaningful = {
        value for value in brands if len(value) >= 3 and value not in {"www", "com", "de"}
    }
    return bool(meaningful) and meaningful.issubset(tokens)


def _gsc_pairs(
    data: RunData, onpage: dict[tuple[int, int], OnPagePair]
) -> list[GscPair]:
    brands = _brand_terms(data)
    minimum = data.config.gsc.multi_url_min_impressions
    result: list[GscPair] = []
    seen: set[tuple[str, int, int]] = set()
    for segment in segments(data):
        by_query: dict[str, list[Pair]] = {}
        for pair in segment.pairs:
            if pair.impressions >= minimum and pair.query:
                by_query.setdefault(pair.query, []).append(pair)
        for query, pairs in by_query.items():
            significant = sorted(pairs, key=lambda item: item.impressions, reverse=True)[:5]
            if len(significant) < 2 or _is_brand_query(query, brands):
                continue
            for left, right in combinations(significant, 2):
                key = (
                    query,
                    min(left.url_id, right.url_id),
                    max(left.url_id, right.url_id),
                )
                if key in seen:
                    continue
                seen.add(key)
                onpage_pair = onpage.get((key[1], key[2]))
                positions = [left.position, right.position]
                if any(value is None or value > 50 for value in positions):
                    level = "C"
                elif onpage_pair is not None:
                    level = "A"
                else:
                    level = "B"
                result.append(GscPair(query, left, right, level, onpage_pair))
    return result


def analyze(data: RunData) -> tuple[list[GscPair], list[OnPagePair]]:
    profiles = _page_profiles(data)
    onpage_map = _onpage_pairs(profiles)
    gsc_pairs = _gsc_pairs(data, onpage_map)
    used = {
        tuple(sorted((pair.url_a.url_id, pair.url_b.url_id)))
        for pair in gsc_pairs
        if pair.onpage is not None
    }
    only_onpage = [pair for key, pair in onpage_map.items() if key not in used]
    only_onpage.sort(key=lambda item: item.score, reverse=True)
    return gsc_pairs, only_onpage[:50]


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _csv(path: Path, rows: Iterable[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(
            [
                "evidence_level", "query", "url_a", "url_b",
                "impressions_a", "impressions_b", "clicks_a", "clicks_b",
                "position_a", "position_b", "shared_terms",
                "content_similarity", "onpage_score", "assessment",
            ]
        )
        for row in rows:
            writer.writerow([excel_safe(value) for value in row])


def write_cannibalization_report(folder: Path, data: RunData) -> bool:
    gsc_pairs, onpage_pairs = analyze(data)
    raw = folder / "raw_data"
    raw.mkdir(parents=True, exist_ok=True)
    rows: list[list[Any]] = []
    for pair in gsc_pairs:
        rows.append(
            [
                pair.level,
                pair.query,
                pair.url_a.url,
                pair.url_b.url,
                pair.url_a.impressions,
                pair.url_b.impressions,
                pair.url_a.clicks,
                pair.url_b.clicks,
                pair.url_a.position if pair.url_a.position is not None else "",
                pair.url_b.position if pair.url_b.position is not None else "",
                ", ".join(pair.onpage.shared) if pair.onpage else "",
                round(pair.onpage.content, 3) if pair.onpage else "",
                pair.onpage.score if pair.onpage else "",
                {
                    "A": "GSC- und On-Page-Evidenz",
                    "B": "GSC-Evidenz, On-Page nicht bestätigt",
                    "C": "schwaches GSC-Signal oder On-Page only",
                }[pair.level],
            ]
        )
    for pair in onpage_pairs:
        rows.append(
            [
                "C", "", pair.url_a.url, pair.url_b.url, "", "", "", "", "", "",
                ", ".join(pair.shared), round(pair.content, 3), pair.score,
                "On-Page-Kandidat ohne GSC-Paar",
            ]
        )
    _csv(raw / "keyword_cannibalization.csv", rows)
    has_gsc = any(dataset["grain"] == "page_query" for dataset in data.datasets)
    lines = [
        "# Keyword-Kannibalisierung",
        "",
        "Diese Auswertung kombiniert GSC-Query-/URL-Evidenz mit Title-/H1- und Inhaltssignalen.",
        "Sie ist eine Prüfhilfe, kein automatischer Nachweis und keine Freigabe für eine URL-Änderung.",
        "",
        f"**GSC-Page-Query-Daten:** {'vorhanden' if has_gsc else 'fehlen'}  ",
        f"**Schwelle je URL:** {data.config.gsc.multi_url_min_impressions} Impressionen  ",
        f"**Kandidaten:** {len(gsc_pairs)} GSC-Paar(e), {len(onpage_pairs)} On-Page-Paar(e)",
        "",
        "## Evidenzstufen",
        "",
        "- A: GSC-Paar plus On-Page-Überlappung. Stärkster Kandidat, vor einer Änderung",
        "  im GSC-Verlauf und in der internen Verlinkung prüfen.",
        "- B: GSC-Paar, aber keine bestätigte On-Page-Überlappung. Kann auch SERP-Diversität",
        "  oder eine bewusste Query-Abdeckung sein.",
        "- C: On-Page-Kandidat ohne belastbares GSC-Paar oder schwaches GSC-Signal. Nur ein Hinweis.",
        "",
        "## Kandidaten",
        "",
    ]
    if not gsc_pairs and not onpage_pairs:
        lines.extend(
            [
                "Keine Kandidaten mit den aktuellen Schwellenwerten gefunden.",
                "",
                "Das ist keine Garantie gegen Kannibalisierung: fehlende GSC-Daten, anonymisierte",
                "Suchanfragen, begrenzte GSC-Zeilen und die Title-/H1-Heuristik können Treffer",
                "verhindern.",
            ]
        )
    elif gsc_pairs:
        lines.extend(
            [
                "| Stufe | Suchanfrage | URL A | URL B | Impr. A/B | Pos. A/B | Gemeinsame Begriffe | Inhalt |",
                "| --- | --- | --- | --- | ---: | ---: | --- | ---: |",
            ]
        )
        for pair in gsc_pairs:
            lines.append(
                "| "
                + " | ".join(
                    [
                        pair.level,
                        _cell(pair.query),
                        _cell(pair.url_a.url),
                        _cell(pair.url_b.url),
                        f"{pair.url_a.impressions}/{pair.url_b.impressions}",
                        f"{pair.url_a.position if pair.url_a.position is not None else '–'}/"
                        f"{pair.url_b.position if pair.url_b.position is not None else '–'}",
                        _cell(", ".join(pair.onpage.shared) if pair.onpage else "–"),
                        f"{pair.onpage.content:.2f}" if pair.onpage else "–",
                    ]
                )
                + " |"
            )
    if onpage_pairs:
        lines.extend(["", "## On-Page-Kandidaten ohne GSC-Bestätigung", ""])
        for pair in onpage_pairs[:25]:
            lines.append(
                f"- {pair.url_a.url} ↔ {pair.url_b.url}: "
                f"{_cell(', '.join(pair.shared))} (Score {pair.score})"
            )
    lines.extend(
        [
            "",
            "## Warum das nicht immer eindeutig ist",
            "",
            "- GSC-Zeilen sind begrenzt, teils anonymisiert und nicht jede URL ist zugeordnet.",
            "- Ein Query-Paar kann bewusste SERP-Diversität sein, etwa Kategorie und Detailseite.",
            "- Title/H1 sind eine Heuristik; es wird kein Volltext gespeichert oder verglichen.",
            "- Marken-/navigationale Queries werden ausgeschlossen, können aber in Randfällen",
            "  als Kannibalisierung erscheinen.",
            "- Kanonische Duplikate, Pagination und Utility-Seiten werden gefiltert.",
            "",
            "## Empfohlene Prüfung",
            "",
            "1. GSC-Verlauf der beiden URLs vergleichen: Klicks, Impressionen und Positionen.",
            "2. Suchintention und Zielgruppe der Seiten prüfen.",
            "3. Eine klare Hauptseite festlegen; Canonical, interne Links und Inhalt ausrichten.",
            "4. Änderung erst nach Sicherung des Verlaufs umsetzen und danach erneut messen.",
            "",
            "## Rohdaten",
            "",
            "- [Kandidaten](raw_data/keyword_cannibalization.csv)",
            "",
        ]
    )
    (folder / "08_KEYWORD_CANNIBALIZATION.md").write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n"
    )
    return True
