from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from seoboy.application import runner
from seoboy.infrastructure.database import connect

from tests.support import FixtureSite, make_config


class RobustnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_auxiliary_requests_are_retried(self):
        with FixtureSite() as site:
            site.add(
                "/robots.txt",
                responses=[
                    (500, {}, "kaputt"),
                    (500, {}, "kaputt"),
                    (200, {}, f"User-agent: *\nAllow: /\nSitemap: {site.base}/sitemap.xml\n"),
                ],
                content_type="text/plain",
            )
            site.add(
                "/sitemap.xml",
                responses=[
                    (500, {}, "kaputt"),
                    (
                        200,
                        {},
                        "<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
                        f"<url><loc>{site.base}/deep/</loc></url></urlset>",
                    ),
                ],
                content_type="application/xml",
            )
            site.add_html("/", "Start", "<a href='/a/'>A</a>")
            site.add_html("/a/", "A")
            site.add_html("/deep/", "Deep")
            config = make_config(self.directory, site.base)
            outcome = runner.run_project(config)
            self.assertEqual(outcome.status, "completed")
            connection = connect(config.database)
            try:
                robots = connection.execute(
                    "SELECT robots_state FROM crawl_origins"
                ).fetchone()[0]
                self.assertEqual(robots, "available")
                robots_attempts = connection.execute(
                    "SELECT COUNT(*) FROM http_attempts a JOIN crawl_jobs j "
                    "ON j.job_id = a.job_id WHERE j.purpose = 'robots'"
                ).fetchone()[0]
                self.assertEqual(robots_attempts, 3)
                sitemap_attempts = connection.execute(
                    "SELECT COUNT(*) FROM http_attempts a JOIN crawl_jobs j "
                    "ON j.job_id = a.job_id WHERE j.purpose = 'sitemap'"
                ).fetchone()[0]
                self.assertEqual(sitemap_attempts, 2)
                deep = connection.execute(
                    "SELECT state FROM run_urls WHERE url_id = "
                    "(SELECT url_id FROM urls WHERE normalized_url = ?)",
                    (site.url("/deep/"),),
                ).fetchone()
                self.assertEqual(deep["state"], "finished")
            finally:
                connection.close()

    def test_timeout_is_retried_and_reported(self):
        with FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html("/", "Start", "<a href='/slow/'>Langsam</a>")
            site.add("/slow/", body="<html><head><title>Langsam</title></head></html>", delay=0.5)
            config = make_config(
                self.directory,
                site.base,
                crawl={"request_timeout_seconds": 0.1, "min_request_interval_ms": 0},
            )
            outcome = runner.run_project(config)
            self.assertEqual(outcome.status, "completed")
            connection = connect(config.database)
            try:
                attempts = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT a.attempt_no, a.state, a.error_code FROM http_attempts a "
                        "JOIN crawl_jobs j ON j.job_id = a.job_id "
                        "WHERE j.url_id = (SELECT url_id FROM urls WHERE normalized_url = ?) "
                        "ORDER BY a.attempt_no",
                        (site.url("/slow/"),),
                    )
                ]
                self.assertEqual(len(attempts), 3)
                self.assertTrue(all(item["error_code"] == "timeout" for item in attempts))
                finding = connection.execute(
                    "SELECT severity FROM rule_results WHERE rule_id = 'HTTP_UNAVAILABLE' "
                    "AND subject_key = ?",
                    ('["url","' + site.url("/slow/") + '"]',),
                ).fetchone()
                self.assertEqual(finding["severity"], "medium")
            finally:
                connection.close()

    def test_sitemap_only_reads_direct_loc_elements(self):
        with FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add(
                "/sitemap.xml",
                body=(
                    "<?xml version='1.0'?>"
                    "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9' "
                    "xmlns:image='http://www.google.com/schemas/sitemap-image/1.1'>"
                    f"<url><loc>{site.base}/deep/</loc>"
                    f"<image:image><image:loc>{site.base}/bild.jpg</image:loc></image:image>"
                    "</url></urlset>"
                ),
                content_type="application/xml",
            )
            site.add_html("/", "Start")
            site.add_html("/deep/", "Deep")
            config = make_config(self.directory, site.base)
            runner.run_project(config)
            connection = connect(config.database)
            try:
                image = connection.execute(
                    "SELECT COUNT(*) FROM urls WHERE normalized_url = ?",
                    (site.url("/bild.jpg"),),
                ).fetchone()[0]
                self.assertEqual(image, 0)
                deep = connection.execute(
                    "SELECT state FROM run_urls WHERE url_id = "
                    "(SELECT url_id FROM urls WHERE normalized_url = ?)",
                    (site.url("/deep/"),),
                ).fetchone()
                self.assertEqual(deep["state"], "finished")
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
