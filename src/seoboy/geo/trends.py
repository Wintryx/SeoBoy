"""Time series over existing local GEO sampling reports."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from seoboy.infrastructure.config import ProjectConfig
from seoboy.shared.util import excel_safe


@dataclass(frozen=True)
class GeoObservation:
    run_key: str
    prompt_id: str
    query: str
    observed_at: str
    provider: str
    model: str
    platform: str
    web_search_mode: str
    prompt_version: str
    language: str
    region: str
    status: str
    brand_mentions: int
    own_citations: int
    competitor_mentions: int
    error: str
    cost_usd: float | None


def _number(value: str) -> int:
    try:
        return int(float(value or "0"))
    except ValueError:
        return 0


def _cost(value: str) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _observations(folder: Path) -> list[GeoObservation]:
    manifest_path = folder / "manifest.json"
    csv_path = folder / "raw_data" / "geo_samples.csv"
    if not manifest_path.is_file() or not csv_path.is_file():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        with csv_path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except (OSError, ValueError):
        return []
    provider = str(manifest.get("provider") or "unbekannt")
    model = str(manifest.get("model") or "unbekannt")
    language = str(manifest.get("language") or "")
    region = str(manifest.get("region") or "")
    prompt_version = str(manifest.get("prompt_set") or "")
    web_search = str(manifest.get("web_search_mode") or "unbekannt")
    result: list[GeoObservation] = []
    for row in rows:
        prompt_id = (row.get("prompt_id") or "").strip()
        if not prompt_id:
            continue
        error = (row.get("error") or "").strip()
        result.append(
            GeoObservation(
                run_key=folder.name,
                prompt_id=prompt_id,
                query=(row.get("query") or "").strip(),
                observed_at=(row.get("sampled_at") or "").strip(),
                provider=provider,
                model=model,
                platform=provider,
                web_search_mode=web_search,
                prompt_version=prompt_version,
                language=(row.get("language") or language).strip(),
                region=(row.get("region") or region).strip(),
                status="failed" if error else "successful",
                brand_mentions=_number(row.get("brand_mentions") or "0"),
                own_citations=_number(row.get("own_citations") or "0"),
                competitor_mentions=_number(row.get("competitor_mentions") or "0"),
                error=error,
                cost_usd=_cost(row.get("cost_usd") or ""),
            )
        )
    return result


def _discover(config: ProjectConfig, paths: list[Path]) -> list[GeoObservation]:
    roots = paths or [config.reports_dir]
    observations: list[GeoObservation] = []
    for root in roots:
        if root.is_file():
            observations.extend(_observations(root))
            continue
        if not root.is_dir():
            continue
        for folder in sorted(root.iterdir()):
            if folder.is_dir():
                observations.extend(_observations(folder))
    return sorted(observations, key=lambda item: (item.observed_at, item.prompt_id))


def _rate(count: int, total: int) -> str:
    return f"{count} / {total}" if total else "0 / 0"


def _write_csv(path: Path, observations: list[GeoObservation]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(
            [
                "run_key",
                "prompt_id",
                "query",
                "observed_at",
                "platform",
                "provider",
                "model",
                "web_search_mode",
                "prompt_version",
                "language",
                "region",
                "status",
                "brand_mentions",
                "own_citations",
                "competitor_mentions",
                "error",
                "cost_usd",
            ]
        )
        for item in observations:
            writer.writerow(
                [
                    excel_safe(item.run_key),
                    excel_safe(item.prompt_id),
                    excel_safe(item.query),
                    item.observed_at,
                    item.platform,
                    item.provider,
                    item.model,
                    item.web_search_mode,
                    item.prompt_version,
                    item.language,
                    item.region,
                    item.status,
                    item.brand_mentions,
                    item.own_citations,
                    item.competitor_mentions,
                    excel_safe(item.error),
                    "" if item.cost_usd is None else item.cost_usd,
                ]
            )


def write_geo_trends(
    config: ProjectConfig,
    paths: list[Path] | None = None,
    out: Path | None = None,
) -> Path:
    observations = _discover(config, paths or [])
    folder = out or (config.reports_dir / "geo-trends")
    folder.mkdir(parents=True, exist_ok=True)
    successful = [item for item in observations if item.status == "successful"]
    failed = len(observations) - len(successful)
    mentions = sum(1 for item in successful if item.brand_mentions > 0)
    citations = sum(1 for item in successful if item.own_citations > 0)
    competitors = sum(1 for item in successful if item.competitor_mentions > 0)

    by_prompt: dict[str, list[GeoObservation]] = {}
    for item in observations:
        by_prompt.setdefault(item.prompt_id, []).append(item)
    changes: list[str] = []
    rows: list[str] = []
    for prompt_id, items in sorted(by_prompt.items()):
        items.sort(key=lambda item: item.observed_at)
        latest = items[-1]
        previous = items[-2] if len(items) >= 2 else None
        method_changed = bool(
            previous
            and (
                previous.model != latest.model
                or previous.web_search_mode != latest.web_search_mode
                or previous.prompt_version != latest.prompt_version
            )
        )
        if method_changed:
            changes.append(
                f"- **{prompt_id}**: Methodenwechsel zwischen {previous.observed_at} "
                f"({previous.model}, {previous.web_search_mode}, "
                f"{previous.prompt_version or 'Version unbekannt'}) und "
                f"{latest.observed_at} ({latest.model}, {latest.web_search_mode}, "
                f"{latest.prompt_version or 'Version unbekannt'})."
            )
        delta = ""
        if previous and previous.status == "successful" and latest.status == "successful":
            delta = (
                f"{latest.brand_mentions - previous.brand_mentions:+d} / "
                f"{latest.own_citations - previous.own_citations:+d} / "
                f"{latest.competitor_mentions - previous.competitor_mentions:+d}"
            )
        rows.append(
            f"| {prompt_id} | {latest.observed_at} | {latest.model} | "
            f"{latest.web_search_mode} | {latest.status} | {latest.brand_mentions} | "
            f"{latest.own_citations} | {latest.competitor_mentions} | {delta or '–'} |"
        )

    lines = [
        "# SeoBoy – KI-Sichtbarkeit im Zeitverlauf",
        "",
        f"**Projekt:** {config.project_id}  ",
        f"**Beobachtungen:** {len(observations)} · **erfolgreich:** {len(successful)} · "
        f"**fehlgeschlagen:** {failed}",
        "",
        "## Kennzahlen",
        "",
        "| Merkmal | Erfolgreiche Antworten |",
        "| --- | --- |",
        f"| Marke genannt | {_rate(mentions, len(successful))} |",
        f"| eigene URL zitiert | {_rate(citations, len(successful))} |",
        f"| Wettbewerber genannt | {_rate(competitors, len(successful))} |",
        "",
        "Die Nenner zählen ausschließlich erfolgreiche Antworten. Fehlgeschlagene "
        "oder abgebrochene Antworten erscheinen separat.",
        "",
        "## Letzte Beobachtung je Prompt",
        "",
        "| Prompt | Zeitpunkt | Modell | Websuche | Status | Marke | Zitat | Wettbewerber | Δ |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        *(rows or ["| – | – | – | – | Keine GEO-Beobachtungen gefunden. | – | – | – | – |"]),
        "",
        "## Methodenwechsel",
        "",
        *(changes or ["Keine Methodenwechsel innerhalb derselben Prompt-ID gefunden."]),
        "",
        "## Grenzen",
        "",
        "- Ältere Manifeste ohne Prompt-Version oder Websucheinstellung gelten als eingeschränkt vergleichbar.",
        "- Eine API-Stichprobe ist keine Aussage über ChatGPT, Gemini, Perplexity oder AI Overviews.",
        "- Eine bloße Namensnennung ist keine bestätigte Empfehlung.",
        "- Rohantworten bleiben in der bestehenden lokalen Ablage.",
        "",
    ]
    (folder / "GEO_TRENDS.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )
    _write_csv(folder / "raw_data" / "geo_observations.csv", observations)
    return folder
