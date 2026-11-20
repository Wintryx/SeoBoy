"""Exklusive Betriebssystem-Sperre je Projektdatenbank."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from typing import Iterator


class LockError(RuntimeError):
    """Ein anderer Prozess hält bereits die Sperre für diese Datenbank."""


@contextmanager
def database_lock(database_path: Path | str) -> Iterator[None]:
    target = Path(database_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(target.name + ".lock")
    handle = open(lock_path, "a+b")  # noqa: SIM115
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"seoboy-lock\n")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise LockError(
                f"Die Datenbank wird bereits von einem anderen SeoBoy-Prozess verwendet: {target}"
            ) from error
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()
