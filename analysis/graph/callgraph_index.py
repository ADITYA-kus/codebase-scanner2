# Build caller->callees and reverse index
# analysis/graph/callgraph_index.py
# Phase-5 Step-1.1: Build forward + reverse call indexes from Phase-4 resolved calls

from dataclasses import dataclass
import json
from typing import Dict, List, Optional, Set


@dataclass(frozen=True)
class CallSite:
    """
    A single call occurrence in the code.
    """
    caller_fqn: str                 # e.g. testing_repo.test.Student.info
    callee_fqn: Optional[str]       # e.g. testing_repo.test.Student.display (None if unresolved)
    callee_name: str                # raw name from AST (e.g. "display", "print")
    file: str
    line: int


class CallGraphIndex:
    """
    Stores:
      - forward index: caller_fqn -> [CallSite...]
      - reverse index: callee_fqn -> [CallSite...]
      - unresolved calls list
    """

    def __init__(self):
        self._forward: Dict[str, List[CallSite]] = {}
        self._reverse: Dict[str, List[CallSite]] = {}
        self._unresolved: List[CallSite] = []

    # ----------------------------
    # Registration
    # ----------------------------
    def add_call(self, callsite: CallSite) -> None:
        self._forward.setdefault(callsite.caller_fqn, []).append(callsite)

        if callsite.callee_fqn:
            self._reverse.setdefault(callsite.callee_fqn, []).append(callsite)
        else:
            self._unresolved.append(callsite)

    # ----------------------------
    # Query APIs
    # ----------------------------
    def callees_of(self, caller_fqn: str) -> List[CallSite]:
        return self._forward.get(caller_fqn, [])

    def callers_of(self, callee_fqn: str) -> List[CallSite]:
        return self._reverse.get(callee_fqn, [])

    def unresolved_calls(self) -> List[CallSite]:
        return list(self._unresolved)

    def all_callers(self) -> List[str]:
        return sorted(self._forward.keys())

    def all_callees(self) -> List[str]:
        return sorted(self._reverse.keys())

    def stats(self) -> dict:
        return {
            "unique_callers": len(self._forward),
            "unique_callees": len(self._reverse),
            "unresolved_calls": len(self._unresolved),
            "total_calls": sum(len(v) for v in self._forward.values()),
        }


# ----------------------------
# Helper for building FQNs
# ----------------------------

def build_caller_fqn(call: dict, current_module: str) -> str:
    """
    Convert a Phase-3/4 call record into a fully-qualified caller symbol name.
    - If class exists: module.Class.caller
    - Else: module.caller
    """
    caller = call.get("caller", "<unknown>")
    cls = call.get("class")
    if cls:
        return f"{current_module}.{cls}.{caller}"
    return f"{current_module}.{caller}"


def _high_threshold(values: List[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    p90_idx = int((len(ordered) - 1) * 0.9)
    p90 = ordered[p90_idx]
    return max(2, p90)


def compute_hub_metrics(resolved_calls: List[dict], top_k: int = 10) -> dict:
    fan_in_sources: Dict[str, Set[str]] = {}
    fan_out_targets: Dict[str, Set[str]] = {}

    for call in resolved_calls:
        caller = call.get("caller_fqn")
        callee = call.get("callee_fqn")
        if caller:
            fan_out_targets.setdefault(caller, set())
            if callee:
                fan_out_targets[caller].add(callee)
        if callee and caller:
            fan_in_sources.setdefault(callee, set()).add(caller)

    fan_in = {fqn: len(callers) for fqn, callers in fan_in_sources.items()}
    fan_out = {fqn: len(callees) for fqn, callees in fan_out_targets.items()}

    fan_in_threshold = _high_threshold(list(fan_in.values()))
    fan_out_threshold = _high_threshold(list(fan_out.values()))

    critical_apis = [
        {"fqn": fqn, "fan_in": score}
        for fqn, score in sorted(fan_in.items(), key=lambda x: (-x[1], x[0]))
        if score >= fan_in_threshold
    ]
    orchestrators = [
        {"fqn": fqn, "fan_out": score}
        for fqn, score in sorted(fan_out.items(), key=lambda x: (-x[1], x[0]))
        if score >= fan_out_threshold
    ]

    if not critical_apis:
        critical_apis = [
            {"fqn": fqn, "fan_in": score}
            for fqn, score in sorted(fan_in.items(), key=lambda x: (-x[1], x[0]))[:top_k]
            if score > 0
        ]
    if not orchestrators:
        orchestrators = [
            {"fqn": fqn, "fan_out": score}
            for fqn, score in sorted(fan_out.items(), key=lambda x: (-x[1], x[0]))[:top_k]
            if score > 0
        ]

    return {
        "fan_in_threshold": fan_in_threshold,
        "fan_out_threshold": fan_out_threshold,
        "critical_apis": critical_apis[:top_k],
        "orchestrators": orchestrators[:top_k],
        "fan_in": fan_in,
        "fan_out": fan_out,
        "stats": {
            "total_calls": len(resolved_calls),
            "symbols_with_fan_in": len(fan_in),
            "symbols_with_fan_out": len(fan_out),
        },
    }


def write_hub_metrics_from_resolved_calls(resolved_calls_path: str, output_path: str, top_k: int = 10) -> dict:
    with open(resolved_calls_path, "r", encoding="utf-8") as f:
        resolved_calls = json.load(f)

    metrics = compute_hub_metrics(resolved_calls, top_k=top_k)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    return metrics
