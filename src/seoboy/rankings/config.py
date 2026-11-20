"""Keyword profiles for local ranking monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from seoboy.infrastructure.config import BUSINESS_VALUES
from seoboy.shared.urls import normalize_url


class KeywordConfigError(ValueError):
    """The keyword configuration is invalid."""


@dataclass(frozen=True)
class KeywordProfile:
    id: str
    query: str
    intent: str = "booking"
    tags: tuple[str, ...] = ()
    market: str = "DE"
    language: str = "de"
    location_key: str = ""
    engine: str = "google"
    device: str = "desktop"
    result_type: str = "organic"
    expected_target: str = ""
    target_active: bool = True
    business_value: str = "normal"


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KeywordConfigError(f"{field} muss ein nicht leerer Text sein.")
    return value.strip()


def _bool(value: Any, default: bool, field: str) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise KeywordConfigError(f"{field} muss true oder false sein.")
    return value


def _profile(raw: Any, index: int) -> KeywordProfile:
    if not isinstance(raw, dict):
        raise KeywordConfigError(f"keywords[{index}] muss eine Zuordnung sein.")
    ident = _text(raw.get("id"), f"keywords[{index}].id")
    query = _text(raw.get("query"), f"keywords[{index}].query")
    intent = _text(raw.get("intent", "booking"), f"keywords[{index}].intent")
    result_type = _text(
        raw.get("result_type", "organic"), f"keywords[{index}].result_type"
    )
    if result_type not in {"organic", "local_pack"}:
        raise KeywordConfigError(
            f"keywords[{index}].result_type muss organic oder local_pack sein."
        )
    device = _text(raw.get("device", "desktop"), f"keywords[{index}].device")
    if device not in {"desktop", "mobile"}:
        raise KeywordConfigError(
            f"keywords[{index}].device muss desktop oder mobile sein."
        )
    business_value = _text(
        raw.get("business_value", "normal"), f"keywords[{index}].business_value"
    )
    if business_value not in BUSINESS_VALUES:
        raise KeywordConfigError(
            f"keywords[{index}].business_value muss high, normal oder low sein."
        )
    expected = raw.get("expected_target", "")
    if expected is not None and not isinstance(expected, str):
        raise KeywordConfigError(f"keywords[{index}].expected_target muss Text sein.")
    expected = (expected or "").strip()
    if result_type == "organic" and expected:
        try:
            normalize_url(expected)
        except ValueError:
            if not expected.startswith("/"):
                raise KeywordConfigError(
                    f"keywords[{index}].expected_target muss ein Pfad oder eine URL sein."
                ) from None
    tags_raw = raw.get("tags", [])
    if tags_raw is None:
        tags_raw = []
    if not isinstance(tags_raw, list):
        raise KeywordConfigError(f"keywords[{index}].tags muss eine Liste sein.")
    tags = tuple(_text(tag, f"keywords[{index}].tags") for tag in tags_raw)
    return KeywordProfile(
        id=ident,
        query=query,
        intent=intent,
        tags=tags,
        market=_text(raw.get("market", "DE"), f"keywords[{index}].market"),
        language=_text(raw.get("language", "de"), f"keywords[{index}].language"),
        location_key=_text(
            raw.get("location_key", ""), f"keywords[{index}].location_key"
        )
        if raw.get("location_key")
        else "",
        engine=_text(raw.get("engine", "google"), f"keywords[{index}].engine"),
        device=device,
        result_type=result_type,
        expected_target=expected,
        target_active=_bool(
            raw.get("target_active"), True, f"keywords[{index}].target_active"
        ),
        business_value=business_value,
    )


def load_keywords(path: Path | str) -> tuple[KeywordProfile, ...]:
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8-sig"))
    except OSError as error:
        raise KeywordConfigError(f"Keyword-Datei nicht lesbar: {source}") from error
    except yaml.YAMLError as error:
        raise KeywordConfigError(f"Ungültiges YAML in {source}: {error}") from error
    if isinstance(raw, dict):
        raw = raw.get("keywords")
    if not isinstance(raw, list):
        raise KeywordConfigError("keywords muss eine Liste sein.")
    profiles = tuple(_profile(item, index) for index, item in enumerate(raw))
    ids = [profile.id for profile in profiles]
    if len(ids) != len(set(ids)):
        raise KeywordConfigError("Keyword-IDs müssen eindeutig sein.")
    if not profiles:
        raise KeywordConfigError("Mindestens ein Keyword wird benötigt.")
    return profiles
