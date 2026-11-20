from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from seoboy.infrastructure.database import connect, migrate_database
from seoboy.rankings.config import KeywordConfigError, load_keywords
from seoboy.rankings.importer import RankingImportError, import_rankings
from seoboy.rankings.report import write_rankings_report

from tests.support import FixtureSite, make_config


KEYWORDS = """keywords:
  - id: wedding-koeln
    query: Hochzeits-DJ Köln
    intent: booking
    market: DE
    language: de
    location_key: koeln
    device: desktop
    result_type: organic
    expected_target: /kontakt/
    target_active: true
    business_value: high
"""


def snapshot(snapshot_id: str, status: str = "ok") -> str:
    return (
        "snapshot_id,keyword_id,observed_at,source,engine,market,language,"
        "location_key,device,result_type,depth,status\n"
        f"{snapshot_id},wedding-koeln,2026-11-20T10:00:00Z,test,google,DE,de,"
        f"koeln,desktop,organic,10,{status}\n"
    )


class RankingTests(unittest.TestCase):
    def test_import_is_idempotent_and_reports_target_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add_html("/", "Start", "<h1>Start</h1>")
            config = make_config(Path(tmp), site.base)
            keywords = Path(tmp) / "keywords.yaml"
            keywords.write_text(KEYWORDS, encoding="utf-8")
            profiles = load_keywords(keywords)
            headers = Path(tmp) / "headers.csv"
            results = Path(tmp) / "results.csv"
            headers.write_text(snapshot("s1"), encoding="utf-8")
            results.write_text(
                "snapshot_id,position,url,profile_id,domain,title\n"
                f"s1,4,{site.url('/blog/')},,example.de,Blog\n",
                encoding="utf-8",
            )
            migrate_database(config.database)
            connection = connect(config.database)
            try:
                first = import_rankings(
                    connection, config, profiles, headers, results
                )
                self.assertEqual(first.snapshots, 1)
                second = import_rankings(
                    connection, config, profiles, headers, results
                )
                self.assertEqual(second.snapshots, 0)
                self.assertEqual(second.snapshots_skipped, 1)
                folder = write_rankings_report(connection, config)
                text = (folder / "rankings_overview.md").read_text(encoding="utf-8")
                self.assertIn("/kontakt/", text)
                self.assertIn("/blog/", text)
                self.assertIn("Position 4", text)
                self.assertIn("Soll-/Ist-Abweichungen", text)
            finally:
                connection.close()

    def test_no_match_is_not_position_11_and_conflict_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add_html("/", "Start", "<h1>Start</h1>")
            config = make_config(Path(tmp), site.base)
            keywords = Path(tmp) / "keywords.yaml"
            keywords.write_text(KEYWORDS, encoding="utf-8")
            profiles = load_keywords(keywords)
            headers = Path(tmp) / "headers.csv"
            headers.write_text(snapshot("s1", "no_match"), encoding="utf-8")
            migrate_database(config.database)
            connection = connect(config.database)
            try:
                import_rankings(connection, config, profiles, headers)
                folder = write_rankings_report(connection, config)
                text = (folder / "rankings_overview.md").read_text(encoding="utf-8")
                self.assertIn("außerhalb Top 10", text)
                self.assertNotIn("| Position 11 |", text)

                conflict = Path(tmp) / "conflict.csv"
                conflict.write_text(snapshot("s1", "ok"), encoding="utf-8")
                with self.assertRaises(RankingImportError):
                    import_rankings(connection, config, profiles, conflict)
            finally:
                connection.close()

    def test_invalid_keyword_result_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keywords.yaml"
            path.write_text(
                "keywords:\n  - id: x\n    query: Test\n    result_type: paid\n",
                encoding="utf-8",
            )
            with self.assertRaises(KeywordConfigError):
                load_keywords(path)


if __name__ == "__main__":
    unittest.main()
