from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from seoboy.application import runner
from seoboy.reporting.run_report import find_report_dir

from tests.support import FixtureSite, make_config


class ReportFolderTests(unittest.TestCase):
    def test_local_time_name_reuses_existing_folder(self):
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html("/", "Start", "<h1>Start</h1>")
            config = make_config(Path(tmp), site.base)
            outcome = runner.run_project(config)
            assert outcome.report_dir is not None
            name = outcome.report_dir.name
            self.assertRegex(name, r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_")
            self.assertNotIn(outcome.run_id, name)
            self.assertEqual(find_report_dir(config, outcome.run_id), outcome.report_dir)
            again = runner.rerender_report(config, outcome.run_id)
            self.assertEqual(again, outcome.report_dir)


if __name__ == "__main__":
    unittest.main()
