A) Symbol Index

 SymbolIndex.index_file(ast_tree, module, file_path) indexes:

 top-level functions (qualified_name = func)

 classes (qualified_name = ClassName)

 methods (qualified_name = ClassName.method)

 Symbols are module-safe: lookup key uses (module, qualified_name)

 remove_by_file(file_path) removes all symbols from that file (no stale symbols)

B) Import Resolver

 resolve_imports(imports, current_module) supports:

 import x

 import x as y

 from a.b import c

 from a.b import c as d

 relative imports (level > 0)

 index_module_imports(module, imports) stores resolved imports

 get_imports(module) returns correct alias map (empty dict if none)

C) Cross-File Resolver

 Resolves in this order:

 self.method() → CurrentClass.method

 local function call foo() → module.foo

 imported symbol alias v() → import_map["v"]

 imported module attribute m.func() → import_map["m"] + func

 builtin → builtins.<name> (using hasattr(builtins, name))

 If unknown → returns None (no guessing)

D) Runner Output Contract (must not change in Phase-5)

 Runner prints each call with:

 caller name

 call line number

 callee name

 resolved target (or UNRESOLVED)

 For your test file, expected output pattern:

 __init__ -> info ==> <module>.Student.info

 info -> display ==> <module>.Student.display

 print ==> builtins.print

E) “Correct UNRESOLVED” list (these should NOT resolve to project symbols)

 stdlib methods like os.path.join unless indexed in project

 external libraries (numpy, pandas, sklearn) unless you later add external indexing

 dynamic calls (eval/exec/reflection)

F) Non-Functional (important)

 No file execution (static only)

 No network calls

 Does not crash on syntax errors (later improvement, Phase-5/6)