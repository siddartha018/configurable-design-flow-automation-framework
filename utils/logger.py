from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class LineLogger:
    path: Path

    def ensure_parent_dir(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_line(self, message: str) -> None:
        self.ensure_parent_dir()
        with self.path.open("a", encoding="utf-8") as f:
            f.write(f"{iso_utc_now()} {message}\n")

