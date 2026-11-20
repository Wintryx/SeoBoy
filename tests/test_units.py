from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from seoboy.config import ConfigError, init_config, load_config
from seoboy.html_extract import link_header_canonicals
from seoboy.database import DatabaseError, connect, migrate_database
from seoboy.robots import GOOGLEBOT, SEOBOY, RobotsFile
from seoboy.urls import (
    InvalidUrl,
    matches_any_path,
    normalize_url,
    relative_url,
    resolve_url,
)
from seoboy.util import excel_safe, format_local, parse_retry_after, parse_utc, stable_json

from tests.support import make_config


class UrlTests(unittest.TestCase):
    def test_normalization_keeps_spelling_and_removes_tracking(self):
        normalized = normalize_url(
            "HTTPS://Example.DE:443/a/B/?utm_source=x&b=2&gclid=1#frag",
            ("utm_*", "gclid"),
        )
        self.assertEqual(normalized.url, "https://example.de/a/B/?b=2")
        self.assertEqual(normalized.path, "/a/B/")
        self.assertEqual(normalized.host, "example.de")
        self.assertEqual(normalized.query, "b=2")

    def test_trailing_slash_and_case_are_distinct(self):
        self.assertNotEqual(
            normalize_url("https://example.de/A").url,
            normalize_url("https://example.de/a/").url,
        )

    def test_empty_path_becomes_root(self):
        self.assertEqual(normalize_url("http://example.de").url, "http://example.de/")

    def test_non_default_port_stays(self):
        self.assertEqual(
            normalize_url("http://example.de:8080/x").url, "http://example.de:8080/x"
        )

    def test_invalid_urls(self):
        for value in (
            "",
            "ftp://example.de/",
            "javascript:alert(1)",
            "http://",
            "http://user:pass@example.de/",
            "http://example.de:0/",
        ):
            with self.subTest(value=value):
                with self.assertRaises(InvalidUrl):
                    normalize_url(value)

    def test_resolve_relative(self):
        self.assertEqual(
            resolve_url("https://example.de/a/b/", "../c d.html"),
            "https://example.de/a/c%20d.html",
        )
        self.assertIsNone(resolve_url("https://example.de/", "#x"))
        self.assertIsNone(resolve_url("https://example.de/", "mailto:a@b.de"))

    def test_path_patterns(self):
        self.assertTrue(matches_any_path("/wp-admin/", ("/wp-admin/**",)))
        self.assertTrue(matches_any_path("/wp-admin/x/y", ("/wp-admin/**",)))
        self.assertFalse(matches_any_path("/wp-admin", ("/wp-admin/**",)))
        self.assertTrue(matches_any_path("/blog/a/x", ("/blog/*/x",)))
        self.assertFalse(matches_any_path("/blog/a/b/x", ("/blog/*/x",)))
        self.assertTrue(matches_any_path("/danke/", ("/danke/",)))

    def test_relative_url(self):
        self.assertEqual(
            relative_url("https://example.de/a/?x=1", ("example.de",)), "/a/?x=1"
        )
        self.assertEqual(
            relative_url("https://other.de/a/", ("example.de",)), "https://other.de/a/"
        )


class RobotsTests(unittest.TestCase):
    TEXT = (
        "User-agent: *\n"
        "Disallow: /\n"
        "Allow: /public/\n"
        "\n"
        "User-agent: Googlebot\n"
        "Disallow: /private/\n"
        "Sitemap: https://example.de/sitemap.xml\n"
    )

    def test_agent_specific_groups(self):
        robots = RobotsFile.parse(self.TEXT)
        self.assertFalse(robots.is_allowed("/", SEOBOY))
        self.assertTrue(robots.is_allowed("/public/a", SEOBOY))
        self.assertFalse(robots.is_allowed("/private/a", GOOGLEBOT))
        self.assertTrue(robots.is_allowed("/public/a", GOOGLEBOT))
        self.assertEqual(robots.sitemaps, ["https://example.de/sitemap.xml"])

    def test_longest_match_and_allow_tie(self):
        robots = RobotsFile.parse(
            "User-agent: *\nDisallow: /abc\nAllow: /abc\nDisallow: /*.pdf$\n"
        )
        self.assertTrue(robots.is_allowed("/abc", SEOBOY))
        self.assertFalse(robots.is_allowed("/download.pdf", SEOBOY))
        self.assertTrue(robots.is_allowed("/download.pdf?x=1", SEOBOY))

    def test_empty_disallow_allows_all(self):
        robots = RobotsFile.parse("User-agent: *\nDisallow:\n")
        self.assertTrue(robots.is_allowed("/anything", SEOBOY))

    def test_no_matching_group_allows(self):
        robots = RobotsFile.parse("User-agent: OtherBot\nDisallow: /\n")
        self.assertTrue(robots.is_allowed("/", SEOBOY))


class LinkHeaderTests(unittest.TestCase):
    def test_canonical_link_header(self):
        values = link_header_canonicals(
            [
                ("Link", '<https://example.de/a/>; rel="canonical"'),
                ("link", '<https://example.de/b/>; rel="next", <https://example.de/c/>; rel="canonical"'),
            ]
        )
        self.assertEqual(
            values,
            ("https://example.de/a/", "https://example.de/c/"),
        )

    def test_ignores_other_relations(self):
        self.assertEqual(
            link_header_canonicals([("Link", '<https://example.de/a/>; rel="next"')]),
            (),
        )


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.config = make_config(
            self.directory,
            "https://example.de",
            profiles=[
                {
                    "path": "/leistungen/**",
                    "page_type": "service",
                    "business_value": "high",
                    "expected_indexable": True,
                },
                {
                    "path": "/leistungen/**",
                    "page_type": "ignored",
                    "business_value": "low",
                    "expected_indexable": False,
                },
            ],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_defaults(self):
        profile = self.config.profile_for("https://example.de/")
        self.assertEqual(profile.business_value, "high")
        self.assertIs(profile.expected_indexable, True)
        self.assertEqual(profile.source, "start_default")

    def test_other_defaults(self):
        profile = self.config.profile_for("https://example.de/unbekannt/")
        self.assertEqual(profile.business_value, "normal")
        self.assertIsNone(profile.expected_indexable)
        self.assertIsNone(profile.page_type)

    def test_first_matching_profile_wins(self):
        profile = self.config.profile_for("https://example.de/leistungen/a/")
        self.assertEqual(profile.page_type, "service")
        self.assertEqual(profile.business_value, "high")
        self.assertIs(profile.expected_indexable, True)
        self.assertEqual(profile.pattern, "/leistungen/**")

    def test_tracking_parameter_does_not_change_profile(self):
        profile = self.config.profile_for("https://example.de/leistungen/a/?utm_source=x")
        self.assertEqual(profile.page_type, "service")

    def test_invalid_business_value(self):
        path = self.directory / "invalid.yaml"
        path.write_text(
            "project_id: x\nstart_url: https://example.de/\n"
            "allowed_hosts: [example.de]\ndatabase: ./x.db\nreports_dir: ./r\n"
            "priority_pages:\n  - path: /a/\n    business_value: wichtig\n",
            encoding="utf-8",
        )
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_unknown_key_rejected(self):
        path = self.directory / "unknown.yaml"
        path.write_text(
            "project_id: x\nstart_url: https://example.de/\n"
            "allowed_hosts: [example.de]\ndatabase: ./x.db\nreports_dir: ./r\n"
            "unbekannt: 1\n",
            encoding="utf-8",
        )
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_exception_expiry(self):
        path = self.directory / "exceptions.yaml"
        expired = (date.today() - timedelta(days=2)).isoformat()
        active = (date.today() + timedelta(days=2)).isoformat()
        path.write_text(
            "project_id: x\nstart_url: https://example.de/\n"
            "allowed_hosts: [example.de]\ndatabase: ./x.db\nreports_dir: ./r\n"
            "rule_exceptions:\n"
            "  - rule_id: INDEX_NOINDEX\n"
            "    path: /danke/\n"
            "    reason: gewollt\n"
            "    expires: " + active + "\n"
            "  - rule_id: INDEX_NOINDEX\n"
            "    url: https://example.de/alt/\n"
            "    reason: alt\n"
            "    expires: " + expired + "\n",
            encoding="utf-8",
        )
        config = load_config(path)
        self.assertTrue(config.rule_exceptions[0].matches(
            "INDEX_NOINDEX", ["https://example.de/danke/"]
        ))
        self.assertFalse(config.rule_exceptions[1].matches(
            "INDEX_NOINDEX", ["https://example.de/alt/"]
        ))

    def test_init_refuses_overwrite(self):
        path = self.directory / "neu.yaml"
        init_config(path, "https://example.de")
        with self.assertRaises(ConfigError):
            init_config(path, "https://example.de")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "nested" / "test.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_migration_and_idempotence(self):
        self.assertEqual(migrate_database(self.path), 1)
        self.assertEqual(migrate_database(self.path), 1)
        connection = connect(self.path)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type = 'table'"
                )
            }
            self.assertIn("rule_results", tables)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            connection.close()

    def test_newer_schema_version_rejected(self):
        migrate_database(self.path)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA user_version = 99")
        connection.commit()
        connection.close()
        with self.assertRaises(DatabaseError):
            migrate_database(self.path)

    def test_foreign_tables_without_version_rejected(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("CREATE TABLE fremd (id INTEGER)")
        connection.commit()
        connection.close()
        with self.assertRaises(DatabaseError):
            migrate_database(self.path)


class UtilTests(unittest.TestCase):
    def test_berlin_time(self):
        self.assertEqual(
            format_local(parse_utc("2026-07-01T12:00:00Z")),
            "01.07.2026 um 14:00 Uhr MESZ",
        )
        self.assertEqual(
            format_local(parse_utc("2026-11-20T03:10:00Z")),
            "20.11.2026 um 04:10 Uhr MEZ",
        )

    def test_excel_safe(self):
        self.assertEqual(excel_safe("=SUM(1,2)"), "'=SUM(1,2)")
        self.assertEqual(excel_safe("-1"), "'-1")
        self.assertEqual(excel_safe("normal"), "normal")
        self.assertEqual(excel_safe(5), 5)

    def test_retry_after(self):
        now = datetime(2026, 11, 20, 3, 0, tzinfo=timezone.utc)
        self.assertEqual(parse_retry_after("120", now), 120)
        self.assertIsNotNone(parse_retry_after("Fri, 20 Nov 2026 03:02:00 GMT", now))
        self.assertIsNone(parse_retry_after("unsinn", now))

    def test_stable_json(self):
        self.assertEqual(stable_json({"b": 1, "a": ["x"]}), '{"a":["x"],"b":1}')


if __name__ == "__main__":
    unittest.main()
