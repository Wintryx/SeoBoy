from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from seoboy.benchmark.sampler import collect_snapshot
from tests.support import FixtureSite


class FullBenchmarkTests(unittest.TestCase):
    def test_full_mode_follows_multiple_sitemap_children(self):
        with FixtureSite() as site:
            site.add(
                "/robots.txt",
                body=f"User-agent: *\nAllow: /\nSitemap: {site.base}/sitemap_index.xml\n",
                content_type="text/plain",
            )
            site.add(
                "/sitemap_index.xml",
                body=(
                    "<sitemapindex>"
                    f"<sitemap><loc>{site.base}/sitemap-a.xml</loc></sitemap>"
                    f"<sitemap><loc>{site.base}/sitemap-b.xml</loc></sitemap>"
                    "</sitemapindex>"
                ),
                content_type="application/xml",
            )
            site.add(
                "/sitemap-a.xml",
                body=f"<urlset><url><loc>{site.base}/a/</loc></url></urlset>",
                content_type="application/xml",
            )
            site.add(
                "/sitemap-b.xml",
                body=f"<urlset><url><loc>{site.base}/b/</loc></url></urlset>",
                content_type="application/xml",
            )
            site.add_html("/", "Start", "<h1>Start</h1>")
            site.add_html("/a/", "A", "<h1>A</h1>")
            site.add_html("/b/", "B", "<h1>B</h1>")
            snapshot = collect_snapshot(site.base, "full", max_pages=10, full=True)
        urls = {page.url for page in snapshot.pages}
        self.assertIn(site.url("/a/"), urls)
        self.assertIn(site.url("/b/"), urls)
        self.assertTrue(snapshot.full)


if __name__ == "__main__":
    unittest.main()
