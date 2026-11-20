"""Ablaufsteuerung für run, resume, inspect, report und diff."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sqlite3

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
from seoboy.analysis.rules import RuleResult, evaluate, persist_results
from seoboy.shared.urls import InvalidUrl, is_internal, normalize_url
from seoboy.shared.util import iso_utc


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
