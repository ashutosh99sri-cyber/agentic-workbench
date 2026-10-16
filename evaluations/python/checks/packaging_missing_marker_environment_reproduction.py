"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.markers import Marker, UndefinedEnvironmentName

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
try:
    Marker('extra == "speed"').evaluate(context="requirement")
except UndefinedEnvironmentName as error:
    assert isinstance(error, KeyError)
    assert error.args == ("extra",)
else:
    raise AssertionError("Missing environment keys must use the documented error")
