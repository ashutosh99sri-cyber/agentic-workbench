from pathlib import Path
from threading import Event

import pytest

from agentic_workbench.agents import AgentRuntime
from agentic_workbench.changes import ChangeWorkflow
from agentic_workbench.errors import WorkbenchError
from agentic_workbench.orchestrator import Node, Orchestrator, validate_graph
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.repository import scan_workspace
from agentic_workbench.skills import SkillRegistry
from agentic_workbench.state import StateStore


def test_persisted_dependency_workflow_and_no_replay(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("value = 1\n")
    policy = WorkspacePolicy(tmp_path)
    with StateStore(policy) as store:
        runtime = AgentRuntime(
            policy,
            scan_workspace(policy),
            store,
            SkillRegistry(policy),
            ChangeWorkflow(policy, store),
        )
        orchestrator = Orchestrator(runtime)
        nodes = [Node("a", "discovery"), Node("b", "engineering", ("a",))]
        result = orchestrator.execute("improve value", nodes)
        assert [r["agent"] for r in result["results"]] == ["discovery", "engineering"]
        assert orchestrator.execute("improve value", nodes, root_id=result["task_id"]) == result
        assert len(store.export()["tasks"]) == 3
    with StateStore(policy) as reopened:
        assert reopened.get_task(result["task_id"])["state"] == "succeeded"


def test_graph_rejects_cycles_and_missing_edges() -> None:
    for nodes in ([Node("a", "engineering", ("a",))], [Node("a", "engineering", ("missing",))]):
        with pytest.raises(WorkbenchError):
            validate_graph(nodes)


def test_resume_reuses_completed_nodes_and_denies_skill_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("value=1\n")
    policy = WorkspacePolicy(tmp_path)
    with StateStore(policy) as store:
        runtime = AgentRuntime(
            policy,
            scan_workspace(policy),
            store,
            SkillRegistry(policy),
            ChangeWorkflow(policy, store),
        )
        orchestrator = Orchestrator(runtime)
        original = runtime._static
        counts: dict[str, int] = {}

        def once(task_id: str, role: str, instruction: str) -> dict:
            counts[role] = counts.get(role, 0) + 1
            if role == "engineering" and counts[role] == 1:
                raise WorkbenchError("FIXTURE_FAILURE", "First attempt fails")
            return original(task_id, role, instruction)

        monkeypatch.setattr(runtime, "_static", once)
        nodes = [Node("a", "discovery"), Node("b", "engineering", ("a",))]
        with pytest.raises(WorkbenchError):
            orchestrator.execute("value", nodes)
        root = next(t for t in store.export()["tasks"] if t["parent_id"] is None)
        pins = runtime.pins
        monkeypatch.setattr(
            runtime,
            "pins",
            lambda role: {**pins(role), "drift": True} if role == "discovery" else pins(role),
        )
        with pytest.raises(WorkbenchError):
            orchestrator.execute("value", nodes, root_id=root["id"])
        monkeypatch.setattr(runtime, "pins", pins)
        result = orchestrator.execute("value", nodes, root_id=root["id"])
        assert result["results"] and counts == {"discovery": 1, "engineering": 2}


def test_ready_child_starts_before_unrelated_sibling_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "app.py").write_text("value=1\n")
    policy = WorkspacePolicy(tmp_path)
    with StateStore(policy) as store:
        runtime = AgentRuntime(
            policy,
            scan_workspace(policy),
            store,
            SkillRegistry(policy),
            ChangeWorkflow(policy, store),
        )
        original = runtime._static
        child_started = Event()
        instructions: dict[str, str] = {}

        def specialized(task_id: str, role: str, instruction: str) -> dict:
            instructions[role] = instruction
            if role == "architecture":
                assert child_started.wait(timeout=3), "Ready child was blocked by a sibling"
            elif role == "engineering":
                child_started.set()
            return original(task_id, role, instruction)

        monkeypatch.setattr(runtime, "_static", specialized)
        nodes = [
            Node("fast", "discovery", instruction="find value"),
            Node("slow", "architecture", instruction="review structure"),
            Node("child", "engineering", ("fast",), "repair value"),
        ]
        orchestrator = Orchestrator(runtime)
        result = orchestrator.execute("overall task", nodes)
        assert [item["agent"] for item in result["results"]] == [
            "discovery",
            "architecture",
            "engineering",
        ]
        assert instructions == {
            "discovery": "find value",
            "architecture": "review structure",
            "engineering": "repair value",
        }
        assert orchestrator.execute("overall task", nodes, root_id=result["task_id"]) == result


def test_empty_or_blank_specialist_instructions_are_rejected() -> None:
    with pytest.raises(WorkbenchError):
        validate_graph([Node("node", "engineering", instruction=" ")])
