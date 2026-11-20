from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from seoboy import cli
from seoboy.performance import audit as performance


class PerformanceTests(unittest.TestCase):
    def test_report_writes_lighthouse_and_crux(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report"
            with patch.object(
                performance,
                "fetch_lighthouse",
                return_value=performance.LighthouseResult(
                    url="https://example.de/",
                    strategy="mobile",
                    score=82.0,
                    metrics={"LCP": 2100.0, "CLS": 0.04},
                    fetched_at="2026-11-20T10:00:00Z",
                ),
            ), patch.object(
                performance,
                "fetch_crux",
                return_value=performance.CruxResult(
                    url="https://example.de/",
                    form_factor="PHONE",
                    metrics={"largest_contentful_paint": 2500.0},
                    collection_start="2026-10-01",
                    collection_end="2026-10-28",
                ),
            ):
                performance.run_performance(
                    "https://example.de/", api_key="key", out=out
                )
            self.assertTrue((out / "00_PERFORMANCE.md").is_file())
            self.assertTrue((out / "raw_data" / "performance.csv").is_file())
            text = (out / "00_PERFORMANCE.md").read_text(encoding="utf-8")
            self.assertIn("Performance-Score", text)
            self.assertIn("CrUX-Felddaten", text)

    def test_cli_requires_api_key(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict("os.environ", {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = cli.main(["performance", "--url", "https://example.de/"])
        self.assertEqual(code, 2)
        self.assertIn("API-Key", stderr.getvalue())

    def test_cli_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.object(cli, "run_performance", return_value=out):
                with patch.dict("os.environ", {"SEOBOY_PSI_API_KEY": "key"}, clear=True):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = cli.main(
                            [
                                "performance",
                                "--url",
                                "https://example.de/",
                                "--out",
                                str(out),
                            ]
                        )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertIn("Performance-Bericht", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
