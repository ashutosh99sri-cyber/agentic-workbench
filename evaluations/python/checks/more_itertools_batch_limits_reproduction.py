"""A zero item-count limit cannot form a meaningful constrained batch."""

from pathlib import Path

import more_itertools as mi

assert Path(mi.__file__).resolve() == Path.cwd().resolve() / "more_itertools/__init__.py"

try:
    list(mi.constrained_batches([b"abc"], 10, max_count=0))
except ValueError:
    pass
else:
    raise AssertionError("zero max_count was accepted")

assert list(mi.constrained_batches([b"a", b"b"], 10, max_count=1)) == [(b"a",), (b"b",)]
