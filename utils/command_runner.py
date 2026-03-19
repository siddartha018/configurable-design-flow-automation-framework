from __future__ import annotations

from dataclasses import dataclass
from subprocess import CalledProcessError, TimeoutExpired, run


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


def run_command(
    *,
    command: list[str],
    timeout_s: float | None,
    env: dict[str, str] | None,
    cwd: str | None,
) -> CommandResult:
    try:
        proc = run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
            cwd=cwd,
            check=False,
        )
        return CommandResult(
            command=command,
            exit_code=int(proc.returncode),
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            timed_out=False,
        )
    except TimeoutExpired as e:
        return CommandResult(
            command=command,
            exit_code=124,
            stdout=(e.stdout or "") if isinstance(e.stdout, str) else "",
            stderr=(e.stderr or "") if isinstance(e.stderr, str) else "",
            timed_out=True,
        )
    except CalledProcessError as e:
        return CommandResult(
            command=command,
            exit_code=int(e.returncode),
            stdout=e.stdout or "",
            stderr=e.stderr or "",
            timed_out=False,
        )

