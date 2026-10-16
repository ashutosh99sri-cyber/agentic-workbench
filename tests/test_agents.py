from dataclasses import replace
from pathlib import Path

import pytest

from agentic_workbench import Grant, Workbench
from agentic_workbench.agents import AgentRuntime
from agentic_workbench.changes import ChangeWorkflow
from agentic_workbench.config import Config, Limits, PolicyConfig
from agentic_workbench.errors import WorkbenchError
from agentic_workbench.models import (
    AgentResult,
    Evidence,
    Finding,
    Usage,
    canonical_json,
    text_hash,
)
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.providers import ProviderResult
from agentic_workbench.repository import scan_workspace
from agentic_workbench.skills import ROLES, SkillRegistry
from agentic_workbench.state import StateStore


@pytest.mark.parametrize("role", ROLES)
def test_independent_roles_persist_real_results(tmp_path: Path, role: str) -> None:
    (tmp_path / "app.py").write_text("def invoice(x):\n    return x * 2\n")
    (tmp_path / "Page.tsx").write_text('<img src="logo.png" />')
    policy = WorkspacePolicy(tmp_path)
    with StateStore(policy) as store:
        runtime = AgentRuntime(
            policy,
            scan_workspace(policy),
            store,
            SkillRegistry(policy),
            ChangeWorkflow(policy, store),
        )
        result = runtime.run(role, "invoice")
        assert result["agent"] == role and result["mode"] == "static"
        assert store.get_task(result["task_id"])["state"] == "succeeded"
        assert result["usage"]["requests"] == 0
        if role == "ux":
            assert result["findings"][0]["title"].startswith("Image")


def test_model_candidate_is_saved_and_never_auto_applied(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("value=1\n")

    class CandidateProvider:
        def analyze(self, request: str, context: dict, **kwargs: object) -> ProviderResult:
            return ProviderResult(
                {
                    "summary": "Fixture candidate",
                    "findings": [],
                    "recommendations": [],
                    "candidate_edits": [
                        {
                            "path": "app.py",
                            "base_hash": text_hash("value=1\n"),
                            "content": "value=2\n",
                            "delete": False,
                        }
                    ],
                    "limitations": ["Deterministic integration fixture"],
                },
                Usage(),
            )

    with Workbench(
        tmp_path, grants=Grant(network=True, write=True), provider=CandidateProvider()
    ) as wb:
        result = wb.run_agent("engineering", "Improve value")
        assert target.read_text() == "value=1\n" and result["proposal_ids"]
        review = wb.review(result["proposal_ids"][0])
        wb.apply(review["proposal_id"], approval=review["digest"], dry_run=False)
        assert target.read_text() == "value=2\n"


class ContextProvider:
    def __init__(self) -> None:
        self.context = {}
        self.tools = []

    def analyze(self, request: str, context: dict, **kwargs: object) -> ProviderResult:
        self.context = context
        self.tools = kwargs["executor"].schemas
        return ProviderResult(
            {
                "summary": "Review",
                "findings": [],
                "recommendations": [],
                "candidate_edits": [],
                "limitations": [],
            },
            Usage(),
        )


@pytest.mark.parametrize(
    "requirements,workspace_tools,expected",
    [
        (((), ()), ("read_source", "search_code", "lookup_memory"), set()),
        (
            (("read_source",), ("search_code",)),
            ("read_source", "search_code", "lookup_memory"),
            {"read_source", "search_code"},
        ),
        (
            (("read_source",), ("search_code", "lookup_memory")),
            ("read_source", "lookup_memory"),
            {"read_source", "lookup_memory"},
        ),
    ],
)
def test_selected_skills_bound_effective_tools(
    tmp_path: Path, requirements: tuple, workspace_tools: tuple, expected: set
) -> None:
    (tmp_path / "app.py").write_text("value=1\n")
    policy = WorkspacePolicy(
        tmp_path,
        Config(policy=PolicyConfig(allowed_tools=workspace_tools)),
        grants=Grant(network=True),
    )
    registry = SkillRegistry(policy)
    selected = registry.select("engineering", [], ["python"])
    assert len(selected) == len(requirements) == 2
    registry.skills = [
        replace(skill, required_tools=tools)
        for skill, tools in zip(selected, requirements, strict=True)
    ]
    provider = ContextProvider()
    with StateStore(policy) as store:
        runtime = AgentRuntime(
            policy, scan_workspace(policy), store, registry, ChangeWorkflow(policy, store), provider
        )
        runtime.run("engineering", "value")
    assert {item["name"] for item in provider.tools} == expected


@pytest.mark.parametrize("oversized", [False, True])
def test_specialist_dependency_context_has_evidence_limits_and_task_id(
    tmp_path: Path, oversized: bool
) -> None:
    (tmp_path / "app.py").write_text("value=1\n")
    citation = Evidence("app.py", 1, 1, text_hash("value=1\n"))
    findings = [Finding("Dependency fact", "Source detail", "fact", evidence=[citation])]
    if oversized:
        findings += [
            Finding(f"Finding {i}", "detail" * 500, evidence=[citation]) for i in range(50)
        ]
    dependency = AgentResult(
        "upstream-task",
        "intelligence",
        "llm",
        "Summary" * (200 if oversized else 1),
        evidence=[citation],
        findings=findings,
        limitations=["Dynamic dispatch remains unknown"],
    ).to_dict()
    provider = ContextProvider()
    with Workbench(tmp_path, grants=Grant(network=True), provider=provider) as wb:
        wb._runtime().run("engineering", "value", dependencies=[dependency])
        context = provider.context
        item = context["dependencies"][0]
        assert item["task_id"] == "upstream-task"
        assert item["findings"][0]["evidence"] == [citation.to_dict()]
        assert item["findings"][0]["details"] == "Source detail"
        assert item["limitations"] == ["Dynamic dispatch remains unknown"]
        assert context["dependencies_truncated"] is oversized
        assert len(canonical_json(context["dependencies"]).encode()) <= (
            wb.policy.config.limits.context_bytes // 4
        )


@pytest.mark.parametrize("identity_only", [False, True])
def test_dependency_fan_in_reserves_all_seven_task_identities(
    tmp_path: Path, identity_only: bool
) -> None:
    (tmp_path / "app.py").write_text("value=1\n")
    citation = Evidence("app.py", 1, 1, text_hash("value=1\n"))
    dependencies = [
        AgentResult(
            f"task-{role}",
            role,
            "llm",
            "Summary" * 1_000,
            findings=[
                Finding(f"Fact {i}", "details" * 500, "fact", evidence=[citation] * 20)
                for i in range(10)
            ],
            limitations=["Unverified behavior" * 100] * 5,
        ).to_dict()
        for role in ROLES[:-1]
    ]
    identities = [
        {"task_id": item["task_id"], "agent": item["agent"], "truncated": True}
        for item in dependencies
    ]
    maximum = len(canonical_json(identities).encode()) + 1 if identity_only else 4_000
    provider = ContextProvider()
    with Workbench(
        tmp_path,
        Config(limits=Limits(context_bytes=maximum * 4)),
        grants=Grant(network=True),
        provider=provider,
    ) as wb:
        wb._runtime().run("orchestrator", "Review value", dependencies=dependencies)
        received = provider.context["dependencies"]
        assert [item["task_id"] for item in received] == [item["task_id"] for item in dependencies]
        assert [item["agent"] for item in received] == list(ROLES[:-1])
        assert provider.context["dependencies_truncated"] is True
        assert all(item["truncated"] for item in received)
        assert len(canonical_json(received).encode()) <= wb.policy.config.limits.context_bytes // 4
        citations = [
            e
            for item in received
            for finding in item.get("findings", [])
            for e in finding["evidence"]
        ]
        assert all(e == citation.to_dict() for e in citations)
        assert bool(citations) is not identity_only


def test_dependency_identities_that_cannot_fit_fail_before_provider(tmp_path: Path) -> None:
    dependencies = [
        AgentResult(f"{role}-" + "x" * 100, role, "llm", "Summary").to_dict() for role in ROLES[:-1]
    ]
    provider = ContextProvider()
    with Workbench(
        tmp_path,
        Config(limits=Limits(context_bytes=800)),
        grants=Grant(network=True),
        provider=provider,
    ) as wb:
        with pytest.raises(WorkbenchError, match="LIMIT_EXCEEDED"):
            wb._runtime().run("orchestrator", "Review", dependencies=dependencies)
        assert provider.context == {} and wb.store.export()["intents"] == []


@pytest.mark.parametrize(
    "filename,tag,missing",
    [
        ("page.html", '<img data-alt="decorative" src="x">', True),
        ("page.html", '<img alt="" src="x">', False),
        ("page.html", '<IMG ALT="" SRC="x">', False),
        ("Page.tsx", '<img data-alt="decorative" src="x" />', True),
        ("Page.tsx", '<img ALT="" src="x" />', True),
        ("Page.tsx", '<img alt="" src="x" />', False),
        ("page.vue", '<img :alt="description" src="x">', False),
        ("page.vue", '<img v-bind:alt="description" src="x">', False),
        ("page.vue", '<img data-alt="decorative" src="x">', True),
        ("page.vue", '<img :data-alt="description" src="x">', True),
        ("page.vue", '<img v-bind:data-alt="description" src="x">', True),
    ],
)
def test_ux_checks_actual_alt_attribute(
    tmp_path: Path, filename: str, tag: str, missing: bool
) -> None:
    (tmp_path / filename).write_text(tag)
    with Workbench(tmp_path) as wb:
        result = wb.run_agent("ux", "image accessibility")
    assert bool(result["findings"]) is missing


def test_static_roles_trace_named_symbols_through_callers_and_tests(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def total(x):\n    return x - 1\n")
    (tmp_path / "service.py").write_text(
        "from app import total\n\n\ndef charge(x):\n    return total(x)\n"
    )
    (tmp_path / "test_app.py").write_text("from app import total\n\nassert total(2) == 1\n")
    with Workbench(tmp_path) as wb:
        explained = wb.explain("total")
        titles = {finding["title"] for finding in explained["findings"]}
        assert {
            "Definition of total",
            "Call sites naming total",
            "Tests mentioning total",
        } <= titles
        assert explained["evidence"][0]["path"] == "app.py"
        assert explained["recommendations"][0].startswith(
            "Reproduce the behavior with a focused assertion in test_app.py"
        )
        plan = wb.run_agent("engineering", "Fix total so it subtracts nothing")
        assert "Affected files: app.py, service.py, test_app.py." in plan["summary"]
        assert plan["findings"][0]["title"] == "Edit target total"
        assert plan["recommendations"][1].startswith("Add a regression in test_app.py")
        testing = wb.run_agent("testing", "Which tests cover charge")
        assert "Test references found for 0 of 1 traced symbols" in testing["summary"]
        assert testing["findings"][0]["title"] == "Symbols without test references"
        assert "Traced charge" in wb.explain("service.py")["summary"]
