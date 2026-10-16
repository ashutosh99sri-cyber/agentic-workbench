"""Custom overflow exceptions must survive truth checks and hostile item reprs."""

from pathlib import Path

import more_itertools as mi

assert Path(mi.__file__).resolve() == Path.cwd().resolve() / "more_itertools/__init__.py"


class Overflow(Exception):
    def __len__(self):
        return 0


class NoRepresentation:
    def __repr__(self):
        raise RuntimeError("custom errors must not format iterable contents")


for function in (mi.one, mi.only):
    expected = Overflow("too many")
    try:
        function([NoRepresentation(), NoRepresentation()], too_long=expected)
    except Exception as error:
        assert error is expected, "custom overflow exception was not preserved"
    else:
        raise AssertionError("multiple items did not raise")

sentinel = object()
assert mi.only([], default=sentinel) is sentinel
assert mi.only([sentinel]) is sentinel
