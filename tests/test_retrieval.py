from dataclasses import FrozenInstanceError, asdict, replace
from unittest.mock import patch

import pytest

from agentic_workbench.errors import WorkbenchError
from agentic_workbench.models import Evidence, canonical_hash, text_hash
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.repository import scan_workspace
from agentic_workbench.retrieval import Chunk, VectorIndex, lexical_search


@pytest.mark.parametrize("query", ["x" * 4097, None, 123], ids=["oversized", "none", "integer"])
def test_repository_search_preserves_bounded_query_validation(tmp_path, query):
    index = scan_workspace(WorkspacePolicy(tmp_path))
    with pytest.raises(WorkbenchError, match="VALIDATION_ERROR"):
        index.search(query)


def test_immutable_chunk_identity_is_reused_without_changing_source_or_serialization():
    chunk = Chunk(Evidence("app.py", 1, 1, "a" * 64), "invoice = 100")
    original = chunk.to_dict()
    with patch("agentic_workbench.retrieval.canonical_hash", wraps=canonical_hash) as hashing:
        identities = [chunk.id for _ in range(10)]
    assert identities == [canonical_hash(original)] * 10
    assert hashing.call_count == 1
    assert chunk.to_dict() == asdict(chunk) == original
    assert replace(chunk, text="invoice = 200").id != chunk.id
    assert replace(chunk, evidence=replace(chunk.evidence, source_hash="b" * 64)).id != chunk.id
    with pytest.raises(FrozenInstanceError):
        chunk.text = "changed"


def test_lexical_and_semantic_are_separate_and_bound() -> None:
    chunks = [
        Chunk(Evidence("a.py", 1, 1, "a" * 64), "invoice total"),
        Chunk(Evidence("b.py", 1, 1, "b" * 64), "user login"),
    ]
    assert lexical_search(chunks, "invoice")[0] == chunks[0]
    vectors = VectorIndex("fixture", "embedding-1", 2)
    vectors.add(chunks[0], [1.0, 0.0], text_hash(chunks[0].text))
    vectors.add(chunks[1], [0.0, 1.0], text_hash(chunks[1].text))
    assert vectors.search([1.0, 0.1], chunks)[0] == chunks[0]
    with pytest.raises(WorkbenchError):
        vectors.add(chunks[0], [float("nan"), 1.0], text_hash(chunks[0].text))
    with pytest.raises(WorkbenchError):
        vectors.add(chunks[0], [1.0], text_hash(chunks[0].text))
    with pytest.raises(WorkbenchError):
        vectors.add(chunks[0], [1.0, 0.0], "c" * 64)
    changed = Chunk(chunks[0].evidence, "new content")
    assert vectors.search([1.0, 0.0], [changed]) == []
    vectors.add(chunks[0], [1e-300, 0.0], text_hash(chunks[0].text))
    assert vectors.search([1e-300, 0.0], chunks)[0] == chunks[0]
