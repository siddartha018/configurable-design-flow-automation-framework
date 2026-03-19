from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from hashlib import sha256

from core.stage import Stage, StageResult


class DfpPowerAnalysisStage(Stage):
    def __init__(self) -> None:
        super().__init__("dfp_power_analysis")

    def run(self, config: dict, *, attempt: int) -> StageResult:
        seed = config.get("seed")
        if seed is None:
            rng = random.Random()
        else:
            material = f"{seed}:{self.name}:{attempt}".encode("utf-8")
            stable_seed = int.from_bytes(sha256(material).digest()[:8], byteorder="big", signed=False)
            rng = random.Random(stable_seed)

        start = datetime.now(timezone.utc)
        duration_target = float(config.get("stage_durations_s", {}).get(self.name, 0.6))
        time.sleep(max(0.0, duration_target))

        failure_rate = float(config.get("failure_rate", 0.0))
        failed = rng.random() < failure_rate

        warning_count = 1 if rng.random() < 0.2 else 0
        error_count = 1 if failed else 0
        status = "FAIL" if failed else "SUCCESS"
        total_power_mw = round(1200.0 + rng.random() * 500.0, 2)
        leakage_power_mw = round(80.0 + rng.random() * 40.0, 2)
        ir_drop_violations = int(rng.random() * 10)
        message = (
            "power analysis failed (simulated)"
            if failed
            else f"power analysis completed; total_power_mw={total_power_mw} leakage_power_mw={leakage_power_mw} ir_drop_violations={ir_drop_violations}"
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

