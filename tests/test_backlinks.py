from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from seoboy.application import runner
from seoboy.backlinks.importer import import_backlinks
from seoboy.backlinks.report import write_backlink_report
from seoboy.infrastructure.database import connect, migrate_database

from tests.support import FixtureSite, make_config


FIELDS = (
    "source_url",
    "target_url",
    "dataset_source",
    "snapshot_id",
    "observed_at",
    "anchor_text",
    "rel",
    "first_seen_by_provider",
    "last_seen_by_provider",
    "entity_role",
    "review_state",
    "review_note",
)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(FIELDS))
        writer.writeheader()
        writer.writerows(rows)


class BacklinkTests(unittest.TestCase):
    def test_import_is_idempotent_and_missing_link_is_not_removal(self):
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add_html("/", "Start", "<h1>Start</h1>")
            config = make_config(Path(tmp), site.base)
            first = Path(tmp) / "first.csv"
            write_csv(
                first,
                [
                    {
                        "source_url": "https://source-one.example/a",
                        "target_url": site.url("/kontakt/"),
                        "dataset_source": "export",
                        "snapshot_id": "s1",
                        "observed_at": "2026-11-01T10:00:00Z",
                        "anchor_text": "Partner",
                        "rel": "nofollow",
                        "entity_role": "own",
                        "review_state": "open",
                    },
                    {
                        "source_url": "https://source-two.example/b",
                        "target_url": "https://competitor.example/x",
                        "dataset_source": "export",
                        "snapshot_id": "s1",
                        "observed_at": "2026-11-01T10:00:00Z",
                        "anchor_text": "Empfehlung",
                        "entity_role": "competitor",
                        "review_state": "open",
                    },
                    {
                        "source_url": "https://source-two.example/b",
                        "target_url": "https://competitor.example/y",
                        "dataset_source": "export",
                        "snapshot_id": "s1",
                        "observed_at": "2026-11-01T10:00:00Z",
                        "anchor_text": "Empfehlung",
                        "entity_role": "competitor",
                        "review_state": "open",
                    },
                ],
            )
            second = Path(tmp) / "second.csv"
            write_csv(
                second,
                [
                    {
                        "source_url": "https://source-one.example/a",
                        "target_url": site.url("/kontakt/"),
                        "dataset_source": "export",
                        "snapshot_id": "s2",
                        "observed_at": "2026-11-08T10:00:00Z",
                        "anchor_text": "Partner",
                        "rel": "nofollow",
                        "entity_role": "own",
                        "review_state": "open",
                    }
                ],
            )
            migrate_database(config.database)
            connection = connect(config.database)
            try:
                one = import_backlinks(connection, config, first)
                self.assertEqual(one.observations, 3)
                again = import_backlinks(connection, config, first)
                self.assertEqual(again.observations, 0)
                self.assertEqual(again.skipped, 3)
                import_backlinks(connection, config, second)
                folder = write_backlink_report(connection, config)
                text = (folder / "BACKLINK_OPPORTUNITIES.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("nicht erneut beobachtet", text)
                self.assertIn("source-two.example", text)
                self.assertIn("Regionale Linkchancen", text)
                self.assertTrue(
                    (folder / "raw_data" / "backlink_observations.csv").is_file()
                )
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
