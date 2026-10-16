"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.metadata import InvalidMetadata, Metadata

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
metadata = Metadata.from_raw({"license_files": ["C:NOTICE"]}, validate=False)
try:
    _ = metadata.license_files
except InvalidMetadata:
    pass
else:
    raise AssertionError("Drive-relative license paths are not project-relative")
assert Metadata.from_raw({"license_files": ["legal/NOTICE"]}, validate=False).license_files == [
    "legal/NOTICE"
]
