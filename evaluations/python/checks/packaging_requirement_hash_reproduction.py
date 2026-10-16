"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.requirements import Requirement

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
left = Requirement("vectorlib==2.0")
right = Requirement("vectorlib==2.0.0")
assert left == right
assert hash(left) == hash(right), "Equal requirements must share a hash"
assert len({left, right}) == 1
