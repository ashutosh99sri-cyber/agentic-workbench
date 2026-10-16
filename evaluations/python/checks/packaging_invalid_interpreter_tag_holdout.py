"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.tags import parse_tag
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
try:
    parse_tag("py3.cp+311-none-any")
except ValueError as error:
    assert type(error).__name__ == "InvalidTag"
else:
    raise AssertionError("Every compressed interpreter member must be valid")
try:
    parse_wheel_filename("addons-1.0-cp!311-none-any.whl")
except InvalidWheelFilename:
    pass
else:
    raise AssertionError("Wheel parsing must translate the invalid-tag error")
assert len(parse_tag("cp311.py3-none-any")) == 2
