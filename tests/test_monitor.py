from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from seoboy.application import runner
from seoboy.infrastructure.database import connect, migrate_database
from seoboy.monitoring.monitor import run_monitor_check

from tests.support import FixtureSite, make_config


class MonitorTests(unittest.TestCase):
    def test_two_failures_confirm_and_success_recovers(self):
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html("/", "Start", "<h1>Start</h1>")
            site.add_html("/kontakt/", "Kontakt", "<h1>Kontakt</h1>")
            config = make_config(
                Path(tmp),
                site.base,
                profiles=[
                    {
                        "path": "/kontakt/",
                        "page_type": "contact",
                        "business_value": "high",
                        "expected_indexable": True,
                    }
                ],
            )
            runner.run_project(config)
            migrate_database(config.database)
            connection = connect(config.database)
            try:
                url = site.url("/kontakt/")
                _folder, first = run_monitor_check(connection, config, urls=[url])
                self.assertEqual(first[0].state, "ok")
                site.add("/kontakt/", status=503, body="down")
                _folder, second = run_monitor_check(connection, config, urls=[url])
                self.assertEqual(second[0].state, "suspect")
                event = connection.execute(
                    "SELECT state, failures FROM monitor_events WHERE watch_key = ?",
                    (url,),
                ).fetchone()
                self.assertEqual((event["state"], event["failures"]), ("suspect", 1))
                _folder, third = run_monitor_check(connection, config, urls=[url])
                self.assertEqual(third[0].state, "confirmed")
                event = connection.execute(
                    "SELECT state, failures FROM monitor_events WHERE watch_key = ?",
                    (url,),
                ).fetchone()
                self.assertEqual((event["state"], event["failures"]), ("confirmed", 2))
                site.add_html("/kontakt/", "Kontakt", "<h1>Kontakt</h1>")
                _folder, fourth = run_monitor_check(connection, config, urls=[url])
                self.assertEqual(fourth[0].state, "recovered")
                event = connection.execute(
                    "SELECT state, recovered_at FROM monitor_events WHERE watch_key = ?",
                    (url,),
                ).fetchone()
                self.assertEqual(event["state"], "recovered")
                self.assertIsNotNone(event["recovered_at"])
                self.assertTrue((config.reports_dir / "monitor" / "MONITOR_STATUS.md").is_file())
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
