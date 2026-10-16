"""one must raise an explicitly supplied falsey exception on empty input."""

from pathlib import Path

import more_itertools as mi

assert Path(mi.__file__).resolve() == Path.cwd().resolve() / "more_itertools/__init__.py"


class EmptyInputError(Exception):
    def __bool__(self):
        return False


expected = EmptyInputError("preserve this exception")
try:
    mi.one([], too_short=expected)
except Exception as error:
    assert error is expected, "one discarded the supplied falsey exception"
else:
    raise AssertionError("empty input did not raise")

item = object()
assert mi.one([item]) is item
