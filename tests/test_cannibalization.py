from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from seoboy.application import runner
from seoboy.reporting.cannibalization import analyze

from tests.support import FixtureSite, make_config


class CannibalizationTests(unittest.TestCase):
    def test_onpage_pair_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html(
                "/",
                "Start",
                "<a href='/dj-koeln/'>A</a><a href='/hochzeit-dj-koeln/'>B</a>",
            )
            site.add_html(
                "/dj-koeln/",
                "Hochzeits DJ Koeln",
                "<h1>Hochzeits DJ Koeln</h1><p>Feiern in Koeln mit Musik.</p>",
            )
            site.add_html(
                "/hochzeit-dj-koeln/",
                "Hochzeits DJ Koeln",
                "<h1>Hochzeits DJ Koeln</h1><p>Feiern in Koeln mit Musik.</p>",
            )
            config = make_config(Path(tmp), site.base)
            outcome = runner.run_project(config)
            self.assertIsNotNone(outcome.report_dir)
            path = outcome.report_dir / "08_KEYWORD_CANNIBALIZATION.md"
            self.assertTrue(path.is_file())
            text = path.read_text(encoding="utf-8")
            self.assertIn("On-Page-Kandidaten", text)
            self.assertIn("/dj-koeln/", text)
            self.assertIn("/hochzeit-dj-koeln/", text)
            self.assertIn("koeln", text.lower())

    def test_no_gsc_is_not_called_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html("/", "Start", "<h1>Start</h1>")
            config = make_config(Path(tmp), site.base)
            outcome = runner.run_project(config)
            text = (outcome.report_dir / "08_KEYWORD_CANNIBALIZATION.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("keine garantie", text.lower())


if __name__ == "__main__":
    unittest.main()
