from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from seoboy.application import runner
from seoboy.geo.audit import audit_geo

from tests.support import FixtureSite, html, make_config


class GeoTests(unittest.TestCase):
    def test_geo_without_database_does_not_create_one(self):
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add(
                "/robots.txt",
                body="User-agent: *\nAllow: /\n",
                content_type="text/plain",
            )
            site.add("/llms.txt", body="# Beispiel\n", content_type="text/plain")
            site.add_html("/", "Start", "<h1>Start</h1>")
            config = make_config(Path(tmp), site.base)
            folder = audit_geo(config, Path(tmp) / "geo-no-db")
            self.assertFalse(config.database.exists())
            self.assertTrue((folder / "00_GEO_READINESS.md").is_file())

    def test_geo_report_checks_bots_llms_and_schema(self):
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add(
                "/robots.txt",
                body=(
                    "User-agent: SEOBOY\nAllow: /\n\n"
                    "User-agent: GPTBot\nDisallow: /\n"
                ),
                content_type="text/plain",
            )
            site.add(
                "/llms.txt",
                body="# Beispiel\n\n- https://example.de/\n",
                content_type="text/plain",
            )
            schema = json.dumps(
                {
                    "@context": "https://schema.org",
                    "@type": "Organization",
                    "name": "AW Audio",
                }
            )
            site.add_html(
                "/",
                "Start",
                "<h1>Start</h1><p>" + ("Inhalt " * 80) + "</p>",
                extra_head=f"<script type='application/ld+json'>{schema}</script>",
            )
            config = make_config(Path(tmp), site.base)
            outcome = runner.run_project(config)
            self.assertEqual(outcome.status, "completed")
            folder = audit_geo(config, Path(tmp) / "geo")
            report = (folder / "00_GEO_READINESS.md").read_text(encoding="utf-8")
            self.assertIn("GPTBot", report)
            self.assertIn("gesperrt", report)
            self.assertIn("llms.txt", report)
            self.assertIn("Seiten mit strukturierten Daten", report)
            self.assertTrue((folder / "raw_data" / "geo_bots.csv").is_file())


if __name__ == "__main__":
    unittest.main()
