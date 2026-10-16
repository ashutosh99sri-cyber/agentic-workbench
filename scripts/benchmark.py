"""Measure agent output quality on the disposable example projects.

Each task copies an example into a temporary directory, runs one command, and scores whether
the result cites the expected files and names the expected symbols and test files. Usage and
latency are recorded. Static mode runs offline; a provider with --allow-network measures live
model output under the same tasks so the two modes can be compared.
"""

import argparse
import json
import shutil
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from agentic_workbench import Grant, Workbench

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
TASKS: list[dict[str, Any]] = [
    {
        "id": "py-explain-symbol",
        "example": "python_app",
        "command": "explain",
        "input": "discounted_total",
        "files": ["app.py"],
        "symbols": ["discounted_total"],
        "tests": ["test_app.py"],
    },
    {
        "id": "py-explain-file",
        "example": "python_app",
        "command": "explain",
        "input": "app.py",
        "files": ["app.py"],
        "symbols": ["discounted_total"],
        "tests": ["test_app.py"],
    },
    {
        "id": "py-plan-fix",
        "example": "python_app",
        "command": "plan",
        "input": "Fix discounted_total so 1000 cents with a 10 percent discount returns 900",
        "files": ["app.py"],
        "symbols": ["discounted_total"],
        "tests": ["test_app.py"],
    },
    {
        "id": "py-testing-coverage",
        "example": "python_app",
        "command": "run:testing",
        "input": "Which tests cover discounted_total",
        "files": ["test_app.py"],
        "symbols": ["discounted_total"],
        "tests": ["test_app.py"],
    },
    {
        "id": "ts-explain-symbol",
        "example": "typescript_app",
        "command": "explain",
        "input": "discountedTotal",
        "files": ["src/app.ts"],
        "symbols": [],
        "tests": [],
    },
    {
        "id": "ts-plan-fix",
        "example": "typescript_app",
        "command": "plan",
        "input": "Fix percentage discount in discountedTotal",
        "files": ["src/app.ts"],
        "symbols": [],
        "tests": [],
    },
]


def _collect(result: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str], str]:
    results = result["results"] if "results" in result else [result]
    paths: set[str] = set()
    prose: list[str] = []
    for item in results:
        paths.update(e["path"] for e in item.get("evidence", []))
        prose.append(item.get("summary", ""))
        for finding in item.get("findings", []):
            prose += [finding["title"], finding["details"]]
            paths.update(e["path"] for e in finding.get("evidence", []))
        prose += item.get("recommendations", [])
    return results, paths, "\n".join(prose)


def run(
    tasks: list[dict[str, Any]],
    *,
    network: bool = False,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / task["example"]
            shutil.copytree(EXAMPLES / task["example"], root)
            started = time.perf_counter()
            with Workbench(root, grants=Grant(network=network)) as wb:
                if provider or model:
                    current = wb.policy.config.provider
                    wb.policy.config = replace(
                        wb.policy.config,
                        provider=replace(
                            current, name=provider or current.name, model=model or current.model
                        ),
                    )
                command, _, role = task["command"].partition(":")
                if command == "explain":
                    result = wb.explain(task["input"])
                elif command == "plan":
                    result = wb.plan(task["input"])
                else:
                    result = wb.run_agent(role, task["input"])
            elapsed_ms = int((time.perf_counter() - started) * 1000)
        results, paths, prose = _collect(result)
        usage = [r.get("usage", {}) for r in results]
        token_totals = {}
        for key in ("input_tokens", "output_tokens"):
            values = [u.get(key) for u in usage if u.get("requests", 0) or u.get(key) is not None]
            token_totals[key] = None if None in values else sum(values)
        rows.append(
            {
                "id": task["id"],
                "mode": results[0].get("mode", "unknown"),
                "file_hit": all(path in paths for path in task["files"]),
                "symbol_hit": all(symbol in prose for symbol in task["symbols"]),
                "test_hit": all(test in paths or test in prose for test in task["tests"]),
                "cited_paths": sorted(paths),
                "evidence_count": sum(len(r.get("evidence", [])) for r in results),
                "findings_count": sum(len(r.get("findings", [])) for r in results),
                "summary_chars": sum(len(r.get("summary", "")) for r in results),
                "requests": sum(u.get("requests", 0) for u in usage),
                **token_totals,
                "elapsed_ms": elapsed_ms,
            }
        )
    keys = ("file_hit", "symbol_hit", "test_hit")
    return {
        "schema_version": 1,
        "tasks": rows,
        "score": {key: round(sum(1 for r in rows if r[key]) / len(rows), 3) for key in keys},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--task", action="append", help="Run only the named task IDs")
    args = parser.parse_args()
    tasks = [t for t in TASKS if not args.task or t["id"] in args.task]
    report = run(tasks, network=args.allow_network, provider=args.provider, model=args.model)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
