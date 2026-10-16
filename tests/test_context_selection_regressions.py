"""Behavioral retrieval coverage from independent, synthetic source repositories."""

import hashlib
from pathlib import Path
from typing import Any

import pytest

from agentic_workbench.config import Config, Limits
from agentic_workbench.context import ContextManager
from agentic_workbench.errors import WorkbenchError
from agentic_workbench.impact import select_impact_chunks
from agentic_workbench.models import Evidence, canonical_json
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.repository import scan_workspace
from agentic_workbench.sdk import Workbench
from agentic_workbench.state import StateStore

ENTRY_POINTS = ("selector", "manager", "workbench")


def _write(root: Path, path: str, text: str) -> None:
    destination = root / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


def _long_function(name: str, steps: int) -> str:
    return (
        f"def {name}(frames):\n"
        "    weighted = len(frames)\n"
        + "".join(f"    weighted += {step}\n" for step in range(steps))
        + "    if not frames:\n"
        '        return "paused"\n'
        "    return weighted + 19\n"
    )


def _select(root: Path, query: str, entry_point: str) -> list[dict[str, Any]]:
    config = Config(limits=Limits(context_bytes=7000))
    if entry_point == "workbench":
        with Workbench(root, config) as workbench:
            assert workbench.policy.config.provider.name == "none"
            assert not workbench.policy.grants.network
            context = workbench.context(query)
    else:
        policy = WorkspacePolicy(root, config)
        index = scan_workspace(policy)
        if entry_point == "selector":
            return [
                chunk.to_dict()
                for chunk in select_impact_chunks(index, query, index.current_chunks(policy))
            ]
        with StateStore(policy) as store:
            context = ContextManager(policy, index, store).build(
                query, role="engineering", skills=[]
            )
    assert len(canonical_json(context).encode()) <= config.limits.context_bytes
    return context["retrieval"]


def _assert_exact_source_spans(root: Path, citations: list[dict[str, Any]]) -> None:
    policy = WorkspacePolicy(root)
    for item in citations:
        evidence = Evidence(**item["evidence"])
        source = policy.read_source(evidence.path)
        lines = source.text.splitlines()
        assert 1 <= evidence.start_line <= evidence.end_line <= len(lines)
        assert item["text"] == "\n".join(lines[evidence.start_line - 1 : evidence.end_line])
        assert (
            evidence.source_hash == hashlib.sha256((root / evidence.path).read_bytes()).hexdigest()
        )


@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
def test_long_definition_keeps_final_behavior_caller_and_check_in_first_six_citations(
    tmp_path: Path, entry_point: str
) -> None:
    _write(tmp_path, "lantern.py", _long_function("dispatch_lantern", 420))
    _write(
        tmp_path,
        "harbor.py",
        "from lantern import dispatch_lantern\n\n"
        "def reopen_harbor():\n    return dispatch_lantern([3])\n",
    )
    _write(
        tmp_path,
        "tests/test_harbor.py",
        "from lantern import dispatch_lantern\n\n"
        "def test_paused_harbor():\n    assert dispatch_lantern([]) == 'paused'\n",
    )
    citations = _select(
        tmp_path,
        "Explain dispatch_lantern in lantern.py, its final return behavior, caller and check.",
        entry_point,
    )
    _assert_exact_source_spans(tmp_path, citations)
    first = citations[:6]
    paths = {item["evidence"]["path"] for item in first}
    assert {"lantern.py", "harbor.py", "tests/test_harbor.py"} <= paths
    text = "\n".join(item["text"] for item in first)
    assert "def dispatch_lantern(" in text
    assert "return weighted + 19" in text
    assert "return dispatch_lantern([3])" in text
    assert "assert dispatch_lantern([]) == 'paused'" in text


@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
def test_two_explicit_target_files_leave_room_for_their_users_and_checks(
    tmp_path: Path, entry_point: str
) -> None:
    _write(tmp_path, "east.py", _long_function("steer_eastward", 210))
    _write(tmp_path, "west.py", _long_function("steer_westward", 210))
    _write(
        tmp_path,
        "relay.py",
        "from east import steer_eastward\nfrom west import steer_westward\n\n"
        "def route_frames(frames):\n"
        "    return steer_eastward(frames), steer_westward(frames)\n",
    )
    _write(
        tmp_path,
        "tests/test_routes.py",
        "from east import steer_eastward\nfrom west import steer_westward\n\n"
        "def test_empty_routes():\n"
        "    assert steer_eastward([]) == 'paused'\n"
        "    assert steer_westward([]) == 'paused'\n",
    )
    citations = _select(
        tmp_path,
        "Review steer_eastward in east.py and steer_westward in west.py "
        "with their callers and checks.",
        entry_point,
    )
    _assert_exact_source_spans(tmp_path, citations)
    first = citations[:6]
    assert {"east.py", "west.py", "relay.py", "tests/test_routes.py"} <= {
        item["evidence"]["path"] for item in first
    }
    text = "\n".join(item["text"] for item in first)
    assert "def steer_eastward(" in text and "def steer_westward(" in text
    assert "return steer_eastward(frames), steer_westward(frames)" in text
    assert "assert steer_eastward([])" in text and "assert steer_westward([])" in text


@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
def test_natural_query_naming_only_a_symbol_finds_its_definition_user_and_check(
    tmp_path: Path, entry_point: str
) -> None:
    _write(tmp_path, "cairn.py", _long_function("settle_cairn", 90))
    _write(
        tmp_path,
        "arrival.py",
        "from cairn import settle_cairn\n\n"
        "def accept_arrival(events):\n    return settle_cairn(events)\n",
    )
    _write(
        tmp_path,
        "tests/test_arrival.py",
        "from cairn import settle_cairn\n\n"
        "def test_vacant_arrival():\n    assert settle_cairn([]) == 'paused'\n",
    )
    _write(
        tmp_path,
        "planning_notes.py",
        "# settle_cairn handles a vacant batch; show a caller and a check.\n" * 420,
    )
    citations = _select(
        tmp_path,
        "Explain how settle_cairn handles a vacant batch and show a caller and a check.",
        entry_point,
    )
    _assert_exact_source_spans(tmp_path, citations)
    first = citations[:6]
    assert {"cairn.py", "arrival.py", "tests/test_arrival.py"} <= {
        item["evidence"]["path"] for item in first
    }
    assert any("def settle_cairn(" in item["text"] for item in first)
    assert any("return settle_cairn(events)" in item["text"] for item in first)
    assert any("assert settle_cairn([])" in item["text"] for item in first)


@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
def test_selected_citations_keep_exact_redacted_spans_and_original_source_hashes(
    tmp_path: Path, entry_point: str
) -> None:
    secret = "lantern-synthetic-private-value"
    _write(
        tmp_path,
        "beacon.py",
        f"password = '{secret}'\n\ndef inspect_beacon():\n    return 'ready'\n",
    )
    citations = _select(tmp_path, "Explain inspect_beacon in beacon.py", entry_point)
    assert citations
    _assert_exact_source_spans(tmp_path, citations)
    serialized = canonical_json(citations)
    assert secret not in serialized
    assert "[REDACTED]" in serialized


def test_stale_manager_sources_are_not_reintroduced_by_symbol_or_path_selection(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "beacon.py", "def rotate_beacon():\n    return 'old bearing'\n")
    policy = WorkspacePolicy(tmp_path)
    index = scan_workspace(policy)
    with StateStore(policy) as store:
        manager = ContextManager(policy, index, store)
        _write(tmp_path, "beacon.py", "def rotate_beacon():\n    return 'new bearing'\n")
        for query in ("Explain rotate_beacon", "Explain rotate_beacon in beacon.py"):
            assert manager.build(query, role="engineering", skills=[])["retrieval"] == []
        with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
            manager.build("password='do-not-send-this-value'", role="engineering", skills=[])


def test_workbench_refreshes_changed_sources_before_returning_citations(tmp_path: Path) -> None:
    _write(tmp_path, "beacon.py", "def rotate_beacon():\n    return 'old bearing'\n")
    with Workbench(tmp_path) as workbench:
        before = workbench.context("Explain rotate_beacon in beacon.py")["retrieval"]
        _write(tmp_path, "beacon.py", "def rotate_beacon():\n    return 'new bearing'\n")
        after = workbench.context("Explain rotate_beacon in beacon.py")["retrieval"]
    assert before and after
    _assert_exact_source_spans(tmp_path, after)
    assert before[0]["evidence"]["source_hash"] != after[0]["evidence"]["source_hash"]
    assert "old bearing" not in canonical_json(after)
    assert "new bearing" in canonical_json(after)
