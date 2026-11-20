"""Google Search Console API client built on the standard library."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
import urllib.request

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://searchconsole.googleapis.com/webmasters/v3"
INSPECTION_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
MAX_ROWS = 100_000


class GscApiError(RuntimeError):
    """A Search Console API request failed or is not configured."""


@dataclass(frozen=True)
class GscCredentials:
    client_id: str
    client_secret: str
    refresh_token: str
    access_token: str | None = None


@dataclass(frozen=True)
class GscFetchSummary:
    folder: Path
    period_start: str
    period_end: str
    pages: int
    queries: int


def load_credentials(path: Path | str | None = None) -> GscCredentials:
    raw_path = path or os.environ.get("SEOBOY_GSC_CREDENTIALS")
    if not raw_path:
        raise GscApiError(
            "Keine GSC-Zugangsdatei angegeben. Nutze --credentials oder "
            "SEOBOY_GSC_CREDENTIALS."
        )
    target = Path(raw_path).expanduser()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as error:
        raise GscApiError(f"GSC-Zugangsdatei nicht lesbar: {error}") from error
    except ValueError as error:
        raise GscApiError(f"GSC-Zugangsdatei ist kein gültiges JSON: {error}") from error
    if not isinstance(payload, dict):
        raise GscApiError("GSC-Zugangsdatei muss ein JSON-Objekt enthalten.")
    client_id = str(payload.get("client_id") or "").strip()
    client_secret = str(payload.get("client_secret") or "").strip()
    refresh_token = str(payload.get("refresh_token") or "").strip()
    if not client_id or not client_secret or not refresh_token:
        raise GscApiError(
            "GSC-Zugangsdatei benötigt client_id, client_secret und refresh_token."
        )
    access_token = str(payload.get("access_token") or "").strip() or None
    return GscCredentials(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        access_token=access_token,
    )


def _http_json(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> dict:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(20_000_000).decode("utf-8", errors="replace")
    except HTTPError as error:
        detail = error.read(4000).decode("utf-8", errors="replace")
        raise GscApiError(
            f"GSC-API HTTP {error.code}: {detail or error.reason}"
        ) from error
    except URLError as error:
        raise GscApiError(f"GSC-API nicht erreichbar: {error.reason}") from error
    except OSError as error:
        raise GscApiError(f"GSC-API-Verbindung fehlgeschlagen: {error}") from error
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise GscApiError("GSC-API lieferte keine gültige JSON-Antwort.") from error
    if not isinstance(payload, dict):
        raise GscApiError("GSC-API lieferte ein unerwartetes JSON-Format.")
    return payload


def access_token(credentials: GscCredentials) -> str:
    if credentials.access_token:
        return credentials.access_token
    env_token = os.environ.get("SEOBOY_GSC_ACCESS_TOKEN")
    if env_token:
        return env_token
    body = urlencode(
        {
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "refresh_token": credentials.refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    payload = _http_json(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = str(payload.get("access_token") or "")
    if not token:
        raise GscApiError("OAuth-Antwort enthielt kein access_token.")
    return token


def _filters(
    country: str | None, device: str | None
) -> list[dict[str, object]]:
    filters: list[dict[str, object]] = []
    if country:
        filters.append(
            {"dimension": "country", "operator": "equals", "expression": country}
        )
    if device:
        filters.append(
            {"dimension": "device", "operator": "equals", "expression": device.upper()}
        )
    return [{"filters": filters}] if filters else []


def search_analytics(
    token: str,
    property_name: str,
    start: date,
    end: date,
    dimensions: list[str],
    *,
    search_type: str = "web",
    country: str | None = None,
    device: str | None = None,
    row_limit: int = 25_000,
    max_rows: int = MAX_ROWS,
) -> list[dict[str, object]]:
    if start > end:
        raise GscApiError("Der GSC-Zeitraum beginnt nach seinem Enddatum.")
    if not 1 <= row_limit <= 25_000:
        raise GscApiError("--row-limit muss zwischen 1 und 25000 liegen.")
    if max_rows < 1:
        raise GscApiError("--max-rows muss mindestens 1 sein.")
    url = (
        f"{API_BASE}/sites/{quote(property_name, safe='')}/searchAnalytics/query"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    rows: list[dict[str, object]] = []
    start_row = 0
    while start_row < max_rows:
        request_body: dict[str, object] = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": dimensions,
            "type": search_type,
            "rowLimit": min(row_limit, max_rows - start_row),
            "startRow": start_row,
        }
        groups = _filters(country, device)
        if groups:
            request_body["dimensionFilterGroups"] = groups
        payload = _http_json(
            url,
            data=json.dumps(request_body).encode("utf-8"),
            headers=headers,
        )
        page_rows = payload.get("rows") or []
        if not isinstance(page_rows, list):
            raise GscApiError("GSC-API lieferte keine gültige rows-Liste.")
        rows.extend(page_rows)
        if len(page_rows) < request_body["rowLimit"]:
            break
        start_row += len(page_rows)
    if len(rows) > max_rows:
        rows = rows[:max_rows]
    return rows


def _number(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _position(value: object) -> str:
    if value is None:
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    if numeric <= 0:
        return ""
    return f"{numeric:.6f}".rstrip("0").rstrip(".")


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def fetch_to_directory(
    credentials: GscCredentials,
    property_name: str,
    start: date,
    end: date,
    out: Path | str,
    *,
    search_type: str = "web",
    country: str | None = None,
    device: str | None = None,
    row_limit: int = 25_000,
    max_rows: int = MAX_ROWS,
) -> GscFetchSummary:
    token = access_token(credentials)
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    period = f"{start.isoformat()}_{end.isoformat()}"
    pages_name = f"{period}_pages.csv"
    queries_name = f"{period}_page_queries.csv"

    page_rows = search_analytics(
        token,
        property_name,
        start,
        end,
        ["page"],
        search_type=search_type,
        country=country,
        device=device,
        row_limit=row_limit,
        max_rows=max_rows,
    )
    query_rows = search_analytics(
        token,
        property_name,
        start,
        end,
        ["page", "query"],
        search_type=search_type,
        country=country,
        device=device,
        row_limit=row_limit,
        max_rows=max_rows,
    )

    page_output: list[list[str]] = []
    for row in page_rows:
        keys = row.get("keys") or []
        if not isinstance(keys, list) or not keys:
            continue
        page_output.append(
            [
                str(keys[0]),
                _number(row.get("clicks")),
                _number(row.get("impressions")),
                _position(row.get("position")),
            ]
        )
    query_output: list[list[str]] = []
    for row in query_rows:
        keys = row.get("keys") or []
        if not isinstance(keys, list) or len(keys) < 2:
            continue
        query_output.append(
            [
                str(keys[0]),
                str(keys[1]),
                _number(row.get("clicks")),
                _number(row.get("impressions")),
                _position(row.get("position")),
            ]
        )
    _write_csv(
        folder / pages_name,
        ["page", "clicks", "impressions", "position"],
        page_output,
    )
    _write_csv(
        folder / queries_name,
        ["page", "query", "clicks", "impressions", "position"],
        query_output,
    )
    manifest = {
        "property": property_name,
        "search_type": search_type,
        "country": country,
        "device": device.upper() if device else None,
        "periods": [
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "source_format": "gsc_api",
                "pages": pages_name,
                "page_queries": queries_name,
            }
        ],
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return GscFetchSummary(
        folder=folder,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        pages=len(page_output),
        queries=len(query_output),
    )


def inspect_url(
    credentials: GscCredentials,
    property_name: str,
    inspection_url: str,
    *,
    language_code: str = "de-DE",
) -> dict:
    token = access_token(credentials)
    body = {
        "inspectionUrl": inspection_url,
        "siteUrl": property_name,
        "languageCode": language_code,
    }
    payload = _http_json(
        INSPECTION_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    result = payload.get("inspectionResult")
    if not isinstance(result, dict):
        raise GscApiError("URL-Inspection-Antwort enthält kein inspectionResult.")
    return result


def inspection_markdown(
    result: dict, *, property_name: str, inspection_url: str
) -> str:
    index = result.get("indexStatusResult") or {}
    if not isinstance(index, dict):
        index = {}
    lines = [
        "# GSC URL Inspection",
        "",
        f"**Property:** {property_name}",
        f"**URL:** {inspection_url}",
        "",
        "| Feld | Wert |",
        "| --- | --- |",
    ]
    fields = [
        ("Verdict", result.get("verdict")),
        ("Coverage State", index.get("coverageState")),
        ("Indexing State", index.get("indexingState")),
        ("Robots.txt State", index.get("robotsTxtState")),
        ("Page Fetch State", index.get("pageFetchState")),
        ("Google Canonical", index.get("googleCanonical")),
        ("User Canonical", index.get("userCanonical")),
        ("Last Crawl", index.get("lastCrawlTime")),
    ]
    for label, value in fields:
        lines.append(f"| {label} | {str(value) if value else '–'} |")
    lines.extend(
        [
            "",
            "Die Inspection ist eine Momentaufnahme von Googles gespeichertem Stand. "
            "Sie ersetzt keinen Live-Abruf der Seite.",
            "",
        ]
    )
    return "\n".join(lines)
