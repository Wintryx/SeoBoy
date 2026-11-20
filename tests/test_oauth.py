from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from seoboy.gsc import api as gsc_api
from seoboy.gsc import oauth


class OAuthTests(unittest.TestCase):
    def test_client_config_and_authorization_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "client.json"
            path.write_text(
                '{"installed":{"client_id":"id","client_secret":"secret",'
                '"auth_uri":"https://accounts.google.com/o/oauth2/v2/auth",'
                '"token_uri":"https://oauth2.googleapis.com/token"}}',
                encoding="utf-8",
            )
            client = oauth.load_client_config(path)
        self.assertEqual(client.client_id, "id")
        url = oauth.authorization_url(
            client,
            "http://127.0.0.1:1234/oauth2callback",
            state="state",
            code_challenge="challenge",
        )
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("access_type=offline", url)
        self.assertIn("state=state", url)
        self.assertIn("redirect_uri=http%3A%2F%2F127.0.0.1%3A1234", url)

    def test_token_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gsc-oauth.json"
            saved = gsc_api.save_token_store(
                path,
                client_id="id",
                client_secret="secret",
                refresh_token="refresh",
                token_uri="https://oauth2.googleapis.com/token",
                scopes=["scope"],
            )
            self.assertEqual(saved, path)
            credentials = gsc_api.load_credentials(path)
        self.assertEqual(credentials.client_id, "id")
        self.assertEqual(credentials.refresh_token, "refresh")

    def test_exchange_code(self):
        client = oauth.OAuthClient("id", "secret")
        with patch.object(
            oauth,
            "_http_json",
            return_value={"refresh_token": "refresh", "access_token": "access"},
        ) as mocked:
            payload = oauth.exchange_code(
                client, "code", "http://127.0.0.1/callback", "verifier"
            )
        self.assertEqual(payload["refresh_token"], "refresh")
        self.assertTrue(mocked.called)


if __name__ == "__main__":
    unittest.main()
