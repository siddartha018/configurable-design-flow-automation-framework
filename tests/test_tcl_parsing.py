from __future__ import annotations

import json
from pathlib import Path

from core.flow_engine import FlowEngine


def test_tcl_json_contract_parses(tmp_path: Path) -> None:
    # minimal engine; we only call its internal graph resolver
    engine = FlowEngine(
        logs_dir=tmp_path / "logs",
        reports_dir=tmp_path / "reports",
        parser_exe=Path("/bin/true"),
        tcl_script=Path("tcl/flow.tcl"),
    )
    cfg = {"use_tcl": True, "parallel": False, "retries": 0}
    graph = engine._resolve_graph(cfg)  # noqa: SLF001
    topo = graph.topo_order()
    assert topo[:3] == ["synthesis", "placement", "timing"]


def test_legacy_tcl_output_fallback(tmp_path: Path) -> None:
    # Create a temporary TCL script that prints legacy stage names.
    legacy = tmp_path / "legacy.tcl"
    legacy.write_text("puts synthesis\nputs placement\nputs timing\n", encoding="utf-8")

    engine = FlowEngine(
        logs_dir=tmp_path / "logs",
        reports_dir=tmp_path / "reports",
        parser_exe=Path("/bin/true"),
        tcl_script=legacy,
    )
    cfg = {"use_tcl": True, "parallel": False, "retries": 0}
    graph = engine._resolve_graph(cfg)  # noqa: SLF001
    assert graph.topo_order() == ["synthesis", "placement", "timing"]

