from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple


def _module_from_fqn(fqn: Optional[str]) -> Optional[str]:
    if not isinstance(fqn, str):
        return None
    if "." not in fqn:
        return None
    return fqn.rsplit(".", 1)[0]


def build_module_dependency_graph(resolved_calls: list, repo_prefix: str) -> dict:
    graph: Dict[str, Set[str]] = {}
    prefix = (repo_prefix or "").strip()
    if not prefix:
        return graph

    scoped_prefix = prefix + "."
    for call in resolved_calls:
        caller_fqn = call.get("caller_fqn")
        callee_fqn = call.get("callee_fqn")
        if not caller_fqn or not callee_fqn:
            continue
        if not isinstance(caller_fqn, str) or not isinstance(callee_fqn, str):
            continue
        if not caller_fqn.startswith(scoped_prefix) or not callee_fqn.startswith(scoped_prefix):
            continue

        caller_module = _module_from_fqn(caller_fqn)
        callee_module = _module_from_fqn(callee_fqn)
        if not caller_module or not callee_module:
            continue
        if caller_module == callee_module:
            continue

        graph.setdefault(caller_module, set()).add(callee_module)
        graph.setdefault(callee_module, set())

    return graph


def _normalize_cycle(cycle_path: List[str]) -> Tuple[str, ...]:
    # Input expected as [a, b, c, a]. Convert to core [a, b, c].
    core = cycle_path[:-1]
    if not core:
        return tuple()

    best: Optional[Tuple[str, ...]] = None
    n = len(core)
    for i in range(n):
        rotated = tuple(core[i:] + core[:i])
        if best is None or rotated < best:
            best = rotated

    assert best is not None
    return best + (best[0],)


def find_dependency_cycles(graph: dict, max_cycles: int = 50, max_depth: int = 20) -> list:
    nodes = sorted(graph.keys())
    cycles: List[List[str]] = []
    seen_cycles: Set[Tuple[str, ...]] = set()
    active_stack: List[str] = []
    active_index: Dict[str, int] = {}

    def dfs(node: str) -> bool:
        if len(cycles) >= max_cycles:
            return True
        if len(active_stack) >= max_depth:
            return False

        active_index[node] = len(active_stack)
        active_stack.append(node)

        for nxt in sorted(graph.get(node, set())):
            if len(cycles) >= max_cycles:
                break

            idx = active_index.get(nxt)
            if idx is not None:
                raw_cycle = active_stack[idx:] + [nxt]
                if len(raw_cycle) >= 3:
                    norm = _normalize_cycle(raw_cycle)
                    if norm and norm not in seen_cycles:
                        seen_cycles.add(norm)
                        cycles.append(list(norm))
                        if len(cycles) >= max_cycles:
                            break
                continue

            if len(active_stack) < max_depth:
                stop = dfs(nxt)
                if stop:
                    break

        active_stack.pop()
        active_index.pop(node, None)
        return len(cycles) >= max_cycles

    for start in nodes:
        if len(cycles) >= max_cycles:
            break
        dfs(start)

    return cycles


def compute_dependency_cycle_metrics(resolved_calls: list, repo_prefix: str) -> dict:
    graph = build_module_dependency_graph(resolved_calls, repo_prefix)
    cycles = find_dependency_cycles(graph, max_cycles=50, max_depth=20)
    edge_count = sum(len(targets) for targets in graph.values())

    return {
        "ok": True,
        "repo_prefix": repo_prefix,
        "modules": len(graph),
        "edges": edge_count,
        "cycle_count": len(cycles),
        "cycles": cycles,
    }
