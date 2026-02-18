from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from analysis.utils.cache_manager import (
    compute_repo_hash,
    get_cache_dir,
    load_policy as load_retention_policy,
    save_policy as save_retention_policy,
    cleanup as cleanup_retention_data,
    delete_repo as delete_repo_cache,
    set_repo_policy,
    compute_expiration,
)


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
ANALYSIS_ROOT = os.path.join(PROJECT_ROOT, "analysis")
DEFAULT_REPO = os.getenv("CODEMAP_UI_REPO", "testing_repo")
GLOBAL_CACHE_DIR = os.path.join(PROJECT_ROOT, ".codemap_cache")
WORKSPACES_PATH = os.path.join(GLOBAL_CACHE_DIR, "workspaces.json")

MISSING_CACHE_MESSAGE = "Not analyzed yet. Run: python cli.py api analyze --path <repo>"


app = FastAPI(title="CodeMap AI UI")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
SEARCH_INDEX_CACHE: Dict[str, List[Dict[str, Any]]] = {}
GRAPH_INDEX_CACHE: Dict[str, Dict[str, Any]] = {}


def _load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _cache_dir_size(path: str) -> int:
    total = 0
    if not os.path.isdir(path):
        return 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            fp = os.path.join(root, name)
            try:
                total += int(os.path.getsize(fp))
            except OSError:
                continue
    return int(total)


def _resolve_repo_dir(repo_dir: Optional[str]) -> str:
    candidate = os.path.abspath(repo_dir or DEFAULT_REPO)
    if os.path.exists(candidate):
        return candidate
    fallback = os.path.abspath(os.path.join(ANALYSIS_ROOT, repo_dir or DEFAULT_REPO))
    if os.path.exists(fallback):
        return fallback
    return candidate


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ui_state_path(cache_dir: str) -> str:
    return os.path.join(cache_dir, "ui_state.json")


def _default_ui_state() -> Dict[str, Any]:
    return {
        "last_symbol": "",
        "recent_symbols": [],
        "recent_files": [],
        "updated_at": _now_utc(),
    }


def _ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _save_json(path: str, data: Any) -> None:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _repo_ctx_from_dir(repo_dir: str) -> Dict[str, str]:
    resolved = _resolve_repo_dir(repo_dir)
    cache_dir = get_cache_dir(resolved)
    return {
        "repo_dir": resolved,
        "repo_hash": compute_repo_hash(resolved),
        "cache_dir": cache_dir,
        "project_tree_path": os.path.join(cache_dir, "project_tree.json"),
        "explain_path": os.path.join(cache_dir, "explain.json"),
        "resolved_calls_path": os.path.join(cache_dir, "resolved_calls.json"),
        "manifest_path": os.path.join(cache_dir, "manifest.json"),
        "metrics_path": os.path.join(cache_dir, "analysis_metrics.json"),
        "ui_state_path": _ui_state_path(cache_dir),
    }


def _ensure_ui_state(ctx: Dict[str, str]) -> Dict[str, Any]:
    state = _load_json(ctx["ui_state_path"], None)
    if not isinstance(state, dict):
        state = _default_ui_state()
        _save_json(ctx["ui_state_path"], state)
    return state


def _load_workspaces() -> Dict[str, Any]:
    ws = _load_json(WORKSPACES_PATH, None)
    if isinstance(ws, dict) and isinstance(ws.get("repos"), list):
        return ws
    return {"active_repo_hash": "", "repos": []}


def _cache_manifest(cache_dir: str) -> Dict[str, Any]:
    path = os.path.join(cache_dir, "manifest.json")
    data = _load_json(path, {})
    return data if isinstance(data, dict) else {}


def _list_cache_status() -> List[Dict[str, Any]]:
    policy = load_retention_policy()
    items: List[Dict[str, Any]] = []
    if not os.path.isdir(GLOBAL_CACHE_DIR):
        return items
    for name in sorted(os.listdir(GLOBAL_CACHE_DIR)):
        if name in {"workspaces", "workspaces.json", "retention.json"}:
            continue
        cache_dir = os.path.join(GLOBAL_CACHE_DIR, name)
        if not os.path.isdir(cache_dir):
            continue
        manifest = _cache_manifest(cache_dir)
        manifest.setdefault("repo_hash", name)
        exp = compute_expiration(manifest, policy)
        repo_path = manifest.get("repo_path") if isinstance(manifest.get("repo_path"), str) else ""
        items.append(
            {
                "repo_hash": name,
                "repo_path": repo_path,
                "cache_dir": cache_dir,
                "size_bytes": _cache_dir_size(cache_dir),
                "last_updated": manifest.get("updated_at"),
                "retention": exp,
            }
        )
    return items


def _save_workspaces(ws: Dict[str, Any]) -> None:
    _save_json(WORKSPACES_PATH, ws)


def _repo_entry(repo_dir: str) -> Dict[str, str]:
    resolved = _resolve_repo_dir(repo_dir)
    repo_hash = compute_repo_hash(resolved)
    return {
        "name": os.path.basename(resolved.rstrip("\\/")) or resolved,
        "path": resolved,
        "repo_hash": repo_hash,
        "last_opened": _now_utc(),
        "source": "filesystem",
        "repo_url": "",
        "ref": "",
        "mode": "",
    }


def _repo_entry_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = _resolve_repo_dir(str(payload.get("path", "") or ""))
    repo_hash = str(payload.get("repo_hash", "") or compute_repo_hash(path))
    source = str(payload.get("source", "filesystem") or "filesystem")
    if source not in {"filesystem", "github"}:
        source = "filesystem"
    return {
        "name": str(payload.get("name") or os.path.basename(path.rstrip("\\/")) or path),
        "path": path,
        "repo_hash": repo_hash,
        "last_opened": _now_utc(),
        "source": source,
        "repo_url": str(payload.get("repo_url", "") or ""),
        "ref": str(payload.get("ref", "") or ""),
        "mode": str(payload.get("mode", "") or ""),
    }


def _ensure_default_workspace() -> Dict[str, Any]:
    ws = _load_workspaces()
    if ws.get("repos"):
        return ws
    default_dir = _resolve_repo_dir(DEFAULT_REPO)
    if os.path.isdir(default_dir):
        entry = _repo_entry(default_dir)
        ws = {"active_repo_hash": entry["repo_hash"], "repos": [entry]}
        _save_workspaces(ws)
    return ws


def _upsert_workspace_repo(entry: Dict[str, Any], set_active: bool = True) -> Dict[str, Any]:
    ws = _load_workspaces()
    repos = ws.get("repos", [])
    if not isinstance(repos, list):
        repos = []
    existing = next((r for r in repos if isinstance(r, dict) and r.get("repo_hash") == entry.get("repo_hash")), None)
    if existing:
        existing.update(entry)
        existing["last_opened"] = _now_utc()
    else:
        repos.append(entry)
    ws["repos"] = repos
    if set_active:
        ws["active_repo_hash"] = str(entry.get("repo_hash", "") or "")
    _save_workspaces(ws)
    return ws


def _cli_json(args: List[str], timeout_sec: int = 1800) -> Dict[str, Any]:
    cmd = [sys.executable, os.path.join(PROJECT_ROOT, "cli.py"), "api"] + list(args)
    try:
        proc = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "CLI_TIMEOUT", "message": "CLI analyze timed out"}
    except Exception as e:
        return {"ok": False, "error": "CLI_EXEC_FAILED", "message": str(e)}

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    payload: Dict[str, Any]
    try:
        payload = json.loads(stdout) if stdout else {"ok": False, "error": "EMPTY_OUTPUT", "message": "CLI returned empty output"}
    except Exception:
        payload = {
            "ok": False,
            "error": "INVALID_CLI_JSON",
            "message": "Failed to parse CLI JSON output",
            "stdout": stdout[-4000:],
            "stderr": stderr[-4000:],
        }
    if proc.returncode != 0 and payload.get("ok") is not False:
        payload = {
            "ok": False,
            "error": "CLI_FAILED",
            "message": stderr or payload.get("message") or "CLI command failed",
            "stdout": stdout[-4000:],
            "stderr": stderr[-4000:],
        }
    return payload


def _repo_analyze_command(repo: Dict[str, Any]) -> str:
    source = str(repo.get("source", "filesystem") or "filesystem")
    if source == "github":
        repo_url = str(repo.get("repo_url", "") or "").strip()
        ref = str(repo.get("ref", "") or "").strip() or "main"
        mode = str(repo.get("mode", "") or "zip")
        return f"python cli.py api analyze --github {repo_url} --ref {ref} --mode {mode}"
    return f"python cli.py api analyze --path {repo.get('path', '<repo>')}"


def _get_active_repo_entry() -> Optional[Dict[str, str]]:
    ws = _ensure_default_workspace()
    repos = ws.get("repos", [])
    active_hash = ws.get("active_repo_hash", "")
    for repo in repos:
        if repo.get("repo_hash") == active_hash:
            return repo
    if repos:
        ws["active_repo_hash"] = repos[0].get("repo_hash", "")
        _save_workspaces(ws)
        return repos[0]
    return None


def _active_repo_ctx() -> Optional[Dict[str, str]]:
    active = _get_active_repo_entry()
    if not active:
        return None
    ctx = _repo_ctx_from_dir(active["path"])
    _ensure_ui_state(ctx)
    return ctx


def _repo_ctx(repo: Optional[str]) -> Dict[str, str]:
    # Backward-compatible helper retained for older internal call sites.
    if repo:
        return _repo_ctx_from_dir(repo)
    active = _active_repo_ctx()
    if active:
        return active
    repo_dir = _resolve_repo_dir(repo)
    return _repo_ctx_from_dir(repo_dir)


def _has_analysis_cache(ctx: Dict[str, str]) -> bool:
    if not os.path.exists(ctx["cache_dir"]):
        return False
    return os.path.exists(ctx["explain_path"]) and os.path.exists(ctx["resolved_calls_path"])


def _missing_cache_response() -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"ok": False, "error": "CACHE_NOT_FOUND", "message": MISSING_CACHE_MESSAGE},
    )


def _no_active_repo_response() -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "ok": False,
            "error": "NO_ACTIVE_REPO",
            "message": "No repository selected. Add one in workspace first.",
        },
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


def _repo_registry_data() -> List[Dict[str, Any]]:
    ws = _ensure_default_workspace()
    policy = load_retention_policy()
    repos = ws.get("repos", []) if isinstance(ws, dict) else []
    items: List[Dict[str, Any]] = []
    seen = set()

    for repo in repos:
        if not isinstance(repo, dict):
            continue
        entry = _repo_entry_from_payload(repo)
        repo_hash = entry["repo_hash"]
        if not repo_hash:
            continue
        seen.add(repo_hash)
        cache_dir = get_cache_dir(entry["path"])
        explain_path = os.path.join(cache_dir, "explain.json")
        resolved_path = os.path.join(cache_dir, "resolved_calls.json")
        has_analysis = os.path.exists(explain_path) and os.path.exists(resolved_path)
        manifest = _cache_manifest(cache_dir)
        manifest.setdefault("repo_hash", repo_hash)
        expiry = compute_expiration(manifest, policy)
        items.append(
            {
                "repo_hash": repo_hash,
                "name": entry.get("name", ""),
                "source": entry.get("source", "filesystem"),
                "repo_path": entry.get("path", ""),
                "repo_url": entry.get("repo_url", ""),
                "ref": entry.get("ref", ""),
                "mode": entry.get("mode", ""),
                "cache_dir": cache_dir,
                "has_analysis": bool(has_analysis),
                "last_updated": manifest.get("updated_at"),
                "size_bytes": _cache_dir_size(cache_dir),
                "retention": expiry,
                "analyze_command": _repo_analyze_command(entry),
            }
        )

    # Include cache-only repos not yet in workspace list.
    for status in _list_cache_status():
        repo_hash = str(status.get("repo_hash", "") or "")
        if not repo_hash or repo_hash in seen:
            continue
        repo_path = str(status.get("repo_path", "") or "")
        source = "github" if (os.sep + ".codemap_cache" + os.sep + "workspaces" + os.sep) in repo_path else "filesystem"
        items.append(
            {
                "repo_hash": repo_hash,
                "name": os.path.basename(repo_path.rstrip("\\/")) or repo_hash,
                "source": source,
                "repo_path": repo_path,
                "repo_url": "",
                "ref": "",
                "mode": "zip" if source == "github" else "",
                "cache_dir": status.get("cache_dir"),
                "has_analysis": os.path.exists(os.path.join(status.get("cache_dir", ""), "explain.json")),
                "last_updated": status.get("last_updated"),
                "size_bytes": int(status.get("size_bytes", 0)),
                "retention": status.get("retention", {}),
                "analyze_command": f"python cli.py api analyze --path {repo_path}",
            }
        )

    items.sort(key=lambda x: (str(x.get("name", "")).lower(), str(x.get("repo_hash", ""))))
    return items


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


def _classify_symbol(fqn: str, explain: Dict[str, Any]) -> str:
    if fqn.startswith("builtins."):
        return "builtin"
    if fqn in explain:
        return "local"
    if fqn.startswith("external::"):
        return "external"
    return "external"


def _short_label(fqn: str) -> str:
    if fqn.startswith("external::"):
        return fqn.split("external::", 1)[1]
    parts = fqn.split(".")
    if len(parts) >= 2 and parts[-2][:1].isupper():
        return f"{parts[-2]}.{parts[-1]}"
    return parts[-1]


def _build_graph_index(ctx: Dict[str, str]) -> Dict[str, Any]:
    cache_key = ctx["repo_hash"]
    resolved_mtime = os.path.getmtime(ctx["resolved_calls_path"]) if os.path.exists(ctx["resolved_calls_path"]) else -1
    explain_mtime = os.path.getmtime(ctx["explain_path"]) if os.path.exists(ctx["explain_path"]) else -1
    signature = f"{resolved_mtime}:{explain_mtime}"

    cached = GRAPH_INDEX_CACHE.get(cache_key)
    if cached and cached.get("signature") == signature:
        return cached["index"]

    explain = _load_json(ctx["explain_path"], {})
    resolved_calls = _load_json(ctx["resolved_calls_path"], [])

    callees_map: Dict[str, List[str]] = {}
    callers_map: Dict[str, List[str]] = {}
    edge_counts: Dict[tuple, int] = {}

    for call in resolved_calls:
        caller = call.get("caller_fqn")
        if not caller:
            continue
        callee = call.get("callee_fqn")
        if not callee:
            raw_name = str(call.get("callee") or "<unknown>").strip()
            callee = f"external::{raw_name}"

        callees_map.setdefault(caller, []).append(callee)
        callers_map.setdefault(callee, []).append(caller)
        edge_key = (caller, callee)
        edge_counts[edge_key] = edge_counts.get(edge_key, 0) + 1

    index = {
        "explain": explain,
        "callees_map": callees_map,
        "callers_map": callers_map,
        "edge_counts": edge_counts,
    }
    GRAPH_INDEX_CACHE[cache_key] = {"signature": signature, "index": index}
    return index


def _normalize_ui_state(state: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(state, dict):
        return _default_ui_state()
    norm = _default_ui_state()
    norm["last_symbol"] = str(state.get("last_symbol", "") or "")
    norm["recent_symbols"] = [x for x in state.get("recent_symbols", []) if isinstance(x, str)][:20]
    norm["recent_files"] = [x for x in state.get("recent_files", []) if isinstance(x, str)][:20]
    norm["updated_at"] = str(state.get("updated_at", _now_utc()))
    return norm


def _push_recent(items: List[str], value: str, limit: int = 20) -> List[str]:
    clean = [x for x in items if isinstance(x, str) and x != value]
    clean.insert(0, value)
    return clean[:limit]


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "default_repo": DEFAULT_REPO})


@app.get("/api/workspace")
def api_workspace():
    ws = _ensure_default_workspace()
    normalized_repos = []
    for repo in ws.get("repos", []):
        if isinstance(repo, dict):
            normalized_repos.append(_repo_entry_from_payload(repo))
    ws["repos"] = normalized_repos
    _save_workspaces(ws)
    return {
        "ok": True,
        "repos": normalized_repos,
        "active_repo_hash": ws.get("active_repo_hash", ""),
    }


@app.get("/api/repo_registry")
def api_repo_registry():
    ws = _ensure_default_workspace()
    return {
        "ok": True,
        "active_repo_hash": ws.get("active_repo_hash", ""),
        "repos": _repo_registry_data(),
    }


@app.get("/api/data_privacy")
def api_data_privacy():
    policy = load_retention_policy()
    caches = _list_cache_status()
    total_size = sum(int(c.get("size_bytes", 0)) for c in caches)
    expiring = [
        c for c in caches
        if c.get("retention", {}).get("mode") != "pinned"
        and c.get("retention", {}).get("days_left") is not None
        and float(c["retention"]["days_left"]) <= 3
    ]
    oldest_repo = None
    largest_repo = None
    if caches:
        oldest_repo = sorted(caches, key=lambda x: str(x.get("last_updated", "") or ""))[0]
        largest_repo = sorted(caches, key=lambda x: int(x.get("size_bytes", 0)), reverse=True)[0]
    return {
        "ok": True,
        "policy": policy,
        "repo_count": len(caches),
        "total_cache_size_bytes": int(total_size),
        "last_cleanup_iso": policy.get("last_cleanup_iso", ""),
        "oldest_repo": {
            "repo_hash": oldest_repo.get("repo_hash"),
            "repo_path": oldest_repo.get("repo_path"),
            "last_updated": oldest_repo.get("last_updated"),
        } if oldest_repo else None,
        "largest_repo": {
            "repo_hash": largest_repo.get("repo_hash"),
            "repo_path": largest_repo.get("repo_path"),
            "size_bytes": int(largest_repo.get("size_bytes", 0)),
        } if largest_repo else None,
        "caches": caches,
        "expiring_soon": [
            {
                "repo_hash": c.get("repo_hash"),
                "repo_path": c.get("repo_path"),
                "days_left": c.get("retention", {}).get("days_left"),
            }
            for c in expiring
        ],
    }


@app.post("/api/data_privacy/policy")
async def api_data_privacy_policy(request: Request):
    body = await request.json()
    payload = body if isinstance(body, dict) else {}
    current = load_retention_policy()
    default_ttl = payload.get("default_ttl_days", current.get("default_ttl_days", 30))
    workspace_ttl = payload.get("workspaces_ttl_days", current.get("workspaces_ttl_days", 7))
    try:
        default_ttl = int(default_ttl)
        workspace_ttl = int(workspace_ttl)
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_POLICY"})
    if default_ttl < 0 or workspace_ttl < 0:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_POLICY"})
    updated = save_retention_policy(
        {
            "default_ttl_days": default_ttl,
            "workspaces_ttl_days": workspace_ttl,
            "never_delete_repo_hashes": current.get("never_delete_repo_hashes", []),
            "repo_policies": current.get("repo_policies", {}),
            "last_cleanup_iso": current.get("last_cleanup_iso", ""),
        }
    )
    return {"ok": True, "policy": updated}


@app.post("/api/data_privacy/cleanup")
async def api_data_privacy_cleanup(request: Request):
    body = await request.json()
    payload = body if isinstance(body, dict) else {}
    dry_run = bool(payload.get("dry_run", True))
    yes = bool(payload.get("yes", False))
    apply_flag = bool(payload.get("apply", False))
    if apply_flag:
        dry_run = False
        yes = True
    if not dry_run and not yes:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "CONFIRM_REQUIRED", "message": "Set yes=true to run cleanup."},
        )
    result = cleanup_retention_data(dry_run=dry_run)
    return result


@app.post("/api/data_privacy/delete_repo")
async def api_data_privacy_delete_repo(request: Request):
    body = await request.json()
    payload = body if isinstance(body, dict) else {}
    repo_hash = str(payload.get("repo_hash", "") or "").strip()
    dry_run = bool(payload.get("dry_run", True))
    yes = bool(payload.get("yes", False))
    if not repo_hash:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_REPO_HASH"})
    if not dry_run and not yes:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "CONFIRM_REQUIRED", "message": "Set yes=true to delete."},
        )
    result = delete_repo_cache(repo_hash=repo_hash, dry_run=dry_run)
    return result


@app.post("/api/data_privacy/delete_analysis")
async def api_data_privacy_delete_analysis(request: Request):
    body = await request.json()
    payload = body if isinstance(body, dict) else {}
    repo_hash = str(payload.get("repo_hash", "") or "").strip()
    dry_run = bool(payload.get("dry_run", True))
    yes = bool(payload.get("yes", False))
    if not repo_hash:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_REPO_HASH"})
    if not dry_run and not yes:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "CONFIRM_REQUIRED", "message": "Set yes=true to delete."},
        )
    result = delete_repo_cache(repo_hash=repo_hash, dry_run=dry_run, remove_workspace_registry=False)
    return result


@app.post("/api/data_privacy/repo_policy")
async def api_data_privacy_repo_policy(request: Request):
    body = await request.json()
    payload = body if isinstance(body, dict) else {}
    repo_hash = str(payload.get("repo_hash", "") or "").strip()
    policy_value = str(payload.get("policy", "") or "").strip().lower()
    if not repo_hash:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_REPO_HASH"})

    if policy_value == "never":
        mode = "pinned"
        ttl_days = 0
    elif policy_value == "24h":
        mode = "ttl"
        ttl_days = 1
    elif policy_value == "7d":
        mode = "ttl"
        ttl_days = 7
    elif policy_value == "30d":
        mode = "ttl"
        ttl_days = 30
    else:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_POLICY"})

    policy = set_repo_policy(repo_hash=repo_hash, mode=mode, ttl_days=ttl_days)
    return {"ok": True, "repo_hash": repo_hash, "policy": policy}


@app.post("/api/workspace/add")
async def api_workspace_add(request: Request):
    body = await request.json()
    repo_path = str((body or {}).get("path", "")).strip()
    if not repo_path:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_PATH"})
    resolved = _resolve_repo_dir(repo_path)
    if not os.path.isdir(resolved):
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_PATH"})

    entry = _repo_entry(resolved)
    _upsert_workspace_repo(entry, set_active=True)

    ctx = _repo_ctx_from_dir(resolved)
    _ensure_ui_state(ctx)
    SEARCH_INDEX_CACHE.pop(ctx["repo_hash"], None)

    return {"ok": True, "repo_hash": entry["repo_hash"], "path": resolved, "name": entry["name"]}


@app.post("/api/repo_import/local")
async def api_repo_import_local(request: Request):
    body = await request.json()
    payload = body if isinstance(body, dict) else {}
    repo_path = str(payload.get("repo_path", "") or "").strip()
    display_name = str(payload.get("display_name", "") or "").strip()
    analyze_now = bool(payload.get("analyze", True))
    open_after_add = bool(payload.get("open_after_add", False))
    if not repo_path:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_PATH"})
    resolved = _resolve_repo_dir(repo_path)
    if not os.path.isdir(resolved):
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_PATH"})

    entry = _repo_entry_from_payload(
        {
            "path": resolved,
            "name": display_name or os.path.basename(resolved.rstrip("\\/")) or resolved,
            "source": "filesystem",
        }
    )
    ws_before = _load_workspaces()
    had_active = bool(str(ws_before.get("active_repo_hash", "") or ""))
    set_active = bool(open_after_add or not had_active)
    _upsert_workspace_repo(entry, set_active=set_active)
    ctx = _repo_ctx_from_dir(resolved)
    _ensure_ui_state(ctx)
    SEARCH_INDEX_CACHE.pop(ctx["repo_hash"], None)
    GRAPH_INDEX_CACHE.pop(ctx["repo_hash"], None)

    if not analyze_now:
        return {"ok": True, "analyzed": False, "repo_hash": entry["repo_hash"], "repo": entry}

    analyze_result = _cli_json(["analyze", "--path", resolved], timeout_sec=3600)
    if analyze_result.get("ok"):
        _upsert_workspace_repo(entry, set_active=set_active)
    return {
        "ok": bool(analyze_result.get("ok")),
        "analyzed": bool(analyze_result.get("ok")),
        "repo_hash": entry["repo_hash"],
        "repo": entry,
        "analyze_result": analyze_result,
    }


@app.post("/api/repo_import/github_add")
async def api_repo_import_github_add(request: Request):
    from analysis.utils.repo_fetcher import resolve_workspace_paths

    body = await request.json()
    payload = body if isinstance(body, dict) else {}
    repo_url = str(payload.get("repo_url", "") or "").strip()
    ref = str(payload.get("ref", "") or "").strip() or "main"
    mode = str(payload.get("mode", "") or "zip").strip().lower() or "zip"
    display_name = str(payload.get("display_name", "") or "").strip()
    open_after_add = bool(payload.get("open_after_add", False))
    # token is intentionally ignored here; it is never persisted.

    if not repo_url:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_GITHUB_URL", "message": "GitHub URL is required."})
    if mode not in {"zip", "git"}:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_MODE", "message": "Mode must be zip or git."})

    try:
        ws_paths = resolve_workspace_paths(repo_url, ref, mode)
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_GITHUB_URL", "message": str(e)})

    repo_dir = ws_paths.get("repo_dir", "")
    repo_name = display_name or ws_paths.get("repo_name", "") or os.path.basename(str(repo_dir).rstrip("\\/")) or "github_repo"
    entry = _repo_entry_from_payload(
        {
            "path": repo_dir,
            "name": repo_name,
            "source": "github",
            "repo_url": ws_paths.get("normalized_url", repo_url),
            "ref": ref,
            "mode": mode,
        }
    )
    ws_before = _load_workspaces()
    had_active = bool(str(ws_before.get("active_repo_hash", "") or ""))
    set_active = bool(open_after_add or not had_active)
    _upsert_workspace_repo(entry, set_active=set_active)
    return {"ok": True, "repo_hash": entry["repo_hash"], "repo": entry, "analyzed": False}


@app.post("/api/repo_import/github")
async def api_repo_import_github(request: Request):
    body = await request.json()
    payload = body if isinstance(body, dict) else {}
    repo_url = str(payload.get("repo_url", "") or "").strip()
    ref = str(payload.get("ref", "") or "").strip() or "main"
    mode = str(payload.get("mode", "") or "zip").strip().lower() or "zip"
    token = str(payload.get("token", "") or "")

    if not repo_url:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_GITHUB_URL"})
    if mode not in {"zip", "git"}:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_MODE"})

    args = ["analyze", "--github", repo_url, "--ref", ref, "--mode", mode]
    if token.strip():
        args.extend(["--token", token.strip()])
    analyze_result = _cli_json(args, timeout_sec=3600)
    if not analyze_result.get("ok"):
        return {
            "ok": False,
            "error": analyze_result.get("error", "ANALYZE_FAILED"),
            "message": analyze_result.get("message", "GitHub analyze failed"),
            "analyze_result": analyze_result,
        }

    repo_dir = str(analyze_result.get("repo_dir", "") or "").strip()
    if not repo_dir:
        return {"ok": False, "error": "MISSING_REPO_DIR", "analyze_result": analyze_result}

    name = os.path.basename(repo_dir.rstrip("\\/")) or repo_dir
    entry = _repo_entry_from_payload(
        {
            "path": repo_dir,
            "name": name,
            "source": "github",
            "repo_url": str(analyze_result.get("repo_url", repo_url) or repo_url),
            "ref": str(analyze_result.get("ref", ref) or ref),
            "mode": str(analyze_result.get("mode", mode) or mode),
        }
    )
    _upsert_workspace_repo(entry, set_active=True)
    ctx = _repo_ctx_from_dir(entry["path"])
    _ensure_ui_state(ctx)
    SEARCH_INDEX_CACHE.pop(ctx["repo_hash"], None)
    GRAPH_INDEX_CACHE.pop(ctx["repo_hash"], None)
    return {"ok": True, "repo_hash": entry["repo_hash"], "repo": entry, "analyze_result": analyze_result}


@app.post("/api/repo_analyze")
async def api_repo_analyze(request: Request):
    body = await request.json()
    payload = body if isinstance(body, dict) else {}
    repo_hash = str(payload.get("repo_hash", "") or "").strip()
    if not repo_hash:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_REPO_HASH"})

    ws = _ensure_default_workspace()
    repos = ws.get("repos", [])
    target = next((r for r in repos if isinstance(r, dict) and str(r.get("repo_hash", "")) == repo_hash), None)
    if not target:
        return JSONResponse(status_code=404, content={"ok": False, "error": "REPO_NOT_FOUND"})

    entry = _repo_entry_from_payload(target)
    source = entry.get("source", "filesystem")
    if source == "github":
        repo_url = str(entry.get("repo_url", "") or "").strip()
        ref = str(entry.get("ref", "") or "").strip() or "main"
        mode = str(entry.get("mode", "") or "zip")
        if not repo_url:
            return JSONResponse(status_code=400, content={"ok": False, "error": "MISSING_GITHUB_METADATA"})
        result = _cli_json(["analyze", "--github", repo_url, "--ref", ref, "--mode", mode], timeout_sec=3600)
    else:
        result = _cli_json(["analyze", "--path", entry["path"]], timeout_sec=3600)

    if result.get("ok"):
        _upsert_workspace_repo(entry, set_active=True)
    return {"ok": bool(result.get("ok")), "repo_hash": repo_hash, "analyze_result": result}


@app.post("/api/workspace/select")
async def api_workspace_select(request: Request):
    body = await request.json()
    repo_hash = str((body or {}).get("repo_hash", "")).strip()
    if not repo_hash:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_REPO_HASH"})
    ws = _load_workspaces()
    repos = ws.get("repos", [])
    target = next((r for r in repos if r.get("repo_hash") == repo_hash), None)
    if not target:
        return JSONResponse(status_code=404, content={"ok": False, "error": "REPO_NOT_FOUND"})

    ws["active_repo_hash"] = repo_hash
    target["last_opened"] = _now_utc()
    _save_workspaces(ws)

    ctx = _repo_ctx_from_dir(target["path"])
    _ensure_ui_state(ctx)
    return {"ok": True}


@app.post("/api/workspace/remove")
async def api_workspace_remove(request: Request):
    body = await request.json()
    repo_hash = str((body or {}).get("repo_hash", "")).strip()
    if not repo_hash:
        return JSONResponse(status_code=400, content={"ok": False, "error": "INVALID_REPO_HASH"})
    ws = _load_workspaces()
    repos = ws.get("repos", [])
    ws["repos"] = [r for r in repos if not (isinstance(r, dict) and str(r.get("repo_hash", "")) == repo_hash)]
    if str(ws.get("active_repo_hash", "") or "") == repo_hash:
        ws["active_repo_hash"] = ws["repos"][0]["repo_hash"] if ws["repos"] else ""
    _save_workspaces(ws)
    return {"ok": True}


@app.get("/api/ui_state")
def api_ui_state():
    ctx = _active_repo_ctx()
    if not ctx:
        return _no_active_repo_response()

    state = _normalize_ui_state(_ensure_ui_state(ctx))
    if state != _load_json(ctx["ui_state_path"], {}):
        _save_json(ctx["ui_state_path"], state)
    return {"ok": True, "state": state}


@app.post("/api/ui_state/update")
async def api_ui_state_update(request: Request):
    ctx = _active_repo_ctx()
    if not ctx:
        return _no_active_repo_response()

    body = await request.json()
    payload = body if isinstance(body, dict) else {}
    state = _normalize_ui_state(_ensure_ui_state(ctx))

    opened_symbol = str(payload.get("opened_symbol", "") or "").strip()
    opened_file = str(payload.get("opened_file", "") or "").strip()
    last_symbol = str(payload.get("last_symbol", "") or "").strip()

    if opened_symbol:
        state["recent_symbols"] = _push_recent(state.get("recent_symbols", []), opened_symbol, limit=20)
        state["last_symbol"] = opened_symbol
    elif last_symbol:
        state["last_symbol"] = last_symbol

    if opened_file:
        state["recent_files"] = _push_recent(state.get("recent_files", []), opened_file, limit=20)

    state["updated_at"] = _now_utc()
    _save_json(ctx["ui_state_path"], state)
    return {"ok": True}


@app.get("/api/meta")
def api_meta(repo: Optional[str] = Query(default=None)):
    ctx = _repo_ctx(repo) if repo else _active_repo_ctx()
    if not ctx:
        return _no_active_repo_response()
    if not _has_analysis_cache(ctx):
        return _missing_cache_response()

    manifest = _load_json(ctx["manifest_path"], {})
    explain = _load_json(ctx["explain_path"], {})
    resolved = _load_json(ctx["resolved_calls_path"], [])
    metrics = _load_json(ctx["metrics_path"], {})
    ui_state = _normalize_ui_state(_ensure_ui_state(ctx))

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
        "recent_symbols": ui_state.get("recent_symbols", [])[:10],
    }


@app.get("/api/architecture")
def api_architecture(repo: Optional[str] = Query(default=None)):
    ctx = _repo_ctx(repo) if repo else _active_repo_ctx()
    if not ctx:
        return _no_active_repo_response()
    if not _has_analysis_cache(ctx):
        return _missing_cache_response()

    architecture_metrics_path = os.path.join(ctx["cache_dir"], "architecture_metrics.json")
    dependency_cycles_path = os.path.join(ctx["cache_dir"], "dependency_cycles.json")

    missing = []
    if not os.path.exists(architecture_metrics_path):
        missing.append("architecture_metrics.json")
    if not os.path.exists(dependency_cycles_path):
        missing.append("dependency_cycles.json")
    if missing:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "MISSING_ARCHITECTURE_CACHE",
                "message": "Run: python cli.py api analyze --path <repo>",
                "missing_files": missing,
            },
        )

    return {
        "ok": True,
        "architecture_metrics": _load_json(architecture_metrics_path, {}),
        "dependency_cycles": _load_json(dependency_cycles_path, {}),
    }


@app.get("/api/repo_summary")
def api_repo_summary(repo: Optional[str] = Query(default=None)):
    ctx = _repo_ctx(repo) if repo else _active_repo_ctx()
    if not ctx:
        return _no_active_repo_response()
    if not _has_analysis_cache(ctx):
        return _missing_cache_response()

    path = os.path.join(ctx["cache_dir"], "repo_summary.json")
    if not os.path.exists(path):
        return JSONResponse(
            status_code=404,
            content={
                "ok": False,
                "error": "MISSING_REPO_SUMMARY",
                "message": "Repo summary not generated yet.",
            },
        )

    data = _load_json(path, {})
    mtime = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat()
    return {
        "ok": True,
        "repo_summary": data,
        "updated_at": mtime,
    }


@app.get("/api/risk_radar")
def api_risk_radar(repo: Optional[str] = Query(default=None)):
    ctx = _repo_ctx(repo) if repo else _active_repo_ctx()
    if not ctx:
        return _no_active_repo_response()
    if not _has_analysis_cache(ctx):
        return _missing_cache_response()

    path = os.path.join(ctx["cache_dir"], "risk_radar.json")
    if not os.path.exists(path):
        return JSONResponse(
            status_code=404,
            content={
                "ok": False,
                "error": "MISSING_RISK_RADAR",
                "message": "Risk radar not generated yet.",
            },
        )

    data = _load_json(path, {})
    mtime = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat()
    return {
        "ok": True,
        "risk_radar": data,
        "updated_at": mtime,
    }


@app.get("/api/tree")
def api_tree(repo: Optional[str] = Query(default=None)):
    ctx = _repo_ctx(repo) if repo else _active_repo_ctx()
    if not ctx:
        return _no_active_repo_response()
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
    ctx = _repo_ctx(repo) if repo else _active_repo_ctx()
    if not ctx:
        return _no_active_repo_response()
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
    module_scope_fqn: Optional[str] = None
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
        elif kind == "module":
            module_scope_fqn = fqn
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
    module_scope_outgoing_calls_count = 0
    if module_scope_fqn:
        module_scope_outgoing_calls_count = len(
            [c for c in resolved if c.get("caller_fqn") == module_scope_fqn]
        )

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
            "module_scope": {
                "fqn": module_scope_fqn,
                "outgoing_calls_count": module_scope_outgoing_calls_count,
            } if module_scope_fqn else None,
        },
        "symbol_fqns": sorted(symbol_fqns),
        "incoming_usages_count": len(incoming),
        "outgoing_calls_count": len(outgoing),
        "top_callers": top_callers,
        "top_callees": top_callees,
    }


@app.get("/api/symbol")
def api_symbol(fqn: str = Query(...), repo: Optional[str] = Query(default=None)):
    ctx = _repo_ctx(repo) if repo else _active_repo_ctx()
    if not ctx:
        return _no_active_repo_response()
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
    ctx = _repo_ctx(repo) if repo else _active_repo_ctx()
    if not ctx:
        return _no_active_repo_response()
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
    ctx = _repo_ctx(repo) if repo else _active_repo_ctx()
    if not ctx:
        return _no_active_repo_response()
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


@app.get("/api/graph")
def api_graph(
    fqn: Optional[str] = Query(default=None),
    file: Optional[str] = Query(default=None),
    depth: int = Query(default=1, ge=1, le=3),
    hide_builtins: bool = Query(default=True),
    hide_external: bool = Query(default=True),
    repo: Optional[str] = Query(default=None),
):
    ctx = _repo_ctx(repo) if repo else _active_repo_ctx()
    if not ctx:
        return _no_active_repo_response()
    if not _has_analysis_cache(ctx):
        return _missing_cache_response()

    graph = _build_graph_index(ctx)
    explain = graph["explain"]
    callees_map = graph["callees_map"]
    callers_map = graph["callers_map"]
    edge_counts = graph["edge_counts"]

    center_fqn = fqn.strip() if isinstance(fqn, str) else ""
    file_rel = file.replace("\\", "/").lstrip("/") if isinstance(file, str) else ""
    if not center_fqn and not file_rel:
        return JSONResponse(status_code=400, content={"ok": False, "error": "MISSING_GRAPH_TARGET"})

    seed_nodes: set = set()
    mode = "symbol"
    center = center_fqn
    if file_rel:
        mode = "file"
        center = file_rel
        target_abs = os.path.abspath(os.path.join(ctx["repo_dir"], file_rel))
        for sym_fqn, item in explain.items():
            loc_file = (item.get("location") or {}).get("file", "")
            if loc_file and _norm(loc_file) == _norm(target_abs):
                seed_nodes.add(sym_fqn)
        if not seed_nodes:
            return {
                "ok": True,
                "mode": "file",
                "center": center,
                "depth": depth,
                "seed_nodes": [],
                "nodes": [],
                "edges": [],
            }
    else:
        seed_nodes.add(center_fqn)

    visited = set(seed_nodes)
    frontier = set(seed_nodes)
    edges: set = set()

    for _ in range(max(1, min(3, depth))):
        next_frontier = set()
        for node in frontier:
            for callee in callees_map.get(node, []):
                edges.add((node, callee))
                if callee not in visited:
                    next_frontier.add(callee)
            for caller in callers_map.get(node, []):
                edges.add((caller, node))
                if caller not in visited:
                    next_frontier.add(caller)
        visited.update(next_frontier)
        frontier = next_frontier
        if not frontier:
            break

    def _include(node_id: str) -> bool:
        kind = _classify_symbol(node_id, explain)
        if hide_builtins and kind == "builtin":
            return False
        if hide_external and kind == "external":
            return False
        return True

    filtered_edges = [(src, dst) for (src, dst) in edges if _include(src) and _include(dst)]
    node_ids = set()
    for src, dst in filtered_edges:
        node_ids.add(src)
        node_ids.add(dst)
    for seed in seed_nodes:
        if _include(seed):
            node_ids.add(seed)

    nodes = []
    for node_id in sorted(node_ids):
        info = explain.get(node_id, {})
        nodes.append({
            "id": node_id,
            "label": _short_label(node_id),
            "subtitle": info.get("one_liner", ""),
            "kind": _classify_symbol(node_id, explain),
            "clickable": node_id in explain,
            "location": (info.get("location") or {}),
        })

    edges_payload = [
        {
            "from": src,
            "to": dst,
            "count": int(edge_counts.get((src, dst), 1)),
        }
        for (src, dst) in sorted(filtered_edges, key=lambda x: (x[0], x[1]))
    ]

    return {
        "ok": True,
        "mode": mode,
        "center": center,
        "depth": depth,
        "seed_nodes": sorted(seed_nodes),
        "nodes": nodes,
        "edges": edges_payload,
    }


@app.get("/api/impact")
def api_impact(
    target: str = Query(...),
    depth: int = Query(default=2, ge=1, le=4),
    max_nodes: int = Query(default=200, ge=1, le=500),
    repo: Optional[str] = Query(default=None),
):
    from analysis.graph.impact_analyzer import compute_impact

    ctx = _repo_ctx(repo) if repo else _active_repo_ctx()
    if not ctx:
        return _no_active_repo_response()
    if not _has_analysis_cache(ctx):
        return _missing_cache_response()

    architecture_metrics_path = os.path.join(ctx["cache_dir"], "architecture_metrics.json")
    if not os.path.exists(architecture_metrics_path):
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "MISSING_ANALYSIS",
                "message": MISSING_CACHE_MESSAGE,
            },
        )

    try:
        payload = compute_impact(
            cache_dir=ctx["cache_dir"],
            target=target,
            depth=depth,
            max_nodes=max_nodes,
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "IMPACT_FAILED", "message": str(e)},
        )
    return payload
