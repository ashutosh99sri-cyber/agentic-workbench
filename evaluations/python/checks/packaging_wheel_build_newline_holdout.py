"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
for build in ("12rc\ntrailer", "9\n\n"):
    try:
        parse_wheel_filename(f"addons-2.4-{build}-py311-none-any.whl")
    except InvalidWheelFilename:
        pass
    else:
        raise AssertionError(build)
assert parse_wheel_filename("addons-2.4-12rc-py311-none-any.whl")[2] == (12, "rc")
