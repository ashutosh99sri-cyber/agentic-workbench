"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
try:
    parse_wheel_filename("vectorlib\n-1.0-py3-none-any.whl")
except InvalidWheelFilename:
    pass
else:
    raise AssertionError("A wheel project name must not end with a newline")
assert parse_wheel_filename("vectorlib-1.0-py3-none-any.whl")[0] == "vectorlib"
