"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.tags import parse_tag
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
for value in ("py3.-none-any", "py311-none-", "-none-any"):
    try:
        parse_tag(value)
    except ValueError:
        pass
    else:
        raise AssertionError(value)
try:
    parse_wheel_filename("addons-1.0-py311-none-.whl")
except InvalidWheelFilename:
    pass
else:
    raise AssertionError("Wheel parser must reject an empty platform")
assert len(parse_tag("py310.py311-none-any")) == 2
