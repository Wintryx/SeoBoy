#!/usr/bin/env python
"""Fail when tracked content or Git history contains high-confidence secrets."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 2_000_000

PATTERNS = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----[\r\n]+"
            r"[A-Za-z0-9+/=]{40,}"
        ),
    ),
    ("deepseek_or_openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_oauth_token", re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}\b")),
    ("google_refresh_token", re.compile(r"(?<!\w)1//[A-Za-z0-9_-]{30,}")),
    (
        "refresh_token_value",
        re.compile(r"[\"']refresh_token[\"']\s*:\s*[\"'][A-Za-z0-9._-]{30,}[\"']"),
    ),
    (
        "env_secret_assignment",
        re.compile(
            r"(?im)^(?:export\s+)?[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)"
            r"\s*=\s*[\"']?[A-Za-z0-9_\-]{24,}"
        ),
    ),
)


def _text(data: bytes) -> str | None:
    if b"\x00" in data[:4096]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def find_secrets(text: str, name: str = "") -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for label, pattern in PATTERNS:
        if pattern.search(text):
            findings.append((label, name))
    return findings


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    return [ROOT / value for value in result.stdout.decode("utf-8").split("\0") if value]


def _scan_paths(paths: Iterable[Path]) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for path in paths:
        try:
            if not path.is_file() or path.stat().st_size > MAX_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        text = _text(data)
        if text is not None:
            findings.extend(find_secrets(text, str(path.relative_to(ROOT))))
    return findings


def _scan_staged() -> list[tuple[str, str]]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--cached", "--name-only", "-z"],
        capture_output=True,
        check=True,
    )
    findings: list[tuple[str, str]] = []
    for name in result.stdout.decode("utf-8").split("\0"):
        if not name:
            continue
        blob = subprocess.run(
            ["git", "-C", str(ROOT), "show", f":{name}"],
            capture_output=True,
        )
        if blob.returncode != 0 or len(blob.stdout) > MAX_BYTES:
            continue
        text = _text(blob.stdout)
        if text is not None:
            findings.extend(find_secrets(text, name))
    return findings


def _scan_history() -> list[tuple[str, str]]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-list", "--objects", "--all"],
        capture_output=True,
        check=True,
    )
    names: dict[str, str] = {}
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1] and not parts[1].endswith("/"):
            names.setdefault(parts[0], parts[1])
    object_ids = list(names)
    if not object_ids:
        return []
    process = subprocess.Popen(
        ["git", "-C", str(ROOT), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    output, _ = process.communicate(
        ("\n".join(object_ids) + "\n").encode("utf-8"), timeout=120
    )
    findings: list[tuple[str, str]] = []
    position = 0
    for object_id in object_ids:
        header_end = output.find(b"\n", position)
        if header_end < 0:
            break
        header = output[position:header_end].decode("utf-8", errors="replace")
        parts = header.split()
        position = header_end + 1
        if len(parts) < 3 or parts[1] != "blob":
            continue
        try:
            size = int(parts[2])
        except ValueError:
            break
        data = output[position : position + size]
        position += size + 1
        if size > MAX_BYTES:
            continue
        text = _text(data)
        if text is not None:
            findings.extend(find_secrets(text, f"history:{names[object_id]}"))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="nur den Git-Index prüfen")
    parser.add_argument("--history", action="store_true", help="alle Git-Blobs prüfen")
    args = parser.parse_args(argv)
    findings: list[tuple[str, str]] = []
    if args.staged:
        findings = _scan_staged()
        mode = "Index"
    elif args.history:
        findings = _scan_paths(_tracked_files())
        findings.extend(_scan_history())
        mode = "Arbeitsbaum und Historie"
    else:
        findings = _scan_paths(_tracked_files())
        mode = "Arbeitsbaum"
    if findings:
        print(f"Secret-Scan fehlgeschlagen ({mode}):", file=sys.stderr)
        for label, name in sorted(set(findings))[:50]:
            print(f"- {label}: {name}", file=sys.stderr)
        print(
            "Bitte den Wert entfernen, den Key rotieren und die Historie bereinigen.",
            file=sys.stderr,
        )
        return 1
    print(f"Secret-Scan OK ({mode}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
