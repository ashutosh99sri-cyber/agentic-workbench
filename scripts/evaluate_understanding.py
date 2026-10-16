"""Offline fixed-target retrieval and incremental-scan controls on real source."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import shutil
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any

from agentic_workbench import Workbench
from agentic_workbench.errors import WorkbenchError
from agentic_workbench.eval_corpus import fetch_archive, load_corpus, materialize
from agentic_workbench.evaluation import evaluate_corpus
from agentic_workbench.models import canonical_hash, canonical_json, strict_json
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.repository import collect_workspace, scan_workspace

MODES = ("lexical", "impact", "vector", "combined")
VECTOR_UNAVAILABLE = "No real embedding provider configured; no network or paid request made."
LEGACY_CORPUS_PROTOCOL = "policy-bounded-v1"
ISOLATED_CORPUS_PROTOCOL = "policy-bounded-without-evaluation-metadata-v2"
EVALUATION_METADATA_SUBTREE = "evaluations/understanding/"


def _relative(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not PurePosixPath(value).is_absolute()
        and "\\" not in value
        and ":" not in value
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def read_manifest(path: Path) -> dict[str, Any]:
    data = strict_json(path.read_text(), 262_144)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported understanding manifest")
    limits, tasks = data.get("limits", {}), data.get("tasks")
    if (
        not isinstance(limits, dict)
        or type(limits.get("k")) is not int
        or not 1 <= limits["k"] <= 50
        or type(limits.get("selected_bytes")) is not int
        or not 1024 <= limits["selected_bytes"] <= 131_072
        or not isinstance(tasks, list)
        or not 1 <= len(tasks) <= 32
    ):
        raise ValueError("Invalid bounded task limits")
    seen = set()
    for task in tasks:
        if (
            not isinstance(task, dict)
            or not isinstance(task.get("id"), str)
            or not _relative(task["id"])
            or "/" in task["id"]
            or task["id"] in seen
            or task.get("source") not in {"workspace", "python-corpus"}
            or task.get("source") == "python-corpus"
            and (not _relative(task.get("corpus_task")) or "/" in task["corpus_task"])
            or not isinstance(task.get("query"), str)
            or not 1 <= len(task["query"]) <= 4096
            or not isinstance(task.get("changed_paths"), list)
            or not 1 <= len(task["changed_paths"]) <= 20
            or any(not _relative(path) for path in task["changed_paths"])
            or not isinstance(task.get("targets"), dict)
            or set(task["targets"]) != {"edited", "callers", "checks"}
        ):
            raise ValueError("Invalid or duplicate understanding task")
        seen.add(task["id"])
        for targets in task["targets"].values():
            if not isinstance(targets, list) or not 1 <= len(targets) <= 10:
                raise ValueError("Targets must be nonempty bounded lists")
            for target in targets:
                if (
                    not isinstance(target, dict)
                    or not _relative(target.get("path"))
                    or not isinstance(target.get("anchor"), str)
                    or not 1 <= len(target["anchor"]) <= 512
                ):
                    raise ValueError("Invalid source anchor")
    return data


def bounded_chunks(chunks: list[dict[str, Any]], k: int, maximum: int) -> list[dict[str, Any]]:
    """Apply the same complete serialized chunk budget to every ranking."""
    selected: list[dict[str, Any]] = []
    seen = set()
    for chunk in chunks:
        identity = canonical_json(chunk)
        if identity in seen:
            continue
        seen.add(identity)
        if len(canonical_json([*selected, chunk]).encode()) <= maximum:
            selected.append(chunk)
        if len(selected) == k:
            break
    return selected


def resolve_targets(
    task: dict[str, Any], sources: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    resolved = {}
    for group, targets in task["targets"].items():
        rows = []
        for target in targets:
            source = sources.get(target["path"])
            matches = (
                [
                    i
                    for i, line in enumerate(source.text.splitlines(), 1)
                    if target["anchor"] in line
                ]
                if source is not None
                else []
            )
            rows.append({**target, "line": matches[0] if matches else None})
        resolved[group] = rows
    return resolved


def score_targets(
    targets: dict[str, list[dict[str, Any]]], selected: list[dict[str, Any]]
) -> dict[str, Any]:
    groups = {}
    for name, rows in targets.items():
        hits = [
            target["line"] is not None
            and any(
                chunk["evidence"]["path"] == target["path"]
                and chunk["evidence"]["start_line"]
                <= target["line"]
                <= chunk["evidence"]["end_line"]
                for chunk in selected
            )
            for target in rows
        ]
        groups[name] = {"hits": sum(hits), "expected": len(rows), "complete": all(hits)}
    return {"groups": groups, "complete": all(group["complete"] for group in groups.values())}


def latency_summary(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "samples": len(values),
        "p50_seconds": ordered[math.ceil(len(ordered) * 0.5) - 1] if ordered else None,
        "p95_seconds": ordered[math.ceil(len(ordered) * 0.95) - 1] if ordered else None,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for mode in MODES:
        selected = [row for row in rows if row["mode"] == mode]
        available = [row for row in selected if row["status"] == "available"]
        complete = sum(bool(row["score"]["complete"]) for row in selected)
        result[mode] = {
            "selected": len(selected),
            "available": len(available),
            "unavailable_or_failed": len(selected) - len(available),
            "complete": complete,
            "complete_rate_selected": complete / len(selected) if selected else None,
            "effectiveness_measured": bool(available),
            **latency_summary(
                [
                    elapsed
                    for row in available
                    for elapsed in row.get("latency_samples_seconds", [row["latency_seconds"]])
                ]
            ),
        }
    return result


def snapshot_workspace(
    source: Path, destination: Path, *, isolate_evaluation_metadata: bool = False
) -> dict[str, Any]:
    index = collect_workspace(WorkspacePolicy(source))
    omitted = {
        path: entry.source_hash
        for path, entry in sorted(index.files.items())
        if isolate_evaluation_metadata and path.startswith(EVALUATION_METADATA_SUBTREE)
    }
    included = {path: entry for path, entry in index.files.items() if path not in omitted}
    source_hashes = {path: entry.source_hash for path, entry in sorted(included.items())}
    destination.mkdir(parents=True)
    for relative, entry in included.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(entry.text)
    return {
        "kind": "policy-approved-redacted-source-snapshot",
        "corpus_protocol": (
            ISOLATED_CORPUS_PROTOCOL if isolate_evaluation_metadata else LEGACY_CORPUS_PROTOCOL
        ),
        "original_raw_source_hashes": source_hashes,
        "source_fingerprint": canonical_hash(source_hashes),
        "coverage": index.coverage,
        "evaluation_metadata_exclusions": {
            "subtrees": [EVALUATION_METADATA_SUBTREE] if isolate_evaluation_metadata else [],
            "omitted_source_hashes": omitted,
            "policy_approved_files": len(index.files),
            "copied_files": len(included),
        },
    }


def _base_facts(index: Any) -> dict[str, Any]:
    return {
        "fingerprint": index.fingerprint,
        "chunks": [chunk.to_dict() for chunk in index.chunks],
        "python_symbols": [s for s in index.symbols if s["evidence"]["path"].endswith(".py")],
        "python_calls": [c for c in index.calls if c["evidence"]["path"].endswith(".py")],
        "manifests": index.manifests,
        "coverage": index.coverage,
        "languages": index.languages,
        "frameworks": index.frameworks,
    }


def scan_controls(root: Path, changed_path: str, analyzer: Any) -> list[dict[str, Any]]:
    from agentic_workbench.index_cache import IncrementalIndexCache

    cache = IncrementalIndexCache()
    rows = []
    path = root / changed_path
    original = path.read_bytes()
    kwargs = {"typescript_analyzer": analyzer}
    try:
        with Workbench(root, index_cache=cache, **kwargs) as wb:
            for phase in ("cold", "warm", "one_file_edit"):
                if phase == "one_file_edit":
                    comment = (
                        b"\n# understanding scan edit\n"
                        if path.suffix == ".py"
                        else b"\n// understanding scan edit\n"
                    )
                    path.write_bytes(original + comment)
                started = time.perf_counter()
                index = wb._scan()
                rows.append(
                    {
                        "phase": phase,
                        "latency_seconds": time.perf_counter() - started,
                        "cache_stats": dict(index.cache_stats),
                        "fingerprint": index.fingerprint,
                        "coverage": index.coverage,
                    }
                )
            started = time.perf_counter()
            cold = scan_workspace(wb.policy)
            rows.append(
                {
                    "phase": "cold_edit_comparison",
                    "latency_seconds": time.perf_counter() - started,
                    "equivalent_base_facts": _base_facts(index) == _base_facts(cold),
                    "fingerprint": cold.fingerprint,
                }
            )
        with Workbench(root, index_cache=IncrementalIndexCache(), **kwargs) as wb:
            started = time.perf_counter()
            reopened = wb._scan()
            rows.append(
                {
                    "phase": "reopen",
                    "latency_seconds": time.perf_counter() - started,
                    "cache_stats": dict(reopened.cache_stats),
                    "fingerprint": reopened.fingerprint,
                    "equivalent_base_facts": _base_facts(reopened) == _base_facts(cold),
                }
            )
    finally:
        path.write_bytes(original)
    return rows


def evaluate(
    manifest: Path,
    workspace: Path,
    cache: Path,
    output: Path,
    *,
    repetitions: int = 3,
    analyzer: Any = None,
    repair_controls: bool = False,
    backend: str = "docker",
    isolate_evaluation_metadata: bool = False,
) -> dict[str, Any]:
    if type(repetitions) is not int or not 1 <= repetitions <= 10:
        raise ValueError("Repetitions must be within 1..10")
    data = read_manifest(manifest)
    corpus_manifest = workspace / "evaluations/python/manifest.json"
    corpus = load_corpus(corpus_manifest)
    by_id = {task.id: task for task in corpus.tasks}
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    frozen = output / "frozen-manifest.json"
    frozen.write_bytes(manifest.read_bytes())
    rows: list[dict[str, Any]] = []
    scans: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "schema_version": 1,
        "manifest_sha256": hashlib.sha256(frozen.read_bytes()).hexdigest(),
        "python_corpus_manifest_sha256": hashlib.sha256(corpus_manifest.read_bytes()).hexdigest(),
        "python_archives_lock_sha256": hashlib.sha256(
            corpus_manifest.with_name("archives.lock.json").read_bytes()
        ).hexdigest(),
        "protocol": data["protocol"],
        "corpus_protocol": (
            ISOLATED_CORPUS_PROTOCOL if isolate_evaluation_metadata else LEGACY_CORPUS_PROTOCOL
        ),
        "limits": data["limits"],
        "repetitions": repetitions,
        "python": {"version": platform.python_version(), "executable": sys.executable},
        "parser_fingerprint": analyzer.fingerprint if analyzer is not None else None,
        "embedding_provider": None,
        "embedding_model": None,
        "model_effectiveness": "unknown; no live model or real embeddings were called",
        "usage": {"requests": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0},
        "repair_outcomes": None,
        "rows": rows,
        "scan_controls": scans,
        "scan_source_pins": [],
        "source_pins": {},
        "limitations": [
            "Six local controls do not establish general framework superiority.",
            "Impact receives predeclared changed paths; lexical receives the query.",
            "Missing targets and unavailable modes remain in all-selected denominators.",
            "Known-patch replay tests workflow execution, not retrieval repair effectiveness.",
            "No MCP latency is measured here; MCP integration is a separate gate.",
        ],
    }
    local = output / "workspace-source"
    report["source_pins"]["workspace"] = snapshot_workspace(
        workspace, local, isolate_evaluation_metadata=isolate_evaluation_metadata
    )
    roots: dict[str, Path] = {"workspace": local}
    for task in data["tasks"]:
        source_key = task.get("corpus_task", "workspace")
        setup_error = None
        try:
            if source_key not in roots:
                case = by_id[source_key]
                artifact = corpus.archives[(case.repo, case.buggy_commit)]
                root = materialize(fetch_archive(artifact, cache), output / f"source-{source_key}")
                (root / "test_reproduction.py").write_bytes(case.reproduction_file.read_bytes())
                roots[source_key] = root
                report["source_pins"][source_key] = {
                    "repo": case.repo,
                    "commit": case.buggy_commit,
                    "archive_sha256": artifact.sha256,
                    "fixed_commit": case.fixed_commit,
                    "fixed_archive_sha256": corpus.archives[(case.repo, case.fixed_commit)].sha256,
                    "public_check_sha256": hashlib.sha256(
                        case.reproduction_file.read_bytes()
                    ).hexdigest(),
                    "holdout_sha256": hashlib.sha256(case.holdout_file.read_bytes()).hexdigest(),
                }
            with Workbench(roots[source_key], typescript_analyzer=analyzer) as wb:
                index = wb._scan()
                targets = resolve_targets(task, index.files)
                pins = report["source_pins"][source_key]
                pins["indexed_source_hashes"] = {
                    p: s.source_hash for p, s in sorted(index.files.items())
                }
                pins["config_fingerprint"] = wb.policy.config.fingerprint
                pins["structural"] = index.structural
                for mode in MODES:
                    row: dict[str, Any] = {
                        "task_id": task["id"],
                        "mode": mode,
                        "status": "unavailable",
                        "error": VECTOR_UNAVAILABLE,
                        "latency_seconds": None,
                        "latency_samples_seconds": [],
                        "selected": [],
                        "selected_bytes": 2,
                        "context_bytes": None,
                        "attempts": None,
                        "reopens": None,
                        "targets": targets,
                        "score": score_targets(targets, []),
                        "source_fingerprint": index.fingerprint,
                    }
                    if mode in {"lexical", "impact"}:
                        try:
                            samples = []
                            for _ in range(repetitions):
                                started = time.perf_counter()
                                if mode == "lexical":
                                    candidates = wb.search(task["query"], mode="lexical", limit=50)[
                                        "chunks"
                                    ]
                                else:
                                    from agentic_workbench.impact import select_impact_chunks

                                    current = wb._scan()
                                    candidates = [
                                        c.to_dict()
                                        for c in select_impact_chunks(
                                            current,
                                            task["query"],
                                            current.current_chunks(wb.policy),
                                            changed_paths=task["changed_paths"],
                                        )
                                    ]
                                selected = bounded_chunks(
                                    candidates,
                                    data["limits"]["k"],
                                    data["limits"]["selected_bytes"],
                                )
                                samples.append(time.perf_counter() - started)
                            row.update(
                                status="available",
                                error=None,
                                selected=selected,
                                selected_bytes=len(canonical_json(selected).encode()),
                                latency_seconds=latency_summary(samples)["p50_seconds"],
                                latency_samples_seconds=samples,
                                latency=latency_summary(samples),
                                score=score_targets(targets, selected),
                            )
                        except (WorkbenchError, OSError, ValueError) as error:
                            row.update(status="failed", error=str(error))
                    rows.append(row)
        except (WorkbenchError, OSError, ValueError, KeyError) as error:
            setup_error = str(error)
        if setup_error is not None:
            targets = resolve_targets(task, {})
            rows.extend(
                {
                    "task_id": task["id"],
                    "mode": mode,
                    "status": "failed",
                    "error": setup_error,
                    "latency_seconds": None,
                    "selected": [],
                    "selected_bytes": 2,
                    "context_bytes": None,
                    "attempts": None,
                    "reopens": None,
                    "score": score_targets(targets, []),
                    "targets": targets,
                }
                for mode in MODES
            )
    for source_key, root in roots.items():
        task = next(t for t in data["tasks"] if t.get("corpus_task", "workspace") == source_key)
        for repetition in range(repetitions):
            destination = output / f"scan-{source_key}-{repetition + 1}"
            snapshot = snapshot_workspace(
                root,
                destination,
                isolate_evaluation_metadata=(
                    isolate_evaluation_metadata and source_key == "workspace"
                ),
            )
            report["scan_source_pins"].append(
                {"source": source_key, "repetition": repetition + 1, **snapshot}
            )
            try:
                scans.extend(
                    {"source": source_key, "repetition": repetition + 1, **row}
                    for row in scan_controls(destination, task["changed_paths"][0], analyzer)
                )
            except (WorkbenchError, OSError, ValueError) as error:
                scans.append(
                    {"source": source_key, "repetition": repetition + 1, "error": str(error)}
                )
    report["scorecards"] = summarize(rows)
    report["scan_latencies"] = {
        source: {
            phase: latency_summary(
                [
                    row["latency_seconds"]
                    for row in scans
                    if row.get("phase") == phase and row["source"] == source
                ]
            )
            for phase in ("cold", "warm", "one_file_edit", "cold_edit_comparison", "reopen")
        }
        for source in roots
    }
    if repair_controls:
        identifiers = [
            task["corpus_task"] for task in data["tasks"] if task["source"] == "python-corpus"
        ]
        report["repair_outcomes"] = {
            mode: evaluate_corpus(
                corpus_manifest,
                cache,
                output / mode,
                mode=mode,
                task_ids=identifiers,
                trials=1,
                max_attempts=1,
                backend=backend,
            )
            for mode in ("no-patch-control", "known-patch-replay")
        }
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=Path("evaluations/understanding/manifest.json")
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--typescript-package", type=Path)
    parser.add_argument("--repair-controls", action="store_true")
    parser.add_argument("--trusted-host", action="store_true")
    parser.add_argument(
        "--isolate-evaluation-metadata",
        action="store_true",
        help="Use v2 workspace corpus without the evaluations/understanding/ metadata subtree",
    )
    args = parser.parse_args()
    try:
        analyzer = None
        if args.typescript_package:
            from agentic_workbench.typescript import TypeScriptAnalyzer

            node = shutil.which("node")
            if node is None:
                raise ValueError("Trusted Node executable is unavailable")
            analyzer = TypeScriptAnalyzer(Path(node).resolve(), args.typescript_package.resolve())
        report = evaluate(
            args.manifest,
            args.workspace,
            args.cache,
            args.output,
            repetitions=args.repetitions,
            analyzer=analyzer,
            repair_controls=args.repair_controls,
            backend="trusted-host" if args.trusted_host else "docker",
            isolate_evaluation_metadata=args.isolate_evaluation_metadata,
        )
    except (WorkbenchError, OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"scorecards": report["scorecards"], "report": str(args.output / "report.json")},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
