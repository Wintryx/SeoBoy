"""PageSpeed Insights/Lighthouse and CrUX performance checks."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
import urllib.request

from seoboy.shared.util import excel_safe

PAGE_SPEED_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
CRUX_URL = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"
METRICS = {
    "first-contentful-paint": "FCP",
    "largest-contentful-paint": "LCP",
    "total-blocking-time": "TBT",
    "cumulative-layout-shift": "CLS",
    "speed-index": "Speed Index",
    "interactive": "TTI",
}


class PerformanceError(RuntimeError):
    """A performance API request failed or is not configured."""


@dataclass(frozen=True)
class LighthouseResult:
    url: str
    strategy: str
    score: float | None
    metrics: dict[str, float | None]
    fetched_at: str | None


@dataclass(frozen=True)
class CruxResult:
    url: str
    form_factor: str
    metrics: dict[str, float | None]
    collection_start: str | None
    collection_end: str | None


def _request_json(
    url: str,
    *,
    data: bytes | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(20_000_000).decode("utf-8", errors="replace")
    except HTTPError as error:
        detail = error.read(4000).decode("utf-8", errors="replace")
        raise PerformanceError(
            f"Performance-API HTTP {error.code}: {detail or error.reason}"
        ) from error
    except URLError as error:
        raise PerformanceError(f"Performance-API nicht erreichbar: {error.reason}") from error
    except OSError as error:
        raise PerformanceError(f"Performance-API-Verbindung fehlgeschlagen: {error}") from error
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise PerformanceError("Performance-API lieferte kein gültiges JSON.") from error
    if not isinstance(payload, dict):
        raise PerformanceError("Performance-API lieferte ein unerwartetes Format.")
    return payload


def fetch_lighthouse(
    url: str, *, api_key: str, strategy: str = "mobile", timeout: int = 60
) -> LighthouseResult:
    if not api_key:
        raise PerformanceError("Für PageSpeed Insights wird ein API-Key benötigt.")
    if strategy not in {"mobile", "desktop"}:
        raise PerformanceError("Strategie muss mobile oder desktop sein.")
    query = urlencode(
        {
            "url": url,
            "key": api_key,
            "strategy": strategy,
            "category": "performance",
        }
    )
    payload = _request_json(f"{PAGE_SPEED_URL}?{query}", timeout=timeout)
    lighthouse = payload.get("lighthouseResult") or {}
    if not isinstance(lighthouse, dict):
        raise PerformanceError("PageSpeed-Antwort enthält kein lighthouseResult.")
    categories = lighthouse.get("categories") or {}
    performance = categories.get("performance") if isinstance(categories, dict) else {}
    score_value = performance.get("score") if isinstance(performance, dict) else None
    score = round(float(score_value) * 100, 1) if isinstance(score_value, (int, float)) else None
    audits = lighthouse.get("audits") or {}
    metrics: dict[str, float | None] = {}
    for key, label in METRICS.items():
        audit = audits.get(key) if isinstance(audits, dict) else None
        value = audit.get("numericValue") if isinstance(audit, dict) else None
        metrics[label] = round(float(value), 3) if isinstance(value, (int, float)) else None
    return LighthouseResult(
        url=str(lighthouse.get("finalUrl") or url),
        strategy=strategy,
        score=score,
        metrics=metrics,
        fetched_at=str(lighthouse.get("fetchTime") or "") or None,
    )


def fetch_crux(
    url: str, *, api_key: str, form_factor: str = "PHONE", timeout: int = 60
) -> CruxResult:
    if not api_key:
        raise PerformanceError("Für CrUX wird ein API-Key benötigt.")
    parts = urlsplit(url)
    body: dict[str, Any] = {"url": url} if parts.path not in {"", "/"} else {"origin": f"{parts.scheme}://{parts.netloc}"}
    if form_factor:
        body["formFactor"] = form_factor
    payload = _request_json(
        f"{CRUX_URL}?{urlencode({'key': api_key})}",
        data=json.dumps(body).encode("utf-8"),
        timeout=timeout,
    )
    record = payload.get("record") or {}
    metrics_raw = record.get("metrics") if isinstance(record, dict) else {}
    metrics: dict[str, float | None] = {}
    if isinstance(metrics_raw, dict):
        for key, value in metrics_raw.items():
            percentile = value.get("percentiles", {}).get("p75") if isinstance(value, dict) else None
            metrics[key] = round(float(percentile), 3) if isinstance(percentile, (int, float)) else None
    collection = record.get("collectionPeriod") or {} if isinstance(record, dict) else {}
    return CruxResult(
        url=url,
        form_factor=form_factor,
        metrics=metrics,
        collection_start=str(collection.get("firstDate") or "") or None,
        collection_end=str(collection.get("lastDate") or "") or None,
    )


def _write_csv(path: Path, header: list[str], rows: Iterable[Iterable[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow([excel_safe(value) for value in row])


def run_performance(
    url: str,
    *,
    api_key: str,
    out: Path,
    strategy: str = "mobile",
    form_factor: str = "PHONE",
    lighthouse_enabled: bool = True,
    crux_enabled: bool = True,
) -> Path:
    if not lighthouse_enabled and not crux_enabled:
        raise PerformanceError("Mindestens eine Performance-Quelle muss aktiv sein.")
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "raw_data"
    raw.mkdir(parents=True, exist_ok=True)
    lighthouse = fetch_lighthouse(url, api_key=api_key, strategy=strategy) if lighthouse_enabled else None
    crux = fetch_crux(url, api_key=api_key, form_factor=form_factor) if crux_enabled else None
    lines = [
        "# SeoBoy – Performance",
        "",
        f"**URL:** {url}",
        f"**Erzeugt:** {datetime.now().astimezone():%Y-%m-%d %H:%M %Z}",
        "",
        "## Lighthouse / PageSpeed Insights",
        "",
    ]
    if lighthouse is None:
        lines.append("Nicht abgefragt.")
    else:
        lines.extend(
            [
                f"**Performance-Score:** {lighthouse.score if lighthouse.score is not None else '–'}",
                "",
                "| Metrik | Wert |",
                "| --- | ---: |",
            ]
        )
        for label, value in lighthouse.metrics.items():
            lines.append(f"| {label} | {value if value is not None else '–'} |")
    lines.extend(["", "## CrUX-Felddaten", ""])
    if crux is None:
        lines.append("Nicht abgefragt.")
    else:
        lines.extend(
            [
                f"**Formfaktor:** {crux.form_factor}",
                f"**Zeitraum:** {crux.collection_start or '–'} bis {crux.collection_end or '–'}",
                "",
                "| Metrik | p75 |",
                "| --- | ---: |",
            ]
        )
        for label, value in crux.metrics.items():
            lines.append(f"| {label} | {value if value is not None else '–'} |")
    lines.extend(
        [
            "",
            "## Grenzen",
            "",
            "- PageSpeed/Lighthouse ist eine Labor-Momentaufnahme, CrUX ein Felddaten-Aggregat.",
            "- Fehlende CrUX-Daten bedeuten nicht automatisch schlechte Performance.",
            "- Es werden keine Seiten verändert.",
            "",
            "## Rohdaten",
            "",
            "- [Performance-Zeilen](raw_data/performance.csv)",
            "",
        ]
    )
    (out / "00_PERFORMANCE.md").write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n"
    )
    rows: list[list[Any]] = []
    for label, value in (lighthouse.metrics.items() if lighthouse else []):
        rows.append(["lighthouse", label, value if value is not None else "", ""])
    if lighthouse and lighthouse.score is not None:
        rows.append(["lighthouse", "performance_score", lighthouse.score, ""])
    for label, value in (crux.metrics.items() if crux else []):
        rows.append(["crux", label, value if value is not None else "", "p75"])
    _write_csv(raw / "performance.csv", ["source", "metric", "value", "statistic"], rows)
    return out
