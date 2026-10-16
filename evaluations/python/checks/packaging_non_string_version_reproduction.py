"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.version import InvalidVersion, Version

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
try:
    Version(None)
except InvalidVersion:
    pass
else:
    raise AssertionError("InvalidVersion must be consistent for non-string input")
assert str(Version("2.1")) == "2.1"
