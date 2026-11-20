from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import yaml

from seoboy.local_seo.audit import (
    LocalSeoError,
    audit_locations,
    load_locations,
    load_local_rankings,
    write_local_report,
)

from tests.support import FixtureSite, html


class LocalSeoTests(unittest.TestCase):
    def _location_file(self, directory: Path, url: str) -> Path:
        path = directory / "locations.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "locations": [
                        {
                            "label": "Köln",
                            "url": url,
                            "name": "AW Audio",
                            "street": "Musterweg 1",
                            "postal_code": "50667",
                            "city": "Köln",
                            "region": "NRW",
                            "country": "DE",
                            "phone": "+49 221 123456",
                        }
                    ]
                },
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        return path

    def _page(self, city: str) -> str:
        schema = json.dumps(
            {
                "@context": "https://schema.org",
                "@type": "LocalBusiness",
                "name": "AW Audio",
                "telephone": "+49 221 123456",
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": "Musterweg 1",
                    "postalCode": "50667",
                    "addressLocality": city,
                    "addressRegion": "NRW",
                    "addressCountry": "DE",
                },
            }
        )
        return html(
            "Standort Köln",
            "<h1>DJ in Köln</h1><p>Lokaler Standort.</p>",
            description="Lokaler DJ-Standort",
            extra_head=f"<script type='application/ld+json'>{schema}</script>",
        )

    def test_load_locations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._location_file(Path(tmp), "https://example.de/standort/")
            locations = load_locations(path)
        self.assertEqual(locations[0].label, "Köln")
        self.assertEqual(locations[0].city, "Köln")

    def test_nap_match_and_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add(
                "/robots.txt",
                body="User-agent: *\nAllow: /\n",
                content_type="text/plain",
            )
            site.add("/standort/", body=self._page("Köln"))
            path = self._location_file(Path(tmp), site.url("/standort/"))
            locations = load_locations(path)
            results = audit_locations(locations, interval_seconds=0)
            self.assertEqual(results[0].error, None)
            self.assertTrue(all(results[0].matches.values()))
            self.assertEqual(results[0].missing, ())
            self.assertEqual(results[0].mismatches, ())

            site.add("/standort/", body=self._page("Bonn"))
            results = audit_locations(locations, interval_seconds=0)
            self.assertIn("city", results[0].mismatches)

            folder = write_local_report(results, Path(tmp) / "report")
            self.assertTrue((folder / "00_LOCAL_SEO.md").is_file())
            self.assertTrue((folder / "raw_data" / "local_locations.csv").is_file())

    def test_external_profiles_and_local_results(self):
        with tempfile.TemporaryDirectory() as tmp, FixtureSite() as site:
            site.add("/robots.txt", body="User-agent: *\nAllow: /\n", content_type="text/plain")
            site.add_html(
                "/profil/",
                "AW Audio Profil",
                "<h1>AW Audio</h1><p>Köln, +49 221 123456</p>",
            )
            site.add("/standort/", body=self._page("Köln"))
            path = Path(tmp) / "locations.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "locations": [
                            {
                                "label": "Köln",
                                "url": site.url("/standort/"),
                                "name": "AW Audio",
                                "street": "Musterweg 1",
                                "postal_code": "50667",
                                "city": "Köln",
                                "region": "NRW",
                                "country": "DE",
                                "phone": "+49 221 123456",
                                "profiles": [site.url("/profil/")],
                            }
                        ]
                    },
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            locations = load_locations(path)
            results = audit_locations(locations, interval_seconds=0)
            self.assertEqual(len(results[0].profiles), 1)
            profile = results[0].profiles[0]
            self.assertTrue(profile.name_match)
            self.assertTrue(profile.city_match)
            self.assertTrue(profile.phone_match)

            rankings_path = Path(tmp) / "rankings.csv"
            rankings_path.write_text(
                "query,location,position,url,source,date\n"
                "hochzeits dj,Koeln,4,https://example.de/,manual,2026-11-20\n",
                encoding="utf-8",
            )
            rankings = load_local_rankings(rankings_path)
            folder = write_local_report(
                results, Path(tmp) / "report", rankings
            )
            self.assertTrue((folder / "raw_data" / "local_profiles.csv").is_file())
            self.assertTrue((folder / "raw_data" / "local_rankings.csv").is_file())
            text = (folder / "00_LOCAL_SEO.md").read_text(encoding="utf-8")
            self.assertIn("Externe Profile", text)
            self.assertIn("Lokale Suchergebnisse", text)

    def test_invalid_location_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yaml"
            path.write_text("locations: []", encoding="utf-8")
            with self.assertRaises(LocalSeoError):
                load_locations(path)


if __name__ == "__main__":
    unittest.main()
