from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from seoboy.application import runner

from tests.support import FixtureSite, make_config


class GscReportTests(unittest.TestCase):
    def test_page_only_gsc_writes_query_report_note(self):
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add_html("/", "Start", "<h1>Start</h1>")
            config = make_config(Path(tmp), site.base)
            gsc = Path(tmp) / "gsc"
            gsc.mkdir()
            (gsc / "manifest.json").write_text(
                json.dumps(
                    {
                        "property": "sc-domain:example.de",
                        "search_type": "web",
                        "country": None,
                        "device": None,
                        "periods": [
                            {
                                "start": "2026-10-01",
                                "end": "2026-10-31",
                                "pages": "pages.csv",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (gsc / "pages.csv").write_text(
                "page,clicks,impressions,position\n"
                f"{site.base}/,1,10,5.0\n",
                encoding="utf-8",
            )
            outcome = runner.run_project(config, gsc)
            report = outcome.report_dir
            self.assertIsNotNone(report)
            text = (report / "04_GSC_QUERY_PAGES.md").read_text(encoding="utf-8")
            self.assertIn("Keine Query-/Seitendaten", text)
            self.assertTrue((report / "raw_data" / "gsc_query_pages.csv").is_file())


if __name__ == "__main__":
    unittest.main()
