from __future__ import annotations

from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from seoboy.crawl.html_extract import extract_page
from seoboy.crawl.rendering import (
    RenderedPage,
    RenderingError,
    _render_with_chrome,
    compare_pages,
    render_page,
    render_report,
)

from tests.support import FixtureSite, html


class RenderingTests(unittest.TestCase):
    def test_compare_http_and_browser(self):
        http_page = extract_page(
            html("HTTP", "<h1>HTTP</h1><p>kurz</p>"), "https://example.de/"
        )
        browser = RenderedPage(
            url="https://example.de/",
            final_url="https://example.de/",
            status=200,
            title="Browser",
            meta_description="Browser-Meta",
            h1="Browser H1",
            h1_count=1,
            word_count=120,
            image_count=2,
            images_missing_alt=1,
            schema_types=("Organization",),
            links=8,
            content_type="text/html",
        )
        result = compare_pages("https://example.de/", http_page, 200, browser)
        self.assertTrue(result.title_changed)
        self.assertTrue(result.meta_changed)
        self.assertTrue(result.h1_changed)
        self.assertEqual(result.word_delta, 119)
        self.assertEqual(result.link_delta, 8)
        self.assertEqual(result.browser_schema, ("Organization",))

    def test_chrome_fallback(self):
        with patch(
            "seoboy.crawl.rendering._chrome_path", return_value="chrome.exe"
        ), patch("seoboy.crawl.rendering.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stderr = b""
            run.return_value.stdout = html(
                "Chrome", "<h1>Gerendert</h1><p>Text</p>"
            ).encode("utf-8")
            page = _render_with_chrome("https://example.de/", 5000)
        self.assertEqual(page.engine, "chrome")
        self.assertEqual(page.title, "Chrome")
        self.assertEqual(page.h1, "Gerendert")

    def test_auto_falls_back_when_playwright_browser_fails(self):
        chrome_page = RenderedPage(
            url="https://example.de/",
            final_url="https://example.de/",
            status=None,
            title="Chrome",
            meta_description=None,
            h1="Chrome",
            h1_count=1,
            word_count=10,
            image_count=0,
            images_missing_alt=0,
            schema_types=(),
            links=1,
            content_type=None,
            engine="chrome",
        )
        module = types.ModuleType("playwright.sync_api")
        def broken_playwright():
            raise RuntimeError("browser executable missing")
        module.sync_playwright = broken_playwright
        package = types.ModuleType("playwright")
        package.sync_api = module
        with patch.dict(
            "sys.modules", {"playwright": package, "playwright.sync_api": module}
        ), patch(
            "seoboy.crawl.rendering._render_with_chrome",
            return_value=chrome_page,
        ) as fallback:
            page = render_page("https://example.de/", engine="auto")
        self.assertEqual(page.engine, "chrome")
        fallback.assert_called_once()

    def test_missing_playwright_is_explained(self):
        with patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            with self.assertRaises(RenderingError) as context:
                render_page("https://example.de/", engine="playwright")
        self.assertIn("Playwright ist nicht installiert", str(context.exception))

    def test_render_report_with_injected_browser(self):
        with FixtureSite() as site:
            site.add_html("/", "Start", "<h1>Start</h1><p>Text</p>")
            browser = RenderedPage(
                url=site.base + "/",
                final_url=site.base + "/",
                status=200,
                title="Start",
                meta_description=None,
                h1="Start",
                h1_count=1,
                word_count=2,
                image_count=0,
                images_missing_alt=0,
                schema_types=(),
                links=0,
                content_type="text/html",
            )
            with tempfile.TemporaryDirectory() as tmp:
                with patch(
                    "seoboy.crawl.rendering.render_page", return_value=browser
                ):
                    folder = render_report(
                        [site.base + "/"], out=Path(tmp) / "rendering"
                    )
                report = (folder / "00_RENDERING.md").read_text(encoding="utf-8")
                self.assertIn("HTTP-/Browser-Rendering-Vergleich", report)
                self.assertTrue((folder / "raw_data" / "rendering.csv").is_file())
                self.assertTrue((folder / "raw_data" / "rendering.json").is_file())


if __name__ == "__main__":
    unittest.main()
