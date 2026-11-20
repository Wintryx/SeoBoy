from __future__ import annotations

from pathlib import Path
import os
import unittest
from unittest.mock import patch

from seoboy import cli


class AISettingsTests(unittest.TestCase):
    def test_geo_env_defaults_and_cli_override(self):
        env = {
            "SEOBOY_GEO_MODEL": "deepseek-v4-pro",
            "SEOBOY_GEO_THINKING": "disabled",
            "SEOBOY_GEO_REASONING_EFFORT": "max",
        }
        with patch.dict(os.environ, env, clear=True):
            parser = cli._build_parser(Path("seoboy.yaml"))
            args = parser.parse_args(["geo-sample", "--dry-run"])
        self.assertEqual(args.model, "deepseek-v4-pro")
        self.assertEqual(args.thinking, "disabled")
        self.assertEqual(args.reasoning_effort, "max")

        with patch.dict(os.environ, env, clear=True):
            parser = cli._build_parser(Path("seoboy.yaml"))
            args = parser.parse_args(
                ["geo-sample", "--dry-run", "--reasoning-effort", "low"]
            )
        self.assertEqual(args.reasoning_effort, "low")

    def test_review_env_defaults(self):
        env = {
            "SEOBOY_AI_REVIEW_MODEL": "deepseek-v4-pro",
            "SEOBOY_AI_REVIEW_THINKING": "enabled",
            "SEOBOY_AI_REVIEW_REASONING_EFFORT": "high",
        }
        with patch.dict(os.environ, env, clear=True):
            parser = cli._build_parser(Path("seoboy.yaml"))
            args = parser.parse_args(["ai-review", "--run", "run-1"])
        self.assertEqual(args.model, "deepseek-v4-pro")
        self.assertEqual(args.thinking, "enabled")
        self.assertEqual(args.reasoning_effort, "high")


if __name__ == "__main__":
    unittest.main()
