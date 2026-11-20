"""URL- und Warteschlangenregistrierung für einen Lauf."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import sqlite3

from seoboy.infrastructure import database
from seoboy.infrastructure.config import ProjectConfig
from seoboy.shared.urls import InvalidUrl, NormalizedUrl, normalize_url


class UrlRegistry:
    def __init__(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        project_id: str,
        config: ProjectConfig,
    ) -> None:
        self.connection = connection
        self.run_id = run_id
        self.project_id = project_id
        self.config = config
        self._discovery_seq = database.next_id(
            connection, "url_discoveries", "discovery_id", run_id
        )
        self._job_seq = database.next_id(connection, "crawl_jobs", "job_id", run_id)

    def ensure_url(
        self,
        normalized: str | NormalizedUrl,
        *,
        state: str = "discovered",
        reason_code: str | None = None,
        with_profile: bool = True,
    ) -> tuple[int, bool]:
        if isinstance(normalized, NormalizedUrl):
            normalized_url = normalized.url
        else:
            normalized_url = normalize_url(normalized).url
        row = self.connection.execute(
            "SELECT url_id FROM urls WHERE project_id = ? AND normalized_url = ?",
            (self.project_id, normalized_url),
        ).fetchone()
        if row is None:
            cursor = self.connection.execute(
                "INSERT INTO urls(project_id, normalized_url) VALUES (?, ?)",
                (self.project_id, normalized_url),
            )
            url_id = int(cursor.lastrowid)
        else:
            url_id = int(row["url_id"])

        row = self.connection.execute(
            "SELECT state FROM run_urls WHERE run_id = ? AND url_id = ?",
            (self.run_id, url_id),
        ).fetchone()
        if row is not None:
            return url_id, False

        page_type = None
        business_value = "normal"
        expected_indexable = None
        if with_profile:
            profile = self.config.profile_for(normalized_url)
            page_type = profile.page_type
            business_value = profile.business_value
            expected_indexable = profile.expected_indexable
        self.connection.execute(
            "INSERT INTO run_urls(run_id, project_id, url_id, state, reason_code, "
            "page_type, business_value, expected_indexable) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.run_id,
                self.project_id,
                url_id,
                state,
                reason_code,
                page_type,
                business_value,
                1 if expected_indexable else 0 if expected_indexable is False else None,
            ),
        )
        return url_id, True

    def add_discovery(
        self,
        url_id: int,
        original_url: str,
        kind: str,
        *,
        from_url_id: int | None = None,
        import_id: int | None = None,
    ) -> None:
        self.connection.execute(
            "INSERT INTO url_discoveries(run_id, url_id, discovery_id, kind, "

            "original_url, from_url_id, import_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                self.run_id,
                url_id,
                self._discovery_seq,
                kind,
                original_url,
                from_url_id,
                import_id,
            ),
        )
        self._discovery_seq += 1

    def add_job(
        self,
        url_id: int,
        purpose: Literal["page", "robots", "sitemap"],
        priority: int,
        *,
        not_before_at: str,
        reason_code: str | None = None,
    ) -> bool:
        row = self.connection.execute(
            "SELECT job_id, state FROM crawl_jobs WHERE run_id = ? AND purpose = ? AND url_id = ?",
            (self.run_id, purpose, url_id),
        ).fetchone()
        if row is not None:
            if row["state"] == "pending":
                self.connection.execute(
                    "UPDATE crawl_jobs SET priority = MIN(priority, ?) "
                    "WHERE run_id = ? AND job_id = ?",
                    (priority, self.run_id, row["job_id"]),
                )
            return False
        self.connection.execute(
            "INSERT INTO crawl_jobs(run_id, job_id, url_id, purpose, state, priority, "
            "not_before_at, reason_code) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
            (
                self.run_id,
                self._job_seq,
                url_id,
                purpose,
                priority,
                not_before_at,
                reason_code,
            ),
        )
        self._job_seq += 1
        if purpose in {"robots", "sitemap"}:
            self.connection.execute(
                "UPDATE run_urls SET state = 'queued' "
                "WHERE run_id = ? AND url_id = ? AND state = 'discovered'",
                (self.run_id, url_id),
            )
        return True

    def set_excluded(self, url_id: int, reason_code: str) -> None:
        self.connection.execute(
            "UPDATE run_urls SET state = 'excluded', reason_code = ? "
            "WHERE run_id = ? AND url_id = ? AND admitted_at IS NULL "
            "AND state IN ('discovered', 'queued')",
            (reason_code, self.run_id, url_id),
        )

    def update_depth(self, url_id: int, depth: int) -> bool:
        row = self.connection.execute(
            "SELECT click_depth FROM run_urls WHERE run_id = ? AND url_id = ?",
            (self.run_id, url_id),
        ).fetchone()
        if row is None:
            return False
        current = row["click_depth"]
        if current is not None and int(current) <= depth:
            return False
        self.connection.execute(
            "UPDATE run_urls SET click_depth = ? WHERE run_id = ? AND url_id = ?",
            (depth, self.run_id, url_id),
        )
        return True

    def update_pending_priority(self, url_id: int, priority: int) -> None:
        self.connection.execute(
            "UPDATE crawl_jobs SET priority = MIN(priority, ?) "
            "WHERE run_id = ? AND url_id = ? AND purpose = 'page' AND state = 'pending'",
            (priority, self.run_id, url_id),
        )


def classify_url(
    config: ProjectConfig, normalized: NormalizedUrl
) -> str | None:
    """None = zulässig; sonst Ausschlussgrund."""
    from seoboy.shared.urls import is_internal, matches_any_path

    if not is_internal(normalized, config.allowed_hosts):
        return "host_not_allowed"
    if matches_any_path(normalized.path, config.crawl.exclude_paths):
        return "path_excluded"
    return None
