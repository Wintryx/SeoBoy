"""Lightweight URL monitor with confirmed events and local reports."""

from __future__ import annotations

from dataclasses import dataclass, replace
import csv
from datetime import datetime, timezone
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from seoboy.crawl.html_extract import extract_page
from seoboy.crawl.http_client import HttpClient, decode_body
from seoboy.infrastructure.config import ProjectConfig
from seoboy.infrastructure.database import transaction
from seoboy.shared.agents import SEOBOY
from seoboy.shared.robots import RobotsFile
from seoboy.shared.urls import normalize_url, resolve_url
from seoboy.shared.util import iso_utc


@dataclass(frozen=True)
class MonitorTarget:
    url: str
    page_type: str | None = None
    expected_indexable: bool = True


@dataclass(frozen=True)
class MonitorCheck:
    url: str
    state: str
    reason_code: str | None
    http_status: int | None
    final_url: str | None
    elapsed_ms: int
    canonical_url: str | None
    robots_directive: str | None
    observed_at: str


def _targets(
    connection: Any, config: ProjectConfig, explicit: Iterable[str]
) -> list[MonitorTarget]:
    values = [normalize_url(value).url for value in explicit if value.strip()]
    if values:
        return [MonitorTarget(url=value) for value in dict.fromkeys(values)]
    row = connection.execute(
        "SELECT run_id FROM runs WHERE project_id = ? AND mode = 'crawl' "
        "AND status = 'completed' ORDER BY ended_at DESC LIMIT 1",
        (config.project_id,),
    ).fetchone()
    if row is not None:
        rows = connection.execute(
            "SELECT u.normalized_url, r.page_type, r.expected_indexable "
            "FROM urls u JOIN run_urls r ON r.url_id = u.url_id AND r.run_id = ? "
            "WHERE r.business_value = 'high' AND r.page_type IS NOT NULL "
            "ORDER BY u.normalized_url LIMIT 40",
            (row["run_id"],),
        ).fetchall()
        if rows:
            return [
                MonitorTarget(
                    url=item["normalized_url"],
                    page_type=item["page_type"],
                    expected_indexable=(
                        True
                        if item["expected_indexable"] is None
                        else bool(item["expected_indexable"])
                    ),
                )
                for item in rows
            ]
    result = [MonitorTarget(config.start_url)]
    for profile in config.priority_pages:
        if "*" in profile.pattern:
            continue
        result.append(
            MonitorTarget(
                url=config.start_url.rstrip("/") + profile.pattern,
                page_type=profile.page_type,
                expected_indexable=profile.expected_indexable is not False,
            )
        )
    return list({item.url: item for item in result}.values())


def _robots(client: HttpClient, url: str) -> RobotsFile | None:
    origin = normalize_url(url).origin
    result = client.fetch(origin + "/robots.txt")
    if result.status_code != 200 or result.error_code is not None:
        return None
    try:
        return RobotsFile.parse(decode_body(result))
    except (ValueError, UnicodeError):
        return None


def _fetch_follow(client: HttpClient, url: str) -> tuple[Any, str]:
    current = normalize_url(url).url
    result = client.fetch(current)
    for _ in range(5):
        if result.status_code is None or not (300 <= result.status_code < 400):
            break
        location = result.redirect_location
        if not location:
            break
        target = resolve_url(current, location)
        if target is None:
            break
        current = normalize_url(target).url
        result = client.fetch(current)
    return result, current


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _check(client: HttpClient, target: MonitorTarget, robots: RobotsFile | None) -> MonitorCheck:
    observed_at = _now()
    normalized = normalize_url(target.url)
    if robots is not None and not robots.is_allowed(
        urlsplit(normalized.url).path or "/", SEOBOY
    ):
        return MonitorCheck(
            url=normalized.url,
            state="not_checked",
            reason_code="robots_disallowed",
            http_status=None,
            final_url=None,
            elapsed_ms=0,
            canonical_url=None,
            robots_directive=None,
            observed_at=observed_at,
        )
    result, final_url = _fetch_follow(client, normalized.url)
    if result.error_code is not None:
        reason = "rate_limited" if result.status_code == 429 else "fetch_error"
        return MonitorCheck(
            url=normalized.url,
            state="not_checked",
            reason_code=reason,
            http_status=result.status_code,
            final_url=final_url,
            elapsed_ms=result.elapsed_ms,
            canonical_url=None,
            robots_directive=None,
            observed_at=observed_at,
        )
    status = result.status_code
    if status != 200:
        return MonitorCheck(
            url=normalized.url,
            state="suspect",
            reason_code=f"http_{status}" if status is not None else "no_status",
            http_status=status,
            final_url=final_url,
            elapsed_ms=result.elapsed_ms,
            canonical_url=None,
            robots_directive=None,
            observed_at=observed_at,
        )
    content_type = result.content_type or ""
    if "html" not in content_type:
        return MonitorCheck(
            url=normalized.url,
            state="ok",
            reason_code="non_html",
            http_status=status,
            final_url=final_url,
            elapsed_ms=result.elapsed_ms,
            canonical_url=None,
            robots_directive=None,
            observed_at=observed_at,
        )
    page = extract_page(decode_body(result), final_url, result.header_items)
    canonical = page.canonical[0] if page.canonical else None
    robots_directive = page.robots.meta_raw or page.robots.header_raw
    if normalize_url(final_url).url != normalized.url:
        return MonitorCheck(
            url=normalized.url,
            state="suspect",
            reason_code="unexpected_redirect",
            http_status=status,
            final_url=final_url,
            elapsed_ms=result.elapsed_ms,
            canonical_url=canonical,
            robots_directive=robots_directive,
            observed_at=observed_at,
        )
    expected_noindex = not target.expected_indexable
    if page.robots.noindex != expected_noindex:
        reason = "noindex_unexpected" if page.robots.noindex else "noindex_missing"
        return MonitorCheck(
            url=normalized.url,
            state="suspect",
            reason_code=reason,
            http_status=status,
            final_url=final_url,
            elapsed_ms=result.elapsed_ms,
            canonical_url=canonical,
            robots_directive=robots_directive,
            observed_at=observed_at,
        )
    if canonical is not None and not expected_noindex:
        try:
            canonical_normalized = normalize_url(canonical).url
        except ValueError:
            canonical_normalized = canonical
        if canonical_normalized not in {normalized.url, normalize_url(final_url).url}:
            return MonitorCheck(
                url=normalized.url,
                state="suspect",
                reason_code="canonical_mismatch",
                http_status=status,
                final_url=final_url,
                elapsed_ms=result.elapsed_ms,
                canonical_url=canonical,
                robots_directive=robots_directive,
                observed_at=observed_at,
            )
    return MonitorCheck(
        url=normalized.url,
        state="ok",
        reason_code=None,
        http_status=status,
        final_url=final_url,
        elapsed_ms=result.elapsed_ms,
        canonical_url=canonical,
        robots_directive=robots_directive,
        observed_at=observed_at,
    )


def _record(connection: Any, config: ProjectConfig, check: MonitorCheck, observation_id: int) -> str:
    event = connection.execute(
        "SELECT * FROM monitor_events WHERE project_id = ? AND watch_key = ?",
        (config.project_id, check.url),
    ).fetchone()
    previous_state = str(event["state"]) if event is not None else None
    failures = int(event["failures"]) if event is not None else 0
    confirmed_at = event["confirmed_at"] if event is not None else None
    recovered_at = event["recovered_at"] if event is not None else None
    first_seen = event["first_seen"] if event is not None else check.observed_at
    if check.state == "ok":
        if previous_state in {"suspect", "confirmed"}:
            event_state = "recovered"
            recovered_at = check.observed_at
            failures = 0
        elif previous_state == "recovered":
            event_state = "recovered"
        else:
            event_state = "ok"
            failures = 0
        confirmed_at = None if event_state == "recovered" else confirmed_at
    elif check.state == "suspect":
        failures += 1
        if failures >= 2 or previous_state == "confirmed":
            event_state = "confirmed"
            confirmed_at = confirmed_at or check.observed_at
        else:
            event_state = "suspect"
    else:
        return previous_state if event is not None else "not_checked"
    connection.execute(
        "INSERT INTO monitor_events(project_id, watch_key, url, state, reason_code, "
        "first_seen, last_seen, confirmed_at, recovered_at, failures, last_observation_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(project_id, watch_key) DO UPDATE SET state = excluded.state, "
        "reason_code = excluded.reason_code, last_seen = excluded.last_seen, "
        "confirmed_at = excluded.confirmed_at, recovered_at = excluded.recovered_at, "
        "failures = excluded.failures, last_observation_id = excluded.last_observation_id",
        (
            config.project_id,
            check.url,
            check.url,
            event_state,
            check.reason_code,
            first_seen,
            check.observed_at,
            confirmed_at,
            recovered_at,
            failures,
            observation_id,
        ),
    )
    return event_state


def _csv(path: Path, rows: list[MonitorCheck]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(
            [
                "observed_at",
                "url",
                "state",
                "reason_code",
                "http_status",
                "final_url",
                "elapsed_ms",
                "robots_directive",
                "canonical_url",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.observed_at,
                    row.url,
                    row.state,
                    row.reason_code or "",
                    "" if row.http_status is None else row.http_status,
                    row.final_url or "",
                    row.elapsed_ms,
                    row.robots_directive or "",
                    row.canonical_url or "",
                ]
            )


def _markdown(path: Path, config: ProjectConfig, rows: list[MonitorCheck]) -> None:
    counts = {
        state: sum(1 for row in rows if row.state == state)
        for state in ("ok", "suspect", "not_checked")
    }
    lines = [
        "# SeoBoy – URL-Monitor",
        "",
        f"**Projekt:** {config.project_id}  ",
        f"**Messung:** {iso_utc()}  ",
        f"**Geprüft:** {len(rows)} URLs · ok {counts['ok']} · verdächtig {counts['suspect']} · nicht geprüft {counts['not_checked']}",
        "",
        "| URL | Zustand | Grund | HTTP | Laufzeit | Canonical |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.url} | {row.state} | {row.reason_code or '–'} | "
            f"{row.http_status or '–'} | {row.elapsed_ms} ms | {row.canonical_url or '–'} |"
        )
    lines.extend(
        [
            "",
            "Zwei vergleichbare verdächtige Messungen bestätigen ein Ereignis. "
            "Ein späterer erfolgreicher Check markiert es als recovered.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def run_monitor_check(
    connection: Any,
    config: ProjectConfig,
    *,
    urls: Iterable[str] = (),
    timeout: float = 15.0,
) -> tuple[Path, list[MonitorCheck]]:
    targets = _targets(connection, config, urls)
    client = HttpClient(timeout=timeout, max_bytes=2_000_000)
    checks: list[MonitorCheck] = []
    robots_by_origin: dict[str, RobotsFile | None] = {}
    interval = max(0.0, config.crawl.min_request_interval_ms / 1000.0)
    for index, target in enumerate(targets):
        if index:
            time.sleep(interval)
        origin = normalize_url(target.url).origin
        if origin not in robots_by_origin:
            robots_by_origin[origin] = _robots(client, target.url)
        robots = robots_by_origin[origin]
        check = _check(client, target, robots)
        checks.append(check)
        with transaction(connection):
            cursor = connection.execute(
                "INSERT INTO monitor_observations(project_id, watch_key, url, observed_at, "
                "http_status, final_url, elapsed_ms, robots_directive, canonical_url, state, reason_code) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    config.project_id,
                    check.url,
                    check.url,
                    check.observed_at,
                    check.http_status,
                    check.final_url,
                    check.elapsed_ms,
                    check.robots_directive,
                    check.canonical_url,
                    check.state,
                    check.reason_code,
                ),
            )
            event_state = _record(connection, config, check, int(cursor.lastrowid))
            connection.execute(
                "UPDATE monitor_observations SET state = ? WHERE observation_id = ?",
                (check.state if check.state == "not_checked" else event_state, cursor.lastrowid),
            )
            if check.state != "not_checked":
                checks[-1] = replace(check, state=event_state)
    folder = config.reports_dir / "monitor"
    _csv(folder / "raw_data" / "monitor_events.csv", checks)
    _markdown(folder / "MONITOR_STATUS.md", config, checks)
    return folder, checks
