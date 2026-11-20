"""HTTP-Crawl mit SQLite-Warteschlange, Limits und Wiederaufnahme."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
import gzip
import json
import secrets
import sqlite3
import threading
import time
from typing import Any, Literal
from xml.etree import ElementTree

from seoboy.infrastructure import database
from seoboy.infrastructure.config import ProjectConfig
from seoboy.infrastructure.database import transaction
from seoboy.crawl.html_extract import extract_page, link_header_canonicals
from seoboy.crawl.http_client import FetchResult, HttpClient, decode_body
from seoboy.crawl.registry import UrlRegistry, classify_url
from seoboy.shared.robots import RobotsFile
from seoboy.shared.agents import SEOBOY
from seoboy.shared.urls import (
    InvalidUrl,
    NormalizedUrl,
    is_internal,
    normalize_url,
    origin_of,
    resolve_url,
)
from seoboy.shared.util import iso_utc, parse_retry_after, utc_now
from seoboy.shared.version import CRAWLER_VERSION, NORMALIZATION_VERSION, RULESET_VERSION, TOOL_VERSION

PAGE = "page"
ROBOTS = "robots"
SITEMAP = "sitemap"

PRIORITY_ROBOTS = -1000
PRIORITY_SITEMAP = -500
PRIORITY_SEED = 0
PRIORITY_LINK_BASE = 100
PRIORITY_UNLINKED = 10_000

MAX_ATTEMPTS = 3

STOP_COMPLETE = "crawl_complete"
STOP_URL_LIMIT = "url_limit_reached"
STOP_REQUEST_LIMIT = "request_limit_reached"
STOP_RUNTIME_LIMIT = "runtime_limit_reached"
STOP_HOP_LIMIT = "redirect_hop_limit"


class ResumeError(RuntimeError):
    """Der gespeicherte Lauf lässt sich mit dieser Konfiguration nicht fortsetzen."""


class RequestLimitReached(RuntimeError):
    pass


class UrlLimitReached(RuntimeError):
    pass


@dataclass(frozen=True)
class Reservation:
    attempt_id: int
    attempt_no: int


@dataclass(frozen=True)
class CrawlOutcome:
    status: Literal["complete", "partial", "paused"]
    stop_reason: str | None


@dataclass(frozen=True)
class PageTask:
    job: sqlite3.Row
    reservation: Reservation
    url: str
    origin: str
    delay: float


class RequestPacer:
    """Startet Anfragen pro Origin im konfigurierten Mindestabstand."""

    def __init__(self, interval_seconds: float) -> None:
        self.interval = max(0.0, interval_seconds)
        self._lock = threading.Lock()
        self._next_start: dict[str, float] = {}

    def reserve(self, origin: str) -> float:
        now = time.monotonic()
        with self._lock:
            allowed = max(now, self._next_start.get(origin, now))
            self._next_start[origin] = allowed + self.interval
            delay = max(0.0, allowed - now)
        return delay


def _new_run_id() -> str:
    return f"{utc_now():%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


def _headers_payload(result: FetchResult) -> str:
    headers: dict[str, str] = {}
    skipped = {"set-cookie", "set-cookie2"}
    for name, value in result.header_items:
        key = name.casefold()
        if key in skipped:
            continue
        if key in headers:
            headers[key] = f"{headers[key]}, {value}"
        else:
            headers[key] = value
    payload = json.dumps(headers, ensure_ascii=False, sort_keys=True)
    return payload[:20_000]


def _origin_path(normalized: NormalizedUrl) -> str:
    return f"{normalized.path}?{normalized.query}" if normalized.query else normalized.path


def create_run(
    connection: sqlite3.Connection,
    config: ProjectConfig,
    *,
    mode: Literal["crawl", "inspect"],
    inputs: dict[str, Any],
    initial_urls: list[str],
) -> str:
    """Legt Lauf, initiale Warteschlange und Eingabe-Hashes in einer Transaktion an."""
    run_id = _new_run_id()
    started_at = iso_utc()
    max_urls = 1 if mode == "inspect" else config.crawl.max_urls
    max_requests = min(config.crawl.max_requests, 10) if mode == "inspect" else config.crawl.max_requests
    registry = UrlRegistry(connection, run_id, config.project_id, config)
    with transaction(connection):
        database.ensure_project(connection, config.project_id)
        database.ensure_site(connection, config.project_id, "own", config.start_url)
        connection.execute(
            "INSERT INTO runs(run_id, project_id, site_id, mode, status, started_at, "
            "config_json, config_hash, inputs_json, tool_version, crawler_version, "
            "ruleset_version, normalization_version, max_urls, max_requests) "
            "VALUES (?, ?, 'own', ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                config.project_id,
                mode,
                started_at,
                config.canonical_json(),
                config.config_hash(),
                json.dumps(inputs, ensure_ascii=False, sort_keys=True),
                TOOL_VERSION,
                CRAWLER_VERSION,
                RULESET_VERSION,
                NORMALIZATION_VERSION,
                max_urls,
                max_requests,
            ),
        )
        first_origin: str | None = None
        for raw_url in initial_urls:
            try:
                normalized = normalize_url(raw_url, config.crawl.remove_query_params)
            except InvalidUrl:
                continue
            url_id, _ = registry.ensure_url(normalized)
            registry.add_discovery(url_id, raw_url, "seed")
            registry.update_depth(url_id, 0)
            reason = classify_url(config, normalized)
            if reason is not None:
                registry.set_excluded(url_id, reason)
                continue
            registry.add_job(
                url_id, PAGE, PRIORITY_SEED, not_before_at=iso_utc()
            )
            if first_origin is None:
                first_origin = normalized.origin
        if first_origin is not None:
            connection.execute(
                "INSERT INTO crawl_origins(run_id, origin, not_before_at, robots_state) "
                "VALUES (?, ?, ?, 'unknown') ON CONFLICT(run_id, origin) DO NOTHING",
                (run_id, first_origin, iso_utc()),
            )
            robots = normalize_url(first_origin + "/robots.txt")
            robots_id, _ = registry.ensure_url(robots, with_profile=False)
            registry.add_discovery(robots_id, robots.url, "auxiliary")
            registry.add_job(robots_id, ROBOTS, PRIORITY_ROBOTS, not_before_at=iso_utc())
    return run_id


def validate_resume(
    connection: sqlite3.Connection, config: ProjectConfig, run_id: str
) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise ResumeError(f"Lauf '{run_id}' wurde nicht gefunden.")
    if row["mode"] != "crawl":
        raise ResumeError(f"Lauf '{run_id}' ist kein Crawl-Lauf und kann nicht fortgesetzt werden.")
    if row["status"] not in {"paused", "running"}:
        raise ResumeError(
            f"Lauf '{run_id}' hat Status '{row['status']}' und kann nicht fortgesetzt werden."
        )
    if row["project_id"] != config.project_id:
        raise ResumeError(
            f"Lauf '{run_id}' gehört zu Projekt '{row['project_id']}', nicht zu "
            f"'{config.project_id}'."
        )
    if row["config_hash"] != config.config_hash():
        raise ResumeError(
            f"Lauf '{run_id}' wurde mit einer anderen Konfiguration gestartet. "
            "Bitte einen neuen Lauf ohne --resume starten."
        )
    for column, expected in (
        ("crawler_version", CRAWLER_VERSION),
        ("ruleset_version", RULESET_VERSION),
        ("normalization_version", NORMALIZATION_VERSION),
    ):
        if row[column] != expected:
            raise ResumeError(
                f"Lauf '{run_id}' verwendet {column} '{row[column]}', SeoBoy erwartet "
                f"'{expected}'. Bitte einen neuen Lauf starten."
            )
    return row


def prepare_resume(connection: sqlite3.Connection, run_id: str) -> None:
    """Kennzeichnet unterbrochene Versuche und plant offene Jobs erneut ein."""
    now = iso_utc()
    with transaction(connection):
        connection.execute(
            "UPDATE http_attempts SET state = 'interrupted', finished_at = ? "
            "WHERE run_id = ? AND state = 'reserved'",
            (now, run_id),
        )
        connection.execute(
            "UPDATE crawl_jobs SET state = 'pending', not_before_at = ? "
            "WHERE run_id = ? AND state = 'in_flight'",
            (now, run_id),
        )
        connection.execute(
            "UPDATE runs SET status = 'running', stop_reason = NULL "
            "WHERE run_id = ? AND status = 'paused'",
            (run_id,),
        )


class Crawler:
    def __init__(
        self,
        connection: sqlite3.Connection,
        config: ProjectConfig,
        run_id: str,
        *,
        mode: Literal["crawl", "inspect"] = "crawl",
        client: HttpClient | None = None,
        runtime_seconds: float | None = None,
    ) -> None:
        self.connection = connection
        self.config = config
        self.run_id = run_id
        self.mode = mode
        self.registry = UrlRegistry(connection, run_id, config.project_id, config)
        self.client = client or HttpClient(
            timeout=config.crawl.request_timeout_seconds,
            max_bytes=config.crawl.max_response_bytes,
        )
        self.runtime_seconds = (
            config.crawl.max_runtime_seconds if runtime_seconds is None else runtime_seconds
        )
        self._started = time.monotonic()
        self._robots_cache: dict[str, RobotsFile | None] = {}
        row = connection.execute(
            "SELECT max_urls, max_requests FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Lauf '{run_id}' wurde nicht gefunden.")
        self.max_urls = int(row["max_urls"])
        self.max_requests = int(row["max_requests"])
        self.max_workers = 1 if mode == "inspect" else max(1, config.crawl.max_workers)
        self.max_parallel_per_host = max(1, config.crawl.max_parallel_per_host)
        self.follow_links = mode == "crawl"
        self.fetch_sitemaps = mode == "crawl"
        self._pacer = RequestPacer(config.crawl.min_request_interval_ms / 1000.0)
        self._host_inflight: dict[str, int] = {}
        self._stop_reason_pending: str | None = None

    # ------------------------------------------------------------------ Laufsteuerung

    def crawl(self) -> CrawlOutcome:
        self._normalize_interrupted()
        executor = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="seoboy-fetch"
        )
        try:
            while True:
                if self._runtime_exceeded():
                    return self._pause()
                try:
                    if self._pending_jobs() == 0:
                        return self._finish()
                    if self._requests_used() >= self.max_requests:
                        return self._stop_partial(STOP_REQUEST_LIMIT)
                    auxiliary = self._next_job((ROBOTS, SITEMAP))
                    if auxiliary is not None:
                        self._dispatch(auxiliary)
                        continue
                    tasks = self._collect_page_tasks()
                    if tasks:
                        self._run_page_tasks(tasks, executor)
                    if self._stop_reason_pending is not None:
                        reason = self._stop_reason_pending
                        self._stop_reason_pending = None
                        return self._stop_partial(reason)
                    if tasks:
                        continue
                    if self._pending_jobs() == 0:
                        return self._finish()
                    self._sleep_until_next()
                except RequestLimitReached:
                    return self._stop_partial(STOP_REQUEST_LIMIT)
                except UrlLimitReached:
                    return self._stop_partial(STOP_URL_LIMIT)
        finally:
            executor.shutdown(wait=True)

    def _collect_page_tasks(self) -> list[PageTask]:
        now = iso_utc()
        rows = self.connection.execute(
            "SELECT j.job_id, j.url_id, j.purpose, j.priority, j.not_before_at, "
            "u.normalized_url FROM crawl_jobs j "
            "JOIN urls u ON u.url_id = j.url_id "
            "WHERE j.run_id = ? AND j.state = 'pending' AND j.purpose = 'page' "
            "AND j.not_before_at <= ? "
            "ORDER BY j.priority ASC, u.normalized_url ASC, j.job_id ASC LIMIT ?",
            (self.run_id, now, max(20, self.max_workers * 8)),
        ).fetchall()
        tasks: list[PageTask] = []
        for job in rows:
            if len(tasks) >= self.max_workers:
                break
            try:
                origin = origin_of(job["normalized_url"])
            except InvalidUrl:
                continue
            if self._host_inflight.get(origin, 0) >= self.max_parallel_per_host:
                continue
            try:
                task = self._prepare_page(job)
            except RequestLimitReached:
                self._stop_reason_pending = STOP_REQUEST_LIMIT
                break
            except UrlLimitReached:
                self._stop_reason_pending = STOP_URL_LIMIT
                break
            if task is None:
                continue
            self._host_inflight[origin] = self._host_inflight.get(origin, 0) + 1
            tasks.append(task)
        return tasks

    def _run_page_tasks(
        self, tasks: list[PageTask], executor: ThreadPoolExecutor
    ) -> None:
        futures = {executor.submit(self._fetch_page, task): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            try:
                try:
                    result = future.result()
                except Exception as error:
                    result = FetchResult(
                        url=task.url,
                        status_code=None,
                        error_code="network_error",
                        error_detail=str(error)[:500],
                    )
                self._store_page(task.job, task.reservation, result)
            finally:
                remaining = self._host_inflight.get(task.origin, 1) - 1
                if remaining <= 0:
                    self._host_inflight.pop(task.origin, None)
                else:
                    self._host_inflight[task.origin] = remaining

    def _fetch_page(self, task: PageTask) -> FetchResult:
        if task.delay > 0:
            time.sleep(task.delay)
        return self.client.fetch(task.url)

    def _runtime_exceeded(self) -> bool:
        return (time.monotonic() - self._started) >= self.runtime_seconds

    def _requests_used(self) -> int:
        (count,) = self.connection.execute(
            "SELECT COUNT(*) FROM http_attempts WHERE run_id = ?", (self.run_id,)
        ).fetchone()
        return int(count)

    def _pending_jobs(self) -> int:
        (count,) = self.connection.execute(
            "SELECT COUNT(*) FROM crawl_jobs WHERE run_id = ? AND state IN ('pending', 'in_flight')",
            (self.run_id,),
        ).fetchone()
        return int(count)

    def _normalize_interrupted(self) -> None:
        now = iso_utc()
        with transaction(self.connection):
            self.connection.execute(
                "UPDATE http_attempts SET state = 'interrupted', finished_at = ? "
                "WHERE run_id = ? AND state = 'reserved'",
                (now, self.run_id),
            )
            self.connection.execute(
                "UPDATE crawl_jobs SET state = 'pending', not_before_at = ? "
                "WHERE run_id = ? AND state = 'in_flight'",
                (now, self.run_id),
            )

    def _finish(self) -> CrawlOutcome:
        deferred = self.connection.execute(
            "SELECT reason_code FROM run_urls WHERE run_id = ? AND state = 'deferred' "
            "ORDER BY url_id LIMIT 1",
            (self.run_id,),
        ).fetchone()
        if deferred is not None:
            return CrawlOutcome("partial", deferred["reason_code"] or STOP_URL_LIMIT)
        return CrawlOutcome("complete", STOP_COMPLETE)

    def _pause(self) -> CrawlOutcome:
        with transaction(self.connection):
            self.connection.execute(
                "UPDATE runs SET status = 'paused', stop_reason = ? WHERE run_id = ?",
                (STOP_RUNTIME_LIMIT, self.run_id),
            )
        return CrawlOutcome("paused", STOP_RUNTIME_LIMIT)

    def _stop_partial(self, reason: str) -> CrawlOutcome:
        with transaction(self.connection):
            pending_pages = self.connection.execute(
                "SELECT j.job_id, j.url_id FROM crawl_jobs j "
                "WHERE j.run_id = ? AND j.state = 'pending' AND j.purpose = 'page'",
                (self.run_id,),
            ).fetchall()
            for row in pending_pages:
                self.connection.execute(
                    "UPDATE run_urls SET state = 'deferred', reason_code = ? "
                    "WHERE run_id = ? AND url_id = ? AND state IN ('discovered', 'queued')",
                    (reason, self.run_id, row["url_id"]),
                )
            self.connection.execute(
                "UPDATE crawl_jobs SET state = 'skipped', reason_code = ? "
                "WHERE run_id = ? AND state = 'pending'",
                (reason, self.run_id),
            )
            self.connection.execute(
                "UPDATE runs SET stop_reason = ? WHERE run_id = ?",
                (reason, self.run_id),
            )
        return CrawlOutcome("partial", reason)

    def _next_job(self, purposes: tuple[str, ...] | None = None) -> sqlite3.Row | None:
        now = iso_utc()
        query = (
            "SELECT j.job_id, j.url_id, j.purpose, j.priority, j.not_before_at, "
            "u.normalized_url FROM crawl_jobs j "
            "JOIN urls u ON u.url_id = j.url_id "
            "WHERE j.run_id = ? AND j.state = 'pending' AND j.not_before_at <= ?"
        )
        parameters: list[Any] = [self.run_id, now]
        if purposes:
            query += " AND j.purpose IN (" + ", ".join("?" for _ in purposes) + ")"
            parameters.extend(purposes)
        query += " ORDER BY j.priority ASC, u.normalized_url ASC, j.job_id ASC LIMIT 100"
        rows = self.connection.execute(query, parameters).fetchall()
        for row in rows:
            try:
                origin = origin_of(row["normalized_url"])
            except InvalidUrl:
                continue
            origin_row = self._get_origin(origin)
            if origin_row["not_before_at"] <= now:
                return row
        return None

    def _sleep_until_next(self) -> None:
        rows = self.connection.execute(
            "SELECT not_before_at FROM crawl_jobs WHERE run_id = ? AND state = 'pending' "
            "UNION ALL SELECT not_before_at FROM crawl_origins WHERE run_id = ?",
            (self.run_id, self.run_id),
        ).fetchall()
        now = utc_now()
        soonest: datetime | None = None
        for row in rows:
            try:
                moment = datetime.fromisoformat(row["not_before_at"].replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if soonest is None or moment < soonest:
                soonest = moment
        delay = 0.05
        if soonest is not None:
            delta = (soonest - now).total_seconds()
            delay = min(max(delta, 0.02), 0.5)
        remaining = self.runtime_seconds - (time.monotonic() - self._started)
        time.sleep(max(0.0, min(delay, remaining)))

    # ------------------------------------------------------------------ Dispatch

    def _dispatch(self, job: sqlite3.Row) -> None:
        if job["purpose"] == ROBOTS:
            self._dispatch_robots(job)
        elif job["purpose"] == SITEMAP:
            self._dispatch_sitemap(job)

    def _mark_job(self, job_id: int, state: str, reason: str | None = None) -> None:
        self.connection.execute(
            "UPDATE crawl_jobs SET state = ?, reason_code = COALESCE(?, reason_code) "
            "WHERE run_id = ? AND job_id = ?",
            (state, reason, self.run_id, job_id),
        )

    def _mark_url(self, url_id: int, state: str, reason: str | None = None) -> None:
        self.connection.execute(
            "UPDATE run_urls SET state = ?, reason_code = ? WHERE run_id = ? AND url_id = ?",
            (state, reason, self.run_id, url_id),
        )

    def _reserve(self, job: sqlite3.Row, *, admit_page: bool) -> Reservation | None:
        now = iso_utc()
        with transaction(self.connection):
            current = self.connection.execute(
                "SELECT state FROM crawl_jobs WHERE run_id = ? AND job_id = ?",
                (self.run_id, job["job_id"]),
            ).fetchone()
            if current is None or current["state"] != "pending":
                return None
            run_url = self.connection.execute(
                "SELECT admitted_at, click_depth FROM run_urls WHERE run_id = ? AND url_id = ?",
                (self.run_id, job["url_id"]),
            ).fetchone()
            if run_url is None:
                self._mark_job(job["job_id"], "skipped", "url_missing")
                return None
            if admit_page and run_url["admitted_at"] is None:
                (admitted,) = self.connection.execute(
                    "SELECT COUNT(*) FROM run_urls WHERE run_id = ? AND admitted_at IS NOT NULL",
                    (self.run_id,),
                ).fetchone()
                if int(admitted) >= self.max_urls:
                    raise UrlLimitReached
                self.connection.execute(
                    "UPDATE run_urls SET admitted_at = ?, state = 'queued' "
                    "WHERE run_id = ? AND url_id = ? AND admitted_at IS NULL",
                    (now, self.run_id, job["url_id"]),
                )
            try:
                origin = origin_of(job["normalized_url"])
            except InvalidUrl:
                self._mark_job(job["job_id"], "skipped", "invalid_url")
                return None
            origin_row = self.connection.execute(
                "SELECT not_before_at FROM crawl_origins WHERE run_id = ? AND origin = ?",
                (self.run_id, origin),
            ).fetchone()
            if origin_row is not None and origin_row["not_before_at"] > now:
                self.connection.execute(
                    "UPDATE crawl_jobs SET not_before_at = ? WHERE run_id = ? AND job_id = ?",
                    (origin_row["not_before_at"], self.run_id, job["job_id"]),
                )
                return None
            (used,) = self.connection.execute(
                "SELECT COUNT(*) FROM http_attempts WHERE run_id = ?", (self.run_id,)
            ).fetchone()
            if int(used) >= self.max_requests:
                raise RequestLimitReached
            (attempt_no,) = self.connection.execute(
                "SELECT COALESCE(MAX(attempt_no), 0) + 1 FROM http_attempts "
                "WHERE run_id = ? AND job_id = ?",
                (self.run_id, job["job_id"]),
            ).fetchone()
            attempt_id = database.next_id(
                self.connection, "http_attempts", "attempt_id", self.run_id
            )
            self.connection.execute(
                "INSERT INTO http_attempts(run_id, attempt_id, job_id, attempt_no, state, "
                "reserved_at) VALUES (?, ?, ?, ?, 'reserved', ?)",
                (self.run_id, attempt_id, job["job_id"], attempt_no, now),
            )
            self.connection.execute(
                "UPDATE crawl_jobs SET state = 'in_flight' WHERE run_id = ? AND job_id = ?",
                (self.run_id, job["job_id"]),
            )
        return Reservation(attempt_id=attempt_id, attempt_no=int(attempt_no))

    def _get_origin(self, origin: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM crawl_origins WHERE run_id = ? AND origin = ?",
            (self.run_id, origin),
        ).fetchone()
        if row is not None:
            return row
        with transaction(self.connection):
            self.connection.execute(
                "INSERT INTO crawl_origins(run_id, origin, not_before_at, robots_state) "
                "VALUES (?, ?, ?, 'unknown') ON CONFLICT(run_id, origin) DO NOTHING",
                (self.run_id, origin, iso_utc()),
            )
        return self.connection.execute(
            "SELECT * FROM crawl_origins WHERE run_id = ? AND origin = ?",
            (self.run_id, origin),
        ).fetchone()

    def _update_origin_pause(
        self, origin: str, now: datetime, retry_after: int | None
    ) -> None:
        interval = self.config.crawl.min_request_interval_ms / 1000.0
        pause = interval
        if retry_after is not None:
            pause = max(pause, float(retry_after))
        not_before = iso_utc(now + timedelta(seconds=pause))
        self.connection.execute(
            "UPDATE crawl_origins SET not_before_at = CASE WHEN not_before_at > ? "
            "THEN not_before_at ELSE ? END WHERE run_id = ? AND origin = ?",
            (not_before, not_before, self.run_id, origin),
        )

    def _robots_file(self, origin: str) -> RobotsFile | None:
        if origin in self._robots_cache:
            return self._robots_cache[origin]
        row = self.connection.execute(
            "SELECT robots_state, robots_rules_json FROM crawl_origins "
            "WHERE run_id = ? AND origin = ?",
            (self.run_id, origin),
        ).fetchone()
        robots: RobotsFile | None = None
        if row is not None and row["robots_state"] == "available" and row["robots_rules_json"]:
            try:
                payload = json.loads(row["robots_rules_json"])
                robots = RobotsFile.parse(payload.get("raw", ""))
            except (ValueError, TypeError):
                robots = None
        self._robots_cache[origin] = robots
        return robots

    # ------------------------------------------------------------------ Robots

    def _ensure_robots_job(self, origin: str, referrer_url_id: int) -> str:
        robots_url = origin + "/robots.txt"
        now = iso_utc()
        with transaction(self.connection):
            self.connection.execute(
                "INSERT INTO crawl_origins(run_id, origin, not_before_at, robots_state) "
                "VALUES (?, ?, ?, 'unknown') ON CONFLICT(run_id, origin) DO NOTHING",
                (self.run_id, origin, now),
            )
            try:
                normalized = normalize_url(robots_url)
            except InvalidUrl:
                return "skipped"
            url_id, _ = self.registry.ensure_url(normalized, with_profile=False)
            row = self.connection.execute(
                "SELECT state FROM crawl_jobs WHERE run_id = ? AND purpose = 'robots' "
                "AND url_id = ?",
                (self.run_id, url_id),
            ).fetchone()
            if row is None:
                self.registry.add_discovery(
                    url_id, robots_url, "auxiliary", from_url_id=referrer_url_id
                )
                self.registry.add_job(url_id, ROBOTS, PRIORITY_ROBOTS, not_before_at=now)
                return "pending"
            return row["state"]

    def _dispatch_robots(self, job: sqlite3.Row) -> None:
        reservation = self._reserve(job, admit_page=False)
        if reservation is None:
            return
        result = self.client.fetch(job["normalized_url"])
        origin = origin_of(job["normalized_url"])
        now = utc_now()
        retry_after = parse_retry_after(result.headers.get("retry-after"), now)
        with transaction(self.connection):
            self._save_attempt(job, reservation, result)
            self._update_origin_pause(origin, now, retry_after)
            if self._retry_auxiliary(job, reservation, result, now, retry_after):
                return
            state, raw, sitemaps = self._interpret_robots(result)
            self.connection.execute(
                "UPDATE crawl_origins SET robots_state = ?, robots_attempt_id = ?, "
                "robots_rules_json = ?, not_before_at = CASE WHEN not_before_at > ? "
                "THEN not_before_at ELSE ? END WHERE run_id = ? AND origin = ?",
                (
                    state,
                    reservation.attempt_id,
                    json.dumps({"raw": raw, "sitemaps": sitemaps}, ensure_ascii=False),
                    iso_utc(now + timedelta(milliseconds=self.config.crawl.min_request_interval_ms)),
                    iso_utc(now + timedelta(milliseconds=self.config.crawl.min_request_interval_ms)),
                    self.run_id,
                    origin,
                ),
            )
            self._mark_job(job["job_id"], "done")
            self._mark_url(job["url_id"], "finished", "robots")
            self._robots_cache.pop(origin, None)
            if self.fetch_sitemaps and state == "available":
                targets = list(sitemaps)
                if not targets and origin == origin_of(self.config.start_url):
                    targets.append(origin + "/sitemap.xml")
                for target in targets:
                    self._enqueue_sitemap(target, job["url_id"], from_robots=True)

    def _interpret_robots(self, result: FetchResult) -> tuple[str, str, list[str]]:
        if result.error_code is not None:
            return "unreachable", "", []
        assert result.status_code is not None
        if 200 <= result.status_code < 300:
            raw = decode_body(result)[:262_144]
            parsed = RobotsFile.parse(raw)
            return "available", raw, parsed.sitemaps
        if 400 <= result.status_code < 500:
            return "unavailable", "", []
        return "unreachable", "", []

    def _enqueue_sitemap(
        self, raw_url: str, referrer_url_id: int, *, from_robots: bool
    ) -> None:
        try:
            normalized = normalize_url(raw_url, self.config.crawl.remove_query_params)
        except InvalidUrl:
            return
        if not is_internal(normalized, self.config.allowed_hosts):
            return
        url_id, _ = self.registry.ensure_url(normalized, with_profile=False)
        row = self.connection.execute(
            "SELECT state FROM crawl_jobs WHERE run_id = ? AND purpose = 'sitemap' AND url_id = ?",
            (self.run_id, url_id),
        ).fetchone()
        if row is not None:
            return
        self.registry.add_discovery(url_id, raw_url, "auxiliary", from_url_id=referrer_url_id)
        self.registry.add_job(
            url_id, SITEMAP, PRIORITY_SITEMAP, not_before_at=iso_utc()
        )

    # ------------------------------------------------------------------ Sitemaps

    def _dispatch_sitemap(self, job: sqlite3.Row) -> None:
        origin = origin_of(job["normalized_url"])
        self._get_origin(origin)
        reservation = self._reserve(job, admit_page=False)
        if reservation is None:
            return
        result = self.client.fetch(job["normalized_url"])
        now = utc_now()
        retry_after = parse_retry_after(result.headers.get("retry-after"), now)
        kind, locations = self._parse_sitemap_result(result)
        with transaction(self.connection):
            self._save_attempt(job, reservation, result)
            self._update_origin_pause(origin, now, retry_after)
            if self._retry_auxiliary(job, reservation, result, now, retry_after):
                return
            self._mark_job(job["job_id"], "done", kind if kind in {"invalid", "http_error"} else None)
            self._mark_url(
                job["url_id"], "finished",
                "invalid_sitemap" if kind == "invalid" else "sitemap",
            )
            if kind == "index":
                for raw_url in locations:
                    self._enqueue_sitemap(raw_url, job["url_id"], from_robots=False)
            elif kind == "urlset":
                for raw_url in locations:
                    self._enqueue_sitemap_page(raw_url, job["url_id"])

    def _parse_sitemap_result(self, result: FetchResult) -> tuple[str, list[str]]:
        if result.error_code is not None:
            return "http_error", []
        assert result.status_code is not None
        if not 200 <= result.status_code < 300:
            return "http_error", []
        body = result.body
        if body[:2] == b"\x1f\x8b":
            try:
                body = gzip.decompress(body)[: self.config.crawl.max_response_bytes * 2]
            except (OSError, EOFError):
                return "invalid", []
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError:
            return "invalid", []
        tag = root.tag.rsplit("}", 1)[-1].lower()
        if tag not in {"sitemapindex", "urlset"}:
            return "invalid", []
        locations: list[str] = []
        direct_children = {"sitemapindex": "sitemap", "urlset": "url"}[tag]
        for child in root:
            if child.tag.rsplit("}", 1)[-1].lower() != direct_children:
                continue
            for element in child:
                if element.tag.rsplit("}", 1)[-1].lower() != "loc":
                    continue
                value = (element.text or "").strip()
                if value:
                    locations.append(value)
                break
        return ("index" if tag == "sitemapindex" else "urlset"), locations

    def _enqueue_sitemap_page(self, raw_url: str, sitemap_url_id: int) -> None:
        try:
            normalized = normalize_url(raw_url, self.config.crawl.remove_query_params)
        except InvalidUrl:
            return
        url_id, _ = self.registry.ensure_url(normalized)
        self.registry.add_discovery(
            url_id, raw_url, "sitemap", from_url_id=sitemap_url_id
        )
        reason = classify_url(self.config, normalized)
        if reason is not None:
            self.registry.set_excluded(url_id, reason)
            return
        if not self.follow_links:
            return
        row = self.connection.execute(
            "SELECT click_depth FROM run_urls WHERE run_id = ? AND url_id = ?",
            (self.run_id, url_id),
        ).fetchone()
        depth = int(row["click_depth"]) if row and row["click_depth"] is not None else None
        priority = PRIORITY_LINK_BASE + depth if depth is not None else PRIORITY_UNLINKED
        self.registry.add_job(url_id, PAGE, priority, not_before_at=iso_utc())

    # ------------------------------------------------------------------ Seiten

    def _prepare_page(self, job: sqlite3.Row) -> PageTask | None:
        run_url = self.connection.execute(
            "SELECT state, admitted_at, click_depth FROM run_urls "
            "WHERE run_id = ? AND url_id = ?",
            (self.run_id, job["url_id"]),
        ).fetchone()
        if run_url is None:
            with transaction(self.connection):
                self._mark_job(job["job_id"], "skipped", "url_missing")
            return None
        if run_url["state"] in {"blocked", "excluded", "deferred"}:
            with transaction(self.connection):
                self._mark_job(job["job_id"], "skipped", run_url["state"])
            return None

        origin = origin_of(job["normalized_url"])
        origin_row = self._get_origin(origin)
        if origin_row["robots_state"] == "unknown":
            robots_state = self._ensure_robots_job(origin, job["url_id"])
            if robots_state in {"pending", "in_flight"}:
                return None
            origin_row = self._get_origin(origin)
        if origin_row["robots_state"] == "available":
            robots = self._robots_file(origin)
            if robots is not None:
                normalized = normalize_url(job["normalized_url"])
                decision = robots.evaluate(_origin_path(normalized), SEOBOY)
                if not decision.allowed:
                    with transaction(self.connection):
                        self._mark_url(job["url_id"], "blocked", "robots_disallowed")
                        self._mark_job(job["job_id"], "skipped", "robots_disallowed")
                    return None

        reservation = self._reserve(job, admit_page=True)
        if reservation is None:
            return None
        delay = self._pacer.reserve(origin)
        return PageTask(
            job=job,
            reservation=reservation,
            url=job["normalized_url"],
            origin=origin,
            delay=delay,
        )

    def _store_page(
        self, job: sqlite3.Row, reservation: Reservation, result: FetchResult
    ) -> None:
        now = utc_now()
        retry_after = parse_retry_after(result.headers.get("retry-after"), now)
        normalized = normalize_url(job["normalized_url"])
        origin = normalized.origin
        with transaction(self.connection):
            self._save_attempt(job, reservation, result)
            self._update_origin_pause(origin, now, retry_after)

            if result.error_code is not None:
                if result.error_code == "timeout" and reservation.attempt_no < MAX_ATTEMPTS:
                    self._schedule_retry(job, now, retry_after)
                    return
                self._mark_job(job["job_id"], "done")
                self._mark_url(job["url_id"], "finished", result.error_code)
                return

            assert result.status_code is not None
            status = result.status_code
            if 300 <= status < 400 and status != 304:
                self._handle_redirect(job, reservation, result, normalized, now)
                return
            if status == 429 or 500 <= status < 600:
                if reservation.attempt_no < MAX_ATTEMPTS:
                    self._schedule_retry(job, now, retry_after)
                    return
                self._mark_job(job["job_id"], "done")
                self._mark_url(
                    job["url_id"], "finished",
                    "rate_limited" if status == 429 else "http_error",
                )
                return
            if 200 <= status < 300:
                self._save_page_success(job, reservation, result, normalized, now)
                return
            self._mark_job(job["job_id"], "done")
            self._mark_url(job["url_id"], "finished", "http_error")

    def _retry_auxiliary(
        self,
        job: sqlite3.Row,
        reservation: Reservation,
        result: FetchResult,
        now: datetime,
        retry_after: int | None,
    ) -> bool:
        if reservation.attempt_no >= MAX_ATTEMPTS:
            return False
        retryable = result.error_code == "timeout" or result.status_code == 429 or (
            result.status_code is not None and 500 <= result.status_code < 600
        )
        if not retryable:
            return False
        self._schedule_retry(job, now, retry_after)
        return True

    def _schedule_retry(
        self, job: sqlite3.Row, now: datetime, retry_after: int | None
    ) -> None:
        delay = self.config.crawl.min_request_interval_ms / 1000.0
        if retry_after is not None:
            delay = max(delay, float(retry_after))
        self.connection.execute(
            "UPDATE crawl_jobs SET state = 'pending', not_before_at = ? "
            "WHERE run_id = ? AND job_id = ?",
            (iso_utc(now + timedelta(seconds=delay)), self.run_id, job["job_id"]),
        )

    def _save_page_success(
        self,
        job: sqlite3.Row,
        reservation: Reservation,
        result: FetchResult,
        normalized: NormalizedUrl,
        now: datetime,
    ) -> None:
        links_complete = 0
        if result.is_html and result.body:
            text = decode_body(result)
            page = extract_page(text, result.url, result.header_items)
            if self.follow_links and not result.truncated:
                links_complete = 1
            header_canonicals = [
                resolve_url(result.url, value) or value
                for value in link_header_canonicals(result.header_items)
            ]
            signals = {
                "canonical": list(page.canonical),
                "canonical_header": header_canonicals,
                "robots_tokens": list(page.robots.tokens),
                "robots_meta": page.robots.meta_raw,
                "x_robots_tag": page.robots.header_raw,
                "noindex": page.robots.noindex,
                "googlebot_specific": page.robots.googlebot_specific,
                "link_count": len(page.links),
                "base_href": page.base_href,
                "truncated": result.truncated,
                "content_type": result.content_type,
            }
            observation_id = database.next_id(
                self.connection, "page_observations", "observation_id", self.run_id
            )
            self.connection.execute(
                "INSERT INTO page_observations(run_id, observation_id, url_id, method, "
                "attempt_id, observed_at, title, meta_description, links_complete, "
                "signals_json) VALUES (?, ?, ?, 'http', ?, ?, ?, ?, ?, ?)",
                (
                    self.run_id,
                    observation_id,
                    job["url_id"],
                    reservation.attempt_id,
                    iso_utc(now),
                    page.title,
                    page.meta_description,
                    links_complete,
                    json.dumps(signals, ensure_ascii=False),
                ),
            )
            if self.follow_links:
                self._store_links(job, observation_id, page.links, normalized, now)
            self._mark_url(job["url_id"], "finished", None)
        else:
            self._mark_url(
                job["url_id"], "finished",
                "non_html" if not result.is_html else "empty_body",
            )
        self._mark_job(job["job_id"], "done")

    def _store_links(
        self,
        job: sqlite3.Row,
        observation_id: int,
        links: tuple[str, ...],
        source: NormalizedUrl,
        now: datetime,
    ) -> None:
        source_depth = self.connection.execute(
            "SELECT click_depth FROM run_urls WHERE run_id = ? AND url_id = ?",
            (self.run_id, job["url_id"]),
        ).fetchone()["click_depth"]
        depth = int(source_depth) + 1 if source_depth is not None else None
        for raw_link in links:
            resolved = resolve_url(source.url, raw_link)
            if resolved is None:
                continue
            try:
                target = normalize_url(resolved, self.config.crawl.remove_query_params)
            except InvalidUrl:
                continue
            target_id, _ = self.registry.ensure_url(target)
            self.connection.execute(
                "INSERT OR IGNORE INTO links(run_id, observation_id, target_url_id) "
                "VALUES (?, ?, ?)",
                (self.run_id, observation_id, target_id),
            )
            self.registry.add_discovery(
                target_id, resolved, "link", from_url_id=job["url_id"]
            )
            reason = classify_url(self.config, target)
            if reason is not None:
                self.registry.set_excluded(target_id, reason)
                continue
            if target.url == source.url:
                continue
            if depth is not None:
                if self.registry.update_depth(target_id, depth):
                    self.registry.update_pending_priority(
                        target_id, PRIORITY_LINK_BASE + depth
                    )
            priority = (
                PRIORITY_LINK_BASE + depth if depth is not None else PRIORITY_UNLINKED
            )
            self.registry.add_job(target_id, PAGE, priority, not_before_at=iso_utc(now))

    def _handle_redirect(
        self,
        job: sqlite3.Row,
        reservation: Reservation,
        result: FetchResult,
        source: NormalizedUrl,
        now: datetime,
    ) -> None:
        raw_location = result.redirect_location
        resolved = resolve_url(source.url, raw_location) if raw_location else None
        target: NormalizedUrl | None = None
        if resolved:
            try:
                target = normalize_url(resolved, self.config.crawl.remove_query_params)
            except InvalidUrl:
                target = None
        target_id: int | None = None
        if target is not None:
            target_id, _ = self.registry.ensure_url(target)
            self.connection.execute(
                "UPDATE http_attempts SET location_url_id = ? "
                "WHERE run_id = ? AND attempt_id = ?",
                (target_id, self.run_id, reservation.attempt_id),
            )
            self.registry.add_discovery(
                target_id, resolved, "redirect", from_url_id=job["url_id"]
            )
        self._mark_job(job["job_id"], "done")
        self._mark_url(job["url_id"], "finished", "redirect")
        if target is None or target_id is None or not self.follow_links:
            return
        reason = classify_url(self.config, target)
        if reason is not None:
            self.registry.set_excluded(target_id, reason)
            return
        if target.url == source.url:
            return
        if self._redirect_chain_length(job["url_id"]) + 1 > self.config.crawl.max_redirects:
            self.connection.execute(
                "UPDATE run_urls SET state = 'deferred', reason_code = ? "
                "WHERE run_id = ? AND url_id = ? AND admitted_at IS NULL",
                (STOP_HOP_LIMIT, self.run_id, target_id),
            )
            return
        row = self.connection.execute(
            "SELECT click_depth FROM run_urls WHERE run_id = ? AND url_id = ?",
            (self.run_id, job["url_id"]),
        ).fetchone()
        depth = int(row["click_depth"]) if row and row["click_depth"] is not None else None
        if depth is not None:
            self.registry.update_depth(target_id, depth)
        priority = PRIORITY_LINK_BASE + depth if depth is not None else PRIORITY_UNLINKED
        self.registry.add_job(target_id, PAGE, priority, not_before_at=iso_utc(now))

    def _redirect_chain_length(self, url_id: int) -> int:
        """Anzahl interner Redirect-Schritte vor dieser URL (zyklensicher)."""
        edges = self.connection.execute(
            "SELECT j.url_id AS source, a.location_url_id AS target FROM http_attempts a "
            "JOIN crawl_jobs j ON j.run_id = a.run_id AND j.job_id = a.job_id "
            "WHERE a.run_id = ? AND a.status_code BETWEEN 300 AND 399 "
            "AND a.location_url_id IS NOT NULL",
            (self.run_id,),
        ).fetchall()
        reverse: dict[int, set[int]] = {}
        for edge in edges:
            reverse.setdefault(int(edge["target"]), set()).add(int(edge["source"]))
        seen = {url_id}
        frontier = [url_id]
        depth = 0
        while frontier:
            next_frontier: list[int] = []
            for current in frontier:
                for predecessor in reverse.get(current, set()):
                    if predecessor in seen:
                        continue
                    seen.add(predecessor)
                    next_frontier.append(predecessor)
            if next_frontier:
                depth += 1
                frontier = next_frontier
            else:
                break
        return depth

    def _save_attempt(
        self, job: sqlite3.Row, reservation: Reservation, result: FetchResult
    ) -> None:
        if result.error_code is not None:
            self.connection.execute(
                "UPDATE http_attempts SET state = 'transport_error', finished_at = ?, "
                "error_code = ? WHERE run_id = ? AND attempt_id = ?",
                (iso_utc(), result.error_code, self.run_id, reservation.attempt_id),
            )
            return
        self.connection.execute(
            "UPDATE http_attempts SET state = 'response', finished_at = ?, status_code = ?, "
            "content_type = ?, headers_json = ? WHERE run_id = ? AND attempt_id = ?",
            (
                iso_utc(),
                result.status_code,
                result.content_type,
                _headers_payload(result),
                self.run_id,
                reservation.attempt_id,
            ),
        )
