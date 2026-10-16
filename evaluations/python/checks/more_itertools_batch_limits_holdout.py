"""Negative limits are invalid even for an empty source; valid limits still batch."""

from pathlib import Path

import more_itertools as mi

assert Path(mi.__file__).resolve() == Path.cwd().resolve() / "more_itertools/__init__.py"

for items, limit in (([b"x", b"y"], -3), ([], -1), ([], 0)):
    try:
        list(mi.constrained_batches(iter(items), 8, max_count=limit))
    except ValueError:
        pass
    else:
        raise AssertionError(f"nonpositive max_count {limit} was accepted")

assert list(mi.constrained_batches([b"a", b"bb", b"c"], 3, max_count=2)) == [
    (b"a", b"bb"),
    (b"c",),
]
assert list(mi.constrained_batches([b"a", b"b"], 4)) == [(b"a", b"b")]
