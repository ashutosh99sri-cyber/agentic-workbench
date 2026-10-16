"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, Specifier

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
for text in ("addon(===)", "addon=== ; python_version >= '3.9'"):
    try:
        Requirement(text)
    except InvalidRequirement:
        pass
    else:
        raise AssertionError(text)
try:
    Specifier("===   ")
except InvalidSpecifier:
    pass
else:
    raise AssertionError("Whitespace cannot supply an arbitrary version")
assert Requirement("addon(===nightly.42)").name == "addon"
