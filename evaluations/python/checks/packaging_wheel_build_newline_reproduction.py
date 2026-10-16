"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
try:
    parse_wheel_filename("vectorlib-1.0-7\n-py3-none-any.whl")
except InvalidWheelFilename:
    pass
else:
    raise AssertionError("A build component must be consumed completely")
assert parse_wheel_filename("vectorlib-1.0-7-py3-none-any.whl")[2] == (7, "")
