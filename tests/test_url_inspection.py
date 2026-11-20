from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from seoboy import cli
from seoboy.application import runner
from seoboy.gsc import api as gsc_api
from seoboy.gsc.inspection_store import store_inspection
from seoboy.infrastructure.database import connect

from tests.support import FixtureSite, make_config


def inspection(verdict: str = "PASS", coverage: str = "Submitted and indexed") -> dict:
    return {
        "verdict": verdict,
        "indexStatusResult": {
            "coverageState": coverage,
            "indexingState": "INDEXING_ALLOWED",
            "robotsTxtState": "ALLOWED",
            "pageFetchState": "SUCCESSFUL",
            "googleCanonical": "https://example.de/",
            "userCanonical": "https://example.de/",
            "lastCrawlTime": "2026-11-20T08:00:00Z",
        },
    }


class UrlInspectionTests(unittest.TestCase):
    def _run(self, directory: Path) -> tuple[object, str]:
        with FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html("/", "Start", "<h1>Start</h1><a href='/a/'>A</a>")
            site.add_html("/a/", "A", "<h1>A</h1>")
            config = make_config(directory, site.base)
            outcome = runner.run_project(config)
            self.assertEqual(outcome.status, "completed")
            connection = connect(config.database)
            try:
                run_id = connection.execute("SELECT run_id FROM runs").fetchone()[0]
                url_id = connection.execute(
                    "SELECT url_id FROM urls WHERE project_id = ? AND normalized_url = ?",
                    (config.project_id, site.base + "/"),
                ).fetchone()[0]
            finally:
                connection.close()
        return config, run_id, url_id

    def test_store_report_and_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, run_id, url_id = self._run(Path(tmp))
            connection = connect(config.database)
            try:
                store_inspection(
                    connection,
                    run_id,
                    url_id,
                    "https://example.de/",
                    "https://example.de/",
                    inspection(),
                )
            finally:
                connection.close()
            folder = runner.rerender_report(config, run_id)
            self.assertTrue((folder / "06_URL_INSPECTION.md").is_file())
            self.assertTrue((folder / "raw_data" / "url_inspections.csv").is_file())
            text = (folder / "06_URL_INSPECTION.md").read_text(encoding="utf-8")
            self.assertIn("Submitted and indexed", text)
            self.assertIn("URL Inspection", text)

            second = runner.run_project(config)
            connection = connect(config.database)
            try:
                second_run_id = connection.execute(
                    "SELECT run_id FROM runs WHERE run_id <> ?", (run_id,)
                ).fetchone()[0]
                store_inspection(
                    connection,
                    second_run_id,
                    url_id,
                    "https://example.de/",
                    "https://example.de/",
                    inspection("FAIL", "Crawled - currently not indexed"),
                )
            finally:
                connection.close()
            diff_folder = runner.compare_runs(config, run_id, second_run_id)
            diff_text = (diff_folder / "05_AUDIT_DIFF.md").read_text(encoding="utf-8")
            self.assertIn("## URL Inspection", diff_text)
            self.assertIn("Geändert", diff_text)
            self.assertTrue(
                (diff_folder / "raw_data" / "url_inspection_diff.csv").is_file()
            )

    def test_cli_batch_selects_and_stores(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, run_id, _url_id = self._run(Path(tmp))
            credentials = Path(tmp) / "gsc.json"
            credentials.write_text("{}", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.object(
                gsc_api, "load_credentials", return_value=gsc_api.GscCredentials(access_token="test")
            ), patch.object(gsc_api, "inspect_url", return_value=inspection()):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = cli.main(
                        [
                            "url-inspection",
                            "--config",
                            str(config.config_path),
                            "--run",
                            run_id,
                            "--credentials",
                            str(credentials),
                            "--property",
                            "https://example.de/",
                            "--limit",
                            "1",
                        ]
                    )
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertIn("1 von 1 URL(s) gespeichert", stdout.getvalue())
            connection = connect(config.database)
            try:
                count = connection.execute(
                    "SELECT COUNT(*) FROM url_inspections WHERE run_id = ?", (run_id,)
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
