"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.requirements import InvalidRequirement, Requirement

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
try:
    Requirement("vectorlib===")
except InvalidRequirement:
    pass
else:
    raise AssertionError("An arbitrary requirement version must not be empty")
assert str(Requirement("vectorlib===custom-build")) == "vectorlib===custom-build"
