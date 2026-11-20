"""GEO and AI-readiness checks based on observable signals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import csv
from pathlib import Path
import sqlite3
from typing import Any

from seoboy.analysis.audit_data import RunData
from seoboy.crawl.http_client import HttpClient, decode_body
from seoboy.infrastructure.config import ProjectConfig
from seoboy.infrastructure.database import connect
from seoboy.shared.robots import RobotsFile
from seoboy.shared.urls import normalize_url
from seoboy.shared.util import excel_safe

AI_BOTS = [
    ("Googlebot", "Google Search"),
    ("Google-Extended", "Google AI training/product token"),
    ("GPTBot", "OpenAI crawler"),
    ("OAI-SearchBot", "OpenAI search"),
    ("PerplexityBot", "Perplexity"),
    ("ClaudeBot", "Anthropic"),
]


class GeoError(RuntimeError):
    """GEO readiness cannot be evaluated."""


@dataclass(frozen=True)
class LlmsInfo:
    url: str
    status: int | None
    content_type: str | None
    size: int
    excerpt: str
    error: str | None = None


@dataclass
class GeoResult:
    bots: dict[str, bool]
    llms: LlmsInfo
    run_id: str | None
    schema_pages: int
    html_pages: int
    h1_missing: int
    thin_pages: int


def _write_csv(path: Path, rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(["bot", "purpose", "allowed"])
        for row in rows:
            writer.writerow([excel_safe(value) for value in row])


def _latest_run(connection, config: ProjectConfig) -> str | None:
    row = connection.execute(
        "SELECT run_id FROM runs WHERE project_id = ? AND status = 'completed' "
        "ORDER BY ended_at DESC, run_id DESC LIMIT 1",
        (config.project_id,),
    ).fetchone()
    return str(row["run_id"]) if row is not None else None


def _llms(client: HttpClient, origin: str) -> LlmsInfo:
    url = origin + "/llms.txt"
    result = client.fetch(url)
    if result.error_code is not None:
        return LlmsInfo(url, result.status_code, result.content_type, 0, "", result.error_code)
    success = bool(
        result.status_code
        and 200 <= result.status_code < 300
        and (result.content_type or "").startswith("text/")
    )
    body = decode_body(result) if success and result.body else ""
    return LlmsInfo(
        url=url,
        status=result.status_code,
        content_type=result.content_type,
        size=len(result.body) if success else 0,
        excerpt=body[:2000],
        error=None if success else f"http_{result.status_code}",
    )


def audit_geo(config: ProjectConfig, out: Path | None = None) -> Path:
    normalized = normalize_url(config.start_url)
    client = HttpClient(
        timeout=config.crawl.request_timeout_seconds,
        max_bytes=config.crawl.max_response_bytes,
    )
    robots_result = client.fetch(normalized.origin + "/robots.txt")
    robots = (
        RobotsFile.parse(decode_body(robots_result))
        if robots_result.status_code and 200 <= robots_result.status_code < 300
        else RobotsFile.parse("")
    )
    path = normalized.path + (f"?{normalized.query}" if normalized.query else "")
    bots = {bot: robots.is_allowed(path, bot) for bot, _ in AI_BOTS}
    llms = _llms(client, normalized.origin)

    run_id: str | None = None
    schema_pages = 0
    html_pages = 0
    h1_missing = 0
    thin_pages = 0
    if config.database.is_file():
        connection = connect(config.database)
        try:
            try:
                run_id = _latest_run(connection, config)
                if run_id is not None:
                    data = RunData(connection, config, run_id)
                    for url_id in data.page_url_ids:
                        observation = data.observation(url_id)
                        if observation is None or "h1_count" not in observation.signals:
                            continue
                        html_pages += 1
                        if observation.signals.get("schema_types"):
                            schema_pages += 1
                        if int(observation.signals.get("h1_count", 0) or 0) == 0:
                            h1_missing += 1
                        if int(observation.signals.get("word_count", 0) or 0) < 300:
                            thin_pages += 1
            except sqlite3.Error:
                run_id = None
        finally:
            connection.close()

    now = datetime.now().astimezone()
    folder = out or (
        Path(config.reports_dir)
        / f"{now:%Y-%m-%d}_{config.project_id}_geo_{now:%Y%m%dT%H%M%S}"
    )
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / "raw_data"
    raw.mkdir(parents=True, exist_ok=True)
    _write_csv(
        raw / "geo_bots.csv",
        [[bot, purpose, "1" if allowed else "0"] for (bot, purpose), allowed in zip(AI_BOTS, bots.values())],
    )
    lines = [
        "# SeoBoy – GEO- und AI-Readiness",
        "",
        f"**Erzeugt:** {now:%Y-%m-%d %H:%M %Z}",
        f"**Start-URL:** {normalized.url}",
        f"**Eigener Lauf:** {run_id or 'kein abgeschlossener Lauf'}",
        "",
        "## Bot-Zugriff",
        "",
        "| Bot | Zweck | robots.txt für Startpfad |",
        "| --- | --- | :---: |",
    ]
    for (bot, purpose), allowed in zip(AI_BOTS, bots.values()):
        lines.append(f"| {bot} | {purpose} | {'erlaubt' if allowed else 'gesperrt'} |")
    lines.extend(
        [
            "",
            "Hinweis: Google-Extended ist ein Produkt-Token und keine Suchmaschinen-Sperre. "
            "Die Auswertung sagt nichts über die Aufnahme in AI-Antworten aus.",
            "",
            "## llms.txt",
            "",
            f"- URL: {llms.url}",
            f"- Status: {llms.status if llms.status is not None else 'nicht erreichbar'}",
            f"- Content-Type: {llms.content_type or '–'}",
            f"- Größe: {llms.size} Bytes",
            *([f"- Fehler: {llms.error}"] if llms.error else []),
        ]
    )
    if llms.excerpt:
        lines.extend(["", "Auszug:", "", llms.excerpt[:1000]])
    lines.extend(
        [
            "",
            "## Content- und Schema-Signale",
            "",
            "| Kennzahl | Wert |",
            "| --- | ---: |",
            f"| HTML-Seiten mit Metriken | {html_pages} |",
            f"| Seiten mit strukturierten Daten | {schema_pages} |",
            f"| H1 fehlt | {h1_missing} |",
            f"| unter 300 Wörtern | {thin_pages} |",
            "",
            "## Grenzen",
            "",
            "Diese Stufe prüft beobachtbare Zugänglichkeit, llms.txt und vorhandene "
            "Content-/Schema-Signale. Sie enthält keine KI-Antwortstichproben, keine "
            "Marken-Erwähnungen und keinen GEO-Score.",
            "",
            "- [Bot-Auswertung](raw_data/geo_bots.csv)",
            "",
        ]
    )
    (folder / "00_GEO_READINESS.md").write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n"
    )
    return folder
