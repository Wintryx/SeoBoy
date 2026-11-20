from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import tempfile
import unittest

from seoboy import cli
from seoboy.infrastructure.env import load_env, parse_env

from tests.support import make_config


class EnvTests(unittest.TestCase):
    def test_parse_env(self):
        values = parse_env(
            "# Kommentar\n"
            "\n"
            "SEOBOY_CONFIG=./seoboy.yaml\n"
            "export GSC_DIR='./imports/gsc'\n"
            'QUOTED="hello world"\n'
            "INVALID LINE\n"
        )
        self.assertEqual(values["SEOBOY_CONFIG"], "./seoboy.yaml")
        self.assertEqual(values["GSC_DIR"], "./imports/gsc")
        self.assertEqual(values["QUOTED"], "hello world")
        self.assertNotIn("INVALID LINE", values)

    def test_load_env_does_not_override_existing_values(self):
        keys = ["SEOBOY_TEST_KEEP", "SEOBOY_TEST_NEW", "SEOBOY_TEST_QUOTED"]
        old = {key: os.environ.get(key) for key in keys}
        try:
            os.environ["SEOBOY_TEST_KEEP"] = "keep"
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / ".env"
                path.write_text(
                    "SEOBOY_TEST_KEEP=file\n"
                    "SEOBOY_TEST_NEW=value\n"
                    'SEOBOY_TEST_QUOTED="hello world"\n',
                    encoding="utf-8",
                )
                loaded = load_env(path)
            self.assertEqual(os.environ["SEOBOY_TEST_KEEP"], "keep")
            self.assertEqual(os.environ["SEOBOY_TEST_NEW"], "value")
            self.assertEqual(os.environ["SEOBOY_TEST_QUOTED"], "hello world")
            self.assertNotIn("SEOBOY_TEST_KEEP", loaded)
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_cli_uses_env_config_default(self):
        keys = ["SEOBOY_CONFIG", "SEOBOY_GSC_DIR", "SEOBOY_ENV_FILE"]
        old_env = {key: os.environ.get(key) for key in keys}
        old_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                make_config(base, "https://example.de")
                (base / ".env").write_text(
                    "SEOBOY_CONFIG=./seoboy.yaml\n", encoding="utf-8"
                )
                for key in keys:
                    os.environ.pop(key, None)
                os.chdir(base)
                try:
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = cli.main(["migrate"])
                    self.assertEqual(code, 0, stderr.getvalue())
                    self.assertTrue((base / "data" / "test.db").is_file())
                finally:
                    os.chdir(old_cwd)
        finally:
            os.chdir(old_cwd)
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
