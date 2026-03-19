from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterable, Literal

StageMode = Literal["simulate", "command"]


@dataclass(frozen=True)
class StageSpec:
    name: str
    depends_on: list[str] = field(default_factory=list)
    mode: StageMode = "simulate"
    command: list[str] | None = None
    timeout_s: float | None = None
    env: dict[str, str] | None = None
    workdir: str | None = None
    outputs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FlowGraph:
    stages: dict[str, StageSpec]

    @staticmethod
    def from_stage_specs(specs: Iterable[StageSpec]) -> "FlowGraph":
        stages: dict[str, StageSpec] = {}
        for spec in specs:
            if spec.name in stages:
                raise ValueError(f"Duplicate stage name: {spec.name}")
            stages[spec.name] = spec
        graph = FlowGraph(stages=stages)
        graph.validate()
        return graph

    def validate(self) -> None:
        if not self.stages:
            raise ValueError("FlowGraph must contain at least one stage")

        # deps exist
        for name, spec in self.stages.items():
            for dep in spec.depends_on:
                if dep not in self.stages:
                    raise ValueError(f"Stage {name} depends on unknown stage: {dep}")

        # cycle detection (DFS colors)
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {k: WHITE for k in self.stages}

        def dfs(n: str, stack: list[str]) -> None:
            color[n] = GRAY
            stack.append(n)
            for dep in self.stages[n].depends_on:
                if color[dep] == WHITE:
                    dfs(dep, stack)
                elif color[dep] == GRAY:
                    cycle_start = stack.index(dep)
                    cycle = stack[cycle_start:] + [dep]
                    raise ValueError(f"Cycle detected: {' -> '.join(cycle)}")
            stack.pop()
            color[n] = BLACK

        for n in self.stages:
            if color[n] == WHITE:
                dfs(n, [])

    def topo_order(self) -> list[str]:
        # Kahn’s algorithm
        indeg: dict[str, int] = {n: 0 for n in self.stages}
        for n, spec in self.stages.items():
            for dep in spec.depends_on:
                indeg[n] += 1

        ready = deque([n for n, d in indeg.items() if d == 0])
        order: list[str] = []
        while ready:
            n = ready.popleft()
            order.append(n)
            for child, spec in self.stages.items():
                if n in spec.depends_on:
                    indeg[child] -= 1
                    if indeg[child] == 0:
                        ready.append(child)
        if len(order) != len(self.stages):
            raise ValueError("Topological ordering failed (graph may contain a cycle)")
        return order

