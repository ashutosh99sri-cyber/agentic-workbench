"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.markers import Marker

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
marker = Marker("platform_version == 'build \"alpha\"'")
restored = Marker(str(marker))
assert restored.evaluate({"platform_version": 'build "alpha"'})
assert not restored.evaluate({"platform_version": "different"})
