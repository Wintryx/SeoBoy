"""Technisches Regelwerk mit Evidenz, Grundcodes und Geltungsbereichen."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import sqlite3
import unicodedata
from typing import Any, Callable, Iterable

from seoboy.analysis.audit_data import AttemptInfo, ObservationInfo, RunData, UrlInfo
from seoboy.shared.agents import GOOGLEBOT
from seoboy.shared.urls import (
    InvalidUrl,
    key_for_link,
    key_for_url,
    normalize_url,
)
from seoboy.shared.util import sha256_text, stable_json

RULE_VERSIONS = {
    "HTTP_UNAVAILABLE": "1",
    "HTTP_REDIRECT": "2",
    "INDEX_ROBOTS_BLOCKED": "1",
    "INDEX_NOINDEX": "1",
    "CANONICAL_TARGET": "2",
    "SITEMAP_TARGET": "1",
    "LINK_BROKEN": "2",
    "LINK_ORPHAN_CANDIDATE": "1",
    "LINK_DEPTH": "1",
    "META_TITLE": "2",
    "META_DESCRIPTION": "2",
    "GSC_NEAR_TOP": "1",
    "GSC_DECLINE": "1",
    "GSC_CTR_REVIEW": "1",
    "GSC_MULTI_URL": "1",
}

BLOCKER_RULES = {
    "HTTP_UNAVAILABLE",
    "HTTP_REDIRECT",
    "INDEX_ROBOTS_BLOCKED",
    "INDEX_NOINDEX",
}

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
CONFIDENCE_RANK = {"confirmed": 0, "plausible": 1, "hint": 2}


@dataclass
class Evidence:
    source_kind: str
    observed_at: str
    facts: dict[str, Any]
    attempt_id: int | None = None
    observation_id: int | None = None
    import_id: int | None = None


@dataclass
class RuleResult:
    rule_id: str
    subject_key: str
    subject_kind: str
    subcheck: str
    scope_key: str
    outcome: str
    severity: str | None = None
    confidence: str | None = None
    reason_code: str | None = None
    exception: dict[str, Any] | None = None
    urls: list[tuple[int, str]] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    fix_kind: str | None = None
    group_key: str | None = None

    @property
    def rule_version(self) -> str:
        return RULE_VERSIONS[self.rule_id]

    @property
    def key(self) -> tuple[str, str]:
        return (self.rule_id, self.subject_key)


def _rule(
    rule_id: str,
    subject_key: str,
    subject_kind: str,
    subcheck: str,
    scope_key: str,
    outcome: str,
    *,
    severity: str | None = None,
    confidence: str | None = None,
    reason_code: str | None = None,
    urls: Iterable[tuple[int, str]] = (),
    evidence: Iterable[Evidence] = (),
    fix_kind: str | None = None,
    group_key: str | None = None,
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        subject_key=subject_key,
        subject_kind=subject_kind,
        subcheck=subcheck,
        scope_key=scope_key,
        outcome=outcome,
        severity=severity,
        confidence=confidence,
        reason_code=reason_code,
        urls=list(dict.fromkeys(urls)),
        evidence=list(evidence),
        fix_kind=fix_kind,
        group_key=group_key,
    )


def _http_evidence(attempt: AttemptInfo | None, facts: dict[str, Any]) -> Evidence | None:
    if attempt is None:
        return None
    return Evidence(
        source_kind="http",
        observed_at=attempt.observed_at,
        facts=facts,
        attempt_id=attempt.attempt_id,
    )


def _observation_evidence(
    observation: ObservationInfo | None, facts: dict[str, Any]
) -> Evidence | None:
    if observation is None:
        return None
    return Evidence(
        source_kind="page_observation",
        observed_at=observation.observed_at,
        facts=facts,
        observation_id=observation.observation_id,
    )


def _config_evidence(data: RunData, facts: dict[str, Any]) -> Evidence:
    return Evidence(
        source_kind="config",
        observed_at=data.run["started_at"],
        facts=facts,
    )


def _crawl_evidence(data: RunData, facts: dict[str, Any]) -> Evidence:
    return Evidence(
        source_kind="crawl",
        observed_at=data.run["started_at"],
        facts=facts,
    )


def _clean(evidence: Iterable[Evidence | None]) -> list[Evidence]:
    return [item for item in evidence if item is not None]


def _attempts_summary(attempts: list[AttemptInfo]) -> str:
    parts: list[str] = []
    for attempt in attempts:
        if attempt.state == "transport_error":
            parts.append(f"Versuch {attempt.attempt_no}: {attempt.error_code}")
        elif attempt.status_code is not None:
            parts.append(f"Versuch {attempt.attempt_no}: HTTP {attempt.status_code}")
        else:
            parts.append(f"Versuch {attempt.attempt_no}: {attempt.state}")
    return "; ".join(parts)


def _page_urls(data: RunData) -> list[UrlInfo]:
    return sorted(
        (data.urls[url_id] for url_id in data.page_url_ids if url_id in data.urls),
        key=lambda info: info.url,
    )


def _is_blocker(data: RunData, info: UrlInfo) -> bool:
    return info.is_important and info.expected_indexable is True


def _content_reason(data: RunData, url_id: int) -> tuple[str, str | None]:
    return data.content_state(url_id)


# ---------------------------------------------------------------------- HTTP_UNAVAILABLE


def rule_http_unavailable(data: RunData) -> list[RuleResult]:
    results: list[RuleResult] = []
    for info in _page_urls(data):
        if info.state == "excluded":
            continue
        subject = key_for_url(info.url)
        if info.state == "blocked":
            results.append(
                _rule(
                    "HTTP_UNAVAILABLE", subject, "url", "", info.scope, "not_checked",
                    reason_code="robots_disallowed", urls=[(info.url_id, "affected")],
                    evidence=_clean([_crawl_evidence(data, {"state": info.state, "reason": info.reason_code})]),
                )
            )
            continue
        if info.state == "deferred":
            results.append(
                _rule(
                    "HTTP_UNAVAILABLE", subject, "url", "", info.scope, "not_checked",
                    reason_code=info.reason_code or "url_limit_reached",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([_crawl_evidence(data, {"state": info.state, "reason": info.reason_code})]),
                )
            )
            continue
        attempts = data.page_attempts(info.url_id)
        final = data.final_attempt(info.url_id)
        if final is None:
            results.append(
                _rule(
                    "HTTP_UNAVAILABLE", subject, "url", "", info.scope, "not_checked",
                    reason_code=info.reason_code or "not_fetched",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([_crawl_evidence(data, {"state": info.state})]),
                )
            )
            continue
        facts = {
            "summary": _attempts_summary(attempts) or "kein Abruf",
            "status_code": final.status_code,
            "error_code": final.error_code,
            "attempts": len(attempts),
            "final_attempt": final.attempt_no,
            "url": info.url,
        }
        if final.state == "transport_error":
            results.append(
                _rule(
                    "HTTP_UNAVAILABLE", subject, "url", "", info.scope, "finding",
                    severity="medium", confidence="confirmed",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([_http_evidence(final, facts)]),
                )
            )
            continue
        status = final.status_code
        if status is None:
            results.append(
                _rule(
                    "HTTP_UNAVAILABLE", subject, "url", "", info.scope, "not_checked",
                    reason_code="fetch_interrupted", urls=[(info.url_id, "affected")],
                    evidence=_clean([_http_evidence(final, facts)]),
                )
            )
            continue
        if 200 <= status < 300 or 300 <= status < 400:
            results.append(
                _rule(
                    "HTTP_UNAVAILABLE", subject, "url", "", info.scope, "pass",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([_http_evidence(final, facts)]),
                )
            )
            continue
        blocker = False
        if _is_blocker(data, info):
            if status in {404, 410}:
                blocker = True
            elif 500 <= status < 600:
                blocker = len(attempts) >= 3 and all(
                    attempt.status_code is not None and 500 <= attempt.status_code < 600
                    for attempt in attempts
                )
        severity = "critical" if blocker else "high"
        if status == 429:
            severity = "medium"
        facts["blocker"] = blocker
        facts["summary"] = (
            f"HTTP {status} nach {len(attempts)} Versuch(en)"
            + (" – bestätigter Blocker" if blocker else "")
        )
        results.append(
            _rule(
                "HTTP_UNAVAILABLE", subject, "url", "", info.scope, "finding",
                severity=severity, confidence="confirmed",
                urls=[(info.url_id, "affected")],
                evidence=_clean([_http_evidence(final, facts)]),
                fix_kind="http_error", group_key=info.url,
            )
        )
    return results


# ---------------------------------------------------------------------- HTTP_REDIRECT


def _analyse_chain(data: RunData, start_id: int) -> dict[str, Any]:
    visited = [start_id]
    current = start_id
    hops = 0
    loop = False
    external = False
    hop_limit = False
    unresolved = False
    missing_location = False
    chain: list[int] = [start_id]
    while True:
        target = data.redirects.get(current)
        if target is None:
            attempt = data.final_attempt(current)
            if attempt is not None and attempt.status_code is not None and 300 <= attempt.status_code < 400:
                external = bool(attempt.headers.get("location"))
                missing_location = not external
            break
        if target in visited:
            loop = True
            chain.append(target)
            break
        hops += 1
        visited.append(target)
        chain.append(target)
        target_info = data.urls.get(target)
        if target_info is None:
            unresolved = True
            break
        if target_info.state == "deferred" and target_info.reason_code == "redirect_hop_limit":
            hop_limit = True
            break
        status = data.final_status(target)
        if status is None:
            unresolved = True
            break
        if 300 <= status < 400:
            current = target
            continue
        break
    return {
        "hops": hops,
        "loop": loop,
        "external": external,
        "hop_limit": hop_limit,
        "unresolved": unresolved,
        "missing_location": missing_location,
        "chain": chain,
    }


def rule_http_redirect(data: RunData) -> list[RuleResult]:
    results: list[RuleResult] = []
    inspect = data.run.get("mode") == "inspect"
    for info in _page_urls(data):
        if info.state == "excluded":
            continue
        subject = key_for_url(info.url)
        final = data.final_attempt(info.url_id)
        if final is None:
            reason = info.reason_code or ("robots_disallowed" if info.state == "blocked" else "not_fetched")
            results.append(
                _rule(
                    "HTTP_REDIRECT", subject, "url", "", info.scope, "not_checked",
                    reason_code=reason, urls=[(info.url_id, "affected")],
                    evidence=_clean([_crawl_evidence(data, {"state": info.state})]),
                )
            )
            continue
        if final.state == "transport_error":
            results.append(
                _rule(
                    "HTTP_REDIRECT", subject, "url", "", info.scope, "not_checked",
                    reason_code="fetch_timeout" if final.error_code == "timeout" else "fetch_error",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([_http_evidence(final, {"error_code": final.error_code})]),
                )
            )
            continue
        status = final.status_code
        if status is None:
            results.append(
                _rule(
                    "HTTP_REDIRECT", subject, "url", "", info.scope, "not_checked",
                    reason_code="fetch_interrupted", urls=[(info.url_id, "affected")],
                    evidence=_clean([_http_evidence(final, {"state": final.state})]),
                )
            )
            continue
        if not 300 <= status < 400:
            results.append(
                _rule(
                    "HTTP_REDIRECT", subject, "url", "", info.scope, "pass",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([_http_evidence(final, {"status_code": status, "redirects": 0})]),
                )
            )
            continue
        if inspect:
            results.append(
                _rule(
                    "HTTP_REDIRECT", subject, "url", "", info.scope, "not_checked",
                    reason_code="inspect_single_url", urls=[(info.url_id, "affected")],
                    evidence=_clean([_http_evidence(final, {"status_code": status})]),
                )
            )
            continue
        analysis = _analyse_chain(data, info.url_id)
        facts = {
            "hops": analysis["hops"],
            "loop": analysis["loop"],
            "external_target": analysis["external"],
            "hop_limit": analysis["hop_limit"],
            "unresolved": analysis["unresolved"],
            "chain": [data.url_string(url_id) for url_id in analysis["chain"]],
            "max_redirects": data.config.crawl.max_redirects,
        }
        evidence: list[Evidence | None] = [
            _http_evidence(data.final_attempt(url_id), {
                "status_code": data.final_status(url_id),
                "position_in_chain": index,
            })
            for index, url_id in enumerate(analysis["chain"])
        ]
        evidence.append(_config_evidence(data, {"max_redirects": data.config.crawl.max_redirects}))
        urls = [(url_id, "source" if index == 0 else "affected") for index, url_id in enumerate(analysis["chain"])]
        if analysis["loop"]:
            blocker = _is_blocker(data, info)
            facts["summary"] = "Redirect-Schleife: " + " → ".join(facts["chain"])
            results.append(
                _rule(
                    "HTTP_REDIRECT", subject, "url", "", info.scope, "finding",
                    severity="critical" if blocker else "high",
                    confidence="confirmed", urls=urls,
                    evidence=_clean(evidence),
                    fix_kind="redirect", group_key=info.url,
                )
            )
            continue
        if analysis["hop_limit"]:
            facts["summary"] = f"Hop-Grenze von {data.config.crawl.max_redirects} erreicht"
            results.append(
                _rule(
                    "HTTP_REDIRECT", subject, "url", "", info.scope, "finding",
                    severity="medium", confidence="confirmed", urls=urls,
                    evidence=_clean(evidence),
                    fix_kind="redirect", group_key=info.url,
                )
            )
            continue
        if analysis["missing_location"]:
            facts["summary"] = "Weiterleitung ohne Location-Header"
            results.append(
                _rule(
                    "HTTP_REDIRECT", subject, "url", "", info.scope, "finding",
                    severity="medium", confidence="confirmed", urls=urls,
                    evidence=_clean(evidence),
                    fix_kind="redirect", group_key=info.url,
                )
            )
            continue
        if analysis["hops"] > 2:
            facts["summary"] = f"Redirect-Kette mit {analysis['hops']} Weiterleitungen"
            results.append(
                _rule(
                    "HTTP_REDIRECT", subject, "url", "", info.scope, "finding",
                    severity="medium", confidence="confirmed", urls=urls,
                    evidence=_clean(evidence),
                    fix_kind="redirect", group_key=info.url,
                )
            )
            continue
        if analysis["unresolved"]:
            facts["summary"] = "Redirect-Ziel wurde nicht geprüft"
            results.append(
                _rule(
                    "HTTP_REDIRECT", subject, "url", "", info.scope, "not_checked",
                    reason_code="redirect_target_not_checked", urls=urls,
                    evidence=_clean(evidence),
                )
            )
            continue
        facts["summary"] = (
            "Externes Redirect-Ziel" if analysis["external"]
            else f"{analysis['hops']} Weiterleitung(en), Ziel geprüft"
        )
        results.append(
            _rule(
                "HTTP_REDIRECT", subject, "url", "", info.scope, "pass",
                urls=urls, evidence=_clean(evidence),
            )
        )
    return results


# ---------------------------------------------------------------------- INDEX_ROBOTS_BLOCKED


def rule_index_robots_blocked(data: RunData) -> list[RuleResult]:
    results: list[RuleResult] = []
    for info in _page_urls(data):
        if info.state == "excluded":
            continue
        subject = key_for_url(info.url)
        if info.expected_indexable is False:
            results.append(
                _rule(
                    "INDEX_ROBOTS_BLOCKED", subject, "url", "", info.scope,
                    "not_applicable", reason_code="expected_non_indexable",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([_config_evidence(data, {"expected_indexable": False})]),
                )
            )
            continue
        robots = data.robots_for(info.url)
        if robots is None or robots.state in {"unknown", "unreachable"}:
            results.append(
                _rule(
                    "INDEX_ROBOTS_BLOCKED", subject, "url", "", info.scope, "not_checked",
                    reason_code="robots_unreachable", urls=[(info.url_id, "affected")],
                    evidence=_clean([
                        _crawl_evidence(data, {
                            "robots_state": robots.state if robots else "unknown",
                            "origin": robots.origin if robots else None,
                        })
                    ]),
                )
            )
            continue
        if robots.state == "unavailable" or robots.robots is None:
            results.append(
                _rule(
                    "INDEX_ROBOTS_BLOCKED", subject, "url", "", info.scope, "pass",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([
                        _crawl_evidence(data, {"robots_state": robots.state, "agent": GOOGLEBOT})
                    ]),
                )
            )
            continue
        normalized = normalize_url(info.url)
        path = f"{normalized.path}?{normalized.query}" if normalized.query else normalized.path
        decision = robots.robots.evaluate(path, GOOGLEBOT)
        attempt = data.attempt_by_id(robots.attempt_id)
        facts = {
            "agent": GOOGLEBOT,
            "origin": robots.origin,
            "path": path,
            "blocked": not decision.allowed,
            "robots_rule": decision.rule.text if decision.rule else None,
            "robots_group": decision.agent_token,
        }
        evidence = _clean([
            _http_evidence(attempt, facts) if attempt is not None else _crawl_evidence(data, facts),
            _config_evidence(data, {
                "expected_indexable": info.expected_indexable,
                "business_value": info.business_value,
                "page_type": info.page_type,
            }),
        ])
        if not decision.allowed:
            if info.expected_indexable is True:
                severity = "critical" if info.is_important else "high"
                confidence = "confirmed"
            else:
                severity = "low"
                confidence = "hint"
            facts["summary"] = (
                f"Googlebot durch robots.txt gesperrt: {decision.rule.text if decision.rule else 'Regel'}"
            )
            results.append(
                _rule(
                    "INDEX_ROBOTS_BLOCKED", subject, "url", "", info.scope, "finding",
                    severity=severity, confidence=confidence,
                    urls=[(info.url_id, "affected")], evidence=evidence,
                    fix_kind="robots", group_key=info.url,
                )
            )
        else:
            facts["summary"] = "Googlebot laut robots.txt zugelassen"
            results.append(
                _rule(
                    "INDEX_ROBOTS_BLOCKED", subject, "url", "", info.scope, "pass",
                    urls=[(info.url_id, "affected")], evidence=evidence,
                )
            )
    return results


# ---------------------------------------------------------------------- INDEX_NOINDEX


def rule_index_noindex(data: RunData) -> list[RuleResult]:
    results: list[RuleResult] = []
    for info in _page_urls(data):
        if info.state == "excluded":
            continue
        subject = key_for_url(info.url)
        if info.expected_indexable is False:
            results.append(
                _rule(
                    "INDEX_NOINDEX", subject, "url", "", info.scope, "not_applicable",
                    reason_code="expected_non_indexable", urls=[(info.url_id, "affected")],
                    evidence=_clean([_config_evidence(data, {"expected_indexable": False})]),
                )
            )
            continue
        state, reason = _content_reason(data, info.url_id)
        if state == "non_html":
            results.append(
                _rule(
                    "INDEX_NOINDEX", subject, "url", "", info.scope, "not_applicable",
                    reason_code="non_html_document", urls=[(info.url_id, "affected")],
                    evidence=_clean([_http_evidence(data.final_attempt(info.url_id), {"content_type": None})]),
                )
            )
            continue
        if state != "checked":
            results.append(
                _rule(
                    "INDEX_NOINDEX", subject, "url", "", info.scope, "not_checked",
                    reason_code=reason or "not_fetched", urls=[(info.url_id, "affected")],
                    evidence=_clean([
                        _http_evidence(data.final_attempt(info.url_id), {"summary": reason}),
                    ]),
                )
            )
            continue
        observation = data.observation(info.url_id)
        attempt = data.final_attempt(info.url_id)
        assert observation is not None
        noindex = bool(observation.signals.get("noindex"))
        facts = {
            "noindex": noindex,
            "robots_meta": observation.signals.get("robots_meta"),
            "x_robots_tag": observation.signals.get("x_robots_tag"),
            "robots_tokens": observation.signals.get("robots_tokens", []),
            "summary": (
                "noindex beobachtet ("
                + ("Meta-Tag" if observation.signals.get("robots_meta") else "X-Robots-Tag")
                + ")"
                if noindex
                else "kein noindex beobachtet"
            ),
        }
        evidence = _clean([
            _observation_evidence(observation, facts),
            _http_evidence(attempt, {"status_code": attempt.status_code if attempt else None}),
            _config_evidence(data, {
                "expected_indexable": info.expected_indexable,
                "business_value": info.business_value,
            }),
        ])
        if noindex:
            if info.expected_indexable is True:
                severity = "critical" if info.is_important else "high"
                confidence = "confirmed"
            else:
                severity = "info"
                confidence = "hint"
            results.append(
                _rule(
                    "INDEX_NOINDEX", subject, "url", "", info.scope, "finding",
                    severity=severity, confidence=confidence,
                    urls=[(info.url_id, "affected")], evidence=evidence,
                    fix_kind="noindex", group_key=info.url,
                )
            )
        else:
            results.append(
                _rule(
                    "INDEX_NOINDEX", subject, "url", "", info.scope, "pass",
                    urls=[(info.url_id, "affected")], evidence=evidence,
                )
            )
    return results


# ---------------------------------------------------------------------- Canonical


def _normalized_canonicals(data: RunData, url_id: int) -> tuple[list[str], list[str]]:
    observation = data.observation(url_id)
    if observation is None:
        return [], []
    valid: list[str] = []
    invalid: list[str] = []
    raw_values = list(observation.signals.get("canonical", []) or [])
    raw_values.extend(observation.signals.get("canonical_header", []) or [])
    for raw in raw_values:
        try:
            normalized = normalize_url(raw, data.config.crawl.remove_query_params).url
        except InvalidUrl:
            invalid.append(raw)
            continue
        if normalized not in valid:
            valid.append(normalized)
    return valid, invalid


def canonical_variant_target(data: RunData, url_id: int) -> int | None:
    """Prüft die Canonical-Variante für den Duplikat-Untercheck."""
    info = data.urls.get(url_id)
    if info is None or info.expected_indexable is True:
        return None
    observation = data.html_observation(url_id)
    if observation is None:
        return None
    canonicals, invalid = _normalized_canonicals(data, url_id)
    if invalid or len(canonicals) != 1:
        return None
    target_url = canonicals[0]
    if target_url == info.url:
        return None
    target_info = data.url_by_url.get(target_url)
    if target_info is None:
        return None
    attempt = data.final_attempt(target_info.url_id)
    if attempt is None or attempt.status_code != 200:
        return None
    target_observation = data.observation(target_info.url_id)
    if target_observation is None:
        return None
    robots = data.robots_for(target_info.url)
    if robots is not None and robots.state == "available" and robots.robots is not None:
        parsed = normalize_url(target_info.url)
        path = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
        if not robots.robots.is_allowed(path, GOOGLEBOT):
            return None
    if target_observation.signals.get("noindex"):
        return None
    target_canonicals, target_invalid = _normalized_canonicals(data, target_info.url_id)
    if target_invalid or len(target_canonicals) > 1:
        return None
    if target_canonicals and target_canonicals[0] != target_info.url:
        return None
    return target_info.url_id


def rule_canonical_target(data: RunData) -> list[RuleResult]:
    results: list[RuleResult] = []
    inspect = data.run.get("mode") == "inspect"
    for info in _page_urls(data):
        if info.state == "excluded":
            continue
        subject = key_for_url(info.url)
        state, reason = _content_reason(data, info.url_id)
        if state == "non_html":
            results.append(
                _rule(
                    "CANONICAL_TARGET", subject, "url", "", info.scope,
                    "not_applicable", reason_code="non_html_document",
                    urls=[(info.url_id, "affected")],
                )
            )
            continue
        if state != "checked":
            results.append(
                _rule(
                    "CANONICAL_TARGET", subject, "url", "", info.scope, "not_checked",
                    reason_code=reason or "not_fetched", urls=[(info.url_id, "affected")],
                )
            )
            continue
        observation = data.observation(info.url_id)
        assert observation is not None
        canonicals, invalid = _normalized_canonicals(data, info.url_id)
        base_evidence = _clean([
            _observation_evidence(observation, {
                "raw_canonicals": (
                    list(observation.signals.get("canonical", []) or [])
                    + list(observation.signals.get("canonical_header", []) or [])
                ),
                "normalized_canonicals": canonicals,
                "invalid_canonicals": invalid,
            }),
            _http_evidence(data.final_attempt(info.url_id), {"status_code": 200}),
        ])
        if not observation.signals.get("canonical") and not observation.signals.get("canonical_header"):
            results.append(
                _rule(
                    "CANONICAL_TARGET", subject, "url", "", info.scope, "pass",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([
                        _observation_evidence(observation, {"summary": "kein Canonical beobachtet"}),
                    ]),
                )
            )
            continue
        if invalid:
            results.append(
                _rule(
                    "CANONICAL_TARGET", subject, "url", "", info.scope, "finding",
                    severity="medium", confidence="confirmed",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([
                        _observation_evidence(observation, {
                            "summary": "Ungültiges Canonical-Ziel: " + ", ".join(invalid),
                        }),
                    ]),
                    fix_kind="canonical", group_key=info.url,
                )
            )
            continue
        if len(canonicals) > 1:
            results.append(
                _rule(
                    "CANONICAL_TARGET", subject, "url", "", info.scope, "finding",
                    severity="medium", confidence="confirmed",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([
                        _observation_evidence(observation, {
                            "summary": "Widersprüchliche Canonical-Angaben: " + ", ".join(canonicals),
                        }),
                    ]),
                    fix_kind="canonical", group_key=info.url,
                )
            )
            continue
        target_url = canonicals[0]
        if target_url == info.url:
            results.append(
                _rule(
                    "CANONICAL_TARGET", subject, "url", "", info.scope, "pass",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([
                        _observation_evidence(observation, {"summary": "Self-Canonical"}),
                    ]),
                )
            )
            continue
        try:
            target_parsed = normalize_url(target_url)
        except InvalidUrl:
            target_parsed = None
        if target_parsed is None or target_parsed.host not in data.config.allowed_hosts:
            results.append(
                _rule(
                    "CANONICAL_TARGET", subject, "url", "", info.scope, "not_checked",
                    reason_code="external_canonical_target",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([
                        _observation_evidence(observation, {
                            "summary": f"Externes Canonical-Ziel: {target_url}",
                        }),
                    ]),
                )
            )
            continue
        target_info = data.url_by_url.get(target_url)
        if target_info is None or target_info.url_id not in data.page_url_ids:
            results.append(
                _rule(
                    "CANONICAL_TARGET", subject, "url", "", info.scope, "not_checked",
                    reason_code="inspect_single_url" if inspect else "canonical_target_not_seen",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([
                        _observation_evidence(observation, {
                            "summary": f"Canonical-Ziel nicht im Lauf geprüft: {target_url}",
                        }),
                        _config_evidence(data, {"canonical_target": target_url}),
                    ]),
                )
            )
            continue
        target_state, target_reason = _content_reason(data, target_info.url_id)
        target_attempt = data.final_attempt(target_info.url_id)
        target_obs = data.observation(target_info.url_id)
        target_evidence = _clean([
            _http_evidence(target_attempt, {
                "status_code": target_attempt.status_code if target_attempt else None,
                "canonical_target": target_url,
            }),
            _observation_evidence(target_obs, {
                "noindex": bool(target_obs.signals.get("noindex")) if target_obs else None,
                "canonical": target_obs.signals.get("canonical") if target_obs else None,
            }),
        ])
        target_robots = data.robots_for(target_info.url)
        robots_blocked = False
        if (
            target_robots is not None
            and target_robots.state == "available"
            and target_robots.robots is not None
        ):
            parsed = normalize_url(target_info.url)
            robots_blocked = not target_robots.robots.is_allowed(
                f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path,
                GOOGLEBOT,
            )
        problem: str | None = None
        severity = "high"
        confidence = "confirmed"
        if target_info.state == "blocked" or robots_blocked:
            problem = "Googlebot ist am Canonical-Ziel gesperrt"
        elif target_state == "redirect":
            problem = "Canonical-Ziel leitet weiter"
        elif target_state == "error" and (
            target_attempt is None or target_attempt.status_code is None
        ):
            results.append(
                _rule(
                    "CANONICAL_TARGET", subject, "url", "", info.scope, "not_checked",
                    reason_code=target_reason or "canonical_target_not_checked",
                    urls=[(info.url_id, "affected"), (target_info.url_id, "target")],
                    evidence=_clean([*base_evidence, *target_evidence]),
                )
            )
            continue
        elif target_state == "error" and target_attempt is not None and target_attempt.status_code in {401, 403}:
            problem = "Canonical-Ziel ist zugriffsbeschränkt"
        elif target_state == "error" and target_attempt is not None and target_attempt.status_code is not None and 400 <= target_attempt.status_code < 600:
            problem = f"Canonical-Ziel liefert HTTP {target_attempt.status_code}"
        elif target_state == "non_html":
            problem = "Canonical-Ziel ist kein HTML-Dokument"
        elif target_state == "checked" and target_obs is not None and target_obs.signals.get("noindex"):
            problem = "Canonical-Ziel trägt noindex"
        elif target_state == "checked":
            target_canonicals, target_invalid = _normalized_canonicals(data, target_info.url_id)
            if target_invalid or len(target_canonicals) > 1:
                problem = "Canonical-Ziel hat widersprüchliche Canonical-Angaben"
            elif target_canonicals and target_canonicals[0] != target_info.url:
                problem = "Canonical-Ziel verweist auf eine weitere URL"
            elif info.expected_indexable is True:
                problem = "Profil erwartet eigenständige Indexierbarkeit, Canonical zeigt auf eine andere Seite"
                severity = "low"
                confidence = "hint"
        elif target_state in {"not_fetched", "deferred", "blocked"}:
            results.append(
                _rule(
                    "CANONICAL_TARGET", subject, "url", "", info.scope, "not_checked",
                    reason_code=target_reason or "canonical_target_not_checked",
                    urls=[(info.url_id, "affected"), (target_info.url_id, "target")],
                    evidence=_clean([*base_evidence, *target_evidence]),
                )
            )
            continue
        if problem is None:
            results.append(
                _rule(
                    "CANONICAL_TARGET", subject, "url", "", info.scope, "pass",
                    urls=[(info.url_id, "affected"), (target_info.url_id, "target")],
                    evidence=_clean([
                        *base_evidence,
                        _observation_evidence(observation, {"summary": "Canonical-Ziel geprüft: " + target_url}),
                    ]),
                )
            )
            continue
        facts = {"summary": problem, "canonical_target": target_url}
        results.append(
            _rule(
                "CANONICAL_TARGET", subject, "url", "", info.scope, "finding",
                severity=severity, confidence=confidence,
                urls=[(info.url_id, "affected"), (target_info.url_id, "target")],
                evidence=_clean([
                    *base_evidence,
                    *target_evidence,
                    _config_evidence(data, {
                        "expected_indexable": info.expected_indexable,
                        "canonical_target": target_url,
                    }),
                ]),
                fix_kind="canonical", group_key=info.url,
            )
        )
        results[-1].evidence.insert(0, Evidence(
            source_kind="page_observation",
            observed_at=observation.observed_at,
            facts=facts,
            observation_id=observation.observation_id,
        ))
    return results


# ---------------------------------------------------------------------- Sitemap


def rule_sitemap_target(data: RunData) -> list[RuleResult]:
    results: list[RuleResult] = []
    for info in data.sitemap_targets():
        if info.state == "excluded":
            continue
        subject = key_for_url(info.url)
        state, reason = _content_reason(data, info.url_id)
        sitemap_facts = {
            "sitemaps": [data.url_string(source) for source in info.sitemap_sources],
            "discoveries": info.discovery_originals,
        }
        if state == "blocked":
            results.append(
                _rule(
                    "SITEMAP_TARGET", subject, "url", "", "sitemap", "not_checked",
                    reason_code=reason or "robots_disallowed",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([_crawl_evidence(data, sitemap_facts)]),
                )
            )
            continue
        if state == "deferred":
            results.append(
                _rule(
                    "SITEMAP_TARGET", subject, "url", "", "sitemap", "not_checked",
                    reason_code=reason or "url_limit_reached",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([_crawl_evidence(data, sitemap_facts)]),
                )
            )
            continue
        if state == "error":
            attempt = data.final_attempt(info.url_id)
            if attempt is not None and attempt.state == "transport_error":
                results.append(
                    _rule(
                        "SITEMAP_TARGET", subject, "url", "", "sitemap", "not_checked",
                        reason_code=reason or "fetch_error",
                        urls=[(info.url_id, "affected")],
                        evidence=_clean([
                            _http_evidence(attempt, {"error_code": attempt.error_code}),
                            _crawl_evidence(data, sitemap_facts),
                        ]),
                    )
                )
                continue
            facts = {
                "status_code": attempt.status_code if attempt else None,
                "summary": f"Sitemap-Ziel liefert HTTP {attempt.status_code}" if attempt else "Sitemap-Ziel fehlerhaft",
            }
            results.append(
                _rule(
                    "SITEMAP_TARGET", subject, "url", "", "sitemap", "finding",
                    severity="high", confidence="confirmed",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([
                        _http_evidence(attempt, facts),
                        _crawl_evidence(data, sitemap_facts),
                    ]),
                    fix_kind="sitemap", group_key=info.url,
                )
            )
            continue
        if state == "redirect":
            attempt = data.final_attempt(info.url_id)
            results.append(
                _rule(
                    "SITEMAP_TARGET", subject, "url", "", "sitemap", "finding",
                    severity="high", confidence="confirmed",
                    urls=[(info.url_id, "affected"), *(
                        [(attempt.location_url_id, "target")] if attempt and attempt.location_url_id else []
                    )],
                    evidence=_clean([
                        _http_evidence(attempt, {
                            "status_code": attempt.status_code if attempt else None,
                            "summary": "Sitemap-Eintrag leitet weiter",
                        }),
                        _crawl_evidence(data, sitemap_facts),
                    ]),
                    fix_kind="sitemap", group_key=info.url,
                )
            )
            continue
        if state == "non_html":
            results.append(
                _rule(
                    "SITEMAP_TARGET", subject, "url", "", "sitemap", "finding",
                    severity="medium", confidence="confirmed",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([
                        _http_evidence(data.final_attempt(info.url_id), {"content_type": "non-html"}),
                        _crawl_evidence(data, sitemap_facts),
                    ]),
                    fix_kind="sitemap", group_key=info.url,
                )
            )
            continue
        if state != "checked":
            results.append(
                _rule(
                    "SITEMAP_TARGET", subject, "url", "", "sitemap", "not_checked",
                    reason_code=reason or "not_fetched",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([_crawl_evidence(data, sitemap_facts)]),
                )
            )
            continue
        observation = data.observation(info.url_id)
        assert observation is not None
        noindex = bool(observation.signals.get("noindex"))
        facts = {
            "noindex": noindex,
            "status_code": 200,
            "summary": "Sitemap-Ziel trägt noindex" if noindex else "Sitemap-Ziel ist abrufbar und indexierbar",
        }
        if noindex:
            results.append(
                _rule(
                    "SITEMAP_TARGET", subject, "url", "", "sitemap", "finding",
                    severity="high", confidence="confirmed",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([
                        _observation_evidence(observation, facts),
                        _http_evidence(data.final_attempt(info.url_id), {"status_code": 200}),
                        _crawl_evidence(data, sitemap_facts),
                    ]),
                    fix_kind="sitemap", group_key=info.url,
                )
            )
        else:
            results.append(
                _rule(
                    "SITEMAP_TARGET", subject, "url", "", "sitemap", "pass",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([
                        _observation_evidence(observation, facts),
                        _crawl_evidence(data, sitemap_facts),
                    ]),
                )
            )
    return results


# ---------------------------------------------------------------------- Links


def rule_link_broken(data: RunData) -> list[RuleResult]:
    results: list[RuleResult] = []
    edges: list[tuple[int, int]] = []
    for source, targets in data.links.items():
        for target, complete in targets.items():
            if complete:
                edges.append((source, target))
    edges.sort(key=lambda pair: (data.url_string(pair[0]), data.url_string(pair[1])))
    for source_id, target_id in edges:
        source = data.urls.get(source_id)
        target = data.urls.get(target_id)
        if source is None or target is None:
            continue
        subject = key_for_link(source.url, target.url)
        if target.state == "excluded":
            reason = target.reason_code or "excluded"
            results.append(
                _rule(
                    "LINK_BROKEN", subject, "link", "", "internal_links", "not_applicable",
                    reason_code="external_target" if reason == "host_not_allowed" else "excluded_target",
                    urls=[(source_id, "source"), (target_id, "target")],
                    evidence=_clean([
                        _observation_evidence(data.observation(source_id), {"link_present": True}),
                        _crawl_evidence(data, {"target_reason": reason}),
                    ]),
                )
            )
            continue
        target_state, target_reason = _content_reason(data, target_id)
        if target_state == "blocked":
            results.append(
                _rule(
                    "LINK_BROKEN", subject, "link", "", "internal_links", "not_checked",
                    reason_code="target_robots_disallowed",
                    urls=[(source_id, "source"), (target_id, "target")],
                    evidence=_clean([_crawl_evidence(data, {"target_reason": target_reason})]),
                )
            )
            continue
        if target_state in {"deferred"}:
            results.append(
                _rule(
                    "LINK_BROKEN", subject, "link", "", "internal_links", "not_checked",
                    reason_code=target_reason or "url_limit_reached",
                    urls=[(source_id, "source"), (target_id, "target")],
                    evidence=_clean([_crawl_evidence(data, {"target_reason": target_reason})]),
                )
            )
            continue
        target_attempt = data.final_attempt(target_id)
        if target_attempt is None:
            results.append(
                _rule(
                    "LINK_BROKEN", subject, "link", "", "internal_links", "not_checked",
                    reason_code="target_not_fetched",
                    urls=[(source_id, "source"), (target_id, "target")],
                    evidence=_clean([_crawl_evidence(data, {"target_state": target.state})]),
                )
            )
            continue
        if target_attempt.state == "transport_error":
            results.append(
                _rule(
                    "LINK_BROKEN", subject, "link", "", "internal_links", "not_checked",
                    reason_code="target_fetch_timeout" if target_attempt.error_code == "timeout" else "target_fetch_error",
                    urls=[(source_id, "source"), (target_id, "target")],
                    evidence=_clean([_http_evidence(target_attempt, {"error_code": target_attempt.error_code})]),
                )
            )
            continue
        status = target_attempt.status_code
        facts = {
            "target_status": status,
            "target_url": target.url,
            "source_url": source.url,
            "summary": f"Linkziel liefert HTTP {status}",
        }
        if status in {404, 410}:
            results.append(
                _rule(
                    "LINK_BROKEN", subject, "link", "", "internal_links", "finding",
                    severity="high", confidence="confirmed",
                    urls=[(source_id, "source"), (target_id, "target")],
                    evidence=_clean([
                        _http_evidence(target_attempt, facts),
                        _observation_evidence(data.observation(source_id), {
                            "summary": "Link in vollständig ausgewerteter Seite gefunden",
                        }),
                    ]),
                    fix_kind="broken_link", group_key=target.url,
                )
            )
            continue
        if status in {401, 403}:
            results.append(
                _rule(
                    "LINK_BROKEN", subject, "link", "", "internal_links", "not_checked",
                    reason_code="access_restricted",
                    urls=[(source_id, "source"), (target_id, "target")],
                    evidence=_clean([_http_evidence(target_attempt, facts)]),
                )
            )
            continue
        if status is not None and 400 <= status < 600:
            results.append(
                _rule(
                    "LINK_BROKEN", subject, "link", "", "internal_links", "not_checked",
                    reason_code="target_server_error",
                    urls=[(source_id, "source"), (target_id, "target")],
                    evidence=_clean([_http_evidence(target_attempt, facts)]),
                )
            )
            continue
        results.append(
            _rule(
                "LINK_BROKEN", subject, "link", "", "internal_links", "pass",
                urls=[(source_id, "source"), (target_id, "target")],
                evidence=_clean([
                    _http_evidence(target_attempt, {
                        "status_code": status,
                        "summary": f"Linkziel erreichbar (HTTP {status})",
                    })
                ]),
            )
        )
    return results


def _orphan_candidates(data: RunData) -> list[UrlInfo]:
    start = data.config.start_url
    candidates: list[UrlInfo] = []
    for info in _page_urls(data):
        if info.state == "excluded" or info.url == start:
            continue
        if info.kinds & {"sitemap", "gsc", "seed"}:
            candidates.append(info)
    return candidates


def rule_link_orphan_candidate(data: RunData) -> list[RuleResult]:
    results: list[RuleResult] = []
    if data.run.get("mode") == "inspect":
        return results
    candidates = _orphan_candidates(data)
    coverage = data.graph_coverage()
    complete = data.link_graph_complete()
    for info in candidates:
        subject = key_for_url(info.url)
        state, reason = _content_reason(data, info.url_id)
        if state == "non_html":
            results.append(
                _rule(
                    "LINK_ORPHAN_CANDIDATE", subject, "url", "", "internal_links",
                    "not_applicable", reason_code="non_html_document",
                    urls=[(info.url_id, "affected")],
                )
            )
            continue
        if state != "checked":
            results.append(
                _rule(
                    "LINK_ORPHAN_CANDIDATE", subject, "url", "", "internal_links", "not_checked",
                    reason_code=reason or "not_fetched", urls=[(info.url_id, "affected")],
                    evidence=_clean([_crawl_evidence(data, {"coverage": coverage})]),
                )
            )
            continue
        inbound = data.inbound_sources(info.url_id)
        facts = {
            "inbound_links": len(inbound),
            "inbound_sources": [data.url_string(source) for source in sorted(inbound)][:10],
            "discovered_via": sorted(info.kinds),
            "graph_coverage": coverage,
            "graph_complete": complete,
            "summary": (
                (
                    f"Kein eingehender interner Link beobachtet ({coverage['complete']} "
                    f"vollständig ausgewertete Seiten, {coverage['incomplete']} unvollständig, "
                    f"{coverage['missing']} ohne Extrakt)"
                )
                if not inbound
                else f"{len(inbound)} eingehender interner Link beobachtet"
            ),
        }
        evidence = _clean([
            _crawl_evidence(data, facts),
            _observation_evidence(data.observation(info.url_id), {"status": "checked"}),
        ])
        if inbound:
            results.append(
                _rule(
                    "LINK_ORPHAN_CANDIDATE", subject, "url", "", "internal_links", "pass",
                    urls=[(info.url_id, "affected")], evidence=evidence,
                )
            )
        else:
            results.append(
                _rule(
                    "LINK_ORPHAN_CANDIDATE", subject, "url", "", "internal_links", "finding",
                    severity="low",
                    confidence="confirmed" if complete else "hint",
                    urls=[(info.url_id, "affected")], evidence=evidence,
                    fix_kind="orphan", group_key=info.url,
                )
            )
    return results


def rule_link_depth(data: RunData) -> list[RuleResult]:
    results: list[RuleResult] = []
    limit = data.config.link_depth_limit
    for info in _page_urls(data):
        if info.state == "excluded" or not info.is_important:
            continue
        subject = key_for_url(info.url)
        facts = {
            "click_depth": info.click_depth,
            "limit": limit,
            "summary": (
                f"Klicktiefe {info.click_depth} (Grenze {limit})"
                if info.click_depth is not None
                else "Klicktiefe unbekannt"
            ),
        }
        if info.click_depth is None:
            results.append(
                _rule(
                    "LINK_DEPTH", subject, "url", "", info.scope, "not_checked",
                    reason_code="incomplete_link_graph", urls=[(info.url_id, "affected")],
                    evidence=_clean([_crawl_evidence(data, facts)]),
                )
            )
            continue
        evidence = _clean([
            _crawl_evidence(data, facts),
            _config_evidence(data, {"link_depth_limit": limit}),
        ])
        if info.click_depth > limit:
            results.append(
                _rule(
                    "LINK_DEPTH", subject, "url", "", info.scope, "finding",
                    severity="info", confidence="hint",
                    urls=[(info.url_id, "affected")], evidence=evidence,
                    fix_kind="depth", group_key=info.url,
                )
            )
        else:
            results.append(
                _rule(
                    "LINK_DEPTH", subject, "url", "", info.scope, "pass",
                    urls=[(info.url_id, "affected")], evidence=evidence,
                )
            )
    return results


# ---------------------------------------------------------------------- Meta


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(value.split())


def _meta_rule(data: RunData, rule_id: str, attribute: str, severity: str) -> list[RuleResult]:
    results: list[RuleResult] = []
    inspect = data.run.get("mode") == "inspect"
    candidates: list[tuple[UrlInfo, ObservationInfo, str]] = []
    for info in _page_urls(data):
        if info.state == "excluded":
            continue
        subject_base = key_for_url(info.url)
        if info.expected_indexable is False:
            results.append(
                _rule(
                    rule_id, subject_base, "url", "", info.scope, "not_applicable",
                    reason_code="expected_non_indexable", urls=[(info.url_id, "affected")],
                    evidence=_clean([_config_evidence(data, {"expected_indexable": False})]),
                )
            )
            continue
        state, reason = _content_reason(data, info.url_id)
        if state == "non_html":
            results.append(
                _rule(
                    rule_id, subject_base, "url", "", info.scope, "not_applicable",
                    reason_code="non_html_document", urls=[(info.url_id, "affected")],
                )
            )
            continue
        if state != "checked":
            results.append(
                _rule(
                    rule_id, subject_base, "url", "", info.scope, "not_checked",
                    reason_code=reason or "not_fetched", urls=[(info.url_id, "affected")],
                )
            )
            continue
        observation = data.observation(info.url_id)
        if observation is None:
            results.append(
                _rule(
                    rule_id, subject_base, "url", "", info.scope, "not_checked",
                    reason_code="empty_body", urls=[(info.url_id, "affected")],
                )
            )
            continue
        value = observation.title if attribute == "title" else observation.meta_description
        normalized = _normalize_text(value)
        if not normalized:
            facts = {"summary": "Titel fehlt" if attribute == "title" else "Meta-Beschreibung fehlt"}
            results.append(
                _rule(
                    rule_id, key_for_url(info.url, "missing"), "url", "missing",
                    info.scope, "finding", severity=severity, confidence="confirmed",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([
                        _observation_evidence(observation, facts),
                        _http_evidence(data.final_attempt(info.url_id), {"status_code": 200}),
                    ]),
                    fix_kind=f"missing_{attribute}",
                    group_key=info.url,
                )
            )
            results.append(
                _rule(
                    rule_id, key_for_url(info.url, "duplicate"), "url", "duplicate",
                    info.scope, "not_applicable", reason_code="title_absent" if attribute == "title" else "description_absent",
                    urls=[(info.url_id, "affected")],
                )
            )
            continue
        results.append(
            _rule(
                rule_id, key_for_url(info.url, "missing"), "url", "missing",
                info.scope, "pass", urls=[(info.url_id, "affected")],
                evidence=_clean([_observation_evidence(observation, {"value": value})]),
            )
        )
        candidates.append((info, observation, normalized))

    if inspect:
        for info, observation, normalized in candidates:
            results.append(
                _rule(
                    rule_id, key_for_url(info.url, "duplicate"), "url", "duplicate",
                    info.scope, "not_checked", reason_code="single_page_scope",
                    urls=[(info.url_id, "affected")],
                )
            )
        return results

    groups: dict[str, list[tuple[UrlInfo, ObservationInfo, str]]] = {}
    for info, observation, normalized in candidates:
        if canonical_variant_target(data, info.url_id) is not None:
            results.append(
                _rule(
                    rule_id, key_for_url(info.url, "duplicate"), "url", "duplicate",
                    info.scope, "not_applicable", reason_code="canonical_duplicate_variant",
                    urls=[(info.url_id, "affected")],
                    evidence=_clean([_observation_evidence(observation, {"summary": "Canonical-Variante"})]),
                )
            )
            continue
        groups.setdefault(normalized, []).append((info, observation, normalized))
    for normalized_value, members in groups.items():
        duplicate = len(members) >= 2
        for info, observation, _ in members:
            if duplicate:
                facts = {
                    "value": observation.title if attribute == "title" else observation.meta_description,
                    "normalized_value": normalized_value,
                    "duplicate_count": len(members),
                    "group_examples": [member[0].url for member in members][:10],
                    "summary": f"Identischer {('Titel' if attribute == 'title' else 'Meta-Beschreibung')} auf {len(members)} Seiten",
                }
                results.append(
                    _rule(
                        rule_id, key_for_url(info.url, "duplicate"), "url", "duplicate",
                        info.scope, "finding", severity=severity, confidence="confirmed",
                        urls=[(info.url_id, "affected"), *[
                            (member[0].url_id, "source") for member in members if member[0].url_id != info.url_id
                        ]],
                        evidence=_clean([_observation_evidence(observation, facts)]),
                        fix_kind=f"duplicate_{attribute}",
                        group_key=sha256_text(normalized_value),
                    )
                )
            else:
                results.append(
                    _rule(
                        rule_id, key_for_url(info.url, "duplicate"), "url", "duplicate",
                        info.scope, "pass", urls=[(info.url_id, "affected")],
                        evidence=_clean([_observation_evidence(observation, {
                            "summary": "Eindeutiger Wert",
                        })]),
                    )
                )
    return results


def rule_meta_title(data: RunData) -> list[RuleResult]:
    return _meta_rule(data, "META_TITLE", "title", "medium")


def rule_meta_description(data: RunData) -> list[RuleResult]:
    return _meta_rule(data, "META_DESCRIPTION", "description", "low")


# ---------------------------------------------------------------------- Engine


TECHNICAL_RULES: tuple[Callable[[RunData], list[RuleResult]], ...] = (
    rule_http_unavailable,
    rule_http_redirect,
    rule_index_robots_blocked,
    rule_index_noindex,
    rule_canonical_target,
    rule_sitemap_target,
    rule_link_broken,
    rule_link_orphan_candidate,
    rule_link_depth,
    rule_meta_title,
    rule_meta_description,
)


def _apply_exceptions(data: RunData, results: list[RuleResult]) -> None:
    for result in results:
        if result.outcome != "finding":
            continue
        urls = [data.url_string(url_id) for url_id, _ in result.urls]
        for exception in data.config.rule_exceptions:
            if exception.matches(result.rule_id, urls):
                result.exception = {
                    "reason": exception.reason,
                    "url": exception.url,
                    "path": exception.path,
                    "expires": exception.expires.isoformat() if exception.expires else None,
                }
                break


def _validate(results: list[RuleResult]) -> None:
    seen: dict[tuple[str, str], RuleResult] = {}
    for result in results:
        if result.rule_id not in RULE_VERSIONS:
            raise ValueError(f"Unbekannte Regel-ID: {result.rule_id}")
        if result.outcome == "finding":
            if result.severity not in SEVERITY_RANK or result.confidence not in CONFIDENCE_RANK:
                raise ValueError(
                    f"Befund ohne gültigen Schweregrad/Beleglage: {result.rule_id} {result.subject_key}"
                )
        elif result.outcome in {"not_checked", "not_applicable"}:
            if not result.reason_code:
                raise ValueError(
                    f"{result.outcome} ohne reason_code: {result.rule_id} {result.subject_key}"
                )
        elif result.outcome not in {"pass"}:
            raise ValueError(f"Unbekanntes Ergebnis: {result.outcome}")
        if result.outcome == "finding" and not result.evidence:
            raise ValueError(
                f"Befund ohne Evidenz: {result.rule_id} {result.subject_key}"
            )
        key = result.key
        if key in seen:
            raise ValueError(
                f"Doppeltes Prüfergebnis: {result.rule_id} {result.subject_key}"
            )
        seen[key] = result


def evaluate(data: RunData) -> list[RuleResult]:
    results: list[RuleResult] = []
    for rule in TECHNICAL_RULES:
        results.extend(rule(data))
    from seoboy.analysis.rules_gsc import evaluate_gsc

    results.extend(evaluate_gsc(data))
    if data.run.get("mode") == "inspect":
        _inspect_site_results(data, results)
    _apply_exceptions(data, results)
    _validate(results)
    return results


def _inspect_site_results(data: RunData, results: list[RuleResult]) -> None:
    present = {result.rule_id for result in results}
    for rule_id in ("LINK_BROKEN", "LINK_ORPHAN_CANDIDATE", "SITEMAP_TARGET"):
        if rule_id in present:
            continue
        results.append(
            _rule(
                rule_id,
                stable_json(["site", "inspect", rule_id]),
                "site",
                "",
                "inspect",
                "not_checked",
                reason_code="incomplete_link_graph",
                evidence=_clean([_crawl_evidence(data, {
                    "summary": "Einzel-URL-Prüfung ohne Linkgraphen; Regel nicht prüfbar",
                })]),
            )
        )


def persist_results(
    connection: sqlite3.Connection,
    run_id: str,
    results: list[RuleResult],
) -> None:
    for result in results:
        connection.execute(
            "INSERT INTO rule_results(run_id, rule_id, subject_key, subject_kind, "
            "rule_version, subcheck, scope_key, outcome, severity, confidence, "
            "reason_code, exception_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                result.rule_id,
                result.subject_key,
                result.subject_kind,
                result.rule_version,
                result.subcheck,
                result.scope_key,
                result.outcome,
                result.severity,
                result.confidence,
                result.reason_code,
                json.dumps(result.exception, ensure_ascii=False) if result.exception else None,
            ),
        )
        for url_id, relation in result.urls:
            connection.execute(
                "INSERT OR IGNORE INTO result_urls(run_id, rule_id, subject_key, url_id, "
                "relation) VALUES (?, ?, ?, ?, ?)",
                (run_id, result.rule_id, result.subject_key, url_id, relation),
            )
        for ordinal, evidence in enumerate(result.evidence, start=1):
            connection.execute(
                "INSERT INTO rule_evidence(run_id, rule_id, subject_key, ordinal, "
                "source_kind, attempt_id, observation_id, import_id, observed_at, facts_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    result.rule_id,
                    result.subject_key,
                    ordinal,
                    evidence.source_kind,
                    evidence.attempt_id,
                    evidence.observation_id,
                    evidence.import_id,
                    evidence.observed_at,
                    json.dumps(evidence.facts, ensure_ascii=False),
                ),
            )
