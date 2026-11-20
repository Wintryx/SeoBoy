from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from seoboy import cli
from seoboy.infrastructure.doctor import run_doctor

from tests.support import make_config


class DoctorTests(unittest.TestCase):
    def test_configured_project_has_no_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(Path(tmp), "https://example.de/")
            report = run_doctor(config.config_path)
        self.assertEqual(report.errors, [])
        self.assertTrue(any(check.name == "Projektkonfiguration" and check.status == "ok" for check in report.checks))

    def test_missing_config_is_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_doctor(Path(tmp) / "missing.yaml")
        self.assertEqual(report.errors, [])
        self.assertTrue(any(check.name == "Projektkonfiguration" and check.status == "warning" for check in report.checks))

    def test_invalid_config_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yaml"
            path.write_text("project_id: [", encoding="utf-8")
            report = run_doctor(path)
        self.assertTrue(any(check.name == "Projektkonfiguration" and check.status == "error" for check in report.checks))

    def test_cli_doctor(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(Path(tmp), "https://example.de/")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = cli.main(["doctor", "--config", str(config.config_path)])
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertIn("Systemcheck", stdout.getvalue())
        self.assertIn("Projektkonfiguration", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
