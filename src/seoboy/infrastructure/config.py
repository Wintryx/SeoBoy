"""Projektkonfiguration: Laden, Validieren, Kanonisieren."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import re
from typing import Any
from urllib.parse import urljoin

import yaml

from seoboy.shared.urls import InvalidUrl, normalize_url, path_matches
from seoboy.shared.util import local_now_date, sha256_json, stable_json

BUSINESS_VALUES = ("high", "normal", "low")
TOP_LEVEL_KEYS = {
    "project_id",
    "start_url",
    "allowed_hosts",
    "database",
    "reports_dir",
    "crawl",
    "seeds",
    "priority_pages",
    "rule_exceptions",
    "link_depth_limit",
    "gsc",
}
CRAWL_KEYS = {
    "max_urls",
    "max_requests",
    "max_runtime_seconds",
    "max_parallel_per_host",
    "max_workers",
    "min_request_interval_ms",
    "max_redirects",
    "request_timeout_seconds",
    "max_response_bytes",
    "remove_query_params",
    "exclude_paths",
}
GSC_KEYS = {
    "near_top_min_impressions",
    "near_top_position_min",
    "near_top_position_max",
    "decline_min_previous_clicks",
    "decline_min_clicks",
    "decline_min_ratio",
    "ctr_min_impressions",
    "ctr_min_drop",
    "ctr_max_position_delta",
    "multi_url_min_impressions",
    "multi_url_min_urls",
}


class ConfigError(ValueError):
    """Die Projektkonfiguration ist fachlich ungültig."""


@dataclass(frozen=True)
class CrawlSettings:
    max_urls: int = 500
    max_requests: int = 1500
    max_runtime_seconds: float = 900.0
    max_parallel_per_host: int = 2
    max_workers: int = 8
    min_request_interval_ms: int = 500
    max_redirects: int = 10
    request_timeout_seconds: float = 15.0
    max_response_bytes: int = 5_000_000
    remove_query_params: tuple[str, ...] = ("utm_*", "gclid", "fbclid")
    exclude_paths: tuple[str, ...] = ("/wp-admin/**", "/wp-login.php", "/feed/**")


@dataclass(frozen=True)
class GscThresholds:
    near_top_min_impressions: int = 100
    near_top_position_min: float = 5.0
    near_top_position_max: float = 20.0
    decline_min_previous_clicks: int = 20
    decline_min_clicks: int = 10
    decline_min_ratio: float = 0.25
    ctr_min_impressions: int = 100
    ctr_min_drop: float = 0.02
    ctr_max_position_delta: float = 1.0
    multi_url_min_impressions: int = 30
    multi_url_min_urls: int = 2


@dataclass(frozen=True)
class PageProfile:
    pattern: str
    page_type: str | None = None
    business_value: str | None = None
    expected_indexable: bool | None = None


@dataclass(frozen=True)
class ResolvedProfile:
    page_type: str | None
    business_value: str
    expected_indexable: bool | None
    source: str
    pattern: str | None = None


@dataclass(frozen=True)
class RuleException:
    rule_id: str
    url: str | None
    path: str | None
    reason: str
    expires: date | None = None

    def active(self, today: date | None = None) -> bool:
        return self.expires is None or (today or local_now_date()) <= self.expires

    def matches(self, rule_id: str, urls: list[str]) -> bool:
        if rule_id != self.rule_id or not self.active():
            return False
        for url in urls:
            try:
                parsed = normalize_url(url)
            except InvalidUrl:
                continue
            if self.url is not None and parsed.url == self.url:
                return True
            if self.path is not None and path_matches(self.path, parsed.path):
                return True
        return False


@dataclass(frozen=True)
class ProjectConfig:
    project_id: str
    start_url: str
    allowed_hosts: tuple[str, ...]
    database: Path
    reports_dir: Path
    crawl: CrawlSettings
    seeds: tuple[str, ...] = ()
    priority_pages: tuple[PageProfile, ...] = ()
    rule_exceptions: tuple[RuleException, ...] = ()
    link_depth_limit: int = 3
    gsc: GscThresholds = field(default_factory=GscThresholds)
    config_path: Path | None = None

    def profile_for(self, url: str) -> ResolvedProfile:
        parsed = normalize_url(url)
        if parsed.url == self.start_url:
            profile = ResolvedProfile(
                page_type=None,
                business_value="high",
                expected_indexable=True,
                source="start_default",
            )
        else:
            profile = ResolvedProfile(
                page_type=None,
                business_value="normal",
                expected_indexable=None,
                source="default",
            )
        for rule in self.priority_pages:
            if path_matches(rule.pattern, parsed.path):
                return ResolvedProfile(
                    page_type=rule.page_type if rule.page_type is not None else profile.page_type,
                    business_value=(
                        rule.business_value
                        if rule.business_value is not None
                        else profile.business_value
                    ),
                    expected_indexable=(
                        rule.expected_indexable
                        if rule.expected_indexable is not None
                        else profile.expected_indexable
                    ),
                    source="profile",
                    pattern=rule.pattern,
                )
        return profile

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "start_url": self.start_url,
            "allowed_hosts": sorted(self.allowed_hosts),
            "database": str(self.database),
            "reports_dir": str(self.reports_dir),
            "crawl": {
                "max_urls": self.crawl.max_urls,
                "max_requests": self.crawl.max_requests,
                "max_runtime_seconds": self.crawl.max_runtime_seconds,
                "max_parallel_per_host": self.crawl.max_parallel_per_host,
                "max_workers": self.crawl.max_workers,
                "min_request_interval_ms": self.crawl.min_request_interval_ms,
                "max_redirects": self.crawl.max_redirects,
                "request_timeout_seconds": self.crawl.request_timeout_seconds,
                "max_response_bytes": self.crawl.max_response_bytes,
                "remove_query_params": list(self.crawl.remove_query_params),
                "exclude_paths": list(self.crawl.exclude_paths),
            },
            "seeds": list(self.seeds),
            "priority_pages": [
                {
                    "path": profile.pattern,
                    "page_type": profile.page_type,
                    "business_value": profile.business_value,
                    "expected_indexable": profile.expected_indexable,
                }
                for profile in self.priority_pages
            ],
            "rule_exceptions": [
                {
                    "rule_id": rule.rule_id,
                    "url": rule.url,
                    "path": rule.path,
                    "reason": rule.reason,
                    "expires": rule.expires.isoformat() if rule.expires else None,
                }
                for rule in self.rule_exceptions
            ],
            "link_depth_limit": self.link_depth_limit,
            "gsc": {
                "near_top_min_impressions": self.gsc.near_top_min_impressions,
                "near_top_position_min": self.gsc.near_top_position_min,
                "near_top_position_max": self.gsc.near_top_position_max,
                "decline_min_previous_clicks": self.gsc.decline_min_previous_clicks,
                "decline_min_clicks": self.gsc.decline_min_clicks,
                "decline_min_ratio": self.gsc.decline_min_ratio,
                "ctr_min_impressions": self.gsc.ctr_min_impressions,
                "ctr_min_drop": self.gsc.ctr_min_drop,
                "ctr_max_position_delta": self.gsc.ctr_max_position_delta,
                "multi_url_min_impressions": self.gsc.multi_url_min_impressions,
                "multi_url_min_urls": self.gsc.multi_url_min_urls,
            },
        }

    def canonical_json(self) -> str:
        return stable_json(self.canonical_dict())

    def config_hash(self) -> str:
        return sha256_json(self.canonical_dict())


def _mapping(value: Any, label: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"'{label}' muss eine YAML-Zuordnung sein.")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ConfigError(
            f"Unbekannte Schlüssel in '{label}': {', '.join(str(item) for item in unknown)}."
        )
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"'{label}' muss ein nicht leerer Textwert sein.")
    return value.strip()


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"'{label}' muss eine ganze Zahl sein.")
    if value < minimum:
        raise ConfigError(f"'{label}' muss mindestens {minimum} sein.")
    return value


def _number(value: Any, label: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"'{label}' muss eine Zahl sein.")
    if value < minimum:
        raise ConfigError(f"'{label}' muss mindestens {minimum} sein.")
    return float(value)


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"'{label}' muss true oder false sein.")
    return value


def _text_list(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ConfigError(f"'{label}' muss eine Liste nicht leerer Textwerte sein.")
    return tuple(item.strip() for item in value)


def _host_from_url(url: str) -> tuple[str, str]:
    try:
        parsed = normalize_url(url)
    except InvalidUrl as error:
        raise ConfigError(f"'start_url' ist ungültig: {error}") from None
    return parsed.url, parsed.host


def _parse_crawl(value: Any) -> CrawlSettings:
    if value is None:
        return CrawlSettings()
    data = _mapping(value, "crawl", CRAWL_KEYS)
    defaults = CrawlSettings()
    remove = data.get("remove_query_params", list(defaults.remove_query_params))
    exclude = data.get("exclude_paths", list(defaults.exclude_paths))
    crawl = CrawlSettings(
        max_urls=_integer(data.get("max_urls", defaults.max_urls), "crawl.max_urls", 1),
        max_requests=_integer(
            data.get("max_requests", defaults.max_requests), "crawl.max_requests", 1
        ),
        max_runtime_seconds=_number(
            data.get("max_runtime_seconds", defaults.max_runtime_seconds),
            "crawl.max_runtime_seconds",
            0.001,
        ),
        max_parallel_per_host=_integer(
            data.get("max_parallel_per_host", defaults.max_parallel_per_host),
            "crawl.max_parallel_per_host",
            1,
        ),
        max_workers=_integer(
            data.get("max_workers", defaults.max_workers),
            "crawl.max_workers",
            1,
        ),
        min_request_interval_ms=_integer(
            data.get("min_request_interval_ms", defaults.min_request_interval_ms),
            "crawl.min_request_interval_ms",
            0,
        ),
        max_redirects=_integer(
            data.get("max_redirects", defaults.max_redirects), "crawl.max_redirects", 0
        ),
        request_timeout_seconds=_number(
            data.get("request_timeout_seconds", defaults.request_timeout_seconds),
            "crawl.request_timeout_seconds",
            0.001,
        ),
        max_response_bytes=_integer(
            data.get("max_response_bytes", defaults.max_response_bytes),
            "crawl.max_response_bytes",
            1,
        ),
        remove_query_params=_text_list(remove, "crawl.remove_query_params"),
        exclude_paths=_text_list(exclude, "crawl.exclude_paths"),
    )
    for pattern in crawl.exclude_paths:
        if not pattern.startswith("/"):
            raise ConfigError(f"Pfadmuster muss mit '/' beginnen: {pattern}")
    return crawl


def _parse_seeds(value: Any, start_url: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError("'seeds' muss eine Liste von URLs sein.")
    seeds: list[str] = []
    for raw in value:
        text = _text(raw, "seeds[]")
        absolute = urljoin(start_url, text)
        try:
            normalized = normalize_url(absolute).url
        except InvalidUrl as error:
            raise ConfigError(f"Seed '{text}' ist ungültig: {error}") from None
        seeds.append(normalized)
    return tuple(dict.fromkeys(seeds))


def _parse_profiles(value: Any) -> tuple[PageProfile, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError("'priority_pages' muss eine Liste sein.")
    profiles: list[PageProfile] = []
    for index, item in enumerate(value, start=1):
        data = _mapping(
            item,
            f"priority_pages[{index}]",
            {"path", "page_type", "business_value", "expected_indexable"},
        )
        pattern = _text(data.get("path"), f"priority_pages[{index}].path")
        if not pattern.startswith("/"):
            raise ConfigError(f"priority_pages[{index}].path muss mit '/' beginnen.")
        page_type = data.get("page_type")
        if page_type is not None:
            page_type = _text(page_type, f"priority_pages[{index}].page_type")
        business_value = data.get("business_value")
        if business_value is not None:
            business_value = _text(
                business_value, f"priority_pages[{index}].business_value"
            )
            if business_value not in BUSINESS_VALUES:
                raise ConfigError(
                    f"priority_pages[{index}].business_value muss einer von "
                    f"{', '.join(BUSINESS_VALUES)} sein."
                )
        expected = data.get("expected_indexable")
        if expected is not None:
            expected = _boolean(expected, f"priority_pages[{index}].expected_indexable")
        profiles.append(
            PageProfile(
                pattern=pattern,
                page_type=page_type,
                business_value=business_value,
                expected_indexable=expected,
            )
        )
    return tuple(profiles)


def _parse_exceptions(value: Any) -> tuple[RuleException, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError("'rule_exceptions' muss eine Liste sein.")
    exceptions: list[RuleException] = []
    for index, item in enumerate(value, start=1):
        label = f"rule_exceptions[{index}]"
        data = _mapping(item, label, {"rule_id", "url", "path", "reason", "expires"})
        rule_id = _text(data.get("rule_id"), f"{label}.rule_id")
        reason = _text(data.get("reason"), f"{label}.reason")
        url = data.get("url")
        path = data.get("path")
        if (url is None) == (path is None):
            raise ConfigError(f"{label} braucht genau eines von 'url' oder 'path'.")
        normalized_url = None
        if url is not None:
            try:
                normalized_url = normalize_url(_text(url, f"{label}.url")).url
            except InvalidUrl as error:
                raise ConfigError(f"{label}.url ist ungültig: {error}") from None
        pattern = None
        if path is not None:
            pattern = _text(path, f"{label}.path")
            if not pattern.startswith("/"):
                raise ConfigError(f"{label}.path muss mit '/' beginnen.")
        expires_raw = data.get("expires")
        expires = None
        if isinstance(expires_raw, date):
            expires = expires_raw
        elif expires_raw is not None:
            text = _text(expires_raw, f"{label}.expires")
            try:
                expires = date.fromisoformat(text)
            except ValueError:
                raise ConfigError(
                    f"{label}.expires muss ein Kalendertag im Format JJJJ-MM-TT sein."
                ) from None
        exceptions.append(
            RuleException(
                rule_id=rule_id,
                url=normalized_url,
                path=pattern,
                reason=reason,
                expires=expires,
            )
        )
    return tuple(exceptions)


def _parse_gsc(value: Any) -> GscThresholds:
    if value is None:
        return GscThresholds()
    data = _mapping(value, "gsc", GSC_KEYS)
    defaults = GscThresholds()
    thresholds = GscThresholds(
        near_top_min_impressions=_integer(
            data.get("near_top_min_impressions", defaults.near_top_min_impressions),
            "gsc.near_top_min_impressions",
            0,
        ),
        near_top_position_min=_number(
            data.get("near_top_position_min", defaults.near_top_position_min),
            "gsc.near_top_position_min",
            0.0,
        ),
        near_top_position_max=_number(
            data.get("near_top_position_max", defaults.near_top_position_max),
            "gsc.near_top_position_max",
            0.0,
        ),
        decline_min_previous_clicks=_integer(
            data.get("decline_min_previous_clicks", defaults.decline_min_previous_clicks),
            "gsc.decline_min_previous_clicks",
            0,
        ),
        decline_min_clicks=_integer(
            data.get("decline_min_clicks", defaults.decline_min_clicks),
            "gsc.decline_min_clicks",
            0,
        ),
        decline_min_ratio=_number(
            data.get("decline_min_ratio", defaults.decline_min_ratio),
            "gsc.decline_min_ratio",
            0.0,
        ),
        ctr_min_impressions=_integer(
            data.get("ctr_min_impressions", defaults.ctr_min_impressions),
            "gsc.ctr_min_impressions",
            0,
        ),
        ctr_min_drop=_number(
            data.get("ctr_min_drop", defaults.ctr_min_drop), "gsc.ctr_min_drop", 0.0
        ),
        ctr_max_position_delta=_number(
            data.get("ctr_max_position_delta", defaults.ctr_max_position_delta),
            "gsc.ctr_max_position_delta",
            0.0,
        ),
        multi_url_min_impressions=_integer(
            data.get("multi_url_min_impressions", defaults.multi_url_min_impressions),
            "gsc.multi_url_min_impressions",
            0,
        ),
        multi_url_min_urls=_integer(
            data.get("multi_url_min_urls", defaults.multi_url_min_urls),
            "gsc.multi_url_min_urls",
            1,
        ),
    )
    if thresholds.near_top_position_min > thresholds.near_top_position_max:
        raise ConfigError(
            "gsc.near_top_position_min darf nicht größer als near_top_position_max sein."
        )
    if thresholds.decline_min_ratio > 1:
        raise ConfigError("gsc.decline_min_ratio muss zwischen 0 und 1 liegen.")
    if thresholds.ctr_min_drop > 1:
        raise ConfigError("gsc.ctr_min_drop muss zwischen 0 und 1 liegen.")
    return thresholds


def load_config(path: Path | str) -> ProjectConfig:
    config_path = Path(path)
    try:
        raw = config_path.read_text(encoding="utf-8-sig")
    except UnicodeError:
        raise ConfigError(f"Die Projektkonfiguration ist nicht UTF-8: {config_path}") from None
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as error:
        raise ConfigError(f"Ungültige YAML-Konfiguration in {config_path}: {error}") from None
    if not isinstance(data, dict):
        raise ConfigError("Die Projektkonfiguration muss eine YAML-Zuordnung sein.")
    unknown = sorted(set(data) - TOP_LEVEL_KEYS)
    if unknown:
        raise ConfigError(
            f"Unbekannte Schlüssel in der Projektkonfiguration: {', '.join(str(item) for item in unknown)}."
        )

    project_id = _text(data.get("project_id"), "project_id")
    start_url, host = _host_from_url(_text(data.get("start_url"), "start_url"))
    hosts = _text_list(data.get("allowed_hosts"), "allowed_hosts")
    hosts = tuple(dict.fromkeys(item.casefold() for item in hosts))
    if host not in hosts:
        raise ConfigError(f"Host '{host}' fehlt in 'allowed_hosts'.")
    database_raw = _text(data.get("database"), "database")
    reports_raw = _text(data.get("reports_dir"), "reports_dir")
    link_depth_limit = _integer(
        data.get("link_depth_limit", 3), "link_depth_limit", 0
    )

    return ProjectConfig(
        project_id=project_id,
        start_url=start_url,
        allowed_hosts=hosts,
        database=(config_path.parent / database_raw).resolve(),
        reports_dir=(config_path.parent / reports_raw).resolve(),
        crawl=_parse_crawl(data.get("crawl")),
        seeds=_parse_seeds(data.get("seeds"), start_url),
        priority_pages=_parse_profiles(data.get("priority_pages")),
        rule_exceptions=_parse_exceptions(data.get("rule_exceptions")),
        link_depth_limit=link_depth_limit,
        gsc=_parse_gsc(data.get("gsc")),
        config_path=config_path.resolve(),
    )


def _project_id_for(host: str) -> str:
    project_id = re.sub(r"[^a-z0-9]+", "-", host.encode("idna").decode()).strip("-")
    if not project_id:
        raise ConfigError("Aus dem Hostnamen lässt sich keine Projekt-ID ableiten.")
    return project_id


def init_config(path: Path | str, url: str) -> None:
    start_url, host = _host_from_url(url)
    config = {
        "project_id": _project_id_for(host),
        "start_url": start_url,
        "allowed_hosts": [host],
        "database": "./data/seoboy.db",
        "reports_dir": "./reports",
        "crawl": {
            "max_urls": 500,
            "max_requests": 1500,
            "max_runtime_seconds": 900,
            "max_parallel_per_host": 2,
            "max_workers": 8,
            "min_request_interval_ms": 500,
            "max_redirects": 10,
            "request_timeout_seconds": 15,
            "max_response_bytes": 5000000,
            "remove_query_params": ["utm_*", "gclid", "fbclid"],
            "exclude_paths": ["/wp-admin/**", "/wp-login.php", "/feed/**"],
        },
        "seeds": [],
        "priority_pages": [
            {
                "path": "/leistungen/**",
                "page_type": "service",
                "business_value": "high",
                "expected_indexable": True,
            },
            {
                "path": "/danke/",
                "page_type": "utility",
                "business_value": "low",
                "expected_indexable": False,
            },
        ],
        "rule_exceptions": [],
        "link_depth_limit": 3,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(config, stream, sort_keys=False, allow_unicode=True)
    except FileExistsError:
        raise ConfigError(f"Die Projektkonfiguration existiert bereits: {target}") from None
