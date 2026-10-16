"""Validation must also govern iteration and membership for falsey callables."""

from pathlib import Path

import more_itertools as mi

assert Path(mi.__file__).resolve() == Path.cwd().resolve() / "more_itertools/__init__.py"


class Filter:
    def __len__(self):
        return 0

    def __call__(self, key):
        return key.startswith("allowed")


groups = mi.bucket(
    ["blocked", "allowed-a", "blocked-again", "allowed-b"],
    key=lambda value: value,
    validator=Filter(),
)
assert "blocked" not in groups, "membership ignored the supplied validator"
assert set(groups) == {"allowed-a", "allowed-b"}
assert list(groups["allowed-b"]) == ["allowed-b"]
assert list(groups["missing"]) == []
