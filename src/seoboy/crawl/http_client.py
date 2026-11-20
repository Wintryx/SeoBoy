"""HTTP-Client ohne automatische Weiterleitungsverfolgung."""

from __future__ import annotations

from dataclasses import dataclass, field
import gzip
import http.client
import re
import socket
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
import urllib.request
import zlib

from seoboy.shared.version import TOOL_VERSION

USER_AGENT = f"SeoBoy/{TOOL_VERSION} (lokales SEO-Audit)"
_CHARSET_RE = re.compile(r"charset\s*=\s*[\"']?([A-Za-z0-9._:-]+)", re.IGNORECASE)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int | None
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    error_code: str | None = None
    error_detail: str | None = None
    elapsed_ms: int = 0
    truncated: bool = False
    redirect_location: str | None = None
    header_items: tuple[tuple[str, str], ...] = ()

    @property
    def content_type(self) -> str | None:
        value = self.headers.get("content-type")
        if not value:
            return None
        return value.split(";", 1)[0].strip().lower() or None

    @property
    def charset(self) -> str | None:
        value = self.headers.get("content-type")
        if value:
            match = _CHARSET_RE.search(value)
            if match:
                return match.group(1)
        return None

    @property
    def is_redirect(self) -> bool:
        return self.status_code is not None and 300 <= self.status_code < 400

    @property
    def is_html(self) -> bool:
        content_type = self.content_type
        if content_type in {"text/html", "application/xhtml+xml"}:
            return True
        if content_type is not None:
            return False
        head = self.body.lstrip()[:512].lower()
        return any(
            marker in head
            for marker in (b"<!doctype html", b"<html", b"<head", b"<title")
        )

    @property
    def is_xml(self) -> bool:
        content_type = self.content_type or ""
        return (
            "xml" in content_type
            or self.body.lstrip()[:5] == b"<?xml"
            or self.body.lstrip()[:8].lower() == b"<urlset>"
            or self.body.lstrip()[:16].lower() == b"<sitemapindex>"
        )


def _decompress(data: bytes, encoding: str, limit: int) -> tuple[bytes, bool]:
    encoding = encoding.lower()
    if not data or not encoding:
        return data, False
    try:
        if "gzip" in encoding:
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        elif "deflate" in encoding:
            decompressor = zlib.decompressobj()
        else:
            return data, False
        output = decompressor.decompress(data, limit + 1)
        return output[:limit], len(output) > limit
    except (zlib.error, OSError):
        try:
            if "gzip" in encoding:
                output = gzip.decompress(data)
                return output[:limit], len(output) > limit
        except (OSError, EOFError):
            pass
        return data, False


def _read_limited(stream, limit: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(min(65536, limit + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            break
    data = b"".join(chunks)
    if len(data) > limit:
        return data[:limit], True
    return data, False


class HttpClient:
    def __init__(self, timeout: float = 15.0, max_bytes: int = 5_000_000) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        # Opener sind nicht für die gemeinsame Nutzung durch Threads gedacht.
        self._local = threading.local()

    def _opener(self) -> urllib.request.OpenerDirector:
        opener = getattr(self._local, "opener", None)
        if opener is None:
            opener = urllib.request.build_opener(_NoRedirect())
            self._local.opener = opener
        return opener

    def fetch(self, url: str) -> FetchResult:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.1",
                "Accept-Encoding": "gzip, deflate",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
                "Connection": "close",
            },
            method="GET",
        )
        started = time.monotonic()
        try:
            with self._opener().open(request, timeout=self.timeout) as response:
                status = response.status
                headers = {key.lower(): value for key, value in response.headers.items()}
                header_items = tuple(response.headers.items())
                body, truncated = _read_limited(response, self.max_bytes)
                encoding = headers.get("content-encoding", "")
                body, decompressed_truncated = _decompress(body, encoding, self.max_bytes)
                return self._result(
                    url, status, headers, header_items, body,
                    truncated or decompressed_truncated, started,
                )
        except HTTPError as error:
            status = error.code
            headers = {key.lower(): value for key, value in error.headers.items()} if error.headers else {}
            header_items = tuple(error.headers.items()) if error.headers else ()
            try:
                body, truncated = _read_limited(error, self.max_bytes)
            except (OSError, http.client.HTTPException):
                body, truncated = b"", False
            encoding = headers.get("content-encoding", "")
            body, decompressed_truncated = _decompress(body, encoding, self.max_bytes)
            return self._result(
                url, status, headers, header_items, body,
                truncated or decompressed_truncated, started,
            )
        except (socket.timeout, TimeoutError) as error:
            return self._error(url, "timeout", str(error) or "Zeitüberschreitung", started)
        except URLError as error:
            reason = error.reason
            if isinstance(reason, (socket.timeout, TimeoutError)):
                code = "timeout"
            elif isinstance(reason, socket.gaierror):
                code = "dns_error"
            elif isinstance(reason, ssl.SSLError):
                code = "ssl_error"
            elif isinstance(reason, ConnectionRefusedError):
                code = "connection_refused"
            else:
                code = "network_error"
            return self._error(url, code, str(reason) or str(error), started)
        except ssl.SSLError as error:
            return self._error(url, "ssl_error", str(error), started)
        except (OSError, http.client.HTTPException) as error:
            return self._error(url, "network_error", str(error), started)

    def _result(
        self,
        url: str,
        status: int,
        headers: dict[str, str],
        header_items: tuple[tuple[str, str], ...],
        body: bytes,
        truncated: bool,
        started: float,
    ) -> FetchResult:
        location = None
        if 300 <= status < 400:
            location = headers.get("location")
        return FetchResult(
            url=url,
            status_code=status,
            headers=headers,
            body=body,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
            redirect_location=location,
            header_items=header_items,
        )

    def _error(self, url: str, code: str, detail: str, started: float) -> FetchResult:
        return FetchResult(
            url=url,
            status_code=None,
            error_code=code,
            error_detail=detail[:500],
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )


def decode_body(result: FetchResult) -> str:
    """Dekodiert den Antwortkörper anhand Header, Meta-Charset und Fallbacks."""
    charset = result.charset
    if not charset:
        head = result.body[:4096].decode("ascii", errors="ignore")
        match = re.search(r"<meta[^>]+charset\s*=\s*[\"']?([A-Za-z0-9._:-]+)", head, re.I)
        if match:
            charset = match.group(1)
    for candidate in (charset, "utf-8", "cp1252", "latin-1"):
        if not candidate:
            continue
        try:
            return result.body.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return result.body.decode("utf-8", errors="replace")


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()
