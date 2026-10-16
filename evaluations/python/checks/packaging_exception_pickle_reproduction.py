"""Independently authored historical packaging behavior check."""

import pickle
from pathlib import Path

import packaging
from packaging.metadata import InvalidMetadata

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
original = InvalidMetadata("summary", "summary must be one line")
restored = pickle.loads(pickle.dumps(original))  # noqa: S301 - round trip of a locally constructed object
assert type(restored) is InvalidMetadata
assert restored.field == "summary"
assert restored.args == original.args
