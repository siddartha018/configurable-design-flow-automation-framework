from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from subprocess import CalledProcessError, run


@dataclass(frozen=True)
class ParsedMetrics:
    warnings: int
    errors: int
    runtime_s: float


def parse_log_with_cpp(*, log_path: Path, parser_exe: Path) -> ParsedMetrics:
    if not parser_exe.exists():
        raise FileNotFoundError(
            f"C++ log parser not found at {parser_exe}. Compile it first (see README)."
        )
    if not log_path.exists():
        raise FileNotFoundError(f"Log file not found: {log_path}")

    try:
        proc = run(
            [str(parser_exe), str(log_path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        raise RuntimeError(f"log parser failed for {log_path}: {stderr}") from e

    warnings: int | None = None
    errors: int | None = None
    runtime_s: float | None = None

    for raw_line in (proc.stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("warnings="):
            warnings = int(line.split("=", 1)[1])
        elif line.startswith("errors="):
            errors = int(line.split("=", 1)[1])
        elif line.startswith("runtime_s="):
            runtime_s = float(line.split("=", 1)[1])

    if warnings is None or errors is None or runtime_s is None:
        raise RuntimeError(f"Unexpected parser output for {log_path}: {proc.stdout!r}")

    return ParsedMetrics(warnings=warnings, errors=errors, runtime_s=runtime_s)

