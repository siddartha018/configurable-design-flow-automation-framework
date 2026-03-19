from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")

def read_last_jsonl_record(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    last: str | None = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                last = line
    if last is None:
        return None
    obj = json.loads(last)
    if not isinstance(obj, dict):
        return None
    return obj


@dataclass(frozen=True)
class StageMeta:
    stage_name: str
    signature: str
    updated_at: datetime

    def to_json(self) -> dict[str, Any]:
        return {
            "stage_name": self.stage_name,
            "signature": self.signature,
            "updated_at": self.updated_at.isoformat(),
        }


def write_meta(path: Path, meta: StageMeta) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta.to_json(), sort_keys=True, indent=2) + "\n", encoding="utf-8")


def read_meta(path: Path) -> StageMeta | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    stage_name = raw.get("stage_name")
    signature = raw.get("signature")
    updated_at = raw.get("updated_at")
    if not isinstance(stage_name, str) or not isinstance(signature, str) or not isinstance(updated_at, str):
        return None
    try:
        dt = datetime.fromisoformat(updated_at)
    except ValueError:
        return None
    return StageMeta(stage_name=stage_name, signature=signature, updated_at=dt)

