"""Vergleich zweier gespeicherter Läufe (05_AUDIT_DIFF.md)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import csv
from pathlib import Path
import re
import sqlite3

from seoboy.analysis.audit_data import RunData
from seoboy.infrastructure.config import ProjectConfig
from seoboy.reporting.run_report import (
    ReportData,
    STATUS_LABELS,
    StoredAction,
    StoredResult,
    _confidence,
    _evidence_summary,
    _finding_label,
    _reason_label,
    _result_urls,
    _severity,
    load_report_data,
)
from seoboy.shared.util import excel_safe, format_local, local_date_from_utc, parse_utc

DIFF_STATES = {
    "new": "Neu",
    "first_seen": "Erstmals beobachtet",
    "persistent": "Fortbestehend",
    "fixed": "Behoben",
    "unchecked": "Ungeprüft",
    "incomparable": "Nicht vergleichbar",
}


class DiffError(ValueError):
    """Die beiden Läufe lassen sich nicht vergleichen."""


@dataclass
class DiffRow:
    rule_id: str
    subject_key: str
    subject_kind: str
    subcheck: str
    scope_key: str
    state: str
    base: StoredResult | None
    target: StoredResult | None
    urls: list[str]
    note: str

    @property
    def label(self) -> str:
        return DIFF_STATES[self.state]


def ensure_comparable_runs(
    connection: sqlite3.Connection,
    config: ProjectConfig,
    base_run_id: str,
    target_run_id: str,
) -> tuple[sqlite3.Row, sqlite3.Row]:
    rows = {}
    for run_id in (base_run_id, target_run_id):
        row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise DiffError(f"Lauf '{run_id}' wurde nicht gefunden.")
        rows[run_id] = row
    base, target = rows[base_run_id], rows[target_run_id]
    if base["project_id"] != target["project_id"] or base["site_id"] != target["site_id"]:
        raise DiffError("Die Läufe gehören zu unterschiedlichen Projekten oder Websites.")
    for run_id, row in rows.items():
        if row["status"] not in {"completed", "partial"}:
            raise DiffError(
                f"Lauf '{run_id}' ist nicht abgeschlossen (Status {row['status']}). "
                "Für den Vergleich sind completed- oder partial-Läufe nötig."
            )
        if row["mode"] != "crawl":
            raise DiffError(f"Lauf '{run_id}' ist kein Crawl-Lauf.")
    if base_run_id == target_run_id:
        raise DiffError("Basis- und Ziellauf müssen unterschiedlich sein.")
    return base, target


def _rule_versions(data: RunData, results: list[StoredResult]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for result in results:
        versions.setdefault(result.rule_id, result.rule_version)
    return versions


def _result_period(result: StoredResult) -> tuple[str, str] | None:
    for evidence in result.evidence:
        facts = evidence.get("facts", {})
        start = facts.get("period_start")
        end = facts.get("period_end")
        if start and end:
            return (str(start), str(end))
    return None


def _link_edge_fixed_by_urls(
    base_data: RunData,
    base_result: StoredResult,
    target_data: RunData,
) -> bool | None:
    source_urls = _result_urls(base_data, base_result, "source")
    target_urls = _result_urls(base_data, base_result, "target")
    if not source_urls or not target_urls:
        return None
    source_info = target_data.url_by_url.get(source_urls[0])
    target_info = target_data.url_by_url.get(target_urls[0])
    if source_info is None:
        return None
    observation = target_data.observation(source_info.url_id)
    if observation is None or not observation.links_complete:
        return None
    edges = target_data.links.get(source_info.url_id, {})
    if target_info is not None and target_info.url_id in edges:
        return None
    return True


def _compare(
    base: ReportData,
    target: ReportData,
) -> tuple[list[DiffRow], dict[tuple[str, str], str]]:
    rows: list[DiffRow] = []
    state_by_key: dict[tuple[str, str], str] = {}
    base_map = base.result_map
    target_map = target.result_map
    base_versions = _rule_versions(base.data, base.results)
    target_versions = _rule_versions(target.data, target.results)
    keys = sorted(set(base_map) | set(target_map))
    for key in keys:
        base_result = base_map.get(key)
        target_result = target_map.get(key)
        if base_result is None and target_result is None:
            continue
        rule_id = (base_result or target_result).rule_id
        subject_key = (base_result or target_result).subject_key
        base_outcome = base_result.outcome if base_result else None
        target_outcome = target_result.outcome if target_result else None
        note = ""
        state: str
        if base_result is not None and target_result is not None:
            base_period = _result_period(base_result) if base_result.rule_id.startswith("GSC_") else None
            target_period = _result_period(target_result) if target_result.rule_id.startswith("GSC_") else None
            if base_period and target_period and base_period != target_period:
                state = "incomparable"
                note = (
                    f"Messfenster {base_period[0]}–{base_period[1]} → "
                    f"{target_period[0]}–{target_period[1]}"
                )
            elif base_result.rule_version != target_result.rule_version:
                state = "incomparable"
                note = (
                    f"Regelversion {base_result.rule_version} → "
                    f"{target_result.rule_version}"
                )
            elif base_result.scope_key != target_result.scope_key:
                state = "incomparable"
                note = f"Geltungsbereich {base_result.scope_key} → {target_result.scope_key}"
            elif base_result.subcheck != target_result.subcheck:
                state = "incomparable"
                note = f"Untercheck {base_result.subcheck} → {target_result.subcheck}"
            elif base_result.subject_kind != target_result.subject_kind:
                state = "incomparable"
                note = "Gegenstandstyp geändert"
            elif base_outcome == "finding" and target_outcome == "finding":
                state = "persistent"
                note = "Befund in beiden Läufen mit vergleichbarer Evidenz"
            elif base_outcome == "finding" and target_outcome == "pass":
                state = "fixed"
                note = "Im Ziellauf mit ausreichender Evidenz erneut geprüft und bestanden"
            elif base_outcome == "finding" and target_outcome == "not_checked":
                state = "unchecked"
                note = f"Im Ziellauf ungeprüft: {_reason_label(target_result.reason_code)}"
            elif base_outcome == "finding" and target_outcome == "not_applicable":
                state = "incomparable"
                note = f"Im Ziellauf nicht anwendbar: {_reason_label(target_result.reason_code)}"
            elif base_outcome == "pass" and target_outcome == "finding":
                state = "new"
                note = "Im Basislauf bestanden, im Ziellauf Befund"
            elif base_outcome == "pass" and target_outcome == "not_checked":
                state = "unchecked"
                note = f"Im Ziellauf ungeprüft: {_reason_label(target_result.reason_code)}"
            elif base_outcome == "not_checked" and target_outcome == "finding":
                state = "first_seen"
                note = "Im Basislauf ohne Vergleichsbeobachtung"
            elif base_outcome == "pass" and target_outcome == "pass":
                continue
            elif base_outcome == "not_checked" and target_outcome == "pass":
                state = "incomparable"
                note = "Im Basislauf ungeprüft; ein früherer Befund ist nicht belegt"
            elif base_outcome == "not_applicable" and target_outcome in {"finding", "pass"}:
                state = "incomparable"
                note = "Fachliche Anwendbarkeit hat sich geändert"
            else:
                continue
        elif base_result is not None:
            base_outcome = base_result.outcome
            if base_result.rule_id not in target_versions:
                state = "incomparable" if base.data.run["ruleset_version"] != target.data.run["ruleset_version"] else "unchecked"
                note = "Regel wurde im Ziellauf nicht ausgeführt"
            elif base_outcome == "finding":
                if (
                    base_result.rule_id == "LINK_BROKEN"
                    and _link_edge_fixed_by_urls(base.data, base_result, target.data)
                ):
                    state = "fixed"
                    note = "Kein Linkdatensatz im Ziellauf, aber Quellseite vollständig ausgewertet"
                else:
                    state = "unchecked"
                    note = "Kein vergleichbares Ergebnis im Ziellauf"
            elif base_outcome == "pass":
                state = "unchecked"
                note = "Kein vergleichbares Ergebnis im Ziellauf"
            else:
                state = "incomparable"
                note = "Regel im Ziellauf nicht ausgeführt"
        else:
            assert target_result is not None
            if target_result.outcome == "finding":
                state = "first_seen"
                note = "Befund ohne vergleichbare Beobachtung im Basislauf"
            else:
                continue
        if base_result is not None and target_result is not None:
            base_exception = bool(base_result.exception)
            target_exception = bool(target_result.exception)
            if base_exception != target_exception:
                extra = "Ausnahme entfallen" if base_exception else "Ausnahme neu wirksam"
                note = f"{note}; {extra}" if note else extra
        elif base_result is not None and target_result is None and base_result.exception:
            note = f"{note}; Ausnahme im Basislauf wirksam" if note else "Ausnahme im Basislauf wirksam"
        if (
            state in {"unchecked", "incomparable"}
            and base_result is not None
            and base_result.outcome in {"pass", "not_checked", "not_applicable"}
            and (target_result is None or target_result.outcome != "finding")
        ):
            continue
        source_result = base_result or target_result
        assert source_result is not None
        data_for_urls = base.data if base_result is not None else target.data
        urls = _result_urls(data_for_urls, source_result)
        rows.append(
            DiffRow(
                rule_id=rule_id,
                subject_key=subject_key,
                subject_kind=source_result.subject_kind,
                subcheck=source_result.subcheck,
                scope_key=source_result.scope_key,
                state=state,
                base=base_result,
                target=target_result,
                urls=urls,
                note=note,
            )
        )
        state_by_key[key] = state
    return rows, state_by_key


def _action_state(
    action: StoredAction,
    state_by_key: dict[tuple[str, str], str],
    target_actions: list[StoredAction],
) -> tuple[str, Counter]:
    counts = Counter()
    for key in action.finding_keys:
        counts[state_by_key.get(key, "unchecked")] += 1
    target_has_action = any(item.action_key == action.action_key for item in target_actions)
    total = sum(counts.values())
    if total and counts["fixed"] == total and not target_has_action:
        return "Vollständig behoben", counts
    if total and counts["fixed"] == total and target_has_action:
        return "Weiterhin Befunde", counts
    if counts["persistent"] or counts["new"]:
        return "Offen", counts
    if counts["unchecked"]:
        return "Ungeprüft", counts
    return "Teilweise behoben", counts


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "project"


def _write_csv(path: Path, rows: list[DiffRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(
            [
                "state", "rule_id", "subject_key", "subject_kind", "subcheck",
                "scope_key", "base_outcome", "target_outcome", "base_severity",
                "target_severity", "base_reason", "target_reason", "urls", "note",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    excel_safe(row.label),
                    row.rule_id,
                    excel_safe(row.subject_key),
                    row.subject_kind,
                    row.subcheck,
                    row.scope_key,
                    excel_safe(row.base.outcome if row.base else ""),
                    excel_safe(row.target.outcome if row.target else ""),
                    excel_safe(row.base.severity if row.base else ""),
                    excel_safe(row.target.severity if row.target else ""),
                    excel_safe(row.base.reason_code if row.base else ""),
                    excel_safe(row.target.reason_code if row.target else ""),
                    excel_safe("|".join(row.urls)),
                    excel_safe(row.note),
                ]
            )


def _row_line(data: RunData, row: DiffRow) -> str:
    source = row.target or row.base
    urls = _finding_label(data, source) if source is not None else row.subject_key
    severity = ""
    if source is not None and source.outcome == "finding":
        severity = f" · {_severity(source)} / {_confidence(source)}"
    evidence = _evidence_summary(row.target or row.base, limit=1) if (row.target or row.base) else ""
    parts = [f"**{row.rule_id}** · {urls}{severity}"]
    if evidence and evidence != "–":
        parts.append(f"Evidenz: {evidence}")
    if row.note:
        parts.append(row.note)
    if row.state == "incomparable" and row.base and row.target:
        if row.base.rule_version != row.target.rule_version:
            parts.append(
                f"Regelversion {row.base.rule_version} → {row.target.rule_version}"
            )
    return "- " + ". ".join(parts)


def _section(
    title: str,
    rows: list[DiffRow],
    state: str,
    data: RunData,
    limit: int = 10,
) -> list[str]:
    selected = [row for row in rows if row.state == state]
    lines = [f"## {title}", ""]
    if not selected:
        lines.extend(["Keine Fälle.", ""])
        return lines
    for row in selected[:limit]:
        lines.append(_row_line(data, row))
    if len(selected) > limit:
        lines.extend(
            [
                "",
                f"10 von {len(selected)} Fällen gezeigt; vollständig in "
                "[raw_data/audit_diff.csv](raw_data/audit_diff.csv).",
            ]
        )
    lines.append("")
    return lines


def render_diff_report(
    connection: sqlite3.Connection,
    config: ProjectConfig,
    base_run_id: str,
    target_run_id: str,
    reports_dir: Path | None = None,
) -> Path:
    base_row, target_row = ensure_comparable_runs(connection, config, base_run_id, target_run_id)
    base = load_report_data(connection, config, base_run_id)
    target = load_report_data(connection, config, target_run_id)
    rows, state_by_key = _compare(base, target)
    counts = Counter(row.state for row in rows)
    base_dir = Path(reports_dir) if reports_dir is not None else config.reports_dir
    day = local_date_from_utc(target_row["started_at"])
    folder = base_dir / f"{day.isoformat()}_{_safe(config.project_id)}_diff_{base_run_id}_{target_run_id}"
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / "raw_data"
    raw.mkdir(parents=True, exist_ok=True)
    _write_csv(raw / "audit_diff.csv", rows)

    action_rows = [
        (action, *_action_state(action, state_by_key, target.actions))
        for action in base.actions
    ]
    lines = [
        "# SeoBoy – Audit-Vergleich",
        "",
        f"**Projekt:** {config.project_id}  ",
        f"**Basislauf:** {base_run_id} ({STATUS_LABELS.get(base_row['status'], base_row['status'])}, "
        f"{format_local(parse_utc(base_row['started_at']))})  ",
        f"**Ziellauf:** {target_run_id} ({STATUS_LABELS.get(target_row['status'], target_row['status'])}, "
        f"{format_local(parse_utc(target_row['started_at']))})  ",
        f"**Regelsatz:** {base_row['ruleset_version']} → {target_row['ruleset_version']}  ",
        f"**Konfiguration:** {base_row['config_hash'][:12]} → {target_row['config_hash'][:12]}" +
        ("" if base_row["config_hash"] == target_row["config_hash"] else " (geändert)") + "  ",
        "",
        "Verglichen werden Befunde auf Ebene der stabilen Befund-ID. Regeln mit anderer "
        "Version, anderem Geltungsbereich oder geänderter Anwendbarkeit gelten als nicht "
        "vergleichbar. Ein fehlender Linkdatensatz kann als behoben gelten, wenn die "
        "Quellseite im Ziellauf vollständig ausgewertet wurde.",
        "",
        "## Übersicht",
        "",
        "| Zustand | Anzahl |",
        "| --- | ---: |",
    ]
    for state in ("new", "first_seen", "persistent", "fixed", "unchecked", "incomparable"):
        lines.append(f"| {DIFF_STATES[state]} | {counts.get(state, 0)} |")
    lines.extend(["", f"Gesamt: **{len(rows)}** vergleichbare Einträge.", ""])
    lines.extend(_section("Neue Befunde", rows, "new", target.data))
    lines.extend(_section("Erstmals beobachtet", rows, "first_seen", target.data))
    lines.extend(_section("Fortbestehende Befunde", rows, "persistent", target.data))
    lines.extend(_section("Behobene Befunde", rows, "fixed", base.data))
    lines.extend(_section("Ungeprüft", rows, "unchecked", target.data))
    lines.extend(_section("Nicht vergleichbar", rows, "incomparable", target.data))
    lines.extend(["## Maßnahmen", ""])
    if action_rows:
        lines.append("| Maßnahme | Priorität | Behoben | Fortbestehend | Neu | Ungeprüft | Status |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | --- |")
        for action, status, action_counts in action_rows:
            lines.append(
                f"| {action.title} | P{action.priority} | {action_counts.get('fixed', 0)} | "
                f"{action_counts.get('persistent', 0)} | {action_counts.get('new', 0)} | "
                f"{action_counts.get('unchecked', 0)} | {status} |"
            )
        lines.append("")
        lines.append(
            "Eine Maßnahme gilt erst als vollständig behoben, wenn alle bisherigen Befunde "
            "behoben sind und der Ziellauf für denselben Fix keinen weiteren Befund meldet. "
            "Neue oder abgelaufene Ausnahmen ändern die Sichtbarkeit, nicht die Beobachtung."
        )
    else:
        lines.append("Der Basislauf enthält keine Maßnahmen.")
    lines.extend(["", "## Rohdaten", "", "- [Audit-Diff als CSV](raw_data/audit_diff.csv)", ""])
    (folder / "05_AUDIT_DIFF.md").write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n"
    )
    return folder
