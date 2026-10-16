"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.tags import parse_tag

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
try:
    parse_tag("py311-none")
except ValueError as error:
    assert type(error).__name__ == "InvalidTag", type(error).__name__
else:
    raise AssertionError("A tag needs exactly three fields")
assert len(parse_tag("py311-none-any")) == 1
