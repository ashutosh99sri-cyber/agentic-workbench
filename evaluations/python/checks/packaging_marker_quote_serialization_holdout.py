"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.markers import Marker
from packaging.requirements import Requirement

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
requirement = Requirement("addons; os_name == 'say \"yes\"'")
restored = Requirement(str(requirement))
assert restored.marker is not None
assert restored.marker.evaluate({"os_name": 'say "yes"'})
assert not restored.marker.evaluate({"os_name": 'say "no"'})
single_quote = Marker('os_name == "can\'t"')
assert Marker(str(single_quote)).evaluate({"os_name": "can't"})
