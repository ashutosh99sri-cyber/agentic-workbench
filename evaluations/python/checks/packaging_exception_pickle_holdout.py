"""Independently authored historical packaging behavior check."""

import copy
import pickle
from pathlib import Path

import packaging
from packaging.dependency_groups import CyclicDependencyGroup
from packaging.metadata import InvalidMetadata

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
original = CyclicDependencyGroup("dev", "lint", "dev")
for protocol in (0, pickle.HIGHEST_PROTOCOL):
    restored = pickle.loads(pickle.dumps(original, protocol=protocol))  # noqa: S301 - round trip of a locally constructed object
    assert type(restored) is CyclicDependencyGroup
    assert (restored.requested_group, restored.group, restored.include_group) == (
        "dev",
        "lint",
        "dev",
    )
    assert str(restored) == str(original)
metadata_error = InvalidMetadata("version", "bad release")
assert copy.deepcopy(metadata_error).field == "version"
