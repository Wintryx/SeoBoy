"""Search Console rules: opportunities, trends, CTR, and multiple URLs."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import urlsplit

from seoboy.analysis.audit_data import RunData
from seoboy.gsc.importer import select_comparison_periods
from seoboy.analysis.rules import Evidence, RuleResult, _rule
from seoboy.shared.urls import key_for_gsc
from seoboy.shared.util import stable_json

GSC_RULES = (
    "GSC_NEAR_TOP",
    "GSC_DECLINE",
    "GSC_CTR_REVIEW",
    "GSC_MULTI_URL",
)
TOKEN_RE = re.compile(r"[a-z0-9äöüß]+")


def _brand_terms(data: RunData) -> frozenset[str]:
    host = (urlsplit(data.config.start_url).hostname or "").casefold()
    return frozenset(part for part in re.split(r"[.\-]", host) if part)


def _is_brand_query(query: str, brands: frozenset[str]) -> bool:
    tokens = set(TOKEN_RE.findall(query.casefold()))
    meaningful = {
        value for value in brands if len(value) >= 3 and value not in {"www", "com", "de"}
    }
    return bool(meaningful) and meaningful.issubset(tokens)


@dataclass(frozen=True)
class Metric:
    url_id: int
    url: str
    query: str
    source_page: str
    clicks: int
    impressions: int
    position: float | None

    @property
    def ctr(self) -> float | None:
        if self.impressions <= 0:
            return None
        return self.clicks / self.impressions


def _segment(dataset: dict[str, Any]) -> str:
    return "|".join(
        [
            dataset["property"],
            dataset["search_type"],
            dataset["country"] or "*",
            dataset["device"] or "*",
        ]
    )


def _import_time(data: RunData) -> dict[int, str]:
    return {
        int(item["import_id"]): item["captured_at"] for item in data.source_imports
    }


def _evidence(
    data: RunData, dataset: dict[str, Any], facts: dict[str, Any]
) -> Evidence:
    captured = _import_time(data).get(int(dataset["import_id"]), data.run["started_at"])
    return Evidence(
        source_kind="import",
        observed_at=captured,
        import_id=int(dataset["import_id"]),
        facts=facts,
    )


def _metrics(data: RunData, dataset: dict[str, Any]) -> list[Metric]:
    result: list[Metric] = []
    for row in data.metrics.get(int(dataset["dataset_id"]), []):
        if row["mapping_status"] != "matched" or row["url_id"] is None:
            continue
        position = row["position"]
        result.append(
            Metric(
                url_id=int(row["url_id"]),
                url=data.url_string(int(row["url_id"])),
                query=row["query"] or "",
                source_page=row["source_page"],
                clicks=int(row["clicks"]),
                impressions=int(row["impressions"]),
                position=None if position is None else float(position),
            )
        )
    return result


def _metric_key(dataset: dict[str, Any], metric: Metric) -> tuple:
    if dataset["grain"] == "page":
        return (metric.url_id,)
    return (metric.url_id, metric.query)


def _subject(
    dataset: dict[str, Any],
    metric: Metric | None = None,
    *,
    query: str | None = None,
    url: str | None = None,
) -> str:
    common = [
        dataset["property"],
        dataset["search_type"],
        dataset["country"] or "",
        dataset["device"] or "",
    ]
    if query is not None:
        return stable_json(["gsc", *common, "query", query])
    if metric is None:
        return stable_json(["gsc", *common, "url", url or ""])
    if dataset["grain"] == "page":
        return stable_json(["gsc", *common, "page", metric.url])
    return stable_json(["gsc", *common, "page_query", metric.url, metric.query])


def _scope(dataset: dict[str, Any]) -> str:
    return _segment(dataset)


def _facts(
    dataset: dict[str, Any],
    metric: Metric,
    *,
    summary: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "summary": summary,
        "dataset_id": int(dataset["dataset_id"]),
        "import_id": int(dataset["import_id"]),
        "row_key": [int(dataset["dataset_id"]), metric.url_id, metric.query],
        "source_page": metric.source_page,
        "property": dataset["property"],
        "search_type": dataset["search_type"],
        "country": dataset["country"] or None,
        "device": dataset["device"] or None,
        "grain": dataset["grain"],
        "period_start": dataset["period_start"],
        "period_end": dataset["period_end"],
        "page": metric.url,
        "query": metric.query or None,
        "clicks": metric.clicks,
        "impressions": metric.impressions,
        "position": metric.position,
        "ctr": metric.ctr,
    }
    if extra:
        facts.update(extra)
    return facts


def _empty_site_result(rule_id: str, reason: str, facts: dict[str, Any]) -> RuleResult:
    return _rule(
        rule_id,
        stable_json(["site", "gsc", rule_id]),
        "site",
        "",
        "gsc",
        "not_checked",
        reason_code=reason,
        evidence=[Evidence(source_kind="crawl", observed_at="", facts=facts)],
    )


def _segment_unchecked(
    rule_id: str, dataset: dict[str, Any], reason: str, facts: dict[str, Any]
) -> RuleResult:
    return _rule(
        rule_id,
        stable_json(["segment", "gsc", rule_id, _segment(dataset), dataset["grain"]]),
        "site",
        dataset["grain"],
        _scope(dataset),
        "not_checked",
        reason_code=reason,
        evidence=[
            Evidence(
                source_kind="import",
                observed_at=f"{dataset['period_end']}T00:00:00Z",
                import_id=int(dataset["import_id"]),
                facts=facts,
            )
        ],
    )


def evaluate_gsc(data: RunData) -> list[RuleResult]:
    results: list[RuleResult] = []
    if not data.datasets:
        statuses = [
            {"provider": item["provider"], "status": item["status"], "module": item["module"]}
            for item in data.source_imports
        ]
        for rule_id in GSC_RULES:
            result = _empty_site_result(
                rule_id,
                "missing_gsc_data",
                {"summary": "Kein GSC-Import vorhanden", "imports": statuses},
            )
            result.evidence[0].observed_at = data.run["started_at"]
            results.append(result)
        return results

    # Segments by property, search type, country, and device
    segments: dict[str, list[dict[str, Any]]] = {}
    for dataset in data.datasets:
        segments.setdefault(
            "|".join(
                [
                    dataset["property"],
                    dataset["search_type"],
                    dataset["country"] or "",
                    dataset["device"] or "",
                ]
            ),
            [],
        ).append(dataset)

    page_query_datasets = [
        dataset for dataset in data.datasets if dataset["grain"] == "page_query"
    ]
    if not page_query_datasets:
        for rule_id in ("GSC_CTR_REVIEW", "GSC_MULTI_URL"):
            results.append(
                _empty_site_result(
                    rule_id,
                    "missing_gsc_data",
                    {
                        "summary": "Kein GSC-Datensatz mit URL-Suchanfrage-Granularität vorhanden",
                        "required_grain": "page_query",
                    },
                )
            )
            results[-1].evidence[0].observed_at = data.run["started_at"]

    for segment_key, datasets in segments.items():
        for grain in ("page", "page_query"):
            grain_datasets = [item for item in datasets if item["grain"] == grain]
            if not grain_datasets:
                continue
            latest, previous = select_comparison_periods(grain_datasets)
            if latest is None:
                continue
            results.extend(
                _near_top(data, latest, segment_key)
            )
            if previous is None:
                for rule_id in ("GSC_DECLINE",):
                    results.append(
                        _segment_unchecked(
                            rule_id,
                            latest,
                            "missing_comparison_period",
                            {
                                "summary": "Kein vergleichbarer Vorzeitraum vorhanden",
                                "period": [latest["period_start"], latest["period_end"]],
                            },
                        )
                    )
                if grain == "page_query":
                    results.append(
                        _segment_unchecked(
                            "GSC_CTR_REVIEW",
                            latest,
                            "missing_comparison_period",
                            {
                                "summary": "Kein vergleichbarer Vorzeitraum vorhanden",
                                "period": [latest["period_start"], latest["period_end"]],
                            },
                        )
                    )
            else:
                results.extend(_decline(data, latest, previous, segment_key))
                if grain == "page_query":
                    results.extend(_ctr_review(data, latest, previous, segment_key))
            if grain == "page_query":
                results.extend(_multi_url(data, latest, segment_key))
    return results


# ---------------------------------------------------------------------- GSC_NEAR_TOP


def _near_top(data: RunData, latest: dict[str, Any], segment_key: str) -> list[RuleResult]:
    results: list[RuleResult] = []
    metrics = _metrics(data, latest)
    thresholds = data.config.gsc
    if not metrics:
        results.append(
            _segment_unchecked(
                "GSC_NEAR_TOP",
                latest,
                "missing_gsc_data",
                {
                    "summary": "Keine zugeordneten GSC-Zeilen",
                    "period": [latest["period_start"], latest["period_end"]],
                },
            )
        )
        return results
    for metric in metrics:
        subject = _subject(latest, metric)
        relations = [(metric.url_id, "affected")]
        if metric.position is None:
            results.append(
                _rule(
                    "GSC_NEAR_TOP", subject,
                    "url" if latest["grain"] == "page" else "query",
                    latest["grain"], _scope(latest), "not_checked",
                    reason_code="missing_position", urls=relations,
                    evidence=[
                        _evidence(data, latest, _facts(
                            latest, metric,
                            summary="Mittlere Position fehlt im Import",
                        ))
                    ],
                )
            )
            continue
        facts = _facts(
            latest, metric,
            summary=(
                f"{metric.impressions} Impressionen, Position {metric.position:.1f}"
            ),
            extra={
                "min_impressions": thresholds.near_top_min_impressions,
                "position_range": [
                    thresholds.near_top_position_min,
                    thresholds.near_top_position_max,
                ],
            },
        )
        if (
            metric.impressions >= thresholds.near_top_min_impressions
            and thresholds.near_top_position_min
            <= metric.position
            <= thresholds.near_top_position_max
        ):
            results.append(
                _rule(
                    "GSC_NEAR_TOP", subject,
                    "url" if latest["grain"] == "page" else "query",
                    latest["grain"], _scope(latest), "finding",
                    severity="medium", confidence="confirmed",
                    urls=relations,
                    evidence=[_evidence(data, latest, facts)],
                    fix_kind="gsc_near_top", group_key=subject,
                )
            )
        else:
            results.append(
                _rule(
                    "GSC_NEAR_TOP", subject,
                    "url" if latest["grain"] == "page" else "query",
                    latest["grain"], _scope(latest), "pass",
                    urls=relations,
                    evidence=[_evidence(data, latest, facts)],
                )
            )
    return results


# ---------------------------------------------------------------------- GSC_DECLINE


def _decline(
    data: RunData,
    latest: dict[str, Any],
    previous: dict[str, Any],
    segment_key: str,
) -> list[RuleResult]:
    results: list[RuleResult] = []
    thresholds = data.config.gsc
    missing_rows = 0
    current = {_metric_key(latest, metric): metric for metric in _metrics(data, latest)}
    before = {_metric_key(previous, metric): metric for metric in _metrics(data, previous)}
    if not before:
        results.append(
            _segment_unchecked(
                "GSC_DECLINE",
                latest,
                "missing_gsc_data",
                {"summary": "Vorzeitraum enthält keine zugeordneten Zeilen"},
            )
        )
        return results
    for key, previous_metric in before.items():
        latest_metric = current.get(key)
        subject = _subject(latest, previous_metric)
        relations = [(previous_metric.url_id, "affected")]
        if latest_metric is None:
            missing_rows += 1
            continue
        decline = previous_metric.clicks - latest_metric.clicks
        ratio = decline / previous_metric.clicks if previous_metric.clicks else 0.0
        if decline > 0:
            change = f"−{decline}, {ratio * 100:.0f} %"
        elif decline < 0:
            change = f"+{-decline}"
        else:
            change = "unverändert"
        facts = _facts(
            latest, latest_metric,
            summary=(
                f"Klicks {previous_metric.clicks} → {latest_metric.clicks} ({change})"
            ),
            extra={
                "previous": {
                    "period_start": previous["period_start"],
                    "period_end": previous["period_end"],
                    "clicks": previous_metric.clicks,
                    "impressions": previous_metric.impressions,
                    "position": previous_metric.position,
                },
                "thresholds": {
                    "min_previous_clicks": thresholds.decline_min_previous_clicks,
                    "min_clicks": thresholds.decline_min_clicks,
                    "min_ratio": thresholds.decline_min_ratio,
                },
                "impressions_change": latest_metric.impressions - previous_metric.impressions,
            },
        )
        if (
            previous_metric.clicks >= thresholds.decline_min_previous_clicks
            and decline >= thresholds.decline_min_clicks
            and ratio >= thresholds.decline_min_ratio
        ):
            results.append(
                _rule(
                    "GSC_DECLINE", subject,
                    "url" if latest["grain"] == "page" else "query",
                    latest["grain"], _scope(latest), "finding",
                    severity="medium", confidence="confirmed",
                    urls=[(latest_metric.url_id, "affected")],
                    evidence=[
                        _evidence(data, latest, facts),
                        _evidence(data, previous, _facts(previous, previous_metric, summary="Vorzeitraum")),
                    ],
                    fix_kind="gsc_decline", group_key=subject,
                )
            )
        else:
            results.append(
                _rule(
                    "GSC_DECLINE", subject,
                    "url" if latest["grain"] == "page" else "query",
                    latest["grain"], _scope(latest), "pass",
                    urls=[(latest_metric.url_id, "affected")],
                    evidence=[_evidence(data, latest, facts)],
                )
            )
    if missing_rows:
        results.append(
            _segment_unchecked(
                "GSC_DECLINE",
                latest,
                "missing_comparison_row",
                {
                    "summary": (
                        f"{missing_rows} Vergleichszeile(n) fehlen im aktuellen Zeitraum"
                    ),
                    "missing_rows": missing_rows,
                },
            )
        )
    for key, metric in current.items():
        if key in before:
            continue
        subject = _subject(latest, metric)
        results.append(
            _rule(
                "GSC_DECLINE", subject,
                "url" if latest["grain"] == "page" else "query",
                latest["grain"], _scope(latest), "pass",
                urls=[(metric.url_id, "affected")],
                evidence=[
                    _evidence(data, latest, _facts(
                        latest, metric,
                        summary="Neue Zeile ohne Vorjahreswert",
                    ))
                ],
            )
        )
    return results


# ---------------------------------------------------------------------- GSC_CTR_REVIEW


def _ctr_review(
    data: RunData,
    latest: dict[str, Any],
    previous: dict[str, Any],
    segment_key: str,
) -> list[RuleResult]:
    results: list[RuleResult] = []
    thresholds = data.config.gsc
    missing_rows = 0
    current = {_metric_key(latest, metric): metric for metric in _metrics(data, latest)}
    before = {_metric_key(previous, metric): metric for metric in _metrics(data, previous)}
    if not before:
        results.append(
            _segment_unchecked(
                "GSC_CTR_REVIEW",
                latest,
                "missing_gsc_data",
                {"summary": "Vorzeitraum enthält keine zugeordneten Zeilen"},
            )
        )
        return results
    for key, previous_metric in before.items():
        latest_metric = current.get(key)
        subject = _subject(latest, previous_metric)
        relations = [(previous_metric.url_id, "affected")]
        if latest_metric is None:
            missing_rows += 1
            continue
        if (
            previous_metric.position is None
            or latest_metric.position is None
        ):
            results.append(
                _rule(
                    "GSC_CTR_REVIEW", subject, "query", latest["grain"],
                    _scope(latest), "not_checked",
                    reason_code="missing_position", urls=relations,
                    evidence=[
                        _evidence(data, latest, {
                            "summary": "Mittlere Position fehlt für den CTR-Vergleich",
                        })
                    ],
                )
            )
            continue
        previous_ctr = previous_metric.ctr
        latest_ctr = latest_metric.ctr
        if previous_ctr is None or latest_ctr is None:
            results.append(
                _rule(
                    "GSC_CTR_REVIEW", subject, "query", latest["grain"],
                    _scope(latest), "not_checked",
                    reason_code="missing_gsc_data", urls=relations,
                    evidence=[
                        _evidence(data, latest, {
                            "summary": "CTR ohne Impressionen nicht berechenbar",
                        })
                    ],
                )
            )
            continue
        position_delta = abs(latest_metric.position - previous_metric.position)
        ctr_drop = previous_ctr - latest_ctr
        facts = _facts(
            latest, latest_metric,
            summary=(
                f"CTR {previous_ctr * 100:.1f} % → {latest_ctr * 100:.1f} % "
                f"bei Positionsänderung {position_delta:.1f}"
            ),
            extra={
                "previous": {
                    "clicks": previous_metric.clicks,
                    "impressions": previous_metric.impressions,
                    "ctr": previous_ctr,
                    "position": previous_metric.position,
                },
                "ctr_drop": ctr_drop,
                "position_delta": position_delta,
                "thresholds": {
                    "min_impressions": thresholds.ctr_min_impressions,
                    "min_drop": thresholds.ctr_min_drop,
                    "max_position_delta": thresholds.ctr_max_position_delta,
                },
            },
        )
        if (
            previous_metric.impressions >= thresholds.ctr_min_impressions
            and latest_metric.impressions >= thresholds.ctr_min_impressions
            and ctr_drop >= thresholds.ctr_min_drop
            and position_delta <= thresholds.ctr_max_position_delta
        ):
            results.append(
                _rule(
                    "GSC_CTR_REVIEW", subject, "query", latest["grain"],
                    _scope(latest), "finding",
                    severity="medium", confidence="confirmed",
                    urls=[(latest_metric.url_id, "affected")],
                    evidence=[
                        _evidence(data, latest, facts),
                        _evidence(data, previous, _facts(previous, previous_metric, summary="Vorzeitraum")),
                    ],
                    fix_kind="gsc_ctr", group_key=subject,
                )
            )
        else:
            results.append(
                _rule(
                    "GSC_CTR_REVIEW", subject, "query", latest["grain"],
                    _scope(latest), "pass",
                    urls=[(latest_metric.url_id, "affected")],
                    evidence=[_evidence(data, latest, facts)],
                )
            )
    if missing_rows:
        results.append(
            _segment_unchecked(
                "GSC_CTR_REVIEW",
                latest,
                "missing_comparison_row",
                {
                    "summary": (
                        f"{missing_rows} Vergleichszeile(n) fehlen im aktuellen Zeitraum"
                    ),
                    "missing_rows": missing_rows,
                },
            )
        )
    return results


# ---------------------------------------------------------------------- GSC_MULTI_URL


def _multi_url(
    data: RunData, latest: dict[str, Any], segment_key: str
) -> list[RuleResult]:
    results: list[RuleResult] = []
    thresholds = data.config.gsc
    brands = _brand_terms(data)
    by_query: dict[str, list[Metric]] = {}
    had_query_rows = False
    for metric in _metrics(data, latest):
        if not metric.query:
            continue
        had_query_rows = True
        if not _is_brand_query(metric.query, brands):
            by_query.setdefault(metric.query, []).append(metric)
    if not by_query:
        if not had_query_rows:
            results.append(
                _segment_unchecked(
                    "GSC_MULTI_URL",
                    latest,
                    "missing_gsc_data",
                    {"summary": "Keine zugeordneten URL-Suchanfrage-Zeilen"},
                )
            )
        return results
    for query, metrics in sorted(by_query.items()):
        significant = [
            metric for metric in metrics if metric.impressions >= thresholds.multi_url_min_impressions
        ]
        significant.sort(key=lambda metric: (-metric.impressions, metric.position or 999))
        positions = [
            metric.position for metric in significant if metric.position is not None
        ]
        dominant = significant[0] if significant else None
        subject = _subject(latest, query=query)
        facts = {
            "summary": (
                f"{len(significant)} URL(s) mit mindestens "
                f"{thresholds.multi_url_min_impressions} Impressionen für dieselbe Suchanfrage"
            ),
            "query": query,
            "grain": latest["grain"],
            "period_start": latest["period_start"],
            "period_end": latest["period_end"],
            "dominant_url": dominant.url if dominant is not None else None,
            "dominant_position": dominant.position if dominant is not None else None,
            "position_gap": (
                max(positions) - min(positions) if len(positions) >= 2 else None
            ),
            "urls": [
                {
                    "url": metric.url,
                    "clicks": metric.clicks,
                    "impressions": metric.impressions,
                    "position": metric.position,
                }
                for metric in significant
            ],
            "thresholds": {
                "min_impressions": thresholds.multi_url_min_impressions,
                "min_urls": thresholds.multi_url_min_urls,
            },
        }
        relations = [(metric.url_id, "affected") for metric in significant]
        if len(significant) >= thresholds.multi_url_min_urls:
            results.append(
                _rule(
                    "GSC_MULTI_URL", subject, "query", latest["grain"],
                    _scope(latest), "finding",
                    severity="medium", confidence="plausible",
                    urls=relations,
                    evidence=[_evidence(data, latest, facts)],
                    fix_kind="gsc_multi_url", group_key=subject,
                )
            )
        else:
            results.append(
                _rule(
                    "GSC_MULTI_URL", subject, "query", latest["grain"],
                    _scope(latest), "pass",
                    urls=relations,
                    evidence=[_evidence(data, latest, facts)],
                )
            )
    return results