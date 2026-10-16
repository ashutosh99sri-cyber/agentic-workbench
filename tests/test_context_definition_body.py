"""Useful context keeps behavior inside modest definitions and enclosing checks."""

from pathlib import Path

from agentic_workbench.config import Config, Limits
from agentic_workbench.context import ContextManager
from agentic_workbench.impact import select_impact_chunks
from agentic_workbench.models import Evidence, canonical_json
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.repository import scan_workspace
from agentic_workbench.retrieval import Chunk
from agentic_workbench.state import StateStore


def covers(chunks: list[Chunk], path: str, line: int, text: str) -> bool:
    return any(
        chunk.evidence.path == path
        and chunk.evidence.start_line <= line <= chunk.evidence.end_line
        and text in chunk.text
        for chunk in chunks
    )


def test_modest_definition_keeps_middle_behavior_with_caller_and_check(tmp_path: Path) -> None:
    behavior = "    balance = max(0, balance)"
    body = [
        "def reconcile_ledger(values):",
        "    balance = sum(values)",
        *[f"    # preparation detail {n}" for n in range(18)],
        behavior,
        *[f"    # reporting detail {n}" for n in range(18)],
        "    return balance",
    ]
    ledger = [*["# unrelated module notes"] * 50, *body, *["# other notes"] * 20]
    (tmp_path / "ledger.py").write_text("\n".join(ledger) + "\n")
    (tmp_path / "service.py").write_text(
        "from ledger import reconcile_ledger\n"
        "def reconcile_account(values): return reconcile_ledger(values)\n"
    )
    (tmp_path / "test_ledger.py").write_text(
        "from ledger import reconcile_ledger\n"
        "def test_negative_balance(): assert reconcile_ledger([-5]) == 0\n"
    )
    assert 35 <= len(body) <= 50 and len(ledger) > 60
    line = ledger.index(behavior) + 1
    policy = WorkspacePolicy(tmp_path, Config(limits=Limits(context_bytes=6000)))
    index = scan_workspace(policy)
    query = "Update reconcile_ledger in ledger.py and include its caller and test"
    selected = select_impact_chunks(index, query, index.current_chunks(policy), ["ledger.py"])
    assert covers(selected[:6], "ledger.py", line, behavior)
    assert {"ledger.py", "service.py", "test_ledger.py"} <= {
        chunk.evidence.path for chunk in selected[:6]
    }
    with StateStore(policy) as store:
        context = ContextManager(policy, index, store).build(
            query, role="engineering", skills=[], changed_paths=["ledger.py"]
        )
    assert len(canonical_json(context).encode()) <= 6000
    assert any(
        chunk["evidence"]["path"] == "ledger.py" and behavior in chunk["text"]
        for chunk in context["retrieval"]
    )


def test_modest_enclosing_check_keeps_middle_assertion(tmp_path: Path) -> None:
    (tmp_path / "ledger.py").write_text(
        "def reconcile_ledger(values):\n    return max(0, sum(values))\n"
    )
    (tmp_path / "service.py").write_text(
        "from ledger import reconcile_ledger\n"
        "def reconcile_account(values): return reconcile_ledger(values)\n"
    )
    assertion = "    assert actual == 0"
    check_body = [
        "def test_nonnegative_balance():",
        "    actual = reconcile_ledger([-5])",
        *[f"    # arrange detail {n}" for n in range(18)],
        assertion,
        *[f"    # cleanup detail {n}" for n in range(18)],
        "    assert isinstance(actual, int)",
    ]
    checks = [
        "from ledger import reconcile_ledger",
        *["# unrelated module notes"] * 49,
        *check_body,
        *["# other notes"] * 20,
    ]
    (tmp_path / "test_ledger.py").write_text("\n".join(checks) + "\n")
    assert 35 <= len(check_body) <= 50 and len(checks) > 60
    line = checks.index(assertion) + 1
    policy = WorkspacePolicy(tmp_path, Config(limits=Limits(context_bytes=6000)))
    index = scan_workspace(policy)
    query = "Update reconcile_ledger in ledger.py and include its caller and test"
    selected = select_impact_chunks(index, query, index.current_chunks(policy), ["ledger.py"])
    assert covers(selected[:6], "test_ledger.py", line, assertion)
    assert {"ledger.py", "service.py", "test_ledger.py"} <= {
        chunk.evidence.path for chunk in selected[:6]
    }
    with StateStore(policy) as store:
        context = ContextManager(policy, index, store).build(
            query, role="engineering", skills=[], changed_paths=["ledger.py"]
        )
    assert len(canonical_json(context).encode()) <= 6000
    assert any(
        chunk["evidence"]["path"] == "test_ledger.py" and assertion in chunk["text"]
        for chunk in context["retrieval"]
    )


def test_aliased_actual_call_precedes_its_more_lexically_relevant_import(tmp_path: Path) -> None:
    (tmp_path / "ledger.py").write_text(
        "def reconcile_ledger(values):\n    return max(0, sum(values))\n"
    )
    actual_call = "    return apply_balance(rows)"
    service = [
        "from ledger import reconcile_ledger as apply_balance",
        *["# unrelated module notes"] * 70,
        "def calculate_report(rows):",
        actual_call,
    ]
    (tmp_path / "service.py").write_text("\n".join(service) + "\n")
    (tmp_path / "test_ledger.py").write_text(
        "from ledger import reconcile_ledger\n"
        "def test_negative_balance(): assert reconcile_ledger([-5]) == 0\n"
    )
    policy = WorkspacePolicy(tmp_path)
    index = scan_workspace(policy)
    declaration = next(symbol for symbol in index.symbols if symbol["name"] == "reconcile_ledger")
    declaration["id"] = "ledger.py:reconcile_ledger"
    # Model a resolved alias while keeping every citation on real parsed source.
    call = next(call for call in index.calls if call["callee"] == "apply_balance")
    call["target_id"] = declaration["id"]
    call["resolution"] = "static-symbol"
    index.imports.append(
        {
            "module": "ledger",
            "imported": "reconcile_ledger",
            "local": "apply_balance",
            "target_id": declaration["id"],
            "resolution": "static-symbol",
            "evidence": Evidence(
                "service.py", 1, 1, index.files["service.py"].source_hash
            ).to_dict(),
        }
    )
    selected = select_impact_chunks(
        index,
        "Update reconcile_ledger in ledger.py and include its caller and test",
        index.current_chunks(policy),
        ["ledger.py"],
    )
    assert covers(selected[:3], "service.py", len(service), actual_call)
    assert {"ledger.py", "service.py", "test_ledger.py"} <= {
        chunk.evidence.path for chunk in selected[:3]
    }
