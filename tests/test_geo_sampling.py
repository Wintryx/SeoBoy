from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from seoboy import cli
from seoboy.geo import sampling


class GeoSamplingTests(unittest.TestCase):
    def test_analyze_answer(self):
        result = sampling.analyze_answer(
            "AW Audio aus Köln ist eine Option. Siehe https://aw-audio.de/ "
            "und https://www.djmagic.eu/.",
            brands=("AW Audio", "aw-audio.de"),
            competitors=("djmagic",),
            domain="aw-audio.de",
        )
        self.assertEqual(result["brand_mentions"], 2)
        self.assertEqual(result["competitor_mentions"], 1)
        self.assertIn("https://aw-audio.de/", result["own_citations"])
        self.assertEqual(len(result["citations"]), 2)

    def test_custom_prompt_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompts.yaml"
            path.write_text(
                "version: test\nlanguage: de\nregion: DE\n"
                "prompts:\n  - id: eins\n    prompt: Frage?\n",
                encoding="utf-8",
            )
            prompt_set = sampling.load_prompt_set(path)
        self.assertEqual(prompt_set.version, "test")
        self.assertEqual(prompt_set.prompts[0].id, "eins")

    def test_run_writes_report_and_raw_answers(self):
        prompt_set = sampling.load_prompt_set()
        config = sampling.SamplingConfig(max_calls=1, budget_usd=1.0)
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            sampling,
            "chat_completion",
            return_value={
                "content": "AW Audio, siehe https://aw-audio.de/.",
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
                "model": "deepseek-flash",
                "id": "req",
            },
        ):
            out = Path(tmp) / "geo"
            run = sampling.run_sampling(
                api_key="test-key",
                prompt_set=prompt_set,
                config=config,
                out=out,
                domain="aw-audio.de",
            )
            self.assertEqual(run.successful, 1)
            self.assertEqual(run.total_tokens, 150)
            self.assertTrue((out / "00_GEO_SAMPLING.md").is_file())
            self.assertTrue((out / "raw_data" / "geo_answers.jsonl").is_file())
            self.assertTrue((out / "raw_data" / "geo_citations.csv").is_file())
            text = (out / "00_GEO_SAMPLING.md").read_text(encoding="utf-8")
            self.assertNotIn("test-key", text)
            raw = (out / "raw_data" / "geo_answers.jsonl").read_text(encoding="utf-8")
            self.assertIn("aw-audio.de", raw)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["provider"], "deepseek")
            self.assertEqual(manifest["successful"], 1)

    def test_chat_completion_uses_non_thinking_mode(self):
        payload = {
            "model": "deepseek-flash",
            "choices": [{"message": {"content": "Antwort"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        with patch.object(sampling, "_post_json", return_value=payload) as post:
            result = sampling.chat_completion("key", "Frage?")
        self.assertEqual(result["content"], "Antwort")
        body = post.call_args.args[1]
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertFalse(body["stream"])

    def test_web_search_request_and_citations(self):
        payload = {
            "model": "deepseek-flash",
            "choices": [
                {
                    "message": {
                        "content": "Antwort mit Quelle.",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url_citation": {"url": "https://example.de/a"},
                            }
                        ],
                        "server_tool_calls": [
                            {
                                "calls": [
                                    {
                                        "sources": [
                                            {"url": "https://example.de/b"}
                                        ]
                                    }
                                ]
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        with patch.object(sampling, "_post_json", return_value=payload) as post:
            result = sampling.chat_completion("key", "Frage?", web_search=True)
        body = post.call_args.args[1]
        self.assertEqual(
            body["tools"], [{"type": "deepseek_web_search"}]
        )
        self.assertEqual(
            result["citations"], ("https://example.de/a", "https://example.de/b")
        )

    def test_auth_error_stops(self):
        prompt_set = sampling.load_prompt_set()
        config = sampling.SamplingConfig(max_calls=6, budget_usd=1.0)
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            sampling,
            "chat_completion",
            side_effect=sampling.GeoSamplingError("DeepSeek HTTP 401: unauthorized"),
        ):
            out = Path(tmp) / "geo"
            run = sampling.run_sampling(
                api_key="test-key", prompt_set=prompt_set, config=config, out=out
            )
        self.assertEqual(run.successful, 0)
        self.assertEqual(run.failed, 1)
        self.assertEqual(run.stop_reason, "auth_error")

    def test_cli_requires_key(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict("os.environ", {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = cli.main(["geo-sample"])
        self.assertEqual(code, 2)
        self.assertIn("DeepSeek-API-Key", stderr.getvalue())

    def test_cli_dry_run(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(["geo-sample", "--dry-run"])
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertIn("hochzeit-dj-koeln", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
