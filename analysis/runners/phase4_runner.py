# Orchestrates Phase-4 pipeline
from typing import Optional, Dict, Any, List, Set

import os
import ast
import json

from analysis.indexing.symbol_index import SymbolIndex
from analysis.indexing.import_resolver import ImportResolver
from analysis.call_graph.cross_file_resolver import CrossFileResolver
from analysis.call_graph.call_extractor import extract_function_calls
from analysis.core.import_extractor import extract_imports
from analysis.graph.callgraph_index import build_caller_fqn
from analysis.utils.cache_manager import collect_fingerprints, diff_fingerprints, load_manifest


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))  # points to /analysis


def collect_python_files(root_dir):
    ignore_dirs = {
        "runners", "indexing", "call_graph", "utils", "core",
        "graph", "explain", "doc", "output", "outputs",
    }
    py_files = []
    for root, _, files in os.walk(root_dir):
        parts = set(os.path.normpath(root).split(os.sep))
        if parts & ignore_dirs:
            continue
        for file_name in files:
            if file_name.endswith(".py") and not file_name.startswith("__"):
                py_files.append(os.path.join(root, file_name))
    return py_files


def parse_ast(file_path: str):
    with open(file_path, "r", encoding="utf-8") as f:
        return ast.parse(f.read())


def file_to_module(file_path: str, repo_root: str) -> str:
    repo_root = os.path.abspath(repo_root)
    file_path = os.path.abspath(file_path)

    rel = os.path.relpath(file_path, repo_root)
    rel = rel.replace(os.sep, ".")
    if rel.endswith(".py"):
        rel = rel[:-3]

    repo_name = os.path.basename(repo_root.rstrip("\\/"))
    return f"{repo_name}.{rel}"


def _load_previous_resolved_calls(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _rel_to_abs(repo_dir: str, rel_path: str) -> str:
    return os.path.abspath(os.path.join(repo_dir, rel_path.replace("/", os.sep)))


def run(repo_dir: Optional[str] = None, output_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Phase-4 pipeline callable from CLI/VS Code.
    """
    project_root = os.path.dirname(os.path.dirname(__file__))

    if repo_dir is None:
        repo_dir = os.path.join(project_root, "testing_repo")
    repo_dir = os.path.abspath(repo_dir)

    if output_dir is None:
        output_dir = os.path.join(project_root, "output")
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    python_files = [os.path.abspath(p) for p in collect_python_files(repo_dir)]
    file_module_map = {file_path: file_to_module(file_path, repo_dir) for file_path in python_files}

    current_fingerprints = collect_fingerprints(repo_dir)
    previous_manifest = load_manifest(repo_dir)
    previous_fingerprints = previous_manifest.get("fingerprints", {})
    delta = diff_fingerprints(previous_fingerprints, current_fingerprints)

    changed_rel_files = set(delta["added"] + delta["modified"] + delta["removed"])
    changed_existing_abs: Set[str] = set()
    removed_abs: Set[str] = set()
    for rel_path in delta["added"] + delta["modified"]:
        abs_path = _rel_to_abs(repo_dir, rel_path)
        if os.path.exists(abs_path):
            changed_existing_abs.add(abs_path)
    for rel_path in delta["removed"]:
        removed_abs.add(_rel_to_abs(repo_dir, rel_path))

    symbol_index = SymbolIndex()
    import_resolver = ImportResolver(symbol_index)

    previous_symbol_snapshot = previous_manifest.get("symbol_snapshot", [])
    previous_import_snapshot = previous_manifest.get("imports_snapshot", {})
    full_rebuild = (not previous_manifest) or (not previous_symbol_snapshot)

    if not full_rebuild:
        symbol_index.load_snapshot(previous_symbol_snapshot)
        import_resolver.load_imports_by_module(previous_import_snapshot)

    if full_rebuild:
        for file_path in python_files:
            module_path = file_module_map[file_path]
            tree = parse_ast(file_path)
            symbol_index.index_file(tree, module_path, file_path)
            import_resolver.index_module_imports(module_path, extract_imports(file_path))
    else:
        old_module_map = previous_manifest.get("file_module_map", {})
        for file_path in removed_abs:
            symbol_index.remove_by_file(file_path)
            old_module = old_module_map.get(file_path)
            if old_module:
                import_resolver.clear_module(old_module)

        for file_path in changed_existing_abs:
            module_path = file_module_map[file_path]
            symbol_index.remove_by_file(file_path)
            tree = parse_ast(file_path)
            symbol_index.index_file(tree, module_path, file_path)
            import_resolver.index_module_imports(module_path, extract_imports(file_path))

    changed_symbol_fqns: Set[str] = set()
    for record in previous_symbol_snapshot:
        old_file = record.get("file_path")
        if old_file in changed_existing_abs or old_file in removed_abs:
            changed_symbol_fqns.add(f"{record.get('module')}.{record.get('qualified_name')}")
    for file_path in changed_existing_abs:
        for symbol in symbol_index.symbols_for_file(file_path):
            changed_symbol_fqns.add(f"{symbol.module}.{symbol.qualified_name}")

    resolved_calls_path = os.path.join(output_dir, "resolved_calls.json")
    previous_resolved_calls = _load_previous_resolved_calls(resolved_calls_path)

    impacted_files: Set[str] = set()
    if full_rebuild or not previous_resolved_calls:
        impacted_files.update(python_files)
    else:
        impacted_files.update(changed_existing_abs)
        for call in previous_resolved_calls:
            call_file = call.get("file")
            if not call_file:
                continue
            abs_call_file = os.path.abspath(call_file)
            if not os.path.exists(abs_call_file):
                continue
            if call.get("callee_fqn") in changed_symbol_fqns:
                impacted_files.add(abs_call_file)

    cross_resolver = CrossFileResolver(symbol_index, import_resolver)

    recalculated_calls: List[dict] = []
    for file_path in sorted(impacted_files):
        current_module = file_module_map.get(file_path)
        if not current_module:
            continue
        for call in extract_function_calls(file_path):
            symbol = cross_resolver.resolve_call(call, current_module)
            caller_fqn = build_caller_fqn(call, current_module)
            callee_fqn = f"{symbol.module}.{symbol.qualified_name}" if symbol else None
            recalculated_calls.append({
                **call,
                "caller_fqn": caller_fqn,
                "callee_fqn": callee_fqn,
                "resolved_target": callee_fqn,
            })

    if full_rebuild or not previous_resolved_calls:
        resolved_calls = recalculated_calls
    else:
        excluded_files = set(impacted_files) | removed_abs
        preserved_calls = [
            call for call in previous_resolved_calls
            if os.path.abspath(call.get("file", "")) not in excluded_files
            and os.path.exists(call.get("file", ""))
        ]
        resolved_calls = preserved_calls + recalculated_calls

    with open(resolved_calls_path, "w", encoding="utf-8") as f:
        json.dump(resolved_calls, f, indent=2)

    return {
        "resolved_calls_path": resolved_calls_path,
        "total_calls": len(resolved_calls),
        "incremental": not full_rebuild,
        "reindexed_files": len(changed_existing_abs) if not full_rebuild else len(python_files),
        "impacted_files": len(impacted_files),
        "changed_files_detected": len(changed_rel_files),
        "symbol_snapshot": symbol_index.snapshot(),
        "imports_snapshot": import_resolver.snapshot_imports_by_module(),
        "file_module_map": file_module_map,
    }


def main():
    print("\n=== Phase-4 Runner ===\n")
    result = run()
    print(f"Saved: {result['resolved_calls_path']}")
    print(f"Total calls: {result['total_calls']}")
    print("\n=== Phase-4 Complete ===\n")


if __name__ == "__main__":
    main()
