import argparse
import json
import os
import sys
from typing import Dict, Any, List, Optional, Tuple

def print_json(obj) -> None:
    sys.stdout.write(json.dumps(obj, indent=2))
    sys.stdout.write("\n")

MISSING_ANALYSIS_MESSAGE = "Run: python cli.py api analyze --path <repo>"
ANALYSIS_VERSION = "2.2"



def _analysis_root() -> str:
    # cli.py is at project root; analysis/ is sibling
    return os.path.join(os.path.dirname(__file__), "analysis")


def _build_project_tree_snapshot(repo_dir: str) -> Dict[str, Any]:
    repo_dir = os.path.abspath(repo_dir)
    ignore_dirs = {".git", ".codemap_cache", "__pycache__", ".venv", "venv", "node_modules"}
    root = {
        "name": os.path.basename(repo_dir.rstrip("\\/")) or repo_dir,
        "type": "directory",
        "path": "",
        "children": [],
    }
    nodes: Dict[str, Dict[str, Any]] = {"": root}

    for current_root, dirs, files in os.walk(repo_dir):
        dirs[:] = sorted([d for d in dirs if d not in ignore_dirs and not d.startswith(".")])
        files = sorted([f for f in files if not f.startswith(".")])

        rel_root = os.path.relpath(current_root, repo_dir)
        rel_root = "" if rel_root == "." else rel_root.replace("\\", "/")
        parent = nodes[rel_root]

        for d in dirs:
            rel_path = f"{rel_root}/{d}" if rel_root else d
            node = {"name": d, "type": "directory", "path": rel_path, "children": []}
            parent["children"].append(node)
            nodes[rel_path] = node

        for f in files:
            rel_path = f"{rel_root}/{f}" if rel_root else f
            parent["children"].append({"name": f, "type": "file", "path": rel_path})

    return root


def resolve_repo_paths(repo_dir: Optional[str]) -> Dict[str, str]:
    if not repo_dir:
        output_dir = os.path.join(_analysis_root(), "output")
        return {
            "repo_dir": "",
            "cache_dir": output_dir,
            "explain_path": os.path.join(output_dir, "explain.json"),
            "resolved_calls_path": os.path.join(output_dir, "resolved_calls.json"),
            "llm_cache_path": os.path.join(output_dir, "llm_cache.json"),
        }

    repo_candidate = os.path.abspath(repo_dir)
    if not os.path.exists(repo_candidate):
        alt_candidate = os.path.abspath(os.path.join(_analysis_root(), repo_dir))
        if os.path.exists(alt_candidate):
            repo_candidate = alt_candidate

    from analysis.utils.cache_manager import get_cache_dir
    cache_dir = get_cache_dir(repo_candidate)
    return {
        "repo_dir": repo_candidate,
        "cache_dir": cache_dir,
        "explain_path": os.path.join(cache_dir, "explain.json"),
        "resolved_calls_path": os.path.join(cache_dir, "resolved_calls.json"),
        "llm_cache_path": os.path.join(cache_dir, "llm_cache.json"),
    }


def load_explain_db(repo: Optional[str] = None) -> Dict[str, Any]:
    paths = resolve_repo_paths(repo)
    path = paths["explain_path"]
    if not os.path.exists(path):
        hint = (
            "Run:\n  python cli.py api analyze --path <repo>\n"
            "to build repo-scoped cache before querying with --repo."
            if repo else
            "Run:\n  python -m analysis.explain.explain_runner\n"
            "after generating resolved_calls.json from Phase-4 runner."
        )
        raise FileNotFoundError(
            f"explain.json not found at:\n  {path}\n\n"
            f"{hint}"
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _symbol_payload(item: Dict[str, Any], fallback_fqn: str) -> Dict[str, Any]:
    location = item.get("location") or {}
    return {
        "fqn": item.get("fqn", fallback_fqn),
        "one_liner": item.get("one_liner", ""),
        "details": item.get("details", []),
        "tags": item.get("tags", []),
        "location": {
            "file": location.get("file", ""),
            "start_line": location.get("start_line", -1),
            "end_line": location.get("end_line", -1),
        },
    }


def suggest_keys(db: Dict[str, Any], query: str, k: int = 5) -> List[str]:
    q = query.lower()
    # simple scoring: substring + shared suffix parts
    scored: List[Tuple[int, str]] = []
    for key in db.keys():
        kl = key.lower()
        score = 0
        if q in kl:
            score += 10
        # bonus for matching last segment(s)
        q_parts = q.split(".")
        k_parts = kl.split(".")
        common_suffix = 0
        while common_suffix < min(len(q_parts), len(k_parts)):
            if q_parts[-1 - common_suffix] == k_parts[-1 - common_suffix]:
                common_suffix += 1
            else:
                break
        score += common_suffix * 3
        if score > 0:
            scored.append((score, key))
    scored.sort(reverse=True, key=lambda x: x[0])
    return [s[1] for s in scored[:k]]


def cmd_explain(args) -> int:
    db = load_explain_db(args.repo)
    fqn = args.fqn

    if fqn not in db:
        print(f"\n❌ Not found: {fqn}\n")
        suggestions = suggest_keys(db, fqn, k=8)
        if suggestions:
            print("Did you mean:")
            for s in suggestions:
                print(f"  - {s}")
        else:
            print("No similar symbols found. Try: python cli.py search <keyword>")
        print()
        return 1

    item = db[fqn]

    print("\n" + "=" * 80)
    print(f"{item.get('fqn', fqn)}")
    print("-" * 80)
    print(item.get("one_liner", ""))
    print()

    details = item.get("details", [])
    if details:
        for d in details:
            print(f"- {d}")

    tags = item.get("tags", [])
    if tags:
        print("\nTags: " + ", ".join(tags))

    print("=" * 80 + "\n")
    return 0


def cmd_search(args) -> int:
    db = load_explain_db(args.repo)
    q = args.query.lower()

    matches = [k for k in db.keys() if q in k.lower()]
    matches.sort()

    limit = args.limit
    print(f"\nFound {len(matches)} matches for '{args.query}':\n")
    for k in matches[:limit]:
        print(f"- {k}")

    if len(matches) > limit:
        print(f"\n...and {len(matches) - limit} more. Use --limit to increase.")
    print()
    return 0


def cmd_list(args) -> int:
    db = load_explain_db(args.repo)
    keys = sorted(db.keys())

    if args.module:
        prefix = args.module.strip()
        keys = [k for k in keys if k.startswith(prefix)]

    limit = args.limit
    print(f"\nListing {min(len(keys), limit)} of {len(keys)} symbols:\n")
    for k in keys[:limit]:
        print(f"- {k}")

    if len(keys) > limit:
        print(f"\n...and {len(keys) - limit} more. Use --limit to increase.")
    print()
    return 0


def api_explain(args) -> int:
    paths = resolve_repo_paths(args.repo)
    if args.repo and not os.path.exists(paths["explain_path"]):
        print_json({
            "ok": False,
            "error": "MISSING_ANALYSIS",
            "message": MISSING_ANALYSIS_MESSAGE,
        })
        return 1

    db = load_explain_db(args.repo)
    fqn = args.fqn

    if fqn not in db:
        print_json({
            "ok": False,
            "error": "NOT_FOUND",
            "fqn": fqn,
        })
        return 1

    print_json({
        "ok": True,
        "result": _symbol_payload(db[fqn], fqn)
    })
    return 0


def api_search(args) -> int:
    paths = resolve_repo_paths(args.repo)
    if args.repo and not os.path.exists(paths["explain_path"]):
        print_json({
            "ok": False,
            "error": "MISSING_ANALYSIS",
            "message": MISSING_ANALYSIS_MESSAGE,
        })
        return 1

    db = load_explain_db(args.repo)
    q = args.query.lower()
    matches = [k for k in db.keys() if q in k.lower()]
    matches.sort()
    results = matches[:args.limit]
    print_json({
        "ok": True,
        "query": args.query,
        "count": len(matches),
        "results": results,
        "truncated": len(matches) > args.limit
    })
    return 0


def api_list(args) -> int:
    paths = resolve_repo_paths(args.repo)
    if args.repo and not os.path.exists(paths["explain_path"]):
        print_json({
            "ok": False,
            "error": "MISSING_ANALYSIS",
            "message": MISSING_ANALYSIS_MESSAGE,
        })
        return 1

    db = load_explain_db(args.repo)
    keys = sorted(db.keys())

    if args.module:
        prefix = args.module.strip()
        keys = [k for k in keys if k.startswith(prefix)]

    results = keys[:args.limit]
    print_json({
        "ok": True,
        "module": args.module,
        "count": len(keys),
        "results": results,
        "truncated": len(keys) > args.limit
    })
    return 0


def api_status(args) -> int:
    path = resolve_repo_paths(args.repo)["explain_path"]
    if not os.path.exists(path):
        print_json({
            "ok": False,
            "error": "EXPLAIN_JSON_MISSING",
            "path": path
        })
        return 1

    # lightweight stats (no full load needed, but we can load safely)
    db = load_explain_db(args.repo)
    print_json({
        "ok": True,
        "path": path,
        "symbols": len(db)
    })
    return 0


def api_llm_explain(args) -> int:
    from analysis.explain.ai_client import llm_explain_symbol

    paths = resolve_repo_paths(args.repo)
    if not os.path.exists(paths["explain_path"]):
        print_json({
            "ok": False,
            "error": "MISSING_ANALYSIS",
            "message": MISSING_ANALYSIS_MESSAGE,
        })
        return 1

    result = llm_explain_symbol(fqn=args.fqn, repo_dir=paths["repo_dir"], no_cache=args.no_cache)
    print_json(result)
    return 0 if result.get("ok") else 1


def api_analyze(args) -> int:
    from analysis.runners.phase4_runner import run as run_phase4
    from analysis.explain.explain_runner import run as run_explain
    from analysis.graph.callgraph_index import write_hub_metrics_from_resolved_calls
    from analysis.utils.cache_manager import (
        build_manifest,
        collect_fingerprints,
        diff_fingerprints,
        get_cache_dir,
        load_manifest,
        save_manifest,
        should_rebuild,
    )

    repo_dir = resolve_repo_paths(args.path)["repo_dir"]
    cache_dir = get_cache_dir(repo_dir)
    os.makedirs(cache_dir, exist_ok=True)

    resolved_calls_path = os.path.join(cache_dir, "resolved_calls.json")
    explain_path = os.path.join(cache_dir, "explain.json")
    analysis_metrics_path = os.path.join(cache_dir, "analysis_metrics.json")
    llm_cache_path = os.path.join(cache_dir, "llm_cache.json")
    project_tree_path = os.path.join(cache_dir, "project_tree.json")

    previous_manifest = load_manifest(repo_dir)
    previous_fingerprints = previous_manifest.get("fingerprints", {})
    current_fingerprints = collect_fingerprints(repo_dir)
    delta = diff_fingerprints(previous_fingerprints, current_fingerprints)
    version_mismatch = previous_manifest.get("analysis_version") != ANALYSIS_VERSION

    rebuild_required = should_rebuild(repo_dir, analysis_version=ANALYSIS_VERSION)
    r1 = {}
    r2 = {}
    metrics = {}

    try:
        if rebuild_required:
            r1 = run_phase4(
                repo_dir=repo_dir,
                output_dir=cache_dir,
                force_rebuild=version_mismatch,
            )
            r2 = run_explain(repo_dir=repo_dir, output_dir=cache_dir)
            resolved_calls_path = r1.get("resolved_calls_path", resolved_calls_path)
            metrics = write_hub_metrics_from_resolved_calls(
                resolved_calls_path=resolved_calls_path,
                output_path=analysis_metrics_path,
            )
            save_manifest(
                repo_dir,
                build_manifest(
                    repo_dir,
                    current_fingerprints,
                    metadata={
                        "analysis_version": ANALYSIS_VERSION,
                        "symbol_snapshot": r1.get("symbol_snapshot", []),
                        "imports_snapshot": r1.get("imports_snapshot", {}),
                        "file_module_map": r1.get("file_module_map", {}),
                        "metrics_summary": {
                            "critical_apis": len(metrics.get("critical_apis", [])),
                            "orchestrators": len(metrics.get("orchestrators", [])),
                        },
                    },
                ),
            )
            tree_snapshot = _build_project_tree_snapshot(repo_dir)
            with open(project_tree_path, "w", encoding="utf-8") as f:
                json.dump(tree_snapshot, f, indent=2)
        elif os.path.exists(resolved_calls_path):
            metrics = write_hub_metrics_from_resolved_calls(
                resolved_calls_path=resolved_calls_path,
                output_path=analysis_metrics_path,
            )
            if not os.path.exists(project_tree_path):
                tree_snapshot = _build_project_tree_snapshot(repo_dir)
                with open(project_tree_path, "w", encoding="utf-8") as f:
                    json.dump(tree_snapshot, f, indent=2)
    except Exception as e:
        print_json({"ok": False, "error": "ANALYZE_FAILED", "message": str(e)})
        return 1

    print_json({
        "ok": True,
        "cached": not rebuild_required,
        "changed_files": delta["changed_files"],
        "incremental": False if version_mismatch else r1.get("incremental", False),
        "reindexed_files": r1.get("reindexed_files", 0),
        "impacted_files": r1.get("impacted_files", 0),
        "analysis_version": ANALYSIS_VERSION,
        "version_mismatch_rebuild": bool(version_mismatch and rebuild_required),
        "cache_dir": cache_dir,
        "resolved_calls_path": r1.get("resolved_calls_path", resolved_calls_path),
        "explain_path": r2.get("explain_path", explain_path),
        "analysis_metrics_path": analysis_metrics_path,
        "llm_cache_path": llm_cache_path,
        "project_tree_path": project_tree_path,
        "critical_apis": len(metrics.get("critical_apis", [])),
        "orchestrators": len(metrics.get("orchestrators", [])),
    })
    return 0



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codemap-ai",
        description="CodeMap AI CLI (Phase-5): query explain.json"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_explain = sub.add_parser("explain", help="Explain a symbol by fully-qualified name")
    p_explain.add_argument("fqn", help="Fully-qualified symbol name (e.g. testing_repo.test.Student.display)")
    p_explain.add_argument("--repo", default=None, help="Repository directory to read repo-scoped cached explain.json")
    p_explain.set_defaults(func=cmd_explain)

    p_search = sub.add_parser("search", help="Search symbols by substring")
    p_search.add_argument("query", help="Search keyword (case-insensitive)")
    p_search.add_argument("--repo", default=None, help="Repository directory to read repo-scoped cached explain.json")
    p_search.add_argument("--limit", type=int, default=30, help="Max results to show")
    p_search.set_defaults(func=cmd_search)

    p_list = sub.add_parser("list", help="List all symbols (optionally filter by module prefix)")
    p_list.add_argument("--module", default=None, help="Module prefix filter (e.g. testing_repo.test)")
    p_list.add_argument("--repo", default=None, help="Repository directory to read repo-scoped cached explain.json")
    p_list.add_argument("--limit", type=int, default=50, help="Max results to show")
    p_list.set_defaults(func=cmd_list)



    # -------------------------
    # API (JSON stdout) commands
    # -------------------------
    p_api = sub.add_parser("api", help="Machine-readable JSON API over explain.json")
    api_sub = p_api.add_subparsers(dest="api_command", required=True)

    p_api_explain = api_sub.add_parser("explain", help="Return JSON explanation for one symbol")
    p_api_explain.add_argument("fqn", help="Fully-qualified symbol name")
    p_api_explain.add_argument("--repo", default=None, help="Repository directory to read repo-scoped cached explain.json")
    p_api_explain.set_defaults(func=api_explain)

    p_api_search = api_sub.add_parser("search", help="Search symbols by substring (JSON)")
    p_api_search.add_argument("query", help="Search keyword")
    p_api_search.add_argument("--repo", default=None, help="Repository directory to read repo-scoped cached explain.json")
    p_api_search.add_argument("--limit", type=int, default=50)
    p_api_search.set_defaults(func=api_search)

    p_api_list = api_sub.add_parser("list", help="List all symbols (JSON)")
    p_api_list.add_argument("--module", default=None)
    p_api_list.add_argument("--repo", default=None, help="Repository directory to read repo-scoped cached explain.json")
    p_api_list.add_argument("--limit", type=int, default=200)
    p_api_list.set_defaults(func=api_list)

    p_api_status = api_sub.add_parser("status", help="Explain DB status (JSON)")
    p_api_status.add_argument("--repo", default=None, help="Repository directory to read repo-scoped cached explain.json")
    p_api_status.set_defaults(func=api_status)

    p_api_llm_explain = api_sub.add_parser("llm_explain", help="LLM-enhanced architecture explanation for one symbol")
    p_api_llm_explain.add_argument("fqn", help="Fully-qualified symbol name")
    p_api_llm_explain.add_argument("--repo", required=True, help="Repository directory to analyze")
    p_api_llm_explain.add_argument("--no-cache", action="store_true", help="Bypass read-cache for this request")
    p_api_llm_explain.set_defaults(func=api_llm_explain)

    p_api_analyze = api_sub.add_parser("analyze", help="Run Phase-4 and explain generation")
    p_api_analyze.add_argument("--path", default=".", help="Repository directory to analyze")
    p_api_analyze.set_defaults(func=api_analyze)


    return parser
def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())


