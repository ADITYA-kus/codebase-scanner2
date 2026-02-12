import argparse
import json
import os
import sys
from typing import Dict, Any, List, Tuple

def print_json(obj) -> None:
    sys.stdout.write(json.dumps(obj, indent=2))
    sys.stdout.write("\n")



def _analysis_root() -> str:
    # cli.py is at project root; analysis/ is sibling
    return os.path.join(os.path.dirname(__file__), "analysis")


def _explain_json_path() -> str:
    return os.path.join(_analysis_root(), "output", "explain.json")


def load_explain_db() -> Dict[str, Any]:
    path = _explain_json_path()
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"explain.json not found at:\n  {path}\n\n"
            "Run:\n  python -m analysis.explain.explain_runner\n"
            "after generating resolved_calls.json from Phase-4 runner."
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


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
    db = load_explain_db()
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
    db = load_explain_db()
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
    db = load_explain_db()
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
    db = load_explain_db()
    fqn = args.fqn

    if fqn not in db:
        suggestions = suggest_keys(db, fqn, k=8)
        print_json({
            "ok": False,
            "error": "NOT_FOUND",
            "fqn": fqn,
            "suggestions": suggestions
        })
        return 1

    print_json({
        "ok": True,
        "result": db[fqn]
    })
    return 0


def api_search(args) -> int:
    db = load_explain_db()
    q = args.query.lower()
    matches = [k for k in db.keys() if q in k.lower()]
    matches.sort()

    print_json({
        "ok": True,
        "query": args.query,
        "count": len(matches),
        "results": matches[:args.limit],
        "truncated": len(matches) > args.limit
    })
    return 0


def api_list(args) -> int:
    db = load_explain_db()
    keys = sorted(db.keys())

    if args.module:
        prefix = args.module.strip()
        keys = [k for k in keys if k.startswith(prefix)]

    print_json({
        "ok": True,
        "module": args.module,
        "count": len(keys),
        "results": keys[:args.limit],
        "truncated": len(keys) > args.limit
    })
    return 0


def api_status(args) -> int:
    path = _explain_json_path()
    if not os.path.exists(path):
        print_json({
            "ok": False,
            "error": "EXPLAIN_JSON_MISSING",
            "path": path
        })
        return 1

    # lightweight stats (no full load needed, but we can load safely)
    db = load_explain_db()
    print_json({
        "ok": True,
        "path": path,
        "symbols": len(db)
    })
    return 0


def api_analyze(args) -> int:
    from analysis.runners.phase4_runner import run as run_phase4
    from analysis.explain.explain_runner import run as run_explain

    # For now allow --path as repo_dir; output stays default
    repo_dir = args.path

    try:
        r1 = run_phase4(repo_dir=repo_dir)
        r2 = run_explain(repo_dir=repo_dir)
    except Exception as e:
        print_json({"ok": False, "error": "ANALYZE_FAILED", "message": str(e)})
        return 1

    print_json({
        "ok": True,
        **r1,
        **r2
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
    p_explain.set_defaults(func=cmd_explain)

    p_search = sub.add_parser("search", help="Search symbols by substring")
    p_search.add_argument("query", help="Search keyword (case-insensitive)")
    p_search.add_argument("--limit", type=int, default=30, help="Max results to show")
    p_search.set_defaults(func=cmd_search)

    p_list = sub.add_parser("list", help="List all symbols (optionally filter by module prefix)")
    p_list.add_argument("--module", default=None, help="Module prefix filter (e.g. testing_repo.test)")
    p_list.add_argument("--limit", type=int, default=50, help="Max results to show")
    p_list.set_defaults(func=cmd_list)



    # -------------------------
    # API (JSON stdout) commands
    # -------------------------
    p_api = sub.add_parser("api", help="Machine-readable JSON API over explain.json")
    api_sub = p_api.add_subparsers(dest="api_command", required=True)

    p_api_explain = api_sub.add_parser("explain", help="Return JSON explanation for one symbol")
    p_api_explain.add_argument("fqn", help="Fully-qualified symbol name")
    p_api_explain.set_defaults(func=api_explain)

    p_api_search = api_sub.add_parser("search", help="Search symbols by substring (JSON)")
    p_api_search.add_argument("query", help="Search keyword")
    p_api_search.add_argument("--limit", type=int, default=50)
    p_api_search.set_defaults(func=api_search)

    p_api_list = api_sub.add_parser("list", help="List all symbols (JSON)")
    p_api_list.add_argument("--module", default=None)
    p_api_list.add_argument("--limit", type=int, default=200)
    p_api_list.set_defaults(func=api_list)

    p_api_status = api_sub.add_parser("status", help="Explain DB status (JSON)")
    p_api_status.set_defaults(func=api_status)

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


