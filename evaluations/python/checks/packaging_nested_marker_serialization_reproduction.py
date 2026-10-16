"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.markers import Marker

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
marker = Marker('python_version == "3.11" and ((os_name == "posix" or os_name == "nt"))')
environment = {"python_version": "3.10", "os_name": "nt"}
assert marker.evaluate(environment) is False
assert Marker(str(marker)).evaluate(environment) is False, str(marker)
