from __future__ import annotations

from datetime import date
from pathlib import Path
import json
import tempfile
import unittest

from seoboy import gsc as gsc_module
from seoboy.audit_data import RunData
from seoboy.config import load_config
from seoboy.crawler import create_run
from seoboy.database import connect, migrate_database
from seoboy.registry import UrlRegistry
from seoboy.rules_gsc import evaluate_gsc

from tests.support import make_config


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_german_export_is_normalized(self):
        export = self.directory / "export.csv"
        export.write_text(
            "Top-Seiten;Klicks;Impressionen;Durchschnittliche Position\n"
            "https://example.de/;1.234;5.678;4,2\n"
            "https://example.de/a/;12;340;\n",
            encoding="utf-8",
        )
        summary = gsc_module.prepare_export(
            export,
            self.directory / "out",
            property_name="sc-domain:example.de",
            start=date(2026, 11, 1),
            end=date(2026, 11, 30),
        )
        self.assertEqual(summary["rows"], 2)
        self.assertEqual(summary["delimiter"], ";")
        self.assertEqual(summary["decimal"], ",")
        self.assertEqual(summary["unknown_positions"], 1)
        output = Path(summary["file"]).read_text(encoding="utf-8")
        self.assertIn("page,clicks,impressions,position", output)
        self.assertIn("https://example.de/,1234,5678,4.2", output)
        self.assertIn("https://example.de/a/,12,340,", output)
        manifest = json.loads(Path(summary["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["property"], "sc-domain:example.de")
        self.assertEqual(manifest["periods"][0]["source_format"], "gsc_ui_csv")
        self.assertEqual(manifest["periods"][0]["pages"], "2026-11-01_2026-11-30_pages.csv")

    def test_missing_column_reports_found_columns(self):
        export = self.directory / "export.csv"
        export.write_text(
            "Seiten;Klicks;Impressionen\nhttps://example.de/;1;2\n", encoding="utf-8"
        )
        with self.assertRaises(gsc_module.GscError) as context:
            gsc_module.prepare_export(
                export,
                self.directory / "out",
                property_name="sc-domain:example.de",
                start=date(2026, 11, 1),
                end=date(2026, 11, 30),
            )
        self.assertIn("position", str(context.exception))
        self.assertIn("Seiten", str(context.exception))

    def test_ambiguous_column(self):
        export = self.directory / "export.csv"
        export.write_text(
            "Seite;Klicks;Impressionen;Position;Klicks\n"
            "https://example.de/;1;2;3;4\n",
            encoding="utf-8",
        )
        with self.assertRaises(gsc_module.GscError):
            gsc_module.prepare_export(
                export,
                self.directory / "out",
                property_name="sc-domain:example.de",
                start=date(2026, 11, 1),
                end=date(2026, 11, 30),
            )

    def test_existing_manifest_conflict(self):
        out = self.directory / "out"
        out.mkdir()
        (out / "manifest.json").write_text(
            json.dumps(
                {
                    "property": "sc-domain:andere.de",
                    "search_type": "web",
                    "country": None,
                    "device": None,
                    "periods": [],
                }
            ),
            encoding="utf-8",
        )
        export = self.directory / "export.csv"
        export.write_text(
            "page,clicks,impressions,position\nhttps://example.de/,1,2,3\n",
            encoding="utf-8",
        )
        with self.assertRaises(gsc_module.GscError):
            gsc_module.prepare_export(
                export,
                out,
                property_name="sc-domain:example.de",
                start=date(2026, 11, 1),
                end=date(2026, 11, 30),
            )


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.config = make_config(self.directory, "https://example.de")
        migrate_database(self.config.database)
        self.connection = connect(self.config.database)
        self.run_id = create_run(
            self.connection,
            self.config,
            mode="crawl",
            inputs={"mode": "test"},
            initial_urls=[self.config.start_url],
        )

    def tearDown(self):
        self.connection.close()
        self.tmp.cleanup()

    def _write_manifest(self, pages_rows: list[str], query_rows: list[str] | None = None, *, source_format="gsc_ui_csv"):
        directory = self.directory / "gsc"
        directory.mkdir(exist_ok=True)
        manifest = {
            "property": "sc-domain:example.de",
            "search_type": "web",
            "country": None,
            "device": None,
            "periods": [
                {
                    "start": "2026-09-01",
                    "end": "2026-09-30",
                    "source_format": source_format,
                    "pages": "pages.csv",
                }
            ],
        }
        if query_rows is not None:
            manifest["periods"][0]["page_queries"] = "queries.csv"
        (directory / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (directory / "pages.csv").write_text(
            "page,clicks,impressions,position\n" + "\n".join(pages_rows) + "\n",
            encoding="utf-8",
        )
        if query_rows is not None:
            (directory / "queries.csv").write_text(
                "page,query,clicks,impressions,position\n" + "\n".join(query_rows) + "\n",
                encoding="utf-8",
            )
        return directory

    def test_mapping_statuses_and_zero_position(self):
        directory = self._write_manifest(
            [
                "https://example.de/,10,100,5.0",
                "https://example.de/a/,5,50,8.0",
                "https://example.de/a/?utm_source=x,4,40,9.0",
                "https://external.example/,1,1,1.0",
                "https://example.de/zero/,0,0,0",
            ],
            [
                "https://example.de/,seo,10,100,5.0",
                "https://example.de/a/,seo,5,50,8.0",
            ],
        )
        registry = UrlRegistry(self.connection, self.run_id, self.config.project_id, self.config)
        summary = gsc_module.import_gsc_directory(
            self.connection, self.run_id, self.config, directory, registry
        )
        self.assertEqual(summary.status, "ok")
        self.assertEqual(summary.datasets, 2)
        self.assertEqual(summary.metrics, 7)
        self.assertEqual(summary.matched, 4)
        self.assertEqual(summary.unmatched, 1)
        self.assertEqual(summary.ambiguous, 2)
        rows = {
            (row["source_page"], row["mapping_status"], row["url_id"], row["position"])
            for row in self.connection.execute(
                "SELECT source_page, mapping_status, url_id, position FROM gsc_metrics"
            )
        }
        self.assertIn(("https://example.de/", "matched", 1, 5.0), rows)
        zero_rows = [row for row in rows if row[0] == "https://example.de/zero/"]
        self.assertEqual(len(zero_rows), 1)
        self.assertEqual(zero_rows[0][1], "matched")
        self.assertIsNone(zero_rows[0][3])
        self.assertIn(("https://external.example/", "unmatched", None, 1.0), rows)
        ambiguous = [row for row in rows if row[1] == "ambiguous"]
        self.assertEqual(len(ambiguous), 2)
        statuses = {
            row[0]
            for row in self.connection.execute(
                "SELECT DISTINCT kind FROM url_discoveries"
            )
        }
        self.assertIn("gsc", statuses)

        data = RunData(self.connection, self.config, self.run_id)
        results = evaluate_gsc(data)
        near_top = [item for item in results if item.rule_id == "GSC_NEAR_TOP" and item.outcome == "finding"]
        self.assertTrue(near_top)

    def test_invalid_row_makes_file_unusable(self):
        directory = self._write_manifest(
            ["https://example.de/,10,100,5.0", "https://example.de/defekt/,abc,100,5.0"]
        )
        registry = UrlRegistry(self.connection, self.run_id, self.config.project_id, self.config)
        summary = gsc_module.import_gsc_directory(
            self.connection, self.run_id, self.config, directory, registry
        )
        self.assertEqual(summary.status, "unavailable")
        self.assertEqual(summary.datasets, 0)
        self.assertTrue(any("Zeile 3" in error for error in summary.errors))
        metadata = self.connection.execute(
            "SELECT metadata_json FROM source_imports"
        ).fetchone()[0]
        payload = json.loads(metadata)
        self.assertEqual(payload["files"][0]["status"], "invalid")
        self.assertEqual(payload["files"][0]["errors"][0]["line"], 3)

    def test_no_directory_disabled_import(self):
        registry = UrlRegistry(self.connection, self.run_id, self.config.project_id, self.config)
        summary = gsc_module.import_gsc_directory(
            self.connection, self.run_id, self.config, None, registry
        )
        self.assertEqual(summary.status, "disabled")
        status = self.connection.execute("SELECT status FROM source_imports").fetchone()[0]
        self.assertEqual(status, "disabled")

    def test_invalid_manifest(self):
        directory = self.directory / "gsc"
        directory.mkdir()
        (directory / "manifest.json").write_text("{kein json", encoding="utf-8")
        registry = UrlRegistry(self.connection, self.run_id, self.config.project_id, self.config)
        summary = gsc_module.import_gsc_directory(
            self.connection, self.run_id, self.config, directory, registry
        )
        self.assertEqual(summary.status, "unavailable")
        self.assertTrue(summary.errors)


if __name__ == "__main__":
    unittest.main()
