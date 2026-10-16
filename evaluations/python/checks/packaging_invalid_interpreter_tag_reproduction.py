"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.tags import parse_tag

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
try:
    parse_tag("3py-none-any")
except ValueError as error:
    assert type(error).__name__ == "InvalidTag"
else:
    raise AssertionError("An interpreter tag must be a valid identifier")
assert {str(tag) for tag in parse_tag("py3-none-any")} == {"py3-none-any"}
