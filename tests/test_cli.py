from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import date
import io
from pathlib import Path
import tempfile
import unittest

from seoboy import cli
from seoboy.application import runner
from seoboy.crawl.crawler import Crawler, create_run
from seoboy.infrastructure.database import connect, migrate_database

from tests.support import FixtureSite, html, make_config


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = cli.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_migrate_and_overwrite(self):
        config_path = self.directory / "seoboy.yaml"
        code, output, error = run_cli(
            ["init", "--url", "https://example.de/", "--config", str(config_path)]
        )
        self.assertEqual(code, 0, error)
        self.assertTrue(config_path.is_file())
        self.assertIn("Projektkonfiguration angelegt", output)
        code, _, error = run_cli(
            ["init", "--url", "https://example.de/", "--config", str(config_path)]
        )
        self.assertEqual(code, 2)
        self.assertIn("existiert bereits", error)
        code, output, error = run_cli(["migrate", "--config", str(config_path)])
        self.assertEqual(code, 0, error)
        self.assertIn("SQLite-Schema 1", output)
        self.assertTrue((self.directory / "data" / "seoboy.db").is_file())

    def test_run_inspect_report_and_diff(self):
        with FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html("/", "Start", "<a href='/noindex/'>Noindex</a><a href='/b/'>B</a>")
            site.add("/noindex/", body=html("Noindex"), headers={"X-Robots-Tag": "noindex"})
            site.add_html("/b/", "Seite B", description="B")
            config = make_config(self.directory, site.base)
            code, output, error = run_cli(["run", "--config", str(config.config_path)])
            self.assertEqual(code, 0, error)
            self.assertIn("Berichte:", output)
            connection = connect(config.database)
            try:
                run_id = connection.execute("SELECT run_id FROM runs").fetchone()[0]
            finally:
                connection.close()
            code, output, error = run_cli(
                ["inspect", site.url("/noindex/"), "--config", str(config.config_path)]
            )
            self.assertEqual(code, 0, error)
            self.assertIn("Einzel-URL-Prüfung", output)
            code, output, error = run_cli(
                ["report", "--run", run_id, "--config", str(config.config_path)]
            )
            self.assertEqual(code, 0, error)
            self.assertIn("Berichte geschrieben", output)
            second = runner.run_project(config)
            code, output, error = run_cli(
                [
                    "diff",
                    "--base", run_id,
                    "--target", second.run_id,
                    "--config", str(config.config_path),
                ]
            )
            self.assertEqual(code, 0, error)
            self.assertIn("Vergleich geschrieben", output)
            code, output, error = run_cli(
                ["diff", "--base", "fehlt", "--target", second.run_id, "--config", str(config.config_path)]
            )
            self.assertEqual(code, 2)
            self.assertIn("fehlt", error)

    def test_gsc_prepare_command(self):
        export = self.directory / "export.csv"
        export.write_text(
            "Top-Seiten;Klicks;Impressionen;Durchschnittliche Position\n"
            "https://example.de/;1.234;5.678;4,2\n",
            encoding="utf-8",
        )
        code, output, error = run_cli(
            [
                "gsc-prepare",
                "--input", str(export),
                "--out", str(self.directory / "out"),
                "--property", "sc-domain:example.de",
                "--start", "2026-11-01",
                "--end", "2026-11-30",
            ]
        )
        self.assertEqual(code, 0, error)
        self.assertIn("Normalisierte CSV geschrieben", output)
        self.assertIn("Manifest aktualisiert", output)
        self.assertTrue((self.directory / "out" / "manifest.json").is_file())

    def test_resume_with_changed_config_exits_2(self):
        with FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html("/", "Start", "<a href='/a/'>A</a>")
            site.add_html("/a/", "A")
            config = make_config(self.directory, site.base)
            migrate_database(config.database)
            connection = connect(config.database)
            try:
                run_id = create_run(
                    connection, config, mode="crawl", inputs={},
                    initial_urls=[config.start_url],
                )
                Crawler(connection, config, run_id, runtime_seconds=0.001).crawl()
            finally:
                connection.close()
            changed = make_config(
                self.directory, site.base,
                crawl={"max_urls": 5}, file_name="changed.yaml",
            )
            code, output, error = run_cli(
                ["run", "--resume", run_id, "--config", str(changed.config_path)]
            )
            self.assertEqual(code, 2)
            self.assertIn(run_id, error)

    def test_unknown_config_exits_2(self):
        code, output, error = run_cli(["migrate", "--config", str(self.directory / "fehlt.yaml")])
        self.assertEqual(code, 2)
        self.assertIn("SeoBoy:", error)


if __name__ == "__main__":
    unittest.main()
