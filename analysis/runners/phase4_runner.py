# Orchestrates Phase-4 pipeline
from typing import Optional, Dict, Any

import os
import ast
import json
from analysis.indexing.symbol_index import SymbolIndex
from analysis.indexing.import_resolver import ImportResolver
from analysis.call_graph.cross_file_resolver import CrossFileResolver
from analysis.call_graph.call_extractor import extract_function_calls

# ✅ IMPORTANT: adjust this import if your file is located elsewhere
# Common locations in your project could be:
#   from analysis.core.import_extractor import extract_imports
#   from analysis.import_extractor import extract_imports
from analysis.core.import_extractor import extract_imports
from analysis.graph.callgraph_index import build_caller_fqn


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))  # points to /analysis


def collect_python_files(root_dir):
    IGNORE_DIRS = {"runners", "indexing", "call_graph", "utils", "core","graph","explain","doc","output","outputs"}  # adjust as needed

    py_files = []
    for root, _, files in os.walk(root_dir):
        parts = set(os.path.normpath(root).split(os.sep))
        if parts & IGNORE_DIRS:
            continue

        for file in files:
            if file.endswith(".py") and not file.startswith("__"):
                py_files.append(os.path.join(root, file))
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

    # Prefix with folder name so symbols don’t collide across repos
    repo_name = os.path.basename(repo_root.rstrip("\\/"))
    return f"{repo_name}.{rel}"



# def main():
#     print("\n=== Phase-4 Runner ===\n")

#     # --------------------------------------------------
#     # Step 1: Collect files
#     # --------------------------------------------------
#     python_files = collect_python_files(PROJECT_ROOT)



#     # --------------------------------------------------
#     # Step 2: Build Symbol Index + file->module map
#     # --------------------------------------------------
#     symbol_index = SymbolIndex()
#     file_module_map = {}

#     for file_path in python_files:
#         module_path = file_to_module(file_path, PROJECT_ROOT)
#         file_module_map[file_path] = module_path

#         tree = parse_ast(file_path)
#         symbol_index.index_file(tree, module_path, file_path)

#     # --------------------------------------------------
#     # Step 3: Resolve + Cache Imports per module
#     # --------------------------------------------------
#     import_resolver = ImportResolver(symbol_index)

#     for file_path in python_files:
#         module_path = file_module_map[file_path]
#         imports = extract_imports(file_path)

#         # ✅ store resolved imports in resolver cache
#         import_resolver.index_module_imports(module_path, imports)

#     # --------------------------------------------------
#     # Step 4: Extract Calls
#     # --------------------------------------------------
#     all_calls = []
#     for file_path in python_files:
#         all_calls.extend(extract_function_calls(file_path))

#     # --------------------------------------------------
#     # Step 5: Cross-file Resolution
#     # --------------------------------------------------
#     cross_resolver = CrossFileResolver(symbol_index, import_resolver)

#     resolved_calls = []
#     for call in all_calls:
#         call_file = call.get("file")
#         current_module = file_module_map.get(call_file)

#         symbol = cross_resolver.resolve_call(call, current_module)
#         caller_fqn = build_caller_fqn(call, current_module)
#         callee_fqn = f"{symbol.module}.{symbol.qualified_name}" if symbol else None

#         resolved_calls.append({
#             **call,
#             "caller_fqn": caller_fqn,
#             "callee_fqn": callee_fqn,
#             "resolved_target": callee_fqn,   
#         })
#     # --------------------------------------------------
#     # Step 6: Output
#     # --------------------------------------------------
#     print("Resolved Calls:\n")
#     for call in resolved_calls:
#         caller = call.get("caller_fqn")
#         callee = call.get("callee_fqn")
#         line = call.get("line")
#         target = call.get("resolved_target") or "UNRESOLVED"

#         print(f"{caller} (line {line}) -> {callee}")

#     # --------------------------------------------------
#     # Save output for Phase-5
#     # --------------------------------------------------
#     output_dir = os.path.join(PROJECT_ROOT, "output")
#     os.makedirs(output_dir, exist_ok=True)

#     out_path = os.path.join(output_dir, "resolved_calls.json")
#     with open(out_path, "w", encoding="utf-8") as f:
#         json.dump(resolved_calls, f, indent=2)

#     print(f"\nSaved: {out_path}\n")
#________________________________________________

def run(repo_dir: Optional[str] = None, output_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Phase-4 pipeline callable from CLI/VS Code.

    Args:
      repo_dir: directory to analyze (default: analysis/testing_repo)
      output_dir: directory to write outputs (default: analysis/output)

    Returns:
      dict with output path + counts
    """
    project_root = os.path.dirname(os.path.dirname(__file__))  # /analysis

    if repo_dir is None:
        repo_dir = os.path.join(project_root, "testing_repo")

    if output_dir is None:
        output_dir = os.path.join(project_root, "output")

    os.makedirs(output_dir, exist_ok=True)

    # ---- YOUR EXISTING PHASE-4 LOGIC START ----
    # 1) collect files
    python_files = collect_python_files(repo_dir)

    # 2) build SymbolIndex, ImportResolver, CrossFileResolver, etc.
    symbol_index = SymbolIndex()
    file_module_map = {}

    # Step 2: Build Symbol Index + file->module map
    # --------------------------------------------------

    for file_path in python_files:
        module_path = file_to_module(file_path, repo_dir)
        file_module_map[file_path] = module_path

        tree = parse_ast(file_path)
        symbol_index.index_file(tree, module_path, file_path)

    # Step 3: Resolve + Cache Imports per module
    # --------------------------------------------------
    import_resolver = ImportResolver(symbol_index)

    for file_path in python_files:
        module_path = file_module_map[file_path]
        imports = extract_imports(file_path)

        # ✅ store resolved imports in resolver cache
        import_resolver.index_module_imports(module_path, imports)

    # Step 4: Extract Calls
    # --------------------------------------------------
    all_calls = []
    for file_path in python_files:
        all_calls.extend(extract_function_calls(file_path))



    # produce resolved_calls list (list[dict])
    # Step 5: Cross-file Resolution
    # --------------------------------------------------
    cross_resolver = CrossFileResolver(symbol_index, import_resolver)

    resolved_calls = []
    for call in all_calls:
        call_file = call.get("file")
        current_module = file_module_map.get(call_file)

        symbol = cross_resolver.resolve_call(call, current_module)
        caller_fqn = build_caller_fqn(call, current_module)
        callee_fqn = f"{symbol.module}.{symbol.qualified_name}" if symbol else None

        resolved_calls.append({
            **call,
            "caller_fqn": caller_fqn,
            "callee_fqn": callee_fqn,
            "resolved_target": callee_fqn,   
        })
    # --------------------------------------------------

 # Step 6: Output
    # --------------------------------------------------
    print("Resolved Calls:\n")
    for call in resolved_calls:
        caller = call.get("caller_fqn")
        callee = call.get("callee_fqn")
        line = call.get("line")
        target = call.get("resolved_target") or "UNRESOLVED"

        # print(f"{caller} (line {line}) -> {callee}")

    # At the end save:
    resolved_calls_path = os.path.join(output_dir, "resolved_calls.json")
    with open(resolved_calls_path, "w", encoding="utf-8") as f:
        json.dump(resolved_calls, f, indent=2)
    # ---- YOUR EXISTING PHASE-4 LOGIC END ----

    return {
        "resolved_calls_path": resolved_calls_path,
        "total_calls": len(resolved_calls),
    }



def main():
    print("\n=== Phase-4 Runner ===\n")
    result = run()
    print(f"Saved: {result['resolved_calls_path']}")
    print(f"Total calls: {result['total_calls']}")
    print("\n=== Phase-4 Complete ===\n")



if __name__ == "__main__":
    main()


