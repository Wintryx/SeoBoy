from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

from seoboy import cli
from seoboy.infrastructure.update import (
    UpdateError,
    apply_update,
    check_for_update,
    find_repo_root,
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _write_version(repo: Path, version: str) -> None:
    (repo / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""            [project]
            name = "seoboy"
            version = "{version}"
            """
        ),
        encoding="utf-8",
    )


@unittest.skipUnless(shutil.which("git"), "git is required")
class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.remote = self.root / "remote.git"
        self.source = self.root / "source"
        self.work = self.root / "work"
        _git(self.root, "init", "--bare", str(self.remote))
        _git(self.root, "init", "-b", "main", str(self.source))
        for repo in (self.source, self.work):
            if repo.exists():
                _git(repo, "config", "user.name", "SeoBoy Test")
                _git(repo, "config", "user.email", "test@example.invalid")
        _git(self.source, "config", "user.name", "SeoBoy Test")
        _git(self.source, "config", "user.email", "test@example.invalid")
        _write_version(self.source, "0.1.0")
        _git(self.source, "add", "pyproject.toml")
        _git(self.source, "commit", "-m", "Initial version")
        _git(self.source, "remote", "add", "origin", str(self.remote))
        _git(self.source, "push", "-u", "origin", "main")
        _git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        subprocess.run(
            ["git", "clone", str(self.remote), str(self.work)],
            capture_output=True,
            text=True,
            check=True,
        )
        _git(self.work, "config", "user.name", "SeoBoy Test")
        _git(self.work, "config", "user.email", "test@example.invalid")

    def tearDown(self):
        self.tmp.cleanup()

    def _publish_next_version(self) -> None:
        _write_version(self.source, "0.2.0")
        _git(self.source, "add", "pyproject.toml")
        _git(self.source, "commit", "-m", "Next version")
        _git(self.source, "push", "origin", "main")

    def test_check_and_apply_fast_forward(self):
        initial = check_for_update(self.work)
        self.assertEqual(initial.current_version, "0.1.0")
        self.assertEqual(initial.target_version, "0.1.0")
        self.assertEqual(initial.behind, 0)
        self.assertEqual(initial.dirty, ())

        self._publish_next_version()
        available = check_for_update(self.work)
        self.assertEqual(available.current_version, "0.1.0")
        self.assertEqual(available.target_version, "0.2.0")
        self.assertEqual(available.behind, 1)
        self.assertEqual(available.ahead, 0)

        result = apply_update(self.work, install=False, verify=False)
        self.assertTrue(result.updated)
        self.assertEqual(result.version, "0.2.0")
        self.assertNotEqual(result.old_commit, result.new_commit)
        current = check_for_update(self.work)
        self.assertEqual(current.current_version, "0.2.0")
        self.assertEqual(current.behind, 0)

    def test_cli_check_reports_available_version(self):
        self._publish_next_version()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(["update", "--check", "--repo", str(self.work)])
        self.assertEqual(code, 0, stderr.getvalue())
        output = stdout.getvalue()
        self.assertIn("0.1.0 -> 0.2.0", output)
        self.assertIn("Update verfügbar", output)

    def test_local_ahead_is_not_updated(self):
        _write_version(self.work, "0.1.1")
        _git(self.work, "add", "pyproject.toml")
        _git(self.work, "commit", "-m", "Local change")
        status = check_for_update(self.work)
        self.assertEqual(status.ahead, 1)
        self.assertEqual(status.behind, 0)
        result = apply_update(self.work, install=False, verify=False)
        self.assertFalse(result.updated)
        self.assertIn('0.1.1', (self.work / "pyproject.toml").read_text(encoding="utf-8"))

    def test_dirty_tree_blocks_update(self):
        self._publish_next_version()
        (self.work / "notes.txt").write_text("local", encoding="utf-8")
        status = check_for_update(self.work)
        self.assertTrue(status.dirty)
        with self.assertRaises(UpdateError):
            apply_update(self.work, install=False, verify=False)

    def test_missing_upstream_is_reported(self):
        local = self.root / "local-only"
        local.mkdir()
        _git(local, "init", "-b", "main")
        _git(local, "config", "user.name", "SeoBoy Test")
        _git(local, "config", "user.email", "test@example.invalid")
        _write_version(local, "0.1.0")
        _git(local, "add", "pyproject.toml")
        _git(local, "commit", "-m", "Local only")
        with self.assertRaises(UpdateError):
            check_for_update(local)

    def test_find_repo_root(self):
        self.assertEqual(find_repo_root(self.work), self.work.resolve())
        with self.assertRaises(UpdateError):
            find_repo_root(self.root / "missing")


if __name__ == "__main__":
    unittest.main()
