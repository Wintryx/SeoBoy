"""HTML-Extraktion: Titel, Beschreibung, Robots-Signale, Canonicals, Links."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from urllib.parse import urljoin

from seoboy.shared.util import normalize_whitespace

DIRECTIVE_SPLIT = re.compile(r"[,\s]+")
_LINK_CANONICAL = re.compile(
    r"<\s*([^>]+?)\s*>\s*;\s*[^,]*?\brel\s*=\s*[\"']?canonical[\"']?",
    re.IGNORECASE,
)


def link_header_canonicals(header_items) -> tuple[str, ...]:
    """Liest Canonical-Ziele aus HTTP-Link-Headern (rel="canonical")."""
    values: list[str] = []
    for name, value in header_items:
        if str(name).casefold() != "link":
            continue
        for match in _LINK_CANONICAL.finditer(str(value)):
            url = match.group(1).strip()
            if url and url not in values:
                values.append(url)
    return tuple(values)


@dataclass(frozen=True)
class RobotsSignals:
    tokens: tuple[str, ...]
    meta_raw: str | None
    header_raw: str | None
    googlebot_specific: bool

    @property
    def noindex(self) -> bool:
        return "noindex" in self.tokens or "none" in self.tokens

    @property
    def nofollow(self) -> bool:
        return "nofollow" in self.tokens or "none" in self.tokens


@dataclass
class ExtractedPage:
    title: str | None
    meta_description: str | None
    canonical: tuple[str, ...]
    links: tuple[str, ...]
    robots: RobotsSignals
    meta: dict[str, str] = field(default_factory=dict)
    base_href: str | None = None


def _directives(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    parts = [part.strip().casefold() for part in DIRECTIVE_SPLIT.split(value) if part.strip()]
    return tuple(dict.fromkeys(parts))


def _header_directives(
    header_items: tuple[tuple[str, str], ...] | list[tuple[str, str]], agent: str
) -> tuple[tuple[str, ...], str | None, bool]:
    generic: list[str] = []
    specific: list[str] = []
    raw_values: list[str] = []
    found_specific = False
    for name, value in header_items:
        if name.casefold() != "x-robots-tag":
            continue
        raw_values.append(value)
        for token in value.split(","):
            token = token.strip()
            if not token:
                continue
            if ":" in token:
                prefix, _, rest = token.partition(":")
                if prefix.strip().casefold() == agent:
                    specific.extend(_directives(rest))
                    found_specific = True
            else:
                generic.extend(_directives(token))
    tokens = tuple(dict.fromkeys(specific if found_specific else generic))
    return tokens, ("; ".join(raw_values) if raw_values else None), found_specific


def robots_signals(
    meta: dict[str, str], header_items: tuple[tuple[str, str], ...] | list[tuple[str, str]],
    agent: str = "googlebot",
) -> RobotsSignals:
    meta_raw = None
    meta_tokens: tuple[str, ...] = ()
    if meta.get(agent) is not None:
        meta_raw = meta[agent]
        meta_tokens = _directives(meta_raw)
        googlebot_meta = True
    elif meta.get("robots") is not None:
        meta_raw = meta["robots"]
        meta_tokens = _directives(meta_raw)
        googlebot_meta = False
    else:
        googlebot_meta = False
    header_tokens, header_raw, googlebot_header = _header_directives(header_items, agent)
    tokens = tuple(dict.fromkeys((*meta_tokens, *header_tokens)))
    return RobotsSignals(
        tokens=tokens,
        meta_raw=meta_raw,
        header_raw=header_raw,
        googlebot_specific=googlebot_meta or googlebot_header,
    )


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self._in_title = False
        self._title_done = False
        self.meta: dict[str, str] = {}
        self.canonicals: list[str] = []
        self.raw_links: list[str] = []
        self.base_href: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        values = {str(key).casefold(): (value or "") for key, value in attrs}
        if tag == "title" and not self._title_done:
            self._in_title = True
        elif tag == "meta":
            name = (values.get("name") or values.get("property") or "").strip().casefold()
            content = values.get("content")
            if name and content and name not in self.meta:
                self.meta[name] = content
        elif tag == "link":
            relations = values.get("rel", "").casefold().split()
            href = values.get("href", "").strip()
            if "canonical" in relations and href:
                self.canonicals.append(href)
        elif tag == "base" and self.base_href is None:
            href = values.get("href", "").strip()
            if href:
                self.base_href = href
        elif tag in {"a", "area"}:
            href = values.get("href", "").strip()
            if href:
                self.raw_links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in_title:
            self._in_title = False
            self._title_done = True

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)


def _resolve(base: str, reference: str) -> str | None:
    try:
        resolved = urljoin(base, reference)
    except ValueError:
        return None
    if not resolved:
        return None
    return resolved


def extract_page(
    html: str,
    document_url: str,
    header_items: tuple[tuple[str, str], ...] | list[tuple[str, str]] = (),
) -> ExtractedPage:
    parser = _Extractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # HTMLParser ist robust, aber Fremdmarkup soll den Lauf nicht stoppen
        pass

    base = document_url
    if parser.base_href:
        resolved_base = _resolve(document_url, parser.base_href)
        if resolved_base:
            base = resolved_base

    title = normalize_whitespace(" ".join(parser.title_parts)) or None
    description = normalize_whitespace(parser.meta.get("description")) or None

    canonical: list[str] = []
    for reference in parser.canonicals:
        resolved = _resolve(base, reference)
        if resolved and resolved not in canonical:
            canonical.append(resolved)

    links: list[str] = []
    for reference in parser.raw_links:
        resolved = _resolve(base, reference)
        if resolved and resolved not in links:
            links.append(resolved)

    return ExtractedPage(
        title=title,
        meta_description=description,
        canonical=tuple(canonical),
        links=tuple(links),
        robots=robots_signals(parser.meta, header_items),
        meta=parser.meta,
        base_href=parser.base_href,
    )
