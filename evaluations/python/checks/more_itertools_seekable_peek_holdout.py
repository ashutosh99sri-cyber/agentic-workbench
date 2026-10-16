"""Truth testing, repeated peeks, and exhausted defaults preserve stream contents."""

from pathlib import Path

import more_itertools as mi

assert Path(mi.__file__).resolve() == Path.cwd().resolve() / "more_itertools/__init__.py"

stream = mi.seekable((value for value in [None, 0, "end"]), maxlen=0)
assert bool(stream)
assert bool(stream)
assert stream.peek() is None
assert stream.peek() is None
assert list(stream) == [None, 0, "end"], "inspection dropped stream values"
assert not stream
sentinel = object()
assert stream.peek(sentinel) is sentinel
assert list(mi.seekable([2, 4], maxlen=0)) == [2, 4]
