import argparse
from datetime import date
import os
from pathlib import Path
import sqlite3
import sys

from seoboy.gsc import importer as gsc_module
from seoboy.application import runner
from seoboy.infrastructure.config import ConfigError, init_config, load_config
from seoboy.crawl.crawler import ResumeError
from seoboy.infrastructure.database import DatabaseError, migrate_database
from seoboy.reporting.diff_report import DiffError
from seoboy.infrastructure.env import load_env
from seoboy.gsc.importer import GscError
from seoboy.infrastructure.lock import LockError
from seoboy.infrastructure.update import UpdateError, apply_update, check_for_update
from seoboy.application.runner import RunnerError
from seoboy.shared.version import __version__


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "Datum muss im Format JJJJ-MM-TT angegeben werden."
        ) from None


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
    run.add_argument("--gsc-dir", type=Path, help="Verzeichnis mit GSC-Manifest und CSV-Dateien")
    run.add_argument("--resume", metavar="LAUF-ID", help="Pausierten Lauf fortsetzen")

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
    benchmark.add_argument(
        "--competitor",
        action="append",
        required=True,
        dest="competitors",
        help="Wettbewerbs-URL; mehrfach angebbar",
    )
    benchmark.add_argument(
        "--max-pages", type=int, default=20, help="Seiten je Wettbewerber (Standard: 20)"
    )
    benchmark.add_argument("--out", type=Path, help="Zielverzeichnis des Vergleichs")

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

    inspect = commands.add_parser("inspect", help="Einzelne URL prüfen")
    inspect.add_argument("url", help="Zu prüfende URL")
    inspect.add_argument("--config", type=Path, default=default_config)

    diff = commands.add_parser("diff", help="Zwei Läufe vergleichen")
    diff.add_argument("--base", required=True, metavar="LAUF-ID", help="Basislauf")
    diff.add_argument("--target", required=True, metavar="LAUF-ID", help="Ziellauf")
    diff.add_argument("--config", type=Path, default=default_config)

    report = commands.add_parser("report", help="Berichte eines gespeicherten Laufs erneut schreiben")
    report.add_argument("--run", required=True, metavar="LAUF-ID")
    report.add_argument("--config", type=Path, default=default_config)

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
            if args.resume and args.gsc_dir:
                parser.error("--resume und --gsc-dir schließen sich aus.")
            if args.resume:
                outcome = runner.resume_project(config, args.resume)
            else:
                gsc_value = args.gsc_dir
                if gsc_value is None:
                    env_gsc = os.environ.get("SEOBOY_GSC_DIR")
                    gsc_value = Path(env_gsc) if env_gsc else None
                gsc_dir = gsc_value.resolve() if gsc_value else None
                outcome = runner.run_project(config, gsc_dir)
            for warning in outcome.warnings:
                print(f"Hinweis: {warning}")
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
            folder = runner.run_benchmark(
                config,
                args.competitors,
                max_pages=args.max_pages,
                out=args.out,
            )
            print(f"Wettbewerbsvergleich geschrieben: {folder}")
            return 0
        if args.command == "inspect":
            config = _load(args.config)
            outcome = runner.inspect_url(config, args.url)
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
    except (ConfigError, GscError, RunnerError, ResumeError, DiffError, DatabaseError, LockError) as error:
        print(f"SeoBoy: {error}", file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error) as error:
        print(f"SeoBoy: {error}", file=sys.stderr)
        return 2
    return 2
