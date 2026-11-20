from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from seoboy.application import runner
from seoboy.shared.progress import ProgressReporter
from tests.support import FixtureSite, make_config


class ProgressTests(unittest.TestCase):
    def test_json_event_contains_eta_fields(self):
        stream = StringIO()
        reporter = ProgressReporter("json", interval_seconds=0.2, stream=stream)
        reporter.emit(
            stage="crawl",
            message="Analysiere URLs",
            completed=5,
            total=10,
            unit="URLs",
            force=True,
        )
        event = json.loads(stream.getvalue().strip())
        self.assertEqual(event["event"], "progress")
        self.assertEqual(event["stage"], "crawl")
        self.assertEqual(event["percent"], 50.0)
        self.assertIn("eta_seconds", event)
        self.assertIn("timestamp", event)

    def test_human_event(self):
        stream = StringIO()
        reporter = ProgressReporter("human", interval_seconds=0.2, stream=stream)
        reporter.emit(
            stage="analysis",
            message="Regeln auswerten",
            completed=1,
            total=4,
            unit="Schritte",
            force=True,
        )
        text = stream.getvalue()
        self.assertIn("analysis", text)
        self.assertIn("25.0%", text)
        self.assertIn("ETA", text)

    def test_run_emits_stage_events(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html("/", "Start", "<h1>Start</h1>")
            config = make_config(Path(tmp), site.base)
            outcome = runner.run_project(config, progress=events.append)
        self.assertIsNotNone(outcome.report_dir)
        stages = {event["stage"] for event in events}
        self.assertIn("vorbereitung", stages)
        self.assertIn("crawl", stages)
        self.assertIn("analysis", stages)
        self.assertIn("reports", stages)
        self.assertTrue(any(event.get("total") for event in events))
        crawl_events = [event for event in events if event["stage"] == "crawl"]
        self.assertTrue(
            any(event.get("completed", 0) > 0 for event in crawl_events),
            crawl_events,
        )

    def test_off_and_handle(self):
        stream = StringIO()
        reporter = ProgressReporter("off", interval_seconds=0.2, stream=stream)
        reporter.handle({"stage": "test", "message": "x", "force": True})
        self.assertEqual(reporter.mode, "off")
        self.assertEqual(stream.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
