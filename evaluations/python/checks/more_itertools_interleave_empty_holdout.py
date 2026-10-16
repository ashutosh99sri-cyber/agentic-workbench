"""Explicit empty lengths and ordinary weighted interleaving are consistent."""

from collections import Counter
from pathlib import Path

import more_itertools as mi

assert Path(mi.__file__).resolve() == Path.cwd().resolve() / "more_itertools/__init__.py"

assert list(mi.interleave_evenly((), lengths=())) == []
assert list(mi.interleave_evenly([[], []], lengths=[0, 0])) == []
actual = list(mi.interleave_evenly([[1, 2, 3], [9]], lengths=[3, 1]))
assert Counter(actual) == Counter([1, 2, 3, 9])
assert [value for value in actual if value != 9] == [1, 2, 3]
