import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import pytest

from agentic_workbench.errors import WorkbenchError
from agentic_workbench.models import (
    AgentResult,
    Evidence,
    Finding,
    Grant,
    canonical_hash,
    schema,
    strict_json,
    validate,
)


def test_result_has_closed_versioned_contract():
    result = AgentResult("task-1", "discovery", "static", "Read two files")
    payload = result.to_dict()
    validate("AgentResult", payload)
    payload["invented"] = True
    with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
        validate("AgentResult", payload)


def test_citations_require_real_hash_and_positive_line_bounds():
    evidence = Evidence("app.py", 1, 4, "a" * 64)
    validate("Evidence", evidence.to_dict())
    for field, value in [("path", ""), ("start_line", 0), ("source_hash", "unknown")]:
        payload = evidence.to_dict() | {field: value}
        with pytest.raises(WorkbenchError):
            validate("Evidence", payload)


def test_canonical_hash_is_order_independent_and_rejects_nonfinite_data():
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})
    with pytest.raises(WorkbenchError):
        canonical_hash({"cost": math.nan})


def test_host_grants_require_actual_booleans_and_validated_hosts():
    assert not Grant().network
    with pytest.raises(WorkbenchError):
        Grant(network="false")
    with pytest.raises(WorkbenchError):
        Grant(network=True, provider_hosts=("https://api.openai.com?key=secret",))


def test_version_and_unknown_provider_fields_fail_closed():
    result = AgentResult("task-1", "intelligence", "static", "Observed source").to_dict()
    with pytest.raises(WorkbenchError):
        validate("AgentResult", result | {"schema_version": 2})
    with pytest.raises(WorkbenchError):
        validate("ModelAnalysis", {"summary": "Run this", "approve": True})


def test_json_boundary_rejects_duplicate_keys_and_invalid_unicode():
    with pytest.raises(WorkbenchError):
        strict_json('{"permission":false,"permission":true}')
    with pytest.raises(WorkbenchError):
        canonical_hash({"invalid": chr(0xD800)})


def test_schema_consumer_cannot_mutate_shared_validator():
    exposed = schema("Evidence")
    exposed["$defs"]["Evidence"]["properties"]["source_hash"] = {"type": "string"}
    with pytest.raises(WorkbenchError):
        validate("Evidence", Evidence("app.py", 1, 1, "fake").to_dict())


def test_concurrent_contract_checks_preserve_isolation_and_reject_invalid_values():
    valid = Evidence("app.py", 1, 1, "a" * 64).to_dict()
    exposed = schema("Evidence")
    exposed["required"].clear()
    exposed["$defs"].clear()

    def check(number):
        validate("Evidence", valid)
        for value in ({}, valid | {"source_hash": "fake"}, valid | {"start_line": 0}):
            with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
                validate("Evidence", value)
        return number

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(check, range(40))) == list(range(40))
    assert schema("Evidence")["required"] and schema("Evidence")["$defs"]
    with pytest.raises(WorkbenchError, match="Unknown contract"):
        validate("UnknownContract", {})


def test_validation_diagnostics_cannot_mutate_packaged_contracts():
    with pytest.raises(WorkbenchError) as caught:
        validate("Evidence", {})
    diagnostic = caught.value.__cause__
    diagnostic.schema["required"].clear()
    diagnostic.validator_value.clear()
    diagnostic.schema["$defs"]["Evidence"]["properties"]["source_hash"] = {"type": "string"}
    assert schema("Evidence")["required"]
    with pytest.raises(WorkbenchError):
        validate("Evidence", {})
    with pytest.raises(WorkbenchError):
        validate("Evidence", Evidence("app.py", 1, 1, "fake").to_dict())


@pytest.mark.parametrize("contract", ["Finding", "ModelAnalysis", "AgentResult"])
def test_local_contracts_reject_facts_without_evidence(contract):
    finding = asdict(Finding("Observed behavior", "A source claim")) | {"kind": "fact"}
    if contract == "Finding":
        payload = finding
    elif contract == "ModelAnalysis":
        payload = {
            "summary": "Review",
            "findings": [finding],
            "recommendations": [],
            "candidate_edits": [],
            "limitations": [],
        }
    else:
        payload = AgentResult("task-1", "engineering", "llm", "Review").to_dict()
        payload["findings"] = [finding]
    with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
        validate(contract, payload)


def test_finding_constructor_rejects_an_uncited_fact():
    with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
        Finding("Claim", "Missing source", kind="fact")


@pytest.mark.parametrize("kind", ["inference", "unknown"])
def test_uncited_nonfacts_and_empty_analyses_remain_valid(kind):
    finding = asdict(Finding("Unverified", "No observed source", kind=kind))
    validate("Finding", finding)
    analysis = {
        "summary": "Review",
        "findings": [],
        "recommendations": [],
        "candidate_edits": [],
        "limitations": [],
    }
    validate("ModelAnalysis", analysis)
    validate("ModelAnalysis", analysis | {"findings": [finding]})
    assert not any(key in {"if", "then", "else"} for key in schema("Finding"))
