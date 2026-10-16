"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.markers import InvalidMarker, Marker
from packaging.requirements import InvalidRequirement, Requirement

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
for text in ('os_name == "\\u12"', 'os_name == "\\U0000"'):
    try:
        Marker(text)
    except InvalidMarker:
        pass
    else:
        raise AssertionError(text)
try:
    Requirement('addons; os_name == "\\x"')
except InvalidRequirement:
    pass
else:
    raise AssertionError("Requirements must translate malformed marker literals")
