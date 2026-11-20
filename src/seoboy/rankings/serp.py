"""Minimal Serper.dev adapter that writes the CSV format of the ranking importer."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from seoboy.rankings.config import KeywordProfile


class SerperError(ValueError):
    """Serper is unavailable or returned an invalid response."""


@dataclass(frozen=True)
class SerperResult:
    position: int
    title: str
    url: str
    domain: str


def _location(profile: KeywordProfile) -> str | None:
    mapping = {
        "koeln": "Köln, Nordrhein-Westfalen, Deutschland",
        "nrw": "Nordrhein-Westfalen, Deutschland",
        "gummersbach": "Gummersbach, Nordrhein-Westfalen, Deutschland",
        "olpe": "Olpe, Nordrhein-Westfalen, Deutschland",
        "attendorn": "Attendorn, Nordrhein-Westfalen, Deutschland",
        "bergisch-gladbach": "Bergisch Gladbach, Nordrhein-Westfalen, Deutschland",
    }
    return mapping.get(profile.location_key)


def serper_search(
    api_key: str,
    query: str,
    *,
    market: str = "DE",
    language: str = "de",
    location: str | None = None,
    num: int = 10,
    timeout: float = 30.0,
) -> list[SerperResult]:
    if not api_key:
        raise SerperError("Serper-API-Key fehlt.")
    payload: dict[str, Any] = {
        "q": query,
        "gl": market.casefold(),
        "hl": language.casefold(),
        "num": max(1, min(int(num), 100)),
    }
    if location:
        payload["location"] = location
    request = Request(
        "https://google.serper.dev/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "SeoBoy/0.25 (+local audit)",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise SerperError(f"Serper HTTP {response.status}.")
            raw = response.read(2_000_000)
    except HTTPError as error:
        raise SerperError(f"Serper HTTP {error.code}.") from None
    except (URLError, TimeoutError, OSError) as error:
        raise SerperError(f"Serper nicht erreichbar: {error}") from None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise SerperError("Serper lieferte kein gültiges JSON.") from None
    organic = payload.get("organic") if isinstance(payload, dict) else None
    if not isinstance(organic, list):
        raise SerperError("Serper-Antwort enthält keine organic-Treffer.")
    results: list[SerperResult] = []
    for index, item in enumerate(organic, start=1):
        if not isinstance(item, dict):
            continue
        url = item.get("link") or item.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        try:
            position = int(item.get("position") or index)
        except (TypeError, ValueError):
            position = index
        domain = (urlsplit(url).hostname or "").casefold()
        results.append(
            SerperResult(
                position=position,
                title=str(item.get("title") or ""),
                url=url,
                domain=domain,
            )
        )
    results.sort(key=lambda item: item.position)
    return results[:num]


def fetch_serper_csv(
    profiles: Iterable[KeywordProfile],
    api_key: str,
    out: Path,
    *,
    max_calls: int = 5,
    interval_seconds: float = 1.0,
    timeout: float = 30.0,
) -> tuple[Path, Path, dict[str, Any]]:
    """Fetch a small Serper snapshot and write importer-compatible CSVs."""
    if max_calls < 1:
        raise SerperError("max_calls muss mindestens 1 sein.")
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    snapshots_path = folder / "snapshots.csv"
    results_path = folder / "results.csv"
    snapshot_fields = [
        "snapshot_id",
        "keyword_id",
        "observed_at",
        "source",
        "engine",
        "market",
        "language",
        "location_key",
        "device",
        "result_type",
        "depth",
        "status",
    ]
    result_fields = ["snapshot_id", "position", "url", "profile_id", "domain", "title"]
    selected = [profile for profile in profiles if profile.result_type == "organic"]
    skipped_mobile = 0
    calls = 0
    errors: list[str] = []
    observations: list[dict[str, str]] = []
    result_rows: list[dict[str, Any]] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with snapshots_path.open("w", encoding="utf-8-sig", newline="") as snapshot_stream, results_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as result_stream:
        snapshot_writer = csv.DictWriter(snapshot_stream, fieldnames=snapshot_fields)
        result_writer = csv.DictWriter(result_stream, fieldnames=result_fields)
        snapshot_writer.writeheader()
        result_writer.writeheader()
        for profile in selected:
            if calls >= max_calls:
                break
            if profile.device != "desktop":
                skipped_mobile += 1
                continue
            # Serper does not expose a documented device switch; do not claim mobile.
            snapshot_id = f"{stamp}-{profile.id}"
            observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            )
            try:
                results = serper_search(
                    api_key,
                    profile.query,
                    market=profile.market,
                    language=profile.language,
                    location=_location(profile),
                    num=10,
                    timeout=timeout,
                )
                status = "ok"
                for item in results:
                    result_rows.append(
                        {
                            "snapshot_id": snapshot_id,
                            "position": item.position,
                            "url": item.url,
                            "profile_id": "",
                            "domain": item.domain,
                            "title": item.title,
                        }
                    )
            except SerperError as error:
                status = "failed"
                errors.append(f"{profile.id}: {error}")
            calls += 1
            observations.append(
                {
                    "snapshot_id": snapshot_id,
                    "keyword_id": profile.id,
                    "observed_at": observed_at,
                    "source": "serper",
                    "engine": profile.engine,
                    "market": profile.market,
                    "language": profile.language,
                    "location_key": profile.location_key,
                    "device": profile.device,
                    "result_type": profile.result_type,
                    "depth": "10",
                    "status": status,
                }
            )
            if interval_seconds > 0 and calls < max_calls:
                time.sleep(interval_seconds)
        snapshot_writer.writerows(observations)
        result_writer.writerows(result_rows)
    return snapshots_path, results_path, {
        "profiles": len(observations),
        "calls": calls,
        "skipped_mobile": skipped_mobile,
        "errors": errors,
    }
