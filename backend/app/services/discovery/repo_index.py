from __future__ import annotations

import ast
import fnmatch
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.services.discovery.store import digest
from app.services.discovery.syntax import (
    CALLS,
    DEFINITIONS,
    IMPORTS,
    PARSER_LANGUAGES,
    code_only,
    declaration_name,
    node_text,
    parse_source,
    walk,
)

EXCLUDED_DIRS = {
    ".git",
    ".auditai",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
}
LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".m": "objective_c",
    ".mm": "objective_cpp",
    ".cs": "csharp",
    ".php": "php",
    ".rb": "ruby",
}


def matches(path, patterns):
    for pattern in patterns:
        directory = pattern.removesuffix("/**").rstrip("/")
        if (
            fnmatch.fnmatch(path, pattern)
            or fnmatch.fnmatch(Path(path).name, pattern)
            or path == directory
            or path.startswith(directory + "/")
        ):
            return True
    return False


def create_snapshot(
    project_root,
    storage_root,
    *,
    target_files=None,
    exclude_patterns=None,
    quota_bytes=1024**3,
    forbidden_roots=None,
):
    root, storage = Path(project_root).resolve(), Path(storage_root).resolve()
    storage.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = Path(tempfile.mkdtemp(prefix="source-", dir=storage))
    files, unknowns, size = {}, [], 0
    forbidden = [Path(p).resolve() for p in (forbidden_roots or [storage])]
    try:
        for parent, directories, names in os.walk(root, followlinks=False):
            unknowns.extend(
                f"Not copied (symlink directory): {(Path(parent) / name).relative_to(root).as_posix()}"
                for name in directories
                if (Path(parent) / name).is_symlink()
            )
            directories[:] = sorted(
                d
                for d in directories
                if d not in EXCLUDED_DIRS
                and not (Path(parent) / d).is_symlink()
                and not any((Path(parent) / d).resolve().is_relative_to(p) for p in forbidden)
                and not matches(
                    (Path(parent) / d).relative_to(root).as_posix(), exclude_patterns or []
                )
            )
            for name in sorted(names):
                src = Path(parent) / name
                relative = src.relative_to(root).as_posix()
                if name == ".env" or matches(relative, exclude_patterns or []):
                    continue
                if target_files and not matches(relative, target_files):
                    continue
                if src.is_symlink() or not src.is_file():
                    unknowns.append(f"Not copied (symlink/special file): {relative}")
                    continue
                size += src.stat().st_size
                if size > quota_bytes:
                    raise ValueError("Source snapshot quota exceeded; narrow the audit scope")
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                before = src.stat()
                shutil.copyfile(src, target)
                after = src.stat()
                if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                    raise ValueError(f"Source changed while taking snapshot: {relative}")
                with target.open("rb") as stream:
                    files[relative] = hashlib.file_digest(stream, "sha256").hexdigest()
                target.chmod(0o444)
        commit = None
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            commit = result.stdout.strip()
        snapshot_id = digest(
            {"files": files, "scope": target_files or [], "excludes": exclude_patterns or []}
        )
        for parent, _, _ in os.walk(destination, topdown=False):
            Path(parent).chmod(0o555)
        return {
            "repo_snapshot_id": snapshot_id,
            "root": str(destination),
            "files": files,
            "commit": commit,
            "content_hash": digest(files),
            "scope": target_files or ["."],
            "exclude_patterns": exclude_patterns or [],
            "builtin_excludes": sorted(EXCLUDED_DIRS | {".env"}),
            "unknowns": unknowns,
            "bytes": size,
            "index_version": "source-index-v2",
        }
    except BaseException:
        for parent, _, _ in os.walk(destination):
            Path(parent).chmod(0o755)
        shutil.rmtree(destination)
        raise


class RepoIndex:
    """Syntax-backed navigation with explicit unresolved calls and framework heuristics."""

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.root = Path(snapshot["root"]).resolve()
        self.symbols, self.references, self.imports, self.unknowns = (
            [],
            [],
            [],
            list(snapshot.get("unknowns", [])),
        )
        self.texts = {}
        self.code_texts, self.parsed_languages, self.parsed_files = {}, set(), set()
        for path in snapshot["files"]:
            source = self.root / path
            if source.stat().st_size > 2 * 1024 * 1024:
                self.unknowns.append(
                    f"Symbol index skipped large file: {path}; Read remains available"
                )
                continue
            try:
                text = source.read_text(encoding="utf-8")
            except (UnicodeError, OSError):
                continue
            if "\x00" in text:
                continue
            self.texts[path] = text
            language = LANGUAGES.get(Path(path).suffix)
            if language in PARSER_LANGUAGES:
                self._syntax(path, text, "tsx" if path.endswith(".tsx") else language)
            if path.endswith(".py"):
                self._python(path, text)
            elif path not in self.parsed_files and Path(path).suffix in {
                ".js",
                ".jsx",
                ".ts",
                ".tsx",
            }:
                self._javascript(path, text)
        self.unknowns.append(
            "Dynamic registration, reflection, aliases and framework guards require source review; references are not a whole-program call graph."
        )

    def _symbol(self, path, name, line, end, basis, kind="function"):
        value = {
            "id": digest([path, name, line]),
            "name": name,
            "file_path": path,
            "line_start": line,
            "line_end": end,
            "basis": basis,
            "kind": kind,
        }
        self.symbols.append(value)
        return value

    def _syntax(self, path, text, language):
        try:
            tree = parse_source(text, language)
        except Exception as exc:
            self.unknowns.append(
                f"Syntax parser unavailable: {path}: {type(exc).__name__}; text navigation only"
            )
            return
        self.code_texts[path] = code_only(text, tree)
        self.parsed_languages.add(LANGUAGES[Path(path).suffix])
        self.parsed_files.add(path)
        if tree.root_node.has_error:
            self.unknowns.append(
                f"Partial syntax parse: {path}; inspect unresolved or generated constructs"
            )
        if language == "python":
            return  # Preserve Python's richer built-in AST call/import extraction.
        for node in walk(tree.root_node):
            if node.type in DEFINITIONS:
                name = declaration_name(node)
                if name:
                    kind = (
                        "class"
                        if any(t in node.type for t in ("class", "struct", "interface", "object"))
                        else "function"
                    )
                    self._symbol(
                        path,
                        name,
                        node.start_point.row + 1,
                        node.end_point.row + 1,
                        f"tree_sitter_{language}",
                        kind,
                    )
            elif node.type == "variable_declarator":
                value = node.child_by_field_name("value")
                if value and value.type in {"arrow_function", "function_expression"}:
                    self._symbol(
                        path,
                        declaration_name(node),
                        node.start_point.row + 1,
                        node.end_point.row + 1,
                        f"tree_sitter_{language}",
                    )
            if node.type in IMPORTS:
                self.imports.append(
                    {
                        "file_path": path,
                        "line": node.start_point.row + 1,
                        "statement": node_text(node),
                        "basis": f"tree_sitter_{language}",
                    }
                )
            if node.type in CALLS:
                target = (
                    node.child_by_field_name("function")
                    or node.child_by_field_name("name")
                    or node.child_by_field_name("method")
                )
                if target is None and node.named_children:
                    target = node.named_children[0]
                expression = node_text(target)
                names = re.findall(r"[A-Za-z_$][\w$]*", expression)
                if names:
                    self.references.append(
                        {
                            "name": names[-1],
                            "expression": expression,
                            "file_path": path,
                            "line": node.start_point.row + 1,
                            "basis": "ast_call_name_unresolved",
                        }
                    )

    def _python(self, path, text):
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            self.unknowns.append(f"Python parse failed: {path}:{exc.lineno}: {exc.msg}")
            return
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._symbol(
                    path,
                    node.name,
                    node.lineno,
                    node.end_lineno,
                    "python_ast",
                    "class" if isinstance(node, ast.ClassDef) else "function",
                )
            elif isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                self.references.append(
                    {
                        "name": name.rsplit(".", 1)[-1],
                        "expression": name,
                        "file_path": path,
                        "line": node.lineno,
                        "basis": "ast_call_name_unresolved",
                    }
                )
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                self.imports.append(
                    {
                        "file_path": path,
                        "line": node.lineno,
                        "statement": ast.unparse(node),
                        "basis": "python_ast",
                    }
                )

    def _javascript(self, path, text):
        for line, content in enumerate(text.splitlines(), 1):
            match = re.search(
                r"(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function|class)\s+(\w+)|export\s+(?:const|let)\s+(\w+)",
                content,
            )
            if match:
                self._symbol(path, match.group(1) or match.group(2), line, line, "text_heuristic")
            if re.search(r"\bimport\b|\brequire\(", content):
                self.imports.append(
                    {
                        "file_path": path,
                        "line": line,
                        "statement": content,
                        "basis": "text_heuristic",
                    }
                )

    def find_symbol(self, name, module_hint=None):
        return [
            s
            for s in self.symbols
            if name.lower() in s["name"].lower()
            and (not module_hint or module_hint in s["file_path"])
        ][:100]

    def find_references(self, symbol_id):
        symbol = next((s for s in self.symbols if s["id"] == symbol_id), None)
        if not symbol:
            raise ValueError("Unknown symbol")
        results = [r for r in self.references if r["name"] == symbol["name"]]
        for path, text in self.texts.items():
            if path.endswith(".py") or path in self.parsed_files:
                continue
            for line, content in enumerate(text.splitlines(), 1):
                if re.search(r"\b" + re.escape(symbol["name"]) + r"\b", content):
                    results.append({"file_path": path, "line": line, "basis": "text_name_match"})
        return {
            "symbol": symbol,
            "references": results[:200],
            "truncated": len(results) > 200,
            "resolution": "Name matches may refer to different symbols; inspect imports and caller conditions.",
        }

    def read(self, path, start=1, end=None):
        normalized = Path(path).as_posix()
        if normalized not in self.snapshot["files"]:
            raise ValueError("Path is outside the source manifest")
        resolved = (self.root / normalized).resolve()
        if not resolved.is_relative_to(self.root) or resolved.is_symlink():
            raise ValueError("Path escapes source snapshot")
        # Recheck content on every evidence read; observations bind to these exact bytes.
        with resolved.open("rb") as stream:
            if (
                hashlib.file_digest(stream, "sha256").hexdigest()
                != self.snapshot["files"][normalized]
            ):
                raise ValueError("Source snapshot integrity check failed")
        start = max(1, start)
        end = min(end or start + 199, start + 399)
        lines, truncated_lines = [], []
        with resolved.open(encoding="utf-8", errors="replace") as stream:
            for number, line in enumerate(stream, 1):
                if number > end:
                    break
                if number >= start:
                    if len(line) > 4000:
                        truncated_lines.append(number)
                    lines.append(line[:4000].rstrip("\n"))
        if not lines:
            raise ValueError("Requested line range is empty or outside the source file")
        return {
            "file_path": normalized,
            "line_start": start,
            "line_end": start + len(lines) - 1,
            "content": "\n".join(lines),
            "file_hash": self.snapshot["files"][normalized],
            "truncated_line_numbers": truncated_lines,
        }
