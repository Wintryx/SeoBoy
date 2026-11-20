"""Near-real-time CLI progress events with human and JSON modes."""

from __future__ import annotations

from datetime import datetime
import json
import sys
import time
from typing import Any, TextIO


class ProgressReporter:
    def __init__(
        self,
        mode: str = "auto",
        interval_seconds: float = 2.0,
        stream: TextIO | None = None,
    ) -> None:
        self.stream = stream or sys.stderr
        if mode == "auto":
            self.mode = "human" if getattr(self.stream, "isatty", lambda: False)() else "json"
        else:
            self.mode = mode if mode in {"human", "json", "off"} else "off"
        self.interval = max(0.2, interval_seconds)
        self._last: dict[str, float] = {}
        self._stage_started: dict[str, float] = {}

    def handle(self, payload: dict[str, Any]) -> None:
        self.emit(
            stage=str(payload.get("stage") or "lauf"),
            message=str(payload.get("message") or ""),
            completed=payload.get("completed"),
            total=payload.get("total"),
            unit=payload.get("unit"),
            force=bool(payload.get("force", False)),
        )

    def emit(
        self,
        *,
        stage: str,
        message: str,
        completed: int | float | None = None,
        total: int | float | None = None,
        unit: str | None = None,
        force: bool = False,
    ) -> None:
        if self.mode == "off":
            return
        now = time.monotonic()
        if stage not in self._stage_started:
            self._stage_started[stage] = now
        previous = self._last.get(stage, 0.0)
        if not force and now - previous < self.interval:
            return
        self._last[stage] = now
        elapsed = max(0.0, now - self._stage_started[stage])
        percent = None
        eta_seconds = None
        if isinstance(completed, (int, float)) and isinstance(total, (int, float)) and total > 0:
            percent = round(min(100.0, max(0.0, completed / total * 100)), 1)
            if completed > 0 and completed < total:
                eta_seconds = round(elapsed / completed * (total - completed), 1)
            elif completed >= total:
                eta_seconds = 0.0
        event = {
            "event": "progress",
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "stage": stage,
            "message": message,
            "completed": completed,
            "total": total,
            "unit": unit,
            "percent": percent,
            "elapsed_seconds": round(elapsed, 1),
            "eta_seconds": eta_seconds,
            "eta": _format_duration(eta_seconds) if eta_seconds is not None else None,
        }
        if self.mode == "json":
            self.stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        else:
            stamp = datetime.now().astimezone().strftime("%H:%M:%S")
            detail = f"[{stamp}] {stage}: {message}"
            if percent is not None:
                detail += f" · {completed}/{total} {unit or ''}".rstrip()
                detail += f" · {percent:.1f}%"
            elif completed is not None:
                detail += f" · {completed} {unit or ''}".rstrip()
            if eta_seconds is not None:
                detail += f" · ETA {_format_duration(eta_seconds)}"
            elif elapsed > 0:
                detail += f" · {_format_duration(elapsed)}"
            self.stream.write(detail + "\n")
        self.stream.flush()


def _format_duration(seconds: float) -> str:
    value = max(0, int(seconds))
    minutes, remaining = divmod(value, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}h {minutes:02d}m"
    if minutes:
        return f"{minutes:d}m {remaining:02d}s"
    return f"{remaining:d}s"
