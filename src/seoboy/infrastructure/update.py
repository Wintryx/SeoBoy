"""Safely update the local SeoBoy CLI from its Git checkout."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import tomllib


class UpdateError(RuntimeError):
    """The local checkout cannot be updated safely."""


@dataclass(frozen=True)
class UpdateStatus:
    repo: Path
    branch: str
    upstream: str
    current_commit: str
    target_commit: str
    current_version: str | None
    target_version: str | None
    ahead: int
    behind: int
    dirty: tuple[str, ...]


@dataclass(frozen=True)
class UpdateResult:
    status: UpdateStatus
    updated: bool
    old_commit: str
    new_commit: str
    version: str | None
    installed: bool
    verified: bool


def find_repo_root(repo: Path | str | None = None) -> Path:
    candidates = [Path(repo)] if repo is not None else list(Path(__file__).resolve().parents)
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if (resolved / ".git").exists() and (resolved / "pyproject.toml").is_file():
            return resolved
    raise UpdateError(
        "Kein SeoBoy-Git-Checkout gefunden. Der Updater benötigt ein lokales "
        "Repository mit .git und pyproject.toml."
    )


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_PAGER", "cat")
    return env


def _git(repo: Path, *args: str, timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_git_env(),
            check=False,
        )
    except FileNotFoundError as error:
        raise UpdateError("Git wurde nicht gefunden. Bitte Git installieren.") from error
    except subprocess.TimeoutExpired as error:
        raise UpdateError(
            f"Git-Befehl '{' '.join(args)}' hat das Zeitlimit überschritten."
        ) from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise UpdateError(f"Git-Befehl '{' '.join(args)}' fehlgeschlagen: {detail}")
    return result.stdout.strip()


def _version_from_toml(text: str) -> str | None:
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, TypeError):
        return None
    project = data.get("project")
    if not isinstance(project, dict):
        return None
    version = project.get("version")
    return str(version) if version is not None else None


def _local_version(repo: Path) -> str | None:
    try:
        return _version_from_toml((repo / "pyproject.toml").read_text(encoding="utf-8"))
    except OSError:
        return None


def _target_version(repo: Path) -> str | None:
    try:
        text = _git(repo, "show", "@{u}:pyproject.toml")
    except UpdateError:
        return None
    return _version_from_toml(text)


def _branch(repo: Path) -> str:
    try:
        return _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    except UpdateError as error:
        raise UpdateError(
            "Der Checkout ist nicht auf einem Branch. Bitte einen Branch auschecken."
        ) from error


def _upstream(repo: Path) -> str:
    try:
        return _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    except UpdateError as error:
        raise UpdateError(
            "Für den aktuellen Branch ist kein Upstream konfiguriert. "
            "Beispiel: git branch --set-upstream-to=origin/main"
        ) from error


def check_for_update(repo: Path | str | None = None) -> UpdateStatus:
    root = find_repo_root(repo)
    _git(root, "rev-parse", "--show-toplevel")
    _git(root, "fetch", "--prune", timeout=90)
    branch = _branch(root)
    upstream = _upstream(root)
    current_commit = _git(root, "rev-parse", "HEAD")
    target_commit = _git(root, "rev-parse", "@{u}")
    counts = _git(root, "rev-list", "--left-right", "--count", "HEAD...@{u}").split()
    if len(counts) != 2:
        raise UpdateError("Git lieferte keinen gültigen Ahead/Behind-Stand.")
    ahead, behind = int(counts[0]), int(counts[1])
    dirty = tuple(
        line for line in _git(root, "status", "--porcelain").splitlines() if line.strip()
    )
    return UpdateStatus(
        repo=root,
        branch=branch,
        upstream=upstream,
        current_commit=current_commit,
        target_commit=target_commit,
        current_version=_local_version(root),
        target_version=_target_version(root),
        ahead=ahead,
        behind=behind,
        dirty=dirty,
    )


def _install(repo: Path) -> None:
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-e",
                ".",
                "--disable-pip-version-check",
                "--no-input",
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=300,
            env=os.environ.copy(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise UpdateError(f"Installation fehlgeschlagen: {error}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-5:]
        raise UpdateError("Installation fehlgeschlagen: " + " | ".join(detail))


def _verify(repo: Path) -> None:
    env = os.environ.copy()
    source = str(repo / "src")
    env["PYTHONPATH"] = source + os.pathsep + env.get("PYTHONPATH", "")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "seoboy", "--version"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise UpdateError(f"Smoke-Test fehlgeschlagen: {error}") from error
    if result.returncode != 0:
        raise UpdateError(
            "Smoke-Test fehlgeschlagen: "
            + (result.stderr or result.stdout).strip().splitlines()[-1]
        )


def _rollback(repo: Path, old_commit: str, install: bool) -> None:
    try:
        _git(repo, "reset", "--hard", old_commit)
    except UpdateError as error:
        raise UpdateError(
            f"Rollback auf {old_commit[:10]} fehlgeschlagen: {error}"
        ) from error
    if install:
        try:
            _install(repo)
        except UpdateError as error:
            raise UpdateError(
                f"Rollback auf {old_commit[:10]} installiert, aber Neuinstallation "
                f"fehlgeschlagen: {error}"
            ) from error


def apply_update(
    repo: Path | str | None = None,
    *,
    install: bool = True,
    verify: bool = True,
) -> UpdateResult:
    status = check_for_update(repo)
    if status.dirty:
        raise UpdateError(
            "Der Arbeitsbaum enthält lokale Änderungen. Bitte zuerst committen oder "
            "stashen: " + ", ".join(status.dirty[:5])
        )
    if status.ahead > 0 and status.behind > 0:
        raise UpdateError(
            "Lokaler Branch und Upstream sind divergiert. Bitte manuell zusammenführen."
        )
    if status.behind == 0:
        return UpdateResult(
            status=status,
            updated=False,
            old_commit=status.current_commit,
            new_commit=status.current_commit,
            version=status.current_version,
            installed=False,
            verified=False,
        )
    old_commit = status.current_commit
    try:
        _git(status.repo, "merge", "--ff-only", "@{u}")
    except UpdateError as error:
        raise UpdateError(
            f"Fast-Forward auf {status.upstream} nicht möglich: {error}"
        ) from error
    new_commit = _git(status.repo, "rev-parse", "HEAD")
    version = _local_version(status.repo)
    installed = False
    verified = False
    try:
        if install:
            _install(status.repo)
            installed = True
        if verify:
            _verify(status.repo)
            verified = True
    except UpdateError as error:
        try:
            _rollback(status.repo, old_commit, install=install)
        except UpdateError as rollback_error:
            raise UpdateError(
                f"Update fehlgeschlagen ({error}); Rollback ebenfalls fehlgeschlagen: "
                f"{rollback_error}"
            ) from error
        raise UpdateError(
            f"Update fehlgeschlagen ({error}); Rollback auf {old_commit[:10]} ausgeführt."
        ) from error
    return UpdateResult(
        status=status,
        updated=True,
        old_commit=old_commit,
        new_commit=new_commit,
        version=version,
        installed=installed,
        verified=verified,
    )
