from itertools import combinations

import pytest

from agentic_workbench.errors import WorkbenchError
from agentic_workbench.models import Evidence
from agentic_workbench.retrieval import Chunk, combine_rankings


def chunk(path: str, text: str = "source", start_line: int = 1) -> Chunk:
    return Chunk(Evidence(path, start_line, start_line, "a" * 64), text)


def test_overlap_ranks_a_shared_candidate_ahead_of_each_source_leader() -> None:
    lexical, vector, shared = chunk("a.py"), chunk("z.py"), chunk("shared.py")

    assert combine_rankings([lexical, shared], [vector, shared]) == [shared, lexical, vector]


def test_equal_scores_have_stable_path_line_and_identity_ties() -> None:
    candidates = [chunk("b.py"), chunk("a.py", start_line=2), chunk("a.py", "one")]
    candidates.append(chunk("a.py", "two"))
    for first, second in combinations(candidates, 2):
        expected = sorted(
            [first, second],
            key=lambda item: (item.evidence.path, item.evidence.start_line, item.id),
        )
        assert combine_rankings([first], [second]) == expected
        assert combine_rankings([second], [first]) == expected
        assert combine_rankings([first, second], [second, first]) == expected


def test_duplicate_identities_count_once_per_source_and_keep_the_first_chunk() -> None:
    first, shared = chunk("a.py"), chunk("b.py")
    duplicate = Chunk(first.evidence, first.text)

    result = combine_rankings([first, duplicate, shared], [shared])

    assert result == [shared, first]
    assert result[1] is first
    assert combine_rankings([first, duplicate, shared], []) == combine_rankings([first, shared], [])


def test_empty_sources_limits_and_inputs_are_preserved() -> None:
    candidates = [chunk(f"{number:02}.py") for number in range(60)]
    lexical, vector = candidates[:], list(reversed(candidates))
    original = (lexical[:], vector[:])

    assert combine_rankings([], []) == []
    assert combine_rankings(lexical, [], 1) == [candidates[0]]
    assert len(combine_rankings([], vector, 50)) == 50
    assert len(combine_rankings(lexical, vector, 3)) == 3
    assert (lexical, vector) == original


@pytest.mark.parametrize("limit", [True, False, 0, -1, 51, 1.0, "5", None])
def test_invalid_limits_fail_like_existing_retrieval_apis(limit: object) -> None:
    with pytest.raises(WorkbenchError, match="Invalid retrieval limit") as error:
        combine_rankings([], [], limit)  # type: ignore[arg-type]
    assert error.value.code == "VALIDATION_ERROR"
