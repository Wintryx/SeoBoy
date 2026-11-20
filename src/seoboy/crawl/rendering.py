"""Optional Playwright rendering and HTTP/browser comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from seoboy.crawl.html_extract import ExtractedPage, extract_page
from seoboy.crawl.http_client import HttpClient, decode_body
from seoboy.shared.util import excel_safe, iso_utc


class RenderingError(RuntimeError):
    """Playwright is unavailable or rendering failed."""


@dataclass(frozen=True)
class RenderedPage:
    url: str
    final_url: str
    status: int | None
    title: str | None
    meta_description: str | None
    h1: str | None
    h1_count: int
    word_count: int
    image_count: int
    images_missing_alt: int
    schema_types: tuple[str, ...]
    links: int
    content_type: str | None
    engine: str = "playwright"


@dataclass(frozen=True)
class RenderingComparison:
    url: str
    http_status: int | None
    browser_status: int | None
    http_title: str | None
    browser_title: str | None
    title_changed: bool
    meta_changed: bool
    h1_changed: bool
    word_delta: int
    link_delta: int
    http_schema: tuple[str, ...]
    browser_schema: tuple[str, ...]
    note: str = ""


def _chrome_path() -> str | None:
    configured = os.environ.get("SEOBOY_CHROME")
    if configured and Path(configured).is_file():
        return configured
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    if os.name == "nt":
        for candidate in (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ):
            if candidate.is_file():
                return str(candidate)
    return None


def _render_with_chrome(url: str, timeout_ms: int) -> RenderedPage:
    executable = _chrome_path()
    if not executable:
        raise RenderingError(
            "Weder Playwright noch Chrome/Edge gefunden. Installation: "
            "pip install 'seoboy[rendering]' && playwright install chromium"
        )
    with tempfile.TemporaryDirectory(prefix="seoboy-chrome-") as temporary:
        result = subprocess.run(
            [
                executable,
                "--headless=new",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                f"--user-data-dir={temporary}",
                "--dump-dom",
                url,
            ],
            capture_output=True,
            check=False,
            timeout=max(5, timeout_ms // 1000 + 5),
        )
    if result.returncode != 0 or not result.stdout:
        detail = result.stderr.decode("utf-8", errors="replace")[:500]
        raise RenderingError(f"Chrome-Rendering fehlgeschlagen: {detail or result.returncode}")
    html = result.stdout.decode("utf-8", errors="replace")
    extracted = extract_page(html, url, ())
    return RenderedPage(
        url=url,
        final_url=url,
        status=None,
        title=extracted.title,
        meta_description=extracted.meta_description,
        h1=extracted.h1,
        h1_count=extracted.h1_count,
        word_count=extracted.word_count,
        image_count=extracted.image_count,
        images_missing_alt=extracted.images_missing_alt,
        schema_types=extracted.schema_types,
        links=len(extracted.links),
        content_type=None,
        engine="chrome",
    )


def render_page(
    url: str,
    *,
    timeout_ms: int = 15_000,
    wait_until: str = "networkidle",
    user_agent: str | None = None,
    browser_name: str = "chromium",
    engine: str = "auto",
) -> RenderedPage:
    if engine not in {"auto", "playwright", "chrome"}:
        raise RenderingError(f"Unbekannte Rendering-Engine: {engine}")
    if engine in {"auto", "playwright"}:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            if engine == "playwright":
                raise RenderingError(
                    "Playwright ist nicht installiert. Installation: "
                    "pip install 'seoboy[rendering]' && playwright install chromium"
                ) from error
            return _render_with_chrome(url, timeout_ms)
        try:
            with sync_playwright() as playwright:
                browser_type = getattr(playwright, browser_name, None)
                if browser_type is None:
                    raise RenderingError(f"Unbekannte Browser-Engine: {browser_name}")
                browser = browser_type.launch(headless=True)
                context = (
                    browser.new_context(user_agent=user_agent)
                    if user_agent
                    else browser.new_context()
                )
                page = context.new_page()
                response = page.goto(url, wait_until=wait_until, timeout=timeout_ms)
                html = page.content()
                final_url = page.url
                headers = response.headers if response is not None else {}
                status = response.status if response is not None else None
                browser.close()
        except RenderingError:
            raise
        except Exception as error:
            raise RenderingError(f"Rendering von {url} fehlgeschlagen: {error}") from error
        extracted = extract_page(html, final_url, tuple(headers.items()))
        return RenderedPage(
            url=url,
            final_url=final_url,
            status=status,
            title=extracted.title,
            meta_description=extracted.meta_description,
            h1=extracted.h1,
            h1_count=extracted.h1_count,
            word_count=extracted.word_count,
            image_count=extracted.image_count,
            images_missing_alt=extracted.images_missing_alt,
            schema_types=extracted.schema_types,
            links=len(extracted.links),
            content_type=headers.get("content-type"),
            engine="playwright",
        )
    return _render_with_chrome(url, timeout_ms)


def compare_pages(
    url: str,
    http_page: ExtractedPage | None,
    http_status: int | None,
    browser: RenderedPage,
) -> RenderingComparison:
    http_title = http_page.title if http_page else None
    http_description = http_page.meta_description if http_page else None
    http_h1 = http_page.h1 if http_page else None
    http_schema = http_page.schema_types if http_page else ()
    http_words = http_page.word_count if http_page else 0
    http_links = len(http_page.links) if http_page else 0
    notes: list[str] = []
    if http_page is None:
        notes.append("HTTP-Dokument nicht auswertbar")
    if browser.status is None:
        notes.append("Browser-Status fehlt")
    if http_status != browser.status:
        notes.append(f"Status {http_status} → {browser.status}")
    return RenderingComparison(
        url=url,
        http_status=http_status,
        browser_status=browser.status,
        http_title=http_title,
        browser_title=browser.title,
        title_changed=http_title != browser.title,
        meta_changed=http_description != browser.meta_description,
        h1_changed=http_h1 != browser.h1,
        word_delta=browser.word_count - http_words,
        link_delta=browser.links - http_links,
        http_schema=http_schema,
        browser_schema=browser.schema_types,
        note="; ".join(notes),
    )


def _write_csv(path: Path, rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(
            [
                "url",
                "http_status",
                "browser_status",
                "http_title",
                "browser_title",
                "title_changed",
                "meta_changed",
                "h1_changed",
                "word_delta",
                "link_delta",
                "http_schema",
                "browser_schema",
                "note",
            ]
        )
        for row in rows:
            writer.writerow([excel_safe(value) for value in row])


def render_report(
    urls: list[str],
    *,
    out: Path,
    timeout_ms: int = 15_000,
    wait_until: str = "networkidle",
    browser_name: str = "chromium",
    engine: str = "auto",
) -> Path:
    client = HttpClient()
    comparisons: list[RenderingComparison] = []
    rendered: list[RenderedPage] = []
    for url in urls:
        http_result = client.fetch(url)
        http_page = None
        status = http_result.status_code
        if http_result.body and http_result.is_html and status is not None:
            http_page = extract_page(
                decode_body(http_result), http_result.url, http_result.header_items
            )
        browser = render_page(
            url,
            timeout_ms=timeout_ms,
            wait_until=wait_until,
            browser_name=browser_name,
            engine=engine,
        )
        rendered.append(browser)
        comparisons.append(compare_pages(url, http_page, status, browser))
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "raw_data"
    raw.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": iso_utc(),
        "browser": browser_name,
        "engine": engine,
        "used_engines": sorted({item.engine for item in rendered}),
        "urls": urls,
        "rendered": [
            {
                "url": item.url,
                "final_url": item.final_url,
                "status": item.status,
                "title": item.title,
                "meta_description": item.meta_description,
                "h1": item.h1,
                "h1_count": item.h1_count,
                "word_count": item.word_count,
                "image_count": item.image_count,
                "images_missing_alt": item.images_missing_alt,
                "schema_types": list(item.schema_types),
                "links": item.links,
            }
            for item in rendered
        ],
    }
    (raw / "rendering.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_csv(
        raw / "rendering.csv",
        [
            [
                item.url,
                item.http_status if item.http_status is not None else "",
                item.browser_status if item.browser_status is not None else "",
                item.http_title or "",
                item.browser_title or "",
                "1" if item.title_changed else "0",
                "1" if item.meta_changed else "0",
                "1" if item.h1_changed else "0",
                item.word_delta,
                item.link_delta,
                "|".join(item.http_schema),
                "|".join(item.browser_schema),
                item.note,
            ]
            for item in comparisons
        ],
    )
    lines = [
        "# SeoBoy – HTTP-/Browser-Rendering-Vergleich",
        "",
        f"**Erzeugt:** {datetime.now().astimezone():%Y-%m-%d %H:%M %Z}",
        f"**URLs:** {len(urls)}",
        f"**Wartezeit:** {wait_until}, Timeout {timeout_ms} ms",
        f"**Verwendete Engine:** {', '.join(sorted({item.engine for item in rendered}))}",
        *(
            [
                "**Hinweis:** Chrome/Edge-Fallback. HTTP-Status und Response-Header",
                "sind dabei nicht zuverlässig verfügbar; Node.js/Playwright werden nicht benötigt.",
            ]
            if any(item.engine == "chrome" for item in rendered)
            else []
        ),
        "",
        "| URL | HTTP | Browser | Titel geändert | Meta geändert | H1 geändert | Wörter Δ | Links Δ | Hinweis |",
        "| --- | ---: | ---: | :---: | :---: | :---: | ---: | ---: | --- |",
    ]
    for item in comparisons:
        lines.append(
            "| "
            + " | ".join(
                [
                    item.url,
                    str(item.http_status if item.http_status is not None else "–"),
                    str(item.browser_status if item.browser_status is not None else "–"),
                    "ja" if item.title_changed else "nein",
                    "ja" if item.meta_changed else "nein",
                    "ja" if item.h1_changed else "nein",
                    f"{item.word_delta:+d}",
                    f"{item.link_delta:+d}",
                    item.note or "–",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Browser-Extrakte stehen in raw_data/rendering.json und raw_data/rendering.csv. "
            "Sie sind eine Momentaufnahme des gewählten Browser-Profils.",
            "",
        ]
    )
    (out / "00_RENDERING.md").write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n"
    )
    return out
