"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.metadata import InvalidMetadata, Metadata

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
for path in ("Z:sub/LICENSE", "d:copyright.txt"):
    try:
        _ = Metadata.from_raw({"license_files": [path]}, validate=False).license_files
    except InvalidMetadata as error:
        assert error.field == "license-file"
    else:
        raise AssertionError(path)
assert Metadata.from_raw(
    {"license_files": ["LICENSE", "docs/COPYING"]}, validate=False
).license_files == ["LICENSE", "docs/COPYING"]
