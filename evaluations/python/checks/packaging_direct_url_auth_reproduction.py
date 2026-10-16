"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.direct_url import ArchiveInfo, DirectUrl

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
url = DirectUrl(url="https://user:pa@ss@example.org/artifact.zip", archive_info=ArchiveInfo())
assert url.to_dict()["url"] == "https://example.org/artifact.zip"
