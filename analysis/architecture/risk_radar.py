from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _percentile_90(values: List[int], floor: int) -> int:
    if not values:
        return floor
    ordered = sorted(values)
    rank = max(0, math.ceil(0.9 * len(ordered)) - 1)
    return max(floor, int(ordered[rank]))


def _risk_band(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def _clamp_score(score: int) -> int:
    return max(0, min(100, int(score)))


def _repo_health_from_metrics(
    hotspots: List[Dict[str, Any]],
    risky_files: List[Dict[str, Any]],
    dead_symbols: List[str],
    cycle_count: int,
    unresolved_ratio: float,
) -> Dict[str, Any]:
    return {
        "hotspot_symbols": len(hotspots),
        "risky_files": len(risky_files),
        "dead_symbols": len(dead_symbols),
        "dependency_cycles": int(cycle_count),
        "unresolved_ratio": round(float(unresolved_ratio), 4),
    }


def _symbol_location(symbol_info: Dict[str, Any]) -> Dict[str, Any]:
    loc = symbol_info.get("location") or {}
    return {
        "file": loc.get("file", ""),
        "start_line": _to_int(loc.get("start_line", -1), -1),
        "end_line": _to_int(loc.get("end_line", -1), -1),
    }


def _short_targets(items: List[str], limit: int = 3) -> List[str]:
    return [str(x) for x in items[:limit] if x]


def _compute_refactor_targets(
    hotspots: List[Dict[str, Any]],
    high_fan_in: List[Tuple[str, int]],
    high_fan_out: List[Tuple[str, int]],
    unresolved_ratio: float,
    cycle_count: int,
    cycles: List[List[str]],
) -> List[Dict[str, Any]]:
    targets: List[Dict[str, Any]] = []

    if high_fan_out:
        targets.append(
            {
                "title": "Break down top orchestrator",
                "why": "High fan-out symbols coordinate many calls and are harder to maintain.",
                "targets": _short_targets([fqn for fqn, _ in high_fan_out], limit=3),
            }
        )

    if high_fan_in:
        targets.append(
            {
                "title": "Stabilize critical API",
                "why": "High fan-in symbols are dependency hubs and can cause broad regressions.",
                "targets": _short_targets([fqn for fqn, _ in high_fan_in], limit=3),
            }
        )

    module_hotspots = [h["fqn"] for h in hotspots if "module_level" in (h.get("flags") or [])]
    if module_hotspots:
        targets.append(
            {
                "title": "Reduce script-level work",
                "why": "Module-level orchestration is harder to test and reuse than function boundaries.",
                "targets": _short_targets(module_hotspots, limit=3),
            }
        )

    if unresolved_ratio > 0.2:
        targets.append(
            {
                "title": "Investigate unresolved calls",
                "why": "High unresolved ratio reduces confidence in call graph completeness.",
                "targets": ["unresolved_calls"],
            }
        )

    if cycle_count > 0:
        cycle_targets = [" -> ".join(cycle[:4]) for cycle in cycles[:2] if cycle]
        targets.append(
            {
                "title": "Address dependency cycles",
                "why": "Cycles increase coupling and make module boundaries fragile.",
                "targets": cycle_targets or ["dependency_cycles"],
            }
        )

    # Keep output concise and bounded.
    return targets[:6]


def compute_risk_radar(cache_dir: str, top_k: int = 25) -> dict:
    architecture_metrics_path = os.path.join(cache_dir, "architecture_metrics.json")
    dependency_cycles_path = os.path.join(cache_dir, "dependency_cycles.json")
    analysis_metrics_path = os.path.join(cache_dir, "analysis_metrics.json")

    for path in [architecture_metrics_path, dependency_cycles_path, analysis_metrics_path]:
        if not os.path.exists(path):
            raise FileNotFoundError(path)

    arch = _load_json(architecture_metrics_path) or {}
    dep = _load_json(dependency_cycles_path) or {}
    metrics = _load_json(analysis_metrics_path) or {}

    repo_prefix = str(arch.get("repo_prefix") or "")
    repo = arch.get("repo") or {}
    symbols = arch.get("symbols") or {}
    files = arch.get("files") or {}

    local_symbols = [
        (fqn, info)
        for fqn, info in symbols.items()
        if isinstance(info, dict) and str(info.get("kind")) == "local"
    ]

    fan_in_values = [_to_int(info.get("fan_in", 0), 0) for _, info in local_symbols]
    fan_out_values = [_to_int(info.get("fan_out", 0), 0) for _, info in local_symbols]
    file_edge_values = [_to_int(info.get("edges", 0), 0) for info in files.values() if isinstance(info, dict)]

    fan_in_hot = _percentile_90(fan_in_values, floor=10)
    fan_out_hot = _percentile_90(fan_out_values, floor=10)
    file_edges_hot = _percentile_90(file_edge_values, floor=20)
    incoming_hot = _percentile_90(
        [_to_int(info.get("incoming_symbols", 0), 0) for info in files.values() if isinstance(info, dict)],
        floor=1,
    )
    outgoing_hot = _percentile_90(
        [_to_int(info.get("outgoing_symbols", 0), 0) for info in files.values() if isinstance(info, dict)],
        floor=1,
    )

    unresolved_calls = _to_int(metrics.get("unresolved_calls", 0), 0)
    total_calls = _to_int(
        metrics.get("total_calls", metrics.get("calls", metrics.get("resolved_calls", 0))),
        0,
    )
    unresolved_ratio = float(unresolved_calls) / float(total_calls) if total_calls > 0 else 0.0
    cycle_count = _to_int(dep.get("cycle_count", 0), 0)
    cycles = dep.get("cycles") or []

    orchestrators = set(repo.get("orchestrators") or [])
    critical_symbols = set(repo.get("critical_symbols") or [])
    dead_symbols = list(repo.get("dead_symbols") or [])

    hotspots: List[Dict[str, Any]] = []
    for fqn, info in local_symbols:
        fan_in = _to_int(info.get("fan_in", 0), 0)
        fan_out = _to_int(info.get("fan_out", 0), 0)
        score = 0
        reasons: List[str] = []
        flags: List[str] = []

        if fan_in >= fan_in_hot:
            score += 40
            reasons.append("High fan-in: many callers depend on it")
        if fan_out >= fan_out_hot:
            score += 40
            reasons.append("High fan-out: orchestrates many calls")
        if fqn in orchestrators:
            score += 15
            flags.append("orchestrator")
        if fqn in critical_symbols:
            score += 15
            flags.append("critical")
        if fqn.endswith(".<module>"):
            score += 10
            reasons.append("Module-level script orchestration")
            flags.append("module_level")
        if cycle_count > 0:
            score += 10
            reasons.append("Repo has dependency cycles")
            flags.append("cycle_related")
        if unresolved_ratio > 0.2:
            score += 10
            reasons.append("High unresolved call ratio")

        score = _clamp_score(score)
        if score <= 0:
            continue

        hotspots.append(
            {
                "fqn": fqn,
                "risk": _risk_band(score),
                "score": score,
                "reasons": reasons[:4],
                "fan_in": fan_in,
                "fan_out": fan_out,
                "location": _symbol_location(info),
                "flags": flags,
            }
        )

    hotspots.sort(key=lambda x: (-int(x["score"]), -int(x["fan_out"]), -int(x["fan_in"]), x["fqn"]))
    hotspots = hotspots[: int(top_k)]

    risky_files: List[Dict[str, Any]] = []
    for file_path, info in files.items():
        if not isinstance(info, dict):
            continue
        edges = _to_int(info.get("edges", 0), 0)
        incoming_symbols = _to_int(info.get("incoming_symbols", 0), 0)
        outgoing_symbols = _to_int(info.get("outgoing_symbols", 0), 0)

        score = 0
        reasons: List[str] = []
        if edges >= file_edges_hot:
            score += 60
            reasons.append("High edge density in file-level call graph")
        if outgoing_symbols >= outgoing_hot:
            score += 20
            reasons.append("High outgoing symbol count")
        if incoming_symbols >= incoming_hot:
            score += 20
            reasons.append("High incoming symbol count")

        score = _clamp_score(score)
        if score <= 0:
            continue

        risky_files.append(
            {
                "file": file_path,
                "risk": _risk_band(score),
                "score": score,
                "edges": edges,
                "incoming_symbols": incoming_symbols,
                "outgoing_symbols": outgoing_symbols,
                "reasons": reasons[:3],
            }
        )

    risky_files.sort(key=lambda x: (-int(x["score"]), -int(x["edges"]), x["file"]))
    risky_files = risky_files[: int(top_k)]

    top_fan_in = sorted(
        [(_fqn, _to_int(_info.get("fan_in", 0), 0)) for _fqn, _info in local_symbols],
        key=lambda x: (-x[1], x[0]),
    )
    top_fan_out = sorted(
        [(_fqn, _to_int(_info.get("fan_out", 0), 0)) for _fqn, _info in local_symbols],
        key=lambda x: (-x[1], x[0]),
    )
    refactor_targets = _compute_refactor_targets(
        hotspots=hotspots,
        high_fan_in=top_fan_in[:3],
        high_fan_out=top_fan_out[:3],
        unresolved_ratio=unresolved_ratio,
        cycle_count=cycle_count,
        cycles=cycles if isinstance(cycles, list) else [],
    )

    payload = {
        "ok": True,
        "repo_prefix": repo_prefix,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "thresholds": {
            "fan_in_hot": fan_in_hot,
            "fan_out_hot": fan_out_hot,
            "file_edges_hot": file_edges_hot,
            "top_k": int(top_k),
        },
        "repo_health": _repo_health_from_metrics(
            hotspots=hotspots,
            risky_files=risky_files,
            dead_symbols=dead_symbols,
            cycle_count=cycle_count,
            unresolved_ratio=unresolved_ratio,
        ),
        "hotspots": hotspots,
        "risky_files": risky_files,
        "refactor_targets": refactor_targets,
    }
    return payload
