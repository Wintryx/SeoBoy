from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_secrets.py"
SPEC = importlib.util.spec_from_file_location("seoboy_check_secrets", SCRIPT)
assert SPEC and SPEC.loader
scanner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scanner)


class SecretScanTests(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(scanner.find_secrets("Ein normaler Text ohne Key."), [])

    def test_deepseek_style_key(self):
        text = "DEEPSEEK_API_KEY=" + "sk-" + "a" * 24
        labels = [label for label, _ in scanner.find_secrets(text, "test")]
        self.assertIn("deepseek_or_openai_key", labels)

    def test_private_key_block(self):
        text = "-----BEGIN " + "PRIVATE KEY-----\n" + "A" * 48 + "\n"
        labels = [label for label, _ in scanner.find_secrets(text, "test")]
        self.assertIn("private_key", labels)


if __name__ == "__main__":
    unittest.main()
