from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from hashlib import sha256

from core.stage import Stage, StageResult


class DftAtpgStage(Stage):
    def __init__(self) -> None:
        super().__init__("dft_atpg")

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
        fault_coverage_pct = round(90.0 + rng.random() * 8.0, 2)
        pattern_count = int(1500 + rng.random() * 600)
        message = (
            "ATPG failed (simulated)"
            if failed
            else f"ATPG completed; fault_coverage_pct={fault_coverage_pct} pattern_count={pattern_count}"
        )

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

