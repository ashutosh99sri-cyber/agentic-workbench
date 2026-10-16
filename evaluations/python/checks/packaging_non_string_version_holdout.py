"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.version import InvalidVersion, Version

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
for value in (42, b"2.1", ["2", ".", "1"], {"2": "value"}):
    try:
        Version(value)
    except InvalidVersion:
        pass
    else:
        raise AssertionError(repr(value))
assert Version("1.0rc1") < Version("1.0")
