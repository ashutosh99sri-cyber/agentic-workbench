"""Peeking at a seekable iterator with no history cache must not consume it."""

from pathlib import Path

import more_itertools as mi

assert Path(mi.__file__).resolve() == Path.cwd().resolve() / "more_itertools/__init__.py"

stream = mi.seekable(iter(["first", "last"]), maxlen=0)
assert stream.peek() == "first"
assert next(stream) == "first", "peek consumed an item with maxlen=0"
assert list(stream) == ["last"]
