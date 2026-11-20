"""Budgeted GEO answer sampling via the DeepSeek chat API."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
import urllib.request

import yaml

from seoboy.shared.util import excel_safe, iso_utc

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_BRANDS = ("AW Audio", "aw-audio.de", "Arne Winter")
DEFAULT_COMPETITORS = ("djmagic", "beats-per-micha", "topeventtechnik")
DEFAULT_PROMPTS = (
    {
        "id": "hochzeit-dj-koeln",
        "prompt": "Welche DJs für Hochzeiten in Köln sind empfehlenswert? Nenne konkrete Anbieter und begründe kurz.",
        "intent": "commercial",
    },
    {
        "id": "hochzeit-dj-kosten",
        "prompt": "Was kostet ein guter DJ für eine Hochzeit in NRW? Nenne eine realistische Preisspanne und die wichtigsten Leistungen.",
        "intent": "commercial",
    },
    {
        "id": "firmenevent-dj-koeln",
        "prompt": "Wir suchen einen DJ für ein Firmenevent in Köln. Worauf sollten wir bei Auswahl und Technik achten?",
        "intent": "commercial",
    },
    {
        "id": "hochzeit-dj-bergisches-land",
        "prompt": "Welche DJs und Locations eignen sich für eine Hochzeit im Bergischen Land? Nenne Beispiele.",
        "intent": "local",
    },
    {
        "id": "dj-mit-pa-und-licht",
        "prompt": "Welche Anbieter mieten DJ, PA-Anlage und Lichttechnik für eine Hochzeit im Raum Köln?",
        "intent": "commercial",
    },
    {
        "id": "hochzeitsdj-fragen",
        "prompt": "Welche fünf Fragen sollte man einem Hochzeits-DJ vor der Buchung stellen?",
        "intent": "informational",
    },
)


class GeoSamplingError(RuntimeError):
    """A provider request or sampling configuration is invalid."""


@dataclass(frozen=True)
class PromptSpec:
    id: str
    prompt: str
    intent: str = "commercial"
    language: str = "de"
    region: str = "DE"


@dataclass(frozen=True)
class PromptSet:
    version: str
    language: str
    region: str
    prompts: tuple[PromptSpec, ...]


@dataclass(frozen=True)
class SamplingConfig:
    model: str = DEFAULT_MODEL
    temperature: float = 0.2
    max_tokens: int = 800
    thinking: str = "disabled"
    web_search: bool = False
    search_usd_per_1000: float = 0.75
    max_calls: int = 6
    budget_usd: float = 0.50
    input_usd_per_mtok: float = 0.30
    output_usd_per_mtok: float = 1.20
    retention_days: int = 30


@dataclass
class SampleResult:
    prompt_id: str
    query: str
    language: str
    region: str
    model: str
    answer: str = ""
    answer_sha256: str = ""
    citations: tuple[str, ...] = ()
    own_citations: tuple[str, ...] = ()
    brand_mentions: int = 0
    competitor_mentions: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    sampled_at: str = ""
    error: str | None = None


@dataclass
class SamplingRun:
    prompt_set: PromptSet
    config: SamplingConfig
    samples: list[SampleResult] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    stop_reason: str = ""

    @property
    def successful(self) -> int:
        return sum(1 for item in self.samples if item.error is None)

    @property
    def failed(self) -> int:
        return sum(1 for item in self.samples if item.error is not None)

    @property
    def total_tokens(self) -> int:
        return sum(item.total_tokens for item in self.samples)

    @property
    def estimated_cost(self) -> float:
        return round(sum(item.cost_usd for item in self.samples), 6)


def load_prompt_set(path: Path | str | None = None) -> PromptSet:
    if path is None:
        prompts = tuple(
            PromptSpec(
                id=str(item["id"]),
                prompt=str(item["prompt"]),
                intent=str(item.get("intent") or "commercial"),
            )
            for item in DEFAULT_PROMPTS
        )
        return PromptSet("geo-de-2026-11", "de", "DE", prompts)
    target = Path(path)
    try:
        payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    except OSError as error:
        raise GeoSamplingError(f"Prompt-Datei nicht lesbar: {error}") from error
    except yaml.YAMLError as error:
        raise GeoSamplingError(f"Prompt-Datei ist kein gültiges YAML: {error}") from error
    if isinstance(payload, list):
        version = "custom"
        language = "de"
        region = "DE"
        raw_prompts = payload
    elif isinstance(payload, dict):
        version = str(payload.get("version") or "custom")
        language = str(payload.get("language") or "de")
        region = str(payload.get("region") or "DE")
        raw_prompts = payload.get("prompts")
    else:
        raise GeoSamplingError("Prompt-Datei benötigt eine Liste oder ein Objekt.")
    if not isinstance(raw_prompts, list) or not raw_prompts:
        raise GeoSamplingError("Prompt-Datei enthält keine Prompts.")
    prompts: list[PromptSpec] = []
    ids: set[str] = set()
    for index, item in enumerate(raw_prompts, start=1):
        if not isinstance(item, dict):
            raise GeoSamplingError(f"Prompt {index} muss ein Objekt sein.")
        prompt_id = str(item.get("id") or "").strip()
        text = str(item.get("prompt") or item.get("query") or "").strip()
        if not prompt_id or not text:
            raise GeoSamplingError(f"Prompt {index} benötigt id und prompt.")
        if prompt_id in ids:
            raise GeoSamplingError(f"Prompt-ID doppelt: {prompt_id}")
        ids.add(prompt_id)
        prompts.append(
            PromptSpec(
                id=prompt_id,
                prompt=text,
                intent=str(item.get("intent") or "commercial"),
                language=str(item.get("language") or language),
                region=str(item.get("region") or region),
            )
        )
    return PromptSet(version, language, region, tuple(prompts))


def _endpoint(base_url: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    return value + "/chat/completions"


def _post_json(
    api_key: str,
    body: dict[str, Any],
    *,
    base_url: str,
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        _endpoint(base_url),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "SeoBoy/0.15",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(5_000_000).decode("utf-8", errors="replace")
    except HTTPError as error:
        detail = error.read(2000).decode("utf-8", errors="replace")
        try:
            message = json.loads(detail).get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            message = detail
        raise GeoSamplingError(
            f"DeepSeek HTTP {error.code}: {str(message)[:300]}"
        ) from error
    except URLError as error:
        raise GeoSamplingError(f"DeepSeek nicht erreichbar: {error.reason}") from error
    except OSError as error:
        raise GeoSamplingError(f"DeepSeek-Verbindung fehlgeschlagen: {error}") from error
    try:
        response_payload = json.loads(payload)
    except ValueError as error:
        raise GeoSamplingError("DeepSeek lieferte kein gültiges JSON.") from error
    if not isinstance(response_payload, dict):
        raise GeoSamplingError("DeepSeek lieferte ein unerwartetes Format.")
    return response_payload


def chat_completion(
    api_key: str,
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
    max_tokens: int = 800,
    thinking: str = "disabled",
    web_search: bool = False,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 90.0,
) -> dict[str, Any]:
    if not api_key:
        raise GeoSamplingError("Für GEO-Sampling wird ein DeepSeek-API-Key benötigt.")
    if web_search and thinking != "disabled":
        raise GeoSamplingError(
            "Websuche erfordert thinking=disabled, sonst antwortet DeepSeek ohne Suche."
        )
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking": {"type": thinking},
        "stream": False,
    }
    if web_search:
        body["tools"] = [{"type": "deepseek_web_search"}]
    payload = _post_json(
        api_key,
        body,
        base_url=base_url,
        timeout=timeout,
    )
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise GeoSamplingError("DeepSeek lieferte keine Antwort.")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise GeoSamplingError("DeepSeek lieferte eine leere Antwort.")
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    citations: list[str] = []

    def add_citation(value: Any) -> None:
        if isinstance(value, str) and value and value not in citations:
            citations.append(value)

    for annotation in message.get("annotations") or []:
        if isinstance(annotation, dict):
            citation = annotation.get("url_citation")
            if isinstance(citation, dict):
                add_citation(citation.get("url"))
    for step in message.get("server_tool_calls") or []:
        if not isinstance(step, dict):
            continue
        for call in step.get("calls") or []:
            if not isinstance(call, dict):
                continue
            for source in call.get("sources") or []:
                if isinstance(source, dict):
                    add_citation(source.get("url"))
            page = call.get("page")
            if isinstance(page, dict):
                add_citation(page.get("url"))
    return {
        "content": content,
        "usage": usage,
        "model": str(payload.get("model") or model),
        "id": str(payload.get("id") or ""),
        "citations": tuple(citations),
    }


def _urls(text: str) -> tuple[str, ...]:
    values = re.findall(r"https?://[^\s)\]\"'<>]+", text)
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = value.rstrip(".,;:!?")
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return tuple(result)


def _domain(value: str) -> str:
    try:
        return urlsplit(value).netloc.casefold().removeprefix("www.")
    except ValueError:
        return ""


def analyze_answer(
    answer: str,
    *,
    brands: tuple[str, ...] = DEFAULT_BRANDS,
    competitors: tuple[str, ...] = DEFAULT_COMPETITORS,
    domain: str = "",
) -> dict[str, Any]:
    folded = answer.casefold()
    citations = _urls(answer)
    own = tuple(
        value
        for value in citations
        if domain and _domain(value) == domain.casefold().removeprefix("www.")
    )
    brand_mentions = sum(max(0, folded.count(value.casefold())) for value in brands if value)
    competitor_mentions = sum(
        max(0, folded.count(value.casefold())) for value in competitors if value
    )
    return {
        "citations": citations,
        "own_citations": own,
        "brand_mentions": brand_mentions,
        "competitor_mentions": competitor_mentions,
    }


def _cost(usage: dict[str, Any], config: SamplingConfig) -> tuple[int, int, int, float]:
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
    cost = (
        prompt_tokens * config.input_usd_per_mtok
        + completion_tokens * config.output_usd_per_mtok
    ) / 1_000_000
    if config.web_search:
        cost += config.search_usd_per_1000 / 1000
    return prompt_tokens, completion_tokens, total_tokens, round(cost, 6)


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow([excel_safe(value) for value in row])


def run_sampling(
    *,
    api_key: str,
    prompt_set: PromptSet,
    config: SamplingConfig,
    out: Path,
    brands: tuple[str, ...] = DEFAULT_BRANDS,
    competitors: tuple[str, ...] = DEFAULT_COMPETITORS,
    domain: str = "",
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 90.0,
) -> SamplingRun:
    if not api_key:
        raise GeoSamplingError("Für GEO-Sampling wird ein DeepSeek-API-Key benötigt.")
    if not 1 <= config.max_calls <= 50:
        raise GeoSamplingError("max_calls muss zwischen 1 und 50 liegen.")
    if not 16 <= config.max_tokens <= 8192:
        raise GeoSamplingError("max_tokens muss zwischen 16 und 8192 liegen.")
    if not 0 <= config.temperature <= 2:
        raise GeoSamplingError("temperature muss zwischen 0 und 2 liegen.")
    if config.thinking not in {"disabled", "enabled"}:
        raise GeoSamplingError("thinking muss disabled oder enabled sein.")
    if config.web_search and config.thinking != "disabled":
        raise GeoSamplingError("Websuche erfordert thinking=disabled.")
    if config.search_usd_per_1000 < 0:
        raise GeoSamplingError("search_usd_per_1000 darf nicht negativ sein.")
    if config.budget_usd < 0:
        raise GeoSamplingError("budget_usd darf nicht negativ sein.")
    if not 0 <= config.retention_days <= 3650:
        raise GeoSamplingError("retention_days muss zwischen 0 und 3650 liegen.")
    run = SamplingRun(
        prompt_set=prompt_set,
        config=config,
        started_at=iso_utc(),
    )
    out.mkdir(parents=True, exist_ok=True)
    raw_rows: list[dict[str, Any]] = []
    prompts = prompt_set.prompts[: config.max_calls]
    for spec in prompts:
        if run.estimated_cost >= config.budget_usd:
            run.stop_reason = "budget"
            break
        try:
            response = chat_completion(
                api_key,
                spec.prompt,
                model=config.model,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                thinking=config.thinking,
                web_search=config.web_search,
                base_url=base_url,
                timeout=timeout,
            )
        except GeoSamplingError as error:
            sample = SampleResult(
                prompt_id=spec.id,
                query=spec.prompt,
                language=spec.language,
                region=spec.region,
                model=config.model,
                sampled_at=iso_utc(),
                error=str(error),
            )
            run.samples.append(sample)
            if "HTTP 401" in str(error) or "HTTP 403" in str(error):
                run.stop_reason = "auth_error"
                break
            if run.failed >= 3 and run.failed * 2 >= len(run.samples):
                run.stop_reason = "error_rate"
                break
            continue
        analysis = analyze_answer(
            response["content"], brands=brands, competitors=competitors, domain=domain
        )
        citations = tuple(
            dict.fromkeys(
                tuple(response.get("citations") or ()) + tuple(analysis["citations"])
            )
        )
        own_citations = tuple(
            value
            for value in citations
            if domain and _domain(value) == domain.casefold().removeprefix("www.")
        )
        prompt_tokens, completion_tokens, total_tokens, cost = _cost(
            response["usage"], config
        )
        answer = response["content"]
        sample = SampleResult(
            prompt_id=spec.id,
            query=spec.prompt,
            language=spec.language,
            region=spec.region,
            model=response["model"],
            answer=answer,
            answer_sha256=hashlib.sha256(answer.encode("utf-8")).hexdigest()[:16],
            citations=citations,
            own_citations=own_citations,
            brand_mentions=analysis["brand_mentions"],
            competitor_mentions=analysis["competitor_mentions"],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            sampled_at=iso_utc(),
        )
        run.samples.append(sample)
        raw_rows.append(
            {
                "provider": "deepseek",
                "model": sample.model,
                "prompt_id": sample.prompt_id,
                "query": sample.query,
                "language": sample.language,
                "region": sample.region,
                "answer": sample.answer,
                "answer_sha256": sample.answer_sha256,
                "citations": list(sample.citations),
                "own_citations": list(sample.own_citations),
                "brand_mentions": sample.brand_mentions,
                "competitor_mentions": sample.competitor_mentions,
                "prompt_tokens": sample.prompt_tokens,
                "completion_tokens": sample.completion_tokens,
                "total_tokens": sample.total_tokens,
                "cost_usd": sample.cost_usd,
                "sampled_at": sample.sampled_at,
            }
        )
    run.finished_at = iso_utc()
    if not run.stop_reason:
        run.stop_reason = "completed"
    raw = out / "raw_data"
    raw.mkdir(parents=True, exist_ok=True)
    if config.retention_days > 0:
        _write_jsonl(raw / "geo_answers.jsonl", raw_rows)
    _write_csv(
        raw / "geo_samples.csv",
        [
            "prompt_id",
            "query",
            "language",
            "region",
            "model",
            "brand_mentions",
            "own_citations",
            "competitor_mentions",
            "prompt_tokens",
            "completion_tokens",
            "cost_usd",
            "sampled_at",
            "error",
        ],
        [
            [
                item.prompt_id,
                item.query,
                item.language,
                item.region,
                item.model,
                item.brand_mentions,
                "|".join(item.own_citations),
                item.competitor_mentions,
                item.prompt_tokens,
                item.completion_tokens,
                item.cost_usd,
                item.sampled_at,
                item.error or "",
            ]
            for item in run.samples
        ],
    )
    _write_csv(
        raw / "geo_citations.csv",
        ["prompt_id", "citation", "own"],
        [
            [item.prompt_id, citation, "1" if citation in item.own_citations else "0"]
            for item in run.samples
            for citation in item.citations
        ],
    )
    lines = [
        "# SeoBoy – GEO-Sampling",
        "",
        f"**Anbieter:** DeepSeek  ",
        f"**Modell:** {config.model}  ",
        f"**Websuche:** {'ja' if config.web_search else 'nein'}  ",
        f"**Prompt-Set:** {prompt_set.version} ({prompt_set.language}/{prompt_set.region})  ",
        f"**Zeitraum:** {run.started_at} bis {run.finished_at}  ",
        f"**Aufbewahrungsrichtlinie der Rohantworten:** {config.retention_days} Tage "
        "(manuelle Löschung)  ",
        "",
        "## Zusammenfassung",
        "",
        f"- Stichproben: {len(run.samples)}",
        f"- Erfolgreich: {run.successful}",
        f"- Fehler: {run.failed}",
        f"- Marke erwähnt: {sum(1 for item in run.samples if item.brand_mentions > 0)}",
        f"- Eigene Domain zitiert: {sum(1 for item in run.samples if item.own_citations)}",
        f"- Tokens: {run.total_tokens}",
        f"- Geschätzte Kosten: {run.estimated_cost:.6f} USD (Peak-Tarif)",
        f"- Stoppgrund: {run.stop_reason}",
        "",
        "## Stichproben",
        "",
        "| Prompt | Marke | Eigene Zitate | Wettbewerber | Tokens | Kosten USD | Fehler |",
        "| --- | :---: | :---: | :---: | ---: | ---: | --- |",
    ]
    for item in run.samples:
        lines.append(
            "| "
            + " | ".join(
                [
                    item.prompt_id,
                    "ja" if item.brand_mentions else "nein",
                    str(len(item.own_citations)),
                    str(item.competitor_mentions),
                    str(item.total_tokens),
                    f"{item.cost_usd:.6f}",
                    item.error or "–",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Zitierte URLs",
            "",
            "| Prompt | URL | Eigene Domain |",
            "| --- | --- | :---: |",
        ]
    )
    for item in run.samples:
        if not item.citations:
            continue
        for citation in item.citations:
            lines.append(
                f"| {item.prompt_id} | {citation} | "
                f"{'ja' if citation in item.own_citations else 'nein'} |"
            )
    if not any(item.citations for item in run.samples):
        lines.append("| – | keine URL-Zitate erkannt | – |")
    lines.extend(
        [
            "",
            "## Grenzen",
            "",
            "- Die Antworten sind KI-generierte Momentaufnahmen, keine Suchmaschinen-Rankings.",
            "- Marken- und URL-Erkennung ist ein Textabgleich, keine Attribution.",
            "- Einzelne Antworten sind nicht repräsentativ; Wiederholungen und weitere Modelle",
            "  sind nötig, bevor daraus eine Strategie abgeleitet wird.",
            "- Rohantworten werden nur lokal gespeichert und nicht in die Datenbank",
            "  geschrieben; die Löschung nach der Aufbewahrungsfrist erfolgt manuell.",
            "",
            "## Rohdaten",
            "",
            "- [Stichproben](raw_data/geo_samples.csv)",
            "- [Zitate](raw_data/geo_citations.csv)",
            *(
                ["- [Rohantworten](raw_data/geo_answers.jsonl)"]
                if config.retention_days > 0
                else []
            ),
            "",
        ]
    )
    (out / "00_GEO_SAMPLING.md").write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n"
    )
    manifest = {
        "provider": "deepseek",
        "base_url": base_url,
        "model": config.model,
        "thinking": config.thinking,
        "web_search": config.web_search,
        "prompt_set": prompt_set.version,
        "language": prompt_set.language,
        "region": prompt_set.region,
        "prompts_available": len(prompt_set.prompts),
        "prompts_requested": len(prompts),
        "samples": len(run.samples),
        "successful": run.successful,
        "failed": run.failed,
        "total_tokens": run.total_tokens,
        "estimated_cost_usd": run.estimated_cost,
        "input_usd_per_mtok": config.input_usd_per_mtok,
        "output_usd_per_mtok": config.output_usd_per_mtok,
        "budget_usd": config.budget_usd,
        "retention_days": config.retention_days,
        "stop_reason": run.stop_reason,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return run


def retention_cutoff(days: int, *, now: datetime | None = None) -> str:
    moment = now or datetime.now().astimezone()
    return (moment - timedelta(days=days)).isoformat(timespec="seconds")
