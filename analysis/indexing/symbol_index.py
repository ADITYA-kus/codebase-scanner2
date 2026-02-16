import ast
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class SymbolKind(Enum):
    MODULE = "module"
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    BUILTIN = "builtin"
    EXTERNAL = "external"


@dataclass
class SymbolInfo:
    """
    Represents a single symbol definition in the codebase.
    """
    name: str
    qualified_name: str
    kind: SymbolKind

    module: str
    file_path: str

    start_line: int
    end_line: int

    class_name: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


class SymbolIndex:
    """
    Global registry of all symbols across the codebase.
    """

    def __init__(self):
        self._symbols: List[SymbolInfo] = []

        # Fast lookup indexes
        self._by_name: Dict[str, List[SymbolInfo]] = {}
        self._by_fqn: Dict[Tuple[str, str], SymbolInfo] = {}

    # ----------------------------
    # Registration
    # ----------------------------
    def add_symbol(self, symbol: SymbolInfo):
        key = (symbol.module, symbol.qualified_name)

        self._symbols.append(symbol)
        self._by_fqn[key] = symbol
        self._by_name.setdefault(symbol.name, []).append(symbol)

    # ----------------------------
    # AST INGESTION (🔥 NEW)
    # ----------------------------
    def index_file(self, ast_tree: ast.AST, module: str, file_path: str):
        """
        Index all symbols found in a single AST tree.
        """
        module_end = self._module_end_line(ast_tree, file_path)
        has_defs_or_classes = any(isinstance(n, (ast.FunctionDef, ast.ClassDef)) for n in ast_tree.body)
        imported_libs = self._module_imports(ast_tree)

        module_symbol = SymbolInfo(
            name="<module>",
            qualified_name="<module>",
            kind=SymbolKind.MODULE,
            module=module,
            file_path=file_path,
            start_line=1,
            end_line=module_end,
            metadata={
                "imports": imported_libs,
                "has_defs_or_classes": has_defs_or_classes,
            },
        )
        self.add_symbol(module_symbol)

        for node in ast.walk(ast_tree):

            # -------- Top-level functions --------
            if isinstance(node, ast.FunctionDef):
                symbol = SymbolInfo(
                    name=node.name,
                    qualified_name=node.name,
                    kind=SymbolKind.FUNCTION,
                    module=module,
                    file_path=file_path,
                    start_line=node.lineno,
                    end_line=node.end_lineno,
                )
                self.add_symbol(symbol)

            # -------- Classes --------
            elif isinstance(node, ast.ClassDef):
                class_symbol = SymbolInfo(
                    name=node.name,
                    qualified_name=node.name,
                    kind=SymbolKind.CLASS,
                    module=module,
                    file_path=file_path,
                    start_line=node.lineno,
                    end_line=node.end_lineno,
                )
                self.add_symbol(class_symbol)

                # -------- Methods --------
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        method_symbol = SymbolInfo(
                            name=item.name,
                            qualified_name=f"{node.name}.{item.name}",
                            kind=SymbolKind.METHOD,
                            module=module,
                            file_path=file_path,
                            start_line=item.lineno,
                            end_line=item.end_lineno,
                            class_name=node.name,
                        )
                        self.add_symbol(method_symbol)

    def _module_end_line(self, ast_tree: ast.AST, file_path: str) -> int:
        end_line = 1
        for node in ast.walk(ast_tree):
            node_end = getattr(node, "end_lineno", None)
            node_start = getattr(node, "lineno", None)
            if isinstance(node_end, int):
                end_line = max(end_line, node_end)
            elif isinstance(node_start, int):
                end_line = max(end_line, node_start)

        if end_line <= 1:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    end_line = max(1, len(f.readlines()))
            except OSError:
                end_line = 1
        return end_line

    def _module_imports(self, ast_tree: ast.AST) -> List[str]:
        imports: List[str] = []
        for node in ast_tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = (alias.name or "").split(".")[0]
                    if base:
                        imports.append(base)
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[0]
                if mod:
                    imports.append(mod)
        # Stable unique order
        seen = set()
        unique: List[str] = []
        for item in imports:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique

    # ----------------------------
    # Lookup APIs
    # ----------------------------
    def get_by_name(self, name: str) -> List[SymbolInfo]:
        return self._by_name.get(name, [])

    def get(self, module: str, qualified_name: str) -> Optional[SymbolInfo]:
        return self._by_fqn.get((module, qualified_name))

    def all_symbols(self) -> List[SymbolInfo]:
        return list(self._symbols)

    # ----------------------------
    # Maintenance
    # ----------------------------
    def remove_by_file(self, file_path: str):
        remaining = [s for s in self._symbols if s.file_path != file_path]
        self._symbols = []
        self._by_name.clear()
        self._by_fqn.clear()
        for s in remaining:
            self.add_symbol(s)

    def symbols_for_file(self, file_path: str) -> List[SymbolInfo]:
        return [s for s in self._symbols if s.file_path == file_path]

    def snapshot(self) -> List[Dict]:
        return [
            {
                "name": s.name,
                "qualified_name": s.qualified_name,
                "kind": s.kind.value,
                "module": s.module,
                "file_path": s.file_path,
                "start_line": s.start_line,
                "end_line": s.end_line,
                "class_name": s.class_name,
                "metadata": s.metadata,
            }
            for s in self._symbols
        ]

    def load_snapshot(self, records: List[Dict]):
        self.clear()
        for r in records:
            self.add_symbol(
                SymbolInfo(
                    name=r["name"],
                    qualified_name=r["qualified_name"],
                    kind=SymbolKind(r["kind"]),
                    module=r["module"],
                    file_path=r["file_path"],
                    start_line=r["start_line"],
                    end_line=r["end_line"],
                    class_name=r.get("class_name"),
                    metadata=r.get("metadata", {}),
                )
            )

    def clear(self):
        self._symbols.clear()
        self._by_name.clear()
        self._by_fqn.clear()
