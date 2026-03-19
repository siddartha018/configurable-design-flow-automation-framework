from __future__ import annotations

import argparse
import copy
from pathlib import Path

from core.flow_engine import FlowEngine, FlowRunResult


def _merge_variant(base: dict, variant: dict) -> dict:
    merged = copy.deepcopy(base)
    for k, v in variant.items():
        merged[k] = v
    return merged


def _score(result: FlowRunResult) -> tuple[int, int, float]:
    return (result.total_errors, result.total_warnings, result.total_runtime_s)


def write_report(*, report_path: Path, results: list[FlowRunResult]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    best = min(results, key=_score)

    lines: list[str] = []
    lines.append("Configurable Design Flow Automation Framework Report")
    lines.append("")
    for r in results:
        lines.append(f"== Run: {r.config_name} ==")
        lines.append(f"Total runtime (s): {r.total_runtime_s:.3f}")
        lines.append(f"Total warnings: {r.total_warnings}")
        lines.append(f"Total errors: {r.total_errors}")
        lines.append("Per-stage:")
        for e in r.stage_executions:
            fr = e.final_result
            prefix = "SKIPPED" if getattr(e, "skipped", False) else "EXEC"
            reason = f" reason={e.skip_reason}" if getattr(e, "skipped", False) and e.skip_reason else ""
            lines.append(
                f"- {e.stage_name}: {prefix}{reason} status={fr.status} attempts={e.attempts} "
                f"runtime_s={fr.duration_s:.3f} warnings={e.parsed_metrics.warnings} "
                f"errors={e.parsed_metrics.errors}"
            )
        lines.append("")

    lines.append(
        f"BEST CONFIG: {best.config_name} (errors={best.total_errors}, "
        f"warnings={best.total_warnings}, runtime_s={best.total_runtime_s:.3f})"
    )
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")


def next_report_path(reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, 10_000):
        candidate = reports_dir / f"report_{i:03d}.txt"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Too many reports; clean up reports/ directory")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to JSON config")
    parser.add_argument("--dry-run", action="store_true", help="Print planned DAG execution and exit")
    parser.add_argument("--resume", action="store_true", help="Skip stages with matching checkpoint metadata")
    parser.add_argument("--max-workers", type=int, default=None, help="Cap parallel workers")
    parser.add_argument("--only", dest="only", default=None, help="Run only this stage (and required deps)")
    parser.add_argument("--from", dest="from_stage", default=None, help="Start execution from this stage")
    parser.add_argument("--until", dest="until_stage", default=None, help="Stop execution after this stage")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    config_path = (root / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config)

    logs_dir = root / "logs"
    reports_dir = root / "reports"
    parser_exe = root / "cpp" / "log_parser"
    tcl_script = root / "tcl" / "flow.tcl"

    engine = FlowEngine(
        logs_dir=logs_dir,
        reports_dir=reports_dir,
        parser_exe=parser_exe,
        tcl_script=tcl_script,
    )
    base_config = engine.load_config(config_path)

    variants = base_config.get("variants")
    results: list[FlowRunResult] = []
    if isinstance(variants, list) and variants:
        for i, v in enumerate(variants):
            if not isinstance(v, dict):
                raise ValueError("Each variants[] entry must be an object")
            cfg = _merge_variant(base_config, v)
            name = str(v.get("name") or f"variant_{i}")
            results.append(
                engine.run_once(
                    config=cfg,
                    config_name=name,
                    only=args.only,
                    from_stage=args.from_stage,
                    until_stage=args.until_stage,
                    resume=True if args.resume else None,
                    max_workers=args.max_workers,
                    dry_run=args.dry_run,
                )
            )
    else:
        results.append(
            engine.run_once(
                config=base_config,
                config_name=str(base_config.get("name") or "default"),
                only=args.only,
                from_stage=args.from_stage,
                until_stage=args.until_stage,
                resume=True if args.resume else None,
                max_workers=args.max_workers,
                dry_run=args.dry_run,
            )
        )

    report_path = next_report_path(reports_dir)
    write_report(report_path=report_path, results=results)
    print(f"Wrote report to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

