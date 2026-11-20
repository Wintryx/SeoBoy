"""Orchestration for run, resume, inspect, report, and diff."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from seoboy.gsc import importer as gsc
from seoboy.analysis.actions import ActionDraft, build_actions, persist_actions
from seoboy.analysis.audit_data import RunData
from seoboy.infrastructure.config import ProjectConfig
from seoboy.crawl.crawler import (
    Crawler,
    CrawlOutcome,
    ResumeError,
    create_run,
    prepare_resume,
    validate_resume,
)
from seoboy.infrastructure.database import connect, migrate_database, transaction
from seoboy.reporting.diff_report import DiffError, render_diff_report
from seoboy.infrastructure.lock import database_lock
from seoboy.crawl.registry import UrlRegistry
from seoboy.reporting.run_report import render_run_report
from seoboy.benchmark.report import (
    render_benchmark,
    write_benchmark_csv,
    write_benchmark_content_terms_csv,
    write_benchmark_similar_pages_csv,
    write_benchmark_terms_csv,
)
from seoboy.benchmark.sampler import (
    BenchmarkError,
    SiteSnapshot,
    collect_snapshot,
    snapshot_from_run,
)
from seoboy.analysis.rules import RuleResult, evaluate, persist_results
from seoboy.shared.urls import InvalidUrl, is_internal, normalize_url
from seoboy.shared.util import iso_utc
from seoboy.shared.version import TOOL_VERSION


class RunnerError(RuntimeError):
    def __init__(self, message: str, run_id: str | None = None) -> None:
        super().__init__(message)
        self.run_id = run_id


@dataclass
class RunOutcome:
    run_id: str
    status: str
    exit_code: int
    report_dir: Path | None = None
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    findings: int = 0
    actions: int = 0


@dataclass
class BatchResult:
    config: ProjectConfig
    outcome: RunOutcome | None = None
    error: str | None = None


def _open(config: ProjectConfig) -> sqlite3.Connection:
    migrate_database(config.database)
    return connect(config.database)


def _record_failure(connection: sqlite3.Connection, run_id: str, message: str) -> None:
    try:
        with transaction(connection):
            connection.execute(
                "UPDATE runs SET status = 'failed', ended_at = ?, stop_reason = ? "
                "WHERE run_id = ? AND status IN ('running', 'paused')",
                (iso_utc(), message[:200], run_id),
            )
    except sqlite3.Error:
        pass


def _finalize(
    connection: sqlite3.Connection,
    config: ProjectConfig,
    run_id: str,
    outcome: CrawlOutcome,
) -> tuple[str, Path | None, list[RuleResult], list[ActionDraft], str | None]:
    data = RunData(connection, config, run_id)
    try:
        results = evaluate(data)
        actions = build_actions(data, results)
    except Exception as error:
        raise RunnerError(
            f"Lauf {run_id} wurde gecrawlt, aber die Auswertung ist fehlgeschlagen: {error}. "
            f"Der Lauf bleibt speicherbar; bitte erneut mit 'seoboy run --resume {run_id}' "
            "versuchen.",
            run_id=run_id,
        ) from error
    status = "completed" if outcome.status == "complete" else "partial"
    ended_at = iso_utc()
    stop_reason = None if status == "completed" else outcome.stop_reason
    with transaction(connection):
        persist_results(connection, run_id, results)
        persist_actions(connection, run_id, actions)
        connection.execute(
            "UPDATE runs SET status = ?, ended_at = ?, stop_reason = ? WHERE run_id = ?",
            (status, ended_at, stop_reason, run_id),
        )
    try:
        report_dir: Path | None = render_run_report(connection, config, run_id)
    except OSError as error:
        raise RunnerError(
            f"Lauf {run_id} wurde abgeschlossen, aber die Berichte konnten nicht "
            f"geschrieben werden: {error}. Bitte 'seoboy report --run {run_id}' ausführen.",
            run_id=run_id,
        ) from error
    return status, report_dir, results, actions, None


def _summary_message(status: str, results: list[RuleResult], actions: list[ActionDraft]) -> str:
    findings = sum(1 for result in results if result.outcome == "finding")
    unchecked = sum(1 for result in results if result.outcome == "not_checked")
    return (
        f"Status {status}: {findings} Befund(e), {len(actions)} Maßnahme(n), "
        f"{unchecked} ungeprüfte Prüfung(en)."
    )


def run_project(config: ProjectConfig, gsc_dir: Path | None = None) -> RunOutcome:
    if gsc_dir is not None and not gsc_dir.is_dir():
        raise RunnerError(f"GSC-Verzeichnis nicht gefunden: {gsc_dir}")
    connection = _open(config)
    warnings: list[str] = []
    try:
        with database_lock(config.database):
            initial = list(dict.fromkeys([config.start_url, *config.seeds]))
            inputs = {
                "mode": "crawl",
                "seeds": initial,
                "gsc": gsc.describe_inputs(gsc_dir),
            }
            run_id = create_run(
                connection, config, mode="crawl", inputs=inputs, initial_urls=initial
            )
            try:
                registry = UrlRegistry(connection, run_id, config.project_id, config)
                summary = gsc.import_gsc_directory(
                    connection, run_id, config, gsc_dir, registry
                )
            except Exception as error:
                _record_failure(connection, run_id, f"gsc_import_error: {error}")
                raise RunnerError(
                    f"GSC-Import für Lauf {run_id} fehlgeschlagen: {error}",
                    run_id=run_id,
                ) from error
            try:
                if summary.status in {"partial", "unavailable"}:
                    warnings.append(
                        f"GSC-Import {summary.status}: {len(summary.errors)} Fehler; "
                        "Details im Bericht und in source_imports."
                    )
                elif summary.status == "ok":
                    warnings.append(
                        f"GSC-Import ok: {summary.datasets} Datensatz/Datensätze, "
                        f"{summary.metrics} Zeilen."
                    )
                warnings.extend(summary.notes)
                crawler = Crawler(connection, config, run_id, mode="crawl")
                try:
                    outcome = crawler.crawl()
                except Exception as error:
                    raise RunnerError(
                        f"Lauf {run_id} wurde unterbrochen: {error}. Der Lauf bleibt "
                        f"fortsetzbar; bitte 'seoboy run --resume {run_id}' ausführen.",
                        run_id=run_id,
                    ) from error
                if outcome.status == "paused":
                    return RunOutcome(
                        run_id=run_id,
                        status="paused",
                        exit_code=1,
                        message=(
                            f"Lauf {run_id} ist pausiert (Zeitbudget). Fortsetzen mit "
                            f"'seoboy run --resume {run_id}'."
                        ),
                        warnings=warnings,
                    )
                status, report_dir, results, actions, _ = _finalize(
                    connection, config, run_id, outcome
                )
                return RunOutcome(
                    run_id=run_id,
                    status=status,
                    exit_code=0 if status == "completed" else 1,
                    report_dir=report_dir,
                    message=_summary_message(status, results, actions),
                    warnings=warnings,
                    findings=sum(1 for result in results if result.outcome == "finding"),
                    actions=len(actions),
                )
            except Exception:
                raise
    finally:
        connection.close()


def resume_project(config: ProjectConfig, run_id: str) -> RunOutcome:
    connection = _open(config)
    try:
        with database_lock(config.database):
            try:
                validate_resume(connection, config, run_id)
            except ResumeError:
                raise
            prepare_resume(connection, run_id)
            crawler = Crawler(connection, config, run_id, mode="crawl")
            try:
                outcome = crawler.crawl()
            except Exception as error:
                raise RunnerError(
                    f"Fortsetzen von Lauf {run_id} unterbrochen: {error}. Bitte "
                    f"'seoboy run --resume {run_id}' erneut ausführen.",
                    run_id=run_id,
                ) from error
            if outcome.status == "paused":
                return RunOutcome(
                    run_id=run_id,
                    status="paused",
                    exit_code=1,
                    message=(
                        f"Lauf {run_id} ist erneut pausiert (Zeitbudget). Fortsetzen mit "
                        f"'seoboy run --resume {run_id}'."
                    ),
                )
            status, report_dir, results, actions, _ = _finalize(
                connection, config, run_id, outcome
            )
            return RunOutcome(
                run_id=run_id,
                status=status,
                exit_code=0 if status == "completed" else 1,
                report_dir=report_dir,
                message=_summary_message(status, results, actions),
                findings=sum(1 for result in results if result.outcome == "finding"),
                actions=len(actions),
            )
    finally:
        connection.close()


def inspect_url(config: ProjectConfig, url: str) -> RunOutcome:
    try:
        normalized = normalize_url(url, config.crawl.remove_query_params)
    except InvalidUrl as error:
        raise RunnerError(f"Ungültige URL: {error}") from None
    if not is_internal(normalized, config.allowed_hosts):
        raise RunnerError(
            f"Host '{normalized.host}' ist nicht in allowed_hosts enthalten."
        )
    connection = _open(config)
    try:
        with database_lock(config.database):
            inputs = {"mode": "inspect", "target": normalized.url}
            run_id = create_run(
                connection, config, mode="inspect", inputs=inputs,
                initial_urls=[normalized.url],
            )
            registry = UrlRegistry(connection, run_id, config.project_id, config)
            gsc.import_gsc_directory(connection, run_id, config, None, registry)
            crawler = Crawler(connection, config, run_id, mode="inspect")
            try:
                outcome = crawler.crawl()
            except Exception as error:
                _record_failure(connection, run_id, f"inspect_error: {error}")
                raise RunnerError(
                    f"Prüfung von {normalized.url} fehlgeschlagen: {error}", run_id=run_id
                ) from error
            status, report_dir, results, actions, _ = _finalize(
                connection, config, run_id, outcome
            )
            return RunOutcome(
                run_id=run_id,
                status=status,
                exit_code=0 if status == "completed" else 1,
                report_dir=report_dir,
                message=(
                    f"Einzel-URL-Prüfung {normalized.url}: "
                    + _summary_message(status, results, actions)
                ),
                findings=sum(1 for result in results if result.outcome == "finding"),
                actions=len(actions),
            )
    finally:
        connection.close()


def rerender_report(config: ProjectConfig, run_id: str) -> Path:
    connection = _open(config)
    try:
        row = connection.execute(
            "SELECT run_id, status FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RunnerError(f"Lauf '{run_id}' wurde nicht gefunden.")
        if row["status"] not in {"completed", "partial"}:
            raise RunnerError(
                f"Lauf '{run_id}' hat Status '{row['status']}' und kann noch nicht "
                "rendern. Bitte zuerst den Lauf abschließen."
            )
        try:
            return render_run_report(connection, config, run_id)
        except OSError as error:
            raise RunnerError(f"Berichte konnten nicht geschrieben werden: {error}") from error
    finally:
        connection.close()


def run_projects(
    configs: list[ProjectConfig], *, workers: int = 4
) -> list[BatchResult]:
    """Run several projects in parallel; each configuration needs its own DB."""
    if not configs:
        return []
    databases = [os.path.normcase(str(config.database.resolve())) for config in configs]
    if len(set(databases)) != len(databases):
        raise RunnerError(
            "Für den Batch-Modus benötigt jede Konfiguration eine eigene Datenbank. "
            "Mehrere Läufe in derselben SQLite-Datenbank werden nicht parallel gestartet."
        )
    site_owner: dict[tuple[str, int], int] = {}
    for index, config in enumerate(configs):
        parts = urlsplit(config.start_url)
        host = (parts.hostname or "").casefold()
        port = parts.port or (443 if parts.scheme == "https" else 80)
        key = (host, port)
        owner = site_owner.get(key)
        if owner is not None and owner != index:
            raise RunnerError(
                "Batch-Konfigurationen dürfen nicht gleichzeitig dieselbe Website "
                f"prüfen ({host}:{port}). Bitte die Läufe nacheinander starten."
            )
        site_owner[key] = index
    limit = max(1, min(int(workers), len(configs)))
    results: list[BatchResult | None] = [None] * len(configs)
    with ThreadPoolExecutor(max_workers=limit, thread_name_prefix="seoboy-project") as executor:
        futures = {
            executor.submit(run_project, config, None): index
            for index, config in enumerate(configs)
        }
        for future in as_completed(futures):
            index = futures[future]
            config = configs[index]
            try:
                outcome = future.result()
                results[index] = BatchResult(config=config, outcome=outcome)
            except Exception as error:
                results[index] = BatchResult(
                    config=config,
                    error=f"{type(error).__name__}: {error}",
                )
    return [result for result in results if result is not None]


def _latest_completed_run(connection: sqlite3.Connection) -> str | None:
    row = connection.execute(
        "SELECT run_id FROM runs WHERE status = 'completed' "
        "ORDER BY ended_at DESC, run_id DESC LIMIT 1"
    ).fetchone()
    return str(row["run_id"]) if row is not None else None


def _safe_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "project"


def run_benchmark(
    config: ProjectConfig,
    competitors: list[str],
    *,
    max_pages: int = 20,
    out: Path | None = None,
    selected_urls: dict[str, list[str]] | None = None,
) -> Path:
    """Compare the latest own run with read-only competitor samples."""
    if not competitors:
        raise RunnerError("Für den Wettbewerbsvergleich wird mindestens eine URL benötigt.")
    if not 1 <= max_pages <= 100:
        raise RunnerError("--max-pages muss zwischen 1 und 100 liegen.")
    connection = _open(config)
    try:
        run_id = _latest_completed_run(connection)
        if run_id is None:
            raise RunnerError("Es gibt noch keinen abgeschlossenen Lauf für den Vergleich.")
        try:
            own = snapshot_from_run(RunData(connection, config, run_id))
        except BenchmarkError as error:
            raise RunnerError(str(error)) from error
    finally:
        connection.close()

    snapshots: list[SiteSnapshot] = []
    for index, competitor in enumerate(competitors, start=1):
        label = urlsplit(competitor).hostname or f"Wettbewerb {index}"
        if any(snapshot.label == label for snapshot in snapshots):
            label = f"{label} #{index}"
        manual = selected_urls.get(competitor) if selected_urls else None
        try:
            snapshots.append(
                collect_snapshot(
                    competitor,
                    label,
                    max_pages=max_pages,
                    selected_urls=manual,
                )
            )
        except BenchmarkError as error:
            snapshots.append(
                SiteSnapshot(
                    label=label,
                    start_url=competitor,
                    final_url=competitor,
                    error=str(error),
                )
            )
    now = datetime.now().astimezone()
    folder = out or (
        Path(config.reports_dir)
        / f"{now:%Y-%m-%d}_{_safe_label(config.project_id)}_benchmark_{now:%Y%m%dT%H%M%S}"
    )
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / "raw_data"
    raw.mkdir(parents=True, exist_ok=True)
    report = render_benchmark(own, snapshots, run_id=run_id, max_pages=max_pages)
    (folder / "04_COMPETITOR_BENCHMARK.md").write_text(
        report.rstrip() + "\n", encoding="utf-8", newline="\n"
    )
    write_benchmark_csv(raw / "benchmark_pages.csv", [own, *snapshots])
    write_benchmark_terms_csv(raw / "benchmark_terms.csv", own, snapshots)
    write_benchmark_content_terms_csv(
        raw / "benchmark_content_terms.csv", own, snapshots
    )
    write_benchmark_similar_pages_csv(
        raw / "benchmark_similar_pages.csv", [own, *snapshots]
    )
    manifest = {
        "kind": "competitor_benchmark",
        "project_id": config.project_id,
        "own_run_id": run_id,
        "generated_at": iso_utc(),
        "tool_version": TOOL_VERSION,
        "max_pages_per_site": max_pages,
        "manual_urls": {
            snapshot.label: len(snapshot.pages)
            for snapshot in snapshots
            if snapshot.manual
        },
        "files": [
            "04_COMPETITOR_BENCHMARK.md",
            "raw_data/benchmark_pages.csv",
            "raw_data/benchmark_terms.csv",
            "raw_data/benchmark_content_terms.csv",
            "raw_data/benchmark_similar_pages.csv",
        ],
        "sites": [
            {
                "label": snapshot.label,
                "start_url": snapshot.start_url,
                "final_url": snapshot.final_url,
                "error": snapshot.error,
                "pages": len(snapshot.pages),
                "sitemap_urls": snapshot.sitemap_urls,
            }
            for snapshot in [own, *snapshots]
        ],
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return folder


def compare_runs(config: ProjectConfig, base_run_id: str, target_run_id: str) -> Path:
    connection = _open(config)
    try:
        try:
            return render_diff_report(
                connection, config, base_run_id, target_run_id
            )
        except DiffError:
            raise
        except OSError as error:
            raise RunnerError(f"Vergleich konnte nicht geschrieben werden: {error}") from error
    finally:
        connection.close()