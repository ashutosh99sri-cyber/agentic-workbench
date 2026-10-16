"""Bounded source inventory. Never import or execute the inspected application."""

from __future__ import annotations

import ast
import os
import re
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from pathspec import GitIgnoreSpec

from .errors import WorkbenchError
from .models import Evidence, canonical_hash, strict_json
from .policy import SourceFile, WorkspacePolicy
from .retrieval import Chunk
from .selection import select_context_chunks

INDEX_ANALYSIS_VERSION = "1"

_EXTENSIONS = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
}
_FRAMEWORKS = {
    "fastapi",
    "django",
    "flask",
    "react",
    "next",
    "vue",
    "express",
    "svelte",
    "spring",
    "rails",
    "laravel",
}


@dataclass
class RepositoryIndex:
    files: dict[str, SourceFile] = field(default_factory=dict)
    chunks: list[Chunk] = field(default_factory=list)
    symbols: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    manifests: list[dict[str, Any]] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    coverage: dict[str, int] = field(default_factory=dict)
    imports: list[dict[str, Any]] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    cache_stats: dict[str, int] = field(default_factory=dict)
    structural: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        return canonical_hash(
            {path: source.source_hash for path, source in sorted(self.files.items())}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "files": [
                {
                    "path": s.path,
                    "source_hash": s.source_hash,
                    "size": s.size,
                    "contains_secrets": s.contains_secrets,
                }
                for s in self.files.values()
            ],
            "frameworks": self.frameworks,
            "languages": self.languages,
            "manifests": self.manifests,
            "symbols": self.symbols,
            "calls": self.calls,
            "imports": self.imports,
            "references": self.references,
            "cache_stats": self.cache_stats,
            "structural": self.structural,
            "coverage": self.coverage,
            "limitations": [
                "Python call expressions are static facts; dynamic dispatch is unresolved.",
                "TypeScript/JavaScript relationships require a host-selected native parser; "
                "see structural coverage and limitations.",
            ],
        }

    def current(self, policy: WorkspacePolicy, evidence: Evidence) -> bool:
        return self.current_evidence(policy, [evidence])[0]

    def current_evidence(self, policy: WorkspacePolicy, evidence: list[Evidence]) -> list[bool]:
        """Revalidate every citation while reading each source path once per operation."""
        sources: dict[str, tuple[str, int] | None] = {}
        for citation in evidence:
            if citation.path not in sources:
                try:
                    source = policy.read_source(citation.path)
                    sources[citation.path] = (
                        source.source_hash,
                        max(1, len(source.text.splitlines())),
                    )
                except WorkbenchError:
                    sources[citation.path] = None
        current = []
        for citation in evidence:
            snapshot = sources[citation.path]
            current.append(
                snapshot is not None
                and snapshot[0] == citation.source_hash
                and 1 <= citation.start_line <= citation.end_line <= snapshot[1]
            )
        return current

    def current_chunks(
        self, policy: WorkspacePolicy, chunks: list[Chunk] | None = None
    ) -> list[Chunk]:
        selected = self.chunks if chunks is None else chunks
        fresh = self.current_evidence(policy, [chunk.evidence for chunk in selected])
        return [chunk for chunk, current in zip(selected, fresh, strict=True) if current]

    def search(
        self, query: str, limit: int = 5, *, policy: WorkspacePolicy | None = None
    ) -> list[Chunk]:
        if (
            not isinstance(query, str)
            or len(query) > 4096
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid retrieval request")
        chunks = self.chunks if policy is None else self.current_chunks(policy)
        return select_context_chunks(self, query, chunks)[:limit]

    def symbols_in(self, path: str) -> list[dict[str, Any]]:
        return [s for s in self.symbols if s["evidence"]["path"] == path]

    def current_relationships(self, policy: WorkspacePolicy) -> bool:
        """Resolution can depend on an unreturned import/re-export source."""
        return self.files == collect_workspace(policy).files

    def trace(self, name: str, limit: int = 20) -> dict[str, Any]:
        """Source-cited static relationships; resolved TS aliases share declaration IDs."""
        aliases = {
            row.get("target_id")
            for row in self.imports
            if row.get("local") == name and row.get("target_id") is not None
        }
        definitions = [s for s in self.symbols if s["name"] == name or s.get("id") in aliases]
        identities = {s["id"] for s in definitions if "id" in s}
        spans = [
            (s["evidence"]["path"], s["evidence"]["start_line"], s["evidence"]["end_line"])
            for s in definitions
        ]
        callers = [
            c
            for c in self.calls
            if (c.get("target_id") is not None and c["target_id"] in identities)
            or (
                c["evidence"]["path"].endswith(".py")
                and "target_id" not in c
                and (c["callee"] == name or c["callee"].endswith("." + name))
            )
        ]
        callees = [
            c
            for c in self.calls
            if c not in callers
            and any(
                c["evidence"]["path"] == path and start <= c["evidence"]["start_line"] <= end
                for path, start, end in spans
            )
        ]
        pattern = re.compile(rf"(?<![\w$]){re.escape(name)}(?![\w$])")
        tests = [
            Evidence(source.path, line, line, source.source_hash).to_dict()
            for source in self.files.values()
            if "test" in source.path.lower()
            for line, text in enumerate(source.text.splitlines(), 1)
            if pattern.search(text)
        ]
        groups = {
            "definitions": definitions,
            "callers": callers,
            "callees": callees,
            "tests": tests,
            "imports": [r for r in self.imports if r.get("target_id") in identities],
            "references": [r for r in self.references if r.get("target_id") in identities],
        }
        return {
            "name": name,
            **{key: value[:limit] for key, value in groups.items()},
            "truncated": any(len(value) > limit for value in groups.values()),
            "limitations": [
                "Python calls match source names; dynamic dispatch is unresolved.",
                "TypeScript relationships resolve only within approved source snapshots.",
                "Test references are text matches in paths containing 'test'.",
                *self.structural.get("limitations", []),
            ],
        }


def _python(source: SourceFile, index: RepositoryIndex) -> None:
    try:
        tree = ast.parse(source.text)
    # CPython reports deep unary/power nesting as MemoryError (parser stack overflow).
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        index.coverage["parse_errors"] += 1
        return
    nodes = list(ast.walk(tree))
    names = {
        node.name
        for node in nodes
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    # Chain depth (f()()..., a.b.c...) for every node in one bottom-up pass: walk order puts
    # parents first, so reversed order sees each inner node before its parent.
    depth: dict[int, int] = {}
    for node in reversed(nodes):
        inner = getattr(node, "func", None) or getattr(node, "value", None)
        depth[id(node)] = 1 + depth.get(id(inner), 0) if isinstance(inner, ast.AST) else 0
    unformatted = False
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            index.symbols.append(
                {
                    "name": node.name,
                    "kind": type(node).__name__,
                    "evidence": Evidence(
                        source.path, node.lineno, node.end_lineno or node.lineno, source.source_hash
                    ).to_dict(),
                }
            )
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for module in modules:
                framework = module.split(".")[0]
                if framework in _FRAMEWORKS:
                    index.frameworks.append(framework)
        elif isinstance(node, ast.Call):
            if depth.get(id(node.func), 0) > 32:
                # Skip without unparsing: each nested call would hit the recursion limit again.
                unformatted = True
                continue
            try:
                callee = ast.unparse(node.func)[:256]
            except RecursionError:
                # Valid but deeply nested source: skip this call, keep the file's other facts.
                unformatted = True
                continue
            index.calls.append(
                {
                    "callee": callee,
                    "resolution": "local-name"
                    if isinstance(node.func, ast.Name) and callee in names
                    else "unresolved",
                    "evidence": Evidence(
                        source.path, node.lineno, node.end_lineno or node.lineno, source.source_hash
                    ).to_dict(),
                }
            )
    if unformatted:
        index.coverage["parse_errors"] += 1


def _manifest(source: SourceFile, index: RepositoryIndex) -> None:
    leaf = source.path.rsplit("/", 1)[-1]
    language = None
    dependencies: list[str] = []
    try:
        if leaf == "pyproject.toml":
            language = "python"
            data = tomllib.loads(source.text)
            dependencies = list(data.get("project", {}).get("dependencies", []))
            dependencies += list(data.get("tool", {}).get("poetry", {}).get("dependencies", {}))
        elif leaf == "package.json":
            language = (
                "typescript"
                if any(p.endswith((".ts", ".tsx")) for p in index.files)
                else "javascript"
            )
            data = strict_json(source.text)
            dependencies = list(data.get("dependencies", {})) + list(
                data.get("devDependencies", {})
            )
        elif leaf in {
            "requirements.txt",
            "go.mod",
            "Cargo.toml",
            "pom.xml",
            "build.gradle",
            "Gemfile",
            "composer.json",
        } or leaf.endswith(".csproj"):
            language = {
                "requirements.txt": "python",
                "go.mod": "go",
                "Cargo.toml": "rust",
                "pom.xml": "java",
                "build.gradle": "java",
                "Gemfile": "ruby",
                "composer.json": "php",
            }.get(leaf, "csharp")
            if leaf == "Cargo.toml":
                data = tomllib.loads(source.text)
                dependencies = list(data.get("dependencies", {})) + list(
                    data.get("dev-dependencies", {})
                )
            elif leaf == "composer.json":
                data = strict_json(source.text)
                dependencies = list(data.get("require", {})) + list(data.get("require-dev", {}))
            elif leaf == "pom.xml" or leaf.endswith(".csproj"):
                tree = ET.fromstring(source.text)  # noqa: S314 - bounded parser; no external resolver
                if leaf == "pom.xml":
                    dependencies = [
                        artifact.text or ""
                        for dependency in tree.findall(".//{*}dependency")
                        for artifact in dependency.findall("{*}artifactId")
                    ]
                else:
                    dependencies = [
                        node.get("Include") or node.get("Update") or ""
                        for node in tree.findall(".//{*}PackageReference")
                    ]
            elif leaf == "Gemfile":
                dependencies = re.findall(r"""(?m)^\s*gem\s+["']([^"']+)["']""", source.text)
            elif leaf == "build.gradle":
                dependencies = re.findall(
                    r"""["']([A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:[^"']+)["']""", source.text
                )
            elif leaf == "requirements.txt":
                dependencies = [
                    line.strip()
                    for line in source.text.splitlines()
                    if line.strip() and not line.lstrip().startswith(("#", "-"))
                ]
            else:
                dependencies = [
                    line.strip()
                    for line in source.text.splitlines()
                    if re.match(r"^\s*(?:require\s+)?[A-Za-z0-9_.-]+\.[A-Za-z0-9_./-]+\s+v\d", line)
                ]
        else:
            return
        if len(dependencies) > 500 or not all(isinstance(dep, str) for dep in dependencies):
            raise ValueError("invalid dependency list")
        frameworks = sorted(
            f
            for f in _FRAMEWORKS
            if any(
                re.search(r"(?:^|[/@:])" + re.escape(f) + r"(?:$|[/>=<\[ ;:-])", dep.lower())
                for dep in dependencies
            )
        )
        index.languages.append(language)
        index.frameworks.extend(frameworks)
        index.manifests.append(
            {
                "path": source.path,
                "language": language,
                "dependencies": dependencies,
                "frameworks": frameworks,
                "evidence": Evidence(
                    source.path, 1, max(1, len(source.text.splitlines())), source.source_hash
                ).to_dict(),
            }
        )
    except (
        tomllib.TOMLDecodeError,
        ET.ParseError,
        WorkbenchError,
        TypeError,
        AttributeError,
        ValueError,
        # Valid but deeply nested manifests (inline TOML tables) exceed the parser stack.
        RecursionError,
    ):
        index.coverage["parse_errors"] += 1


def collect_workspace(policy: WorkspacePolicy) -> RepositoryIndex:
    """Read the current policy-bounded inventory without deriving source facts."""
    index = RepositoryIndex(
        coverage=dict.fromkeys(
            [
                "scanned",
                "excluded",
                "unavailable",
                "oversized",
                "parse_errors",
                "limit_reached",
                "bytes",
            ],
            0,
        )
    )
    limits = policy.config.scan
    visited = 0

    def walk(parts: tuple[str, ...], rules: list[tuple[str, GitIgnoreSpec]]) -> None:
        nonlocal visited
        if len(parts) > 128:
            index.coverage["unavailable"] += 1
            return
        if index.coverage["limit_reached"]:
            return
        relative = "/".join(parts)
        ignore_path = f"{relative}/.gitignore" if relative else ".gitignore"
        try:
            ignore = policy.read_source(ignore_path)
            rules = [*rules, (relative, GitIgnoreSpec.from_lines(ignore.text.splitlines()))]
        except WorkbenchError:
            pass
        truncated = False
        try:
            if os.name == "posix":
                with policy.directory(parts) as fd, os.scandir(fd) as stream:
                    entries: list[tuple[str, bool, bool]] = []
                    for entry in stream:
                        if visited + len(entries) >= limits.max_files * 4:
                            truncated = True
                            break
                        entries.append(
                            (entry.name, entry.is_dir(follow_symlinks=False), entry.is_symlink())
                        )
            else:
                target = policy.root.joinpath(*parts)
                if target.resolve() != target:
                    raise WorkbenchError("POLICY_DENIED", "Directory alias")
                with os.scandir(target) as stream:
                    entries = []
                    for entry in stream:
                        if visited + len(entries) >= limits.max_files * 4:
                            truncated = True
                            break
                        entries.append(
                            (entry.name, entry.is_dir(follow_symlinks=False), entry.is_symlink())
                        )
            for name, directory, alias in sorted(entries):
                visited += 1
                path = "/".join((*parts, name))
                try:
                    ignored = policy.is_excluded(path)
                    if not ignored:
                        for base, spec in rules:
                            match = spec.check_file(
                                (path[len(base) + 1 :] if base else path)
                                + ("/" if directory else "")
                            ).include
                            if match is not None:
                                ignored = match
                except WorkbenchError:
                    ignored = True
                if ignored or alias:
                    index.coverage["excluded"] += 1
                elif directory:
                    walk((*parts, name), rules)
                else:
                    if len(index.files) >= limits.max_files:
                        index.coverage["limit_reached"] = 1
                        return
                    try:
                        source = policy.read_source(path)
                        if index.coverage["bytes"] + source.size > limits.max_total_bytes:
                            index.coverage["limit_reached"] = 1
                            return
                        index.files[path] = source
                        index.coverage["scanned"] += 1
                        index.coverage["bytes"] += source.size
                    except WorkbenchError as error:
                        index.coverage[
                            "oversized" if error.code == "LIMIT_EXCEEDED" else "unavailable"
                        ] += 1
                if index.coverage["limit_reached"]:
                    return
            # Set only after collected entries are processed, so the bounded prefix is full.
            if truncated:
                index.coverage["limit_reached"] = 1
        except (OSError, WorkbenchError):
            index.coverage["unavailable"] += 1

    walk((), [])
    return index


def index_source(source: SourceFile) -> RepositoryIndex:
    """Derive per-file facts from an already authorized, redacted source snapshot."""
    index = RepositoryIndex(coverage={"parse_errors": 0})
    suffix = os.path.splitext(source.path)[1]
    if suffix in _EXTENSIONS:
        index.languages.append(_EXTENSIONS[suffix])
    _manifest(source, index)
    if suffix == ".py":
        _python(source, index)
    lines = source.text.splitlines()
    for start in range(0, len(lines), 60):
        index.chunks.append(
            Chunk(
                Evidence(source.path, start + 1, min(start + 60, len(lines)), source.source_hash),
                "\n".join(lines[start : start + 60]),
            )
        )
    return index


def merge_source(index: RepositoryIndex, derived: RepositoryIndex) -> None:
    """Merge derived facts without replacing fresh files or traversal coverage."""
    for name in ("chunks", "symbols", "calls", "manifests", "imports", "references"):
        getattr(index, name).extend(getattr(derived, name))
    index.frameworks = sorted(set(index.frameworks + derived.frameworks))
    index.languages = sorted(set(index.languages + derived.languages))
    index.coverage["parse_errors"] += derived.coverage.get("parse_errors", 0)


def scan_workspace(policy: WorkspacePolicy) -> RepositoryIndex:
    index = collect_workspace(policy)
    for source in index.files.values():
        merge_source(index, index_source(source))
    return index
