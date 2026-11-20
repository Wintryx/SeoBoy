from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from seoboy import cli
from seoboy.ai import review
from seoboy.application import runner
from seoboy.infrastructure.database import connect

from tests.support import FixtureSite, make_config


class AIReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        site = FixtureSite()
        site.__enter__()
        self.addCleanup(site.__exit__, None, None, None)
        site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
        site.add_html("/", "", "<h1>Start</h1><a href='/missing/'>Fehlt</a>")
        site.add("/missing/", body="fehlt", status=404, content_type="text/html")
        config = make_config(self.directory, site.base)
        outcome = runner.run_project(config)
        return config, outcome

    def test_packet_has_deterministic_refs(self):
        _config, outcome = self._run()
        connection = connect(_config.database)
        try:
            data = review.load_report_data(connection, _config, outcome.run_id)
            packet = review.build_review_packet(data, review.ReviewConfig())
        finally:
            connection.close()
        self.assertTrue(packet["findings"])
        self.assertTrue(packet["actions"])
        self.assertTrue(packet["findings"][0]["id"].startswith("f_"))
        self.assertTrue(packet["actions"][0]["id"].startswith("a_"))

    def test_review_and_cache(self):
        config, outcome = self._run()
        connection = connect(config.database)
        try:
            report = review.load_report_data(connection, config, outcome.run_id)
            packet = review.build_review_packet(report, review.ReviewConfig())
            finding_ref = packet["findings"][0]["id"] if packet["findings"] else ""
            action_ref = packet["actions"][0]["id"] if packet["actions"] else ""
            answer = {
                "overall_assessment": "Die Befunde sind konsistent.",
                "confidence": "medium",
                "cross_cutting_issues": [
                    {
                        "title": "CTA und defektes Ziel",
                        "explanation": "Der defekte Link betrifft eine wichtige Seite.",
                        "evidence_refs": [finding_ref] if finding_ref else [],
                        "action_refs": [action_ref] if action_ref else [],
                        "suggested_priority": 2,
                    }
                ],
                "priority_adjustments": [
                    {
                        "action_ref": action_ref,
                        "current_priority": packet["actions"][0]["priority"],
                        "suggested_priority": 2,
                        "reason": "Buchungsrelevanter Pfad.",
                        "confidence": "medium",
                    }
                ] if packet["actions"] else [],
                "data_quality_issues": [],
                "additional_analyses": [],
                "limitations": ["Nur eine Stichprobe."],
            }
            response = {
                "content": json.dumps(answer, ensure_ascii=False),
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                "model": "deepseek-flash",
                "model_version": "DeepSeek-V4.1-Flash-1017",
            }
            review_config = review.ReviewConfig(use_cache=True)
            with patch.object(review, "chat_completion", return_value=response) as call:
                first = review.run_ai_review(
                    connection,
                    config,
                    outcome.run_id,
                    report_dir=outcome.report_dir,
                    api_key="test-key",
                    review_config=review_config,
                )
            self.assertEqual(call.call_count, 1)
            self.assertFalse(first.cached)
            path = review.write_ai_review(first)
            text = path.read_text(encoding="utf-8")
            self.assertIn("Der SeoBoy KI-Agent hat darüber hinaus folgendes analysiert", text)
            self.assertTrue((outcome.report_dir / "raw_data" / "ai_review.json").is_file())
            with patch.object(review, "chat_completion") as second_call:
                second = review.run_ai_review(
                    connection,
                    config,
                    outcome.run_id,
                    report_dir=outcome.report_dir,
                    api_key="test-key",
                    review_config=review_config,
                )
            second_call.assert_not_called()
            self.assertTrue(second.cached)
        finally:
            connection.close()

    def test_invalid_refs_are_unsupported(self):
        packet = {
            "findings": [{"id": "f_valid"}],
            "actions": [{"id": "a_valid"}],
        }
        result, unsupported = review.validate_review(
            {
                "overall_assessment": "Test",
                "confidence": "low",
                "cross_cutting_issues": [
                    {
                        "title": "X",
                        "explanation": "Y",
                        "evidence_refs": ["f_missing"],
                        "action_refs": ["a_missing"],
                    }
                ],
                "priority_adjustments": [],
                "data_quality_issues": [],
                "additional_analyses": [],
                "limitations": [],
            },
            packet,
        )
        self.assertEqual(result["cross_cutting_issues"][0]["evidence_refs"], [])
        self.assertIn("f_missing", unsupported)
        self.assertIn("a_missing", unsupported)

    def test_cli_dry_run_does_not_need_key(self):
        config, outcome = self._run()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict("os.environ", {}, clear=True), patch.object(
            cli, "load_env", return_value={}
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = cli.main(
                    [
                        "ai-review",
                        "--config",
                        str(config.config_path),
                        "--run",
                        outcome.run_id,
                        "--dry-run",
                    ]
                )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertIn("KI-Review-Packung", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
