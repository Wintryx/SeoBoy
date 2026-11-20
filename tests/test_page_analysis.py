from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from seoboy.application import runner

from tests.support import FixtureSite, make_config


class PageAnalysisTests(unittest.TestCase):
    def test_pdf_is_reported_as_not_evaluated(self):
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add_html(
                "/",
                "Start",
                '<a href="/plan.pdf">Bauplan als PDF</a>',
            )
            site.add(
                "/plan.pdf",
                body="%PDF-1.4\n1 0 obj\n<<>>\nendobj\n",
                content_type="application/pdf",
            )
            config = make_config(Path(tmp), site.base)
            outcome = runner.run_project(config)
            self.assertEqual(outcome.status, "completed")
            report = outcome.report_dir
            self.assertIsNotNone(report)
            markdown = (report / "03_PAGE_ANALYSIS.md").read_text(encoding="utf-8")
            self.assertIn("Nicht-HTML-Ziele (nicht bewertet) | 1", markdown)
            self.assertIn("nicht bewertet", markdown)
            with (report / "raw_data" / "pages.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                rows = {row["url"]: row for row in csv.DictReader(stream)}
            pdf = rows[site.base + "/plan.pdf"]
            self.assertEqual(pdf["content_type"], "application/pdf")
            self.assertEqual(pdf["evaluation"], "non_html")
            self.assertEqual(pdf["indexable"], "")
            self.assertEqual(pdf["word_count"], "")


if __name__ == "__main__":
    unittest.main()
