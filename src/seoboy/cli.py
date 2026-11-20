import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from urllib.parse import urlsplit

from seoboy.gsc import api as gsc_api
from seoboy.gsc import importer as gsc_module
from seoboy.gsc import oauth as gsc_oauth
from seoboy.crawl.rendering import RenderingError, render_report
from seoboy.geo.audit import GeoError, audit_geo
from seoboy.local_seo.audit import (
    LocalSeoError,
    audit_locations,
    load_locations,
    load_local_rankings,
    write_local_report,
)
from seoboy.geo.trends import write_geo_trends
from seoboy.geo.sampling import (
    DEFAULT_BASE_URL,
    DEFAULT_BRANDS,
    DEFAULT_COMPETITORS,
    DEFAULT_MODEL,
    GeoSamplingError,
    SamplingConfig,
    load_prompt_set,
    run_sampling,
)
from seoboy.performance.audit import PerformanceError, run_performance
from seoboy.application import runner
from seoboy.analysis.audit_data import RunData
from seoboy.gsc.inspection_store import select_targets, store_error, store_inspection
from seoboy.infrastructure.config import ConfigError, init_config, load_config
from seoboy.crawl.crawler import ResumeError
from seoboy.infrastructure.database import (
    DatabaseError,
    connect,
    migrate_database,
)
from seoboy.reporting.diff_report import DiffError
from seoboy.ai.review import (
    AIReviewError,
    ReviewConfig,
    build_review_packet,
    run_ai_review,
    write_ai_review,
)
from seoboy.backlinks.importer import BacklinkImportError, import_backlinks
from seoboy.backlinks.report import write_backlink_report
from seoboy.monitoring.monitor import run_monitor_check
from seoboy.rankings.competitors import write_competitor_report
from seoboy.rankings.config import KeywordConfigError, load_keywords
from seoboy.rankings.importer import RankingImportError, import_rankings
from seoboy.rankings.report import write_rankings_report
from seoboy.rankings.serp import SerperError, fetch_serper_csv
from seoboy.reporting.run_report import (
    find_report_dir,
    load_report_data,
    render_run_report,
)
from seoboy.infrastructure.env import load_env
from seoboy.gsc.importer import GscError
from seoboy.gsc.api import GscApiError
from seoboy.infrastructure.lock import LockError
from seoboy.infrastructure.doctor import run_doctor
from seoboy.infrastructure.update import UpdateError, apply_update, check_for_update
from seoboy.application.runner import RunnerError
from seoboy.shared.progress import ProgressReporter
from seoboy.shared.version import __version__


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "Datum muss im Format JJJJ-MM-TT angegeben werden."
        ) from None


def _env_choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    value = os.environ.get(name, "").strip().lower()
    return value if value in choices else default


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _add_progress_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--progress",
        choices=["auto", "human", "json", "off"],
        default="auto",
        help="Fortschritt auf stderr: auto, human, json oder off",
    )
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=2.0,
        help="Mindestabstand zwischen Fortschrittsmeldungen in Sekunden",
    )


def _parse_columns(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    mapping: dict[str, str] = {}
    for part in value.split(","):
        key, separator, header = part.partition("=")
        key = key.strip()
        header = header.strip()
        if not separator or not key or not header:
            raise argparse.ArgumentTypeError(
                "Spaltenmapping im Format page=Spalte,clicks=Spalte angeben."
            )
        if key in mapping:
            raise argparse.ArgumentTypeError(f"Spalte '{key}' ist doppelt angegeben.")
        mapping[key] = header
    return mapping


def _gsc_period(args: argparse.Namespace, parser: argparse.ArgumentParser) -> tuple[date, date]:
    if not 1 <= args.gsc_days <= 366:
        parser.error("--gsc-days muss zwischen 1 und 366 liegen.")
    end = args.gsc_end or (date.today() - timedelta(days=1))
    if args.gsc_start is not None:
        start = args.gsc_start
        if args.gsc_end is None:
            end = start + timedelta(days=args.gsc_days - 1)
    else:
        start = end - timedelta(days=args.gsc_days - 1)
    if start > end:
        parser.error("GSC-Startdatum darf nicht nach dem Enddatum liegen.")
    return start, end


def _gsc_property(config, value: str | None) -> str:
    selected = (value or os.environ.get("SEOBOY_GSC_PROPERTY") or "").strip()
    if selected:
        return selected
    return config.start_url.rstrip("/") + "/"


def _build_parser(default_config: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seoboy",
        description="Lokales SEO-Audit für eigene Websites",
    )
    parser.add_argument("--version", action="version", version=f"SeoBoy {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="Projektkonfiguration anlegen")
    init.add_argument("--url", required=True, help="Start-URL der Website")
    init.add_argument("--config", type=Path, default=default_config)

    migrate = commands.add_parser("migrate", help="SQLite-Schema anlegen oder aktualisieren")
    migrate.add_argument("--config", type=Path, default=default_config)

    run = commands.add_parser("run", help="Audit ausführen")
    run.add_argument("--config", type=Path, default=default_config)
    run.add_argument(
        "--gsc-dir",
        type=Path,
        help="Verzeichnis mit GSC-Manifest und CSV-Dateien (manueller Import)",
    )
    run.add_argument(
        "--gsc-credentials",
        type=Path,
        help="GSC-Zugangsdatei; ohne Angabe wird SEOBOY_GSC_CREDENTIALS genutzt",
    )
    run.add_argument(
        "--gsc-property",
        help="GSC-Property; Standard ist die Start-URL mit abschließendem Slash",
    )
    run.add_argument("--gsc-start", type=_parse_date, help="GSC-Startdatum JJJJ-MM-TT")
    run.add_argument("--gsc-end", type=_parse_date, help="GSC-Enddatum JJJJ-MM-TT")
    run.add_argument(
        "--gsc-days",
        type=int,
        default=28,
        help="Zeitraum in Tagen, wenn kein Startdatum gesetzt ist (Standard: 28)",
    )
    run.add_argument(
        "--gsc-compare",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="beim automatischen Abruf zusätzlich den gleich langen Vorzeitraum holen",
    )
    run.add_argument("--resume", metavar="LAUF-ID", help="Pausierten Lauf fortsetzen")
    _add_progress_options(run)
    run.add_argument(
        "--ai-review",
        action="store_true",
        help="nach dem Lauf eine beratende KI-Review erzeugen",
    )
    run.add_argument(
        "--ai-review-model",
        choices=["deepseek-flash", "deepseek-v4-pro"],
        default=_env_choice(
            "SEOBOY_AI_REVIEW_MODEL", "deepseek-flash", ("deepseek-flash", "deepseek-v4-pro")
        ),
    )
    run.add_argument(
        "--ai-review-thinking",
        choices=["disabled", "enabled"],
        default=_env_choice(
            "SEOBOY_AI_REVIEW_THINKING", "disabled", ("disabled", "enabled")
        ),
    )
    run.add_argument(
        "--ai-review-reasoning-effort",
        choices=["none", "low", "high", "max"],
        default=_env_choice(
            "SEOBOY_AI_REVIEW_REASONING_EFFORT",
            "none",
            ("none", "low", "high", "max"),
        ),
    )

    batch = commands.add_parser("batch", help="Mehrere Projekte parallel prüfen")
    batch.add_argument(
        "--config",
        type=Path,
        action="append",
        required=True,
        dest="configs",
        help="Projektkonfiguration; mehrfach angebbar",
    )
    batch.add_argument("--workers", type=int, default=4, help="Parallele Projekte (Standard: 4)")

    benchmark = commands.add_parser(
        "benchmark", help="Eigene Seite mit Wettbewerbern vergleichen"
    )
    benchmark.add_argument("--config", type=Path, default=default_config)
    _add_progress_options(benchmark)
    benchmark.add_argument(
        "--competitor",
        action="append",
        dest="competitors",
        help="Wettbewerbs-URL; mehrfach angebbar",
    )
    benchmark.add_argument(
        "--competitor-url",
        action="append",
        dest="competitor_urls",
        help="Manuell ausgewählte Wettbewerbsseite; mehrfach angebbar",
    )
    benchmark.add_argument(
        "--max-pages", type=int, default=20, help="Seiten je Wettbewerber (Standard: 20)"
    )
    benchmark.add_argument(
        "--full",
        action="store_true",
        help="alle Sitemap-URLs bis zum max-pages-Budget auswerten",
    )
    benchmark.add_argument("--out", type=Path, help="Zielverzeichnis des Vergleichs")

    doctor = commands.add_parser(
        "doctor", help="Umgebung, Konfiguration und optionale Funktionen prüfen"
    )
    doctor.add_argument("--config", type=Path, default=default_config)
    doctor.add_argument(
        "--strict", action="store_true", help="Warnungen als Fehler behandeln"
    )

    gsc_auth = commands.add_parser(
        "gsc-auth", help="Interaktive Search-Console-Anmeldung per OAuth"
    )
    gsc_auth.add_argument(
        "--client-file",
        type=Path,
        help="Google-OAuth-Clientdatei (Desktop-Client)",
    )
    gsc_auth.add_argument("--client-id")
    gsc_auth.add_argument("--client-secret")
    gsc_auth.add_argument("--token-store", type=Path)
    gsc_auth.add_argument("--no-browser", action="store_true")
    gsc_auth.add_argument("--timeout", type=int, default=180)

    gsc_fetch = commands.add_parser(
        "gsc-fetch", help="GSC-Daten über die Search Console API laden"
    )
    gsc_fetch.add_argument("--property", required=True, help="GSC-Property")
    gsc_fetch.add_argument("--start", required=True, type=_parse_date)
    gsc_fetch.add_argument("--end", required=True, type=_parse_date)
    gsc_fetch.add_argument("--out", required=True, type=Path)
    gsc_fetch.add_argument("--credentials", type=Path)
    gsc_fetch.add_argument("--search-type", default="web")
    gsc_fetch.add_argument("--country", help="ISO-3-Ländercode, z. B. deu")
    gsc_fetch.add_argument("--device", choices=["DESKTOP", "MOBILE", "TABLET"])
    gsc_fetch.add_argument("--row-limit", type=int, default=25000)
    gsc_fetch.add_argument("--max-rows", type=int, default=100000)

    inspection = commands.add_parser(
        "url-inspection", help="URL Inspection API für eine URL abfragen"
    )
    inspection.add_argument("--url", help="Einzelne URL; ohne --run erforderlich")
    inspection.add_argument("--run", metavar="LAUF-ID", help="Wichtige URLs eines Laufs prüfen")
    inspection.add_argument("--config", type=Path, default=default_config)
    inspection.add_argument("--property", help="GSC-Property; sonst Start-URL")
    inspection.add_argument("--credentials", type=Path)
    inspection.add_argument("--out", type=Path)
    inspection.add_argument("--language", default="de-DE")
    inspection.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximale Anzahl wichtiger URLs im Batch-Modus (Standard: 10)",
    )

    performance = commands.add_parser(
        "performance", help="PageSpeed/Lighthouse und CrUX abfragen"
    )
    performance.add_argument("--url", required=True)
    performance.add_argument("--out", type=Path)
    performance.add_argument(
        "--strategy", choices=["mobile", "desktop"], default="mobile"
    )
    performance.add_argument(
        "--form-factor", choices=["PHONE", "DESKTOP", "TABLET"], default="PHONE"
    )
    performance.add_argument("--api-key")
    performance.add_argument("--no-lighthouse", action="store_true")
    performance.add_argument("--no-crux", action="store_true")

    ai_review = commands.add_parser(
        "ai-review", help="Gesamtergebnis eines Laufs durch KI prüfen lassen"
    )
    ai_review.add_argument("--config", type=Path, default=default_config)
    ai_review.add_argument("--run", required=True, metavar="LAUF-ID")
    _add_progress_options(ai_review)
    ai_review.add_argument(
        "--model",
        choices=["deepseek-flash", "deepseek-v4-pro"],
        default=_env_choice(
            "SEOBOY_AI_REVIEW_MODEL", "deepseek-flash", ("deepseek-flash", "deepseek-v4-pro")
        ),
    )
    ai_review.add_argument(
        "--thinking",
        choices=["disabled", "enabled"],
        default=_env_choice(
            "SEOBOY_AI_REVIEW_THINKING", "disabled", ("disabled", "enabled")
        ),
    )
    ai_review.add_argument(
        "--reasoning-effort",
        choices=["none", "low", "high", "max"],
        default=_env_choice(
            "SEOBOY_AI_REVIEW_REASONING_EFFORT",
            "none",
            ("none", "low", "high", "max"),
        ),
    )
    ai_review.add_argument("--max-findings", type=int, default=40)
    ai_review.add_argument("--max-actions", type=int, default=25)
    ai_review.add_argument("--max-tokens", type=int, default=4096)
    ai_review.add_argument("--budget-usd", type=float, default=0.25)
    ai_review.add_argument("--timeout", type=float, default=90.0)
    ai_review.add_argument("--no-cache", action="store_true")
    ai_review.add_argument("--refresh", action="store_true")
    ai_review.add_argument("--dry-run", action="store_true")

    geo_sample = commands.add_parser(
        "geo-sample", help="Budgetierte KI-Antwortstichproben über DeepSeek erzeugen"
    )
    geo_sample.add_argument("--prompts", type=Path)
    geo_sample.add_argument("--out", type=Path)
    _add_progress_options(geo_sample)
    geo_sample.add_argument("--api-key")
    geo_sample.add_argument(
        "--model",
        choices=["deepseek-flash", "deepseek-v4-pro"],
        default=_env_choice(
            "SEOBOY_GEO_MODEL", DEFAULT_MODEL, ("deepseek-flash", "deepseek-v4-pro")
        ),
    )
    geo_sample.add_argument("--max-calls", type=int, default=6)
    geo_sample.add_argument("--max-tokens", type=int, default=8192)
    geo_sample.add_argument("--temperature", type=float, default=0.2)
    geo_sample.add_argument(
        "--thinking",
        choices=["disabled", "enabled"],
        default=_env_choice(
            "SEOBOY_GEO_THINKING", "enabled", ("disabled", "enabled")
        ),
    )
    geo_sample.add_argument(
        "--reasoning-effort",
        choices=["none", "low", "high", "max"],
        default=_env_choice(
            "SEOBOY_GEO_REASONING_EFFORT",
            "high",
            ("none", "low", "high", "max"),
        ),
    )
    geo_sample.add_argument(
        "--web-search",
        action=argparse.BooleanOptionalAction,
        default=_env_flag("SEOBOY_GEO_WEB_SEARCH", False),
    )
    geo_sample.add_argument("--search-price", type=float, default=0.75)
    geo_sample.add_argument("--budget-usd", type=float, default=1.00)
    geo_sample.add_argument("--retention-days", type=int, default=30)
    geo_sample.add_argument("--input-price", type=float, default=0.30)
    geo_sample.add_argument("--output-price", type=float, default=1.20)
    geo_sample.add_argument("--domain", default="")
    geo_sample.add_argument("--brand", action="append")
    geo_sample.add_argument("--competitor", action="append")
    geo_sample.add_argument("--timeout", type=float, default=90.0)
    geo_sample.add_argument("--dry-run", action="store_true")

    geo_trends = commands.add_parser(
        "geo-trends", help="Bestehende GEO-Stichproben im Zeitverlauf vergleichen"
    )
    geo_trends.add_argument("--config", type=Path, default=default_config)
    geo_trends.add_argument(
        "--dir", type=Path, action="append", default=[], help="Report-Ordner; mehrfach angebbar"
    )
    geo_trends.add_argument("--out", type=Path)

    geo = commands.add_parser(
        "geo", help="GEO- und AI-Readiness beobachtbar prüfen"
    )
    geo.add_argument("--config", type=Path, default=default_config)
    geo.add_argument("--out", type=Path)

    local = commands.add_parser(
        "local", help="Local-SEO- und NAP-Konsistenz für Standorte prüfen"
    )
    local.add_argument("--locations", type=Path, required=True)
    local.add_argument("--out", type=Path)
    local.add_argument("--timeout", type=float, default=15.0)
    local.add_argument("--interval", type=float, default=0.5)
    local.add_argument(
        "--local-results",
        type=Path,
        help="CSV mit query,location,position,url,source,date",
    )

    render = commands.add_parser(
        "render", help="HTTP-Dokument und Browser-DOM mit Playwright vergleichen"
    )
    render.add_argument(
        "--url", action="append", required=True, dest="urls", help="URL; mehrfach angebbar"
    )
    render.add_argument("--out", type=Path)
    render.add_argument("--timeout-ms", type=int, default=15000)
    render.add_argument(
        "--wait-until",
        choices=["load", "domcontentloaded", "networkidle", "commit"],
        default="networkidle",
    )
    render.add_argument(
        "--browser",
        choices=["chromium", "firefox", "webkit"],
        default="chromium",
    )
    render.add_argument(
        "--engine",
        choices=["auto", "playwright", "chrome"],
        default="auto",
        help="auto nutzt Playwright oder Chrome/Edge als Fallback",
    )

    update = commands.add_parser(
        "update", help="SeoBoy-CLI aus dem Git-Checkout aktualisieren"
    )
    update_mode = update.add_mutually_exclusive_group()
    update_mode.add_argument(
        "--check", action="store_true", help="nur prüfen (Standard)"
    )
    update_mode.add_argument(
        "--apply", action="store_true", help="Update anwenden"
    )
    update.add_argument(
        "--no-install", action="store_true", help="kein pip install ausführen"
    )
    update.add_argument(
        "--repo", type=Path, help="Pfad zum SeoBoy-Git-Checkout"
    )

    backlinks = commands.add_parser(
        "backlinks", help="Backlink-Exporte importieren und Linkchancen auswerten"
    )
    backlink_commands = backlinks.add_subparsers(
        dest="backlinks_command", required=True
    )
    backlink_import = backlink_commands.add_parser(
        "import", help="Backlink-CSV importieren"
    )
    backlink_import.add_argument("--config", type=Path, default=default_config)
    backlink_import.add_argument("--csv", type=Path, required=True)
    backlink_import.add_argument("--out", type=Path)
    backlink_report = backlink_commands.add_parser(
        "report", help="Backlink-Bericht neu schreiben"
    )
    backlink_report.add_argument("--config", type=Path, default=default_config)
    backlink_report.add_argument("--out", type=Path)

    rankings = commands.add_parser(
        "rankings", help="Lokale Keyword-Positionen importieren und auswerten"
    )
    ranking_commands = rankings.add_subparsers(dest="rankings_command", required=True)
    ranking_import = ranking_commands.add_parser(
        "import", help="Keyword-Snapshots aus CSV importieren"
    )
    ranking_import.add_argument("--config", type=Path, default=default_config)
    ranking_import.add_argument("--keywords", type=Path)
    ranking_import.add_argument("--csv", type=Path, required=True)
    ranking_import.add_argument("--results", type=Path)
    ranking_import.add_argument("--out", type=Path)
    ranking_fetch = ranking_commands.add_parser(
        "fetch", help="SERP-Snapshot über Serper erzeugen und importieren"
    )
    ranking_fetch.add_argument("--config", type=Path, default=default_config)
    ranking_fetch.add_argument("--keywords", type=Path)
    ranking_fetch.add_argument("--provider", choices=["serper"], default="serper")
    ranking_fetch.add_argument("--out", type=Path)
    ranking_fetch.add_argument("--max-calls", type=int, default=1)
    ranking_fetch.add_argument("--interval", type=float, default=1.0)
    ranking_fetch.add_argument("--timeout", type=float, default=30.0)
    ranking_report = ranking_commands.add_parser(
        "report", help="Ranking-Bericht aus der Datenbank neu schreiben"
    )
    ranking_report.add_argument("--config", type=Path, default=default_config)
    ranking_report.add_argument("--out", type=Path)
    ranking_competitors = ranking_commands.add_parser(
        "competitors", help="Gespeicherte SERP-Treffer je Suchanfrage gruppieren"
    )
    ranking_competitors.add_argument("--config", type=Path, default=default_config)
    ranking_competitors.add_argument("--out", type=Path)

    monitor = commands.add_parser(
        "monitor", help="Wichtige URLs leichtgewichtig überwachen"
    )
    monitor_commands = monitor.add_subparsers(dest="monitor_command", required=True)
    monitor_check = monitor_commands.add_parser(
        "check", help="Konfigurierte wichtige URLs einmal prüfen"
    )
    monitor_check.add_argument("--config", type=Path, default=default_config)
    monitor_check.add_argument(
        "--url", action="append", default=[], help="Explizite URL; mehrfach angebbar"
    )
    monitor_check.add_argument("--timeout", type=float, default=15.0)

    inspect = commands.add_parser("inspect", help="Einzelne URL prüfen")
    inspect.add_argument("url", help="Zu prüfende URL")
    inspect.add_argument("--config", type=Path, default=default_config)
    _add_progress_options(inspect)

    diff = commands.add_parser("diff", help="Zwei Läufe vergleichen")
    diff.add_argument("--base", required=True, metavar="LAUF-ID", help="Basislauf")
    diff.add_argument("--target", required=True, metavar="LAUF-ID", help="Ziellauf")
    diff.add_argument("--config", type=Path, default=default_config)

    report = commands.add_parser("report", help="Berichte eines gespeicherten Laufs erneut schreiben")
    report.add_argument("--run", required=True, metavar="LAUF-ID")
    report.add_argument("--config", type=Path, default=default_config)

    status = commands.add_parser(
        "action-status", help="Manuellen Status einer Maßnahme pflegen"
    )
    status.add_argument("--config", type=Path, default=default_config)
    status.add_argument("--run", metavar="LAUF-ID")
    status.add_argument("--action-key")
    status.add_argument(
        "--status",
        choices=["open", "in_progress", "done", "ignored"],
    )
    status.add_argument("--note", default="")
    status.add_argument("--list", action="store_true")
    status.add_argument("--history", action="store_true")

    prepare = commands.add_parser(
        "gsc-prepare",
        help="GSC-UI-Seitenexport in das normalisierte CSV-Format überführen",
    )
    prepare.add_argument("--input", type=Path, required=True, help="GSC-Seitenexport (CSV)")
    prepare.add_argument("--out", type=Path, required=True, help="Zielverzeichnis")
    prepare.add_argument("--property", required=True, help="GSC-Property, z. B. sc-domain:example.de")
    prepare.add_argument("--start", required=True, type=_parse_date, help="Startdatum JJJJ-MM-TT")
    prepare.add_argument("--end", required=True, type=_parse_date, help="Enddatum JJJJ-MM-TT")
    prepare.add_argument("--search-type", default="web")
    prepare.add_argument("--country", default=None)
    prepare.add_argument("--device", default=None)
    prepare.add_argument("--delimiter", default=None, help="Trennzeichen: ';', ',' oder '\\t'")
    prepare.add_argument("--decimal", default=None, help="Dezimalzeichen: ',' oder '.'")
    prepare.add_argument(
        "--columns",
        default=None,
        help="Spaltenmapping, z. B. page=Top-Seiten,clicks=Klicks,impressions=Impressionen,position=Durchschnittliche Position",
    )
    return parser


def _load(path: Path):
    return load_config(path)


def main(argv: list[str] | None = None) -> int:
    load_env()
    default_config = Path(os.environ.get("SEOBOY_CONFIG", "seoboy.yaml"))
    parser = _build_parser(default_config)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            init_config(args.config, args.url)
            print(f"Projektkonfiguration angelegt: {args.config}")
            return 0
        if args.command == "migrate":
            config = _load(args.config)
            version = migrate_database(config.database)
            print(f"SQLite-Schema {version} bereit: {config.database}")
            return 0
        if args.command == "run":
            config = _load(args.config)
            reporter = ProgressReporter(args.progress, args.progress_interval)
            reporter.emit(
                stage="vorbereitung",
                message=f"Projekt {config.project_id} vorbereiten",
                force=True,
            )
            if args.resume and (args.gsc_dir or args.gsc_credentials):
                parser.error(
                    "--resume und die GSC-Optionen --gsc-dir/--gsc-credentials "
                    "schließen sich aus."
                )
            if args.resume:
                outcome = runner.resume_project(
                    config, args.resume, progress=reporter.handle
                )
            else:
                gsc_value = args.gsc_dir
                if gsc_value is None:
                    env_gsc = os.environ.get("SEOBOY_GSC_DIR")
                    gsc_value = Path(env_gsc) if env_gsc else None
                if gsc_value is not None and args.gsc_credentials is not None:
                    print(
                        "Hinweis: --gsc-dir hat Vorrang; automatischer GSC-Abruf "
                        "wird übersprungen."
                    )
                gsc_dir = gsc_value.resolve() if gsc_value else None
                temporary_gsc: tempfile.TemporaryDirectory | None = None
                if gsc_dir is None:
                    credential_value = (
                        args.gsc_credentials
                        or os.environ.get("SEOBOY_GSC_CREDENTIALS")
                    )
                    if credential_value:
                        reporter.emit(
                            stage="gsc",
                            message="GSC-Daten über die API abrufen",
                            force=True,
                        )
                        try:
                            credentials = gsc_api.load_credentials(credential_value)
                            start, end = _gsc_period(args, parser)
                            property_name = _gsc_property(config, args.gsc_property)
                            temporary_gsc = tempfile.TemporaryDirectory(
                                prefix="seoboy-gsc-"
                            )
                            summary = gsc_api.fetch_to_directory(
                                credentials,
                                property_name,
                                start,
                                end,
                                Path(temporary_gsc.name),
                            )
                            gsc_dir = Path(temporary_gsc.name)
                            compared = False
                            if args.gsc_compare:
                                previous_end = start - timedelta(days=1)
                                previous_start = previous_end - timedelta(
                                    days=(end - start).days
                                )
                                try:
                                    gsc_api.fetch_to_directory(
                                        credentials,
                                        property_name,
                                        previous_start,
                                        previous_end,
                                        Path(temporary_gsc.name),
                                        append=True,
                                    )
                                    compared = True
                                except GscApiError as error:
                                    print(
                                        "Hinweis: GSC-Vorzeitraum nicht geladen: "
                                        f"{error}",
                                        file=sys.stderr,
                                    )
                            print(
                                f"GSC-API: {summary.pages} Seitenzeilen, "
                                f"{summary.queries} Suchanfrage-Zeilen "
                                f"({summary.period_start} bis {summary.period_end})"
                                + (
                                    " inkl. gleich langem Vorzeitraum."
                                    if compared
                                    else "."
                                )
                            )
                        except GscApiError as error:
                            print(
                                f"Hinweis: GSC-API nicht geladen: {error}",
                                file=sys.stderr,
                            )
                            if temporary_gsc is not None:
                                temporary_gsc.cleanup()
                                temporary_gsc = None
                            gsc_dir = None
                try:
                    outcome = runner.run_project(
                        config, gsc_dir, progress=reporter.handle
                    )
                finally:
                    if temporary_gsc is not None:
                        temporary_gsc.cleanup()
            if args.ai_review and outcome.report_dir is not None:
                review_key = os.environ.get("SEOBOY_GEO_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
                if not review_key:
                    print(
                        "Hinweis: --ai-review ohne DeepSeek-API-Key nicht möglich.",
                        file=sys.stderr,
                    )
                else:
                    reporter.emit(
                        stage="ai-review",
                        message="Beratende KI-Review vorbereiten",
                        force=True,
                    )
                    review_connection = connect(config.database)
                    try:
                        review_outcome = run_ai_review(
                            review_connection,
                            config,
                            outcome.run_id,
                            report_dir=outcome.report_dir,
                            api_key=review_key,
                            review_config=ReviewConfig(
                                model=args.ai_review_model,
                                thinking=args.ai_review_thinking,
                                reasoning_effort=args.ai_review_reasoning_effort,
                            ),
                        )
                        review_path = write_ai_review(review_outcome)
                        runner.rerender_report(config, outcome.run_id)
                        reporter.emit(
                            stage="ai-review",
                            message="KI-Review abgeschlossen",
                            completed=1,
                            total=1,
                            unit="Schritt",
                            force=True,
                        )
                        print(f"KI-Review: {review_path}")
                    except (AIReviewError, OSError) as error:
                        print(f"Hinweis: KI-Review fehlgeschlagen: {error}", file=sys.stderr)
                    finally:
                        review_connection.close()
            for warning in outcome.warnings:
                print(f"Hinweis: {warning}")
            reporter.emit(
                stage="fertig",
                message=outcome.message,
                force=True,
            )
            print(outcome.message)
            if outcome.report_dir is not None:
                print(f"Berichte: {outcome.report_dir}")
            return outcome.exit_code
        if args.command == "batch":
            if args.workers < 1:
                parser.error("--workers muss mindestens 1 sein.")
            configs = [_load(path) for path in args.configs]
            results = runner.run_projects(configs, workers=args.workers)
            exit_code = 0
            for result in results:
                label = result.config.project_id
                if result.error is not None:
                    print(f"[{label}] Fehler: {result.error}", file=sys.stderr)
                    exit_code = 2
                    continue
                outcome = result.outcome
                if outcome is None:
                    print(f"[{label}] Fehler: kein Ergebnis", file=sys.stderr)
                    exit_code = 2
                    continue
                for warning in outcome.warnings:
                    print(f"[{label}] Hinweis: {warning}")
                print(f"[{label}] {outcome.message}")
                if outcome.report_dir is not None:
                    print(f"[{label}] Berichte: {outcome.report_dir}")
                exit_code = max(exit_code, outcome.exit_code)
            return exit_code
        if args.command == "performance":
            api_key = args.api_key or os.environ.get("SEOBOY_PSI_API_KEY") or ""
            if not api_key:
                print(
                    "SeoBoy: Für performance wird ein API-Key benötigt "
                    "(--api-key oder SEOBOY_PSI_API_KEY).",
                    file=sys.stderr,
                )
                return 2
            folder = args.out or (
                Path("reports")
                / f"performance_{datetime.now().astimezone():%Y%m%dT%H%M%S}"
            )
            try:
                run_performance(
                    args.url,
                    api_key=api_key,
                    out=folder,
                    strategy=args.strategy,
                    form_factor=args.form_factor,
                    lighthouse_enabled=not args.no_lighthouse,
                    crux_enabled=not args.no_crux,
                )
            except PerformanceError as error:
                print(f"SeoBoy: {error}", file=sys.stderr)
                return 2
            print(f"Performance-Bericht geschrieben: {folder}")
            return 0
        if args.command == "ai-review":
            config = _load(args.config)
            migrate_database(config.database)
            connection = connect(config.database)
            try:
                report = load_report_data(connection, config, args.run)
                review_config = ReviewConfig(
                    model=args.model,
                    thinking=args.thinking,
                    reasoning_effort=args.reasoning_effort,
                    max_findings=args.max_findings,
                    max_actions=args.max_actions,
                    max_tokens=args.max_tokens,
                    budget_usd=args.budget_usd,
                    use_cache=not args.no_cache,
                    refresh=args.refresh,
                )
                if args.dry_run:
                    packet = build_review_packet(report, review_config)
                    from seoboy.ai.review import packet_hash

                    print(
                        f"KI-Review-Packung: {len(packet['findings'])} Befunde, "
                        f"{len(packet['actions'])} Maßnahmen, "
                        f"{len(packet['data_quality'])} Datenqualitätshinweise, "
                        f"Hash {packet_hash(packet)[:16]}"
                    )
                    return 0
                report_dir = find_report_dir(config, args.run)
                if report_dir is None:
                    report_dir = render_run_report(connection, config, args.run)
                api_key = (
                    os.environ.get("SEOBOY_GEO_API_KEY")
                    or os.environ.get("DEEPSEEK_API_KEY")
                    or ""
                )
                reporter = ProgressReporter(args.progress, args.progress_interval)
                outcome = run_ai_review(
                    connection,
                    config,
                    args.run,
                    report_dir=report_dir,
                    api_key=api_key,
                    review_config=review_config,
                    timeout=args.timeout,
                    progress=reporter.handle,
                )
                path = write_ai_review(outcome)
                reporter.emit(
                    stage="fertig",
                    message="KI-Review geschrieben",
                    completed=1,
                    total=1,
                    unit="Schritt",
                    force=True,
                )
            except (AIReviewError, ValueError) as error:
                print(f"SeoBoy: {error}", file=sys.stderr)
                return 2
            finally:
                connection.close()
            runner.rerender_report(config, args.run)
            print(f"KI-Review geschrieben: {path}")
            print(
                f"Modell: {outcome.model} ({outcome.model_version}), "
                f"Cache: {'Treffer' if outcome.cached else 'neu'}, "
                f"Kosten: {outcome.cost_usd:.6f} USD"
            )
            return 0
        if args.command == "geo-sample":
            try:
                prompt_set = load_prompt_set(args.prompts)
                config = SamplingConfig(
                    model=args.model,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    thinking=args.thinking,
                    reasoning_effort=args.reasoning_effort,
                    web_search=args.web_search,
                    search_usd_per_1000=args.search_price,
                    max_calls=args.max_calls,
                    budget_usd=args.budget_usd,
                    input_usd_per_mtok=args.input_price,
                    output_usd_per_mtok=args.output_price,
                    retention_days=args.retention_days,
                )
            except GeoSamplingError as error:
                print(f"SeoBoy: {error}", file=sys.stderr)
                return 2
            if args.dry_run:
                print(f"Prompt-Set: {prompt_set.version} ({prompt_set.language}/{prompt_set.region})")
                for item in prompt_set.prompts[: config.max_calls]:
                    print(f"- {item.id}: {item.prompt}")
                print(
                    f"Geplant: {min(len(prompt_set.prompts), config.max_calls)} Aufrufe, "
                    f"Modell {config.model}, Thinking {config.thinking}, "
                    f"Effort {config.reasoning_effort}"
                )
                return 0
            api_key = (
                args.api_key
                or os.environ.get("SEOBOY_GEO_API_KEY")
                or os.environ.get("DEEPSEEK_API_KEY")
                or ""
            )
            if not api_key:
                print(
                    "SeoBoy: Für geo-sample wird ein DeepSeek-API-Key benötigt "
                    "(--api-key, SEOBOY_GEO_API_KEY oder DEEPSEEK_API_KEY).",
                    file=sys.stderr,
                )
                return 2
            brands = tuple(
                dict.fromkeys(DEFAULT_BRANDS + tuple(args.brand or ()))
            )
            competitors = tuple(
                dict.fromkeys(DEFAULT_COMPETITORS + tuple(args.competitor or ()))
            )
            folder = args.out or (
                Path("reports")
                / f"geo_sampling_{datetime.now().astimezone():%Y%m%dT%H%M%S}"
            )
            reporter = ProgressReporter(args.progress, args.progress_interval)
            reporter.emit(
                stage="geo-sample",
                message=f"GEO-Sampling mit {config.model} startet",
                completed=0,
                total=min(len(prompt_set.prompts), config.max_calls),
                unit="Prompts",
                force=True,
            )
            try:
                run = run_sampling(
                    api_key=api_key,
                    prompt_set=prompt_set,
                    config=config,
                    out=folder,
                    brands=brands,
                    competitors=competitors,
                    domain=args.domain,
                    base_url=os.environ.get("SEOBOY_GEO_BASE_URL") or DEFAULT_BASE_URL,
                    timeout=args.timeout,
                    progress=reporter.handle,
                )
            except GeoSamplingError as error:
                print(f"SeoBoy: {error}", file=sys.stderr)
                return 2
            reporter.emit(
                stage="fertig",
                message="GEO-Sampling abgeschlossen",
                completed=len(run.samples),
                total=len(run.samples),
                unit="Prompts",
                force=True,
            )
            print(f"GEO-Sampling geschrieben: {folder}")
            print(
                f"Stichproben: {len(run.samples)}, erfolgreich: {run.successful}, "
                f"Fehler: {run.failed}, Tokens: {run.total_tokens}, "
                f"Kosten (Peak-Schätzung): {run.estimated_cost:.6f} USD"
            )
            return 0 if run.successful else 2
        if args.command == "geo-trends":
            config = _load(args.config)
            folder = write_geo_trends(config, args.dir, args.out)
            print(f"GEO-Trends geschrieben: {folder / 'GEO_TRENDS.md'}")
            return 0
        if args.command == "geo":
            config = _load(args.config)
            try:
                folder = audit_geo(config, args.out)
            except GeoError as error:
                print(f"SeoBoy: {error}", file=sys.stderr)
                return 2
            print(f"GEO-Bericht geschrieben: {folder}")
            return 0
        if args.command == "local":
            try:
                locations = load_locations(args.locations)
                results = audit_locations(
                    locations,
                    timeout=args.timeout,
                    interval_seconds=args.interval,
                )
                rankings = (
                    load_local_rankings(args.local_results)
                    if args.local_results
                    else []
                )
                folder = args.out or (
                    Path("reports")
                    / f"local_{datetime.now().astimezone():%Y%m%dT%H%M%S}"
                )
                write_local_report(results, folder, rankings)
            except LocalSeoError as error:
                print(f"SeoBoy: {error}", file=sys.stderr)
                return 2
            print(f"Local-SEO-Bericht geschrieben: {folder}")
            return 0
        if args.command == "render":
            if len(args.urls) > 10:
                parser.error("render unterstützt höchstens 10 URLs pro Aufruf.")
            if args.timeout_ms < 1000:
                parser.error("--timeout-ms muss mindestens 1000 sein.")
            folder = args.out or (
                Path("reports")
                / f"rendering_{datetime.now().astimezone():%Y%m%dT%H%M%S}"
            )
            try:
                render_report(
                    args.urls,
                    out=folder,
                    timeout_ms=args.timeout_ms,
                    wait_until=args.wait_until,
                    browser_name=args.browser,
                    engine=args.engine,
                )
            except RenderingError as error:
                print(f"SeoBoy: {error}", file=sys.stderr)
                return 2
            print(f"Rendering-Vergleich geschrieben: {folder}")
            return 0
        if args.command == "doctor":
            report = run_doctor(args.config)
            print(f"SeoBoy {report.version} – Systemcheck")
            for check in report.checks:
                label = {
                    "ok": "OK",
                    "warning": "HINWEIS",
                    "error": "FEHLER",
                }.get(check.status, check.status.upper())
                print(f"[{label}] {check.name}: {check.detail}")
            errors = len(report.errors)
            warnings = len(report.warnings)
            print(
                f"Ergebnis: {len(report.checks)} Prüfungen, "
                f"{errors} Fehler, {warnings} Hinweise"
            )
            if errors or (args.strict and warnings):
                return 2
            return 0
        if args.command == "gsc-auth":
            if args.client_file:
                client = gsc_oauth.load_client_config(args.client_file)
            elif args.client_id and args.client_secret:
                client = gsc_oauth.OAuthClient(
                    client_id=args.client_id,
                    client_secret=args.client_secret,
                )
            else:
                parser.error(
                    "--client-file oder --client-id und --client-secret sind erforderlich."
                )
            target = gsc_oauth.login(
                client,
                token_store=args.token_store,
                open_browser=not args.no_browser,
                timeout=args.timeout,
            )
            print(f"OAuth-Token gespeichert: {target}")
            return 0
        if args.command == "gsc-fetch":
            credentials = gsc_api.load_credentials(args.credentials)
            summary = gsc_api.fetch_to_directory(
                credentials,
                args.property,
                args.start,
                args.end,
                args.out,
                search_type=args.search_type,
                country=args.country,
                device=args.device,
                row_limit=args.row_limit,
                max_rows=args.max_rows,
            )
            print(f"GSC-Daten geschrieben: {summary.folder}")
            print(
                f"{summary.pages} Seitenzeilen, {summary.queries} Seiten-/Suchanfrage-Zeilen "
                f"für {summary.period_start} bis {summary.period_end}"
            )
            print("Weiter mit: seoboy run --gsc-dir <verzeichnis>")
            return 0
        if args.command == "url-inspection":
            if args.run and args.url:
                parser.error("--run und --url schließen sich aus.")
            credentials = gsc_api.load_credentials(args.credentials)
            if args.run:
                if not 1 <= args.limit <= 100:
                    parser.error("--limit muss zwischen 1 und 100 liegen.")
                config = _load(args.config)
                migrate_database(config.database)
                connection = connect(config.database)
                try:
                    try:
                        data = RunData(connection, config, args.run)
                    except (KeyError, sqlite3.Error) as error:
                        print(f"SeoBoy: Lauf nicht lesbar: {error}", file=sys.stderr)
                        return 2
                    property_name = _gsc_property(config, args.property)
                    targets = select_targets(data, args.limit)
                    if not targets:
                        print("Keine wichtigen HTML-URLs für die Inspection gefunden.")
                        return 0
                    success = 0
                    for url_id, inspection_url in targets:
                        try:
                            result = gsc_api.inspect_url(
                                credentials,
                                property_name,
                                inspection_url,
                                language_code=args.language,
                            )
                        except GscApiError as error:
                            store_error(
                                connection,
                                args.run,
                                url_id,
                                property_name,
                                inspection_url,
                                "inspection_failed",
                                language_code=args.language,
                            )
                            print(
                                f"Hinweis: {inspection_url}: {error}",
                                file=sys.stderr,
                            )
                            continue
                        store_inspection(
                            connection,
                            args.run,
                            url_id,
                            property_name,
                            inspection_url,
                            result,
                            language_code=args.language,
                        )
                        success += 1
                finally:
                    connection.close()
                folder = runner.rerender_report(config, args.run)
                print(
                    f"URL-Inspection: {success} von {len(targets)} URL(s) gespeichert."
                )
                print(f"Berichte geschrieben: {folder}")
                return 0 if success else 2
            if not args.url or not args.property:
                parser.error("Ohne --run sind --url und --property erforderlich.")
            result = gsc_api.inspect_url(
                credentials,
                args.property,
                args.url,
                language_code=args.language,
            )
            folder = args.out or (
                Path("reports")
                / f"url-inspection_{datetime.now().astimezone():%Y%m%dT%H%M%S}"
            )
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "inspection.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            (folder / "00_URL_INSPECTION.md").write_text(
                gsc_api.inspection_markdown(
                    result, property_name=args.property, inspection_url=args.url
                ).rstrip()
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            print(f"URL-Inspection geschrieben: {folder}")
            return 0
        if args.command == "update":
            if args.no_install and not args.apply:
                parser.error("--no-install ist nur mit --apply zulässig.")
            try:
                status = check_for_update(args.repo)
                print(f"Repository: {status.repo}")
                print(f"Branch: {status.branch} -> {status.upstream}")
                print(
                    f"Version: {status.current_version or '?'} -> "
                    f"{status.target_version or '?'}"
                )
                print(
                    f"Commit: {status.current_commit[:10]} -> "
                    f"{status.target_commit[:10]}"
                )
                if status.dirty:
                    print("Lokale Änderungen blockieren ein Update:", file=sys.stderr)
                    for line in status.dirty[:10]:
                        print(f"  {line}", file=sys.stderr)
                    return 2
                if status.ahead > 0 and status.behind > 0:
                    print(
                        "Lokaler Branch und Upstream sind divergiert. "
                        "Bitte manuell zusammenführen.",
                        file=sys.stderr,
                    )
                    return 2
                if args.apply:
                    result = apply_update(args.repo, install=not args.no_install)
                    if not result.updated:
                        if result.status.ahead > 0:
                            print(
                                f"Lokaler Branch ist {result.status.ahead} Commit(s) "
                                "vor dem Upstream; kein Update nötig."
                            )
                        else:
                            print("SeoBoy ist bereits aktuell.")
                    else:
                        print(
                            f"Update angewendet: {result.old_commit[:10]} -> "
                            f"{result.new_commit[:10]} (Version "
                            f"{result.version or 'unbekannt'})"
                        )
                        print(f"Installation: {'ja' if result.installed else 'nein'}")
                        print(f"Smoke-Test: {'ja' if result.verified else 'nein'}")
                    return 0
                if status.behind == 0:
                    print("SeoBoy ist bereits aktuell.")
                elif status.ahead > 0:
                    print(
                        f"Lokaler Branch ist {status.ahead} Commit(s) vor dem Upstream; "
                        "kein Update nötig."
                    )
                else:
                    print(
                        f"{status.behind} Commit(s) hinter dem Upstream. "
                        "Update verfügbar; anwenden mit: seoboy update --apply"
                    )
                return 0
            except UpdateError as error:
                print(f"SeoBoy: {error}", file=sys.stderr)
                return 2
        if args.command == "benchmark":
            config = _load(args.config)
            competitors = list(args.competitors or [])
            selected: dict[str, list[str]] = {}
            for value in args.competitor_urls or []:
                parts = urlsplit(value)
                origin = f"{parts.scheme}://{parts.netloc}/"
                if origin not in competitors:
                    competitors.append(origin)
                selected.setdefault(origin, []).append(value)
            if not competitors:
                parser.error(
                    "Mindestens --competitor oder --competitor-url ist erforderlich."
                )
            reporter = ProgressReporter(args.progress, args.progress_interval)
            reporter.emit(
                stage="benchmark",
                message="Wettbewerber lesend erfassen",
                force=True,
            )
            folder = runner.run_benchmark(
                config,
                competitors,
                max_pages=args.max_pages,
                out=args.out,
                selected_urls=selected or None,
                full=args.full,
                progress=reporter.handle,
            )
            reporter.emit(
                stage="fertig",
                message="Wettbewerbsvergleich geschrieben",
                completed=1,
                total=1,
                unit="Schritt",
                force=True,
            )
            print(f"Wettbewerbsvergleich geschrieben: {folder}")
            return 0
        if args.command == "backlinks":
            config = _load(args.config)
            migrate_database(config.database)
            connection = connect(config.database)
            try:
                if args.backlinks_command == "import":
                    summary = import_backlinks(connection, config, args.csv)
                    print(
                        f"Backlinks importiert: {summary.observations} neu, "
                        f"{summary.skipped} Duplikate."
                    )
                folder = write_backlink_report(connection, config, args.out)
            except BacklinkImportError as error:
                print(f"SeoBoy: {error}", file=sys.stderr)
                return 2
            finally:
                connection.close()
            print(f"Bericht: {folder / 'BACKLINK_OPPORTUNITIES.md'}")
            return 0
        if args.command == "rankings":
            config = _load(args.config)
            migrate_database(config.database)
            connection = connect(config.database)
            try:
                keyword_path = getattr(args, "keywords", None) or (
                    (config.config_path.parent / "keywords.yaml")
                    if config.config_path is not None
                    else Path("keywords.yaml")
                )
                if args.rankings_command == "fetch":
                    if args.max_calls < 1:
                        raise RankingImportError("--max-calls muss mindestens 1 sein.")
                    api_key = os.environ.get("SEOBOY_SERP_API_KEY") or os.environ.get(
                        "SERPER_API_KEY"
                    )
                    if not api_key:
                        raise SerperError(
                            "Kein Serper-Key. Bitte SEOBOY_SERP_API_KEY lokal in .env setzen."
                        )
                    profiles = load_keywords(keyword_path)
                    out = args.out or (
                        config.reports_dir
                        / "serp"
                        / datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
                    )
                    snapshots_path, results_path, stats = fetch_serper_csv(
                        profiles,
                        api_key,
                        out,
                        max_calls=args.max_calls,
                        interval_seconds=args.interval,
                        timeout=args.timeout,
                    )
                    print(
                        f"Serper: {stats['calls']} Aufrufe, "
                        f"{stats['profiles']} Profile, "
                        f"{stats['skipped_mobile']} Mobile übersprungen."
                    )
                    for item in stats["errors"][:3]:
                        print(f"Hinweis: {item}", file=sys.stderr)
                    if not stats["profiles"]:
                        raise SerperError("Keine Profile für den Serper-Lauf ausgewählt.")
                    summary = import_rankings(
                        connection, config, profiles, snapshots_path, results_path
                    )
                    folder = write_rankings_report(connection, config)
                    print(
                        f"Rankings importiert: {summary.snapshots} neu, "
                        f"{summary.snapshots_skipped} identisch, "
                        f"{summary.results} Treffer."
                    )
                elif args.rankings_command == "import":
                    profiles = load_keywords(keyword_path)
                    summary = import_rankings(
                        connection,
                        config,
                        profiles,
                        args.csv,
                        args.results,
                    )
                    folder = write_rankings_report(connection, config, args.out)
                    print(
                        f"Rankings importiert: {summary.snapshots} neu, "
                        f"{summary.snapshots_skipped} identisch, "
                        f"{summary.results} Treffer."
                    )
                elif args.rankings_command == "competitors":
                    folder = write_competitor_report(connection, config, args.out)
                    print("Wettbewerber-Bericht geschrieben.")
                else:
                    folder = write_rankings_report(connection, config, args.out)
                    print("Ranking-Bericht geschrieben.")
            except (KeywordConfigError, RankingImportError, SerperError) as error:
                print(f"SeoBoy: {error}", file=sys.stderr)
                return 2
            finally:
                connection.close()
            print(f"Bericht: {folder}")
            return 0
        if args.command == "monitor":
            config = _load(args.config)
            migrate_database(config.database)
            connection = connect(config.database)
            try:
                folder, checks = run_monitor_check(
                    connection,
                    config,
                    urls=args.url,
                    timeout=args.timeout,
                )
            finally:
                connection.close()
            confirmed = sum(1 for check in checks if check.state == "confirmed")
            suspect = sum(1 for check in checks if check.state == "suspect")
            print(f"Monitor: {len(checks)} URLs, {suspect} verdächtig, {confirmed} bestätigt")
            print(f"Status: {folder}")
            return 0
        if args.command == "inspect":
            config = _load(args.config)
            reporter = ProgressReporter(args.progress, args.progress_interval)
            outcome = runner.inspect_url(
                config, args.url, progress=reporter.handle
            )
            reporter.emit(
                stage="fertig", message=outcome.message, force=True
            )
            print(outcome.message)
            if outcome.report_dir is not None:
                print(f"Berichte: {outcome.report_dir}")
            return outcome.exit_code
        if args.command == "diff":
            config = _load(args.config)
            folder = runner.compare_runs(config, args.base, args.target)
            print(f"Vergleich geschrieben: {folder}")
            return 0
        if args.command == "report":
            config = _load(args.config)
            folder = runner.rerender_report(config, args.run)
            print(f"Berichte geschrieben: {folder}")
            return 0
        if args.command == "action-status":
            config = _load(args.config)
            migrate_database(config.database)
            connection = connect(config.database)
            try:
                run_id = args.run
                if run_id is None:
                    row = connection.execute(
                        "SELECT run_id FROM runs WHERE project_id = ? "
                        "AND status IN ('completed', 'partial') "
                        "ORDER BY ended_at DESC, run_id DESC LIMIT 1",
                        (config.project_id,),
                    ).fetchone()
                    if row is None:
                        print("SeoBoy: Kein abgeschlossener Lauf gefunden.", file=sys.stderr)
                        return 2
                    run_id = str(row["run_id"])
                report = load_report_data(connection, config, run_id)
                action_map = {item.action_key: item for item in report.actions}
                if args.list:
                    if not report.actions:
                        print("Keine Maßnahmen im Lauf.")
                        return 0
                    for item in report.actions:
                        current = item.status or "open"
                        print(
                            f"P{item.priority} | {current} | {item.action_key} | {item.title}"
                        )
                    return 0
                if args.history:
                    if not args.action_key:
                        parser.error("--history benötigt --action-key.")
                    rows = connection.execute(
                        "SELECT status, note, changed_at FROM action_status_history "
                        "WHERE project_id = ? AND action_key = ? "
                        "ORDER BY changed_at DESC LIMIT 50",
                        (config.project_id, args.action_key),
                    )
                    for row in rows:
                        note = f" – {row['note']}" if row["note"] else ""
                        print(f"{row['changed_at']} | {row['status']}{note}")
                    return 0
                if not args.action_key or not args.status:
                    parser.error("Setzen benötigt --action-key und --status.")
                if args.action_key not in action_map:
                    print(
                        f"SeoBoy: Maßnahme '{args.action_key}' kommt im Lauf nicht vor.",
                        file=sys.stderr,
                    )
                    return 2
                changed_at = datetime.now(timezone.utc).isoformat(
                    timespec="microseconds"
                )
                connection.execute(
                    "INSERT INTO action_statuses(project_id, action_key, status, note, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(project_id, action_key) DO UPDATE SET "
                    "status = excluded.status, note = excluded.note, "
                    "updated_at = excluded.updated_at",
                    (
                        config.project_id,
                        args.action_key,
                        args.status,
                        args.note,
                        changed_at,
                    ),
                )
                connection.execute(
                    "INSERT INTO action_status_history(project_id, action_key, status, note, changed_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        config.project_id,
                        args.action_key,
                        args.status,
                        args.note,
                        changed_at,
                    ),
                )
            finally:
                connection.close()
            folder = runner.rerender_report(config, run_id)
            print(f"Status gespeichert; Berichte geschrieben: {folder}")
            return 0
        if args.command == "gsc-prepare":
            summary = gsc_module.prepare_export(
                args.input,
                args.out,
                property_name=args.property,
                start=args.start,
                end=args.end,
                search_type=args.search_type,
                country=args.country,
                device=args.device,
                delimiter=args.delimiter,
                decimal=args.decimal,
                columns=_parse_columns(args.columns),
            )
            print(f"Normalisierte CSV geschrieben: {summary['file']}")
            print(f"Manifest aktualisiert: {summary['manifest']}")
            print(
                f"{summary['rows']} Zeile(n), {summary['unknown_positions']} ohne Position, "
                f"Trennzeichen '{summary['delimiter']}', Dezimalzeichen '{summary['decimal']}'"
            )
            return 0
    except argparse.ArgumentTypeError as error:
        print(f"SeoBoy: {error}", file=sys.stderr)
        return 2
    except (
        ConfigError,
        GscError,
        GscApiError,
        RunnerError,
        ResumeError,
        DiffError,
        DatabaseError,
        LockError,
    ) as error:
        print(f"SeoBoy: {error}", file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error) as error:
        print(f"SeoBoy: {error}", file=sys.stderr)
        return 2
    return 2
