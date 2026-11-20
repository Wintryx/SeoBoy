"""Google Search Console API client built on the standard library."""

from __future__ import annotations

import base64
import csv
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
import urllib.request

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://searchconsole.googleapis.com/webmasters/v3"
INSPECTION_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
MAX_ROWS = 100_000


class GscApiError(RuntimeError):
    """A Search Console API request failed or is not configured."""


@dataclass(frozen=True)
class GscCredentials:
    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    access_token: str | None = None
    service_account_email: str | None = None
    private_key: str | None = None
    token_uri: str | None = None

    @property
    def is_service_account(self) -> bool:
        return bool(self.service_account_email and self.private_key)


@dataclass(frozen=True)
class GscFetchSummary:
    folder: Path
    period_start: str
    period_end: str
    pages: int
    queries: int


def default_token_store() -> Path:
    configured = os.environ.get("SEOBOY_GSC_TOKEN_STORE")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = Path(
            os.environ.get("LOCALAPPDATA")
            or (Path.home() / "AppData" / "Local")
        )
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "SeoBoy" / "gsc-oauth.json"


def save_token_store(
    path: Path | str,
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    token_uri: str,
    scopes: list[str],
) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.parent.chmod(0o700)
    except OSError:
        pass
    payload = {
        "type": "oauth_token_store",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "token_uri": token_uri,
        "scopes": scopes,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(target)
    return target


def load_credentials(path: Path | str | None = None) -> GscCredentials:
    raw_path = path or os.environ.get("SEOBOY_GSC_CREDENTIALS")
    if not raw_path:
        candidate = default_token_store()
        if candidate.is_file():
            raw_path = candidate
    if not raw_path:
        raise GscApiError(
            "Keine GSC-Zugangsdatei angegeben. Nutze --credentials, "
            "SEOBOY_GSC_CREDENTIALS oder 'seoboy gsc-auth'."
        )
    target = Path(raw_path).expanduser()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as error:
        raise GscApiError(f"GSC-Zugangsdatei nicht lesbar: {error}") from error
    except ValueError as error:
        raise GscApiError(f"GSC-Zugangsdatei ist kein gültiges JSON: {error}") from error
    if not isinstance(payload, dict):
        raise GscApiError("GSC-Zugangsdatei muss ein JSON-Objekt enthalten.")
    service_email = str(payload.get("client_email") or "").strip()
    private_key = str(payload.get("private_key") or "").strip()
    if payload.get("type") == "service_account" or (service_email and private_key):
        if not service_email or not private_key:
            raise GscApiError(
                "Service-Account-Datei benötigt client_email und private_key."
            )
        token_uri = str(payload.get("token_uri") or "").strip() or None
        return GscCredentials(
            service_account_email=service_email,
            private_key=private_key,
            token_uri=token_uri,
        )
    client_id = str(payload.get("client_id") or "").strip()
    client_secret = str(payload.get("client_secret") or "").strip()
    refresh_token = str(payload.get("refresh_token") or "").strip()
    if not client_id or not client_secret or not refresh_token:
        raise GscApiError(
            "GSC-Zugangsdatei benötigt client_id, client_secret und refresh_token."
        )
    access_token = str(payload.get("access_token") or "").strip() or None
    return GscCredentials(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        access_token=access_token,
    )


def _http_json(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> dict:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(20_000_000).decode("utf-8", errors="replace")
    except HTTPError as error:
        detail = error.read(4000).decode("utf-8", errors="replace")
        raise GscApiError(
            f"GSC-API HTTP {error.code}: {detail or error.reason}"
        ) from error
    except URLError as error:
        raise GscApiError(f"GSC-API nicht erreichbar: {error.reason}") from error
    except OSError as error:
        raise GscApiError(f"GSC-API-Verbindung fehlgeschlagen: {error}") from error
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise GscApiError("GSC-API lieferte keine gültige JSON-Antwort.") from error
    if not isinstance(payload, dict):
        raise GscApiError("GSC-API lieferte ein unerwartetes JSON-Format.")
    return payload


_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


def _cache_key(credentials: GscCredentials) -> str:
    material = "|".join(
        [
            credentials.service_account_email or "",
            credentials.client_id,
            credentials.refresh_token,
            credentials.token_uri or "",
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _openssl_path() -> str | None:
    configured = os.environ.get("SEOBOY_OPENSSL")
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("openssl")
    if found:
        return found
    if os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        for candidate in (
            program_files / "Git" / "usr" / "bin" / "openssl.exe",
            program_files / "Git" / "mingw64" / "bin" / "openssl.exe",
        ):
            if candidate.is_file():
                return str(candidate)
    return None


def _sign_with_openssl(signing_input: bytes, private_key: str) -> bytes:
    executable = _openssl_path()
    if not executable:
        raise GscApiError(
            "Service-Account-Anmeldung benötigt cryptography oder OpenSSL. "
            "Installation: pip install 'seoboy[gsc-service-account]'."
        )
    try:
        with tempfile.TemporaryDirectory(prefix="seoboy-jwt-") as temporary:
            key_path = Path(temporary) / "key.pem"
            input_path = Path(temporary) / "input.bin"
            key_path.write_text(private_key, encoding="utf-8")
            try:
                key_path.chmod(0o600)
            except OSError:
                pass
            input_path.write_bytes(signing_input)
            result = subprocess.run(
                [
                    executable,
                    "dgst",
                    "-sha256",
                    "-sign",
                    str(key_path),
                    "-binary",
                    str(input_path),
                ],
                capture_output=True,
                check=False,
                timeout=30,
            )
    except (OSError, subprocess.SubprocessError) as error:
        raise GscApiError("OpenSSL-Signatur konnte nicht ausgeführt werden.") from error
    if result.returncode != 0 or not result.stdout:
        raise GscApiError("OpenSSL-Signatur ist fehlgeschlagen.")
    return result.stdout


def _service_account_token(credentials: GscCredentials) -> dict:
    if not credentials.service_account_email or not credentials.private_key:
        raise GscApiError("Service-Account-Zugangsdaten sind unvollständig.")
    token_uri = credentials.token_uri or TOKEN_URL
    header = _base64url(
        json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8")
    )
    now = int(time.time())
    claims = {
        "iss": credentials.service_account_email,
        "scope": "https://www.googleapis.com/auth/webmasters.readonly",
        "aud": token_uri,
        "exp": now + 3600,
        "iat": now,
    }
    body = _base64url(
        json.dumps(claims, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{header}.{body}".encode("ascii")
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        signature = _sign_with_openssl(signing_input, credentials.private_key)
    else:
        try:
            private_key = serialization.load_pem_private_key(
                credentials.private_key.encode("utf-8"), password=None
            )
            signature = private_key.sign(
                signing_input, padding.PKCS1v15(), hashes.SHA256()
            )
        except (ValueError, TypeError) as error:
            raise GscApiError("Service-Account-Private-Key ist ungültig.") from error
    assertion = f"{header}.{body}.{_base64url(signature)}"
    token_body = urlencode(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }
    ).encode("utf-8")
    return _http_json(
        token_uri,
        data=token_body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def access_token(credentials: GscCredentials) -> str:
    if credentials.access_token:
        return credentials.access_token
    env_token = os.environ.get("SEOBOY_GSC_ACCESS_TOKEN")
    if env_token:
        return env_token
    key = _cache_key(credentials)
    cached = _TOKEN_CACHE.get(key)
    if cached is not None and cached[1] > time.monotonic() + 30:
        return cached[0]
    if credentials.is_service_account:
        payload = _service_account_token(credentials)
    else:
        body = urlencode(
            {
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "refresh_token": credentials.refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")
        payload = _http_json(
            TOKEN_URL,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    token = str(payload.get("access_token") or "")
    if not token:
        raise GscApiError("OAuth-Antwort enthielt kein access_token.")
    try:
        expires_in = int(payload.get("expires_in") or 3600)
    except (TypeError, ValueError):
        expires_in = 3600
    _TOKEN_CACHE[key] = (token, time.monotonic() + max(60, expires_in))
    return token


def _filters(
    country: str | None, device: str | None
) -> list[dict[str, object]]:
    filters: list[dict[str, object]] = []
    if country:
        filters.append(
            {"dimension": "country", "operator": "equals", "expression": country}
        )
    if device:
        filters.append(
            {"dimension": "device", "operator": "equals", "expression": device.upper()}
        )
    return [{"filters": filters}] if filters else []


def search_analytics(
    token: str,
    property_name: str,
    start: date,
    end: date,
    dimensions: list[str],
    *,
    search_type: str = "web",
    country: str | None = None,
    device: str | None = None,
    row_limit: int = 25_000,
    max_rows: int = MAX_ROWS,
) -> list[dict[str, object]]:
    if start > end:
        raise GscApiError("Der GSC-Zeitraum beginnt nach seinem Enddatum.")
    if not 1 <= row_limit <= 25_000:
        raise GscApiError("--row-limit muss zwischen 1 und 25000 liegen.")
    if max_rows < 1:
        raise GscApiError("--max-rows muss mindestens 1 sein.")
    url = (
        f"{API_BASE}/sites/{quote(property_name, safe='')}/searchAnalytics/query"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    rows: list[dict[str, object]] = []
    start_row = 0
    while start_row < max_rows:
        request_body: dict[str, object] = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": dimensions,
            "type": search_type,
            "rowLimit": min(row_limit, max_rows - start_row),
            "startRow": start_row,
        }
        groups = _filters(country, device)
        if groups:
            request_body["dimensionFilterGroups"] = groups
        payload = _http_json(
            url,
            data=json.dumps(request_body).encode("utf-8"),
            headers=headers,
        )
        page_rows = payload.get("rows") or []
        if not isinstance(page_rows, list):
            raise GscApiError("GSC-API lieferte keine gültige rows-Liste.")
        rows.extend(page_rows)
        if len(page_rows) < request_body["rowLimit"]:
            break
        start_row += len(page_rows)
    if len(rows) > max_rows:
        rows = rows[:max_rows]
    return rows


def _number(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _position(value: object) -> str:
    if value is None:
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    if numeric <= 0:
        return ""
    return f"{numeric:.6f}".rstrip("0").rstrip(".")


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def fetch_to_directory(
    credentials: GscCredentials,
    property_name: str,
    start: date,
    end: date,
    out: Path | str,
    *,
    search_type: str = "web",
    country: str | None = None,
    device: str | None = None,
    row_limit: int = 25_000,
    max_rows: int = MAX_ROWS,
    append: bool = False,
) -> GscFetchSummary:
    token = access_token(credentials)
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    period = f"{start.isoformat()}_{end.isoformat()}"
    pages_name = f"{period}_pages.csv"
    queries_name = f"{period}_page_queries.csv"

    page_rows = search_analytics(
        token,
        property_name,
        start,
        end,
        ["page"],
        search_type=search_type,
        country=country,
        device=device,
        row_limit=row_limit,
        max_rows=max_rows,
    )
    query_rows = search_analytics(
        token,
        property_name,
        start,
        end,
        ["page", "query"],
        search_type=search_type,
        country=country,
        device=device,
        row_limit=row_limit,
        max_rows=max_rows,
    )

    page_output: list[list[str]] = []
    for row in page_rows:
        keys = row.get("keys") or []
        if not isinstance(keys, list) or not keys:
            continue
        page_output.append(
            [
                str(keys[0]),
                _number(row.get("clicks")),
                _number(row.get("impressions")),
                _position(row.get("position")),
            ]
        )
    query_output: list[list[str]] = []
    for row in query_rows:
        keys = row.get("keys") or []
        if not isinstance(keys, list) or len(keys) < 2:
            continue
        query_output.append(
            [
                str(keys[0]),
                str(keys[1]),
                _number(row.get("clicks")),
                _number(row.get("impressions")),
                _position(row.get("position")),
            ]
        )
    _write_csv(
        folder / pages_name,
        ["page", "clicks", "impressions", "position"],
        page_output,
    )
    _write_csv(
        folder / queries_name,
        ["page", "query", "clicks", "impressions", "position"],
        query_output,
    )
    period_entry = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "source_format": "gsc_api",
        "pages": pages_name,
        "page_queries": queries_name,
    }
    periods = [period_entry]
    if append:
        try:
            previous_manifest = json.loads(
                (folder / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            previous_manifest = {}
        same_scope = (
            previous_manifest.get("property") == property_name
            and previous_manifest.get("search_type") == search_type
            and (previous_manifest.get("country") or "") == (country or "")
            and (previous_manifest.get("device") or "")
            == (device.upper() if device else "")
        )
        if same_scope:
            existing = previous_manifest.get("periods")
            if isinstance(existing, list):
                periods = [
                    item
                    for item in existing
                    if isinstance(item, dict)
                    and not (
                        item.get("start") == period_entry["start"]
                        and item.get("end") == period_entry["end"]
                    )
                ] + [period_entry]
    manifest = {
        "property": property_name,
        "search_type": search_type,
        "country": country,
        "device": device.upper() if device else None,
        "periods": periods,
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return GscFetchSummary(
        folder=folder,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        pages=len(page_output),
        queries=len(query_output),
    )


def inspect_url(
    credentials: GscCredentials,
    property_name: str,
    inspection_url: str,
    *,
    language_code: str = "de-DE",
) -> dict:
    token = access_token(credentials)
    body = {
        "inspectionUrl": inspection_url,
        "siteUrl": property_name,
        "languageCode": language_code,
    }
    payload = _http_json(
        INSPECTION_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    result = payload.get("inspectionResult")
    if not isinstance(result, dict):
        raise GscApiError("URL-Inspection-Antwort enthält kein inspectionResult.")
    return result


def inspection_markdown(
    result: dict, *, property_name: str, inspection_url: str
) -> str:
    index = result.get("indexStatusResult") or {}
    if not isinstance(index, dict):
        index = {}
    lines = [
        "# GSC URL Inspection",
        "",
        f"**Property:** {property_name}",
        f"**URL:** {inspection_url}",
        "",
        "| Feld | Wert |",
        "| --- | --- |",
    ]
    fields = [
        ("Verdict", result.get("verdict") or index.get("verdict")),
        ("Coverage State", index.get("coverageState")),
        ("Indexing State", index.get("indexingState")),
        ("Robots.txt State", index.get("robotsTxtState")),
        ("Page Fetch State", index.get("pageFetchState")),
        ("Google Canonical", index.get("googleCanonical")),
        ("User Canonical", index.get("userCanonical")),
        ("Last Crawl", index.get("lastCrawlTime")),
    ]
    for label, value in fields:
        lines.append(f"| {label} | {str(value) if value else '–'} |")
    lines.extend(
        [
            "",
            "Die Inspection ist eine Momentaufnahme von Googles gespeichertem Stand. "
            "Sie ersetzt keinen Live-Abruf der Seite.",
            "",
        ]
    )
    return "\n".join(lines)
