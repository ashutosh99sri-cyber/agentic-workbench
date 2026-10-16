"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.requirements import Requirement

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
left = Requirement('Vector_Lib[fast,io]==3.0; os_name == "posix"')
right = Requirement('vector-lib[io,fast]==3.0.0.0; os_name == "posix"')
assert left == right
assert hash(left) == hash(right)
assert {left: "found"}[right] == "found"
assert left != Requirement('vector-lib[fast]==3.0; os_name == "posix"')
