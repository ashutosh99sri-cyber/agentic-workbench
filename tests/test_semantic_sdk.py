from pathlib import Path
from typing import Any

import pytest

from agentic_workbench import Config, Grant, Workbench, WorkbenchError
from agentic_workbench.config import ProviderConfig
from agentic_workbench.models import Usage
from agentic_workbench.providers import (
    BudgetLedger,
    EmbeddingResult,
    IntentSink,
    ProviderResult,
    ToolExecutor,
)


class FixtureProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.sizes: list[int] = []

    def analyze(
        self,
        request: str,
        context: dict[str, Any],
        *,
        executor: ToolExecutor,
        budget: BudgetLedger,
        intents: IntentSink,
    ) -> ProviderResult:
        self.calls += 1
        return ProviderResult(
            {
                "summary": "Fixture analysis",
                "findings": [],
                "recommendations": [],
                "candidate_edits": [],
                "limitations": ["Test fixture"],
            },
            Usage(),
        )

    def embed(
        self,
        texts: list[str],
        *,
        chunk_hashes: list[str],
        dimensions: int,
        source_grant: bool,
        budget: BudgetLedger,
        intents: IntentSink,
    ) -> EmbeddingResult:
        self.calls += 1
        assert dimensions >= 2 and source_grant
        self.sizes.append(len(texts))
        budget.reserve(8)
        identifier = intents.intent(
            "fixture.embeddings",
            {
                "model": "fixture-model",
                "payload_hash": "a" * 64,
                "bytes": sum(len(t) for t in texts),
            },
        )
        intents.receipt(
            identifier,
            {
                "status": "received",
                "request_id": "fixture-request",
                "response_id": "fixture-response",
                "provider_model": "fixture-model",
                "input_tokens": 10,
                "output_tokens": 0,
            },
        )
        vectors = tuple(
            tuple(([1.0, 0.0] if "invoice" in text else [0.0, 1.0]) + [0.0] * (dimensions - 2))
            for text in texts
        )
        return EmbeddingResult(
            "fixture", "fixture-model", tuple(chunk_hashes), vectors, Usage(requests=1)
        )


def test_semantic_cache_and_durable_provenance(tmp_path: Path) -> None:
    (tmp_path / "invoice.py").write_text("def invoice():\n    return 100\n")
    (tmp_path / "users.py").write_text("def login():\n    return True\n")
    provider = FixtureProvider()
    config = Config(provider=ProviderConfig(name="fixture", embedding_model="fixture-model"))
    with Workbench(tmp_path, config, grants=Grant(network=True), provider=provider) as wb:
        with pytest.raises(WorkbenchError):
            wb.search("invoice", semantic=True, dimensions=2, limit=0)
        assert provider.calls == 0
        first = wb.search("invoice", semantic=True, dimensions=2)
        assert first["chunks"][0]["evidence"]["path"] == "invoice.py"
        assert provider.calls == 2
        second = wb.search("login", semantic=True, dimensions=2)
        assert second["chunks"][0]["evidence"]["path"] == "users.py"
        assert provider.calls == 3
        intent = wb.store.export()["intents"][0]
        assert (
            intent["kind"] == "fixture.embeddings"
            and intent["metadata"]["payload_hash"] == "a" * 64
        )
        assert intent["usage"]["response_id"] == "fixture-response"
        (tmp_path / "users.py").write_text("def login():\n    return False\n")
        refreshed = wb.search("login", semantic=True, dimensions=2)
        assert provider.calls == 5
        assert provider.sizes[-2:] == [1, 1]
        assert refreshed["coverage"]["cached_chunks"] == 1
        assert refreshed["coverage"]["new_vectors"] == 1
    with Workbench(tmp_path, config, grants=Grant(network=True), provider=provider) as wb:
        restarted = wb.search("login", semantic=True, dimensions=2)
        assert provider.calls == 6
        assert restarted["coverage"]["cached_chunks"] == 2
        assert restarted["coverage"]["new_vectors"] == 0


def test_injected_provider_cannot_expand_caller_grant(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("value=1\n")
    provider = FixtureProvider()
    with Workbench(tmp_path, provider=provider) as wb:
        with pytest.raises(WorkbenchError):
            wb.explain("app.py")
        with pytest.raises(WorkbenchError):
            wb.search("value", semantic=True, dimensions=2)
        assert provider.calls == 0


def test_semantic_candidates_prefer_query_relevance_over_early_files(tmp_path: Path) -> None:
    for letter in "abcd":
        (tmp_path / f"{letter}.py").write_text(("# background " + "word " * 20 + "\n") * 25)
    (tmp_path / "z_invoice.py").write_text(("# invoice " + "word " * 20 + "\n") * 25)
    provider = FixtureProvider()
    config = Config(provider=ProviderConfig(name="fixture", embedding_model="fixture-model"))
    with Workbench(tmp_path, config, grants=Grant(network=True), provider=provider) as wb:
        result = wb.search("invoice", semantic=True, dimensions=2)
        assert result["mode"] == "semantic"
        assert result["chunks"][0]["evidence"]["path"] == "z_invoice.py"
        assert result["indexed_chunks"] < result["total_chunks"]


def test_injected_embedding_adapter_uses_its_host_destination_grant(tmp_path: Path) -> None:
    (tmp_path / "invoice.py").write_text("invoice = 1\n")
    config = Config(provider=ProviderConfig(name="fixture", embedding_model="fixture-model"))
    with Workbench(
        tmp_path,
        config,
        grants=Grant(network=True, provider_hosts=("embedding.example",)),
        provider=FixtureProvider(),
    ) as wb:
        assert wb.search("invoice", semantic=True, dimensions=2)["chunks"]


def test_secret_search_query_is_denied_before_injected_dispatch(tmp_path: Path) -> None:
    (tmp_path / "invoice.py").write_text("invoice = 1\n")
    provider = FixtureProvider()
    with Workbench(tmp_path, grants=Grant(network=True), provider=provider) as wb:
        with pytest.raises(WorkbenchError, match="POLICY_DENIED"):
            wb.search("password='do-not-send'", semantic=True, dimensions=2)
        assert provider.calls == 0


def test_vector_response_budget_batches_before_dispatch(tmp_path: Path) -> None:
    for number in range(4):
        (tmp_path / f"invoice_{number}.py").write_text(f"invoice = {number}\n")
    provider = FixtureProvider()
    config = Config(provider=ProviderConfig(name="fixture", embedding_model="fixture-model"))
    with Workbench(tmp_path, config, grants=Grant(network=True), provider=provider) as wb:
        result = wb.search("invoice", semantic=True, dimensions=256)
        assert result["indexed_chunks"] == 4 and provider.sizes == [1, 1, 1, 1, 1]


def test_zero_vector_rejected_before_cache_save(tmp_path: Path) -> None:
    (tmp_path / "invoice.py").write_text("invoice=1\n")
    provider = FixtureProvider()
    original = provider.embed

    def invalid(*args: Any, **kwargs: Any) -> EmbeddingResult:
        response = original(*args, **kwargs)
        return EmbeddingResult(
            response.provider,
            response.model,
            response.chunk_hashes,
            tuple((0.0, 0.0) for _ in response.vectors),
            response.usage,
        )

    provider.embed = invalid  # type: ignore[method-assign]
    config = Config(provider=ProviderConfig(name="fixture", embedding_model="fixture-model"))
    with Workbench(tmp_path, config, grants=Grant(network=True), provider=provider) as wb:
        with pytest.raises(WorkbenchError):
            wb.search("invoice", semantic=True, dimensions=2)
        assert wb.store.list_records("vectors") == []


@pytest.mark.parametrize("mode", ["semantic", "combined"])
def test_explicit_retrieval_modes_reuse_validated_embeddings(tmp_path: Path, mode: str) -> None:
    (tmp_path / "invoice.py").write_text("def invoice():\n    return 100\n")
    provider = FixtureProvider()
    config = Config(provider=ProviderConfig(name="fixture", embedding_model="fixture-model"))
    with Workbench(tmp_path, config, grants=Grant(network=True), provider=provider) as wb:
        result = wb.search("invoice", mode=mode, dimensions=2)
        assert result["mode"] == mode
        assert result["chunks"][0]["evidence"]["path"] == "invoice.py"
        assert result["usage"]["requests"] == 2
        assert wb.search("invoice", mode=mode, dimensions=2)["coverage"]["cached_chunks"] == 1


def test_conflicting_retrieval_modes_fail_before_provider(tmp_path: Path) -> None:
    provider = FixtureProvider()
    with Workbench(tmp_path, provider=provider) as wb:
        for mode in ("lexical", "combined", "unknown", []):
            with pytest.raises(WorkbenchError, match="retrieval mode"):
                wb.search("invoice", semantic=True, mode=mode)
        assert provider.calls == 0
