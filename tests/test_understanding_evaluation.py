"""Fixed-target evaluation controls keep failures and enforce equal budgets."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentic_workbench.models import canonical_json

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "evaluate_understanding", ROOT / "scripts/evaluate_understanding.py"
)
assert spec is not None and spec.loader is not None
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_fixed_manifest_covers_real_python_native_node_and_historical_repairs() -> None:
    data = evaluation.read_manifest(ROOT / "evaluations/understanding/manifest.json")
    assert len(data["tasks"]) == 6
    assert data["limits"] == {"k": 6, "selected_bytes": 16_000}
    groups = {task["source"] for task in data["tasks"]}
    assert groups == {"workspace", "python-corpus"}
    workspace_paths = {
        target["path"]
        for task in data["tasks"]
        if task["source"] == "workspace"
        for targets in task["targets"].values()
        for target in targets
    }
    assert any(path.endswith(".py") for path in workspace_paths)
    assert any(path.endswith(".ts") for path in workspace_paths)
    assert any(path.endswith(".mjs") for path in workspace_paths)


@pytest.mark.parametrize("mutation", ["limits-list", "duplicate-id", "escaping-target"])
def test_manifest_rejects_malformed_limits_duplicate_tasks_and_escaping_sources(
    tmp_path: Path, mutation: str
) -> None:
    data = json.loads((ROOT / "evaluations/understanding/manifest.json").read_text())
    if mutation == "limits-list":
        data["limits"] = []
    elif mutation == "duplicate-id":
        data["tasks"][1]["id"] = data["tasks"][0]["id"]
    else:
        data["tasks"][0]["targets"]["edited"][0]["path"] = "../outside.py"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        evaluation.read_manifest(manifest)


def chunk(path: str, start: int, text: str) -> dict:
    return {
        "evidence": {"path": path, "start_line": start, "end_line": start, "source_hash": "a" * 64},
        "text": text,
    }


def test_equal_budget_counts_serialized_overhead_utf8_and_deduplicates() -> None:
    first, second = chunk("a.py", 1, "é" * 10), chunk("b.py", 1, "second")
    budget = len(canonical_json([first]).encode())
    assert evaluation.bounded_chunks([first, first, second], 2, budget) == [first]
    assert evaluation.bounded_chunks([first, second], 1, 10000) == [first]
    assert evaluation.bounded_chunks([first], 1, budget - 1) == []


def test_scoring_requires_exact_anchor_line_and_missing_source_stays_a_miss() -> None:
    task = {
        "targets": {
            "edited": [{"path": "a.py", "anchor": "def target"}],
            "callers": [{"path": "a.py", "anchor": "target()"}],
            "checks": [{"path": "missing.py", "anchor": "assert"}],
        }
    }
    targets = evaluation.resolve_targets(
        task, {"a.py": SimpleNamespace(text="# prefix\ndef target(): pass\ntarget()\n")}
    )
    score = evaluation.score_targets(targets, [chunk("a.py", 1, "prefix")])
    assert score["groups"]["edited"]["hits"] == 0
    score = evaluation.score_targets(targets, [chunk("a.py", 2, "definition")])
    assert score["groups"]["edited"]["complete"]
    assert not score["complete"]
    assert targets["checks"][0]["line"] is None


def test_unavailable_and_failed_tasks_remain_in_selected_denominator() -> None:
    rows = [
        {
            "mode": "vector",
            "status": "unavailable",
            "latency_seconds": None,
            "score": {"complete": False},
        },
        {
            "mode": "impact",
            "status": "available",
            "latency_seconds": 0.1,
            "score": {"complete": True},
        },
        {
            "mode": "impact",
            "status": "failed",
            "latency_seconds": None,
            "score": {"complete": False},
        },
    ]
    report = evaluation.summarize(rows)
    assert report["vector"]["selected"] == 1
    assert report["vector"]["available"] == 0
    assert not report["vector"]["effectiveness_measured"]
    assert report["vector"]["p95_seconds"] is None
    assert report["impact"]["complete_rate_selected"] == 0.5
    assert evaluation.latency_summary([0.3, 0.1, 0.2]) == {
        "samples": 3,
        "p50_seconds": 0.2,
        "p95_seconds": 0.3,
    }


def test_scan_controls_count_reuse_rebuild_reopen_and_restore_source(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("def value():\n    return 1\n")
    (tmp_path / "test_app.py").write_text("from app import value\nassert value() == 1\n")
    original = source.read_bytes()
    rows = {row["phase"]: row for row in evaluation.scan_controls(tmp_path, "app.py", None)}
    assert rows["cold"]["cache_stats"]["rebuilt"] == 2
    assert rows["warm"]["cache_stats"]["reused"] == 2
    assert rows["one_file_edit"]["cache_stats"]["rebuilt"] == 1
    assert rows["one_file_edit"]["cache_stats"]["reused"] == 1
    assert rows["cold_edit_comparison"]["equivalent_base_facts"]
    assert rows["reopen"]["equivalent_base_facts"]
    assert source.read_bytes() == original


def test_snapshot_isolation_excludes_only_declared_metadata_and_preserves_policy(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    paths = {
        "app.py": "def value():\n    return 1\n",
        "evaluations/understanding/manifest.json": '{"query": "answer metadata"}\n',
        "evaluations/understanding/nested/report.json": '{"answer": "value"}\n',
        "evaluations/understanding-extra/manifest.json": "{}\n",
        "src/evaluations/understanding/manifest.json": "{}\n",
        "evaluations/python/manifest.json": "{}\n",
        "settings.toml": "api_key = local-development-key\n",
        ".git/config": "private git metadata\n",
    }
    for relative, text in paths.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (source / "alias.py").symlink_to(source / "app.py")
    legacy = evaluation.snapshot_workspace(source, tmp_path / "legacy")
    isolated = evaluation.snapshot_workspace(
        source, tmp_path / "isolated", isolate_evaluation_metadata=True
    )
    omitted = {
        relative: hashlib.sha256(text.encode()).hexdigest()
        for relative, text in paths.items()
        if relative.startswith("evaluations/understanding/")
    }
    assert legacy["corpus_protocol"] == "policy-bounded-v1"
    assert legacy["evaluation_metadata_exclusions"]["omitted_source_hashes"] == {}
    assert isolated["corpus_protocol"] == "policy-bounded-without-evaluation-metadata-v2"
    assert isolated["evaluation_metadata_exclusions"] == {
        "subtrees": ["evaluations/understanding/"],
        "omitted_source_hashes": omitted,
        "policy_approved_files": 7,
        "copied_files": 5,
    }
    assert set(legacy["original_raw_source_hashes"]) - set(
        isolated["original_raw_source_hashes"]
    ) == set(omitted)
    for relative in paths:
        if relative.startswith(".git/"):
            assert not (tmp_path / "legacy" / relative).exists()
        elif relative in omitted:
            assert (tmp_path / "legacy" / relative).exists()
            assert not (tmp_path / "isolated" / relative).exists()
        else:
            assert (tmp_path / "isolated" / relative).exists()
    assert not (tmp_path / "isolated/alias.py").exists()
    assert "local-development-key" not in (tmp_path / "isolated/settings.toml").read_text()
    assert isolated["source_fingerprint"] != legacy["source_fingerprint"]
    assert (source / "settings.toml").read_text() == paths["settings.toml"]


@pytest.mark.parametrize("isolated", [False, True])
def test_evaluation_uses_same_explicit_corpus_for_retrieval_and_repeated_scans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated: bool
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("def value():\n    return 1\n")
    metadata = source / "evaluations/understanding/manifest.json"
    metadata.parent.mkdir(parents=True)
    task = {
        "id": "value",
        "source": "workspace",
        "query": "value",
        "changed_paths": ["app.py"],
        "targets": {
            group: [{"path": "app.py", "anchor": "def value()"}]
            for group in ("edited", "callers", "checks")
        },
    }
    manifest_bytes = json.dumps(
        {
            "schema_version": 1,
            "protocol": "fixed",
            "limits": {"k": 6, "selected_bytes": 16_000},
            "tasks": [task],
        }
    ).encode()
    metadata.write_bytes(manifest_bytes)
    corpus_manifest = source / "evaluations/python/manifest.json"
    corpus_manifest.parent.mkdir()
    corpus_manifest.write_text("{}")
    corpus_manifest.with_name("archives.lock.json").write_text("{}")
    monkeypatch.setattr(
        evaluation, "load_corpus", lambda path: SimpleNamespace(tasks=[], archives={})
    )
    copied_modes = []
    snapshot = evaluation.snapshot_workspace

    def capture_snapshot(source: Path, destination: Path, **kwargs: bool) -> dict:
        copied_modes.append(kwargs.get("isolate_evaluation_metadata", False))
        return snapshot(source, destination, **kwargs)

    monkeypatch.setattr(evaluation, "snapshot_workspace", capture_snapshot)
    output = tmp_path / "output"
    report = evaluation.evaluate(
        metadata,
        source,
        tmp_path / "cache",
        output,
        repetitions=2,
        isolate_evaluation_metadata=isolated,
    )
    expected_protocol = (
        "policy-bounded-without-evaluation-metadata-v2" if isolated else "policy-bounded-v1"
    )
    assert copied_modes == [isolated, isolated, isolated]
    assert report["corpus_protocol"] == expected_protocol
    assert report["limits"] == {"k": 6, "selected_bytes": 16_000}
    assert (output / "frozen-manifest.json").read_bytes() == manifest_bytes
    pins = report["source_pins"]["workspace"]
    metadata_path = "evaluations/understanding/manifest.json"
    assert (metadata_path in pins["indexed_source_hashes"]) is not isolated
    assert pins["corpus_protocol"] == expected_protocol
    for destination in ("workspace-source", "scan-workspace-1", "scan-workspace-2"):
        assert (output / destination / metadata_path).exists() is not isolated
    assert len(report["scan_source_pins"]) == 2
    assert all(pin["corpus_protocol"] == expected_protocol for pin in report["scan_source_pins"])
    assert all(
        row["targets"]["edited"] == [{"path": "app.py", "anchor": "def value()", "line": 1}]
        for row in report["rows"]
    )
    assert report["scorecards"]["vector"]["unavailable_or_failed"] == 1
    assert report["usage"]["requests"] == 0


@pytest.mark.parametrize("isolated", [False, True])
def test_cli_isolation_is_explicit_opt_in(monkeypatch: pytest.MonkeyPatch, isolated: bool) -> None:
    received = {}

    def capture_evaluate(*args: object, **kwargs: object) -> dict:
        received.update(kwargs)
        return {"scorecards": {}}

    monkeypatch.setattr(evaluation, "evaluate", capture_evaluate)
    monkeypatch.setattr(
        evaluation.sys,
        "argv",
        ["evaluate_understanding.py", "--cache", "cache", "--output", "output"]
        + (["--isolate-evaluation-metadata"] if isolated else []),
    )
    assert evaluation.main() == 0
    assert received["isolate_evaluation_metadata"] is isolated
