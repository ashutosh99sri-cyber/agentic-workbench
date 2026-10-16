"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.markers import Marker, UndefinedEnvironmentName

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
try:
    Marker('"speed" == extra').evaluate(context="requirement")
except UndefinedEnvironmentName as error:
    assert isinstance(error, KeyError)
    assert error.args == ("extra",)
else:
    raise AssertionError("Right-hand variables need the same missing-key error")
assert Marker('extra == "speed"').evaluate({"extra": "speed"}, context="requirement")
assert not Marker('extra == "speed"').evaluate()
