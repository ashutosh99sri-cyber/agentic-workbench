import importlib.util
from pathlib import Path

import pytest

from agentic_workbench.models import Usage
from agentic_workbench.providers import ProviderResult

spec = importlib.util.spec_from_file_location(
    "benchmark", Path(__file__).resolve().parents[1] / "scripts/benchmark.py"
)
assert spec is not None and spec.loader is not None
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_static_baseline_cites_expected_files_symbols_and_tests() -> None:
    report = benchmark.run(benchmark.TASKS)
    rows = {row["id"]: row for row in report["tasks"]}
    assert all(row["mode"] == "static" for row in rows.values())
    for task_id in ("py-explain-symbol", "py-explain-file", "py-plan-fix", "py-testing-coverage"):
        row = rows[task_id]
        assert row["file_hit"] and row["symbol_hit"] and row["test_hit"], row
    assert rows["ts-explain-symbol"]["file_hit"] and rows["ts-plan-fix"]["file_hit"]
    assert report["score"]["file_hit"] == 1.0
    assert all(row["requests"] == 0 for row in rows.values())
    assert all(row["input_tokens"] == row["output_tokens"] == 0 for row in rows.values())


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        (Usage(requests=1, input_tokens=10, output_tokens=4), (10, 4)),
        (Usage(requests=1, input_tokens=None, output_tokens=4), (None, 4)),
        (Usage(requests=1, input_tokens=10, output_tokens=None), (10, None)),
        (Usage(requests=1, input_tokens=0, output_tokens=0), (0, 0)),
        (Usage(requests=0, input_tokens=10, output_tokens=4), (10, 4)),
    ],
)
def test_benchmark_preserves_missing_provider_usage(monkeypatch, usage, expected):
    class FixtureProvider:
        def analyze(self, request, context, **kwargs):
            return ProviderResult(
                {
                    "summary": "Fixture analysis",
                    "findings": [],
                    "recommendations": [],
                    "candidate_edits": [],
                    "limitations": ["Offline transport fixture"],
                },
                usage,
            )

    original = benchmark.Workbench
    monkeypatch.setattr(
        benchmark,
        "Workbench",
        lambda root, grants: original(root, grants=grants, provider=FixtureProvider()),
    )
    row = benchmark.run(benchmark.TASKS[:1], network=True)["tasks"][0]
    assert (row["input_tokens"], row["output_tokens"]) == expected


def test_benchmark_does_not_report_partial_workflow_usage_as_complete(monkeypatch):
    class FixtureProvider:
        def analyze(self, request, context, **kwargs):
            return ProviderResult(
                {
                    "summary": "Fixture analysis",
                    "findings": [],
                    "recommendations": [],
                    "candidate_edits": [],
                    "limitations": [],
                },
                Usage(
                    requests=1,
                    input_tokens=None if context["role"] == "engineering" else 10,
                    output_tokens=4,
                ),
            )

    original = benchmark.Workbench
    monkeypatch.setattr(
        benchmark,
        "Workbench",
        lambda root, grants: original(root, grants=grants, provider=FixtureProvider()),
    )
    row = benchmark.run([benchmark.TASKS[2]], network=True)["tasks"][0]
    assert row["requests"] == 6
    assert row["input_tokens"] is None
    assert row["output_tokens"] == 24
