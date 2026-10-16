"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.tags import parse_tag

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
for value in ("py3-none-any-extra", "py311"):
    try:
        parse_tag(value)
    except ValueError as error:
        assert type(error).__name__ == "InvalidTag", type(error).__name__
    else:
        raise AssertionError(value)
assert {str(tag) for tag in parse_tag("py310.py311-none-any")} == {
    "py310-none-any",
    "py311-none-any",
}
