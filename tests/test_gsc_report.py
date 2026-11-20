from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from seoboy.application import runner

from tests.support import FixtureSite, make_config


def write_gsc(directory: Path, base: str, start: str, end: str, clicks: int, impressions: int, position: float) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "property": "https://example.de/",
                "search_type": "web",
                "country": None,
                "device": None,
                "periods": [
                    {
                        "start": start,
                        "end": end,
                        "source_format": "gsc_ui_csv",
                        "pages": "pages.csv",
                        "page_queries": "queries.csv",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (directory / "pages.csv").write_text(
        "page,clicks,impressions,position\n"
        f"{base}/,{clicks},{impressions},{position}\n",
        encoding="utf-8",
    )
    (directory / "queries.csv").write_text(
        "page,query,clicks,impressions,position\n"
        f"{base}/,seo,{clicks},{impressions},{position}\n",
        encoding="utf-8",
    )


class GscReportTests(unittest.TestCase):
    def test_history_compares_prior_run(self):
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add_html("/", "Start", "<h1>Start</h1>")
            config = make_config(Path(tmp), site.base)
            first = Path(tmp) / "gsc-1"
            second = Path(tmp) / "gsc-2"
            write_gsc(first, site.base, "2026-08-01", "2026-08-30", 10, 100, 8.0)
            write_gsc(second, site.base, "2026-09-01", "2026-09-30", 5, 120, 9.0)
            first_outcome = runner.run_project(config, first)
            second_outcome = runner.run_project(config, second)
            self.assertIsNotNone(first_outcome.report_dir)
            self.assertIsNotNone(second_outcome.report_dir)
            report = second_outcome.report_dir
            text = (report / "05_GSC_HISTORY.md").read_text(encoding="utf-8")
            self.assertIn("| seo | 10 | 5 | -5 | 100 | 120 | 8.0 | 9.0 |", text)
            self.assertIn("| Lauf |", text)
            with (report / "raw_data" / "gsc_history.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "common")
            self.assertEqual(rows[0]["clicks_delta"], "-5")
            self.assertEqual(rows[0]["previous_run_id"], first_outcome.report_dir.name.rsplit("_", 1)[-1])

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
