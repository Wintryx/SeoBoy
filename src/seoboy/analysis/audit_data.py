"""Geladene Laufdaten für Regeln, Maßnahmen, Berichte und Diff."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import sqlite3
from typing import Any

from seoboy.infrastructure.config import ProjectConfig
from seoboy.shared.robots import RobotsFile


@dataclass
class AttemptInfo:
    attempt_id: int
    job_id: int
    url_id: int
    purpose: str
    attempt_no: int
    state: str
    status_code: int | None
    content_type: str | None
    error_code: str | None
    reserved_at: str
    finished_at: str | None
    location_url_id: int | None
    headers: dict[str, str]

    @property
    def observed_at(self) -> str:
        return self.finished_at or self.reserved_at


@dataclass
class ObservationInfo:
    observation_id: int
    url_id: int
    attempt_id: int | None
    observed_at: str
    title: str | None
    meta_description: str | None
    links_complete: bool
    signals: dict[str, Any]


@dataclass
class UrlInfo:
    url_id: int
    url: str
    state: str
    reason_code: str | None
    page_type: str | None
    business_value: str
    expected_indexable: bool | None
    click_depth: int | None
    admitted_at: str | None
    kinds: set[str] = field(default_factory=set)
    sitemap_sources: list[int] = field(default_factory=list)
    discovery_originals: list[str] = field(default_factory=list)

    @property
    def is_important(self) -> bool:
        return self.business_value == "high"

    @property
    def scope(self) -> str:
        return self.page_type or "unknown"


@dataclass
class RobotsInfo:
    origin: str
    state: str
    attempt_id: int | None
    robots: RobotsFile | None
    raw: str


class RunData:
    def __init__(
        self,
        connection: sqlite3.Connection,
        config: ProjectConfig,
        run_id: str,
    ) -> None:
        self.connection = connection
        self.config = config
        self.run_id = run_id
        self.run: dict[str, Any] = {}
        self.urls: dict[int, UrlInfo] = {}
        self.url_by_url: dict[str, UrlInfo] = {}
        self.page_url_ids: set[int] = set()
        self.aux_url_ids: set[int] = set()
        self.jobs: list[dict[str, Any]] = []
        self.attempts: list[AttemptInfo] = []
        self.attempts_by_url: dict[int, list[AttemptInfo]] = {}
        self.observations: dict[int, list[ObservationInfo]] = {}
        self.links: dict[int, dict[int, bool]] = {}
        self.inbound: dict[int, set[int]] = {}
        self.redirects: dict[int, int] = {}
        self.robots: dict[str, RobotsInfo] = {}
        self.source_imports: list[dict[str, Any]] = []
        self.datasets: list[dict[str, Any]] = []
        self.metrics: dict[int, list[dict[str, Any]]] = {}
        self.load()

    # ------------------------------------------------------------------ Laden

    def load(self) -> None:
        row = self.connection.execute(
            "SELECT * FROM runs WHERE run_id = ?", (self.run_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Lauf '{self.run_id}' wurde nicht gefunden.")
        self.run = dict(row)

        for row in self.connection.execute(
            "SELECT u.url_id, u.normalized_url, r.state, r.reason_code, r.page_type, "
            "r.business_value, r.expected_indexable, r.click_depth, r.admitted_at "
            "FROM urls u JOIN run_urls r ON r.url_id = u.url_id AND r.run_id = ? "
            "ORDER BY u.url_id",
            (self.run_id,),
        ):
            expected = row["expected_indexable"]
            info = UrlInfo(
                url_id=int(row["url_id"]),
                url=row["normalized_url"],
                state=row["state"],
                reason_code=row["reason_code"],
                page_type=row["page_type"],
                business_value=row["business_value"],
                expected_indexable=None if expected is None else bool(expected),
                click_depth=None if row["click_depth"] is None else int(row["click_depth"]),
                admitted_at=row["admitted_at"],
            )
            self.urls[info.url_id] = info
            self.url_by_url[info.url] = info

        for row in self.connection.execute(
            "SELECT url_id, kind, from_url_id, import_id, original_url "
            "FROM url_discoveries WHERE run_id = ?",
            (self.run_id,),
        ):
            info = self.urls.get(int(row["url_id"]))
            if info is None:
                continue
            info.kinds.add(row["kind"])
            if row["original_url"] not in info.discovery_originals:
                info.discovery_originals.append(row["original_url"])
            if row["kind"] == "sitemap" and row["from_url_id"] is not None:
                source = int(row["from_url_id"])
                if source not in info.sitemap_sources:
                    info.sitemap_sources.append(source)

        for row in self.connection.execute(
            "SELECT job_id, url_id, purpose, state, priority, reason_code, not_before_at "
            "FROM crawl_jobs WHERE run_id = ? ORDER BY job_id",
            (self.run_id,),
        ):
            job = dict(row)
            self.jobs.append(job)
            url_id = int(job["url_id"])
            if job["purpose"] == "page":
                self.page_url_ids.add(url_id)
            else:
                self.aux_url_ids.add(url_id)

        for row in self.connection.execute(
            "SELECT a.attempt_id, a.job_id, j.url_id, j.purpose, a.attempt_no, a.state, "
            "a.status_code, a.content_type, a.error_code, a.reserved_at, a.finished_at, "
            "a.location_url_id, a.headers_json FROM http_attempts a "
            "JOIN crawl_jobs j ON j.run_id = a.run_id AND j.job_id = a.job_id "
            "WHERE a.run_id = ? ORDER BY a.job_id, a.attempt_no",
            (self.run_id,),
        ):
            try:
                headers = json.loads(row["headers_json"]) if row["headers_json"] else {}
            except (TypeError, ValueError):
                headers = {}
            attempt = AttemptInfo(
                attempt_id=int(row["attempt_id"]),
                job_id=int(row["job_id"]),
                url_id=int(row["url_id"]),
                purpose=row["purpose"],
                attempt_no=int(row["attempt_no"]),
                state=row["state"],
                status_code=None if row["status_code"] is None else int(row["status_code"]),
                content_type=row["content_type"],
                error_code=row["error_code"],
                reserved_at=row["reserved_at"],
                finished_at=row["finished_at"],
                location_url_id=(
                    None if row["location_url_id"] is None else int(row["location_url_id"])
                ),
                headers=headers,
            )
            self.attempts.append(attempt)
            self.attempts_by_url.setdefault(attempt.url_id, []).append(attempt)
            if (
                attempt.purpose == "page"
                and attempt.status_code is not None
                and 300 <= attempt.status_code < 400
                and attempt.location_url_id is not None
            ):
                self.redirects[attempt.url_id] = attempt.location_url_id

        for row in self.connection.execute(
            "SELECT observation_id, url_id, attempt_id, observed_at, title, "
            "meta_description, links_complete, signals_json FROM page_observations "
            "WHERE run_id = ? AND method = 'http' ORDER BY observation_id",
            (self.run_id,),
        ):
            try:
                signals = json.loads(row["signals_json"])
            except (TypeError, ValueError):
                signals = {}
            observation = ObservationInfo(
                observation_id=int(row["observation_id"]),
                url_id=int(row["url_id"]),
                attempt_id=(
                    None if row["attempt_id"] is None else int(row["attempt_id"])
                ),
                observed_at=row["observed_at"],
                title=row["title"],
                meta_description=row["meta_description"],
                links_complete=bool(row["links_complete"]),
                signals=signals if isinstance(signals, dict) else {},
            )
            self.observations.setdefault(observation.url_id, []).append(observation)

        for row in self.connection.execute(
            "SELECT l.observation_id, o.url_id AS source_url_id, l.target_url_id, "
            "o.links_complete FROM links l JOIN page_observations o "
            "ON o.run_id = l.run_id AND o.observation_id = l.observation_id "
            "WHERE l.run_id = ?",
            (self.run_id,),
        ):
            source = int(row["source_url_id"])
            target = int(row["target_url_id"])
            complete = bool(row["links_complete"])
            self.links.setdefault(source, {})[target] = complete
            if complete:
                self.inbound.setdefault(target, set()).add(source)

        for row in self.connection.execute(
            "SELECT origin, robots_state, robots_attempt_id, robots_rules_json "
            "FROM crawl_origins WHERE run_id = ?",
            (self.run_id,),
        ):
            raw = ""
            if row["robots_rules_json"]:
                try:
                    payload = json.loads(row["robots_rules_json"])
                    raw = payload.get("raw", "") if isinstance(payload, dict) else ""
                except (TypeError, ValueError):
                    raw = ""
            robots = RobotsFile.parse(raw) if row["robots_state"] == "available" else None
            self.robots[row["origin"]] = RobotsInfo(
                origin=row["origin"],
                state=row["robots_state"],
                attempt_id=(
                    None if row["robots_attempt_id"] is None
                    else int(row["robots_attempt_id"])
                ),
                robots=robots,
                raw=raw,
            )

        for row in self.connection.execute(
            "SELECT * FROM source_imports WHERE run_id = ? ORDER BY import_id",
            (self.run_id,),
        ):
            item = dict(row)
            try:
                item["metadata"] = json.loads(item["metadata_json"])
            except (TypeError, ValueError):
                item["metadata"] = {}
            self.source_imports.append(item)

        for row in self.connection.execute(
            "SELECT * FROM gsc_datasets WHERE run_id = ? ORDER BY dataset_id",
            (self.run_id,),
        ):
            self.datasets.append(dict(row))
            self.metrics[int(row["dataset_id"])] = []

        for row in self.connection.execute(
            "SELECT dataset_id, source_page, query, url_id, mapping_status, clicks, "
            "impressions, position FROM gsc_metrics WHERE run_id = ?",
            (self.run_id,),
        ):
            dataset_id = int(row["dataset_id"])
            if dataset_id in self.metrics:
                self.metrics[dataset_id].append(dict(row))

    # ------------------------------------------------------------------ Zugriff

    def url(self, url_id: int) -> UrlInfo | None:
        return self.urls.get(url_id)

    def url_string(self, url_id: int) -> str:
        info = self.urls.get(url_id)
        return info.url if info else f"url:{url_id}"

    def page_attempts(self, url_id: int) -> list[AttemptInfo]:
        return [
            attempt
            for attempt in self.attempts_by_url.get(url_id, [])
            if attempt.purpose == "page"
        ]

    def final_attempt(self, url_id: int) -> AttemptInfo | None:
        attempts = self.page_attempts(url_id)
        if not attempts:
            return None
        return max(attempts, key=lambda attempt: attempt.attempt_no)

    def last_attempt(self, url_id: int) -> AttemptInfo | None:
        attempts = self.attempts_by_url.get(url_id, [])
        if not attempts:
            return None
        return max(attempts, key=lambda attempt: attempt.attempt_id)

    def final_status(self, url_id: int) -> int | None:
        attempt = self.final_attempt(url_id)
        return attempt.status_code if attempt else None

    def final_error(self, url_id: int) -> str | None:
        attempt = self.final_attempt(url_id)
        return attempt.error_code if attempt else None

    def observation(self, url_id: int) -> ObservationInfo | None:
        observations = self.observations.get(url_id)
        return observations[-1] if observations else None

    def observation_for_attempt(
        self, url_id: int, attempt_id: int | None
    ) -> ObservationInfo | None:
        if attempt_id is None:
            return self.observation(url_id)
        for observation in self.observations.get(url_id, []):
            if observation.attempt_id == attempt_id:
                return observation
        return self.observation(url_id)

    def html_observation(self, url_id: int) -> ObservationInfo | None:
        status = self.final_status(url_id)
        if status is None or not 200 <= status < 300:
            return None
        return self.observation(url_id)

    def attempt_by_id(self, attempt_id: int | None) -> AttemptInfo | None:
        if attempt_id is None:
            return None
        for attempt in self.attempts:
            if attempt.attempt_id == attempt_id:
                return attempt
        return None

    def robots_for(self, url: str) -> RobotsInfo | None:
        from seoboy.shared.urls import origin_of

        try:
            origin = origin_of(url)
        except ValueError:
            return None
        return self.robots.get(origin)

    def is_page(self, url_id: int) -> bool:
        return url_id in self.page_url_ids

    def content_state(self, url_id: int) -> tuple[str, str | None]:
        """Liefert (Zustand, Grund) für inhaltsabhängige Prüfungen.

        Zustände: checked, blocked, excluded, deferred, redirect, error, non_html,
        not_fetched.
        """
        info = self.urls.get(url_id)
        if info is None:
            return "not_fetched", "url_missing"
        if info.state == "blocked":
            return "blocked", info.reason_code or "robots_disallowed"
        if info.state == "excluded":
            return "excluded", info.reason_code or "excluded"
        if info.state == "deferred":
            return "deferred", info.reason_code or "url_limit_reached"
        attempt = self.final_attempt(url_id)
        if attempt is None:
            return "not_fetched", info.reason_code or "not_fetched"
        if attempt.state == "transport_error":
            return "error", "fetch_timeout" if attempt.error_code == "timeout" else "fetch_error"
        status = attempt.status_code
        if status is None:
            return "error", "fetch_interrupted"
        if 300 <= status < 400:
            return "redirect", "redirected_url"
        if not 200 <= status < 300:
            return "error", "http_error"
        observation = self.observation_for_attempt(url_id, attempt.attempt_id)
        if observation is None:
            content_type = (attempt.content_type or "").lower()
            if content_type and "html" not in content_type:
                return "non_html", "non_html_document"
            return "not_fetched", "empty_body"
        return "checked", None

    def graph_coverage(self) -> dict[str, int]:
        complete = 0
        incomplete = 0
        missing = 0
        for url_id in self.page_url_ids:
            info = self.urls.get(url_id)
            if info is None or info.state in {"excluded"}:
                continue
            observation = self.observation(url_id)
            if observation is None:
                missing += 1
            elif observation.links_complete:
                complete += 1
            else:
                incomplete += 1
        return {"complete": complete, "incomplete": incomplete, "missing": missing}

    def link_graph_complete(self) -> bool:
        coverage = self.graph_coverage()
        return coverage["incomplete"] == 0 and coverage["missing"] == 0

    def sitemap_targets(self) -> list[UrlInfo]:
        return [
            info
            for info in self.urls.values()
            if info.url_id in self.page_url_ids and info.sitemap_sources
        ]

    def inbound_sources(self, url_id: int) -> set[int]:
        return {
            source
            for source in self.inbound.get(url_id, set())
            if source != url_id
        }
