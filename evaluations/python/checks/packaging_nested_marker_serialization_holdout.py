"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.markers import Marker
from packaging.requirements import Requirement

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
requirement = Requirement(
    'addons; os_name == "posix" and (((python_version == "3.11" or python_version == "3.12")))'
)
restored = Requirement(str(requirement))
assert requirement.marker is not None and restored.marker is not None
for environment, expected in (
    ({"os_name": "nt", "python_version": "3.12"}, False),
    ({"os_name": "posix", "python_version": "3.11"}, True),
):
    assert requirement.marker.evaluate(environment) is expected
    assert restored.marker.evaluate(environment) is expected, str(restored)
assert Marker('os_name == "posix"').evaluate({"os_name": "posix"})
