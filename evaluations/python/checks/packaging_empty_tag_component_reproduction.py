"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.tags import parse_tag

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
try:
    parse_tag("py3--any")
except ValueError:
    pass
else:
    raise AssertionError("Empty ABI must be rejected")
assert len(parse_tag("py3-none-any")) == 1
