from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from seoboy.rankings.config import KeywordProfile
from seoboy.rankings.serp import fetch_serper_csv


class FakeResponse:
    status = 200

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self, *_args) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class SerperTests(unittest.TestCase):
    def test_csv_is_generated_without_mobile_claim(self):
        profiles = (
            KeywordProfile(
                id="hochzeits-dj-koeln",
                query="hochzeits dj köln",
                location_key="koeln",
                expected_target="/hochzeit-dj/",
            ),
            KeywordProfile(
                id="hochzeits-dj-koeln-mobile",
                query="hochzeits dj köln",
                location_key="koeln",
                device="mobile",
                expected_target="/hochzeit-dj/",
            ),
        )
        payload = {
            "organic": [
                {
                    "position": 1,
                    "title": "Konkurrent",
                    "link": "https://competitor.example/",
                },
                {
                    "position": 2,
                    "title": "AW Audio",
                    "link": "https://aw-audio.de/hochzeit-dj/",
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "seoboy.rankings.serp.urlopen", return_value=FakeResponse(payload)
        ):
            snapshots, results, stats = fetch_serper_csv(
                profiles, "test-key", Path(tmp), max_calls=2, interval_seconds=0
            )
            self.assertEqual(stats["calls"], 1)
            self.assertEqual(stats["skipped_mobile"], 1)
            self.assertIn("hochzeits-dj-koeln", snapshots.read_text(encoding="utf-8-sig"))
            result_text = results.read_text(encoding="utf-8-sig")
            self.assertIn("https://aw-audio.de/hochzeit-dj/", result_text)
            self.assertNotIn("test-key", result_text)


if __name__ == "__main__":
    unittest.main()
