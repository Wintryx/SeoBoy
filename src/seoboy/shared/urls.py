"""URL normalization and pattern matching according to the crawl contract."""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import re
from urllib.parse import quote, unquote, urljoin, urlsplit

from seoboy.shared.util import stable_json

DEFAULT_PORTS = {"http": 80, "https": 443}


class InvalidUrl(ValueError):
    """The string is not a crawlable or checkable HTTP(S) URL."""


@dataclass(frozen=True)
class NormalizedUrl:
    url: str
    scheme: str
    host: str
    port: int | None
    path: str
    query: str

    @property
    def origin(self) -> str:
        netloc = f"[{self.host}]" if ":" in self.host else self.host
        if self.port is not None:
            netloc = f"{netloc}:{self.port}"
        return f"{self.scheme}://{netloc}"


def _ascii_host(host: str) -> str:
    if ":" in host:  # IPv6 literal
        return host
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise InvalidUrl("Der Hostname ist nicht gültig.") from error


def _percent_encode_non_ascii(value: str) -> str:
    if value.isascii():
        return value
    return "".join(character if character.isascii() else quote(character) for character in value)


def _filter_query(query: str, patterns: tuple[str, ...]) -> str:
    if not query or not patterns:
        return query
    folded = tuple(pattern.casefold() for pattern in patterns)
    kept: list[str] = []
    for segment in query.split("&"):
        if not segment:
            continue
        name = unquote(segment.split("=", 1)[0]).casefold()
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in folded):
            continue
        kept.append(segment)
    return "&".join(kept)


def normalize_url(value: str, remove_query_params: tuple[str, ...] = ()) -> NormalizedUrl:
    """Normalize an HTTP(S) URL for identity within the project.

    Scheme and host are lowercased. Default ports, fragments, and configured
    tracking parameters are removed. Path spelling, trailing slash, and other
    query parameters are preserved.
    """
    if not isinstance(value, str):
        raise InvalidUrl("Die URL muss Text sein.")
    value = value.strip()
    if not value:
        raise InvalidUrl("Die URL ist leer.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise InvalidUrl("Die URL enthält Steuerzeichen.")
    value = value.replace(" ", "%20")

    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except ValueError as error:
        raise InvalidUrl("Die URL ist nicht gültig.") from error

    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS:
        raise InvalidUrl("Nur HTTP- und HTTPS-URLs sind zulässig.")
    if not host:
        raise InvalidUrl("Die URL enthält keinen Hostnamen.")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise InvalidUrl("URLs mit Zugangsdaten werden nicht verarbeitet.")
    if port == 0:
        raise InvalidUrl("Port 0 ist nicht zulässig.")

    host = _ascii_host(host.rstrip(".").lower())
    if not host:
        raise InvalidUrl("Die URL enthält keinen Hostnamen.")
    if port == DEFAULT_PORTS[scheme]:
        port = None

    path = parts.path or "/"
    path = _percent_encode_non_ascii(path)
    query = _percent_encode_non_ascii(parts.query)
    query = _filter_query(query, remove_query_params)

    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    normalized = f"{scheme}://{netloc}{path}"
    if query:
        normalized += f"?{query}"
    return NormalizedUrl(
        url=normalized, scheme=scheme, host=host, port=port, path=path, query=query
    )


def resolve_url(base: str, href: str) -> str | None:
    """Resolve an HTML reference against the document base.

    Empty references and pure fragments do not create a new URL. Non-HTTP
    schemes are discarded.
    """
    if href is None:
        return None
    href = href.strip()
    if not href or href.startswith("#"):
        return None
    lowered = href.lower()
    if lowered.startswith(("javascript:", "mailto:", "tel:", "data:", "about:", "file:", "ftp:")):
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in href):
        return None
    href = href.replace(" ", "%20")
    if not href.isascii():
        href = _percent_encode_non_ascii(href)
    try:
        return urljoin(base, href)
    except ValueError:
        return None


def is_internal(url: NormalizedUrl, allowed_hosts: tuple[str, ...]) -> bool:
    return url.host in allowed_hosts


def origin_of(url: str) -> str:
    return normalize_url(url).origin


def path_of(url: str) -> str:
    return normalize_url(url).path


def path_glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a path pattern: * stays within a segment, ** spans segments."""
    if not pattern.startswith("/"):
        raise ValueError(f"Pfadmuster muss mit '/' beginnen: {pattern}")
    pieces: list[str] = ["^"]
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                pieces.append(".*")
                index += 2
                while index < len(pattern) and pattern[index] == "*":
                    index += 1
                continue
            pieces.append("[^/]*")
        else:
            pieces.append(re.escape(character))
        index += 1
    pieces.append("$")
    return re.compile("".join(pieces))


def matches_any_path(path: str, patterns: tuple[str, ...]) -> bool:
    return any(path_glob_to_regex(pattern).match(path) for pattern in patterns)


def path_matches(pattern: str, url_path: str) -> bool:
    return bool(path_glob_to_regex(pattern).match(url_path))


def key_for_url(url: str, *extra: str) -> str:
    return stable_json(["url", url, *extra])


def key_for_link(source_url: str, target_url: str) -> str:
    return stable_json(["link", source_url, target_url])


def key_for_gsc(
    property_name: str,
    search_type: str,
    country: str | None,
    device: str | None,
    kind: str,
    url: str | None = None,
    query: str | None = None,
) -> str:
    parts: list[str] = ["gsc", property_name, search_type, country or "", device or "", kind]
    if url is not None:
        parts.append(url)
    if query is not None:
        parts.append(query)
    return stable_json(parts)


def relative_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    """Shorten internal URLs to path and query for reports."""
    try:
        parsed = normalize_url(url)
    except InvalidUrl:
        return url
    if parsed.host in allowed_hosts:
        suffix = f"?{parsed.query}" if parsed.query else ""
        return f"{parsed.path}{suffix}"
    return url