"""Test helpers: local HTTP server, configuration, and HTML fixtures."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit

import yaml

from seoboy.infrastructure.config import ProjectConfig, load_config


@dataclass
class Route:
    status: int = 200
    body: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    content_type: str = "text/html; charset=utf-8"
    delay: float = 0.0
    responses: list[tuple[int, dict[str, str], str]] = field(default_factory=list)

    def next_response(self, count: int) -> tuple[int, dict[str, str], str]:
        if self.responses:
            index = min(count - 1, len(self.responses) - 1)
            status, headers, body = self.responses[index]
            return status, headers, body
        return self.status, self.headers, self.body


class FixtureSite:
    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        self.requests: Counter = Counter()
        self.active_count = 0
        self.max_active = 0
        self._active_lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.base = ""

    def add(
        self,
        path: str,
        *,
        status: int = 200,
        body: str = "",
        headers: dict[str, str] | None = None,
        content_type: str = "text/html; charset=utf-8",
        delay: float = 0.0,
        responses: list[tuple[int, dict[str, str], str]] | None = None,
    ) -> None:
        self.routes[path] = Route(
            status=status,
            body=body,
            headers=headers or {},
            content_type=content_type,
            delay=delay,
            responses=responses or [],
        )

    def add_html(self, path: str, title: str, body: str = "", **kwargs: Any) -> None:
        self.add(path, body=html(title, body, **kwargs))

    def __enter__(self) -> "FixtureSite":
        site = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

            def do_GET(self) -> None:  # noqa: N802
                with site._active_lock:
                    site.active_count += 1
                    site.max_active = max(site.max_active, site.active_count)
                try:
                    self._handle()
                finally:
                    with site._active_lock:
                        site.active_count -= 1

            def _handle(self) -> None:
                path = urlsplit(self.path).path
                site.requests[path] += 1
                route = site.routes.get(path)
                if route is None:
                    data = b"<html><head><title>Nicht gefunden</title></head><body>404</body></html>"
                    self.send_response(404)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                status, headers, body = route.next_response(site.requests[path])
                if route.delay:
                    time.sleep(route.delay)
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", route.content_type)
                self.send_header("Content-Length", str(len(data)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.base = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def url(self, path: str) -> str:
        return self.base + path

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()


def html(
    title: str | None,
    body: str = "",
    *,
    description: str | None = None,
    robots: str | None = None,
    canonical: str | None = None,
    extra_head: str = "",
    lang: str = "de",
) -> str:
    head = f"<html lang='{lang}'><head>"
    if title is not None:
        head += f"<title>{title}</title>"
    if description is not None:
        head += f"<meta name='description' content='{description}'>"
    if robots is not None:
        head += f"<meta name='robots' content='{robots}'>"
    if canonical is not None:
        head += f"<link rel='canonical' href='{canonical}'>"
    head += extra_head + "</head>"
    return head + f"<body>{body}</body></html>"


def make_config(
    directory: Path,
    base: str,
    *,
    crawl: dict[str, Any] | None = None,
    profiles: list[dict[str, Any]] | None = None,
    seeds: list[str] | None = None,
    exceptions: list[dict[str, Any]] | None = None,
    gsc: dict[str, Any] | None = None,
    project_id: str = "testprojekt",
    start_path: str = "/",
    file_name: str = "seoboy.yaml",
) -> ProjectConfig:
    host = urlsplit(base).hostname or "127.0.0.1"
    payload: dict[str, Any] = {
        "project_id": project_id,
        "start_url": base + start_path,
        "allowed_hosts": [host],
        "database": "./data/test.db",
        "reports_dir": "./reports",
        "crawl": {
            "max_urls": 100,
            "max_requests": 500,
            "max_runtime_seconds": 30,
            "max_parallel_per_host": 1,
            "min_request_interval_ms": 0,
            "max_redirects": 10,
            "request_timeout_seconds": 3,
            "max_response_bytes": 2_000_000,
            "remove_query_params": ["utm_*", "gclid", "fbclid"],
            "exclude_paths": ["/wp-admin/**", "/feed/**"],
        },
        "seeds": seeds or [],
        "priority_pages": profiles or [],
        "rule_exceptions": exceptions or [],
        "link_depth_limit": 3,
    }
    if crawl:
        payload["crawl"].update(crawl)
    if gsc:
        payload["gsc"] = gsc
    path = directory / file_name
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return load_config(path)
