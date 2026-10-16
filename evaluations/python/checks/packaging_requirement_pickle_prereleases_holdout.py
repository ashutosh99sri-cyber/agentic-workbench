"""Independently authored historical packaging behavior check."""

import copy
import pickle
from pathlib import Path

import packaging
from packaging.requirements import Requirement

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
requirement = Requirement('addons[fast]>=2.0a1; os_name == "posix"')
requirement.specifier.prereleases = False
for restored in (pickle.loads(pickle.dumps(requirement, protocol=0)), copy.deepcopy(requirement)):  # noqa: S301 - round trip of a locally constructed object
    assert restored.specifier.prereleases is False
    assert "3.0a1" not in restored.specifier
    assert restored == requirement
automatic = Requirement("addons>=1")
automatic_restored = pickle.loads(pickle.dumps(automatic))  # noqa: S301 - local round trip
assert automatic_restored.specifier.prereleases is automatic.specifier.prereleases
