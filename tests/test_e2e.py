from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from seoboy import runner
from seoboy.config import load_config
from seoboy.crawler import Crawler, ResumeError, create_run, validate_resume
from seoboy.database import connect, migrate_database

from tests.support import FixtureSite, html, make_config


def sitemap(base: str, paths: list[str]) -> str:
    body = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
    )
    body += "".join(f"<url><loc>{base}{path}</loc></url>" for path in paths)
    body += "</urlset>"
    return body


def full_site(site: FixtureSite) -> None:
    base = site.base
    site.add(
        "/robots.txt",
        body=f"User-agent: *\nDisallow: /private/\nSitemap: {base}/sitemap.xml\n",
        content_type="text/plain; charset=utf-8",
    )
    site.add(
        "/sitemap.xml",
        body=sitemap(base, ["/", "/a/", "/orphan/", "/missing/", "/redir-target/"]),
        content_type="application/xml; charset=utf-8",
    )
    site.add_html(
        "/",
        "Startseite",
        (
            "<a href='/a/'>A</a>"
            "<a href='/missing/'>Missing</a>"
            "<a href='/missing2/'>Missing2</a>"
            "<a href='/redirect/'>Redirect</a>"
            "<a href='/dupe1/'>Dupe1</a>"
            "<a href='/dupe2/'>Dupe2</a>"
            "<a href='/noindex/'>Noindex</a>"
            "<a href='/canonical/'>Canonical</a>"
            "<a href='/private/'>Private</a>"
            "<a href='/danke/'>Danke</a>"
            "<a href='https://external.example/x'>Extern</a>"
            "<a href='/formula/'>Formel</a>"
        ),
        description="Startseite Beschreibung",
    )
    site.add_html("/a/", "Leistung A", "<a href='/b/'>B</a>", description="Beschreibung A")
    site.add_html("/b/", "Seite B", description="Beschreibung B")
    site.add(
        "/missing/",
        responses=[
            (404, {}, html("Nicht gefunden")),
            (200, {}, html("Repariert", description="Repariert")),
        ],
    )
    site.add("/missing2/", status=410, body=html("Weg"))
    site.add(
        "/redirect/",
        status=302,
        headers={"Location": base + "/redir-target/"},
        body="",
        content_type="text/html",
    )
    site.add_html("/redir-target/", "Redirect Ziel", description="Redirect Ziel")
    site.add_html("/dupe1/", "Gleicher Titel", description="Gleiche Beschreibung")
    site.add_html("/dupe2/", "Gleicher Titel", description="Gleiche Beschreibung")
    site.add(
        "/noindex/",
        body=html("Noindex Seite", description="Noindex"),
        headers={"X-Robots-Tag": "noindex"},
    )
    site.add_html(
        "/canonical/",
        "Canonical Seite",
        description="Canonical Beschreibung",
        canonical=base + "/a/",
    )
    site.add_html("/private/", "Privat", description="Privat")
    site.add("/danke/", body=html("Danke", robots="noindex", description="Danke"))
    site.add_html("/orphan/", "Waise", description="Waise Beschreibung")
    site.add_html("/formula/", "=SUM(1;2)", description="=1+1")


def gsc_directory(directory: Path, base: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "property": "sc-domain:example.de",
        "search_type": "web",
        "country": None,
        "device": None,
        "periods": [
            {
                "start": "2026-09-01",
                "end": "2026-09-30",
                "pages": "2026-09_pages.csv",
                "page_queries": "2026-09_queries.csv",
            },
            {
                "start": "2026-10-01",
                "end": "2026-10-30",
                "source_format": "gsc_ui_csv",
                "pages": "2026-10_pages.csv",
                "page_queries": "2026-10_queries.csv",
            },
        ],
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def write(name: str, header: str, rows: list[tuple]) -> None:
        body = "".join(",".join(str(value) for value in row) + "\n" for row in rows)
        (directory / name).write_text(header + "\n" + body, encoding="utf-8")

    write(
        "2026-09_pages.csv",
        "page,clicks,impressions,position",
        [
            (base + "/", 50, 500, 8.0),
            (base + "/a/", 10, 100, 6.0),
            (base + "/gsc-only/", 0, 10, 30.0),
        ],
    )
    write(
        "2026-10_pages.csv",
        "page,clicks,impressions,position",
        [
            (base + "/", 20, 500, 8.2),
            (base + "/a/", 5, 100, 7.0),
            (base + "/gsc-only/", 0, 5, 0),
        ],
    )
    write(
        "2026-09_queries.csv",
        "page,query,clicks,impressions,position",
        [
            (base + "/", "seo", 50, 500, 8.0),
            (base + "/a/", "seo", 10, 100, 6.0),
            (base + "/", "audit", 5, 100, 15.0),
        ],
    )
    write(
        "2026-10_queries.csv",
        "page,query,clicks,impressions,position",
        [
            (base + "/", "seo", 20, 500, 8.2),
            (base + "/a/", "seo", 50, 100, 6.2),
            (base + "/", "audit", 4, 100, 15.5),
        ],
    )


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_run_reports_and_rules(self):
        with FixtureSite() as site:
            full_site(site)
            config = make_config(
                self.directory,
                site.base,
                profiles=[
                    {"path": "/a/", "page_type": "service", "business_value": "high", "expected_indexable": True},
                    {"path": "/private/", "page_type": "service", "business_value": "high", "expected_indexable": True},
                    {"path": "/canonical/", "page_type": "service", "business_value": "high", "expected_indexable": True},
                    {"path": "/danke/", "page_type": "utility", "business_value": "low", "expected_indexable": False},
                ],
            )
            directory = self.directory / "gsc"
            gsc_directory(directory, site.base)
            outcome = runner.run_project(config, directory)
            self.assertEqual(outcome.status, "completed")
            self.assertEqual(outcome.exit_code, 0)
            self.assertIsNotNone(outcome.report_dir)
            report = outcome.report_dir
            for name in (
                "00_EXECUTIVE_SUMMARY.md",
                "01_ACTION_PLAN_PRIORITIZED.md",
                "02_TECHNICAL_SEO_AUDIT.md",
                "manifest.json",
                "raw_data/all_urls.csv",
                "raw_data/rule_results.csv",
                "raw_data/broken_links.csv",
                "raw_data/gsc_metrics.csv",
            ):
                self.assertTrue((report / name).is_file(), name)
            self.assertTrue((report / "raw_data" / "all_urls.csv").read_bytes().startswith(b"\xef\xbb\xbf"))
            connection = connect(config.database)
            try:
                run = dict(connection.execute("SELECT * FROM runs").fetchone())
                self.assertEqual(run["status"], "completed")
                self.assertIsNotNone(run["ended_at"])
                self.assertIsNone(run["stop_reason"])
                findings = {
                    (row["rule_id"], row["subject_key"])
                    for row in connection.execute(
                        "SELECT rule_id, subject_key FROM rule_results WHERE outcome = 'finding'"
                    )
                }
                rules = {rule for rule, _ in findings}
                self.assertIn("INDEX_ROBOTS_BLOCKED", rules)
                self.assertIn("INDEX_NOINDEX", rules)
                self.assertIn("HTTP_UNAVAILABLE", rules)
                self.assertIn("LINK_BROKEN", rules)
                self.assertIn("SITEMAP_TARGET", rules)
                self.assertIn("META_TITLE", rules)
                self.assertIn("GSC_NEAR_TOP", rules)
                self.assertIn("GSC_MULTI_URL", rules)
                # Danke-Seite ist ausdrücklich nicht indexierbar.
                danke = connection.execute(
                    "SELECT outcome FROM rule_results WHERE rule_id = 'INDEX_NOINDEX' "
                    "AND subject_key LIKE ?", ('%' + site.url("/danke/") + '%',)
                ).fetchone()
                self.assertEqual(danke["outcome"], "not_applicable")
                actions = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT priority, action_key, title FROM actions ORDER BY priority, action_key"
                    )
                ]
                self.assertEqual(actions[0]["priority"], 1)
                self.assertIn("Googlebot", actions[0]["title"])
                self.assertTrue(any(row["priority"] == 2 for row in actions))
                self.assertLessEqual(
                    [row["priority"] for row in actions], sorted(row["priority"] for row in actions)
                )
                # Formel-Schutz nur im Export
                title = connection.execute(
                    "SELECT title FROM page_observations WHERE title LIKE '=SUM%'"
                ).fetchone()[0]
                self.assertEqual(title, "=SUM(1;2)")
                csv_text = (report / "raw_data" / "all_urls.csv").read_text(encoding="utf-8-sig")
                self.assertIn("'=SUM(1;2)", csv_text)
                manifest = json.loads((report / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["status"], "completed")
                self.assertEqual(manifest["run_id"], outcome.run_id)
                self.assertNotIn("password", json.dumps(manifest).lower())
                summary = (report / "00_EXECUTIVE_SUMMARY.md").read_text(encoding="utf-8")
                self.assertIn("Googlebot", summary)
                plan = (report / "01_ACTION_PLAN_PRIORITIZED.md").read_text(encoding="utf-8")
                self.assertIn("Regel und ID", plan)
                self.assertIn("Erneut prüfen", plan)
                technical = (report / "02_TECHNICAL_SEO_AUDIT.md").read_text(encoding="utf-8")
                self.assertIn("Abdeckung je Regel", technical)
                self.assertIn("Ungeprüfte Fälle je Grund", technical)
            finally:
                connection.close()

    def test_url_limit_creates_partial_run(self):
        with FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            links = "".join(f"<a href='/p{i}/'>P{i}</a>" for i in range(10))
            site.add_html("/", "Start", links)
            for index in range(10):
                site.add_html(f"/p{index}/", f"Seite {index}")
            config = make_config(self.directory, site.base, crawl={"max_urls": 3})
            outcome = runner.run_project(config)
            self.assertEqual(outcome.status, "partial")
            self.assertEqual(outcome.exit_code, 1)
            connection = connect(config.database)
            try:
                run = dict(connection.execute("SELECT * FROM runs").fetchone())
                self.assertEqual(run["status"], "partial")
                self.assertEqual(run["stop_reason"], "url_limit_reached")
                self.assertIsNotNone(run["ended_at"])
                admitted = connection.execute(
                    "SELECT COUNT(*) FROM run_urls WHERE admitted_at IS NOT NULL"
                ).fetchone()[0]
                self.assertEqual(admitted, 3)
                deferred = connection.execute(
                    "SELECT COUNT(*) FROM run_urls WHERE state = 'deferred'"
                ).fetchone()[0]
                self.assertGreater(deferred, 0)
            finally:
                connection.close()
            self.assertTrue((outcome.report_dir / "manifest.json").is_file())
            manifest = json.loads((outcome.report_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "partial")
            self.assertEqual(manifest["stop_reason"], "url_limit_reached")

    def test_request_limit_creates_partial_run(self):
        with FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html("/", "Start")
            config = make_config(self.directory, site.base, crawl={"max_requests": 2})
            outcome = runner.run_project(config)
            self.assertEqual(outcome.status, "partial")
            connection = connect(config.database)
            try:
                run = dict(connection.execute("SELECT * FROM runs").fetchone())
                self.assertEqual(run["stop_reason"], "request_limit_reached")
                attempts = connection.execute("SELECT COUNT(*) FROM http_attempts").fetchone()[0]
                self.assertLessEqual(attempts, 2)
            finally:
                connection.close()

    def test_exact_request_budget_can_complete(self):
        with FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html("/", "Start")
            config = make_config(self.directory, site.base, crawl={"max_requests": 3})
            outcome = runner.run_project(config)
            self.assertEqual(outcome.status, "completed")
            connection = connect(config.database)
            try:
                run = dict(connection.execute("SELECT * FROM runs").fetchone())
                self.assertEqual(run["status"], "completed")
                attempts = connection.execute("SELECT COUNT(*) FROM http_attempts").fetchone()[0]
                self.assertEqual(attempts, 3)
            finally:
                connection.close()

    def test_retry_then_success(self):
        with FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html("/", "Start", "<a href='/flaky/'>Flaky</a>")
            site.add(
                "/flaky/",
                responses=[
                    (500, {}, html("Fehler")),
                    (500, {}, html("Fehler")),
                    (200, {}, html("Endlich", description="ok")),
                ],
            )
            config = make_config(self.directory, site.base)
            outcome = runner.run_project(config)
            self.assertEqual(outcome.status, "completed")
            connection = connect(config.database)
            try:
                attempts = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT a.attempt_no, a.state, a.status_code FROM http_attempts a "
                        "JOIN crawl_jobs j ON j.job_id = a.job_id "
                        "WHERE j.url_id = (SELECT url_id FROM urls WHERE normalized_url = ?) "
                        "ORDER BY attempt_no",
                        (site.url("/flaky/"),),
                    )
                ]
                self.assertEqual([row["status_code"] for row in attempts], [500, 500, 200])
                self.assertEqual([row["attempt_no"] for row in attempts], [1, 2, 3])
                outcome_row = connection.execute(
                    "SELECT outcome FROM rule_results WHERE rule_id = 'HTTP_UNAVAILABLE' "
                    "AND subject_key = ?",
                    (json.dumps(["url", site.url("/flaky/")], separators=(",", ":")),),
                ).fetchone()
                self.assertEqual(outcome_row["outcome"], "pass")
            finally:
                connection.close()

    def test_redirect_loop_and_chain(self):
        with FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html(
                "/", "Start",
                "<a href='/loop-a/'>Loop</a><a href='/r1/'>Kette</a>",
            )
            site.add("/loop-a/", status=302, headers={"Location": site.url("/loop-b/")}, body="")
            site.add("/loop-b/", status=302, headers={"Location": site.url("/loop-a/")}, body="")
            site.add("/r1/", status=302, headers={"Location": site.url("/r2/")}, body="")
            site.add("/r2/", status=302, headers={"Location": site.url("/r3/")}, body="")
            site.add("/r3/", status=302, headers={"Location": site.url("/r4/")}, body="")
            site.add_html("/r4/", "Kette Ende")
            config = make_config(self.directory, site.base, crawl={"max_redirects": 10})
            outcome = runner.run_project(config)
            self.assertEqual(outcome.status, "completed")
            connection = connect(config.database)
            try:
                rows = {
                    row["subject_key"]: row["outcome"]
                    for row in connection.execute(
                        "SELECT subject_key, outcome FROM rule_results WHERE rule_id = 'HTTP_REDIRECT'"
                    )
                }
                self.assertEqual(rows[json.dumps(["url", site.url("/loop-a/")], separators=(",", ":"))], "finding")
                self.assertEqual(rows[json.dumps(["url", site.url("/r1/")], separators=(",", ":"))], "finding")
                self.assertEqual(rows[json.dumps(["url", site.url("/r2/")], separators=(",", ":"))], "pass")
                self.assertEqual(rows[json.dumps(["url", site.url("/r4/")], separators=(",", ":"))], "pass")
                findings = connection.execute(
                    "SELECT COUNT(*) FROM rule_results WHERE rule_id = 'HTTP_REDIRECT' AND outcome = 'finding'"
                ).fetchone()[0]
                self.assertGreaterEqual(findings, 1)
            finally:
                connection.close()

    def test_robots_googlebot_specific(self):
        with FixtureSite() as site:
            site.add(
                "/robots.txt",
                body=(
                    "User-agent: *\nAllow: /\nDisallow: /blocked/\n\n"
                    "User-agent: Googlebot\nDisallow: /g/\n"
                ),
                content_type="text/plain",
            )
            site.add_html(
                "/", "Start",
                "<a href='/blocked/'>Blocked</a><a href='/g/'>Googlebot</a>",
            )
            site.add_html("/blocked/", "Blocked")
            site.add_html("/g/", "Googlebot")
            config = make_config(
                self.directory,
                site.base,
                profiles=[
                    {"path": "/blocked/", "business_value": "high", "expected_indexable": True},
                    {"path": "/g/", "business_value": "high", "expected_indexable": True},
                ],
            )
            runner.run_project(config)
            connection = connect(config.database)
            try:
                blocked = connection.execute(
                    "SELECT state, reason_code FROM run_urls WHERE url_id = "
                    "(SELECT url_id FROM urls WHERE normalized_url = ?)",
                    (site.url("/blocked/"),),
                ).fetchone()
                self.assertEqual(blocked["state"], "blocked")
                self.assertEqual(blocked["reason_code"], "robots_disallowed")
                g_state = connection.execute(
                    "SELECT state FROM run_urls WHERE url_id = "
                    "(SELECT url_id FROM urls WHERE normalized_url = ?)",
                    (site.url("/g/"),),
                ).fetchone()
                self.assertEqual(g_state["state"], "finished")
                findings = connection.execute(
                    "SELECT severity FROM rule_results WHERE rule_id = 'INDEX_ROBOTS_BLOCKED' "
                    "AND subject_key = ?",
                    (json.dumps(["url", site.url("/g/")], separators=(",", ":")),),
                ).fetchone()
                self.assertEqual(findings["severity"], "critical")
            finally:
                connection.close()

    def test_resume_after_pause_and_config_mismatch(self):
        with FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            links = "".join(f"<a href='/p{i}/'>P{i}</a>" for i in range(30))
            site.add_html("/", "Start", links)
            for index in range(30):
                site.add_html(f"/p{index}/", f"Seite {index}")
            config = make_config(self.directory, site.base, crawl={"max_runtime_seconds": 30})
            migrate_database(config.database)
            connection = connect(config.database)
            try:
                run_id = create_run(
                    connection,
                    config,
                    mode="crawl",
                    inputs={"mode": "test"},
                    initial_urls=[config.start_url],
                )
                crawler = Crawler(connection, config, run_id, runtime_seconds=0.05)
                paused = crawler.crawl()
                self.assertEqual(paused.status, "paused")
                row = dict(connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone())
                self.assertEqual(row["status"], "paused")
                self.assertIsNone(row["ended_at"])
            finally:
                connection.close()
            resumed = runner.resume_project(config, run_id)
            self.assertEqual(resumed.status, "completed")
            connection = connect(config.database)
            try:
                row = dict(connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone())
                self.assertEqual(row["status"], "completed")
                reserved = connection.execute(
                    "SELECT COUNT(*) FROM http_attempts WHERE state = 'reserved'"
                ).fetchone()[0]
                self.assertEqual(reserved, 0)
            finally:
                connection.close()

            # Konfigurationswechsel macht den Lauf nicht fortsetzbar.
            with FixtureSite() as other:
                other.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
                other.add_html("/", "Andere")
                config2 = make_config(
                    self.directory, other.base, crawl={"max_runtime_seconds": 30}
                )
                migrate_database(config2.database)
                connection = connect(config2.database)
                try:
                    other_run = create_run(
                        connection, config2, mode="crawl", inputs={},
                        initial_urls=[config2.start_url],
                    )
                    Crawler(connection, config2, other_run, runtime_seconds=0.01).crawl()
                finally:
                    connection.close()
                changed = make_config(
                    self.directory, other.base,
                    crawl={"max_runtime_seconds": 30, "max_urls": 5},
                    file_name="changed.yaml",
                )
                connection = connect(changed.database)
                try:
                    with self.assertRaises(ResumeError) as context:
                        validate_resume(connection, changed, other_run)
                    self.assertIn(other_run, str(context.exception))
                finally:
                    connection.close()

    def test_diff_states(self):
        with FixtureSite() as site:
            site.add(
                "/robots.txt",
                body=f"User-agent: *\nDisallow: /private/\nSitemap: {site.base}/sitemap.xml\n",
                content_type="text/plain",
            )
            site.add(
                "/sitemap.xml",
                body=sitemap(site.base, ["/", "/missing/", "/orphan/"]),
                content_type="application/xml",
            )
            home_without = (
                "<a href='/missing/'>Missing</a><a href='/missing2/'>Missing2</a>"
                "<a href='/private/'>Private</a>"
            )
            home_with = home_without + "<a href='/orphan/'>Waise</a>"
            site.add_html("/", "Start", home_without)
            site.add("/missing/", responses=[
                (404, {}, html("Nicht gefunden")),
                (200, {}, html("Repariert", description="Repariert")),
            ])
            site.add("/missing2/", status=410, body=html("Weg"))
            site.add_html("/private/", "Privat")
            site.add_html("/orphan/", "Waise")
            config = make_config(self.directory, site.base)
            first = runner.run_project(config)
            site.add_html("/", "Start", home_with)
            second = runner.run_project(config)
            diff_dir = runner.compare_runs(config, first.run_id, second.run_id)
            self.assertTrue((diff_dir / "05_AUDIT_DIFF.md").is_file())
            csv_text = (diff_dir / "raw_data" / "audit_diff.csv").read_text(encoding="utf-8-sig")
            self.assertIn("Behoben", csv_text)
            self.assertIn("Fortbestehend", csv_text)
            self.assertIn(site.url("/missing/"), csv_text)
            self.assertIn(site.url("/orphan/"), csv_text)
            markdown = (diff_dir / "05_AUDIT_DIFF.md").read_text(encoding="utf-8")
            self.assertIn("## Behobene Befunde", markdown)
            self.assertIn("## Fortbestehende Befunde", markdown)

    def test_inspect_single_url(self):
        with FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add("/noindex/", body=html("Noindex", description="Noindex"), headers={"X-Robots-Tag": "noindex"})
            site.add_html("/", "Start")
            config = make_config(self.directory, site.base)
            outcome = runner.inspect_url(config, site.url("/noindex/"))
            self.assertEqual(outcome.status, "completed")
            self.assertNotIn("/sitemap.xml", site.requests)
            self.assertEqual(site.requests["/noindex/"], 1)
            connection = connect(config.database)
            try:
                run = dict(connection.execute("SELECT * FROM runs").fetchone())
                self.assertEqual(run["mode"], "inspect")
                self.assertEqual(run["max_urls"], 1)
                outcomes = {
                    (row["rule_id"], row["outcome"])
                    for row in connection.execute("SELECT rule_id, outcome FROM rule_results")
                }
                self.assertIn(("INDEX_NOINDEX", "finding"), outcomes)
                self.assertIn(("LINK_BROKEN", "not_checked"), outcomes)
            finally:
                connection.close()
            self.assertIsNotNone(outcome.report_dir)

    def test_canonical_from_http_header(self):
        with FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html(
                "/", "Start",
                "<a href='/header/'>Header</a><a href='/conflict/'>Konflikt</a>"
                "<a href='/a/'>A</a><a href='/b/'>B</a>",
            )
            site.add("/header/", body=html("Header"), headers={"Link": f"<{site.base}/a/>; rel=\"canonical\""})
            site.add(
                "/conflict/",
                body=html("Konflikt", canonical=site.url("/a/")),
                headers={"Link": f"<{site.base}/b/>; rel=\"canonical\""},
            )
            site.add_html("/a/", "A", description="A")
            site.add_html("/b/", "B", description="B")
            config = make_config(
                self.directory,
                site.base,
                profiles=[
                    {"path": "/header/", "page_type": "service", "business_value": "high", "expected_indexable": True},
                    {"path": "/conflict/", "page_type": "service", "business_value": "high", "expected_indexable": True},
                ],
            )
            runner.run_project(config)
            connection = connect(config.database)
            try:
                header = connection.execute(
                    "SELECT outcome, severity FROM rule_results WHERE rule_id = 'CANONICAL_TARGET' "
                    "AND subject_key = ?",
                    (json.dumps(["url", site.url("/header/")], separators=(",", ":")),),
                ).fetchone()
                self.assertEqual(header["outcome"], "finding")
                self.assertEqual(header["severity"], "low")
                conflict = connection.execute(
                    "SELECT outcome, severity FROM rule_results WHERE rule_id = 'CANONICAL_TARGET' "
                    "AND subject_key = ?",
                    (json.dumps(["url", site.url("/conflict/")], separators=(",", ":")),),
                ).fetchone()
                self.assertEqual(conflict["outcome"], "finding")
                self.assertEqual(conflict["severity"], "medium")
            finally:
                connection.close()

    def test_rule_exception_suppresses_action(self):
        with FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html("/", "Start", "<a href='/noindex/'>Noindex</a>")
            site.add("/noindex/", body=html("Noindex"), headers={"X-Robots-Tag": "noindex"})
            config = make_config(
                self.directory,
                site.base,
                exceptions=[
                    {"rule_id": "INDEX_NOINDEX", "path": "/noindex/", "reason": "bewusst ausgeschlossen"}
                ],
            )
            runner.run_project(config)
            connection = connect(config.database)
            try:
                row = dict(connection.execute(
                    "SELECT outcome, exception_json FROM rule_results WHERE rule_id = 'INDEX_NOINDEX' "
                    "AND subject_key LIKE ?",
                    ('%' + site.url("/noindex/") + '%',),
                ).fetchone())
                self.assertEqual(row["outcome"], "finding")
                self.assertIn("bewusst", row["exception_json"])
                actions = [
                    item["rule_id"]
                    for item in connection.execute(
                        "SELECT rule_id FROM action_findings"
                    )
                ]
                self.assertNotIn("INDEX_NOINDEX", actions)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
