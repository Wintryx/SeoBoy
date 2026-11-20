"""Advisory AI review over deterministic audit evidence."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from seoboy.geo.sampling import (
    DEFAULT_MODEL,
    MODEL_VERSIONS,
    GeoSamplingError,
    chat_completion,
)
from seoboy.infrastructure.config import ProjectConfig
from seoboy.reporting.run_report import ReportData, load_report_data, render_run_report
from seoboy.shared.util import excel_safe, iso_utc

PROMPT_VERSION = "ai-review-2026-11-1"
SCHEMA_VERSION = "3"
MAX_PACKET_CHARS = 60_000
MAX_LIST_ITEMS = 10
DEFAULT_BUDGET_USD = 0.25
DEFAULT_MAX_TOKENS = 4096


class AIReviewError(RuntimeError):
    """The review packet, provider call, or model answer is invalid."""


@dataclass(frozen=True)
class ReviewConfig:
    model: str = DEFAULT_MODEL
    max_findings: int = 40
    max_actions: int = 25
    max_tokens: int = DEFAULT_MAX_TOKENS
    budget_usd: float = DEFAULT_BUDGET_USD
    use_cache: bool = True
    refresh: bool = False


@dataclass
class ReviewOutcome:
    report_dir: Path
    packet: dict[str, Any]
    packet_hash: str
    review: dict[str, Any]
    model: str
    model_version: str
    usage: dict[str, Any]
    cost_usd: float
    cached: bool
    generated_at: str


def _clean(value: object, limit: int = 1000) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value))
    if len(text) <= limit:
        return text
    cut = text[: max(0, limit - 1)].rstrip()
    boundary = max(cut.rfind(". "), cut.rfind("\n"))
    if boundary >= len(cut) // 2:
        cut = cut[: boundary + 1].rstrip()
    return cut + "…"


def _md(value: object) -> str:
    return _clean(value, 500).replace("|", "\\|")


def _md_long(value: object) -> str:
    return _clean(value, 12000).replace("|", "\\|")


def _safe_url(value: str, limit: int = 220) -> str:
    return value.split("?", 1)[0].split("#", 1)[0][:limit]


def _finding_id(rule_id: str, subject_key: str) -> str:
    digest = hashlib.sha256(f"{rule_id}|{subject_key}".encode("utf-8")).hexdigest()[:12]
    return f"f_{digest}"


def _action_id(action_key: str) -> str:
    return "a_" + hashlib.sha256(action_key.encode("utf-8")).hexdigest()[:12]


def _count_by(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _action_refs_by_finding(report: ReportData) -> dict[tuple[str, str], list[str]]:
    mapping: dict[tuple[str, str], list[str]] = {}
    for action in report.actions:
        for key in action.finding_keys:
            mapping.setdefault(key, []).append(_action_id(action.action_key))
    return mapping


def build_review_packet(report: ReportData, config: ReviewConfig) -> dict[str, Any]:
    data = report.data
    run = data.run
    actions = report.actions
    finding_refs = _action_refs_by_finding(report)
    findings = sorted(
        report.findings(),
        key=lambda item: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(item.severity or "", 9),
            {"confirmed": 0, "plausible": 1, "hint": 2}.get(item.confidence or "", 9),
        ),
    )[: config.max_findings]
    finding_rows: list[dict[str, Any]] = []
    for result in findings:
        urls: list[str] = []
        for url_id, _relation in result.urls:
            info = data.urls.get(url_id)
            if info is not None:
                urls.append(_safe_url(info.url))
        finding_rows.append(
            {
                "id": _finding_id(result.rule_id, result.subject_key),
                "rule_id": result.rule_id,
                "subject_kind": result.subject_kind,
                "subcheck": result.subcheck,
                "severity": result.severity,
                "confidence": result.confidence,
                "urls": list(dict.fromkeys(urls))[:2],
                "evidence": _clean(json.dumps(result.evidence[:2], ensure_ascii=False), 800),
                "action_refs": sorted(set(finding_refs.get(result.key, []))),
            }
        )
    action_rows: list[dict[str, Any]] = []
    for action in sorted(actions, key=lambda item: (item.priority, item.action_key))[: config.max_actions]:
        action_rows.append(
            {
                "id": _action_id(action.action_key),
                "priority": action.priority,
                "effort": action.effort,
                "title": _clean(action.title, 300),
                "expected_effect": _clean(action.expected_effect, 400),
                "verification": _clean(action.verification, 300),
                "finding_refs": sorted(
                    {_finding_id(rule_id, subject) for rule_id, subject in action.finding_keys}
                )[:10],
            }
        )
    coverage = {
        "outcomes": _count_by([item.outcome for item in report.results]),
        "findings": len(report.findings()),
        "actions": len(actions),
        "urls": len(data.urls),
        "pages": len(data.page_url_ids),
        "requests": len(data.attempts),
        "gsc_rows": sum(len(rows) for rows in data.metrics.values()),
    }
    not_checked = [item for item in report.results if item.outcome == "not_checked"]
    data_quality: list[str] = []
    for reason, count in _count_by(
        [item.reason_code or "ohne_grund" for item in not_checked]
    ).items():
        data_quality.append(f"{count} Prüfung(en) ungeprüft: {reason}")
    if not data.metrics:
        data_quality.append("Keine GSC-Messwerte im Lauf.")
    if data.run.get("stop_reason"):
        data_quality.append(f"Lauf-Stoppgrund: {_clean(data.run['stop_reason'], 120)}")
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project_id": data.config.project_id,
        "run_id": data.run_id,
        "status": run.get("status"),
        "start_url": data.config.start_url,
        "rule_version": run.get("rule_version"),
        "coverage": coverage,
        "findings": finding_rows,
        "actions": action_rows,
        "data_quality": data_quality[:20],
        "truncated": len(findings) >= config.max_findings or len(actions) >= config.max_actions,
    }
    while len(json.dumps(packet, ensure_ascii=False)) > MAX_PACKET_CHARS and (
        packet["findings"] or packet["actions"]
    ):
        if packet["findings"]:
            packet["findings"].pop()
        else:
            packet["actions"].pop()
        packet["truncated"] = True
    return packet


def packet_hash(packet: dict[str, Any]) -> str:
    canonical = json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _prompt(packet: dict[str, Any]) -> str:
    schema = {
        "overall_assessment": "string",
        "confidence": "low|medium|high",
        "cross_cutting_issues": [
            {
                "title": "string",
                "explanation": "string",
                "evidence_refs": ["f_..."],
                "action_refs": ["a_..."],
                "suggested_priority": 1,
            }
        ],
        "priority_adjustments": [
            {
                "action_ref": "a_...",
                "current_priority": 1,
                "suggested_priority": 1,
                "reason": "string",
                "confidence": "low|medium|high",
            }
        ],
        "data_quality_issues": [
            {"issue": "string", "impact": "string", "evidence_refs": ["f_..."]}
        ],
        "additional_analyses": [
            {
                "question": "string",
                "why": "string",
                "suggested_check": "string",
                "priority": 1,
            }
        ],
        "limitations": ["string"],
    }
    return (
        "Du bist ein vorsichtiger Senior-SEO-Reviewer. Du prüfst ausschließlich die "
        "beigefügte Evidenzpackung eines deterministischen Audits.\n\n"
        "Regeln:\n"
        "- Erfinde keine Fakten, Messwerte, URLs oder Befunde.\n"
        "- Verweise mit evidence_refs auf vorhandene f_...-IDs und action_refs auf "
        "vorhandene a_...-IDs.\n"
        "- Du darfst Prioritäten vorschlagen, aber keine Befunde oder Maßnahmen ändern.\n"
        "- Nenne Widersprüche, übersehene Zusammenhänge, Datenlücken und zusätzliche "
        "sinnvolle Prüfungen.\n"
        "- Antworte ausschließlich mit gültigem JSON nach diesem Schema:\n"
        + json.dumps(schema, ensure_ascii=False)
        + "\n\nEvidenzpackung:\n"
        + json.dumps(packet, ensure_ascii=False)
    )


def _extract_json(value: str) -> dict[str, Any]:
    text = value.strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        text = re.sub(r"^" + fence + r"(?:json)?\s*", "", text)
        text = re.sub(r"\s*" + fence + r"$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise AIReviewError("KI-Antwort enthält kein JSON-Objekt.")
    try:
        parsed = json.loads(text[start : end + 1])
    except ValueError as error:
        raise AIReviewError(f"KI-Antwort ist kein gültiges JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise AIReviewError("KI-Antwort muss ein JSON-Objekt sein.")
    return parsed


def _string_list(value: Any, limit: int = 10) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:limit]:
        if isinstance(item, str) and item.strip():
            result.append(_clean(item.strip(), 500))
    return result


def validate_review(raw: dict[str, Any], packet: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    finding_ids = {str(item["id"]) for item in packet.get("findings", [])}
    action_ids = {str(item["id"]) for item in packet.get("actions", [])}
    known_refs = finding_ids | action_ids
    unsupported: list[str] = []

    def refs(value: Any) -> list[str]:
        result: list[str] = []
        for item in _string_list(value, 20):
            if item in known_refs:
                result.append(item)
            else:
                unsupported.append(item)
        return result

    def priority(value: Any) -> int | None:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if 1 <= number <= 4 else None

    review: dict[str, Any] = {
        "overall_assessment": _clean(raw.get("overall_assessment") or "", 12000),
        "confidence": raw.get("confidence") if raw.get("confidence") in {"low", "medium", "high"} else "low",
        "cross_cutting_issues": [],
        "priority_adjustments": [],
        "data_quality_issues": [],
        "additional_analyses": [],
        "limitations": _string_list(raw.get("limitations"), 10),
    }
    for item in raw.get("cross_cutting_issues") or []:
        if not isinstance(item, dict):
            continue
        review["cross_cutting_issues"].append(
            {
                "title": _clean(item.get("title") or "Ohne Titel", 200),
                "explanation": _clean(item.get("explanation") or "", 800),
                "evidence_refs": refs(item.get("evidence_refs")),
                "action_refs": refs(item.get("action_refs")),
                "suggested_priority": priority(item.get("suggested_priority")),
            }
        )
    for item in raw.get("priority_adjustments") or []:
        if not isinstance(item, dict):
            continue
        action_ref = _clean(item.get("action_ref") or "", 100)
        if action_ref not in action_ids:
            unsupported.append(action_ref or "leere action_ref")
            continue
        current = priority(item.get("current_priority"))
        suggested = priority(item.get("suggested_priority"))
        if current is None or suggested is None:
            continue
        review["priority_adjustments"].append(
            {
                "action_ref": action_ref,
                "current_priority": current,
                "suggested_priority": suggested,
                "reason": _clean(item.get("reason") or "", 800),
                "confidence": item.get("confidence") if item.get("confidence") in {"low", "medium", "high"} else "low",
            }
        )
    for item in raw.get("data_quality_issues") or []:
        if not isinstance(item, dict):
            continue
        review["data_quality_issues"].append(
            {
                "issue": _clean(item.get("issue") or "", 300),
                "impact": _clean(item.get("impact") or "", 500),
                "evidence_refs": refs(item.get("evidence_refs")),
            }
        )
    for item in raw.get("additional_analyses") or []:
        if not isinstance(item, dict):
            continue
        review["additional_analyses"].append(
            {
                "question": _clean(item.get("question") or "", 300),
                "why": _clean(item.get("why") or "", 500),
                "suggested_check": _clean(item.get("suggested_check") or "", 500),
                "priority": priority(item.get("priority")),
            }
        )
    for key in ("cross_cutting_issues", "priority_adjustments", "data_quality_issues", "additional_analyses"):
        review[key] = review[key][:MAX_LIST_ITEMS]
    review["unsupported_refs"] = sorted(set(unsupported))[:20]
    return review, review["unsupported_refs"]


def _cache_path(config: ProjectConfig, key: str) -> Path:
    return config.database.parent / "ai_review_cache" / f"{key}.json"


def _load_cached(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_cached(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _cost(usage: dict[str, Any]) -> float:
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    return round((prompt * 0.30 + completion * 1.20) / 1_000_000, 6)


def run_ai_review(
    connection: sqlite3.Connection,
    config: ProjectConfig,
    run_id: str,
    *,
    report_dir: Path | None = None,
    api_key: str = "",
    review_config: ReviewConfig | None = None,
    timeout: float = 90.0,
) -> ReviewOutcome:
    review_config = review_config or ReviewConfig()
    if not 1 <= review_config.max_findings <= 100:
        raise AIReviewError("max_findings muss zwischen 1 und 100 liegen.")
    if not 1 <= review_config.max_actions <= 100:
        raise AIReviewError("max_actions muss zwischen 1 und 100 liegen.")
    if not 64 <= review_config.max_tokens <= 8192:
        raise AIReviewError("max_tokens muss zwischen 64 und 8192 liegen.")
    if review_config.budget_usd < 0:
        raise AIReviewError("budget_usd darf nicht negativ sein.")
    if review_config.model not in MODEL_VERSIONS:
        raise AIReviewError("Unbekanntes Review-Modell.")
    report = load_report_data(connection, config, run_id)
    if report_dir is None:
        folder = render_run_report(connection, config, run_id)
    else:
        folder = Path(report_dir)
        if not folder.is_dir():
            folder = render_run_report(connection, config, run_id)
    packet = build_review_packet(report, review_config)
    digest = packet_hash(packet)
    cache_key = hashlib.sha256(
        f"{digest}|{review_config.model}|{review_config.max_tokens}|"
        f"{PROMPT_VERSION}|{SCHEMA_VERSION}".encode("utf-8")
    ).hexdigest()
    cache_path = _cache_path(config, cache_key)
    cached_payload = None if review_config.refresh else _load_cached(cache_path)
    if cached_payload and review_config.use_cache:
        review = cached_payload.get("review")
        if isinstance(review, dict):
            return ReviewOutcome(
                report_dir=folder,
                packet=packet,
                packet_hash=digest,
                review=review,
                model=str(cached_payload.get("model") or review_config.model),
                model_version=str(cached_payload.get("model_version") or MODEL_VERSIONS.get(review_config.model, review_config.model)),
                usage=dict(cached_payload.get("usage") or {}),
                cost_usd=float(cached_payload.get("cost_usd") or 0.0),
                cached=True,
                generated_at=str(cached_payload.get("generated_at") or iso_utc()),
            )
    if not api_key:
        raise AIReviewError("Für ai-review wird ein DeepSeek-API-Key benötigt.")
    prompt = _prompt(packet)
    maximum_cost = (len(prompt) / 3 * 0.30 + review_config.max_tokens * 1.20) / 1_000_000
    if maximum_cost > review_config.budget_usd:
        raise AIReviewError(f"Review-Budget zu klein: maximal mögliche Kosten {maximum_cost:.6f} USD.")
    try:
        response = chat_completion(
            api_key,
            prompt,
            model=review_config.model,
            temperature=0.1,
            max_tokens=review_config.max_tokens,
            thinking="disabled",
            reasoning_effort="none",
            json_mode=True,
            timeout=timeout,
        )
    except GeoSamplingError as error:
        raise AIReviewError(str(error)) from error
    review, unsupported = validate_review(_extract_json(response["content"]), packet)
    usage = response.get("usage") or {}
    cost = _cost(usage)
    generated_at = iso_utc()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "packet_hash": digest,
        "model": review_config.model,
        "model_version": response.get("model_version", review_config.model),
        "usage": usage,
        "cost_usd": cost,
        "generated_at": generated_at,
        "review": review,
        "unsupported_refs": unsupported,
    }
    if review_config.use_cache:
        _write_cached(cache_path, payload)
    return ReviewOutcome(
        report_dir=folder,
        packet=packet,
        packet_hash=digest,
        review=review,
        model=review_config.model,
        model_version=str(payload["model_version"]),
        usage=usage,
        cost_usd=cost,
        cached=False,
        generated_at=generated_at,
    )


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow([excel_safe(value) for value in row])


def write_ai_review(outcome: ReviewOutcome) -> Path:
    folder = outcome.report_dir
    raw = folder / "raw_data"
    raw.mkdir(parents=True, exist_ok=True)
    review = outcome.review
    lines = [
        "# KI-Review – advisory",
        "",
        "> **Der SeoBoy KI-Agent hat darüber hinaus folgendes analysiert.**",
        "> Diese Review ergänzt den deterministischen Audit. Sie ändert keine Befunde,",
        "> Maßnahmen oder Prioritäten und ersetzt keine Messung.",
        "",
        f"**Modell:** {_md(outcome.model)} ({_md(outcome.model_version)})  ",
        f"**Prompt-Version:** {PROMPT_VERSION}  ",
        f"**Packung:** {outcome.packet_hash[:16]}  ",
        f"**Cache:** {'Treffer' if outcome.cached else 'neu'}  ",
        f"**Kosten:** {outcome.cost_usd:.6f} USD (Peak-Schätzung)",
        "",
        "## Gesamteinordnung",
        "",
        _md_long(review.get("overall_assessment") or "Keine Gesamteinordnung.")
        + f" (Konfidenz: {_md(review.get('confidence') or 'low')})",
        "",
        "## Übergreifende Zusammenhänge",
        "",
    ]
    issues = review.get("cross_cutting_issues") or []
    if not issues:
        lines.append("Keine übergreifenden Zusammenhänge vorgeschlagen.")
    for item in issues:
        refs = ", ".join(item.get("evidence_refs") or []) or "keine"
        lines.extend(
            [
                f"### {_md(item.get('title') or 'Ohne Titel')}",
                "",
                _md(item.get("explanation") or ""),
                "",
                f"- Evidenz: {_md(refs)}",
                f"- Maßnahmen: {_md(', '.join(item.get('action_refs') or []) or 'keine')}",
                f"- Vorgeschlagene Priorität: {item.get('suggested_priority') or '–'}",
                "",
            ]
        )
    lines.extend(
        [
            "## Prioritätsvorschläge",
            "",
            "| Maßnahme | Aktuell | Vorschlag | Begründung | Konfidenz |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    adjustments = review.get("priority_adjustments") or []
    if not adjustments:
        lines.append("| – | – | – | keine Vorschläge | – |")
    for item in adjustments:
        lines.append(
            f"| {_md(item.get('action_ref'))} | {item.get('current_priority')} | "
            f"{item.get('suggested_priority')} | {_md(item.get('reason'))} | {_md(item.get('confidence'))} |"
        )
    lines.extend(["", "## Datenqualität", ""])
    quality = review.get("data_quality_issues") or []
    if not quality:
        lines.append("Keine zusätzlichen Datenqualitätsfragen.")
    for item in quality:
        lines.append(
            f"- **{_md(item.get('issue'))}**: {_md(item.get('impact'))} "
            f"({_md(', '.join(item.get('evidence_refs') or []) or 'keine Referenz')})"
        )
    lines.extend(["", "## Zusätzliche Analysen", ""])
    analyses = review.get("additional_analyses") or []
    if not analyses:
        lines.append("Keine zusätzlichen Analysen vorgeschlagen.")
    for item in analyses:
        lines.append(
            f"- **{_md(item.get('question'))}** – {_md(item.get('why'))} "
            f"Prüfung: {_md(item.get('suggested_check'))} (Priorität {item.get('priority') or '–'})"
        )
    lines.extend(["", "## Ungeprüfte Aussagen", ""])
    unsupported = review.get("unsupported_refs") or []
    if not unsupported:
        lines.append("Keine ungeprüften Referenzen.")
    else:
        for value in unsupported:
            lines.append(f"- {_md(value)}")
    lines.extend(["", "## Grenzen", ""])
    for value in review.get("limitations") or [
        "Die Review ist eine KI-Einschätzung auf Basis der Evidenzpackung."
    ]:
        lines.append(f"- {_md(value)}")
    lines.extend(
        [
            "",
            "## Rohdaten",
            "",
            "- [Review-JSON](raw_data/ai_review.json)",
            "- [Vorschläge](raw_data/ai_review_suggestions.csv)",
            "",
        ]
    )
    (folder / "07_AI_REVIEW.md").write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n"
    )
    (raw / "ai_review.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "prompt_version": PROMPT_VERSION,
                "packet_hash": outcome.packet_hash,
                "model": outcome.model,
                "model_version": outcome.model_version,
                "usage": outcome.usage,
                "cost_usd": outcome.cost_usd,
                "cached": outcome.cached,
                "generated_at": outcome.generated_at,
                "review": review,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    rows: list[list[Any]] = []
    for item in review.get("cross_cutting_issues") or []:
        rows.append(["cross_cutting", "", item.get("title"), item.get("suggested_priority"), ""])
    for item in review.get("priority_adjustments") or []:
        rows.append(["priority", item.get("action_ref"), item.get("reason"), item.get("suggested_priority"), item.get("confidence")])
    for item in review.get("additional_analyses") or []:
        rows.append(["additional", "", item.get("question"), item.get("priority"), ""])
    _write_csv(raw / "ai_review_suggestions.csv", ["type", "ref", "text", "priority", "confidence"], rows)
    return folder / "07_AI_REVIEW.md"
