from pathlib import Path
from typing import Any

import pytest

from agentic_workbench.errors import WorkbenchError
from agentic_workbench.impact import impact, select_impact_chunks
from agentic_workbench.models import Evidence
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.repository import RepositoryIndex, scan_workspace


def billing(tmp_path: Path) -> tuple[WorkspacePolicy, RepositoryIndex]:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "billing.py").write_text(
        "def total(items):\n    return sum(items)\n\n\ndef tax(amount):\n    return amount // 10\n"
    )
    (tmp_path / "app.py").write_text(
        "from pkg.billing import total\n\n\ndef checkout(cart):\n    return total(cart)\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_billing.py").write_text(
        "from pkg.billing import total\n\n\ndef test_total():\n    assert total([1, 2]) == 3\n"
    )
    (tmp_path / "other.py").write_text("def unrelated():\n    return 0\n")
    policy = WorkspacePolicy(tmp_path)
    return policy, scan_workspace(policy)


def test_impact_cites_changed_definitions_their_callers_and_tests(tmp_path: Path) -> None:
    policy, index = billing(tmp_path)
    result = impact(index, ["pkg/billing.py"])
    assert result["fingerprint"] == index.fingerprint
    assert result["changed_paths"] == ["pkg/billing.py"]
    assert [d["name"] for d in result["definitions"]] == ["total", "tax"]
    assert [(c["callee"], c["evidence"]["path"]) for c in result["callers"]] == [
        ("total", "app.py"),
        ("total", "tests/test_billing.py"),
    ]
    assert [(t["evidence"]["start_line"], t["link"]) for t in result["tests"]] == [
        (1, "textual"),
        (5, "textual"),
    ]
    assert result["affected_paths"] == ["app.py", "tests/test_billing.py"]
    assert not result["truncated"] and result["limitations"]
    facts = [
        fact
        for key in ("definitions", "callers", "imports", "references", "tests")
        for fact in result[key]
    ]
    assert all(index.current(policy, Evidence(**fact["evidence"])) for fact in facts)


@pytest.mark.parametrize(
    ("paths", "limit"),
    [
        ([], 20),
        ("app.py", 20),
        (["missing.py"], 20),
        (["app.py", "app.py"], 20),
        (["../app.py"], 20),
        (["app.py"], 0),
        (["app.py"], 51),
        (["app.py"], True),
    ],
)
def test_impact_requires_distinct_indexed_paths_and_a_bounded_limit(
    tmp_path: Path, paths: Any, limit: Any
) -> None:
    _, index = billing(tmp_path)
    with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
        impact(index, paths, limit=limit)


def test_impact_accepts_at_most_twenty_paths(tmp_path: Path) -> None:
    for n in range(21):
        (tmp_path / f"m{n:02}.py").write_text(f"VALUE_{n} = {n}\n")
    index = scan_workspace(WorkspacePolicy(tmp_path))
    paths = sorted(index.files)
    assert impact(index, paths[:20])["changed_paths"] == paths[:20]
    with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
        impact(index, paths)


def test_impact_is_bounded_and_reports_truncation(tmp_path: Path) -> None:
    (tmp_path / "lib.py").write_text("def total():\n    return 1\n")
    (tmp_path / "app.py").write_text("from lib import total\n" + "total()\n" * 60)
    index = scan_workspace(WorkspacePolicy(tmp_path))
    result = impact(index, ["lib.py"], limit=5)
    assert len(result["callers"]) == 5 and result["truncated"]
    assert impact(index, ["lib.py"], limit=50)["truncated"]


def test_declaration_ids_decide_links_and_names_only_match_legacy_python_calls(
    tmp_path: Path,
) -> None:
    (tmp_path / "billing.py").write_text("def total():\n    return 1\n")
    (tmp_path / "shipping.py").write_text("def total():\n    return 2\n")
    (tmp_path / "app.py").write_text("total()\n")
    (tmp_path / "web.py").write_text("total()\n")
    (tmp_path / "legacy.py").write_text("total()\n")
    (tmp_path / "test_app.py").write_text("total()\n")
    (tmp_path / "ui.ts").write_text("import { total as sum } from './billing';\ntotal();\n")
    index = scan_workspace(WorkspacePolicy(tmp_path))
    # Structural enrichment (as the TypeScript analyzer provides) links uses to declarations.
    for symbol in index.symbols:
        symbol["id"] = symbol["evidence"]["path"] + ":total"
    resolved = {"app.py": "billing.py:total", "web.py": "shipping.py:total"}
    resolved["test_app.py"] = "billing.py:total"
    for call in index.calls:
        if call["evidence"]["path"] in resolved:
            call["target_id"] = resolved[call["evidence"]["path"]]

    def cite(path: str) -> dict[str, Any]:
        return Evidence(path, 1, 1, index.files[path].source_hash).to_dict()

    ui = index.files["ui.ts"].source_hash
    index.calls.append(
        {
            "callee": "total",
            "resolution": "unresolved",
            "evidence": Evidence("ui.ts", 2, 2, ui).to_dict(),
        }
    )
    index.imports += [
        {
            "module": "./billing",
            "imported": "total",
            "local": "sum",
            "target_id": "billing.py:total",
            "resolution": "static-symbol",
            "evidence": cite("ui.ts"),
        },
        {
            "module": "./shipping",
            "imported": "total",
            "local": "total",
            "target_id": "shipping.py:total",
            "resolution": "static-symbol",
            "evidence": cite("web.py"),
        },
    ]
    index.references.append(
        {
            "name": "total",
            "target_id": "billing.py:total",
            "resolution": "static-symbol",
            "evidence": cite("test_app.py"),
        }
    )
    result = impact(index, ["billing.py"])
    # Resolved calls follow their IDs; the unlinked legacy Python call matches by name;
    # the unresolved TypeScript call gets no name fallback.
    assert [c["evidence"]["path"] for c in result["callers"]] == [
        "app.py",
        "legacy.py",
        "test_app.py",
    ]
    assert [(i["evidence"]["path"], i["local"]) for i in result["imports"]] == [("ui.ts", "sum")]
    assert [r["evidence"]["path"] for r in result["references"]] == ["test_app.py"]
    assert [t["link"] for t in result["tests"]] == ["declaration"]
    assert result["affected_paths"] == ["app.py", "legacy.py", "test_app.py", "ui.ts"]


def test_selector_ranks_definitions_users_and_checks_before_lexical_fallback(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text("# filler\n" * 120 + "def checkout(cart):\n    return cart\n")
    (tmp_path / "web.py").write_text(
        "# filler\n" * 70 + "from app import checkout\nresult = checkout([])\n"
    )
    (tmp_path / "test_app.py").write_text(
        "from app import checkout\n\n\ndef test_checkout():\n    assert checkout([]) == []\n"
    )
    (tmp_path / "notes.py").write_text("# checkout notes: the checkout flow\n")
    policy = WorkspacePolicy(tmp_path)
    index = scan_workspace(policy)
    fresh = index.current_chunks(policy)
    ranked = [
        (c.evidence.path, c.evidence.start_line)
        for c in select_impact_chunks(index, "Fix checkout in app.py", fresh)
    ]
    # Compact definitions, non-test callers and checks get distinct early capacity.
    assert [path for path, _ in ranked[:3]] == ["app.py", "web.py", "test_app.py"]
    assert all(path != "notes.py" for path, _ in ranked[:3])
    assert ("app.py", 1) not in ranked and ("web.py", 1) not in ranked
    assert len(ranked) == len(set(ranked))
    # A changed file's definitions lead even when the instruction names none of them.
    changed = select_impact_chunks(index, "Fix the order flow", fresh, ["app.py"])
    assert [c.evidence.path for c in changed[:3]] == ["app.py", "web.py", "test_app.py"]
    # A named symbol can guide context without a file path, ahead of repetitive notes.
    named = select_impact_chunks(index, "checkout notes", fresh)
    assert {c.evidence.path for c in named[:3]} == {"app.py", "web.py", "test_app.py"}


def test_dollar_identifiers_are_whole_words_in_test_references(tmp_path: Path) -> None:
    (tmp_path / "money.js").write_text("export function $total(x) {\n  return x;\n}\n")
    (tmp_path / "money.test.js").write_text(
        "expect($total(1)).toBe(1);\nexpect($totals).toBe(0);\nconst total = 2;\n"
    )
    index = scan_workspace(WorkspacePolicy(tmp_path))
    source = index.files["money.js"]
    index.symbols.append(
        {
            "name": "$total",
            "kind": "function",
            "evidence": Evidence("money.js", 1, 3, source.source_hash).to_dict(),
        }
    )
    tests = impact(index, ["money.js"])["tests"]
    assert [(t["name"], t["evidence"]["start_line"]) for t in tests] == [("$total", 1)]


def test_declaration_linked_alias_references_are_listed_as_tests(tmp_path: Path) -> None:
    (tmp_path / "billing.ts").write_text("export function total() {\n  return 1;\n}\n")
    (tmp_path / "cart.test.ts").write_text(
        "import { total as sum } from './billing';\n\nexpect(sum()).toBe(1);\n"
    )
    index = scan_workspace(WorkspacePolicy(tmp_path))
    billing, cart = index.files["billing.ts"], index.files["cart.test.ts"]
    index.symbols.append(
        {
            "id": "billing.ts#total",
            "name": "total",
            "kind": "function",
            "evidence": Evidence("billing.ts", 1, 3, billing.source_hash).to_dict(),
        }
    )
    index.references.append(
        {
            "name": "sum",
            "target_id": "billing.ts#total",
            "resolution": "static-symbol",
            "evidence": Evidence("cart.test.ts", 3, 3, cart.source_hash).to_dict(),
        }
    )
    tests = impact(index, ["billing.ts"])["tests"]
    # The alias line never names `total`, yet its declaration link makes it a check.
    assert [(t["name"], t["link"], t["evidence"]["start_line"]) for t in tests] == [
        ("total", "textual", 1),
        ("sum", "declaration", 3),
    ]
