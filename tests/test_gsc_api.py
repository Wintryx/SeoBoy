from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from seoboy.gsc import api as gsc_api
from seoboy.gsc import importer as gsc_importer


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests: list[dict] = []

    def log_message(self, format, *args):  # noqa: A002
        return

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if self.path == "/token":
            payload = {"access_token": "test-token", "expires_in": 3600}
        else:
            body = json.loads(raw.decode("utf-8"))
            self.requests.append({"path": self.path, "body": body})
            if self.path.endswith("/searchAnalytics/query"):
                dimensions = body.get("dimensions", [])
                if dimensions == ["page"]:
                    payload = {
                        "rows": [
                            {
                                "keys": ["https://example.de/"],
                                "clicks": 10,
                                "impressions": 100,
                                "ctr": 0.1,
                                "position": 4.2,
                            }
                        ]
                    }
                else:
                    payload = {
                        "rows": [
                            {
                                "keys": ["https://example.de/", "seo"],
                                "clicks": 3,
                                "impressions": 30,
                                "ctr": 0.1,
                                "position": 0,
                            }
                        ]
                    }
            elif self.path.endswith("/urlInspection/index:inspect"):
                payload = {
                    "inspectionResult": {
                        "verdict": "PASS",
                        "indexStatusResult": {
                            "coverageState": "Submitted and indexed",
                            "indexingState": "INDEXING_ALLOWED",
                            "robotsTxtState": "ALLOWED",
                            "pageFetchState": "SUCCESSFUL",
                            "googleCanonical": "https://example.de/",
                            "userCanonical": "https://example.de/",
                            "lastCrawlTime": "2026-11-20T08:00:00Z",
                        },
                    }
                }
            else:
                payload = {}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class GscApiTests(unittest.TestCase):
    def setUp(self):
        _Handler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        base = f"http://127.0.0.1:{self.server.server_port}"
        self.patches = [
            patch.object(gsc_api, "TOKEN_URL", base + "/token"),
            patch.object(gsc_api, "API_BASE", base + "/webmasters/v3"),
            patch.object(gsc_api, "INSPECTION_URL", base + "/v1/urlInspection/index:inspect"),
        ]
        for item in self.patches:
            item.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.credentials_path = Path(self.tmp.name) / "credentials.json"
        self.credentials_path.write_text(
            json.dumps(
                {
                    "client_id": "client",
                    "client_secret": "secret",
                    "refresh_token": "refresh",
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def test_fetch_writes_manifest_and_csv(self):
        credentials = gsc_api.load_credentials(self.credentials_path)
        out = Path(self.tmp.name) / "out"
        summary = gsc_api.fetch_to_directory(
            credentials,
            "sc-domain:example.de",
            gsc_api.date(2026, 10, 1),
            gsc_api.date(2026, 10, 31),
            out,
            country="deu",
            device="MOBILE",
        )
        self.assertEqual(summary.pages, 1)
        self.assertEqual(summary.queries, 1)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["periods"][0]["source_format"], "gsc_api")
        self.assertEqual(manifest["country"], "deu")
        self.assertEqual(manifest["device"], "MOBILE")

        gsc_api.fetch_to_directory(
            credentials,
            "sc-domain:example.de",
            gsc_api.date(2026, 9, 1),
            gsc_api.date(2026, 9, 30),
            out,
            country="deu",
            device="mobile",
            append=True,
        )
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["periods"]), 2)
        self.assertTrue(
            (out / "2026-09-01_2026-09-30_pages.csv").is_file()
        )
        page_csv = (out / "2026-10-01_2026-10-31_pages.csv").read_text(encoding="utf-8-sig")
        self.assertIn("https://example.de/", page_csv)
        self.assertIn("4.2", page_csv)
        query_csv = (out / "2026-10-01_2026-10-31_page_queries.csv").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("seo", query_csv)
        self.assertTrue(any("dimensionFilterGroups" in item["body"] for item in _Handler.requests))

        manifest_data = gsc_importer.load_manifest(out)
        period = manifest_data.periods[0]
        parsed = gsc_importer.ParsedFile(
            path=out / period.pages, grain="page", period=period
        )
        gsc_importer.parse_file(parsed)
        self.assertTrue(parsed.valid)
        self.assertEqual(len(parsed.rows), 1)

    def test_url_inspection(self):
        credentials = gsc_api.GscCredentials(
            client_id="c", client_secret="s", refresh_token="r", access_token="token"
        )
        result = gsc_api.inspect_url(
            credentials, "sc-domain:example.de", "https://example.de/"
        )
        self.assertEqual(result["verdict"], "PASS")
        markdown = gsc_api.inspection_markdown(
            result,
            property_name="sc-domain:example.de",
            inspection_url="https://example.de/",
        )
        self.assertIn("Submitted and indexed", markdown)
        self.assertIn("Google Canonical", markdown)

    def test_service_account_credentials_are_detected(self):
        path = Path(self.tmp.name) / "service-account.json"
        path.write_text(
            json.dumps(
                {
                    "type": "service_account",
                    "client_email": "seo@example.iam.gserviceaccount.com",
                    "private_key": "-----BEGIN PRIVATE KEY-----\n...",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            ),
            encoding="utf-8",
        )
        credentials = gsc_api.load_credentials(path)
        self.assertTrue(credentials.is_service_account)
        self.assertEqual(credentials.service_account_email, "seo@example.iam.gserviceaccount.com")

    def test_invalid_credentials_file(self):
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text("{}", encoding="utf-8")
        with self.assertRaises(gsc_api.GscApiError):
            gsc_api.load_credentials(bad)


if __name__ == "__main__":
    unittest.main()
