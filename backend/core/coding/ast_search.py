"""
AST 搜索服务 — 基于 tree-sitter-languages 的多语言结构化代码搜索。

支持 60+ 语言的 AST 解析，提供：
- 函数/类/类型定义搜索（search_definitions）
- 变量/函数引用搜索（search_references）
- 文件结构概览（get_structure，分类为 imports/classes/functions/top_level）
- 通用正则模式搜索（search_pattern，跨语言文本匹配）

行号约定: 1-based（与原 Python ast 模块一致），列号: 0-based。

依赖: tree-sitter-languages>=1.10, tree-sitter>=0.21,<0.22
"""
import re
import warnings
from pathlib import Path
from typing import Any, Iterator, Optional

from loguru import logger

# 抑制 tree_sitter_languages 内部使用旧版 Language(path, name) 触发的弃用告警
warnings.filterwarnings("ignore", category=FutureWarning, module="tree_sitter")

try:
    from tree_sitter_languages import get_language, get_parser

    _TREE_SITTER_AVAILABLE: bool = True
except ImportError as _import_exc:  # pragma: no cover - 依赖缺失时降级
    _TREE_SITTER_AVAILABLE = False
    logger.warning(
        f"[ast_search] tree-sitter-languages 未安装，AST 搜索将不可用: {_import_exc}"
    )


# ===== 文件扩展名 → tree-sitter 语言名映射 =====
# 仅包含 tree-sitter-languages 1.10 已预编译 parser 的语言
_EXT_TO_LANG: dict[str, str] = {
    # Python 系
    ".py": "python",
    ".pyi": "python",
    ".pyw": "python",
    # Web/JS 系
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    # 系统语言
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".cppm": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".rs": "rust",
    ".go": "go",
    ".zig": "zig",
    ".nim": "nim",
    # JVM 系
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".sc": "scala",
    ".groovy": "groovy",
    ".gradle": "groovy",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".cljc": "clojure",
    # .NET 系
    ".cs": "c_sharp",
    ".fs": "fsharp",
    ".fsx": "fsharp",
    # 脚本语言
    ".rb": "ruby",
    ".php": "php",
    ".lua": "lua",
    ".pl": "perl",
    ".pm": "perl",
    ".r": "r",
    ".R": "r",
    ".jl": "julia",
    ".el": "elisp",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hrl": "erlang",
    # 函数式
    ".hs": "haskell",
    ".lhs": "haskell",
    ".ml": "ocaml",
    ".mli": "ocaml",
    # Shell/构建
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".fish": "fish",
    # 标记/配置
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".json": "json",
    ".json5": "json5",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".xml": "xml",
    ".sql": "sql",
    # 其他
    ".makefile": "make",
    ".cmake": "cmake",
    ".dockerfile": "dockerfile",
    ".bzl": "python",  # Starlark 是 Python 语法子集
    ".star": "python",
}

# 无扩展名的特殊文件名 → 语言
_SPECIAL_FILENAMES: dict[str, str] = {
    "dockerfile": "dockerfile",
    "makefile": "make",
    "gnumakefile": "make",
    "cmakelists.txt": "cmake",
    "build": "python",  # Bazel BUILD 文件使用 Starlark
    "build.bazel": "python",
    "workspace": "python",  # Bazel WORKSPACE
    "tiltfile": "python",
    "buck": "python",
}


# ===== 每种语言的定义查询 =====
# 捕获命名约定: @<kind>.name，kind ∈ {function, class, type}
# 捕获的是 name 子节点；通过 _find_definition_ancestor 向上查找定义节点获取行号
_DEFINITION_QUERIES: dict[str, str] = {
    "python": """
        (function_definition name: (identifier) @function.name)
        (class_definition name: (identifier) @class.name)
    """,
    "typescript": """
        (function_declaration name: (identifier) @function.name)
        (class_declaration name: (type_identifier) @class.name)
        (interface_declaration name: (type_identifier) @class.name)
        (method_definition name: (property_identifier) @function.name)
        (type_alias_declaration name: (type_identifier) @type.name)
        (enum_declaration name: (identifier) @class.name)
    """,
    "tsx": """
        (function_declaration name: (identifier) @function.name)
        (class_declaration name: (type_identifier) @class.name)
        (interface_declaration name: (type_identifier) @class.name)
        (method_definition name: (property_identifier) @function.name)
        (type_alias_declaration name: (type_identifier) @type.name)
        (enum_declaration name: (identifier) @class.name)
    """,
    "javascript": """
        (function_declaration name: (identifier) @function.name)
        (class_declaration name: (identifier) @class.name)
        (method_definition name: (property_identifier) @function.name)
    """,
    "rust": """
        (function_item name: (identifier) @function.name)
        (struct_item name: (type_identifier) @class.name)
        (enum_item name: (type_identifier) @class.name)
        (union_item name: (type_identifier) @class.name)
        (trait_item name: (type_identifier) @class.name)
        (impl_item type: (type_identifier) @type.name)
        (type_item name: (type_identifier) @type.name)
    """,
    "go": """
        (function_declaration name: (identifier) @function.name)
        (method_declaration name: (field_identifier) @function.name)
        (type_declaration (type_spec name: (type_identifier) @class.name))
    """,
    "java": """
        (method_declaration name: (identifier) @function.name)
        (class_declaration name: (identifier) @class.name)
        (interface_declaration name: (identifier) @class.name)
        (enum_declaration name: (identifier) @class.name)
        (annotation_type_declaration name: (identifier) @class.name)
    """,
    "c": """
        (function_definition declarator: (function_declarator declarator: (identifier) @function.name))
        (struct_specifier name: (type_identifier) @class.name)
        (enum_specifier name: (type_identifier) @class.name)
        (union_specifier name: (type_identifier) @class.name)
        (type_definition declarator: (type_identifier) @type.name)
    """,
    "cpp": """
        (function_definition declarator: (function_declarator declarator: (identifier) @function.name))
        (class_specifier name: (type_identifier) @class.name)
        (struct_specifier name: (type_identifier) @class.name)
        (enum_specifier name: (type_identifier) @class.name)
        (union_specifier name: (type_identifier) @class.name)
    """,
    "c_sharp": """
        (method_declaration name: (identifier) @function.name)
        (class_declaration name: (identifier) @class.name)
        (interface_declaration name: (identifier) @class.name)
        (struct_declaration name: (identifier) @class.name)
        (enum_declaration name: (identifier) @class.name)
    """,
    "ruby": """
        (method name: (identifier) @function.name)
        (singleton_method name: (identifier) @function.name)
        (class name: (constant) @class.name)
        (module name: (constant) @class.name)
    """,
    "php": """
        (function_definition name: (name) @function.name)
        (class_declaration name: (name) @class.name)
        (interface_declaration name: (name) @class.name)
        (trait_declaration name: (name) @class.name)
        (method_declaration name: (name) @function.name)
    """,
    "kotlin": """
        (function_declaration name: (simple_identifier) @function.name)
        (class_declaration name: (type_identifier) @class.name)
        (object_declaration name: (type_identifier) @class.name)
    """,
    "scala": """
        (function_definition name: (identifier) @function.name)
        (function_declaration name: (identifier) @function.name)
        (class_definition name: (identifier) @class.name)
        (object_definition name: (identifier) @class.name)
        (trait_definition name: (identifier) @class.name)
    """,
    "lua": """
        (function_definition_statement name: (identifier) @function.name)
        (local_function_definition_statement name: (identifier) @function.name)
    """,
    "bash": """
        (function_definition name: (word) @function.name)
    """,
    "julia": """
        (function_definition name: (identifier) @function.name)
        (short_function_definition name: (identifier) @function.name)
        (struct_definition name: (identifier) @class.name)
        (module_definition name: (identifier) @class.name)
    """,
    "haskell": """
        (function name: (variable) @function.name)
        (type_alias name: (type) @type.name)
        (data_type name: (type) @class.name)
        (new_type name: (type) @class.name)
        (class_declaration name: (type) @class.name)
    """,
    "ocaml": """
        (value_definition (let_binding name: (value_name) @function.name))
        (type_definition (type_binding name: (type_name) @type.name))
    """,
    "perl": """
        (subroutine_declaration_statement name: (bareword) @function.name)
        (package_statement name: (bareword) @class.name)
    """,
    "sql": """
        (create_function_statement name: (function_name) @function.name)
        (create_table_statement name: (table_name) @class.name)
        (create_view_statement name: (view_name) @class.name)
    """,
}


# ===== 节点类型分类表（用于 get_structure 与引用搜索排除定义名） =====

# function-like 定义节点类型
_FUNCTION_NODE_TYPES: frozenset[str] = frozenset({
    "function_definition", "function_declaration", "function_item", "function",
    "method_definition", "method_declaration", "method", "singleton_method",
    "constructor_declaration", "destructor_declaration",
    "function_signature", "method_signature",
    "function_clause", "rpc_definition",
    "short_function_definition",
    "subroutine_declaration_statement",
    "operation_definition",
    "function_definition_statement",
    "local_function_definition_statement",
    "create_function_statement",
    "let_binding",
})

# class-like 定义节点类型（含 struct/interface/trait/enum/impl/type alias/module）
_CLASS_NODE_TYPES: frozenset[str] = frozenset({
    "class_definition", "class_declaration", "class_specifier", "class",
    "struct_item", "struct_specifier", "struct_declaration", "struct_definition",
    "interface_declaration", "interface_type_definition",
    "trait_item", "trait_declaration", "trait_definition",
    "enum_item", "enum_specifier", "enum_declaration",
    "union_item", "union_specifier",
    "object_declaration", "object_definition",
    "module", "module_definition",
    "impl_item",
    "type_declaration", "type_alias_declaration", "type_definition",
    "type_alias", "type_item", "type_binding", "type_definition",
    "annotation_type_declaration",
    "package_statement",
    "data_type", "new_type", "class_declaration_statement",
    "input_object_type_definition",
    "message", "service",
    "create_table_statement", "create_view_statement",
})

# import-like 节点类型
_IMPORT_NODE_TYPES: frozenset[str] = frozenset({
    "import_statement", "import_from_statement", "import_declaration",
    "use_declaration", "use_statement", "use_simple_declaration",
    "package_declaration", "package_clause",
    "include_directive", "preproc_include",
    "require_statement", "extern_declaration",
    "import_directive", "using_directive",
    "namespace_declaration",
    "load_statement",
})

# identifier 类节点类型（用于引用搜索）
_IDENTIFIER_NODE_TYPES: frozenset[str] = frozenset({
    "identifier", "type_identifier", "field_identifier", "property_identifier",
    "constant", "simple_identifier", "var_name", "variable_name",
    "atom", "bareword", "variable",
    "type_name", "value_name", "function_name", "view_name", "table_name",
    "word",  # bash 函数名
})

# 二进制/非文本文件扩展名（解析时跳过）
_BINARY_EXTS: frozenset[str] = frozenset({
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff", ".svg",
    ".mp3", ".mp4", ".wav", ".ogg", ".webm", ".avi", ".mov", ".flv",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar", ".xz",
    ".pdf", ".docx", ".xlsx", ".pptx",
    ".class", ".jar", ".war",
    ".o", ".obj", ".a", ".lib",
    ".wasm",
    ".eot", ".ttf", ".woff", ".woff2",
    ".db", ".sqlite", ".sqlite3",
    ".lock",
})

# 单文件最大字节数（1MB），超过则跳过解析
_MAX_FILE_SIZE: int = 1024 * 1024

# search_pattern 返回结果上限
_MAX_PATTERN_RESULTS: int = 200

# 已编译 Query 缓存: lang -> Query | None
_QUERY_CACHE: dict[str, Any] = {}


def _classify_definition(node_type: str) -> Optional[str]:
    """将节点类型分类为 function/class/None。

    用于 get_structure 顶层节点分类与引用搜索时排除定义名。
    """
    if node_type in _FUNCTION_NODE_TYPES:
        return "function"
    if node_type in _CLASS_NODE_TYPES:
        return "class"
    return None


class ASTSearchService:
    """基于 tree-sitter-languages 的多语言 AST 搜索服务。

    支持 60+ 语言的函数/类/变量定义搜索、引用搜索与文件结构概览。
    所有行号遵循 1-based 约定（与原 Python ast 模块一致），列号为 0-based。
    """

    def __init__(self, root_dir: str):
        """初始化搜索服务。

        Args:
            root_dir: 搜索根目录（绝对路径或相对路径）。
        """
        self.root_dir: Path = Path(root_dir).resolve()
        # 解析缓存: 文件路径 -> (tree, source_bytes, lang)
        self._tree_cache: dict[str, tuple] = {}

    def search_definitions(self, name: str, file_pattern: str = "*") -> list[dict]:
        """搜索函数/类/类型定义（多语言，基于 tree-sitter）。

        Args:
            name: 定义名（大小写不敏感子串匹配）。
            file_pattern: 文件 glob 模式，默认 "*" 搜索所有支持的语言。

        Returns:
            匹配的定义列表，每项含 name/type/file/line/col 字段。
            type ∈ {"function", "class"}。
        """
        if not _TREE_SITTER_AVAILABLE or not name:
            return []
        results: list[dict] = []
        name_lower = name.lower()
        for file_path in self._iter_files(file_pattern):
            lang = self._detect_language(file_path)
            if lang is None:
                continue
            parsed = self._parse_file(file_path, lang)
            if parsed is None:
                continue
            tree, _, _ = parsed
            for kind, def_name, def_node in self._find_definitions(tree.root_node, lang):
                if name_lower in def_name.lower():
                    # 优先用定义节点本身分类（_classify_definition 基于节点类型），
                    # 回退到 capture kind（type alias/impl 等 kind="type" 归类为 class）
                    def_type = _classify_definition(def_node.type) or (
                        "class" if kind in ("class", "type") else "function"
                    )
                    results.append({
                        "name": def_name,
                        "type": def_type,
                        "file": self._relpath(file_path),
                        "line": def_node.start_point[0] + 1,
                        "col": def_node.start_point[1],
                    })
        return results

    def search_references(self, name: str, file_pattern: str = "*") -> list[dict]:
        """搜索变量/函数引用（多语言，基于 tree-sitter identifier 节点）。

        排除定义名节点（如 function_definition 的 name 子节点），只返回引用。

        Args:
            name: 标识符（精确匹配，区分大小写）。
            file_pattern: 文件 glob 模式，默认 "*" 搜索所有支持的语言。

        Returns:
            匹配的引用列表，每项含 name/context/file/line/col 字段。
            context ∈ {"Load", "Store", "Call"}。
        """
        if not _TREE_SITTER_AVAILABLE or not name:
            return []
        results: list[dict] = []
        for file_path in self._iter_files(file_pattern):
            lang = self._detect_language(file_path)
            if lang is None:
                continue
            parsed = self._parse_file(file_path, lang)
            if parsed is None:
                continue
            tree, _, _ = parsed
            for node in self._walk_identifiers(tree.root_node):
                node_text = self._node_text(node)
                if node_text != name:
                    continue
                if self._is_definition_name(node):
                    continue
                results.append({
                    "name": node_text,
                    "context": self._infer_context(node),
                    "file": self._relpath(file_path),
                    "line": node.start_point[0] + 1,
                    "col": node.start_point[1],
                })
        return results

    def search_pattern(self, pattern: str, file_pattern: str = "*") -> list[dict]:
        """通用文本模式搜索（正则，跨语言）。

        Args:
            pattern: 正则表达式。
            file_pattern: 文件 glob 模式。

        Returns:
            匹配列表，每项含 file/line/match 字段。最多返回 200 条。
            正则编译失败时返回 [{"error": "..."}]。
        """
        results: list[dict] = []
        try:
            regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        except re.error as exc:
            return [{"error": f"无效的正则表达式: {pattern}: {exc}"}]

        for file_path in self._iter_files(file_pattern):
            try:
                content = file_path.read_text(errors="replace")
            except Exception as exc:
                logger.debug(
                    f"[ast_search] 读取文件失败: {file_path}, error={exc}"
                )
                continue
            for match in regex.finditer(content):
                line_start = content[: match.start()].count("\n") + 1
                results.append({
                    "file": self._relpath(file_path),
                    "line": line_start,
                    "match": match.group()[:200],
                })
                if len(results) >= _MAX_PATTERN_RESULTS:
                    break
            if len(results) >= _MAX_PATTERN_RESULTS:
                break
        return results

    def get_structure(self, file_path: str) -> dict:
        """获取文件结构概览（多语言，基于 tree-sitter 顶层节点分类）。

        Args:
            file_path: 相对项目根目录的文件路径。

        Returns:
            含 imports/classes/functions/top_level 四个列表的字典。
            imports 项: {"name": str, "alias": None, "line": int}
            classes 项: {"name": str, "line": int, "methods": [{"name","line"}]}
            functions 项: {"name": str, "line": int}
            top_level 项: {"type": str, "line": int}
            解析失败时返回 {"error": "..."}。
        """
        if not _TREE_SITTER_AVAILABLE:
            return {"error": "tree-sitter-languages 未安装"}
        full_path = self.root_dir / file_path
        if not full_path.exists():
            return {"error": f"文件不存在: {file_path}"}
        lang = self._detect_language(full_path)
        if lang is None:
            return {"error": f"不支持的文件类型: {full_path.suffix}"}
        parsed = self._parse_file(full_path, lang)
        if parsed is None:
            return {"error": "无法解析该文件"}
        tree, _, _ = parsed

        structure: dict[str, list] = {
            "imports": [],
            "classes": [],
            "functions": [],
            "top_level": [],
        }

        for child in tree.root_node.children:
            kind = self._classify_child(child)
            if kind == "import":
                structure["imports"].append({
                    "name": self._node_text(child)[:80],
                    "alias": None,
                    "line": child.start_point[0] + 1,
                })
            elif kind == "class":
                class_name = self._extract_name(child) or "<anonymous>"
                methods: list[dict] = []
                for sub in child.children:
                    if self._classify_child(sub) == "function":
                        method_name = self._extract_name(sub)
                        if method_name:
                            methods.append({
                                "name": method_name,
                                "line": sub.start_point[0] + 1,
                            })
                structure["classes"].append({
                    "name": class_name,
                    "line": child.start_point[0] + 1,
                    "methods": methods,
                })
            elif kind == "function":
                fn_name = self._extract_name(child)
                if fn_name:
                    structure["functions"].append({
                        "name": fn_name,
                        "line": child.start_point[0] + 1,
                    })
            else:
                structure["top_level"].append({
                    "type": child.type,
                    "line": child.start_point[0] + 1,
                })

        return structure

    def clear_cache(self) -> None:
        """清除 AST 解析缓存。"""
        self._tree_cache.clear()
        _QUERY_CACHE.clear()

    # ===== 内部辅助方法 =====

    def _iter_files(self, file_pattern: str) -> Iterator[Path]:
        """遍历匹配 file_pattern 的文件，跳过隐藏目录与二进制文件。"""
        for file_path in self.root_dir.rglob(file_pattern):
            # 跳过隐藏目录（.git/.venv 等）
            if any(part.startswith(".") for part in file_path.parts):
                continue
            try:
                resolved_file = file_path.resolve(strict=True)
                resolved_file.relative_to(self.root_dir)
            except (OSError, ValueError):
                continue
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() in _BINARY_EXTS:
                continue
            try:
                if file_path.stat().st_size > _MAX_FILE_SIZE:
                    continue
            except OSError:
                continue
            yield file_path

    def _detect_language(self, file_path: Path) -> Optional[str]:
        """根据文件扩展名/文件名检测 tree-sitter 语言名。"""
        ext = file_path.suffix.lower()
        if ext:
            return _EXT_TO_LANG.get(ext)
        # 无扩展名文件按文件名匹配
        name_lower = file_path.name.lower()
        return _SPECIAL_FILENAMES.get(name_lower)

    def _parse_file(self, file_path: Path, lang: str) -> Optional[tuple]:
        """解析文件，返回 (tree, source_bytes, lang)，带缓存。"""
        key = str(file_path)
        if key in self._tree_cache:
            return self._tree_cache[key]
        try:
            source = file_path.read_bytes()
            parser = get_parser(lang)
            tree = parser.parse(source)
            result = (tree, source, lang)
            self._tree_cache[key] = result
            return result
        except Exception as exc:
            logger.debug(
                f"[ast_search] 解析失败: {file_path}, lang={lang}, error={exc}"
            )
            return None

    def _find_definitions(
        self, root: Any, lang: str
    ) -> Iterator[tuple[str, str, Any]]:
        """查找定义节点，yield (kind, name, definition_node)。"""
        query = self._get_definition_query(lang)
        if query is None:
            return
        try:
            captures = query.captures(root)
        except Exception as exc:
            logger.debug(
                f"[ast_search] 查询执行失败: lang={lang}, error={exc}"
            )
            return
        for name_node, capture_name in captures:
            # capture_name 格式: "<kind>.name"
            kind = (
                capture_name.split(".", 1)[0]
                if "." in capture_name
                else capture_name
            )
            name_text = self._node_text(name_node)
            def_node = self._find_definition_ancestor(name_node)
            yield kind, name_text, def_node

    def _get_definition_query(self, lang: str) -> Any:
        """获取指定语言的定义查询（带缓存）。"""
        if lang in _QUERY_CACHE:
            return _QUERY_CACHE[lang]
        query_str = _DEFINITION_QUERIES.get(lang)
        if query_str is None:
            _QUERY_CACHE[lang] = None
            return None
        try:
            language = get_language(lang)
            query = language.query(query_str)
            _QUERY_CACHE[lang] = query
            return query
        except Exception as exc:
            logger.debug(
                f"[ast_search] 查询编译失败: lang={lang}, error={exc}"
            )
            _QUERY_CACHE[lang] = None
            return None

    def _find_definition_ancestor(self, name_node: Any) -> Any:
        """从 name 节点向上查找最近的定义节点（处理 C/C++ declarator 链）。

        对于 Python/TS/Go 等语言，name 节点的直接 parent 即定义节点。
        对于 C/C++，name 节点位于 function_declarator 链中，需向上遍历。
        """
        current = name_node.parent
        while current is not None:
            if _classify_definition(current.type) is not None:
                return current
            current = current.parent
        # 找不到定义祖先时回退到 name 节点本身
        return name_node

    def _walk_identifiers(self, root: Any) -> Iterator[Any]:
        """递归遍历所有 identifier 类节点（文档顺序）。"""
        stack: list[Any] = [root]
        while stack:
            node = stack.pop()
            if node.type in _IDENTIFIER_NODE_TYPES:
                yield node
            # 子节点逆序入栈以保持文档顺序
            children = node.children
            for i in range(len(children) - 1, -1, -1):
                stack.append(children[i])

    def _is_definition_name(self, node: Any) -> bool:
        """判断 identifier 节点是否为定义名（位于定义节点的 name 字段位置）。

        用于引用搜索时排除定义名节点（与原 Python ast.Name 行为一致）。
        """
        parent = node.parent
        if parent is None:
            return False
        # 检查是否为父节点的 name 字段
        name_child = parent.child_by_field_name("name")
        if name_child is not None and name_child == node:
            return _classify_definition(parent.type) is not None
        # C/C++ declarator 链: function_definition -> function_declarator -> identifier
        declarator = parent.child_by_field_name("declarator")
        if declarator is not None and declarator == node:
            return True
        # Rust impl_item 的 type 字段
        type_field = parent.child_by_field_name("type")
        if type_field is not None and type_field == node and parent.type == "impl_item":
            return True
        return False

    def _infer_context(self, node: Any) -> str:
        """推断 identifier 的上下文类型（兼容 Python ast.ctx 命名）。"""
        parent = node.parent
        if parent is None:
            return "Load"
        if parent.type == "call":
            return "Call"
        if parent.type in {"assignment", "assign", "augmented_assignment"}:
            left = parent.child_by_field_name("left")
            if left is not None and self._node_contains(left, node):
                return "Store"
            return "Load"
        return "Load"

    @staticmethod
    def _node_contains(outer: Any, inner: Any) -> bool:
        """判断 inner 节点是否在 outer 节点的字节范围内。"""
        try:
            return (
                inner.start_byte >= outer.start_byte
                and inner.end_byte <= outer.end_byte
            )
        except Exception:
            return False

    def _classify_child(self, node: Any) -> Optional[str]:
        """将顶层节点分类为 import/class/function/None。"""
        if node.type in _IMPORT_NODE_TYPES:
            return "import"
        return _classify_definition(node.type)

    def _extract_name(self, node: Any) -> Optional[str]:
        """从定义节点提取名称（优先 name 字段，回退 declarator 链）。"""
        # 1. name 字段
        name_child = node.child_by_field_name("name")
        if name_child is not None:
            return self._node_text(name_child)
        # 2. C/C++ declarator 链式查找
        declarator = node.child_by_field_name("declarator")
        if declarator is not None:
            inner = declarator
            visited: set[int] = set()
            while inner is not None and id(inner) not in visited:
                visited.add(id(inner))
                if inner.type in _IDENTIFIER_NODE_TYPES:
                    return self._node_text(inner)
                name_field = inner.child_by_field_name("name")
                if name_field is not None:
                    return self._node_text(name_field)
                next_declarator = inner.child_by_field_name("declarator")
                if next_declarator is None:
                    break
                inner = next_declarator
        # 3. Go type_declaration -> type_spec 链
        for child in node.children:
            if child.type == "type_spec":
                name_field = child.child_by_field_name("name")
                if name_field is not None:
                    return self._node_text(name_field)
        # 4. Rust impl_item 的 type 字段
        type_field = node.child_by_field_name("type")
        if type_field is not None and node.type == "impl_item":
            return self._node_text(type_field)
        return None

    @staticmethod
    def _node_text(node: Any) -> str:
        """安全提取节点文本（UTF-8 解码，失败返回空串）。"""
        try:
            return node.text.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _relpath(self, file_path: Path) -> str:
        """返回相对项目根目录的 POSIX 路径。"""
        try:
            return str(file_path.relative_to(self.root_dir)).replace("\\", "/")
        except ValueError:
            # 文件不在根目录下，返回绝对路径
            return str(file_path).replace("\\", "/")


__all__ = ["ASTSearchService"]
