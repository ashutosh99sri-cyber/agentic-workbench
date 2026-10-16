"""A rolling minimum preserves the first occurrence when values compare equal."""

from pathlib import Path

import more_itertools as mi

assert Path(mi.__file__).resolve() == Path.cwd().resolve() / "more_itertools/__init__.py"

first, equal = 7, 7.0
actual = list(mi.running_min([first, equal], maxlen=2))
assert actual[1] is first, "running_min replaced the earlier equal minimum"
assert list(mi.running_min([5, 2, 4], maxlen=2)) == [5, 2, 2]
