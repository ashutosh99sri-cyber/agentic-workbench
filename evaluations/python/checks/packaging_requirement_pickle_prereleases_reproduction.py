"""Independently authored historical packaging behavior check."""

import pickle
from pathlib import Path

import packaging
from packaging.requirements import Requirement

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
requirement = Requirement("vectorlib>=1")
requirement.specifier.prereleases = True
restored = pickle.loads(pickle.dumps(requirement))  # noqa: S301 - round trip of a locally constructed object
assert restored.specifier.prereleases is True
assert "2.0a1" in restored.specifier
