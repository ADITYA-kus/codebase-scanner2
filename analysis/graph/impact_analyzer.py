from __future__ import annotations

import json
import os
from collections import Counter, defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple


def load_resolved_calls(cache_dir: str) -> List[Dict[str, Any]]:
    path = os.path.join(cache_dir, "resolved_calls.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _load_architecture_metrics(cache_dir: str) -> Dict[str, Any]:
    path = os.path.join(cache_dir, "architecture_metrics.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def build_adjacency(
    resolved_calls: List[Dict[str, Any]],
) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    forward: Dict[str, Set[str]] = defaultdict(set)
    backward: Dict[str, Set[str]] = defaultdict(set)
    for rec in resolved_calls:
        caller = rec.get("caller_fqn")
        callee = rec.get("callee_fqn")
        if not caller or not callee:
            continue
        forward[str(caller)].add(str(callee))
        backward[str(callee)].add(str(caller))
        # ensure keys exist both sides
        forward.setdefault(str(callee), set())
        backward.setdefault(str(caller), set())
    return dict(forward), dict(backward)


def infer_repo_prefix(cache_dir: str) -> str:
    try:
        arch = _load_architecture_metrics(cache_dir)
        value = str(arch.get("repo_prefix") or "").strip()
        if value:
            return value
    except Exception:
        pass
    return ""


def _normalize_rel(path: str) -> str:
    return str(path or "").replace("\\", "/").lstrip("/")


def _looks_like_file_target(target: str) -> bool:
    t = str(target or "")
    if "/" in t or "\\" in t:
        return True
    if t.lower().endswith(".py"):
        return True
    return "." not in t


def resolve_target(
    target: str,
    repo_prefix: str,
    resolved_calls: List[Dict[str, Any]],
    arch_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    symbols = (arch_metrics.get("symbols") or {}) if isinstance(arch_metrics, dict) else {}
    t = str(target or "").strip()
    if not t:
        raise ValueError("target is empty")

    if not _looks_like_file_target(t):
        return {"type": "symbol", "value": t, "start_nodes": [t]}

    target_rel = _normalize_rel(t)
    starts: Set[str] = set()

    for rec in resolved_calls:
        caller = rec.get("caller_fqn")
        file_path = _normalize_rel(rec.get("file", ""))
        if caller and file_path.endswith(target_rel):
            starts.add(str(caller))

    # fallback from architecture symbol locations
    if not starts:
        for fqn, info in symbols.items():
            loc = (info or {}).get("location") or {}
            file_path = _normalize_rel(loc.get("file", ""))
            if file_path.endswith(target_rel):
                starts.add(str(fqn))

    return {"type": "file", "value": target_rel, "start_nodes": sorted(starts)}


def _first_callsite_index(resolved_calls: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    for rec in resolved_calls:
        caller = rec.get("caller_fqn")
        callee = rec.get("callee_fqn")
        file_path = rec.get("file", "")
        line = int(rec.get("line", -1))

        if caller and caller not in idx:
            idx[str(caller)] = {"file": file_path, "line": line}
        if callee and callee not in idx:
            idx[str(callee)] = {"file": file_path, "line": line}
    return idx


def _enrich_node(
    fqn: str,
    distance: int,
    symbols: Dict[str, Any],
    callsite_idx: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    info = symbols.get(fqn) or {}
    loc = (info.get("location") or {}) if isinstance(info, dict) else {}
    fallback = callsite_idx.get(fqn) or {}
    file_path = loc.get("file") or fallback.get("file", "")
    line = int(loc.get("start_line", fallback.get("line", -1)))
    return {
        "fqn": fqn,
        "distance": int(distance),
        "fan_in": int(info.get("fan_in", 0)) if isinstance(info, dict) else 0,
        "fan_out": int(info.get("fan_out", 0)) if isinstance(info, dict) else 0,
        "file": file_path,
        "line": line,
    }


def _traverse(
    starts: List[str],
    adjacency: Dict[str, Set[str]],
    direction: str,
    depth: int,
    max_nodes: int,
) -> Tuple[Dict[str, int], Set[Tuple[str, str]], bool]:
    seen: Set[str] = set(str(s) for s in starts if s)
    dist: Dict[str, int] = {}
    edges: Set[Tuple[str, str]] = set()
    q = deque((str(s), 0) for s in starts if s)
    truncated = False

    while q:
        node, d = q.popleft()
        if d >= depth:
            continue
        neighbors = adjacency.get(node, set())
        for nxt in neighbors:
            nxt = str(nxt)
            # Store canonical edge direction caller->callee
            if direction == "downstream":
                edges.add((node, nxt))
            else:
                edges.add((nxt, node))

            if nxt in seen:
                continue
            nd = d + 1
            seen.add(nxt)
            if nxt not in dist:
                dist[nxt] = nd
            if len(dist) >= max_nodes:
                truncated = True
                break
            q.append((nxt, nd))
        if truncated:
            break
    return dist, edges, truncated


def summarize_impacted_files(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counter: Counter[str] = Counter()
    for n in nodes:
        file_path = str(n.get("file") or "")
        if not file_path:
            continue
        counter[file_path] += 1
    return [
        {"file": file_path, "count": int(count)}
        for file_path, count in sorted(counter.items(), key=lambda x: (-x[1], x[0]))
    ]


def compute_impact(
    cache_dir: str,
    target: str,
    depth: int = 2,
    max_nodes: int = 200,
) -> Dict[str, Any]:
    depth = max(1, int(depth))
    max_nodes = max(1, int(max_nodes))

    resolved_calls = load_resolved_calls(cache_dir)
    arch = _load_architecture_metrics(cache_dir)
    symbols = (arch.get("symbols") or {}) if isinstance(arch, dict) else {}
    repo_prefix = str(arch.get("repo_prefix") or infer_repo_prefix(cache_dir))

    forward, backward = build_adjacency(resolved_calls)
    target_info = resolve_target(
        target=target,
        repo_prefix=repo_prefix,
        resolved_calls=resolved_calls,
        arch_metrics=arch,
    )
    starts = list(target_info.get("start_nodes") or [])

    if not starts:
        return {
            "ok": True,
            "repo_prefix": repo_prefix,
            "target": {"type": target_info.get("type", "symbol"), "value": target_info.get("value", target)},
            "depth": depth,
            "max_nodes": max_nodes,
            "upstream": {"nodes": [], "edges": [], "truncated": False},
            "downstream": {"nodes": [], "edges": [], "truncated": False},
            "impacted_files": {"upstream": [], "downstream": []},
        }

    callsite_idx = _first_callsite_index(resolved_calls)
    up_dist, up_edges, up_truncated = _traverse(starts, backward, "upstream", depth, max_nodes)
    down_dist, down_edges, down_truncated = _traverse(starts, forward, "downstream", depth, max_nodes)

    upstream_nodes = [
        _enrich_node(fqn, d, symbols, callsite_idx)
        for fqn, d in sorted(up_dist.items(), key=lambda x: (x[1], x[0]))
    ]
    downstream_nodes = [
        _enrich_node(fqn, d, symbols, callsite_idx)
        for fqn, d in sorted(down_dist.items(), key=lambda x: (x[1], x[0]))
    ]

    return {
        "ok": True,
        "repo_prefix": repo_prefix,
        "target": {"type": target_info.get("type", "symbol"), "value": target_info.get("value", target)},
        "depth": depth,
        "max_nodes": max_nodes,
        "upstream": {
            "nodes": upstream_nodes,
            "edges": [{"from": a, "to": b} for a, b in sorted(up_edges, key=lambda x: (x[0], x[1]))],
            "truncated": up_truncated,
        },
        "downstream": {
            "nodes": downstream_nodes,
            "edges": [{"from": a, "to": b} for a, b in sorted(down_edges, key=lambda x: (x[0], x[1]))],
            "truncated": down_truncated,
        },
        "impacted_files": {
            "upstream": summarize_impacted_files(upstream_nodes),
            "downstream": summarize_impacted_files(downstream_nodes),
        },
    }
