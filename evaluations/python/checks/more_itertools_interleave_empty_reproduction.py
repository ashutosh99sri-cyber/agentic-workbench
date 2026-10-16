"""Interleaving no iterables has an empty result rather than an indexing error."""

from pathlib import Path

import more_itertools as mi

assert Path(mi.__file__).resolve() == Path.cwd().resolve() / "more_itertools/__init__.py"

assert list(mi.interleave_evenly([])) == []
assert list(mi.interleave_evenly([["a", "b"]])) == ["a", "b"]
