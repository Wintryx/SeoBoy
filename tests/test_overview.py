from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from seoboy.application import runner

from tests.support import FixtureSite, make_config


class ProjectOverviewTests(unittest.TestCase):
    def test_offline_html_overview_is_written_and_escaped(self):
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html(
                "/",
                "<script>alert('x')</script>",
                "<h1>Start</h1><a href='/kontakt/'>Kontakt</a>",
            )
            site.add_html("/kontakt/", "Kontakt", "<h1>Kontakt</h1>")
            config = make_config(Path(tmp), site.base)
            outcome = runner.run_project(config)
            assert outcome.report_dir is not None
            path = outcome.report_dir / "PROJECT_OVERVIEW.html"
            self.assertTrue(path.is_file())
            text = path.read_text(encoding="utf-8")
            self.assertIn("Projektübersicht", text)
            self.assertIn("Was zuerst?", text)
            self.assertIn("/kontakt/", text)
            self.assertNotIn("<script>alert('x')</script>", text)
            self.assertNotIn('<script src=', text)
            manifest = json.loads(
                (outcome.report_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertIn("PROJECT_OVERVIEW.html", manifest["files"])


if __name__ == "__main__":
    unittest.main()
