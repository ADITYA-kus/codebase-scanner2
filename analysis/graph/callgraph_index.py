# Build caller->callees and reverse index
# analysis/graph/callgraph_index.py
# Phase-5 Step-1.1: Build forward + reverse call indexes from Phase-4 resolved calls

from dataclasses import dataclass
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
