"""Google-Search-Console-Import und Aufbereitung von UI-Exporten."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import csv
import io
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from seoboy.infrastructure import database
from seoboy.infrastructure.config import ProjectConfig
from seoboy.infrastructure.database import transaction
from seoboy.crawl.registry import UrlRegistry, classify_url
from seoboy.shared.urls import InvalidUrl, is_internal, normalize_url
from seoboy.shared.util import iso_utc, sha256_bytes, sha256_text

PAGE_GRAIN = "page"
PAGE_QUERY_GRAIN = "page_query"
REQUIRED_COLUMNS = {
    PAGE_GRAIN: ("page", "clicks", "impressions", "position"),
    PAGE_QUERY_GRAIN: ("page", "query", "clicks", "impressions", "position"),
}
MAX_REPORTED_ERRORS = 200


class GscError(ValueError):
    """Der Search-Console-Import ist nicht verwendbar."""


@dataclass(frozen=True)
class GscPeriod:
    start: date
    end: date
    source_format: str | None
    pages: Path | None
    page_queries: Path | None
    pages_name: str | None
    page_queries_name: str | None


@dataclass(frozen=True)
class GscManifest:
    base_dir: Path
    property: str
    search_type: str
    country: str | None
    device: str | None
    periods: tuple[GscPeriod, ...]


@dataclass
class ParsedRow:
    line: int
    source_page: str
    query: str
    clicks: int
    impressions: int
    position: float | None


@dataclass
class ParsedFile:
    path: Path
    grain: str
    period: GscPeriod
    rows: list[ParsedRow] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass
class DatasetInput:
    period: GscPeriod
    grain: str
    parsed: ParsedFile
    status: str


@dataclass
class GscImportSummary:
    import_id: int
    status: str
    datasets: int = 0
    metrics: int = 0
    matched: int = 0
    unmatched: int = 0
    ambiguous: int = 0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _parse_date(value: Any, label: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise GscError(f"{label} muss ein Kalendertag im Format JJJJ-MM-TT sein.")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise GscError(f"{label} ist kein gültiger Kalendertag: {value!r}") from None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GscError("Filterwerte müssen Text oder null sein.")
    value = value.strip()
    return value or None


def load_manifest(gsc_dir: Path) -> GscManifest:
    manifest_path = gsc_dir / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise GscError(f"manifest.json fehlt in {gsc_dir}") from None
    except (OSError, UnicodeError) as error:
        raise GscError(f"manifest.json ist nicht lesbar: {error}") from None
    except json.JSONDecodeError as error:
        raise GscError(f"manifest.json ist kein gültiges JSON: {error}") from None
    if not isinstance(payload, dict):
        raise GscError("manifest.json muss ein JSON-Objekt sein.")

    property_name = payload.get("property")
    if not isinstance(property_name, str) or not property_name.strip():
        raise GscError("manifest.property muss ein nicht leerer Textwert sein.")
    search_type = payload.get("search_type")
    if not isinstance(search_type, str) or not search_type.strip():
        raise GscError("manifest.search_type muss ein nicht leerer Textwert sein.")
    country = _optional_text(payload.get("country"))
    device = _optional_text(payload.get("device"))

    raw_periods = payload.get("periods")
    if not isinstance(raw_periods, list) or not raw_periods:
        raise GscError("manifest.periods muss eine nicht leere Liste sein.")
    periods: list[GscPeriod] = []
    seen: set[tuple[date, date]] = set()
    for index, item in enumerate(raw_periods, start=1):
        label = f"periods[{index}]"
        if not isinstance(item, dict):
            raise GscError(f"{label} muss ein JSON-Objekt sein.")
        start = _parse_date(item.get("start"), f"{label}.start")
        end = _parse_date(item.get("end"), f"{label}.end")
        if start > end:
            raise GscError(f"{label}: start liegt nach end.")
        if (start, end) in seen:
            raise GscError(f"{label}: Zeitraum {start} bis {end} ist doppelt angegeben.")
        seen.add((start, end))
        pages_name = item.get("pages")
        if not isinstance(pages_name, str) or not pages_name.strip():
            raise GscError(f"{label}.pages muss einen Dateinamen nennen.")
        page_queries_name = item.get("page_queries")
        if page_queries_name is not None and (
            not isinstance(page_queries_name, str) or not page_queries_name.strip()
        ):
            raise GscError(f"{label}.page_queries muss ein Dateiname oder null sein.")
        source_format = item.get("source_format")
        if source_format is not None and not isinstance(source_format, str):
            raise GscError(f"{label}.source_format muss Text oder null sein.")
        periods.append(
            GscPeriod(
                start=start,
                end=end,
                source_format=source_format,
                pages=_resolve_manifest_file(gsc_dir, pages_name, label),
                page_queries=(
                    _resolve_manifest_file(gsc_dir, page_queries_name, label)
                    if page_queries_name
                    else None
                ),
                pages_name=pages_name,
                page_queries_name=page_queries_name,
            )
        )
    periods.sort(key=lambda period: (period.start, period.end))
    return GscManifest(
        base_dir=gsc_dir,
        property=property_name.strip(),
        search_type=search_type.strip(),
        country=country,
        device=device,
        periods=tuple(periods),
    )


def _resolve_manifest_file(base_dir: Path, name: str, label: str) -> Path:
    candidate = Path(name)
    if candidate.is_absolute():
        raise GscError(f"{label}: Dateipfade müssen relativ zum Manifest sein.")
    resolved = (base_dir / candidate).resolve()
    try:
        resolved.relative_to(base_dir.resolve())
    except ValueError:
        raise GscError(f"{label}: Dateipfad verlässt das Manifest-Verzeichnis.") from None
    return resolved


def _parse_integer(value: str) -> int:
    text = value.strip().replace("\u00a0", "").replace(" ", "")
    if text == "":
        raise ValueError("leer")
    if not re.fullmatch(r"\d+", text):
        raise ValueError("keine nichtnegative ganze Zahl")
    return int(text)


def _parse_position(value: str, source_format: str | None) -> float | None:
    text = value.strip().replace("\u00a0", "").replace(" ", "")
    if text == "":
        return None
    try:
        number = float(text)
    except ValueError:
        raise ValueError("keine Zahl") from None
    if number < 0:
        raise ValueError("negativ")
    if number == 0:
        if source_format == "gsc_ui_csv":
            return None
        raise ValueError("Position 0 ist ohne source_format=gsc_ui_csv nicht zulässig")
    if number < 1:
        raise ValueError("Position kleiner als 1")
    return round(number, 4)


def parse_file(parsed: ParsedFile) -> None:
    grain = parsed.grain
    required = REQUIRED_COLUMNS[grain]
    try:
        raw = parsed.path.read_bytes()
    except OSError as error:
        parsed.errors.append({"line": 0, "reason": f"Datei nicht lesbar: {error}"})
        return
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        parsed.errors.append({"line": 0, "reason": "Datei ist nicht UTF-8-kodiert"})
        return
    reader = csv.reader(io.StringIO(text), delimiter=",")
    try:
        header = next(reader)
    except StopIteration:
        parsed.errors.append({"line": 0, "reason": "Datei ist leer"})
        return
    normalized_header = [cell.strip().casefold() for cell in header]
    missing = [column for column in required if column not in normalized_header]
    if missing:
        parsed.errors.append(
            {
                "line": 1,
                "reason": "Pflichtspalten fehlen: " + ", ".join(missing)
                + " (gefunden: " + ", ".join(header) + ")",
            }
        )
        return
    index = {column: normalized_header.index(column) for column in required}
    seen: set[tuple[str, str]] = set()
    for row in reader:
        line = reader.line_num
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) < len(header):
            parsed.errors.append(
                {"line": line, "reason": f"Spaltenzahl {len(row)} statt {len(header)}"}
            )
            continue
        try:
            source_page = row[index["page"]].strip()
            if not source_page:
                raise ValueError("page ist leer")
            query = row[index["query"]].strip() if grain == PAGE_QUERY_GRAIN else ""
            if grain == PAGE_QUERY_GRAIN and not query:
                raise ValueError("query ist leer")
            clicks = _parse_integer(row[index["clicks"]])
            impressions = _parse_integer(row[index["impressions"]])
            position = _parse_position(
                row[index["position"]], parsed.period.source_format
            )
        except (ValueError, IndexError) as error:
            parsed.errors.append({"line": line, "reason": str(error)})
            continue
        key = (source_page, query)
        if key in seen:
            parsed.errors.append(
                {"line": line, "reason": f"Dimensionsschlüssel doppelt: {source_page}"}
            )
            continue
        seen.add(key)
        parsed.rows.append(
            ParsedRow(
                line=line,
                source_page=source_page,
                query=query,
                clicks=clicks,
                impressions=impressions,
                position=position,
            )
        )
    if len(parsed.errors) > MAX_REPORTED_ERRORS:
        parsed.errors = parsed.errors[:MAX_REPORTED_ERRORS]


def _mapping_for_rows(
    config: ProjectConfig,
    registry: UrlRegistry,
    rows: list[ParsedRow],
    import_id: int,
    *,
    file_name: str,
) -> tuple[dict[str, tuple[str, int | None]], list[dict[str, Any]], dict[str, int]]:
    """Ordnet Quell-URLs den normalisierten Projekt-URLs zu.

    Liefert Zuordnung je Quellseite, Mapping-Hinweise und Zählwerte.
    """
    counts = {"matched": 0, "unmatched": 0, "ambiguous": 0}
    issues: list[dict[str, Any]] = []
    per_page: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.source_page in per_page:
            continue
        try:
            normalized = normalize_url(
                row.source_page, config.crawl.remove_query_params
            )
        except InvalidUrl:
            per_page[row.source_page] = {
                "status": "unmatched",
                "url_id": None,
                "reason": "invalid_url",
            }
            continue
        if not is_internal(normalized, config.allowed_hosts):
            per_page[row.source_page] = {
                "status": "unmatched",
                "url_id": None,
                "reason": "host_not_allowed",
            }
            continue
        per_page[row.source_page] = {"normalized": normalized, "status": "pending"}

    groups: dict[str, list[str]] = {}
    for page, entry in per_page.items():
        normalized = entry.get("normalized")
        if normalized is not None:
            groups.setdefault(normalized.url, []).append(page)

    mapping: dict[str, tuple[str, int | None]] = {}
    registered: set[int] = set()
    for normalized_url, pages in groups.items():
        normalized = normalize_url(normalized_url)
        url_id, _ = registry.ensure_url(normalized)
        if len(pages) > 1:
            for page in pages:
                mapping[page] = ("ambiguous", None)
                issues.append(
                    {
                        "file": file_name,
                        "page": page,
                        "status": "ambiguous",
                        "reason": "multiple_source_pages_normalize_to_same_url",
                    }
                )
            if url_id not in registered:
                registered.add(url_id)
                registry.add_discovery(url_id, pages[0], "gsc", import_id=import_id)
                reason = classify_url(config, normalized)
                if reason is not None:
                    registry.set_excluded(url_id, reason)
                else:
                    registry.add_job(url_id, "page", 10_000, not_before_at=iso_utc())
            continue
        page = pages[0]
        mapping[page] = ("matched", url_id)
        registry.add_discovery(url_id, page, "gsc", import_id=import_id)
        if url_id not in registered:
            registered.add(url_id)
            reason = classify_url(config, normalized)
            if reason is not None:
                registry.set_excluded(url_id, reason)
            else:
                registry.add_job(url_id, "page", 10_000, not_before_at=iso_utc())

    for page, entry in per_page.items():
        if entry["status"] != "pending":
            mapping[page] = (entry["status"], None)
            issues.append(
                {
                    "file": file_name,
                    "page": page,
                    "status": entry["status"],
                    "reason": entry["reason"],
                }
            )
    for row in rows:
        status, _ = mapping.get(row.source_page, ("unmatched", None))
        counts[status] += 1
    if len(issues) > MAX_REPORTED_ERRORS:
        issues = issues[:MAX_REPORTED_ERRORS]
    return mapping, issues, counts


def import_gsc_directory(
    connection: sqlite3.Connection,
    run_id: str,
    config: ProjectConfig,
    gsc_dir: Path | None,
    registry: UrlRegistry,
) -> GscImportSummary:
    captured_at = iso_utc()
    if gsc_dir is None:
        import_id = database.next_id(connection, "source_imports", "import_id", run_id)
        with transaction(connection):
            connection.execute(
                "INSERT INTO source_imports(run_id, import_id, module, provider, status, "
                "captured_at, input_hash, metadata_json) VALUES (?, ?, 'gsc', 'gsc_csv', "
                "'disabled', ?, NULL, ?)",
                (
                    run_id,
                    import_id,
                    captured_at,
                    json.dumps({"reason": "no_gsc_directory"}, ensure_ascii=False),
                ),
            )
        return GscImportSummary(
            import_id=import_id,
            status="disabled",
            notes=["Kein GSC-Verzeichnis angegeben."],
        )

    if not gsc_dir.is_dir():
        import_id = _write_unavailable_import(
            connection, run_id, captured_at, f"Verzeichnis nicht gefunden: {gsc_dir}"
        )
        return GscImportSummary(
            import_id=import_id,
            status="unavailable",
            errors=[f"Verzeichnis nicht gefunden: {gsc_dir}"],
        )

    try:
        manifest = load_manifest(gsc_dir)
    except GscError as error:
        import_id = _write_unavailable_import(connection, run_id, captured_at, str(error))
        return GscImportSummary(import_id=import_id, status="unavailable", errors=[str(error)])

    parsed_files: list[ParsedFile] = []
    for period in manifest.periods:
        pages_file = ParsedFile(
            path=period.pages, grain=PAGE_GRAIN, period=period
        ) if period.pages is not None else None
        if pages_file is not None:
            parse_file(pages_file)
            parsed_files.append(pages_file)
        if period.page_queries is not None:
            query_file = ParsedFile(
                path=period.page_queries, grain=PAGE_QUERY_GRAIN, period=period
            )
            parse_file(query_file)
            parsed_files.append(query_file)

    valid_files = [item for item in parsed_files if item.valid]
    status = "ok" if len(valid_files) == len(parsed_files) and parsed_files else "partial"
    if not valid_files:
        status = "unavailable"

    import_id = database.next_id(connection, "source_imports", "import_id", run_id)
    dataset_inputs: list[DatasetInput] = []
    for parsed in parsed_files:
        dataset_inputs.append(
            DatasetInput(
                period=parsed.period,
                grain=parsed.grain,
                parsed=parsed,
                status="ok" if parsed.valid else "invalid",
            )
        )
    metadata: dict[str, Any] = {
        "property": manifest.property,
        "search_type": manifest.search_type,
        "country": manifest.country,
        "device": manifest.device,
        "periods": [
            {
                "start": period.start.isoformat(),
                "end": period.end.isoformat(),
                "source_format": period.source_format,
                "pages": period.pages_name,
                "page_queries": period.page_queries_name,
            }
            for period in manifest.periods
        ],
        "files": [
            {
                "name": item.path.name,
                "grain": item.grain,
                "period": [item.period.start.isoformat(), item.period.end.isoformat()],
                "status": "ok" if item.valid else "invalid",
                "errors": item.errors,
                "rows": len(item.rows),
            }
            for item in parsed_files
        ],
        "notes": [],
        "mapping_issues": [],
    }
    source_format_values = {
        period.source_format for period in manifest.periods if period.source_format
    }
    if "gsc_ui_csv" in source_format_values:
        metadata["notes"].append(
            "Quelle gsc_ui_csv: Export kann abgeschnitten sein; fehlende Anzeigewerte "
            "können als Nullen erscheinen; Position 0 wird als unbekannt übernommen."
        )
        metadata["truncated_export"] = True
        metadata["missing_values_may_be_zero"] = True
    manifest_hash = _hash_inputs(gsc_dir, manifest)
    counts = {"matched": 0, "unmatched": 0, "ambiguous": 0}
    errors: list[str] = []
    datasets = 0
    metrics = 0
    with transaction(connection):
        connection.execute(
            "INSERT INTO source_imports(run_id, import_id, module, provider, status, "
            "captured_at, input_hash, metadata_json) VALUES (?, ?, 'gsc', 'gsc_csv', ?, ?, ?, ?)",
            (
                run_id,
                import_id,
                status,
                captured_at,
                manifest_hash,
                json.dumps({"status": status}, ensure_ascii=False),
            ),
        )
        for item in dataset_inputs:
            if not item.parsed.valid:
                for error in item.parsed.errors:
                    errors.append(
                        f"{item.parsed.path.name}: Zeile {error['line']}: {error['reason']}"
                    )
                continue
            dataset_id = database.next_id(
                connection, "gsc_datasets", "dataset_id", run_id
            )
            connection.execute(
                "INSERT INTO gsc_datasets(run_id, dataset_id, import_id, property, "
                "search_type, country, device, period_start, period_end, grain) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    dataset_id,
                    import_id,
                    manifest.property,
                    manifest.search_type,
                    manifest.country or "",
                    manifest.device or "",
                    item.period.start.isoformat(),
                    item.period.end.isoformat(),
                    item.grain,
                ),
            )
            mapping, issues, file_counts = _mapping_for_rows(
                config,
                registry,
                item.parsed.rows,
                import_id,
                file_name=item.parsed.path.name,
            )
            metadata["mapping_issues"].extend(issues)
            for key in counts:
                counts[key] += file_counts.get(key, 0)
            metric_rows: list[tuple[Any, ...]] = []
            for row in item.parsed.rows:
                status_value, url_id = mapping.get(row.source_page, ("unmatched", None))
                metric_rows.append(
                    (
                        run_id,
                        dataset_id,
                        row.source_page,
                        row.query,
                        url_id,
                        status_value,
                        row.clicks,
                        row.impressions,
                        row.position,
                    )
                )
            if metric_rows:
                connection.executemany(
                    "INSERT INTO gsc_metrics(run_id, dataset_id, source_page, query, url_id, "
                    "mapping_status, clicks, impressions, position) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    metric_rows,
                )
            metrics += len(metric_rows)
            datasets += 1
        metadata["mapping"] = counts
        metadata["error_count"] = len(errors)
        metadata["errors"] = errors[:MAX_REPORTED_ERRORS]
        if len(metadata["mapping_issues"]) > MAX_REPORTED_ERRORS:
            metadata["mapping_issues"] = metadata["mapping_issues"][:MAX_REPORTED_ERRORS]
        connection.execute(
            "UPDATE source_imports SET metadata_json = ? "
            "WHERE run_id = ? AND import_id = ?",
            (json.dumps(metadata, ensure_ascii=False), run_id, import_id),
        )
    return GscImportSummary(
        import_id=import_id,
        status=status,
        datasets=datasets,
        metrics=metrics,
        matched=counts["matched"],
        unmatched=counts["unmatched"],
        ambiguous=counts["ambiguous"],
        errors=errors,
        notes=metadata["notes"],
    )


def _write_unavailable_import(
    connection: sqlite3.Connection, run_id: str, captured_at: str, message: str
) -> int:
    import_id = database.next_id(connection, "source_imports", "import_id", run_id)
    with transaction(connection):
        connection.execute(
            "INSERT INTO source_imports(run_id, import_id, module, provider, status, "
            "captured_at, input_hash, metadata_json) VALUES (?, ?, 'gsc', 'gsc_csv', "
            "'unavailable', ?, NULL, ?)",
            (
                run_id,
                import_id,
                captured_at,
                json.dumps({"error": message}, ensure_ascii=False),
            ),
        )
    return import_id


def _hash_inputs(gsc_dir: Path, manifest: GscManifest) -> str:
    parts = [sha256_bytes((gsc_dir / "manifest.json").read_bytes())]
    for period in manifest.periods:
        for path in (period.pages, period.page_queries):
            if path is not None and path.exists():
                parts.append(sha256_bytes(path.read_bytes()))
    return sha256_text("|".join(parts))


def describe_inputs(gsc_dir: Path | None) -> dict[str, Any] | None:
    """Bezeichner und Hashes der Importdateien für runs.inputs_json."""
    if gsc_dir is None:
        return None
    description: dict[str, Any] = {"directory": str(gsc_dir.resolve())}
    try:
        manifest_bytes = (gsc_dir / "manifest.json").read_bytes()
    except OSError as error:
        description["error"] = f"manifest.json nicht lesbar: {error}"
        return description
    description["manifest_sha256"] = sha256_bytes(manifest_bytes)
    files: list[dict[str, Any]] = []
    try:
        manifest = load_manifest(gsc_dir)
    except GscError as error:
        description["error"] = str(error)
        return description
    for period in manifest.periods:
        for path in (period.pages, period.page_queries):
            if path is None:
                continue
            entry: dict[str, Any] = {"name": path.name}
            try:
                entry["sha256"] = sha256_bytes(path.read_bytes())
            except OSError as error:
                entry["error"] = str(error)
            files.append(entry)
    description["files"] = files
    description["property"] = manifest.property
    description["search_type"] = manifest.search_type
    description["country"] = manifest.country
    description["device"] = manifest.device
    description["periods"] = [
        {"start": period.start.isoformat(), "end": period.end.isoformat()}
        for period in manifest.periods
    ]
    return description


# ---------------------------------------------------------------------- Vergleichsperioden


def period_length(period_start: str, period_end: str) -> int:
    return (
        date.fromisoformat(period_end) - date.fromisoformat(period_start)
    ).days + 1


def select_comparison_periods(
    datasets: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Wählt die beiden jüngsten überlappungsfreien Zeiträume gleicher Länge."""
    if not datasets:
        return None, None
    ordered = sorted(
        datasets,
        key=lambda item: (item["period_end"], item["period_start"]),
        reverse=True,
    )
    latest = ordered[0]
    latest_length = period_length(latest["period_start"], latest["period_end"])
    previous = None
    for candidate in ordered[1:]:
        if candidate["period_end"] >= latest["period_start"]:
            continue
        if period_length(candidate["period_start"], candidate["period_end"]) != latest_length:
            continue
        previous = candidate
        break
    return latest, previous


# ---------------------------------------------------------------------- Aufbereiter


PAGE_ALIASES = {
    "page",
    "pages",
    "seite",
    "seiten",
    "top pages",
    "top seiten",
    "top 10 seiten",
    "url",
    "urls",
    "landing page",
    "landing pages",
    "zielseite",
    "zielseiten",
}
CLICK_ALIASES = {"click", "clicks", "klick", "klicks", "klicks gesamt"}
IMPRESSION_ALIASES = {
    "impression",
    "impressions",
    "impressionen",
    "anzeigen",
    "impressionen gesamt",
}
POSITION_ALIASES = {
    "position",
    "average position",
    "avg position",
    "avg. position",
    "durchschnittliche position",
    "durchschnittl. position",
    "durchschnittsposition",
    "ø position",
    "o position",
}
ALIASES = {
    "page": PAGE_ALIASES,
    "clicks": CLICK_ALIASES,
    "impressions": IMPRESSION_ALIASES,
    "position": POSITION_ALIASES,
}


def _normalize_header(value: str) -> str:
    value = value.replace("\ufeff", "").strip().casefold()
    value = value.replace("-", " ").replace("_", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" :")


def _detect_delimiter(text: str, explicit: str | None) -> str:
    if explicit is not None:
        if explicit in {"\\t", "tab"}:
            return "\t"
        if explicit in {";", ",", "\t"}:
            return explicit
        raise GscError("Trennzeichen muss ';', ',' oder '\\t' sein.")
    first_lines = [line for line in text.splitlines() if line.strip()][:3]
    if not first_lines:
        raise GscError("Die Datei ist leer.")
    candidates = [";", "\t", ","]
    best = max(candidates, key=lambda char: first_lines[0].count(char))
    if first_lines[0].count(best) == 0:
        raise GscError("Kein Trennzeichen erkannt. Bitte --delimiter angeben.")
    return best


def _infer_decimal(position_samples: list[str], explicit: str | None) -> str:
    if explicit is not None:
        if explicit not in {",", "."}:
            raise GscError("Dezimalzeichen muss ',' oder '.' sein.")
        return explicit
    votes = {",": 0, ".": 0}
    for sample in position_samples:
        sample = sample.strip().replace(" ", "")
        if not sample:
            continue
        comma = sample.rfind(",")
        dot = sample.rfind(".")
        if comma > dot:
            votes[","] += 1
        elif dot > comma:
            votes["."] += 1
    if votes[","] > votes["."]:
        return ","
    return "."


def _number(value: str, decimal: str) -> float:
    text = value.strip().replace("\u00a0", "").replace(" ", "")
    if text == "":
        raise ValueError("leer")
    if decimal == ",":
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    return float(text)


def _map_columns(header: list[str], columns: dict[str, str] | None) -> dict[str, int]:
    normalized = [_normalize_header(cell) for cell in header]
    mapping: dict[str, int] = {}
    if columns:
        for field_name, source_name in columns.items():
            if field_name not in ALIASES:
                raise GscError(f"Unbekanntes Zielfeld im Spaltenmapping: {field_name}")
            target = _normalize_header(source_name)
            matches = [index for index, value in enumerate(normalized) if value == target]
            if len(matches) != 1:
                raise GscError(
                    f"Spalte für '{field_name}' nicht eindeutig gefunden: {source_name!r}"
                )
            mapping[field_name] = matches[0]
    else:
        candidates: dict[str, list[int]] = {field: [] for field in ALIASES}
        for index, value in enumerate(normalized):
            for field_name, aliases in ALIASES.items():
                if value in aliases:
                    candidates[field_name].append(index)
        for field_name, indices in candidates.items():
            if len(indices) > 1:
                raise GscError(
                    f"Spalte für '{field_name}' ist mehrdeutig: "
                    + ", ".join(header[index] for index in indices)
                )
            if not indices:
                raise GscError(
                    f"Pflichtspalte für '{field_name}' fehlt. Gefundene Spalten: "
                    + ", ".join(header)
                )
            mapping[field_name] = indices[0]
    missing = [field for field in ("page", "clicks", "impressions", "position") if field not in mapping]
    if missing:
        raise GscError("Pflichtspalten fehlen: " + ", ".join(missing))
    return mapping


def prepare_export(
    input_path: Path,
    out_dir: Path,
    *,
    property_name: str,
    start: date,
    end: date,
    search_type: str = "web",
    country: str | None = None,
    device: str | None = None,
    delimiter: str | None = None,
    decimal: str | None = None,
    columns: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Überführt einen GSC-UI-Seitenexport in das normalisierte CSV-Format."""
    if start > end:
        raise GscError("Der Startzeitraum liegt nach dem Endzeitraum.")
    if not property_name.strip():
        raise GscError("Die Property muss angegeben werden.")
    try:
        raw = input_path.read_bytes()
    except OSError as error:
        raise GscError(f"Exportdatei nicht lesbar: {error}") from None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError:
            raise GscError("Exportdatei ist weder UTF-8 noch cp1252.") from None

    delimiter = _detect_delimiter(text, delimiter)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        raise GscError("Die Exportdatei ist leer.")
    header_index = None
    for index, row in enumerate(rows):
        if sum(1 for cell in row if cell.strip()) >= 3:
            header_index = index
            break
    if header_index is None:
        raise GscError("In der Exportdatei wurde keine Kopfzeile gefunden.")
    header = [cell.strip() for cell in rows[header_index]]
    mapping = _map_columns(header, columns)
    data_rows = [row for row in rows[header_index + 1 :] if any(cell.strip() for cell in row)]
    position_samples = [
        row[mapping["position"]]
        for row in data_rows
        if len(row) > mapping["position"] and row[mapping["position"]].strip() not in {"", "-"}
    ][:50]
    decimal = _infer_decimal(position_samples, decimal)

    normalized_rows: list[tuple[str, int, int, float | None]] = []
    errors: list[str] = []
    seen: set[str] = set()
    unknown_positions = 0
    for offset, row in enumerate(data_rows, start=header_index + 2):
        if len(row) <= max(mapping.values()):
            errors.append(f"Zeile {offset}: zu wenige Spalten")
            continue
        page = row[mapping["page"]].strip()
        if not page:
            errors.append(f"Zeile {offset}: Seite ist leer")
            continue
        if page in seen:
            errors.append(f"Zeile {offset}: Seite ist doppelt ({page})")
            continue
        seen.add(page)
        try:
            clicks_value = _number(row[mapping["clicks"]], decimal)
            impressions_value = _number(row[mapping["impressions"]], decimal)
            if clicks_value < 0 or impressions_value < 0:
                raise ValueError("negativ")
            if int(clicks_value) != clicks_value or int(impressions_value) != impressions_value:
                raise ValueError("keine ganze Zahl")
            clicks = int(clicks_value)
            impressions = int(impressions_value)
        except ValueError as error:
            errors.append(f"Zeile {offset}: Klicks/Impressionen ungültig ({error})")
            continue
        raw_position = row[mapping["position"]].strip()
        position: float | None = None
        if raw_position:
            try:
                value = _number(raw_position, decimal)
            except ValueError:
                errors.append(f"Zeile {offset}: Position ungültig")
                continue
            if value < 0:
                errors.append(f"Zeile {offset}: Position negativ")
                continue
            if value == 0:
                unknown_positions += 1
            else:
                position = round(value, 4)
        else:
            unknown_positions += 1
        normalized_rows.append((page, clicks, impressions, position))
    if errors:
        shown = "\n".join(errors[:20])
        more = f"\n… und {len(errors) - 20} weitere Fehler." if len(errors) > 20 else ""
        raise GscError(
            f"Der Export enthält ungültige Zeilen und wird nicht übernommen:\n{shown}{more}"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{start.isoformat()}_{end.isoformat()}_pages.csv"
    target = out_dir / file_name
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\n")
        writer.writerow(["page", "clicks", "impressions", "position"])
        for page, clicks, impressions, position in normalized_rows:
            writer.writerow(
                [
                    page,
                    clicks,
                    impressions,
                    "" if position is None else _format_position(position),
                ]
            )

    manifest_path = out_dir / "manifest.json"
    manifest: dict[str, Any]
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as error:
            raise GscError(f"Vorhandenes manifest.json ist nicht lesbar: {error}") from None
        if not isinstance(manifest, dict):
            raise GscError("Vorhandenes manifest.json ist kein JSON-Objekt.")
        for key, value in (
            ("property", property_name),
            ("search_type", search_type),
            ("country", country or None),
            ("device", device or None),
        ):
            existing = manifest.get(key)
            if existing is not None and existing != value:
                raise GscError(
                    f"Vorhandenes Manifest enthält {key}={existing!r}, "
                    f"angegeben ist {value!r}."
                )
            manifest[key] = existing if existing is not None else value
    else:
        manifest = {
            "property": property_name,
            "search_type": search_type,
            "country": country or None,
            "device": device or None,
            "periods": [],
        }
    periods = [item for item in manifest.get("periods", []) if isinstance(item, dict)]
    replaced = False
    for item in periods:
        if item.get("start") == start.isoformat() and item.get("end") == end.isoformat():
            item["pages"] = file_name
            item["source_format"] = "gsc_ui_csv"
            replaced = True
            break
    if not replaced:
        periods.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "source_format": "gsc_ui_csv",
                "pages": file_name,
            }
        )
    periods.sort(key=lambda item: (str(item.get("start", "")), str(item.get("end", ""))))
    manifest["periods"] = periods
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "file": str(target),
        "manifest": str(manifest_path),
        "rows": len(normalized_rows),
        "unknown_positions": unknown_positions,
        "delimiter": delimiter,
        "decimal": decimal,
    }


def _format_position(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"
