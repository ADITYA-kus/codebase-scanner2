from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from analysis.utils.cache_manager import compute_repo_hash, get_cache_dir


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
ANALYSIS_ROOT = os.path.join(PROJECT_ROOT, "analysis")
DEFAULT_REPO = os.getenv("CODEMAP_UI_REPO", "testing_repo")

MISSING_CACHE_MESSAGE = "Cache not found. Run: python cli.py api analyze --path <repo>"


app = FastAPI(title="CodeMap AI UI")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
SEARCH_INDEX_CACHE: Dict[str, List[Dict[str, Any]]] = {}


def _load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_repo_dir(repo_dir: Optional[str]) -> str:
    candidate = os.path.abspath(repo_dir or DEFAULT_REPO)
    if os.path.exists(candidate):
        return candidate
    fallback = os.path.abspath(os.path.join(ANALYSIS_ROOT, repo_dir or DEFAULT_REPO))
    if os.path.exists(fallback):
        return fallback
    return candidate


def _repo_ctx(repo: Optional[str]) -> Dict[str, str]:
    repo_dir = _resolve_repo_dir(repo)
    cache_dir = get_cache_dir(repo_dir)
    return {
        "repo_dir": repo_dir,
        "repo_hash": compute_repo_hash(repo_dir),
        "cache_dir": cache_dir,
        "project_tree_path": os.path.join(cache_dir, "project_tree.json"),
        "explain_path": os.path.join(cache_dir, "explain.json"),
        "resolved_calls_path": os.path.join(cache_dir, "resolved_calls.json"),
        "manifest_path": os.path.join(cache_dir, "manifest.json"),
        "metrics_path": os.path.join(cache_dir, "analysis_metrics.json"),
    }


def _has_analysis_cache(ctx: Dict[str, str]) -> bool:
    if not os.path.exists(ctx["cache_dir"]):
        return False
    return os.path.exists(ctx["explain_path"]) and os.path.exists(ctx["resolved_calls_path"])


def _missing_cache_response() -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"ok": False, "error": "CACHE_NOT_FOUND", "message": MISSING_CACHE_MESSAGE},
    )


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _rel_file(ctx: Dict[str, str], file_path: str) -> str:
    if not file_path:
        return ""
    abs_path = os.path.abspath(file_path)
    if _norm(abs_path).startswith(_norm(ctx["repo_dir"])):
        return os.path.relpath(abs_path, ctx["repo_dir"]).replace("\\", "/")
    return file_path.replace("\\", "/")


def _load_repo_data(ctx: Dict[str, str]) -> Dict[str, Any]:
    explain = _load_json(ctx["explain_path"], {})
    resolved_calls = _load_json(ctx["resolved_calls_path"], [])
    return {"explain": explain, "resolved_calls": resolved_calls}


def _build_symbol_connections(
    ctx: Dict[str, str],
    fqn: str,
    explain: Dict[str, Any],
    resolved_calls: List[Dict[str, Any]],
) -> Dict[str, Any]:
    called_by: List[Dict[str, Any]] = []
    used_in: List[Dict[str, Any]] = []
    calls_counter: Counter[str] = Counter()

    for call in resolved_calls:
        caller_fqn = call.get("caller_fqn")
        callee_fqn = call.get("callee_fqn")
        file_path = call.get("file", "")
        line = int(call.get("line", -1))

        if callee_fqn == fqn:
            item = {
                "fqn": caller_fqn,
                "file": _rel_file(ctx, file_path),
                "line": line,
            }
            called_by.append(item)
            used_in.append(item)

        if caller_fqn == fqn and callee_fqn:
            calls_counter[callee_fqn] += 1

    called_by.sort(key=lambda x: (x.get("file", ""), int(x.get("line", -1)), x.get("fqn", "")))
    used_in.sort(key=lambda x: (x.get("file", ""), int(x.get("line", -1)), x.get("fqn", "")))

    calls: List[Dict[str, Any]] = []
    for callee_fqn, count in sorted(calls_counter.items(), key=lambda x: (x[0].lower(), x[1])):
        parts = callee_fqn.split(".")
        if len(parts) >= 2 and parts[-2][:1].isupper():
            name = f"{parts[-2]}.{parts[-1]}"
        else:
            name = parts[-1]
        calls.append(
            {
                "name": name,
                "fqn": callee_fqn,
                "count": int(count),
                "clickable": callee_fqn in explain,
            }
        )

    return {
        "called_by": called_by,
        "calls": calls,
        "used_in": used_in,
    }


def _display_and_module_from_fqn(fqn: str) -> Dict[str, str]:
    parts = fqn.split(".")
    if len(parts) >= 2 and parts[-2][:1].isupper():
        return {
            "display": f"{parts[-2]}.{parts[-1]}",
            "module": ".".join(parts[:-2]),
            "class_name": parts[-2],
            "short_name": parts[-1],
        }
    return {
        "display": parts[-1],
        "module": ".".join(parts[:-1]),
        "class_name": "",
        "short_name": parts[-1],
    }


def _build_search_index(ctx: Dict[str, str]) -> List[Dict[str, Any]]:
    cache_key = ctx["repo_hash"]
    if cache_key in SEARCH_INDEX_CACHE:
        return SEARCH_INDEX_CACHE[cache_key]

    explain = _load_json(ctx["explain_path"], {})
    items: List[Dict[str, Any]] = []
    for fqn, obj in explain.items():
        dm = _display_and_module_from_fqn(fqn)
        loc = obj.get("location") or {}
        rel_file = _rel_file(ctx, loc.get("file", ""))
        searchable = " ".join([
            fqn.lower(),
            dm["display"].lower(),
            dm["short_name"].lower(),
            dm["class_name"].lower(),
        ]).strip()
        items.append({
            "fqn": fqn,
            "display": dm["display"],
            "module": dm["module"],
            "file": rel_file,
            "line": int(loc.get("start_line", -1)),
            "_searchable": searchable,
        })
    SEARCH_INDEX_CACHE[cache_key] = items
    return items


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "default_repo": DEFAULT_REPO})


@app.get("/api/meta")
def api_meta(repo: Optional[str] = Query(default=None)):
    ctx = _repo_ctx(repo)
    if not _has_analysis_cache(ctx):
        return _missing_cache_response()

    manifest = _load_json(ctx["manifest_path"], {})
    explain = _load_json(ctx["explain_path"], {})
    resolved = _load_json(ctx["resolved_calls_path"], [])
    metrics = _load_json(ctx["metrics_path"], {})

    return {
        "ok": True,
        "repo_hash": ctx["repo_hash"],
        "repo_dir": ctx["repo_dir"],
        "cache_dir": ctx["cache_dir"],
        "analyzed_at": manifest.get("updated_at"),
        "counts": {
            "symbols": len(explain),
            "resolved_calls": len(resolved),
            "critical_apis": len(metrics.get("critical_apis", [])),
            "orchestrators": len(metrics.get("orchestrators", [])),
        },
    }


@app.get("/api/tree")
def api_tree(repo: Optional[str] = Query(default=None)):
    ctx = _repo_ctx(repo)
    if not _has_analysis_cache(ctx):
        return _missing_cache_response()

    if not os.path.exists(ctx["project_tree_path"]):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Snapshot not found. Run analyze first."},
        )

    return {
        "ok": True,
        "tree": _load_json(ctx["project_tree_path"], {}),
    }


@app.get("/api/file")
def api_file(path: str = Query(...), repo: Optional[str] = Query(default=None)):
    ctx = _repo_ctx(repo)
    if not _has_analysis_cache(ctx):
        return _missing_cache_response()

    rel_path = path.replace("\\", "/").lstrip("/")
    abs_path = os.path.abspath(os.path.join(ctx["repo_dir"], rel_path))
    if not _norm(abs_path).startswith(_norm(ctx["repo_dir"])):
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_PATH"})

    data = _load_repo_data(ctx)
    explain = data["explain"]
    resolved = data["resolved_calls"]
    manifest = _load_json(ctx["manifest_path"], {})
    snapshot = manifest.get("symbol_snapshot", [])

    fqn_to_file: Dict[str, str] = {}
    for fqn, obj in explain.items():
        loc_file = (obj.get("location") or {}).get("file")
        if not loc_file:
            continue
        fqn_to_file[fqn] = loc_file

    method_dedupe = {
        (_norm(s.get("file_path", "")), s.get("name"), int(s.get("start_line", -1)), int(s.get("end_line", -1)))
        for s in snapshot if s.get("kind") == "method"
    }
    classes: Dict[str, List[str]] = {}
    functions: List[str] = []
    symbol_fqns: List[str] = []
    for s in snapshot:
        file_path = s.get("file_path")
        if _norm(file_path or "") != _norm(abs_path):
            continue
        kind = s.get("kind")
        module = s.get("module", "")
        qn = s.get("qualified_name", "")
        fqn = f"{module}.{qn}" if module and qn else ""
        if not fqn:
            continue

        if kind == "function":
            dedupe_key = (_norm(file_path), s.get("name"), int(s.get("start_line", -1)), int(s.get("end_line", -1)))
            if dedupe_key in method_dedupe:
                continue
            functions.append(fqn)
            symbol_fqns.append(fqn)
        elif kind == "class":
            class_name = s.get("name", "")
            classes.setdefault(class_name, [])
            symbol_fqns.append(fqn)
        elif kind == "method":
            class_name = s.get("class_name") or qn.split(".")[0]
            classes.setdefault(class_name, []).append(fqn)
            symbol_fqns.append(fqn)

    outgoing = [c for c in resolved if _norm(c.get("file", "")) == _norm(abs_path)]
    incoming = [
        c for c in resolved
        if c.get("callee_fqn") and _norm(fqn_to_file.get(c["callee_fqn"], "")) == _norm(abs_path)
    ]

    top_callers_counter = Counter(
        (c.get("caller_fqn", ""), c.get("file", ""), int(c.get("line", -1))) for c in incoming
    )
    top_callees_counter = Counter(c.get("callee_fqn") for c in outgoing if c.get("callee_fqn"))

    top_callers = [
        {
            "caller_fqn": k[0],
            "file": _rel_file(ctx, k[1]),
            "line": k[2],
            "count": v,
            "hint": f"{_rel_file(ctx, k[1])}:{k[2]}",
        }
        for k, v in top_callers_counter.most_common(10)
    ]
    top_callees = [{"fqn": k, "count": v} for k, v in top_callees_counter.most_common(10)]

    grouped_classes = [
        {
            "name": class_name,
            "methods": sorted(methods),
        }
        for class_name, methods in sorted(classes.items(), key=lambda x: x[0].lower())
    ]

    return {
        "ok": True,
        "file": rel_path,
        "symbols": {
            "classes": grouped_classes,
            "functions": sorted(functions),
        },
        "symbol_fqns": sorted(symbol_fqns),
        "incoming_usages_count": len(incoming),
        "outgoing_calls_count": len(outgoing),
        "top_callers": top_callers,
        "top_callees": top_callees,
    }


@app.get("/api/symbol")
def api_symbol(fqn: str = Query(...), repo: Optional[str] = Query(default=None)):
    ctx = _repo_ctx(repo)
    if not _has_analysis_cache(ctx):
        return _missing_cache_response()

    explain = _load_json(ctx["explain_path"], {})
    obj = explain.get(fqn)
    if not obj:
        return JSONResponse(status_code=404, content={"ok": False, "error": "NOT_FOUND", "fqn": fqn})
    resolved_calls = _load_json(ctx["resolved_calls_path"], [])
    result = dict(obj)
    result["connections"] = _build_symbol_connections(ctx, fqn, explain, resolved_calls)
    return {"ok": True, "result": result}


@app.get("/api/usages")
def api_usages(fqn: str = Query(...), repo: Optional[str] = Query(default=None)):
    ctx = _repo_ctx(repo)
    if not _has_analysis_cache(ctx):
        return _missing_cache_response()

    resolved = _load_json(ctx["resolved_calls_path"], [])
    usages = [
        {
            "caller_fqn": c.get("caller_fqn"),
            "file": _rel_file(ctx, c.get("file", "")),
            "line": int(c.get("line", -1)),
            "hint": f"{_rel_file(ctx, c.get('file', ''))}:{int(c.get('line', -1))}",
        }
        for c in resolved
        if c.get("callee_fqn") == fqn
    ]
    usages.sort(key=lambda u: (u.get("file", ""), int(u.get("line", -1))))
    return {"ok": True, "fqn": fqn, "count": len(usages), "usages": usages}


@app.get("/api/search")
def api_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=50),
    repo: Optional[str] = Query(default=None),
):
    ctx = _repo_ctx(repo)
    if not _has_analysis_cache(ctx):
        return _missing_cache_response()

    query = q.strip().lower()
    if not query:
        return {"ok": True, "query": q, "count": 0, "results": [], "truncated": False}

    index = _build_search_index(ctx)
    matched = [item for item in index if query in item["_searchable"]]
    matched.sort(key=lambda i: (i["display"].lower(), i["fqn"].lower()))
    sliced = matched[:limit]

    results = [
        {
            "fqn": i["fqn"],
            "display": i["display"],
            "module": i["module"],
            "file": i["file"],
            "line": i["line"],
        }
        for i in sliced
    ]
    return {
        "ok": True,
        "query": q,
        "count": len(matched),
        "results": results,
        "truncated": len(matched) > limit,
    }
