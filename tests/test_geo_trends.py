from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from seoboy.geo.trends import write_geo_trends

from tests.support import make_config


def run(folder: Path, model: str, observed: str, mention: int, citation: int, error: str = "") -> None:
    raw = folder / "raw_data"
    raw.mkdir(parents=True)
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "provider": "deepseek",
                "model": model,
                "prompt_set": "geo-test-v1",
                "language": "de",
                "region": "DE",
            }
        ),
        encoding="utf-8",
    )
    (raw / "geo_samples.csv").write_text(
        "prompt_id,query,language,region,model,brand_mentions,own_citations,"
        "competitor_mentions,prompt_tokens,completion_tokens,cost_usd,sampled_at,error\n"
        f"prompt-a,Frage?,de,DE,{model},{mention},{citation},0,10,20,0.001,{observed},{error}\n",
        encoding="utf-8",
    )


class GeoTrendTests(unittest.TestCase):
    def test_counts_and_method_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(Path(tmp), "https://example.de/")
            first = config.reports_dir / "run-1"
            second = config.reports_dir / "run-2"
            run(first, "deepseek-flash", "2026-11-01T10:00:00Z", 1, 0)
            run(second, "deepseek-v4-pro", "2026-11-08T10:00:00Z", 0, 1)
            folder = write_geo_trends(config)
            text = (folder / "GEO_TRENDS.md").read_text(encoding="utf-8")
            self.assertIn("Marke genannt | 1 / 2", text)
            self.assertIn("eigene URL zitiert | 1 / 2", text)
            self.assertIn("Methodenwechsel", text)
            self.assertTrue((folder / "raw_data" / "geo_observations.csv").is_file())


if __name__ == "__main__":
    unittest.main()
