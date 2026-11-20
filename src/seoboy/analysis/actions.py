"""Group findings into actions, prioritize them, and add text templates."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Any

from seoboy.analysis.audit_data import RunData, UrlInfo
from seoboy.analysis.rules import CONFIDENCE_RANK, RuleResult
from seoboy.shared.urls import relative_url
from seoboy.shared.util import truncate

BUSINESS_RANK = {"high": 0, "normal": 1, "low": 2}
EFFORT_RANK = {"small": 0, "medium": 1, "large": 2, "unknown": 3}
EFFORT = {
    "HTTP_UNAVAILABLE": "medium",
    "HTTP_REDIRECT": "medium",
    "INDEX_ROBOTS_BLOCKED": "small",
    "INDEX_NOINDEX": "small",
    "CANONICAL_TARGET": "small",
    "SITEMAP_TARGET": "small",
    "LINK_BROKEN": "small",
    "LINK_ORPHAN_CANDIDATE": "small",
    "LINK_DEPTH": "small",
    "META_TITLE": "small",
    "META_DESCRIPTION": "small",
    "GSC_NEAR_TOP": "medium",
    "GSC_DECLINE": "medium",
    "GSC_CTR_REVIEW": "small",
    "GSC_MULTI_URL": "medium",
}
P2_RULES = {
    "HTTP_UNAVAILABLE",
    "HTTP_REDIRECT",
    "INDEX_ROBOTS_BLOCKED",
    "INDEX_NOINDEX",
    "CANONICAL_TARGET",
    "SITEMAP_TARGET",
    "LINK_BROKEN",
}
GSC_QUERY_RULES = {
    "GSC_NEAR_TOP",
    "GSC_DECLINE",
    "GSC_CTR_REVIEW",
    "GSC_MULTI_URL",
}
GSC_BUNDLE_RULES = {"GSC_NEAR_TOP", "GSC_CTR_REVIEW"}
COMMERCIAL_TERMS = (
    "dj",
    "hochzeit",
    "firmenfeier",
    "geburtstag",
    "karneval",
    "buchen",
    "buchung",
    "preis",
    "kosten",
    "miete",
    "mieten",
    "verleih",
    "vermietung",
    "angebot",
    "kontakt",
)
INFORMATIONAL_TERMS = (
    "pdf",
    "anleitung",
    "bau",
    "selber",
    "selbst",
    "plan",
    "skizze",
    "schaltplan",
    "grundlagen",
)


@dataclass
class ActionDraft:
    action_key: str
    priority: int
    effort: str
    title: str
    proposed_fix: str
    expected_effect: str
    verification: str
    findings: list[RuleResult]
    urls: list[int]
    business_value: str
    confidence: str
    confidence_rank: int
    reach: int

    @property
    def rule_id(self) -> str:
        return self.findings[0].rule_id


def _affected_infos(data: RunData, findings: list[RuleResult]) -> list[UrlInfo]:
    infos: list[UrlInfo] = []
    seen: set[int] = set()
    for finding in findings:
        for url_id, _relation in finding.urls:
            if url_id in seen:
                continue
            info = data.urls.get(url_id)
            if info is None:
                continue
            seen.add(url_id)
            infos.append(info)
    return infos


def _distinct_url_ids(findings: list[RuleResult]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for finding in findings:
        for url_id, _relation in finding.urls:
            if url_id not in seen:
                seen.add(url_id)
                ordered.append(url_id)
    return ordered


def _primary_url(data: RunData, findings: list[RuleResult]) -> str:
    if not findings:
        return ""
    for url_id, relation in findings[0].urls:
        if relation in {"affected", "target"}:
            return data.url_string(url_id)
    if findings[0].urls:
        return data.url_string(findings[0].urls[0][0])
    return findings[0].subject_key


def _display(data: RunData, url: str) -> str:
    return relative_url(url, data.config.allowed_hosts)


def _facts(findings: list[RuleResult]) -> dict[str, Any]:
    for finding in findings:
        for evidence in finding.evidence:
            if evidence.facts:
                return evidence.facts
    return {}


def _query_facts(findings: list[RuleResult]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for finding in findings:
        facts = _facts([finding])
        query = facts.get("query")
        if query:
            rows.append(facts)
    return rows


def _booking_intent(findings: list[RuleResult]) -> bool:
    facts_rows = _query_facts(findings)
    text = " ".join(
        str(row.get("query") or row.get("page") or "") for row in facts_rows
    ).casefold()
    if not text:
        return False
    return any(term in text for term in COMMERCIAL_TERMS) and not any(
        term in text for term in INFORMATIONAL_TERMS
    )


def _bundle_query_findings(
    data: RunData, groups: dict[tuple[str, str, str], list[RuleResult]]
) -> dict[tuple[str, str, str], list[RuleResult]]:
    bundled: dict[tuple[str, str, str], list[RuleResult]] = {}
    for (rule_id, fix_kind, _group_key), findings in groups.items():
        if rule_id not in GSC_BUNDLE_RULES:
            bundled[(rule_id, fix_kind, _group_key)] = findings
            continue
        page = _primary_url(data, findings)
        scope = findings[0].scope_key if findings else ""
        key = (rule_id, fix_kind, f"page:{page}|{scope}")
        bundled.setdefault(key, []).extend(findings)
    return bundled


def _cause_counts(results: list[RuleResult]) -> dict[tuple[str, str], set[int]]:
    counts: dict[tuple[str, str], set[int]] = {}
    for result in results:
        if result.outcome != "finding" or result.exception is not None:
            continue
        key = (result.rule_id, result.fix_kind or result.rule_id)
        bucket = counts.setdefault(key, set())
        for url_id, _relation in result.urls:
            bucket.add(url_id)
    return counts


def _group_findings(results: list[RuleResult]) -> dict[tuple[str, str, str], list[RuleResult]]:
    groups: dict[tuple[str, str, str], list[RuleResult]] = {}
    for result in results:
        if result.outcome != "finding" or result.exception is not None:
            continue
        fix_kind = result.fix_kind or result.rule_id.lower()
        group_key = result.group_key or result.subject_key
        groups.setdefault((result.rule_id, fix_kind, group_key), []).append(result)
    return groups


def _priority(
    rule_id: str,
    fix_kind: str,
    findings: list[RuleResult],
    infos: list[UrlInfo],
    cause_count: int,
) -> int:
    confirmed = all(finding.confidence == "confirmed" for finding in findings)
    critical = any(
        finding.severity == "critical" and finding.confidence == "confirmed"
        for finding in findings
    )
    if critical:
        return 1
    important = any(info.is_important for info in infos)
    if (
        rule_id in P2_RULES
        and confirmed
        and (important or cause_count >= 3)
    ):
        return 2
    if rule_id in GSC_QUERY_RULES:
        if rule_id == "GSC_MULTI_URL":
            return 4
        if important and _booking_intent(findings):
            return 2
        return 3
    if rule_id == "LINK_ORPHAN_CANDIDATE":
        return 3
    if rule_id == "LINK_DEPTH":
        return 4
    if rule_id == "META_DESCRIPTION":
        return 4
    if rule_id == "META_TITLE":
        return 3 if important else 4
    if rule_id in P2_RULES:
        return 3
    return 3


def _bundle_texts(
    data: RunData, rule_id: str, findings: list[RuleResult]
) -> tuple[str, str, str, str]:
    rows = sorted(
        _query_facts(findings),
        key=lambda row: (-int(row.get("impressions") or 0), str(row.get("query"))),
    )
    page = _display(data, _primary_url(data, findings))
    impressions = sum(int(row.get("impressions") or 0) for row in rows)
    clicks = sum(int(row.get("clicks") or 0) for row in rows)
    weighted = [
        (float(row["position"]), int(row.get("impressions") or 0))
        for row in rows
        if row.get("position") is not None and int(row.get("impressions") or 0)
    ]
    position = (
        sum(value * weight for value, weight in weighted)
        / sum(weight for _value, weight in weighted)
        if weighted
        else None
    )
    labels = [f"»{truncate(str(row.get('query')), 60)}«" for row in rows[:3]]
    if len(rows) > 3:
        labels.append(f"u. a. {len(rows) - 3} weitere")
    query_text = ", ".join(labels)
    metrics = f"{impressions} Impressionen, {clicks} Klicks"
    if position is not None:
        metrics += f", Ø Position {position:.1f}"
    title = f"Suchchancen auf {page}: {len(rows)} Suchanfragen bündeln"
    fix = (
        f"{metrics}: {query_text} nach Suchintention trennen und Title, Snippet "
        "sowie interne Verlinkung der Zielseite darauf ausrichten."
    )
    return (
        title,
        fix,
        "Weniger doppelte Prüfaufträge und eine klare Seitenpriorität.",
        "Im nächsten GSC-Zeitraum Impressionen, Klicks und Positionen der gebündelten "
        "Suchanfragen gemeinsam vergleichen.",
    )


def _texts(
    data: RunData,
    rule_id: str,
    fix_kind: str,
    findings: list[RuleResult],
    infos: list[UrlInfo],
) -> tuple[str, str, str, str]:
    if len(findings) > 1 and rule_id in GSC_BUNDLE_RULES:
        return _bundle_texts(data, rule_id, findings)
    facts = _facts(findings)
    primary = _display(data, _primary_url(data, findings))
    if fix_kind == "broken_link":
        target = _display(data, findings[0].group_key or primary)
        sources = []
        for finding in findings:
            for url_id, relation in finding.urls:
                if relation == "source":
                    sources.append(_display(data, data.url_string(url_id)))
        sources = list(dict.fromkeys(sources))
        source_text = ", ".join(sources[:3])
        if len(sources) > 3:
            source_text += f" u. a. ({len(sources)} Quellseiten)"
        return (
            f"Defektes Linkziel {target} korrigieren",
            f"Links auf {target} in {source_text} auf eine gültige URL ändern oder das Ziel wiederherstellen.",
            "Interne Links führen nicht mehr ins Leere; Nutzer und Crawler erreichen das gewünschte Ziel.",
            "Quellseiten erneut crawlen und das Linkziel auf einen 2xx-Status prüfen.",
        )
    if rule_id == "HTTP_UNAVAILABLE":
        status = facts.get("status_code")
        return (
            f"HTTP-Fehler auf {primary} beheben",
            "Antwortstatus der Seite korrigieren: Inhalt wiederherstellen oder dauerhaft auf ein gültiges Ziel weiterleiten.",
            "Die Seite ist für Nutzer und Suchmaschinen wieder erreichbar.",
            "URL erneut abrufen; erwartet wird ein 2xx-Status ohne Transportfehler.",
        )
    if rule_id == "HTTP_REDIRECT":
        return (
            f"Weiterleitungen für {primary} bereinigen",
            "Weiterleitungskette auf ein direkt erreichbares Ziel zusammenfassen und Schleifen auflösen.",
            "Kurze, eindeutige Weiterleitungswege; Linkziele werden ohne Umwege erreicht.",
            "URL abrufen und die Kette prüfen; höchstens zwei Weiterleitungen bis HTTP 200.",
        )
    if rule_id == "INDEX_ROBOTS_BLOCKED":
        return (
            f"Googlebot-Sperre für {primary} prüfen",
            "Passende robots.txt-Regel für diese URL entfernen oder eine gezielte Ausnahme ergänzen, sofern die Seite indexiert werden soll.",
            "Googlebot kann die Seite abrufen und indexieren.",
            "robots.txt und URL erneut prüfen; Googlebot muss für den Pfad zugelassen sein.",
        )
    if rule_id == "INDEX_NOINDEX":
        critical = any(finding.severity == "critical" for finding in findings)
        if critical:
            return (
                f"noindex-Sperre auf {primary} entfernen",
                "Wirksames noindex im Robots-Meta-Tag oder X-Robots-Tag entfernen.",
                "Die unbeabsichtigte Indexierungssperre entfällt.",
                "URL abrufen und HTTP-Header sowie HTML auf noindex prüfen.",
            )
        return (
            f"noindex auf {primary} prüfen",
            "Prüfen, ob das noindex beabsichtigt ist. Falls die Seite indexiert werden soll, "
            "wirksames noindex im Robots-Meta-Tag oder X-Robots-Tag entfernen.",
            "Unbeabsichtigte Indexierungssperren werden vermieden; beabsichtigte Ausschlüsse "
            "bleiben dokumentiert.",
            "URL abrufen und HTTP-Header sowie HTML auf noindex prüfen.",
        )
    if rule_id == "CANONICAL_TARGET":
        return (
            f"Canonical-Angabe für {primary} korrigieren",
            "Canonical auf die selbst kanonische URL ausrichten oder das angegebene Ziel erreichbar und indexierbar machen.",
            "Eindeutige Kanonisierung ohne widersprüchliche Signale.",
            "HTML und HTTP-Header auf genau ein erreichbares Canonical prüfen.",
        )
    if rule_id == "SITEMAP_TARGET":
        return (
            f"Sitemap-Eintrag für {primary} korrigieren",
            "Eintrag entfernen oder die Ziel-URL auf einen direkt erreichbaren, indexierbaren 200-Status bringen.",
            "Die Sitemap nennt nur abrufbare, indexierbare URLs.",
            "Sitemap erneut einlesen und die Ziel-URL abrufen.",
        )
    if rule_id == "LINK_ORPHAN_CANDIDATE":
        return (
            f"Verwaiste Seite {primary} intern verlinken",
            "Von einer thematisch passenden, bereits verlinkten Seite auf diese URL verlinken.",
            "Die Seite ist über den Linkgraphen erreichbar und wird zuverlässiger entdeckt.",
            "Erneut crawlen; mindestens ein eingehender interner Link muss beobachtet werden.",
        )
    if rule_id == "LINK_DEPTH":
        return (
            f"Klicktiefe von {primary} reduzieren",
            "Direkten internen Link von einer Seite mit geringerer Klicktiefe ergänzen.",
            "Wichtige Seite ist mit weniger Klicks erreichbar.",
            "Linkgraphen erneut auswerten; Klicktiefe muss innerhalb der Grenze liegen.",
        )
    if rule_id == "META_TITLE":
        if fix_kind == "duplicate_title":
            count = len({url_id for finding in findings for url_id, _ in finding.urls})
            return (
                f"Doppelte Titel auf {count} Seiten unterscheiden",
                "Titel der betroffenen Seiten an Inhalt und Suchintention anpassen.",
                "Seiten sind in Suchergebnissen unterscheidbar.",
                "Titel normalisiert vergleichen; keine identischen Werte mehr.",
            )
        return (
            f"Titel für {primary} ergänzen",
            "Eindeutigen, beschreibenden Title-Tag ergänzen.",
            "Suchtreffer können einen passenden Titel anzeigen.",
            "HTML erneut prüfen; Title-Tag ist vorhanden und nicht leer.",
        )
    if rule_id == "META_DESCRIPTION":
        if fix_kind == "duplicate_description":
            count = len({url_id for finding in findings for url_id, _ in finding.urls})
            return (
                f"Doppelte Meta-Beschreibungen auf {count} Seiten unterscheiden",
                "Beschreibungen der betroffenen Seiten an Inhalt und Suchintention anpassen.",
                "Suchergebnisse lassen sich je Seite gezielter darstellen.",
                "Meta-Beschreibungen normalisiert vergleichen; keine identischen Werte mehr.",
            )
        return (
            f"Meta-Beschreibung für {primary} ergänzen",
            "Kurze, inhaltlich passende Meta-Beschreibung ergänzen.",
            "Der Suchtreffer lässt sich gezielter beschreiben.",
            "HTML erneut prüfen; Meta-Description ist vorhanden und nicht leer.",
        )
    if rule_id == "GSC_NEAR_TOP":
        query = facts.get("query")
        label = (
            f"»{truncate(query, 80)}« auf {primary}"
            if query
            else primary
        )
        return (
            f"GSC-Chance für {label} prüfen",
            "Suchintention, Snippet und interne Verlinkung prüfen; bei Bedarf Inhalt sowie Title und Meta-Beschreibung verbessern.",
            "Bessere Ausgangslage für Rankings in der Nähe der Top-Ergebnisse.",
            "Im nächsten GSC-Zeitraum Position, Impressionen und Klicks derselben Zeile vergleichen.",
        )
    if rule_id == "GSC_DECLINE":
        query = facts.get("query")
        label = (
            f"»{truncate(query, 80)}« auf {primary}"
            if query
            else primary
        )
        return (
            f"Klickrückgang für {label} analysieren",
            "Ursache im Zeitraum prüfen (Snippet, Wettbewerb, Saisonalität, technische Änderungen) und passende Inhalte aktualisieren.",
            "Der Rückgang wird eingeordnet und lässt sich gezielt adressieren.",
            "Klicks und Impressionen im Folgezeitraum mit gleichem Segment vergleichen.",
        )
    if rule_id == "GSC_CTR_REVIEW":
        query = facts.get("query") or ""
        return (
            f"CTR für Suchanfrage »{truncate(query, 80)}« verbessern",
            "Title und Meta-Beschreibung auf Suchintention und Snippet abstimmen.",
            "Bessere Klickrate bei vergleichbarer Position.",
            "CTR derselben URL-Suchanfrage im nächsten Zeitraum prüfen.",
        )
    if rule_id == "GSC_MULTI_URL":
        query = facts.get("query") or ""
        dominant = facts.get("dominant_url")
        gap = facts.get("position_gap")
        details = []
        if dominant:
            details.append(f"dominante URL: {_display(data, str(dominant))}")
        if isinstance(gap, (int, float)):
            details.append(f"Positionsabstand: {gap:.1f}")
        detail_text = f" ({'; '.join(details)})" if details else ""
        return (
            f"Mehrfach-URLs für »{truncate(query, 80)}« beobachten",
            "Dominante URL und Positionsdifferenz beobachten. Keine Konsolidierung "
            "allein aufgrund eines Zeitraums; erst bei wiederholter, wechselnder "
            f"führender URL und gleicher Suchintention eingreifen{detail_text}.",
            "Beobachtung statt vorschneller Konsolidierung.",
            "Im nächsten GSC-Zeitraum prüfen, ob dieselbe URL führt und ob die "
            "Positionsdifferenz bleibt.",
        )
    return (
        f"Befund {rule_id} auf {primary} prüfen",
        "Befund prüfen und die vorgeschlagene Korrektur umsetzen.",
        "Der Befund wird behoben.",
        "Betroffene URL erneut prüfen.",
    )


def build_actions(data: RunData, results: list[RuleResult]) -> list[ActionDraft]:
    groups = _bundle_query_findings(data, _group_findings(results))
    cause_counts = _cause_counts(results)
    drafts: list[ActionDraft] = []
    for (rule_id, fix_kind, group_key), findings in groups.items():
        infos = _affected_infos(data, findings)
        business_value = (
            min((info.business_value for info in infos), key=lambda value: BUSINESS_RANK[value])
            if infos
            else "normal"
        )
        confidence = min(
            (finding.confidence or "hint" for finding in findings),
            key=lambda value: CONFIDENCE_RANK[value],
        )
        priority = _priority(
            rule_id,
            fix_kind,
            findings,
            infos,
            len(cause_counts.get((rule_id, fix_kind), set())),
        )
        effort = EFFORT.get(rule_id, "unknown")
        title, fix, effect, verification = _texts(data, rule_id, fix_kind, findings, infos)
        action_key = f"{rule_id}|{fix_kind}|{group_key}"
        drafts.append(
            ActionDraft(
                action_key=action_key,
                priority=priority,
                effort=effort,
                title=title,
                proposed_fix=fix,
                expected_effect=effect,
                verification=verification,
                findings=list(findings),
                urls=_distinct_url_ids(findings),
                business_value=business_value,
                confidence=confidence,
                confidence_rank=CONFIDENCE_RANK[confidence],
                reach=len(_distinct_url_ids(findings)),
            )
        )
    drafts.sort(
        key=lambda draft: (
            draft.priority,
            draft.confidence_rank,
            BUSINESS_RANK[draft.business_value],
            -draft.reach,
            EFFORT_RANK.get(draft.effort, 3),
            draft.action_key,
        )
    )
    return drafts


def quick_wins(actions: list[ActionDraft], limit: int = 5) -> list[ActionDraft]:
    return [
        action
        for action in actions
        if action.priority == 2
        and action.effort == "small"
        and action.confidence == "confirmed"
    ][:limit]


def persist_actions(
    connection: sqlite3.Connection, run_id: str, actions: list[ActionDraft]
) -> None:
    for action in actions:
        connection.execute(
            "INSERT INTO actions(run_id, action_key, priority, effort, title, "
            "proposed_fix, expected_effect, verification) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                action.action_key,
                action.priority,
                action.effort,
                action.title,
                action.proposed_fix,
                action.expected_effect,
                action.verification,
            ),
        )
        for finding in action.findings:
            connection.execute(
                "INSERT OR IGNORE INTO action_findings(run_id, action_key, rule_id, "
                "subject_key) VALUES (?, ?, ?, ?)",
                (run_id, action.action_key, finding.rule_id, finding.subject_key),
            )