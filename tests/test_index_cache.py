import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from agentic_workbench import index_cache
from agentic_workbench.config import Config, ScanConfig
from agentic_workbench.index_cache import IncrementalIndexCache
from agentic_workbench.models import canonical_json
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.repository import RepositoryIndex, scan_workspace
from agentic_workbench.secrets import SecretRedactor
from agentic_workbench.state import StateStore

MARKER = "unique_source_marker_7f3a"


def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "billing.py").write_text(
        f"def total(items):\n    return sum(items)  # {MARKER}\n"
    )
    (root / "app.py").write_text("from pkg.billing import total\n\nprint(total([1]))\n")
    (root / "bad.py").write_text("def broken(\n")
    (root / "pyproject.toml").write_text('[project]\nname="demo"\ndependencies=["fastapi"]\n')
    return root


def counted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real = index_cache.index_source

    def counting(source: Any) -> RepositoryIndex:
        calls.append(source.path)
        return real(source)

    monkeypatch.setattr(index_cache, "index_source", counting)
    return calls


def facts(index: RepositoryIndex) -> dict[str, Any]:
    return {**index.to_dict(), "cache_stats": None, "chunks": [c.to_dict() for c in index.chunks]}


def test_warm_refresh_reuses_parses_and_matches_a_cold_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = workspace(tmp_path)
    policy = WorkspacePolicy(root)
    parsed = counted(monkeypatch)
    cache = IncrementalIndexCache()
    with StateStore(policy) as store:
        cold = cache.refresh(policy, store)
        assert cold.cache_stats["rebuilt"] == cold.cache_stats["files_read"] == len(cold.files)
        assert len(parsed) == len(cold.files)
        parsed.clear()
        warm = cache.refresh(policy, store)
        assert not parsed and warm.cache_stats["reused"] == len(warm.files)
        assert warm.cache_stats["rebuilt"] == warm.cache_stats["deleted"] == 0
    assert facts(warm) == facts(cold) == facts(scan_workspace(policy))
    assert warm.fingerprint == scan_workspace(policy).fingerprint


def test_an_equal_size_equal_mtime_edit_is_rebuilt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = workspace(tmp_path)
    policy = WorkspacePolicy(root)
    cache = IncrementalIndexCache()
    target = root / "pkg" / "billing.py"
    with StateStore(policy) as store:
        cache.refresh(policy, store)
        before = target.stat()
        target.write_text(target.read_text().replace("total", "summa"))
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert target.stat().st_size == before.st_size
        parsed = counted(monkeypatch)
        index = cache.refresh(policy, store)
    assert parsed == ["pkg/billing.py"] and index.cache_stats["rebuilt"] == 1
    assert {s["name"] for s in index.symbols} == {"summa"}
    assert facts(index) == facts(scan_workspace(policy))


def test_new_deleted_and_newly_ignored_files_never_contribute_old_facts(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    policy = WorkspacePolicy(root)
    cache = IncrementalIndexCache()
    with StateStore(policy) as store:
        cache.refresh(policy, store)
        (root / "extra.py").write_text("def extra():\n    return 1\n")
        (root / "app.py").unlink()
        (root / ".gitignore").write_text("pkg/\n")
        index = cache.refresh(policy, store)
    names = {s["name"] for s in index.symbols}
    assert "extra" in names and "total" not in names
    assert not any(c["evidence"]["path"] == "app.py" for c in index.calls)
    assert index.cache_stats["deleted"] == 2 and index.cache_stats["rebuilt"] == 2
    assert facts(index) == facts(scan_workspace(policy))


def test_a_redaction_or_configuration_change_rebuilds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = workspace(tmp_path)
    (root / "keys.py").write_text("def fetch_hunter2_value():\n    return 1\n")
    cache = IncrementalIndexCache()
    plain = WorkspacePolicy(root)
    redacting = WorkspacePolicy(root, redactor=SecretRedactor(("hunter2",)))
    with StateStore(plain) as store:
        cache.refresh(plain, store)
        parsed = counted(monkeypatch)
        # Same raw bytes, different presented text: only that file is derived again.
        index = cache.refresh(redacting, store)
        assert parsed == ["keys.py"] and facts(index) == facts(scan_workspace(redacting))
        assert not any("hunter2" in s["name"] for s in index.symbols)
        parsed.clear()
        changed = WorkspacePolicy(root, Config(scan=ScanConfig(max_files=999)))
        cache.refresh(changed, store)
        assert len(parsed) == len(index.files)


def test_the_durable_snapshot_is_reused_after_reopen_bounded_and_holds_no_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = workspace(tmp_path)
    policy = WorkspacePolicy(root)
    with StateStore(policy) as store:
        first = IncrementalIndexCache().refresh(policy, store)
        record = store.load("index", "derived")
        assert record["persisted"] == len(first.files) and record["truncated"] == 0
        assert MARKER not in canonical_json(record)
    parsed = counted(monkeypatch)
    with StateStore(policy) as store:
        reopened = IncrementalIndexCache().refresh(policy, store)
    assert not parsed and reopened.cache_stats["reused"] == len(reopened.files)
    assert facts(reopened) == facts(first)
    monkeypatch.setattr(index_cache, "_RECORD_BYTES", 400)
    with StateStore(policy) as store:
        bounded = IncrementalIndexCache().refresh(policy, store)
        record = store.load("index", "derived")
    assert 0 < record["persisted"] < len(bounded.files)
    assert record["truncated"] == len(bounded.files) - record["persisted"]
    assert bounded.cache_stats["truncated"] == record["truncated"]


DAMAGE = {
    "garbage": None,
    "foreign-path": ("pkg/billing.py", "symbols", lambda f: f["evidence"].update(path="app.py")),
    "foreign-hash": (
        "pkg/billing.py",
        "symbols",
        lambda f: f["evidence"].update(source_hash="0" * 64),
    ),
    "symbol-without-name": ("pkg/billing.py", "symbols", lambda f: f.pop("name")),
    "symbol-kind-not-text": ("pkg/billing.py", "symbols", lambda f: f.update(kind=7)),
    "call-without-callee": ("pkg/billing.py", "calls", lambda f: f.pop("callee")),
    "line-past-end": ("pkg/billing.py", "symbols", lambda f: f["evidence"].update(end_line=99)),
    "line-zero": ("pkg/billing.py", "calls", lambda f: f["evidence"].update(start_line=0)),
    "line-not-integer": (
        "pkg/billing.py",
        "symbols",
        lambda f: f["evidence"].update(start_line="1"),
    ),
    "extra-evidence-key": ("pkg/billing.py", "calls", lambda f: f["evidence"].update(note=1)),
    "manifest-type": ("pyproject.toml", "manifests", lambda f: f.update(dependencies="fastapi")),
    "version": None,
}


@pytest.mark.parametrize("damage", sorted(DAMAGE))
def test_corrupt_tampered_or_mismatched_durable_facts_are_rebuilt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    root = workspace(tmp_path)
    policy = WorkspacePolicy(root)
    target = "pyproject.toml" if damage == "manifest-type" else "pkg/billing.py"
    with StateStore(policy) as store:
        IncrementalIndexCache().refresh(policy, store)
        record = store.load("index", "derived")
        if damage == "garbage":
            record = {"binding": record["binding"], "entries": "not a list"}
        elif damage == "version":
            monkeypatch.setattr(index_cache, "INDEX_ANALYSIS_VERSION", "2")
        else:
            path, kind, corrupt = DAMAGE[damage]
            entry = next(e for e in record["entries"] if e["path"] == path)
            corrupt(entry["facts"][kind][0])
        store.update("index", "derived", record)
    parsed = counted(monkeypatch)
    with StateStore(policy) as store:
        index = IncrementalIndexCache().refresh(policy, store)
    # Invalid persisted rows are acceleration only: they are rebuilt, never trusted.
    assert target in parsed
    assert facts(index) == facts(scan_workspace(policy))
    assert index.trace("total")["definitions"]


@pytest.mark.parametrize(
    "raw",
    [
        "{broken",
        '{"binding": {}, "entries": [], "persisted": NaN, "truncated": 0}',
        '{"binding": {}, "entries": [], "persisted": Infinity, "truncated": 0}',
    ],
    ids=["malformed-json", "nan", "infinity"],
)
def test_an_undecodable_durable_record_still_yields_a_fresh_cold_index(
    tmp_path: Path, raw: str
) -> None:
    root = workspace(tmp_path)
    policy = WorkspacePolicy(root)
    with StateStore(policy) as store:
        IncrementalIndexCache().refresh(policy, store)
        path = store.path
    with closing(sqlite3.connect(path)) as connection, connection:
        changed = connection.execute(
            "UPDATE records SET value = ? WHERE kind = 'index' AND id = 'derived'", (raw,)
        ).rowcount
    assert changed == 1
    with StateStore(policy) as store:
        index = IncrementalIndexCache().refresh(policy, store)
        assert index.cache_stats["rebuilt"] == len(index.files) and index.cache_stats["reused"] == 0
        assert facts(index) == facts(scan_workspace(policy))
        # The corrupt row is replaced by a valid snapshot, so the next reopen is warm again.
        assert store.load("index", "derived")["persisted"] == len(index.files)
    with StateStore(policy) as store:
        assert IncrementalIndexCache().refresh(policy, store).cache_stats["reused"] == len(
            index.files
        )
