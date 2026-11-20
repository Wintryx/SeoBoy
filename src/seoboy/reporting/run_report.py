"""Markdown and CSV reports for a stored run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import csv
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable

from seoboy.analysis.audit_data import RunData
from seoboy.infrastructure.config import ProjectConfig
from seoboy.analysis.rules import RULE_VERSIONS
from seoboy.reporting.page_analysis import render_page_analysis, write_page_analysis_csv
from seoboy.shared.urls import relative_url
from seoboy.shared.util import (
    excel_safe,
    format_local,
    local_date_from_utc,
    parse_utc,
)
from seoboy.shared.version import TOOL_VERSION

STATUS_LABELS = {
    "running": "Läuft",
    "paused": "Pausiert",
    "completed": "Abgeschlossen",
    "partial": "Teillauf",
    "failed": "Fehlgeschlagen",
}
SEVERITY_LABELS = {
    "critical": "Kritisch",
    "high": "Hoch",
    "medium": "Mittel",
    "low": "Niedrig",
    "info": "Hinweis",
}
CONFIDENCE_LABELS = {"confirmed": "Bestätigt", "plausible": "Plausibel", "hint": "Hinweis"}
EFFORT_LABELS = {"small": "Klein", "medium": "Mittel", "large": "Groß", "unknown": "Unbekannt"}
REASON_LABELS = {
    "url_limit_reached": "URL-Limit erreicht",
    "request_limit_reached": "Anfrage-Limit erreicht",
    "runtime_limit_reached": "Zeitbudget erreicht",
    "robots_disallowed": "durch robots.txt gesperrt",
    "fetch_timeout": "Zeitüberschreitung beim Abruf",
    "fetch_error": "Abruf fehlgeschlagen",
    "http_error": "HTTP-Fehler",
    "missing_gsc_data": "keine passenden GSC-Daten",
    "incomplete_link_graph": "Linkgraph unvollständig",
    "non_html_document": "kein HTML-Dokument",
    "expected_non_indexable": "laut Profil nicht indexierbar",
    "canonical_duplicate_variant": "Canonical-Variante",
    "not_fetched": "nicht abgerufen",
    "empty_body": "leerer Antwortkörper",
    "redirected_url": "Weiterleitung",
    "redirect_target_not_checked": "Weiterleitungsziel nicht geprüft",
    "canonical_target_not_checked": "Canonical-Ziel nicht geprüft",
    "canonical_target_not_seen": "Canonical-Ziel nicht im Lauf",
    "external_canonical_target": "externes Canonical-Ziel",
    "robots_unreachable": "robots.txt nicht verfügbar",
    "single_page_scope": "Einzel-URL-Prüfung ohne Seitenvergleich",
    "inspect_single_url": "Einzel-URL-Prüfung",
    "missing_position": "Position fehlt",
    "missing_comparison_period": "kein Vergleichszeitraum",
    "missing_comparison_row": "Vergleichszeile fehlt",
    "access_restricted": "Zugriff beschränkt",
    "target_server_error": "Ziel liefert Serverfehler",
    "target_not_fetched": "Ziel nicht abgerufen",
    "target_robots_disallowed": "Ziel durch robots.txt gesperrt",
    "target_fetch_timeout": "Ziel-Zeitüberschreitung",
    "target_fetch_error": "Ziel-Abruf fehlgeschlagen",
    "excluded_target": "Ziel ausgeschlossen",
    "excluded_by_config": "durch Konfiguration ausgeschlossen",
    "title_absent": "kein Titel vorhanden",
    "description_absent": "keine Meta-Beschreibung vorhanden",
    "invalid_sitemap": "ungültige Sitemap",
    "fetch_interrupted": "Abruf unterbrochen",
    "redirect_hop_limit": "Redirect-Hop-Grenze erreicht",
    "url_missing": "URL fehlt",
    "external_target": "externes Ziel",
}
OUTCOME_LABELS = {
    "pass": "Bestanden",
    "finding": "Befund",
    "not_checked": "Ungeprüft",
    "not_applicable": "Nicht anwendbar",
}
SOURCE_LABELS = {
    "http": "HTTP-Abruf",
    "page_observation": "HTML-Extrakt",
    "import": "GSC-Import",
    "crawl": "Crawl-Daten",
    "config": "Projektkonfiguration",
}


@dataclass
class StoredResult:
    rule_id: str
    subject_key: str
    subject_kind: str
    rule_version: str
    subcheck: str
    scope_key: str
    outcome: str
    severity: str | None
    confidence: str | None
    reason_code: str | None
    exception: dict[str, Any] | None
    urls: list[tuple[int, str]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.rule_id, self.subject_key)


@dataclass
class StoredAction:
    action_key: str
    priority: int
    effort: str
    title: str
    proposed_fix: str
    expected_effect: str
    verification: str
    finding_keys: list[tuple[str, str]] = field(default_factory=list)

    @property
    def rule_id(self) -> str:
        return self.finding_keys[0][0] if self.finding_keys else ""


@dataclass
class ReportData:
    data: RunData
    results: list[StoredResult]
    actions: list[StoredAction]

    @property
    def result_map(self) -> dict[tuple[str, str], StoredResult]:
        return {result.key: result for result in self.results}

    def findings(self, rule_id: str | None = None) -> list[StoredResult]:
        return [
            result
            for result in self.results
            if result.outcome == "finding" and (rule_id is None or result.rule_id == rule_id)
        ]


def load_report_data(connection: sqlite3.Connection, config: ProjectConfig, run_id: str) -> ReportData:
    data = RunData(connection, config, run_id)
    results: dict[tuple[str, str], StoredResult] = {}
    for row in connection.execute(
        "SELECT rule_id, subject_key, subject_kind, rule_version, subcheck, scope_key, "
        "outcome, severity, confidence, reason_code, exception_json FROM rule_results "
        "WHERE run_id = ? ORDER BY rule_id, subject_key",
        (run_id,),
    ):
        try:
            exception = json.loads(row["exception_json"]) if row["exception_json"] else None
        except (TypeError, ValueError):
            exception = None
        result = StoredResult(
            rule_id=row["rule_id"],
            subject_key=row["subject_key"],
            subject_kind=row["subject_kind"],
            rule_version=row["rule_version"],
            subcheck=row["subcheck"],
            scope_key=row["scope_key"],
            outcome=row["outcome"],
            severity=row["severity"],
            confidence=row["confidence"],
            reason_code=row["reason_code"],
            exception=exception if isinstance(exception, dict) else None,
        )
        results[result.key] = result
    for row in connection.execute(
        "SELECT rule_id, subject_key, url_id, relation FROM result_urls WHERE run_id = ?",
        (run_id,),
    ):
        result = results.get((row["rule_id"], row["subject_key"]))
        if result is not None:
            result.urls.append((int(row["url_id"]), row["relation"]))
    for row in connection.execute(
        "SELECT rule_id, subject_key, ordinal, source_kind, attempt_id, observation_id, "
        "import_id, observed_at, facts_json FROM rule_evidence WHERE run_id = ? "
        "ORDER BY rule_id, subject_key, ordinal",
        (run_id,),
    ):
        result = results.get((row["rule_id"], row["subject_key"]))
        if result is None:
            continue
        try:
            facts = json.loads(row["facts_json"])
        except (TypeError, ValueError):
            facts = {}
        result.evidence.append(
            {
                "source_kind": row["source_kind"],
                "attempt_id": row["attempt_id"],
                "observation_id": row["observation_id"],
                "import_id": row["import_id"],
                "observed_at": row["observed_at"],
                "facts": facts if isinstance(facts, dict) else {},
            }
        )
    actions: list[StoredAction] = []
    action_map: dict[str, StoredAction] = {}
    for row in connection.execute(
        "SELECT action_key, priority, effort, title, proposed_fix, expected_effect, "
        "verification FROM actions WHERE run_id = ? ORDER BY priority, action_key",
        (run_id,),
    ):
        action = StoredAction(
            action_key=row["action_key"],
            priority=int(row["priority"]),
            effort=row["effort"],
            title=row["title"],
            proposed_fix=row["proposed_fix"],
            expected_effect=row["expected_effect"],
            verification=row["verification"],
        )
        actions.append(action)
        action_map[action.action_key] = action
    for row in connection.execute(
        "SELECT action_key, rule_id, subject_key FROM action_findings WHERE run_id = ?",
        (run_id,),
    ):
        action = action_map.get(row["action_key"])
        if action is not None:
            action.finding_keys.append((row["rule_id"], row["subject_key"]))
    return ReportData(data=data, results=list(results.values()), actions=actions)


def _page_counts(data: RunData) -> dict[str, int]:
    counts = {
        "discovered": 0,
        "checked": 0,
        "blocked": 0,
        "excluded": 0,
        "deferred": 0,
        "open": 0,
        "admitted": 0,
        "external_references": 0,
    }
    for url_id, info in data.urls.items():
        if url_id in data.aux_url_ids and url_id not in data.page_url_ids:
            continue
        if info.state == "excluded" and info.reason_code == "host_not_allowed":
            counts["external_references"] += 1
            continue
        counts["discovered"] += 1
        if info.admitted_at:
            counts["admitted"] += 1
        if info.state == "finished":
            counts["checked"] += 1
        elif info.state == "blocked":
            counts["blocked"] += 1
        elif info.state == "excluded":
            counts["excluded"] += 1
        elif info.state == "deferred":
            counts["deferred"] += 1
        else:
            counts["open"] += 1
    return counts


def _coverage(results: list[StoredResult]) -> dict[str, dict[str, Any]]:
    coverage: dict[str, dict[str, Any]] = {}
    for result in results:
        bucket = coverage.setdefault(
            result.rule_id,
            {
                "checked_urls": set(),
                "findings": 0,
                "passes": 0,
                "not_checked": {},
                "not_applicable": 0,
                "scopes": {},
            },
        )
        if result.outcome in {"pass", "finding"}:
            for url_id, _relation in result.urls:
                bucket["checked_urls"].add(url_id)
                bucket["scopes"].setdefault(result.scope_key, set()).add(url_id)
            if result.outcome == "finding":
                bucket["findings"] += 1
            else:
                bucket["passes"] += 1
        elif result.outcome == "not_checked":
            reason = result.reason_code or "unbekannt"
            bucket["not_checked"][reason] = bucket["not_checked"].get(reason, 0) + 1
        elif result.outcome == "not_applicable":
            bucket["not_applicable"] += 1
    return coverage


def _basis_for_scope(coverage: dict[str, dict[str, Any]], rule_id: str, scope_key: str) -> int:
    bucket = coverage.get(rule_id)
    return len(bucket["scopes"].get(scope_key, set())) if bucket else 0


def _severity(result: StoredResult) -> str:
    return SEVERITY_LABELS.get(result.severity or "", result.severity or "–")


def _confidence(result: StoredResult) -> str:
    return CONFIDENCE_LABELS.get(result.confidence or "", result.confidence or "–")


def _reason_label(code: str | None) -> str:
    return REASON_LABELS.get(code or "", code or "ohne Grund")


def _display(data: RunData, url: str) -> str:
    return relative_url(url, data.config.allowed_hosts)


def _result_urls(data: RunData, result: StoredResult, relation: str | None = None) -> list[str]:
    urls: list[str] = []
    for url_id, url_relation in result.urls:
        if relation is not None and url_relation != relation:
            continue
        value = data.url_string(url_id)
        if value not in urls:
            urls.append(value)
    return urls


def _evidence_summary(result: StoredResult, limit: int = 3) -> str:
    summaries: list[str] = []
    for evidence in result.evidence:
        summary = evidence.get("facts", {}).get("summary")
        if summary and summary not in summaries:
            summaries.append(str(summary))
        if len(summaries) >= limit:
            break
    return "; ".join(summaries) if summaries else "–"


def _finding_label(data: RunData, finding: StoredResult) -> str:
    affected = _result_urls(data, finding, "affected")
    urls = affected[:2] if affected else _result_urls(data, finding)[:2]
    label = ", ".join(_display(data, url) for url in urls) or finding.subject_key
    if finding.subject_kind == "query":
        query = ""
        for evidence in finding.evidence:
            value = evidence.get("facts", {}).get("query")
            if value:
                query = str(value)
                break
        if query:
            label += f" (Suchanfrage »{query}«)"
    return label


def _first_observed(result: StoredResult) -> str:
    for evidence in result.evidence:
        if evidence.get("observed_at"):
            return str(evidence["observed_at"])
    return ""


def _source_label(result: StoredResult) -> str:
    labels: list[str] = []
    for evidence in result.evidence:
        label = SOURCE_LABELS.get(str(evidence.get("source_kind")), str(evidence.get("source_kind")))
        if label not in labels:
            labels.append(label)
    return ", ".join(labels) if labels else "–"


def _md(value: Any) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def _safe_project(project_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", project_id).strip("._")
    return cleaned or "project"


def _write_csv(path: Path, header: list[str], rows: Iterable[Iterable[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow([excel_safe(value) for value in row])


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def render_run_report(
    connection: sqlite3.Connection,
    config: ProjectConfig,
    run_id: str,
    reports_dir: Path | None = None,
) -> Path:
    report = load_report_data(connection, config, run_id)
    data = report.data
    run = data.run
    base_dir = Path(reports_dir) if reports_dir is not None else config.reports_dir
    day = local_date_from_utc(run["started_at"])
    folder = base_dir / f"{day.isoformat()}_{_safe_project(run['project_id'])}_{run_id}"
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / "raw_data"
    raw.mkdir(parents=True, exist_ok=True)

    counts = _page_counts(data)
    coverage = _coverage(report.results)
    requests = len(data.attempts)
    aux_urls = len(data.aux_url_ids)
    actions = report.actions
    wins: list[StoredAction] = []
    for action in actions:
        if action.priority != 2 or action.effort != "small":
            continue
        keys = [key for key in action.finding_keys if key in report.result_map]
        if keys and all(report.result_map[key].confidence == "confirmed" for key in keys):
            wins.append(action)
        if len(wins) >= 5:
            break

    _write_text(folder / "00_EXECUTIVE_SUMMARY.md", _executive_summary(report, counts, requests, aux_urls, wins))
    _write_text(folder / "01_ACTION_PLAN_PRIORITIZED.md", _action_plan(report, coverage, wins))
    _write_text(folder / "02_TECHNICAL_SEO_AUDIT.md", _technical_audit(report, coverage, counts, requests))
    _write_text(folder / "03_PAGE_ANALYSIS.md", render_page_analysis(data))
    _write_all_urls_csv(raw / "all_urls.csv", report)
    write_page_analysis_csv(raw / "pages.csv", data)
    _write_rule_results_csv(raw / "rule_results.csv", report)
    _write_broken_links_csv(raw / "broken_links.csv", report)
    if data.datasets:
        _write_gsc_metrics_csv(raw / "gsc_metrics.csv", report)

    coverage_payload = {
        "discovered_pages": counts["discovered"],
        "admitted_pages": counts["admitted"],
        "checked_pages": counts["checked"],
        "blocked_pages": counts["blocked"],
        "excluded_pages": counts["excluded"],
        "external_references": counts["external_references"],
        "deferred_pages": counts["deferred"],
        "open_pages": counts["open"],
        "auxiliary_urls": aux_urls,
        "requests": requests,
        "max_urls": int(run["max_urls"]),
        "max_requests": int(run["max_requests"]),
    }
    manifest = {
        "run_id": run_id,
        "project_id": run["project_id"],
        "site_id": run["site_id"],
        "mode": run["mode"],
        "status": run["status"],
        "stop_reason": run["stop_reason"],
        "started_at": run["started_at"],
        "ended_at": run["ended_at"],
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tool_version": TOOL_VERSION,
        "crawler_version": run["crawler_version"],
        "ruleset_version": run["ruleset_version"],
        "normalization_version": run["normalization_version"],
        "config_hash": run["config_hash"],
        "crawl": {**config.canonical_dict()["crawl"], "link_depth_limit": config.link_depth_limit},
        "coverage": coverage_payload,
        "data_sources": [
            {
                "module": item["module"],
                "provider": item["provider"],
                "status": item["status"],
                "captured_at": item["captured_at"],
                "metadata": item["metadata"],
            }
            for item in data.source_imports
        ],
        "files": [
            "00_EXECUTIVE_SUMMARY.md",
            "01_ACTION_PLAN_PRIORITIZED.md",
            "02_TECHNICAL_SEO_AUDIT.md",
            "03_PAGE_ANALYSIS.md",
            "manifest.json",
            "raw_data/all_urls.csv",
            "raw_data/pages.csv",
            "raw_data/rule_results.csv",
            "raw_data/broken_links.csv",
            *(["raw_data/gsc_metrics.csv"] if data.datasets else []),
        ],
    }
    _write_text(folder / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return folder


def _executive_summary(
    report: ReportData,
    counts: dict[str, int],
    requests: int,
    aux_urls: int,
    wins: list[StoredAction],
) -> str:
    data = report.data
    run = data.run
    priority_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for action in report.actions:
        priority_counts[action.priority] = priority_counts.get(action.priority, 0) + 1
    findings = report.findings()
    lines = [
        "# SeoBoy – Executive Summary",
        "",
        f"**Projekt:** {run['project_id']}  ",
        f"**Lauf:** `{run['run_id']}`  ",
        f"**Status:** {STATUS_LABELS.get(run['status'], run['status'])}"
        + (f" – {_reason_label(run['stop_reason'])}" if run["stop_reason"] else "") + "  ",
        f"**Modus:** {run['mode']}  ",
        f"**Start-URL:** {data.config.start_url}  ",
        f"**Zeitraum:** {format_local(parse_utc(run['started_at']))}"
        + (f" bis {format_local(parse_utc(run['ended_at']))}" if run["ended_at"] else "") + "  ",
        "",
        "## Abdeckung",
        "",
        "| Kennzahl | Wert |",
        "| --- | --- |",
        f"| entdeckte interne Seiten | {counts['discovered']} |",
        f"| zum Seitenbudget zugelassen | {counts['admitted']} von {run['max_urls']} |",
        f"| abgerufen (geprüft) | {counts['checked']} |",
        f"| gesperrt | {counts['blocked']} |",
        f"| ausgeschlossen | {counts['excluded']} |",
        f"| externe Referenzen | {counts['external_references']} |",
        f"| zurückgestellt | {counts['deferred']} |",
        f"| offen | {counts['open']} |",
        f"| HTTP-Anfragen | {requests} von {run['max_requests']} |",
        f"| Hilfs-URLs (robots/Sitemap) | {aux_urls} |",
        "",
    ]
    if run["status"] == "partial":
        lines.extend(
            [
                "> **Teillauf:** Nicht alle entdeckten URLs wurden geprüft. "
                f"Abbruchgrund: {_reason_label(run['stop_reason'])}. "
                "Die Abdeckung ist in Teil 2 je Regel ausgewiesen.",
                "",
            ]
        )
    lines.extend(["## Datenquellen", ""])
    if data.source_imports:
        for source in data.source_imports:
            meta = source["metadata"]
            detail = []
            if meta.get("property"):
                detail.append(f"Property {meta['property']}")
            if meta.get("periods"):
                periods = ", ".join(f"{item['start']}–{item['end']}" for item in meta["periods"])
                detail.append(f"Zeiträume {periods}")
            if meta.get("mapping"):
                mapping = meta["mapping"]
                detail.append(
                    f"Zuordnung {mapping.get('matched', 0)} passend, "
                    f"{mapping.get('unmatched', 0)} nicht zuordenbar, "
                    f"{mapping.get('ambiguous', 0)} mehrdeutig"
                )
            lines.append(
                f"- **{source['provider']}** ({source['module']}): Status {source['status']}"
                + (f" – {'; '.join(detail)}" if detail else "")
            )
            for note in meta.get("notes", [])[:3]:
                lines.append(f"  - {note}")
    else:
        lines.append("- Keine Datenquellen importiert.")
    documents = _sitemap_documents(data)
    lines.append(
        f"- **Sitemaps:** {len(documents)} Dokument(e)"
        + (
            ": " + ", ".join(f"{_display(data, url)} ({status})" for url, status in documents[:5])
            if documents
            else ""
        )
    )
    lines.extend(
        [
            "",
            "## Maßnahmen",
            "",
            f"- P1 Blocker: **{priority_counts.get(1, 0)}**",
            f"- P2 Zeitnah: **{priority_counts.get(2, 0)}**",
            f"- P3 Prüfen/verbessern: **{priority_counts.get(3, 0)}**",
            f"- P4 Pflege: **{priority_counts.get(4, 0)}**",
            f"- Befunde gesamt: **{len(findings)}**",
            "",
            "### Wichtigste offene Maßnahmen",
            "",
        ]
    )
    if report.actions:
        for index, action in enumerate(report.actions[:10], start=1):
            lines.append(f"{index}. **P{action.priority} – {action.title}** ({_effort_label(action.effort)})")
    else:
        lines.append("Keine Maßnahmen aus Befunden abgeleitet.")
    lines.extend(["", "### Quick Wins", ""])
    if wins:
        for action in wins:
            lines.append(f"- **P{action.priority} – {action.title}** ({_effort_label(action.effort)})")
    else:
        lines.append("Keine bestätigten P2-Maßnahmen mit geringem Aufwand.")
    lines.extend(
        [
            "",
            "## Berichte",
            "",
            "- [Maßnahmenplan](01_ACTION_PLAN_PRIORITIZED.md)",
            "- [Technischer Audit](02_TECHNICAL_SEO_AUDIT.md)",
            "- [Unterseiten- und Inhaltsanalyse](03_PAGE_ANALYSIS.md)",
            "- [Maschinenlesbare Daten](raw_data/) und [Manifest](manifest.json)",
            "",
        ]
    )
    return "\n".join(lines)


def _effort_label(effort: str) -> str:
    return EFFORT_LABELS.get(effort, effort)


def _sitemap_documents(data: RunData) -> list[tuple[str, str]]:
    documents: list[tuple[str, str]] = []
    for job in data.jobs:
        if job["purpose"] != "sitemap":
            continue
        info = data.urls.get(int(job["url_id"]))
        if info is None:
            continue
        status = (
            data.last_attempt(info.url_id).status_code
            if data.last_attempt(info.url_id) is not None
            else None
        )
        if status is None:
            attempt = data.last_attempt(info.url_id)
            label = attempt.error_code if attempt and attempt.error_code else job["state"]
        else:
            label = f"HTTP {status}"
        documents.append((info.url, str(label)))
    return documents


def _action_plan(
    report: ReportData,
    coverage: dict[str, dict[str, Any]],
    wins: list[StoredAction],
) -> str:
    data = report.data
    lines = [
        "# SeoBoy – Priorisierter Maßnahmenplan",
        "",
        "Die Priorität folgt der Dringlichkeit (P1 bis P4). Innerhalb einer Klasse sortieren "
        "Beleglage, Geschäftsbedeutung, Reichweite und Aufwand. Befunddetails und CSV-Exporte "
        "stehen in [02_TECHNICAL_SEO_AUDIT.md](02_TECHNICAL_SEO_AUDIT.md) und "
        "[raw_data/rule_results.csv](raw_data/rule_results.csv).",
        "",
    ]
    if wins:
        lines.extend(["## Quick Wins", ""])
        for action in wins:
            lines.append(f"- **P{action.priority} – {action.title}** · Aufwand {_effort_label(action.effort)}")
        lines.append("")
    if not report.actions:
        lines.extend(["Keine Maßnahmen aus Befunden abgeleitet.", ""])
        return "\n".join(lines)
    result_map = report.result_map
    for action in report.actions:
        findings = [
            result_map[key]
            for key in action.finding_keys
            if key in result_map and result_map[key].outcome == "finding"
        ]
        if not findings:
            continue
        affected: list[str] = []
        for finding in findings:
            for url in _result_urls(data, finding, "affected"):
                if url not in affected:
                    affected.append(url)
        if not affected:
            for finding in findings:
                for url in _result_urls(data, finding):
                    if url not in affected:
                        affected.append(url)
        first = findings[0]
        basis = _basis_for_scope(coverage, first.rule_id, first.scope_key)
        if first.rule_id == "LINK_BROKEN":
            sources: list[str] = []
            targets: list[str] = []
            for finding in findings:
                for url_id, relation in finding.urls:
                    bucket = sources if relation == "source" else targets if relation == "target" else None
                    if bucket is None:
                        continue
                    value = data.url_string(url_id)
                    if value not in bucket:
                        bucket.append(value)
            source_text = ", ".join(_display(data, url) for url in sources[:5]) or "–"
            target_text = ", ".join(_display(data, url) for url in targets[:5]) or "–"
            example_text = f"Quellen: {source_text} · Ziele: {target_text}"
            betroffen_text = (
                f"{len(sources)} Quellseite(n), {len(targets)} Ziel(e); Bezugsgröße "
                f"{basis or len(sources)} geprüfte Objekte im Linkgraphen"
            )
        else:
            examples = [_display(data, url) for url in affected[:10]]
            example_text = ", ".join(examples) if examples else "–"
            if len(affected) > 10:
                example_text += f" … ({len(affected)} betroffene URLs, 10 von {len(affected)} gezeigt)"
            betroffen_text = (
                f"{len(affected)} von {basis or len(affected)} geprüften Objekten im "
                f"Geltungsbereich {first.scope_key}"
            )
        observed = _first_observed(first)
        lines.extend(
            [
                f"### P{action.priority} – {action.title}",
                "",
                f"- **Regel und ID:** {first.rule_id} · {action.action_key}",
                f"- **Betroffen:** {example_text} · {betroffen_text}",
                f"- **Evidenz:** {_evidence_summary(first)}",
                f"- **Datenquelle und Messzeit:** {_source_label(first)}"
                + (f", beobachtet {format_local(parse_utc(observed))}" if observed else ""),
                f"- **Schweregrad und Beleglage:** {_severity(first)}, {_confidence(first)}",
                f"- **Einordnung:** Geschäftliche Bedeutung {_business_value(data, findings)}"
                + (
                    f"; Segment {first.scope_key}"
                    if first.rule_id.startswith("GSC_")
                    else (
                        f"; Seitentyp {first.scope_key}"
                        if first.scope_key not in {"internal_links", "sitemap", "gsc", "inspect"}
                        else ""
                    )
                ),
                f"- **Änderung:** {action.proposed_fix}",
                f"- **Erwartete Wirkung:** {action.expected_effect}",
                f"- **Erneut prüfen:** {action.verification}",
                f"- **Aufwand:** {_effort_label(action.effort)}",
                f"- **Befunde:** {len(findings)}",
                "",
            ]
        )
        if len(findings) > 1:
            lines.extend(["Beispiele:", ""])
            for finding in findings[:10]:
                urls = _result_urls(data, finding)
                label = ", ".join(_display(data, url) for url in urls[:2])
                lines.append(f"- {label} – {_evidence_summary(finding, limit=1)}")
            if len(findings) > 10:
                lines.append(f"- … {len(findings) - 10} weitere Befunde laut CSV")
            lines.append("")
    return "\n".join(lines)


def _business_value(data: RunData, findings: list[StoredResult]) -> str:
    ranks = {"high": 0, "normal": 1, "low": 2}
    value = "normal"
    for finding in findings:
        for url_id, _relation in finding.urls:
            info = data.urls.get(url_id)
            if info is None:
                continue
            if ranks.get(info.business_value, 1) < ranks.get(value, 1):
                value = info.business_value
    return {"high": "hoch", "normal": "normal", "low": "niedrig"}.get(value, value)


def _technical_audit(
    report: ReportData,
    coverage: dict[str, dict[str, Any]],
    counts: dict[str, int],
    requests: int,
) -> str:
    data = report.data
    run = data.run
    lines = [
        "# SeoBoy – Technischer SEO-Audit",
        "",
        f"**Lauf:** {run['run_id']} · **Status:** {STATUS_LABELS.get(run['status'], run['status'])}"
        + (f" · **Abbruchgrund:** {_reason_label(run['stop_reason'])}" if run["stop_reason"] else ""),
        f"**Abdeckung:** {counts['checked']} abgerufene Seiten, {counts['deferred']} zurückgestellt, "
        f"{counts['blocked']} gesperrt, {counts['excluded']} ausgeschlossen, "
        f"{counts['external_references']} externe Referenzen, {counts['open']} offen; "
        f"{requests} HTTP-Anfragen.",
        "",
        "## Abdeckung je Regel",
        "",
        "| Regel | Bestanden | Befunde | Geprüfte URLs | Ungeprüft | Nicht anwendbar |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for rule_id in RULE_VERSIONS:
        bucket = coverage.get(rule_id)
        if bucket is None:
            lines.append(f"| {rule_id} | 0 | 0 | 0 | 0 | 0 |")
            continue
        not_checked_total = sum(bucket["not_checked"].values())
        lines.append(
            f"| {rule_id} | {bucket['passes']} | {bucket['findings']} | "
            f"{len(bucket['checked_urls'])} | {not_checked_total} | {bucket['not_applicable']} |"
        )
    lines.extend(["", "## Ungeprüfte Fälle je Grund", ""])
    any_reason = False
    for rule_id in RULE_VERSIONS:
        bucket = coverage.get(rule_id)
        if not bucket or not bucket["not_checked"]:
            continue
        any_reason = True
        for reason, amount in sorted(bucket["not_checked"].items(), key=lambda item: -item[1]):
            lines.append(
                f"- **{rule_id}:** {amount} Prüfung(en) offen – {_reason_label(reason)} ({reason})"
            )
    if not any_reason:
        lines.append("Keine ungeprüften Fälle.")
    lines.extend(["", "## Befunde je Regel", ""])
    findings = report.findings()
    if not findings:
        lines.extend(["Keine Befunde.", ""])
    for rule_id in RULE_VERSIONS:
        rule_findings = [finding for finding in findings if finding.rule_id == rule_id]
        if not rule_findings:
            continue
        lines.extend([f"### {rule_id} – {len(rule_findings)} Befund(e)", ""])
        lines.append("| Objekt | Schweregrad | Beleglage | Evidenz |")
        lines.append("| --- | --- | --- | --- |")
        for finding in rule_findings[:10]:
            lines.append(
                f"| {_md(_finding_label(data, finding))} | {_severity(finding)} | "
                f"{_confidence(finding)} | {_md(_evidence_summary(finding, limit=1))} |"
            )
        if len(rule_findings) > 10:
            lines.extend(
                [
                    "",
                    f"10 von {len(rule_findings)} Befunden gezeigt; vollständig in "
                    "[raw_data/rule_results.csv](raw_data/rule_results.csv).",
                ]
            )
        lines.append("")
    lines.extend(["## Search Console", ""])
    if not data.datasets:
        lines.extend(["Kein GSC-Import mit auswertbaren Daten vorhanden.", ""])
    else:
        lines.append("| Property | Suchtyp | Land | Gerät | Zeitraum | Granularität | Zeilen |")
        lines.append("| --- | --- | --- | --- | --- | --- | ---: |")
        for dataset in data.datasets:
            rows = len(data.metrics.get(int(dataset["dataset_id"]), []))
            lines.append(
                f"| {dataset['property']} | {dataset['search_type']} | "
                f"{dataset['country'] or 'alle'} | {dataset['device'] or 'alle'} | "
                f"{dataset['period_start']} bis {dataset['period_end']} | "
                f"{dataset['grain']} | {rows} |"
            )
        lines.append("")
        for source in data.source_imports:
            meta = source["metadata"]
            if source["module"] != "gsc":
                continue
            if meta.get("mapping"):
                mapping = meta["mapping"]
                lines.append(
                    f"Zuordnung des Imports ({source['status']}): "
                    f"{mapping.get('matched', 0)} passend, "
                    f"{mapping.get('unmatched', 0)} nicht zuordenbar, "
                    f"{mapping.get('ambiguous', 0)} mehrdeutig."
                )
            issues = meta.get("mapping_issues", [])
            if issues:
                lines.extend(["", "Nicht zuordenbare oder mehrdeutige Zeilen:", ""])
                for issue in issues[:10]:
                    reason = REASON_LABELS.get(issue.get("reason", ""), issue.get("reason", ""))
                    lines.append(
                        f"- {issue.get('file', '')}: {issue.get('page', '')} – "
                        f"{issue.get('status', '')} ({reason})"
                    )
                if len(issues) > 10:
                    lines.append(f"- … {len(issues) - 10} weitere Zeilen")
            for note in meta.get("notes", []):
                lines.append(f"- {note}")
            errors = meta.get("errors", [])
            if errors:
                lines.extend(["", "Fehlerhafte Zeilen:", ""])
                for error in errors[:10]:
                    lines.append(f"- {error}")
                if len(errors) > 10:
                    lines.append(f"- … {len(errors) - 10} weitere Fehler")
        gsc_findings = [finding for finding in findings if finding.rule_id.startswith("GSC_")]
        lines.extend(["", f"GSC-Befunde: **{len(gsc_findings)}**.", ""])
        for finding in gsc_findings[:10]:
            lines.append(
                f"- {finding.rule_id}: {_evidence_summary(finding, limit=1)} – "
                f"{_severity(finding)}, {_confidence(finding)}"
            )
        if len(gsc_findings) > 10:
            lines.append(f"- … 10 von {len(gsc_findings)} gezeigt")
        lines.append("")
    lines.extend(["## Sitemaps", ""])
    documents = _sitemap_documents(data)
    if documents:
        for url, status in documents:
            lines.append(f"- {_display(data, url)} – {status}")
    else:
        lines.append("Keine Sitemap-Dokumente abgerufen.")
    exceptions = [finding for finding in findings if finding.exception]
    lines.extend(["", "## Ausnahmen", ""])
    if exceptions:
        for finding in exceptions:
            exception = finding.exception or {}
            urls = ", ".join(_display(data, url) for url in _result_urls(data, finding)[:3])
            lines.append(
                f"- {finding.rule_id} · {urls or finding.subject_key}: "
                f"{exception.get('reason', 'ohne Begründung')}"
                + (f" (gültig bis {exception['expires']})" if exception.get("expires") else "")
            )
    else:
        lines.append("Keine Ausnahmen wirksam.")
    lines.extend(
        [
            "",
            "## Rohdaten",
            "",
            "- [URL-Inventar](raw_data/all_urls.csv)",
            "- [Prüfergebnisse](raw_data/rule_results.csv)",
            "- [Defekte Linkziele](raw_data/broken_links.csv)",
        ]
    )
    if data.datasets:
        lines.append("- [GSC-Zeilen](raw_data/gsc_metrics.csv)")
    lines.append("")
    return "\n".join(lines)


def _write_all_urls_csv(path: Path, report: ReportData) -> None:
    data = report.data
    purposes: dict[int, set[str]] = {}
    for job in data.jobs:
        purposes.setdefault(int(job["url_id"]), set()).add(job["purpose"])
    rows = []
    for info in sorted(data.urls.values(), key=lambda item: item.url):
        attempt = data.final_attempt(info.url_id) if info.url_id in data.page_url_ids else data.last_attempt(info.url_id)
        observation = data.observation(info.url_id)
        if info.url_id in data.page_url_ids:
            kind = "page"
        elif purposes.get(info.url_id):
            kind = "/".join(sorted(purposes[info.url_id]))
        elif info.state == "excluded" and info.reason_code == "host_not_allowed":
            kind = "external"
        elif info.state == "excluded":
            kind = "excluded"
        else:
            kind = "discovered"
        rows.append(
            [
                info.url_id,
                info.url,
                kind,
                "/".join(sorted(purposes.get(info.url_id, set()))),
                info.state,
                info.reason_code or "",
                info.page_type or "",
                info.business_value,
                "" if info.expected_indexable is None else int(info.expected_indexable),
                "" if info.click_depth is None else info.click_depth,
                info.admitted_at or "",
                "|".join(sorted(info.kinds)),
                "|".join(info.discovery_originals[:5]),
                "" if attempt is None or attempt.status_code is None else attempt.status_code,
                "" if attempt is None else (attempt.content_type or ""),
                "" if attempt is None else (attempt.error_code or ""),
                observation.title if observation else "",
                observation.meta_description if observation else "",
                "" if observation is None else int(bool(observation.signals.get("noindex"))),
                "|".join(
                    (
                        list(observation.signals.get("canonical", []) or [])
                        + list(observation.signals.get("canonical_header", []) or [])
                    )
                    if observation
                    else []
                ),
                "|".join(data.url_string(source) for source in info.sitemap_sources),
                len(data.observations.get(info.url_id, [])),
            ]
        )
    _write_csv(
        path,
        [
            "url_id", "url", "kind", "purposes", "state", "reason_code", "page_type",
            "business_value", "expected_indexable", "click_depth", "admitted_at",
            "discovery_kinds", "discovery_examples", "http_status", "content_type",
            "error_code", "title", "meta_description", "noindex", "canonical",
            "sitemap_sources", "observations",
        ],
        rows,
    )


def _write_rule_results_csv(path: Path, report: ReportData) -> None:
    data = report.data
    rows = []
    for result in sorted(report.results, key=lambda item: (item.rule_id, item.subject_key)):
        rows.append(
            [
                data.run_id,
                result.rule_id,
                result.rule_version,
                result.subject_key,
                result.subject_kind,
                result.subcheck,
                result.scope_key,
                result.outcome,
                result.severity or "",
                result.confidence or "",
                result.reason_code or "",
                (result.exception or {}).get("reason", "") if result.exception else "",
                "|".join(_result_urls(data, result, "affected")),
                "|".join(_result_urls(data, result, "source")),
                "|".join(_result_urls(data, result, "target")),
                _evidence_summary(result, limit=3),
                _source_label(result),
                _first_observed(result),
                ",".join(
                    str(value)
                    for value in {e.get("attempt_id") for e in result.evidence if e.get("attempt_id") is not None}
                ),
                ",".join(
                    str(value)
                    for value in {e.get("observation_id") for e in result.evidence if e.get("observation_id") is not None}
                ),
                ",".join(
                    str(value)
                    for value in {e.get("import_id") for e in result.evidence if e.get("import_id") is not None}
                ),
            ]
        )
    _write_csv(
        path,
        [
            "run_id", "rule_id", "rule_version", "subject_key", "subject_kind",
            "subcheck", "scope_key", "outcome", "severity", "confidence",
            "reason_code", "exception_reason", "affected_urls", "source_urls",
            "target_urls", "evidence_summary", "evidence_sources", "observed_at",
            "attempt_ids", "observation_ids", "import_ids",
        ],
        rows,
    )


def _write_broken_links_csv(path: Path, report: ReportData) -> None:
    data = report.data
    action_by_finding: dict[tuple[str, str], str] = {}
    for action in report.actions:
        for key in action.finding_keys:
            action_by_finding[key] = action.action_key
    rows = []
    for result in report.results:
        if result.rule_id != "LINK_BROKEN" or result.outcome != "finding":
            continue
        target_urls = _result_urls(data, result, "target")
        source_urls = _result_urls(data, result, "source")
        target_id = None
        for url_id, relation in result.urls:
            if relation == "target":
                target_id = url_id
                break
        target_status = data.final_status(target_id) if target_id is not None else None
        rows.append(
            [
                target_urls[0] if target_urls else result.subject_key,
                "" if target_status is None else target_status,
                len(source_urls),
                "|".join(source_urls),
                result.severity or "",
                result.confidence or "",
                action_by_finding.get(result.key, ""),
            ]
        )
    _write_csv(
        path,
        ["target_url", "target_status", "source_count", "source_urls", "severity", "confidence", "action_key"],
        rows,
    )


def _write_gsc_metrics_csv(path: Path, report: ReportData) -> None:
    data = report.data
    rows = []
    for dataset in data.datasets:
        dataset_id = int(dataset["dataset_id"])
        for metric in data.metrics.get(dataset_id, []):
            rows.append(
                [
                    dataset["property"],
                    dataset["search_type"],
                    dataset["country"] or "",
                    dataset["device"] or "",
                    dataset["period_start"],
                    dataset["period_end"],
                    dataset["grain"],
                    metric["source_page"],
                    metric["query"] or "",
                    metric["mapping_status"],
                    data.url_string(int(metric["url_id"])) if metric["url_id"] is not None else "",
                    metric["clicks"],
                    metric["impressions"],
                    "" if metric["position"] is None else metric["position"],
                ]
            )
    _write_csv(
        path,
        [
            "property", "search_type", "country", "device", "period_start", "period_end",
            "grain", "source_page", "query", "mapping_status", "url", "clicks",
            "impressions", "position",
        ],
        rows,
    )