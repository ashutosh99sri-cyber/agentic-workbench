"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.utils import is_normalized_name

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
assert not is_normalized_name("x--y")
assert is_normalized_name("team-addon")
