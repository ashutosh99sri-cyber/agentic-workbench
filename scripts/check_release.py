"""Check local release essentials without publication or credential access."""

import argparse
import json
import re
import subprocess
from pathlib import Path

from agentic_workbench import __version__
from agentic_workbench.config import Config
from agentic_workbench.models import schema


def release_provenance(root: Path, expected_version: str) -> dict[str, str]:
    if (
        re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", expected_version)
        is None
    ):
        raise ValueError("Release version must use X.Y.Z without a v prefix or leading zeros")
    tag = f"refs/tags/v{expected_version}"
    commits = []
    for ref in (f"{tag}^{{commit}}", "HEAD^{commit}"):
        result = subprocess.run(  # noqa: S603 - fixed Git command; validated full tag ref
            ["git", "rev-parse", "--verify", "--end-of-options", ref],  # noqa: S607
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0:
            raise ValueError(f"Release requires an existing tag {tag} and a Git HEAD")
        commits.append(result.stdout.strip())
    if commits[0] != commits[1]:
        raise ValueError(f"Release HEAD must equal the commit for {tag}")
    status = subprocess.run(  # noqa: S603 - fixed read-only Git command
        ["git", "status", "--porcelain", "--untracked-files=all"],  # noqa: S607
        cwd=root,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if status.returncode != 0 or status.stdout:
        raise ValueError("Release source must be clean")
    return {"tag": tag, "commit": commits[0]}


def node_release_metadata(root: Path, expected_version: str) -> None:
    node = json.loads((root / "adapters/node/package.json").read_text())
    if (
        node["version"] != expected_version
        or node.get("private", False) is not False
        or node.get("publishConfig")
        != {"access": "public", "registry": "https://registry.npmjs.org/"}
    ):
        raise ValueError("Node release must match the version and public registry settings")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    required = [
        "README.md",
        "LICENSE",
        "NOTICE",
        "THIRD_PARTY_NOTICES.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "uv.lock",
        "docs/installation.md",
        "docs/developer-adoption.md",
        "docs/skills.md",
        "docs/architecture.md",
        "docs/security.md",
        "docs/public/GUIDE.md",
        "docs/public/WOOKhoop-Agentic-Workbench-Guide.pdf",
        "docs/public/READINESS.md",
        "docs/public/PUBLICATION.md",
        "docs/public/LICENSING.md",
        "docs/recovery.md",
        "docs/providers.md",
        "examples/sdk_walkthrough.py",
        "src/agentic_workbench/py.typed",
        "adapters/node/package-lock.json",
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
    ]
    assert all((root / item).is_file() for item in required)
    assert "Apache License" in (root / "LICENSE").read_text()
    assert Config.load(root / "examples/config/agentic.toml").provider.name == "none"
    assert schema("AgentResult")["additionalProperties"] is False
    receipt = {"ok": True, "version": __version__, "required_files": len(required)}
    if args.expected_version is not None:
        try:
            receipt.update(release_provenance(root, args.expected_version))
            node_release_metadata(root, args.expected_version)
        except ValueError as error:
            parser.error(str(error))
        assert __version__ == args.expected_version
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
