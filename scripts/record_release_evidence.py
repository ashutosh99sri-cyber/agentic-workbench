"""Bind local acceptance reports and distributions to one clean source commit.

Reports are supplied by the caller. This checks consistency, not remote attestation
or maintainer approval; publication is deliberately outside this script's authority.
"""

import argparse
import configparser
import hashlib
import json
import re
import subprocess
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

NODE_CASES = (
    "test_actual_container_is_nonroot_readonly_and_cannot_access_host_or_credentials",
    "test_actual_interruption_persists_cleanup_receipt",
    "test_actual_container_network_is_disabled",
    "test_registry_command_uses_real_docker_isolation_and_receipt",
)
TIMEOUT_CASE = "test_actual_timeout_and_output_overflow_cleanup_exact_owned_container"
TIMEOUT_IDS = ("timeout", "stdout-overflow", "stderr-overflow")
PYTHON_CASE = "test_an_unstartable_docker_command_is_an_unusable_baseline"
LABELS = {"python", "docker-node", "docker-python"}
MAX_BYTES = 64 * 1024 * 1024


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(  # noqa: S603 - fixed Git operations, validated refs
        ["git", *args],  # noqa: S607 - trusted development Git executable
        cwd=root,
        capture_output=True,
        check=False,
        timeout=30,  # noqa: S607
    )
    if result.returncode:
        raise ValueError("Cannot verify Git source")
    return result.stdout


def read(path: Path, maximum: int = MAX_BYTES) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("Evidence must be a bounded regular file")
    return path.read_bytes()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def suite(path: Path, label: str) -> dict:
    data = read(path, 8 * 1024 * 1024)
    try:
        xml = data.decode("utf-8-sig")
    except UnicodeError as error:
        raise ValueError("JUnit must be UTF-8") from error
    if "\0" in xml or "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise ValueError("DTD/entity declarations are forbidden in test evidence")
    try:
        tree = ElementTree.fromstring(xml)  # noqa: S314 - bounded input, DTD/entities refused
    except ElementTree.ParseError as error:
        raise ValueError("Invalid JUnit evidence") from error
    cases = list(tree.iter("testcase"))
    if not cases or any(item.tag in {"failure", "error", "skipped"} for item in tree.iter()):
        raise ValueError("Acceptance needs nonempty passing tests with zero skips")
    for item in tree.iter():
        if any(item.get(key, "0") != "0" for key in ("failures", "errors", "skipped", "disabled")):
            raise ValueError("Acceptance report records failures or skipped cases")
    names = [case.get("name", "") for case in cases]
    expected_node = {*NODE_CASES, *(TIMEOUT_CASE + f"[{name}]" for name in TIMEOUT_IDS)}
    if label == "docker-node" and (len(names) != 7 or set(names) != expected_node):
        raise ValueError("Actual Node Docker acceptance cases are missing")
    if label == "docker-python" and names != [PYTHON_CASE]:
        raise ValueError("Actual Python Docker baseline acceptance case is missing")
    return {"tests": len(cases), "sha256": digest(data), "cases": names}


def archive_files(path: Path) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    total = 0

    seen: set[str] = set()

    def check_name(name: str, is_directory: bool) -> None:
        clean = name.removesuffix("/") if is_directory else name
        normalized = PurePosixPath(clean)
        if (
            normalized.is_absolute()
            or ".." in normalized.parts
            or "\\" in clean
            or str(normalized) != clean
            or clean in seen
            or len(seen) >= 5000
        ):
            raise ValueError("Unsafe or duplicate archive entry")
        seen.add(clean)

    def add(name: str, size: int, stream: object) -> None:
        nonlocal total
        if size > MAX_BYTES:
            raise ValueError("Archive member exceeds evidence limits")
        total += size
        if total > MAX_BYTES or len(contents) >= 5000:
            raise ValueError("Archive exceeds evidence limits")
        data = stream.read(size + 1)
        if len(data) != size:
            raise ValueError("Archive member has inconsistent size")
        contents[name] = data

    try:
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    check_name(member.filename, member.is_dir())
                    if member.is_dir():
                        continue
                    if (member.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError("Archive links are forbidden")
                    with archive.open(member) as stream:
                        add(member.filename, member.file_size, stream)
        else:
            with tarfile.open(path, "r:gz") as archive:
                for member in archive:
                    check_name(member.name, member.isdir())
                    if member.isdir():
                        continue
                    if not member.isfile():
                        raise ValueError("Archive links and special entries are forbidden")
                    stream = archive.extractfile(member)
                    assert stream is not None
                    with stream:
                        add(member.name, member.size, stream)
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError) as error:
        raise ValueError("Invalid distribution archive") from error
    return contents


def package(path: Path, sources: dict[str, bytes], expected_version: str | None) -> dict:
    read(path)  # Reject symlinks/oversized archives before opening.
    contents = archive_files(path)
    if path.suffix == ".whl":
        metadata = [name for name in contents if name.endswith(".dist-info/METADATA")]
        runtime = {
            name: data for name, data in contents.items() if name.startswith("agentic_workbench/")
        }
        allowed_info = metadata[0].split("/")[0] + "/" if len(metadata) == 1 else ""
        if not allowed_info or any(
            not name.startswith(("agentic_workbench/", allowed_info)) for name in contents
        ):
            raise ValueError("Wheel contains unexpected runtime paths")
        try:
            declared = tomllib.loads(sources["pyproject.toml"].decode())["project"]["scripts"]
            entries = configparser.ConfigParser(interpolation=None)
            entries.optionxform = str
            entries.read_string(contents[allowed_info + "entry_points.txt"].decode())
            if (
                entries.sections() != ["console_scripts"]
                or dict(entries["console_scripts"]) != declared
            ):
                raise ValueError("Wheel entry points differ from committed project")
        except (KeyError, UnicodeError, configparser.Error, tomllib.TOMLDecodeError) as error:
            raise ValueError("Wheel entry points are missing or invalid") from error
    else:
        prefixes = {name.split("/")[0] for name in contents}
        if len(prefixes) != 1:
            raise ValueError("Source distribution must have one root")
        prefix = next(iter(prefixes)) + "/"
        metadata = [prefix + "PKG-INFO"] if prefix + "PKG-INFO" in contents else []
        runtime = {
            name.removeprefix(prefix + "src/"): data
            for name, data in contents.items()
            if name.startswith(prefix + "src/agentic_workbench/")
        }
        for name, data in contents.items():
            relative = name.removeprefix(prefix)
            if relative in sources and data != sources[relative]:
                raise ValueError("Source distribution differs from Git source")
            if (
                relative not in sources
                and relative not in {"PKG-INFO", "setup.cfg"}
                and not relative.startswith("src/agentic_workbench.egg-info/")
            ):
                raise ValueError("Source distribution contains untracked source")
    expected = {
        name.removeprefix("src/"): data
        for name, data in sources.items()
        if name.startswith("src/agentic_workbench/")
    }
    if not expected or runtime != expected:
        raise ValueError("Distribution runtime differs from exact Git source")
    if len(metadata) != 1:
        raise ValueError("Distribution metadata is missing or ambiguous")
    headers = BytesParser().parsebytes(contents[metadata[0]])
    version = headers.get("Version")
    if (
        headers.get("Name") != "agentic-workbench"
        or not version
        or (expected_version is not None and version != expected_version)
    ):
        raise ValueError("Distribution version/name does not match candidate")
    return {
        "name": path.name,
        "sha256": digest(read(path)),
        "version": version,
        "runtime_files": len(runtime),
    }


def collect(
    *,
    root: Path,
    expected_commit: str,
    artifacts: Path,
    junit: dict[str, Path],
    source_receipts: dict[str, Path],
    python_image: str,
    node_image: str,
    expected_version: str | None = None,
) -> dict:
    if not re.fullmatch(r"[a-f0-9]{40}", expected_commit):
        raise ValueError("Expected commit must be an immutable full SHA")
    if git(root, "rev-parse", "HEAD").decode().strip() != expected_commit:
        raise ValueError("Evidence commit does not match HEAD")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Candidate source must be clean")
    if expected_version is not None:
        if not re.fullmatch(
            r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", expected_version
        ):
            raise ValueError("Release version must use X.Y.Z")
        tagged = (
            git(
                root,
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"refs/tags/v{expected_version}^{{commit}}",
            )
            .decode()
            .strip()
        )
        if tagged != expected_commit:
            raise ValueError("Release tag must match exact source commit")
    if set(junit) != LABELS or set(source_receipts) != LABELS:
        raise ValueError("All three acceptance suites and source receipts are required")
    images = {"node": node_image, "python": python_image}
    for image in images.values():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:+-]*@sha256:[a-f0-9]{64}", image):
            raise ValueError("Docker acceptance requires pinned image digests")
    suites = {}
    for label in sorted(LABELS):
        source_data = read(source_receipts[label], 65536)
        try:
            source = json.loads(source_data)
        except (ValueError, UnicodeError) as error:
            raise ValueError("Invalid source receipt") from error
        if not isinstance(source, dict) or source.get("commit") != expected_commit:
            raise ValueError("Test source receipt does not match candidate")
        if label.startswith("docker-"):
            kind = label.removeprefix("docker-")
            if source.get(kind + "_image") != images[kind]:
                raise ValueError("Test image receipt does not match candidate")
        suites[label] = {**suite(junit[label], label), "source_sha256": digest(source_data)}
    names = git(root, "ls-tree", "-r", "--name-only", "-z", expected_commit).decode().split("\0")
    sources = {name: git(root, "show", f"{expected_commit}:{name}") for name in names if name}
    wheels = list(artifacts.glob("*.whl"))
    sdists = list(artifacts.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("Exactly one wheel and source distribution are required")
    packages = [
        package(wheels[0], sources, expected_version),
        package(sdists[0], sources, expected_version),
    ]
    if packages[0]["version"] != packages[1]["version"]:
        raise ValueError("Wheel and source distribution versions differ")
    for path in sorted(artifacts.glob("*.tgz")):
        packages.append(
            {
                "name": path.name,
                "sha256": digest(read(path)),
                "scope": "npm archive hash only; JavaScript verification is separate",
            }
        )
    return {
        "local_candidate_verified": True,
        "publication_ready": False,
        "commit": expected_commit,
        "tree": git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
        "version": packages[0]["version"],
        "suites": suites,
        "images": images,
        "artifacts": packages,
        "external_gates": [
            "hosted CI on exact commit",
            "owner release approval",
            "package registry ownership",
            "operational private reporting channel",
            "required remote checks and review policy",
        ],
        "owner_metadata_configured": (root / ".github/release-owner.json").is_file(),
        "evidence_scope": "caller-supplied local reports; not remote attestation or approval",
    }


def mapping(items: list[str]) -> dict[str, Path]:
    result = {}
    for item in items:
        label, separator, path = item.partition("=")
        if not separator or label not in LABELS or label in result or not path:
            raise ValueError("Evidence arguments require unique LABEL=FILE values")
        result[label] = Path(path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-version")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--junit", action="append", default=[])
    parser.add_argument("--source-receipt", action="append", default=[])
    parser.add_argument("--python-image", required=True)
    parser.add_argument("--node-image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = collect(
            root=Path(__file__).resolve().parents[1],
            expected_commit=args.expected_commit,
            expected_version=args.expected_version,
            artifacts=args.artifacts,
            junit=mapping(args.junit),
            source_receipts=mapping(args.source_receipt),
            python_image=args.python_image,
            node_image=args.node_image,
        )
    except (ValueError, OSError) as error:
        parser.error(str(error))
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
