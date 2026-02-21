from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple


def _infer_repo_prefix(symbol_index, callgraph) -> str:
    first_segments: Counter[str] = Counter()

    for sym in symbol_index.all_symbols():
        module = getattr(sym, "module", "") or ""
        if not module:
            continue
        seg = module.split(".", 1)[0]
        if seg:
            first_segments[seg] += 1

    if not first_segments:
        for fqn in callgraph.all_callers() + callgraph.all_callees():
            if not isinstance(fqn, str):
                continue
            if fqn.startswith("builtins.") or fqn.startswith("external::"):
                continue
            seg = fqn.split(".", 1)[0]
            if seg:
                first_segments[seg] += 1

    if not first_segments:
        return ""
    return first_segments.most_common(1)[0][0]


def _kind_for_fqn(fqn: str, repo_prefix: str) -> str:
    if isinstance(fqn, str) and fqn.startswith("builtins."):
        return "builtin"
    if repo_prefix and isinstance(fqn, str) and fqn.startswith(repo_prefix + "."):
        return "local"
    return "external"


def compute_architecture_metrics(
    callgraph,
    symbol_index,
    repo_prefix: Optional[str] = None,
    top_k: int = 25,
    fanout_threshold: int = 10,
    fanin_threshold: int = 10,
) -> dict:
    if repo_prefix is None:
        repo_prefix = _infer_repo_prefix(symbol_index, callgraph)

    # Build symbol/location index from SymbolIndex snapshot in memory.
    symbol_file: Dict[str, str] = {}
    symbol_location: Dict[str, Dict[str, Any]] = {}
    all_nodes: Set[str] = set()

    for sym in symbol_index.all_symbols():
        fqn = f"{sym.module}.{sym.qualified_name}"
        all_nodes.add(fqn)
        symbol_file[fqn] = sym.file_path
        symbol_location[fqn] = {
            "file": sym.file_path,
            "start_line": int(sym.start_line),
            "end_line": int(sym.end_line),
        }

    # Adjacency sets for distinct fan-in/fan-out.
    out_neighbors: Dict[str, Set[str]] = defaultdict(set)
    in_neighbors: Dict[str, Set[str]] = defaultdict(set)

    # File aggregates.
    file_incoming_symbols: Dict[str, Set[str]] = defaultdict(set)
    file_outgoing_symbols: Dict[str, Set[str]] = defaultdict(set)
    file_edges: Dict[str, int] = defaultdict(int)

    # Initialize file buckets for all known local symbol files.
    for fpath in symbol_file.values():
        if fpath:
            file_incoming_symbols.setdefault(fpath, set())
            file_outgoing_symbols.setdefault(fpath, set())
            file_edges.setdefault(fpath, 0)

    # Traverse all callsites once via caller index.
    for caller_fqn in callgraph.all_callers():
        for site in callgraph.callees_of(caller_fqn):
            callee_fqn = site.callee_fqn
            if not callee_fqn:
                raw_name = site.callee_name or "<unknown>"
                callee_fqn = f"external::{raw_name}"

            all_nodes.add(caller_fqn)
            all_nodes.add(callee_fqn)

            out_neighbors[caller_fqn].add(callee_fqn)
            in_neighbors[callee_fqn].add(caller_fqn)

            caller_file = symbol_file.get(caller_fqn) or getattr(site, "file", "")
            if caller_file:
                file_outgoing_symbols[caller_file].add(caller_fqn)
                file_edges[caller_file] += 1

            callee_file = symbol_file.get(callee_fqn)
            if callee_file:
                file_incoming_symbols[callee_file].add(callee_fqn)

    # Ensure every discovered node has adjacency entries.
    for node in all_nodes:
        out_neighbors.setdefault(node, set())
        in_neighbors.setdefault(node, set())

    symbols_payload: Dict[str, Dict[str, Any]] = {}
    local_nodes: List[str] = []
    for fqn in sorted(all_nodes):
        kind = _kind_for_fqn(fqn, repo_prefix or "")
        fan_in = len(in_neighbors.get(fqn, set()))
        fan_out = len(out_neighbors.get(fqn, set()))
        if kind == "local":
            local_nodes.append(fqn)

        symbols_payload[fqn] = {
            "fan_in": fan_in,
            "fan_out": fan_out,
            "kind": kind,
            "location": symbol_location.get(
                fqn,
                {"file": "", "start_line": -1, "end_line": -1},
            ),
        }

    dead_symbols = [
        fqn
        for fqn in local_nodes
        if symbols_payload[fqn]["fan_in"] == 0 and not fqn.endswith(".<module>")
    ]
    dead_symbols.sort()

    orchestrators = [
        fqn for fqn in local_nodes if symbols_payload[fqn]["fan_out"] >= int(fanout_threshold)
    ]
    orchestrators.sort(key=lambda x: (-symbols_payload[x]["fan_out"], x))

    critical_symbols = [
        fqn for fqn in local_nodes if symbols_payload[fqn]["fan_in"] >= int(fanin_threshold)
    ]
    critical_symbols.sort(key=lambda x: (-symbols_payload[x]["fan_in"], x))

    top_fan_in_candidates: List[Tuple[str, int]] = [
        (fqn, symbols_payload[fqn]["fan_in"]) for fqn in local_nodes
    ]
    top_fan_out_candidates: List[Tuple[str, int]] = [
        (fqn, symbols_payload[fqn]["fan_out"]) for fqn in local_nodes
    ]
    top_fan_in_candidates.sort(key=lambda x: (-x[1], x[0]))
    top_fan_out_candidates.sort(key=lambda x: (-x[1], x[0]))

    top_fan_in = [
        {"fqn": fqn, "fan_in": score} for fqn, score in top_fan_in_candidates[: int(top_k)]
    ]
    top_fan_out = [
        {"fqn": fqn, "fan_out": score} for fqn, score in top_fan_out_candidates[: int(top_k)]
    ]

    files_payload: Dict[str, Dict[str, int]] = {}
    for file_path in sorted(set(file_edges.keys()) | set(file_incoming_symbols.keys()) | set(file_outgoing_symbols.keys())):
        files_payload[file_path] = {
            "incoming_symbols": len(file_incoming_symbols.get(file_path, set())),
            "outgoing_symbols": len(file_outgoing_symbols.get(file_path, set())),
            "edges": int(file_edges.get(file_path, 0)),
        }

    return {
        "ok": True,
        "repo_prefix": repo_prefix or "",
        "repo": {
            "total_nodes": len(all_nodes),
            "dead_symbols": dead_symbols,
            "orchestrators": orchestrators[: int(top_k)],
            "critical_symbols": critical_symbols[: int(top_k)],
            "top_fan_in": top_fan_in,
            "top_fan_out": top_fan_out,
        },
        "symbols": symbols_payload,
        "files": files_payload,
        "thresholds": {
            "fanout_threshold": int(fanout_threshold),
            "fanin_threshold": int(fanin_threshold),
            "top_k": int(top_k),
        },
    }
