from __future__ import annotations

import json
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from subprocess import CalledProcessError, run

from core.flow_graph import FlowGraph, StageSpec
from core.stage import Stage, StageResult
from stages.placement import PlacementStage
from stages.synthesis import SynthesisStage
from stages.timing import TimingStage
from stages.dft_atpg import DftAtpgStage
from stages.dft_scan_insertion import DftScanInsertionStage
from stages.dfp_power_analysis import DfpPowerAnalysisStage
from stages.dfp_power_intent import DfpPowerIntentStage
from utils.parser_interface import ParsedMetrics, parse_log_with_cpp
from utils.structured_log import (
    StageMeta,
    append_jsonl,
    read_last_jsonl_record,
    read_meta,
    write_meta,
)


@dataclass(frozen=True)
class StageExecution:
    stage_name: str
    skipped: bool
    skip_reason: str | None
    attempts: int
    final_result: StageResult
    parsed_metrics: ParsedMetrics
    log_path: Path


@dataclass(frozen=True)
class FlowRunResult:
    config_name: str
    stage_executions: list[StageExecution]
    total_runtime_s: float
    total_warnings: int
    total_errors: int


class FlowEngine:
    def __init__(
        self,
        *,
        logs_dir: Path,
        reports_dir: Path,
        parser_exe: Path,
        tcl_script: Path,
    ) -> None:
        self.logs_dir = logs_dir
        self.reports_dir = reports_dir
        self.parser_exe = parser_exe
        self.tcl_script = tcl_script
        self._stage_registry: dict[str, Stage] = {
            "synthesis": SynthesisStage(),
            "placement": PlacementStage(),
            "timing": TimingStage(),
            "dft_scan_insertion": DftScanInsertionStage(),
            "dft_atpg": DftAtpgStage(),
            "dfp_power_intent": DfpPowerIntentStage(),
            "dfp_power_analysis": DfpPowerAnalysisStage(),
        }

    @staticmethod
    def load_config(path: Path) -> dict:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Config must be a JSON object")
        return data

    def _resolve_graph(self, config: dict) -> FlowGraph:
        use_tcl = bool(config.get("use_tcl", False))
        if use_tcl:
            try:
                proc = run(
                    ["tclsh", str(self.tcl_script)],
                    capture_output=True,
                    text=True,
                    check=True,
                    env={**os.environ},
                )
            except CalledProcessError as e:
                stderr = (e.stderr or "").strip()
                raise RuntimeError(f"TCL flow script failed: {stderr}") from e
            stdout = (proc.stdout or "").strip()
            if not stdout:
                raise ValueError("TCL flow script produced no output")

            # Prefer structured JSON; fallback to legacy one-name-per-line.
            specs: list[StageSpec]
            if stdout.lstrip().startswith("{"):
                payload = json.loads(stdout)
                if not isinstance(payload, dict) or "stages" not in payload:
                    raise ValueError("TCL JSON must be an object with a 'stages' field")
                stages_val = payload["stages"]
                if not isinstance(stages_val, list) or not stages_val:
                    raise ValueError("TCL JSON 'stages' must be a non-empty array")
                specs = []
                for entry in stages_val:
                    if not isinstance(entry, dict):
                        raise ValueError("Each TCL JSON stages[] entry must be an object")
                    name = entry.get("name")
                    depends_on = entry.get("depends_on", [])
                    if not isinstance(name, str) or not name:
                        raise ValueError("Each TCL JSON stage must have a non-empty string 'name'")
                    if not isinstance(depends_on, list) or any(not isinstance(d, str) for d in depends_on):
                        raise ValueError(f"Stage {name} has invalid depends_on; must be list[str]")
                    specs.append(StageSpec(name=name, depends_on=list(depends_on)))
            else:
                stage_names = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
                specs = [StageSpec(name=n) for n in stage_names]
        else:
            graph = config.get("graph")
            if not isinstance(graph, dict):
                raise ValueError("Config must include 'graph' object when use_tcl is false")
            stages_val = graph.get("stages")
            if not isinstance(stages_val, list) or not stages_val:
                raise ValueError("Config graph.stages must be a non-empty array")
            specs = []
            for entry in stages_val:
                if not isinstance(entry, dict):
                    raise ValueError("Each graph.stages[] entry must be an object")
                name = entry.get("name")
                depends_on = entry.get("depends_on", [])
                if not isinstance(name, str) or not name:
                    raise ValueError("Each graph stage must have a non-empty string 'name'")
                if not isinstance(depends_on, list) or any(not isinstance(d, str) for d in depends_on):
                    raise ValueError(f"Stage {name} has invalid depends_on; must be list[str]")
                specs.append(StageSpec(name=name, depends_on=list(depends_on)))

        flow_graph = FlowGraph.from_stage_specs(specs)
        unknown = [s for s in flow_graph.stages if s not in self._stage_registry]
        if unknown:
            raise ValueError(f"Unknown stages: {unknown}. Known: {sorted(self._stage_registry)}")
        return flow_graph

    def _run_stage_with_retries(
        self, *, stage: Stage, config: dict, retries: int, run_logs_dir: Path
    ) -> StageExecution:
        attempts = 0
        last_result: StageResult | None = None
        log_path = run_logs_dir / f"{stage.name}.log"
        jsonl_path = run_logs_dir / f"{stage.name}.jsonl"
        meta_path = run_logs_dir / f"{stage.name}.meta.json"
        # overwrite per run
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.exists():
            log_path.unlink()
        if jsonl_path.exists():
            jsonl_path.unlink()

        for attempt in range(1, retries + 2):
            attempts = attempt
            result, cmd_res = stage.execute(config, attempt=attempt)
            stage.generate_log(result, log_path)
            if cmd_res is not None:
                # Write command output into the same text log for CAD-like debuggability.
                from utils.logger import LineLogger

                logger = LineLogger(log_path)
                logger.write_line(f"CMD: {' '.join(cmd_res.command)}")
                logger.write_line(f"CMD_EXIT: {cmd_res.exit_code}")
                logger.write_line(f"CMD_TIMEOUT: {str(cmd_res.timed_out).lower()}")
                if cmd_res.stdout.strip():
                    for ln in cmd_res.stdout.splitlines():
                        logger.write_line(f"CMD_STDOUT: {ln}")
                if cmd_res.stderr.strip():
                    for ln in cmd_res.stderr.splitlines():
                        logger.write_line(f"CMD_STDERR: {ln}")

            record: dict[str, object] = {
                "stage": result.stage_name,
                "attempt": result.attempt,
                "status": result.status,
                "start_time": result.start_time.isoformat(),
                "end_time": result.end_time.isoformat(),
                "duration_s": result.duration_s,
                "warnings": result.warning_count,
                "errors": result.error_count,
                "message": result.message,
            }
            if cmd_res is not None:
                record["command"] = cmd_res.command
                record["exit_code"] = cmd_res.exit_code
                record["timed_out"] = cmd_res.timed_out
            append_jsonl(jsonl_path, record)
            last_result = result
            if result.status == "SUCCESS":
                break

        if last_result is None:
            raise RuntimeError(f"Stage {stage.name} produced no result")

        metrics = parse_log_with_cpp(log_path=log_path, parser_exe=self.parser_exe)

        signature = self._stage_signature(stage_name=stage.name, config=config)
        write_meta(
            meta_path,
            StageMeta(stage_name=stage.name, signature=signature, updated_at=datetime.now(timezone.utc)),
        )
        return StageExecution(
            stage_name=stage.name,
            skipped=False,
            skip_reason=None,
            attempts=attempts,
            final_result=last_result,
            parsed_metrics=metrics,
            log_path=log_path,
        )

    @staticmethod
    def _stage_signature(*, stage_name: str, config: dict) -> str:
        signature_material = json.dumps(config, sort_keys=True, default=str).encode("utf-8")
        return sha256(signature_material + stage_name.encode("utf-8")).hexdigest()

    @staticmethod
    def _apply_filters(
        *, graph: FlowGraph, only: str | None, from_stage: str | None, until_stage: str | None
    ) -> FlowGraph:
        if only and (from_stage or until_stage):
            raise ValueError("Use either --only or --from/--until, not both")

        topo = graph.topo_order()

        def deps_closure(name: str, acc: set[str]) -> None:
            for dep in graph.stages[name].depends_on:
                if dep not in acc:
                    acc.add(dep)
                    deps_closure(dep, acc)

        selected: set[str]
        if only:
            if only not in graph.stages:
                raise ValueError(f"--only stage not in graph: {only}")
            selected = {only}
            deps_closure(only, selected)
        else:
            if from_stage and from_stage not in graph.stages:
                raise ValueError(f"--from stage not in graph: {from_stage}")
            if until_stage and until_stage not in graph.stages:
                raise ValueError(f"--until stage not in graph: {until_stage}")
            start_idx = topo.index(from_stage) if from_stage else 0
            end_idx = topo.index(until_stage) if until_stage else (len(topo) - 1)
            if start_idx > end_idx:
                raise ValueError("--from must appear before --until in topological order")
            selected = set(topo[start_idx : end_idx + 1])
            for n in list(selected):
                deps_closure(n, selected)

        specs = [graph.stages[n] for n in topo if n in selected]
        return FlowGraph.from_stage_specs(specs)

    def run_once(
        self,
        *,
        config: dict,
        config_name: str,
        only: str | None = None,
        from_stage: str | None = None,
        until_stage: str | None = None,
        resume: bool | None = None,
        max_workers: int | None = None,
        dry_run: bool = False,
    ) -> FlowRunResult:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        run_logs_dir = self.logs_dir / config_name
        run_logs_dir.mkdir(parents=True, exist_ok=True)

        parallel = bool(config.get("parallel", False))
        retries_raw = config.get("retries", 0)
        if not isinstance(retries_raw, int) or retries_raw < 0:
            raise ValueError("Config field 'retries' must be a non-negative integer")
        retries = retries_raw

        graph = self._resolve_graph(config)
        graph = self._apply_filters(graph=graph, only=only, from_stage=from_stage, until_stage=until_stage)
        stage_names = list(graph.stages.keys())
        # Resume is CLI-controlled only: default off unless explicitly enabled.
        resume_effective = False if resume is None else resume

        if dry_run:
            topo = graph.topo_order()
            print(f"[dry-run] config={config_name} stages={topo}")
            for n in topo:
                deps = graph.stages[n].depends_on
                if deps:
                    print(f"[dry-run]   {n} depends_on={deps}")
            return FlowRunResult(
                config_name=config_name,
                stage_executions=[],
                total_runtime_s=0.0,
                total_warnings=0,
                total_errors=0,
            )

        t0 = time.perf_counter()
        executions: list[StageExecution] = []

        # DAG scheduler with failure propagation.
        completed_ok: set[str] = set()
        failed: set[str] = set()
        skipped: set[str] = set()

        pending: set[str] = set(stage_names)
        running: dict[Future[StageExecution], str] = {}

        def deps_satisfied(name: str) -> bool:
            deps = graph.stages[name].depends_on
            return all(d in completed_ok for d in deps)

        def deps_failed(name: str) -> list[str]:
            deps = graph.stages[name].depends_on
            return [d for d in deps if d in failed or d in skipped]

        cap = 1 if not parallel else (max_workers if max_workers is not None else 32)
        max_workers_effective = min(cap, len(stage_names) or 1) if parallel else 1
        with ThreadPoolExecutor(max_workers=max_workers_effective) as ex:
            while pending or running:
                # enqueue ready stages
                made_progress = False
                for name in list(pending):
                    bad_deps = deps_failed(name)
                    if bad_deps:
                        # Skip due to upstream failure.
                        stage = self._stage_registry[name]
                        log_path = run_logs_dir / f"{stage.name}.log"
                        log_path.parent.mkdir(parents=True, exist_ok=True)
                        if log_path.exists():
                            log_path.unlink()
                        # create minimal log so parser doesn't crash in later steps (still parseable)
                        # Note: metrics will show 0 warnings/errors/runtime.
                        now = datetime.now(timezone.utc)
                        dummy = StageResult(
                            stage_name=stage.name,
                            status="FAIL",
                            attempt=0,
                            start_time=now,
                            end_time=now,
                            duration_s=0.0,
                            warning_count=0,
                            error_count=0,
                            message=f"skipped due to failed dependencies: {bad_deps}",
                        )
                        stage.generate_log(dummy, log_path)
                        metrics = parse_log_with_cpp(log_path=log_path, parser_exe=self.parser_exe)
                        executions.append(
                            StageExecution(
                                stage_name=stage.name,
                                skipped=True,
                                skip_reason=f"deps_failed:{','.join(bad_deps)}",
                                attempts=0,
                                final_result=dummy,
                                parsed_metrics=metrics,
                                log_path=log_path,
                            )
                        )
                        pending.remove(name)
                        skipped.add(name)
                        made_progress = True
                        continue

                    if deps_satisfied(name):
                        stage = self._stage_registry[name]
                        if resume_effective:
                            log_path = run_logs_dir / f"{stage.name}.log"
                            jsonl_path = run_logs_dir / f"{stage.name}.jsonl"
                            meta_path = run_logs_dir / f"{stage.name}.meta.json"
                            meta = read_meta(meta_path)
                            current_sig = self._stage_signature(stage_name=stage.name, config=config)
                            if (
                                meta is not None
                                and meta.signature == current_sig
                                and log_path.exists()
                                and jsonl_path.exists()
                            ):
                                last = read_last_jsonl_record(jsonl_path)
                                if last is not None:
                                    try:
                                        start_time = datetime.fromisoformat(str(last["start_time"]))
                                        end_time = datetime.fromisoformat(str(last["end_time"]))
                                        status = str(last["status"])
                                        attempt = int(last["attempt"])
                                        duration_s = float(last["duration_s"])
                                        warnings = int(last.get("warnings", 0))
                                        errors = int(last.get("errors", 0))
                                        message = str(last.get("message", "resumed"))
                                    except Exception:
                                        # If JSONL is malformed, fall back to executing stage.
                                        pass
                                    else:
                                        result = StageResult(
                                            stage_name=stage.name,
                                            status="SUCCESS" if status == "SUCCESS" else "FAIL",
                                            attempt=attempt,
                                            start_time=start_time,
                                            end_time=end_time,
                                            duration_s=duration_s,
                                            warning_count=warnings,
                                            error_count=errors,
                                            message=message,
                                        )
                                        metrics = parse_log_with_cpp(log_path=log_path, parser_exe=self.parser_exe)
                                        executions.append(
                                            StageExecution(
                                                stage_name=stage.name,
                                                skipped=True,
                                                skip_reason="resume",
                                                attempts=0,
                                                final_result=result,
                                                parsed_metrics=metrics,
                                                log_path=log_path,
                                            )
                                        )
                                        pending.remove(name)
                                        completed_ok.add(name) if result.status == "SUCCESS" else failed.add(name)
                                        made_progress = True
                                        continue

                        fut = ex.submit(
                            self._run_stage_with_retries,
                            stage=stage,
                            config=config,
                            retries=retries,
                            run_logs_dir=run_logs_dir,
                        )
                        running[fut] = name
                        pending.remove(name)
                        made_progress = True

                if running:
                    done, _ = wait(running.keys(), timeout=0.05, return_when="FIRST_COMPLETED")
                    for fut in done:
                        name = running.pop(fut)
                        exec_result = fut.result()
                        executions.append(exec_result)
                        if exec_result.final_result.status == "SUCCESS":
                            completed_ok.add(name)
                        else:
                            failed.add(name)
                        made_progress = True

                if not made_progress and pending and not running:
                    # Should not happen if graph is valid; indicates deadlock.
                    raise RuntimeError("Scheduler deadlocked; check graph dependencies")

        # preserve a stable order for reporting: topological order, then any remaining
        topo = graph.topo_order()
        order_index = {n: i for i, n in enumerate(topo)}
        executions.sort(key=lambda e: order_index.get(e.stage_name, 10**9))

        total_runtime_s = time.perf_counter() - t0
        total_warnings = sum(e.parsed_metrics.warnings for e in executions)
        total_errors = sum(e.parsed_metrics.errors for e in executions)
        return FlowRunResult(
            config_name=config_name,
            stage_executions=executions,
            total_runtime_s=total_runtime_s,
            total_warnings=total_warnings,
            total_errors=total_errors,
        )

