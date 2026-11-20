"""Read-only competitor sampling for the benchmark report."""

from __future__ import annotations

from dataclasses import dataclass, field
import gzip
import time
from urllib.parse import urlsplit
from xml.etree import ElementTree

from seoboy.analysis.audit_data import RunData
from seoboy.crawl.html_extract import extract_page
from seoboy.crawl.http_client import FetchResult, HttpClient, decode_body
from seoboy.shared.agents import SEOBOY
from seoboy.shared.robots import RobotsFile
from seoboy.shared.urls import (
    InvalidUrl,
    is_internal,
    normalize_url,
    resolve_url,
)

_MEDIA_SUFFIXES = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".zip",
    ".mp4", ".mp3", ".css", ".js", ".ico", ".xml",
)


class BenchmarkError(RuntimeError):
    """The benchmark cannot be created from the current data."""


@dataclass(frozen=True)
class PageMetric:
    url: str
    status: int | None
    has_content: bool
    indexable: bool
    title_length: int
    description_length: int
    h1_count: int
    word_count: int
    image_count: int
    images_missing_alt: int
    schema_types: tuple[str, ...]
    internal_links: int


@dataclass
class SiteSnapshot:
    label: str
    start_url: str
    final_url: str
    pages: list[PageMetric] = field(default_factory=list)
    sitemap_urls: int = 0
    error: str | None = None


def _origin_path(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path or '/'}" + (f"?{parts.query}" if parts.query else "")


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _sitemap_document(body: bytes) -> tuple[str, list[str]]:
    if body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except OSError:
            return "invalid", []
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return "invalid", []
    kind = _local_tag(root.tag)
    if kind not in {"sitemapindex", "urlset"}:
        return "invalid", []
    child_name = "sitemap" if kind == "sitemapindex" else "url"
    locations: list[str] = []
    for child in root:
        if _local_tag(child.tag) != child_name:
            continue
        for element in child:
            if _local_tag(element.tag) == "loc":
                value = (element.text or "").strip()
                if value:
                    locations.append(value)
                break
    return kind, locations


def _fetch_follow(
    client: HttpClient, url: str, max_redirects: int = 3
) -> tuple[FetchResult, str]:
    current = url
    result = client.fetch(current)
    for _ in range(max_redirects):
        if result.status_code not in {301, 302, 303, 307, 308}:
            break
        if not result.redirect_location:
            break
        target = resolve_url(current, result.redirect_location)
        if target is None:
            break
        current = target
        result = client.fetch(current)
    return result, current


def _load_robots(client: HttpClient, origin: str) -> RobotsFile:
    result, _ = _fetch_follow(client, f"{origin}/robots.txt", max_redirects=1)
    if result.status_code and 200 <= result.status_code < 300:
        return RobotsFile.parse(decode_body(result))
    return RobotsFile.parse("")


def _same_site(url: str, allowed_hosts: tuple[str, ...]) -> bool:
    try:
        normalized = normalize_url(url)
    except InvalidUrl:
        return False
    return is_internal(normalized, allowed_hosts)


def _page_candidate(url: str, allowed_hosts: tuple[str, ...]) -> bool:
    if not _same_site(url, allowed_hosts):
        return False
    normalized = normalize_url(url)
    return not normalized.path.lower().endswith(_MEDIA_SUFFIXES)


def _absolute_url(value: str, base: str) -> str:
    if value.startswith(("http://", "https://")):
        return value
    return resolve_url(base, value) or value


def _sitemap_candidates(
    client: HttpClient,
    origins: list[str],
    robots: RobotsFile,
    allowed_hosts: tuple[str, ...],
    max_pages: int,
) -> tuple[list[str], int]:
    sitemap_urls = [value for value in robots.sitemaps if value]
    if not sitemap_urls:
        for origin in origins:
            sitemap_urls.extend([f"{origin}/sitemap.xml", f"{origin}/sitemap_index.xml"])
    found: list[str] = []
    total = 0
    base = f"{origins[-1]}/"
    for raw_sitemap_url in sitemap_urls:
        sitemap_url = _absolute_url(raw_sitemap_url, base)
        if not _same_site(sitemap_url, allowed_hosts):
            continue
        try:
            normalized = normalize_url(sitemap_url)
        except InvalidUrl:
            continue
        if not robots.is_allowed(_origin_path(normalized.url), SEOBOY):
            continue
        result, _ = _fetch_follow(client, normalized.url, max_redirects=1)
        if result.status_code is None or not 200 <= result.status_code < 300:
            continue
        kind, locations = _sitemap_document(result.body)
        if kind == "sitemapindex":
            for child in locations[:1]:
                try:
                    child_norm = normalize_url(_absolute_url(child, base))
                except InvalidUrl:
                    continue
                if not robots.is_allowed(_origin_path(child_norm.url), SEOBOY):
                    continue
                child_result, _ = _fetch_follow(client, child_norm.url, max_redirects=1)
                if child_result.status_code and 200 <= child_result.status_code < 300:
                    _, locations = _sitemap_document(child_result.body)
                else:
                    locations = []
        total += len(locations)
        for value in locations:
            if _page_candidate(value, allowed_hosts) and value not in found:
                found.append(value)
            if len(found) >= max_pages * 4:
                break
        if found:
            break
    return found, total


def _metric(url: str, result: FetchResult) -> PageMetric:
    has_content = bool(
        result.error_code is None
        and result.status_code is not None
        and 200 <= result.status_code < 300
        and result.is_html
    )
    if not has_content:
        return PageMetric(
            url=url,
            status=result.status_code,
            has_content=False,
            indexable=False,
            title_length=0,
            description_length=0,
            h1_count=0,
            word_count=0,
            image_count=0,
            images_missing_alt=0,
            schema_types=(),
            internal_links=0,
        )
    page = extract_page(decode_body(result), result.url, result.header_items)
    return PageMetric(
        url=url,
        status=result.status_code,
        has_content=True,
        indexable=not page.robots.noindex,
        title_length=len(page.title or ""),
        description_length=len(page.meta_description or ""),
        h1_count=page.h1_count,
        word_count=page.word_count,
        image_count=page.image_count,
        images_missing_alt=page.images_missing_alt,
        schema_types=page.schema_types,
        internal_links=len(page.links),
    )


def collect_snapshot(
    start_url: str,
    label: str,
    *,
    max_pages: int = 20,
    interval_seconds: float = 0.5,
    timeout: float = 10.0,
) -> SiteSnapshot:
    try:
        normalized = normalize_url(start_url)
    except InvalidUrl as error:
        raise BenchmarkError(f"Ungültige Wettbewerbs-URL {start_url}: {error}") from error
    client = HttpClient(timeout=timeout)
    robots = _load_robots(client, normalized.origin)
    if not robots.is_allowed(_origin_path(normalized.url), SEOBOY):
        return SiteSnapshot(
            label=label,
            start_url=normalized.url,
            final_url=normalized.url,
            error="robots_disallowed",
        )
    home_result, final_url = _fetch_follow(client, normalized.url)
    if (
        home_result.error_code is not None
        or home_result.status_code is None
        or not 200 <= home_result.status_code < 300
    ):
        return SiteSnapshot(
            label=label,
            start_url=normalized.url,
            final_url=final_url,
            error=home_result.error_code
            or (f"http_{home_result.status_code}" if home_result.status_code else "homepage_fetch_failed"),
        )
    try:
        final_normalized = normalize_url(final_url)
    except InvalidUrl:
        final_normalized = normalized
    if final_normalized.origin != normalized.origin:
        robots = _load_robots(client, final_normalized.origin)
        if not robots.is_allowed(_origin_path(final_normalized.url), SEOBOY):
            return SiteSnapshot(
                label=label,
                start_url=normalized.url,
                final_url=final_url,
                error="robots_disallowed",
            )
    allowed_hosts = tuple(dict.fromkeys([normalized.host, final_normalized.host]))
    origins = list(dict.fromkeys([normalized.origin, final_normalized.origin]))

    sitemap_values, sitemap_count = _sitemap_candidates(
        client, origins, robots, allowed_hosts, max_pages
    )
    candidates = [final_normalized.url]
    for value in sitemap_values:
        if value not in candidates:
            candidates.append(value)
    if len(candidates) == 1 and home_result.is_html:
        home_page = extract_page(
            decode_body(home_result), home_result.url, home_result.header_items
        )
        for value in home_page.links:
            if _page_candidate(value, allowed_hosts) and value not in candidates:
                candidates.append(value)
            if len(candidates) >= max_pages:
                break

    pages: list[PageMetric] = []
    for index, candidate in enumerate(candidates[:max_pages]):
        try:
            candidate_normalized = normalize_url(candidate)
        except InvalidUrl:
            continue
        if not robots.is_allowed(_origin_path(candidate_normalized.url), SEOBOY):
            continue
        if index == 0 and candidate_normalized.url == final_normalized.url:
            result = home_result
        else:
            if interval_seconds > 0:
                time.sleep(interval_seconds)
            result, _ = _fetch_follow(client, candidate_normalized.url)
        pages.append(_metric(candidate_normalized.url, result))
    return SiteSnapshot(
        label=label,
        start_url=normalized.url,
        final_url=final_url,
        pages=pages,
        sitemap_urls=sitemap_count,
    )


def snapshot_from_run(data: RunData, label: str = "Eigene Seite") -> SiteSnapshot:
    pages: list[PageMetric] = []
    has_metrics = False
    sitemap_urls = sum(1 for info in data.urls.values() if "sitemap" in info.kinds)
    for url_id in sorted(data.page_url_ids, key=lambda value: data.url_string(value)):
        info = data.urls.get(url_id)
        if info is None:
            continue
        observation = data.observation(url_id)
        attempt = data.final_attempt(url_id)
        if observation is None:
            continue
        signals = observation.signals
        if "h1_count" not in signals:
            continue
        has_metrics = True
        status = attempt.status_code if attempt is not None else None
        schema_types = signals.get("schema_types")
        pages.append(
            PageMetric(
                url=info.url,
                status=status,
                has_content=bool(status is not None and 200 <= status < 300),
                indexable=bool(
                    status is not None
                    and 200 <= status < 300
                    and not bool(signals.get("noindex"))
                ),
                title_length=int(signals.get("title_length", len(observation.title or "")) or 0),
                description_length=int(
                    signals.get("description_length", len(observation.meta_description or "")) or 0
                ),
                h1_count=int(signals.get("h1_count", 0) or 0),
                word_count=int(signals.get("word_count", 0) or 0),
                image_count=int(signals.get("image_count", 0) or 0),
                images_missing_alt=int(signals.get("images_missing_alt", 0) or 0),
                schema_types=(
                    tuple(str(value) for value in schema_types if value)
                    if isinstance(schema_types, list)
                    else ()
                ),
                internal_links=int(signals.get("link_count", 0) or 0),
            )
        )
    if not has_metrics:
        raise BenchmarkError(
            "Der letzte Lauf enthält keine Inhaltsmetriken. Bitte zuerst einen neuen "
            "Lauf mit SeoBoy 0.4.0 oder neuer ausführen."
        )
    return SiteSnapshot(
        label=label,
        start_url=data.config.start_url,
        final_url=data.config.start_url,
        pages=pages,
        sitemap_urls=sitemap_urls,
    )
