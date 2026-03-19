from core.flow_graph import FlowGraph, StageSpec


def test_flow_graph_cycle_detection() -> None:
    specs = [
        StageSpec(name="a", depends_on=["c"]),
        StageSpec(name="b", depends_on=["a"]),
        StageSpec(name="c", depends_on=["b"]),
    ]
    try:
        FlowGraph.from_stage_specs(specs)
    except ValueError as e:
        assert "Cycle detected" in str(e)
    else:
        raise AssertionError("Expected cycle detection error")


def test_flow_graph_topo_order() -> None:
    specs = [
        StageSpec(name="synthesis"),
        StageSpec(name="placement", depends_on=["synthesis"]),
        StageSpec(name="timing", depends_on=["placement"]),
    ]
    g = FlowGraph.from_stage_specs(specs)
    assert g.topo_order() == ["synthesis", "placement", "timing"]

