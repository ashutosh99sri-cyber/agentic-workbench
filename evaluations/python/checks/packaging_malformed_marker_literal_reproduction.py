"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.markers import InvalidMarker, Marker

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
try:
    Marker('os_name == "\\x"')
except InvalidMarker:
    pass
else:
    raise AssertionError("Malformed Python escapes must be InvalidMarker")
assert Marker('os_name == "posix"').evaluate({"os_name": "posix"})
