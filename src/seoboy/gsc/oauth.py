"""Interactive Google OAuth login for Search Console."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser

from seoboy.gsc.api import (
    GscApiError,
    TOKEN_URL,
    _http_json,
    default_token_store,
    save_token_store,
)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


@dataclass(frozen=True)
class OAuthClient:
    client_id: str
    client_secret: str
    auth_uri: str = AUTH_URL
    token_uri: str = TOKEN_URL


def load_client_config(path: Path | str) -> OAuthClient:
    target = Path(path).expanduser()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as error:
        raise GscApiError(f"OAuth-Clientdatei nicht lesbar: {error}") from error
    except ValueError as error:
        raise GscApiError(f"OAuth-Clientdatei ist kein gültiges JSON: {error}") from error
    if not isinstance(payload, dict):
        raise GscApiError("OAuth-Clientdatei muss ein JSON-Objekt enthalten.")
    block = payload.get("installed") or payload.get("web") or payload
    if not isinstance(block, dict):
        raise GscApiError("OAuth-Clientdatei enthält keinen installierten Client.")
    client_id = str(block.get("client_id") or "").strip()
    client_secret = str(block.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise GscApiError("OAuth-Clientdatei benötigt client_id und client_secret.")
    return OAuthClient(
        client_id=client_id,
        client_secret=client_secret,
        auth_uri=str(block.get("auth_uri") or AUTH_URL).strip() or AUTH_URL,
        token_uri=str(block.get("token_uri") or TOKEN_URL).strip() or TOKEN_URL,
    )


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorization_url(
    client: OAuthClient,
    redirect_uri: str,
    *,
    state: str,
    code_challenge: str,
) -> str:
    query = urlencode(
        {
            "client_id": client.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
    )
    return f"{client.auth_uri}?{query}"


def exchange_code(
    client: OAuthClient,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict:
    payload = _http_json(
        client.token_uri,
        data=urlencode(
            {
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if not payload.get("refresh_token"):
        raise GscApiError(
            "Google hat keinen refresh_token geliefert. Bitte die Zustimmung erneut "
            "mit prompt=consent erteilen."
        )
    return payload


def login(
    client: OAuthClient,
    *,
    token_store: Path | str | None = None,
    open_browser: bool = True,
    timeout: int = 180,
) -> Path:
    if not 30 <= timeout <= 900:
        raise GscApiError("OAuth-Timeout muss zwischen 30 und 900 Sekunden liegen.")
    redirect_path = "/oauth2callback"
    result: dict[str, str] = {}
    event = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            if parsed.path != redirect_path:
                self.send_response(404)
                self.end_headers()
                return
            for key, values in parse_qs(parsed.query).items():
                if values:
                    result[key] = values[0]
            event.set()
            body = (
                "<html><body><h1>SeoBoy</h1>"
                "<p>Die Search-Console-Anmeldung ist abgeschlossen. "
                "Du kannst dieses Fenster schließen.</p></body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state = secrets.token_urlsafe(24)
    verifier, challenge = _pkce()
    redirect_uri = f"http://127.0.0.1:{server.server_port}{redirect_path}"
    url = authorization_url(
        client, redirect_uri, state=state, code_challenge=challenge
    )
    try:
        print(f"OAuth-URL: {url}")
        if open_browser:
            webbrowser.open(url)
        if not event.wait(timeout):
            raise GscApiError(
                "OAuth-Anmeldung wurde nicht innerhalb des Zeitlimits abgeschlossen."
            )
    finally:
        server.shutdown()
        server.server_close()
    if result.get("error"):
        raise GscApiError(f"OAuth-Fehler: {result['error']}")
    if result.get("state") != state:
        raise GscApiError("OAuth-State stimmt nicht überein.")
    code = result.get("code")
    if not code:
        raise GscApiError("OAuth-Callback enthielt keinen Code.")
    payload = exchange_code(client, code, redirect_uri, verifier)
    target = Path(token_store) if token_store is not None else default_token_store()
    return save_token_store(
        target,
        client_id=client.client_id,
        client_secret=client.client_secret,
        refresh_token=str(payload["refresh_token"]),
        token_uri=client.token_uri,
        scopes=SCOPES,
    )
