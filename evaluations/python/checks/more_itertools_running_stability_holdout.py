"""Both rolling extrema keep stable ties and expire them at the window boundary."""

from functools import total_ordering
from pathlib import Path

import more_itertools as mi

assert Path(mi.__file__).resolve() == Path.cwd().resolve() / "more_itertools/__init__.py"


@total_ordering
class Item:
    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return self.value == other.value

    def __lt__(self, other):
        return self.value < other.value


values = [Item(3), Item(3), Item(3), Item(2)]
for function, expected_indices in ((mi.running_min, [0, 0, 1, 3]), (mi.running_max, [0, 0, 1, 2])):
    actual = list(function(values, maxlen=2))
    assert all(
        item is values[index] for item, index in zip(actual, expected_indices, strict=True)
    ), "equal extrema lost their arrival order or failed to expire"

assert list(mi.running_max([1, 4, 2], maxlen=2)) == [1, 4, 4]
