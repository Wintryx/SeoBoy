"""Local SEO checks for configured locations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import csv
import json
from pathlib import Path
import re
import time
from typing import Any, Iterable
from urllib.parse import urlsplit

import yaml

from seoboy.crawl.html_extract import ExtractedPage, extract_page
from seoboy.crawl.http_client import HttpClient, decode_body
from seoboy.shared.agents import SEOBOY
from seoboy.shared.robots import RobotsFile
from seoboy.shared.urls import InvalidUrl, normalize_url, origin_of, resolve_url
from seoboy.shared.util import excel_safe, normalize_whitespace


class LocalSeoError(RuntimeError):
    """A local SEO configuration or request cannot be evaluated."""


@dataclass(frozen=True)
class Location:
    label: str
    url: str
    name: str
    street: str = ""
    profiles: tuple[str, ...] = ()
    postal_code: str = ""
    city: str = ""
    region: str = ""
    country: str = ""
    phone: str = ""


@dataclass
class ProfileResult:
    url: str
    status: int | None = None
    title: str | None = None
    name_match: bool = False
    city_match: bool = False
    phone_match: bool = False
    error: str | None = None


@dataclass
class LocalRanking:
    query: str
    location: str
    position: float | None
    url: str = ""
    source: str = ""
    date: str = ""


@dataclass
class LocalResult:
    location: Location
    status: int | None = None
    indexable: bool = False
    title: str | None = None
    meta_description: str | None = None
    h1: str | None = None
    word_count: int = 0
    schema_types: tuple[str, ...] = ()
    matches: dict[str, bool] | None = None
    missing: tuple[str, ...] = ()
    mismatches: tuple[str, ...] = ()
    profiles: tuple[ProfileResult, ...] = ()
    error: str | None = None


def load_locations(path: Path | str) -> list[Location]:
    target = Path(path)
    try:
        payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    except OSError as error:
        raise LocalSeoError(f"Standortdatei nicht lesbar: {error}") from error
    except yaml.YAMLError as error:
        raise LocalSeoError(f"Standortdatei ist kein gültiges YAML: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("locations"), list):
        raise LocalSeoError("Standortdatei benötigt eine Liste 'locations'.")
    locations: list[Location] = []
    for index, item in enumerate(payload["locations"], start=1):
        if not isinstance(item, dict):
            raise LocalSeoError(f"Standort {index} muss ein Objekt sein.")
        label = str(item.get("label") or "").strip()
        url = str(item.get("url") or "").strip()
        name = str(item.get("name") or "").strip()
        if not label or not url or not name:
            raise LocalSeoError(f"Standort {index} benötigt label, url und name.")
        raw_profiles = item.get("profiles") or []
        if isinstance(raw_profiles, str):
            raw_profiles = [raw_profiles]
        if not isinstance(raw_profiles, list):
            raise LocalSeoError(f"Standort {index}: profiles muss eine Liste sein.")
        profiles = tuple(
            str(value).strip() for value in raw_profiles if str(value).strip()
        )
        locations.append(
            Location(
                label=label,
                url=url,
                name=name,
                profiles=profiles,
                street=str(item.get("street") or "").strip(),
                postal_code=str(item.get("postal_code") or "").strip(),
                city=str(item.get("city") or "").strip(),
                region=str(item.get("region") or "").strip(),
                country=str(item.get("country") or "").strip(),
                phone=str(item.get("phone") or "").strip(),
            )
        )
    if not locations:
        raise LocalSeoError("Standortdatei enthält keine Standorte.")
    return locations


def _schema_nodes(blocks: Iterable[str]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            type_value = value.get("@type")
            types = [type_value] if isinstance(type_value, str) else type_value if isinstance(type_value, list) else []
            if any(str(item).casefold() in {"localbusiness", "organization", "professionalservice"} for item in types):
                nodes.append(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for block in blocks:
        try:
            visit(json.loads(block))
        except (TypeError, ValueError):
            continue
    return nodes


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return _text(value.get("name") or value.get("value") or "")
    return normalize_whitespace(str(value)) if value is not None else ""


def _phone(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def _expected(location: Location) -> dict[str, str]:
    return {
        "name": location.name,
        "street": location.street,
        "postal_code": location.postal_code,
        "city": location.city,
        "region": location.region,
        "country": location.country,
        "phone": location.phone,
    }


def _actual(nodes: list[dict[str, Any]]) -> dict[str, str]:
    node: dict[str, Any] = {}
    for candidate in nodes:
        if isinstance(candidate.get("address"), dict) or candidate.get("telephone"):
            node = candidate
            break
    if not node and nodes:
        node = nodes[0]
    address = node.get("address") if isinstance(node.get("address"), dict) else {}
    return {
        "name": _text(node.get("name")),
        "street": _text(address.get("streetAddress")),
        "postal_code": _text(address.get("postalCode")),
        "city": _text(address.get("addressLocality")),
        "region": _text(address.get("addressRegion")),
        "country": _text(address.get("addressCountry")),
        "phone": _text(node.get("telephone")),
    }


def _normalise(field: str, value: str) -> str:
    if field == "phone":
        return _phone(value)
    return normalize_whitespace(value).casefold()


def _plain_text(html: str) -> str:
    without_scripts = re.sub(
        r"<(script|style)[^>]*>.*?</(script|style)>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return normalize_whitespace(re.sub(r"<[^>]+>", " ", without_scripts))


def _audit_profile(client: HttpClient, location: Location, profile_url: str) -> ProfileResult:
    try:
        normalized = normalize_url(profile_url)
    except InvalidUrl as error:
        return ProfileResult(url=profile_url, error=str(error))
    robots = RobotsFile.parse("")
    robots_result = client.fetch(origin_of(normalized.url) + "/robots.txt")
    if robots_result.status_code and 200 <= robots_result.status_code < 300:
        robots = RobotsFile.parse(decode_body(robots_result))
    if not robots.is_allowed(
        normalized.path + (f"?{normalized.query}" if normalized.query else ""), SEOBOY
    ):
        return ProfileResult(url=profile_url, error="robots_disallowed")
    result = client.fetch(normalized.url)
    for _ in range(3):
        if result.status_code not in {301, 302, 303, 307, 308} or not result.redirect_location:
            break
        target = resolve_url(result.url, result.redirect_location)
        if target is None:
            break
        result = client.fetch(target)
    if result.error_code is not None or result.status_code is None:
        return ProfileResult(
            url=profile_url, error=result.error_code or "fetch_failed"
        )
    if not result.is_html:
        return ProfileResult(
            url=profile_url, status=result.status_code, error="not_html"
        )
    body = decode_body(result)
    page = extract_page(body, result.url, result.header_items)
    text = _plain_text(body).casefold()
    phone = _phone(location.phone)
    return ProfileResult(
        url=profile_url,
        status=result.status_code,
        title=page.title,
        name_match=bool(location.name and location.name.casefold() in text),
        city_match=bool(location.city and location.city.casefold() in text),
        phone_match=bool(phone and phone in _phone(text)),
    )


def _audit_profiles(client: HttpClient, location: Location) -> tuple[ProfileResult, ...]:
    return tuple(_audit_profile(client, location, value) for value in location.profiles)


def load_local_rankings(path: Path | str) -> list[LocalRanking]:
    target = Path(path)
    try:
        stream = target.open(encoding="utf-8-sig", newline="")
    except OSError as error:
        raise LocalSeoError(f"Local-Result-Datei nicht lesbar: {error}") from error
    with stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise LocalSeoError("Local-Result-Datei enthält keinen Header.")
        required = {"query", "location", "position"}
        if not required.issubset({name.strip() for name in reader.fieldnames}):
            raise LocalSeoError(
                "Local-Result-Datei benötigt query, location und position."
            )
        rows: list[LocalRanking] = []
        for index, row in enumerate(reader, start=2):
            query = (row.get("query") or "").strip()
            label = (row.get("location") or "").strip()
            raw_position = (row.get("position") or "").strip()
            if not query or not label or not raw_position:
                raise LocalSeoError(f"Local-Result-Zeile {index} ist unvollständig.")
            try:
                position = float(raw_position.replace(",", "."))
            except ValueError as error:
                raise LocalSeoError(
                    f"Local-Result-Zeile {index}: Position ist keine Zahl."
                ) from error
            rows.append(
                LocalRanking(
                    query=query,
                    location=label,
                    position=position,
                    url=(row.get("url") or "").strip(),
                    source=(row.get("source") or "").strip(),
                    date=(row.get("date") or "").strip(),
                )
            )
    return rows


def audit_location(client: HttpClient, location: Location, robots: RobotsFile | None = None) -> LocalResult:
    try:
        normalized = normalize_url(location.url)
    except InvalidUrl as error:
        return LocalResult(location=location, error=str(error))
    profiles = _audit_profiles(client, location)
    origin = origin_of(normalized.url)
    if robots is None:
        robots = RobotsFile.parse("")
    if not robots.is_allowed(normalized.path + (f"?{normalized.query}" if normalized.query else ""), SEOBOY):
        return LocalResult(
            location=location, profiles=profiles, error="robots_disallowed"
        )
    result = client.fetch(normalized.url)
    for _ in range(3):
        if result.status_code not in {301, 302, 303, 307, 308} or not result.redirect_location:
            break
        target = resolve_url(result.url, result.redirect_location)
        if target is None:
            break
        result = client.fetch(target)
    if result.error_code is not None or result.status_code is None:
        return LocalResult(
            location=location,
            profiles=profiles,
            error=result.error_code or "fetch_failed",
        )
    if not result.is_html:
        return LocalResult(
            location=location,
            profiles=profiles,
            status=result.status_code,
            error="not_html",
        )
    page: ExtractedPage = extract_page(decode_body(result), result.url, result.header_items)
    nodes = _schema_nodes(page.jsonld)
    expected = _expected(location)
    actual = _actual(nodes)
    matches: dict[str, bool] = {}
    missing: list[str] = []
    mismatches: list[str] = []
    for field, expected_value in expected.items():
        if not expected_value:
            continue
        actual_value = actual.get(field, "")
        if not actual_value:
            missing.append(field)
            matches[field] = False
        elif _normalise(field, actual_value) != _normalise(field, expected_value):
            mismatches.append(field)
            matches[field] = False
        else:
            matches[field] = True
    return LocalResult(
        location=location,
        status=result.status_code,
        indexable=not page.robots.noindex,
        title=page.title,
        meta_description=page.meta_description,
        h1=page.h1,
        word_count=page.word_count,
        schema_types=page.schema_types,
        matches=matches,
        missing=tuple(missing),
        mismatches=tuple(mismatches),
        profiles=profiles,
    )


def audit_locations(
    locations: list[Location],
    *,
    timeout: float = 15.0,
    interval_seconds: float = 0.5,
) -> list[LocalResult]:
    client = HttpClient(timeout=timeout)
    robots_by_origin: dict[str, RobotsFile] = {}
    results: list[LocalResult] = []
    for index, location in enumerate(locations):
        try:
            origin = origin_of(normalize_url(location.url).url)
        except InvalidUrl:
            results.append(LocalResult(location=location, error="invalid_url"))
            continue
        if origin not in robots_by_origin:
            robots_result = client.fetch(origin + "/robots.txt")
            robots_by_origin[origin] = (
                RobotsFile.parse(decode_body(robots_result))
                if robots_result.status_code and 200 <= robots_result.status_code < 300
                else RobotsFile.parse("")
            )
        if index:
            time.sleep(interval_seconds)
        results.append(audit_location(client, location, robots_by_origin[origin]))
    return results


def _write_csv(path: Path, rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(
            [
                "label",
                "url",
                "status",
                "indexable",
                "title",
                "h1",
                "word_count",
                "schema_types",
                "nap_matches",
                "nap_missing",
                "nap_mismatches",
                "error",
            ]
        )
        for row in rows:
            writer.writerow([excel_safe(value) for value in row])


def write_local_report(
    results: list[LocalResult],
    out: Path,
    rankings: list[LocalRanking] | None = None,
) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "raw_data"
    raw.mkdir(parents=True, exist_ok=True)
    _write_csv(
        raw / "local_locations.csv",
        [
            [
                item.location.label,
                item.location.url,
                item.status if item.status is not None else "",
                "1" if item.indexable else "0",
                item.title or "",
                item.h1 or "",
                item.word_count,
                "|".join(item.schema_types),
                "|".join(f"{key}={'ok' if value else 'nein'}" for key, value in (item.matches or {}).items()),
                "|".join(item.missing),
                "|".join(item.mismatches),
                item.error or "",
            ]
            for item in results
        ],
    )
    lines = [
        "# SeoBoy – Local-SEO-Prüfung",
        "",
        f"**Erzeugt:** {datetime.now().astimezone():%Y-%m-%d %H:%M %Z}",
        f"**Standorte:** {len(results)}",
        "",
        "| Standort | URL | HTTP | Indexierbar | H1 | Schema | NAP fehlt | NAP abweichend |",
        "| --- | --- | ---: | :---: | --- | --- | --- | --- |",
    ]
    for item in results:
        lines.append(
            "| "
            + " | ".join(
                [
                    item.location.label,
                    item.location.url,
                    str(item.status if item.status is not None else "–"),
                    "ja" if item.indexable else "nein",
                    item.h1 or "–",
                    ", ".join(item.schema_types) or "–",
                    ", ".join(item.missing) or "–",
                    ", ".join(item.mismatches) or "–",
                ]
            )
            + " |"
        )
    profile_rows = [
        (item.location.label, profile)
        for item in results
        for profile in item.profiles
    ]
    if profile_rows:
        _write_csv(
            raw / "local_profiles.csv",
            [
                [
                    label,
                    profile.url,
                    profile.status if profile.status is not None else "",
                    "1" if profile.name_match else "0",
                    "1" if profile.city_match else "0",
                    "1" if profile.phone_match else "0",
                    profile.title or "",
                    profile.error or "",
                ]
                for label, profile in profile_rows
            ],
        )
        lines.extend(
            [
                "## Externe Profile",
                "",
                "| Standort | Profil | HTTP | Name | Ort | Telefon | Titel | Fehler |",
                "| --- | --- | ---: | :---: | :---: | :---: | --- | --- |",
            ]
        )
        for label, profile in profile_rows:
            lines.append(
                "| "
                + " | ".join(
                    [
                        label,
                        profile.url,
                        str(profile.status if profile.status is not None else "–"),
                        "ja" if profile.name_match else "nein",
                        "ja" if profile.city_match else "nein",
                        "ja" if profile.phone_match else "nein",
                        profile.title or "–",
                        profile.error or "–",
                    ]
                )
                + " |"
            )
        lines.extend(
            [
                "",
                "Die Profilprüfung ist ein Textabgleich auf Name, Ort und Telefon. "
                "Sie ersetzt keine offizielle Google-Business- oder Verzeichnis-API.",
                "",
            ]
        )
    if rankings:
        _write_csv(
            raw / "local_rankings.csv",
            [
                [
                    row.query,
                    row.location,
                    row.position if row.position is not None else "",
                    row.url,
                    row.source,
                    row.date,
                ]
                for row in rankings
            ],
        )
        lines.extend(
            [
                "## Lokale Suchergebnisse",
                "",
                "| Suchanfrage | Standort | Position | URL | Quelle | Datum |",
                "| --- | --- | ---: | --- | --- | --- |",
            ]
        )
        for row in rankings:
            lines.append(
                f"| {row.query} | {row.location} | "
                f"{row.position if row.position is not None else '–'} | "
                f"{row.url or '–'} | {row.source or '–'} | {row.date or '–'} |"
            )
        lines.extend(
            [
                "",
                "Die lokalen Ergebnisse stammen aus einer beigestellten Messdatei. "
                "SeoBoy fragt keine Suchmaschine und kein Unternehmensprofil live ab.",
                "",
            ]
        )
    lines.extend(
        [
            "",
            "## NAP-Abgleich",
            "",
            "Verglichen werden Name, Straße, PLZ, Ort, Region, Land und Telefon aus "
            "LocalBusiness-/Organization-JSON-LD mit der Standortkonfiguration. "
            "Fehlende Felder sind keine automatische Aussage über falsche externe Profile.",
            "",
            "- [Rohdaten](raw_data/local_locations.csv)",
            *(
                ["- [Profile](raw_data/local_profiles.csv)"]
                if profile_rows
                else []
            ),
            *(
                ["- [Lokale Ergebnisse](raw_data/local_rankings.csv)"]
                if rankings
                else []
            ),
            "",
        ]
    )
    (out / "00_LOCAL_SEO.md").write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n"
    )
    return out
