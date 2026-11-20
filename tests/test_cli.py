from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import date
import io
from pathlib import Path
import tempfile
import unittest

from seoboy import cli
from seoboy.application import runner
from seoboy.benchmark.sampler import collect_snapshot
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

    def test_batch_runs_two_projects(self):
        with FixtureSite() as site_a, FixtureSite() as site_b:
            for site, label in ((site_a, "A"), (site_b, "B")):
                site.add(
                    "/robots.txt",
                    body="User-agent: *\nAllow: /\n",
                    content_type="text/plain",
                )
                site.add_html("/", f"Start {label}")
            dir_a = self.directory / "a"
            dir_b = self.directory / "b"
            dir_a.mkdir()
            dir_b.mkdir()
            config_a = make_config(dir_a, site_a.base, project_id="batch-a")
            config_b = make_config(dir_b, site_b.base, project_id="batch-b")
            code, output, error = run_cli(
                [
                    "batch",
                    "--config", str(config_a.config_path),
                    "--config", str(config_b.config_path),
                    "--workers", "2",
                ]
            )
            self.assertEqual(code, 0, error)
            self.assertIn("[batch-a]", output)
            self.assertIn("[batch-b]", output)
            for config in (config_a, config_b):
                connection = connect(config.database)
                try:
                    status = connection.execute("SELECT status FROM runs").fetchone()[0]
                    self.assertEqual(status, "completed")
                finally:
                    connection.close()

    def test_batch_rejects_shared_database(self):
        config_a = make_config(self.directory, "https://example.de/", project_id="a")
        config_b = make_config(
            self.directory, "https://example.de/", project_id="b", file_name="b.yaml"
        )
        with self.assertRaises(runner.RunnerError):
            runner.run_projects([config_a, config_b])

    def test_batch_rejects_shared_host(self):
        dir_a = self.directory / "a"
        dir_b = self.directory / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        config_a = make_config(dir_a, "https://example.de/", project_id="a")
        config_b = make_config(dir_b, "https://example.de/", project_id="b")
        with self.assertRaises(runner.RunnerError):
            runner.run_projects([config_a, config_b])

    def test_benchmark_compares_latest_run_with_competitor(self):
        with FixtureSite() as own, FixtureSite() as competitor:
            own.add(
                "/robots.txt",
                body="User-agent: *\nAllow: /\n",
                content_type="text/plain",
            )
            own.add_html("/", "Start", "<a href='/a/'>A</a>")
            own.add_html(
                "/a/", "Seite A", "<h1>Seite A</h1><p>" + ("Inhalt " * 60) + "</p>"
            )
            config = make_config(self.directory, own.base)
            runner.run_project(config)

            competitor.add(
                "/robots.txt",
                body=(
                    "User-agent: *\nAllow: /\n"
                    f"Sitemap: {competitor.base}/sitemap.xml\n"
                ),
                content_type="text/plain",
            )
            sitemap = (
                "<?xml version='1.0' encoding='UTF-8'?>"
                "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
                f"<url><loc>{competitor.base}/</loc></url>"
                f"<url><loc>{competitor.base}/b/</loc></url>"
                "</urlset>"
            )
            competitor.add("/sitemap.xml", body=sitemap, content_type="application/xml")
            competitor.add_html(
                "/", "Wettbewerb", "<h1>Wettbewerb</h1><p>" + ("Text " * 40) + "</p>"
            )
            competitor.add_html(
                "/b/", "Seite B", "<h1>Seite B</h1><p>" + ("Mehr " * 20) + "</p>"
            )

            folder = runner.run_benchmark(
                config, [competitor.base], max_pages=5, out=self.directory / "benchmark"
            )
            report = (folder / "04_COMPETITOR_BENCHMARK.md").read_text(encoding="utf-8")
            self.assertIn("Wettbewerbsvergleich", report)
            self.assertIn("127.0.0.1", report)
            self.assertIn("HTML-Seiten ausgewertet", report)
            self.assertTrue((folder / "raw_data" / "benchmark_pages.csv").is_file())
            self.assertTrue((folder / "manifest.json").is_file())

    def test_benchmark_respects_competitor_robots(self):
        with FixtureSite() as site:
            site.add(
                "/robots.txt",
                body="User-agent: *\nDisallow: /\n",
                content_type="text/plain",
            )
            site.add_html("/", "Start")
            snapshot = collect_snapshot(
                site.base, "robots", max_pages=2, interval_seconds=0
            )
            self.assertEqual(snapshot.error, "robots_disallowed")
            self.assertEqual(site.requests["/"], 0)

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
