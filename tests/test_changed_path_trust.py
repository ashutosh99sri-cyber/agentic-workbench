"""Changed-body promotion accepts genuine indexed source, never supplied inventions."""

from agentic_workbench.impact import select_impact_chunks
from agentic_workbench.models import Evidence, text_hash
from agentic_workbench.policy import SourceFile
from agentic_workbench.repository import RepositoryIndex, index_source, merge_source
from agentic_workbench.retrieval import Chunk

QUERY = "Assess compatibility with consumers and checks."


def source_index(lines: int = 130) -> RepositoryIndex:
    text = (
        "def evaluate_batch(entries):\n"
        + "    # ordinary detail\n" * (lines - 2)
        + "    return len(entries)\n"
    )
    source = SourceFile("rules.py", text, text_hash(text), len(text.encode()), False)
    index = RepositoryIndex(files={source.path: source}, coverage={"parse_errors": 0})
    merge_source(index, index_source(source))
    return index


def assert_exact_source(index: RepositoryIndex, selected: list[Chunk]) -> None:
    indexed_spans = {
        (
            chunk.evidence.path,
            chunk.evidence.start_line,
            chunk.evidence.end_line,
            chunk.evidence.source_hash,
        ): chunk.id
        for chunk in index.chunks
    }
    assert len(selected) == len({chunk.id for chunk in selected})
    for chunk in selected:
        evidence = chunk.evidence
        source = index.files[evidence.path]
        lines = source.text.splitlines()
        assert evidence.source_hash == source.source_hash
        assert 1 <= evidence.start_line <= evidence.end_line <= len(lines)
        assert chunk.text == "\n".join(lines[evidence.start_line - 1 : evidence.end_line])
        identity = indexed_spans.get(
            (evidence.path, evidence.start_line, evidence.end_line, evidence.source_hash)
        )
        if identity is not None:
            assert chunk.id == identity


def test_changed_body_never_promotes_forged_text_with_genuine_evidence() -> None:
    index = source_index()
    before = [chunk.to_dict() for chunk in index.chunks]
    original_source = index.files["rules.py"]
    forged = Chunk(index.chunks[0].evidence, "UNSUPPORTED SOURCE TEXT ABSENT FROM THE SNAPSHOT")
    assert forged.id not in {chunk.id for chunk in index.chunks}
    supplied = [forged, *index.chunks[1:]]

    selected = select_impact_chunks(index, QUERY, supplied, changed_paths=["rules.py"])

    assert selected
    assert all(chunk.id != forged.id for chunk in selected)
    assert_exact_source(index, selected)
    assert index.files["rules.py"] == original_source
    assert [chunk.to_dict() for chunk in index.chunks] == before


def test_duplicate_supplied_chunks_do_not_inflate_affordable_body_bundle() -> None:
    index = source_index()
    supplied = [chunk for chunk in index.chunks for _ in range(3)]
    selected = select_impact_chunks(index, QUERY, supplied, changed_paths=["rules.py"])

    assert_exact_source(index, selected)
    covered = {
        line
        for chunk in selected[:6]
        for line in range(chunk.evidence.start_line, chunk.evidence.end_line + 1)
    }
    assert covered == set(range(1, 131))


def test_oversized_changed_body_retains_compact_fallback() -> None:
    index = source_index(410)
    assert len(index.chunks) > 6
    selected = select_impact_chunks(index, QUERY, index.chunks, changed_paths=["rules.py"])

    assert_exact_source(index, selected)
    covered = {
        line
        for chunk in selected[:6]
        for line in range(chunk.evidence.start_line, chunk.evidence.end_line + 1)
    }
    assert covered < set(range(1, 411))


def test_empty_changed_paths_preserve_query_only_ranking() -> None:
    index = source_index()
    query = "Explain evaluate_batch in rules.py"
    expected = select_impact_chunks(index, query, index.chunks)
    actual = select_impact_chunks(index, query, index.chunks, changed_paths=[])

    assert [chunk.to_dict() for chunk in actual] == [chunk.to_dict() for chunk in expected]


def test_stale_supplied_middle_chunk_cannot_complete_changed_body_coverage() -> None:
    index = source_index()
    middle = index.chunks[1]
    stale = Chunk(
        Evidence(
            middle.evidence.path,
            middle.evidence.start_line,
            middle.evidence.end_line,
            "0" * 64,
        ),
        "STALE SOURCE CONTENT",
    )
    supplied = [index.chunks[0], stale, index.chunks[2]]

    selected = select_impact_chunks(index, QUERY, supplied, changed_paths=["rules.py"])

    assert selected
    assert_exact_source(index, selected)
    assert all(chunk.id != stale.id for chunk in selected)
    assert not any(
        chunk.evidence.start_line <= middle.evidence.end_line
        and middle.evidence.start_line <= chunk.evidence.end_line
        for chunk in selected
    )
