"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.direct_url import ArchiveInfo, DirectUrl

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
url = DirectUrl(
    url="https://reader:a@b@packages.example.net:8443/a.whl?q=1", archive_info=ArchiveInfo()
)
assert url.to_dict()["url"] == "https://packages.example.net:8443/a.whl?q=1"
assert url.to_dict(strip_user_password=False)["url"] == url.url
safe = DirectUrl(url="https://git@code.example.net/repo.zip", archive_info=ArchiveInfo())
assert safe.to_dict()["url"] == safe.url
