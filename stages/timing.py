from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from hashlib import sha256

from core.stage import Stage, StageResult


class TimingStage(Stage):
    def __init__(self) -> None:
        super().__init__("timing")

    def run(self, config: dict, *, attempt: int) -> StageResult:
        seed = config.get("seed")
        if seed is None:
            rng = random.Random()
        else:
            material = f"{seed}:{self.name}:{attempt}".encode("utf-8")
            stable_seed = int.from_bytes(sha256(material).digest()[:8], byteorder="big", signed=False)
            rng = random.Random(stable_seed)

        start = datetime.now(timezone.utc)
        duration_target = float(config.get("stage_durations_s", {}).get(self.name, 0.5))
        time.sleep(max(0.0, duration_target))

        failure_rate = float(config.get("failure_rate", 0.0))
        failed = rng.random() < failure_rate

        warning_count = 1 if rng.random() < 0.25 else 0
        error_count = 1 if failed else 0
        status = "FAIL" if failed else "SUCCESS"
        message = "timing failed (simulated)" if failed else "timing completed"

        end = datetime.now(timezone.utc)
        duration_s = (end - start).total_seconds()
        return StageResult(
            stage_name=self.name,
            status=status,
            attempt=attempt,
            start_time=start,
            end_time=end,
            duration_s=duration_s,
            warning_count=warning_count,
            error_count=error_count,
            message=message,
        )

