from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from utils.logger import LineLogger
from utils.command_runner import CommandResult, run_command

StageStatus = Literal["SUCCESS", "FAIL"]


@dataclass(frozen=True)
class StageResult:
    stage_name: str
    status: StageStatus
    attempt: int
    start_time: datetime
    end_time: datetime
    duration_s: float
    warning_count: int
    error_count: int
    message: str


class Stage(ABC):
    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def run(self, config: dict, *, attempt: int) -> StageResult:
        raise NotImplementedError

    def execute(self, config: dict, *, attempt: int) -> tuple[StageResult, CommandResult | None]:
        mode = str(config.get("stage_modes", {}).get(self.name, "simulate"))
        if mode == "command":
            command = config.get("stage_commands", {}).get(self.name)
            if not isinstance(command, list) or any(not isinstance(x, str) for x in command):
                raise ValueError(
                    f"stage_commands.{self.name} must be a list of strings when mode=command"
                )
            timeout_s_raw = config.get("stage_timeouts_s", {}).get(self.name)
            timeout_s = float(timeout_s_raw) if timeout_s_raw is not None else None

            env_raw = config.get("stage_env", {}).get(self.name)
            env: dict[str, str] | None
            if env_raw is None:
                env = None
            elif isinstance(env_raw, dict) and all(
                isinstance(k, str) and isinstance(v, str) for k, v in env_raw.items()
            ):
                env = dict(env_raw)
            else:
                raise ValueError(f"stage_env.{self.name} must be a string->string map")

            workdir_raw = config.get("stage_workdirs", {}).get(self.name)
            workdir = str(workdir_raw) if workdir_raw is not None else None

            start_time = datetime.now(timezone.utc)
            cmd_res = run_command(command=command, timeout_s=timeout_s, env=env, cwd=workdir)
            end_time = datetime.now(timezone.utc)
            duration_s = (end_time - start_time).total_seconds()

            status: StageStatus = "SUCCESS" if cmd_res.exit_code == 0 and not cmd_res.timed_out else "FAIL"
            message = "command completed" if status == "SUCCESS" else "command failed"
            result = StageResult(
                stage_name=self.name,
                status=status,
                attempt=attempt,
                start_time=start_time,
                end_time=end_time,
                duration_s=duration_s,
                warning_count=0,
                error_count=0 if status == "SUCCESS" else 1,
                message=message,
            )
            return result, cmd_res

        # default: simulate
        return self.run(config, attempt=attempt), None

    def generate_log(self, result: StageResult, log_path: Path) -> None:
        logger = LineLogger(log_path)
        logger.write_line(f"STAGE: {result.stage_name}")
        logger.write_line(f"ATTEMPT: {result.attempt}")
        logger.write_line(f"STATUS: {result.status}")
        if result.message:
            logger.write_line(f"MESSAGE: {result.message}")
        for _ in range(result.warning_count):
            logger.write_line("WARN: simulated warning")
        for _ in range(result.error_count):
            logger.write_line("ERROR: simulated error")
        logger.write_line(f"RUNTIME_S: {result.duration_s:.6f}")

