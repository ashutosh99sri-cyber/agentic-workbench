"""A callable's false truth value must not disable bucket validation."""

from pathlib import Path

import more_itertools as mi

assert Path(mi.__file__).resolve() == Path.cwd().resolve() / "more_itertools/__init__.py"


class EvenKeys:
    def __bool__(self):
        return False

    def __call__(self, key):
        return key % 2 == 0


groups = mi.bucket([1, 2, 3, 4], key=lambda value: value, validator=EvenKeys())
assert list(groups[1]) == [], "falsey validator was replaced by permissive default"
assert list(groups[2]) == [2]
assert list(mi.bucket([1, 1], key=lambda value: value)[1]) == [1, 1]
