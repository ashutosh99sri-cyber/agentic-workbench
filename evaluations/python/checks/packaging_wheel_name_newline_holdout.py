"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
for name in ("alpha_\n", "team.package\n"):
    try:
        parse_wheel_filename(f"{name}-2.0-py311-none-any.whl")
    except InvalidWheelFilename:
        pass
    else:
        raise AssertionError(name)
assert parse_wheel_filename("team_package-2.0-py311-none-any.whl")[0] == "team-package"
