"""Release gates must select one source and keep actual acceptance mandatory."""

import os
import re
import subprocess
from hashlib import sha256
from pathlib import Path
from textwrap import dedent

import pytest

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"
CI = (WORKFLOWS / "ci.yml").read_text()
RELEASE = (WORKFLOWS / "release.yml").read_text()


def block(source: str, header: str) -> str:
    """Read one indented block without adding a YAML runtime dependency."""
    before, found, after = source.partition(header + "\n")
    assert found, f"Missing workflow block: {header}"
    assert not before or before.endswith("\n")
    indentation = len(header) - len(header.lstrip())
    lines = []
    for line in after.splitlines():
        if line.strip() and len(line) - len(line.lstrip()) <= indentation:
            break
        lines.append(line)
    return "\n".join(lines)


def run(script: str, root: Path, **environment: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", dedent(script)],
        cwd=root,
        env={**os.environ, **environment},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize("source_ref", ["a" * 40, "main", "a" * 39, "a" * 40 + "\nmain"])
def test_ci_rejects_mutable_or_malformed_source_refs(tmp_path: Path, source_ref: str) -> None:
    output = tmp_path / "output"
    script = block(block(CI, "  source:"), "        run: |")
    result = run(script, tmp_path, SOURCE_REF=source_ref, GITHUB_OUTPUT=str(output))
    if source_ref == "a" * 40:
        assert result.returncode == 0, result.stderr
        assert output.read_text() == f"commit={source_ref}\n"
    else:
        assert result.returncode != 0
        assert not output.exists()


def test_every_ci_checkout_uses_the_validated_source() -> None:
    assert "  workflow_call:" in CI
    for name in ("python", "windows-readonly", "node", "docker-acceptance"):
        job = block(CI, f"  {name}:")
        assert re.search(r"^    needs: source$", job, re.MULTILINE)
        checkout = block(
            job, next(line for line in job.splitlines() if "- uses: actions/checkout@" in line)
        )
        assert "persist-credentials: false" in checkout
        assert "ref: ${{ needs.source.outputs.commit }}" in checkout


def test_release_packages_only_after_acceptance_of_the_resolved_commit() -> None:
    acceptance = block(RELEASE, "  acceptance:")
    assert "needs: prepare" in acceptance
    assert "uses: ./.github/workflows/ci.yml" in acceptance
    assert "source_ref: ${{ needs.prepare.outputs.commit }}" in acceptance
    package = block(RELEASE, "  package:")
    assert "needs: [prepare, acceptance]" in package
    assert "ref: ${{ needs.prepare.outputs.commit }}" in package
    assert 'test "$(git rev-parse HEAD)" = "$RELEASE_COMMIT"' in package
    assert "if: always()" not in package and "continue-on-error" not in package
    installs = block(package, "      - name: Install clean wheel and source distribution consumers")
    assert "dist/*.whl" in installs and "dist/*.tar.gz" in installs
    consumers = block(package, "      - name: Verify clean wheel and source distribution consumers")
    assert "working-directory: ${{ runner.temp }}" in consumers
    assert consumers.count('scripts/verify_distribution.py" --expected-version') == 2
    ci_consumers = block(CI, "      - name: Verify consumers outside the checkout")
    assert "working-directory: ${{ runner.temp }}" in ci_consumers
    assert ci_consumers.count('"$GITHUB_WORKSPACE/scripts/verify_distribution.py"') == 2


def test_docker_acceptance_and_evidence_cannot_silently_skip() -> None:
    job = block(CI, "  docker-acceptance:")
    assert not re.search(r"^    if:", job, re.MULTILINE)
    assert "continue-on-error" not in job
    assert re.findall(r"- suite: (\w+)", job) == ["node", "python"]
    images = re.findall(r"image: (\S+)", job)
    assert len(images) == 2
    assert all(re.fullmatch(r"(?:node|python)@sha256:[a-f0-9]{64}", image) for image in images)
    assert "tests/integration/test_sandbox.py" in job
    assert "tests/integration/test_python_repair.py" in job
    assert job.index("docker pull") < job.index("pytest -m docker")
    assert '--junitxml="$RUNNER_TEMP/junit/docker-${{ matrix.suite }}.xml"' in job
    assert 'os.environ["DOCKER_SUITE"] + "_image"' in job
    assert "name: ci-docker-${{ matrix.suite }}" in job
    package = block(RELEASE, "  package:")
    for label, artifact, filename in (
        ("python", "ci-python-ubuntu-latest-3.12", "python.xml"),
        ("docker-node", "ci-docker-node", "docker-node.xml"),
        ("docker-python", "ci-docker-python", "docker-python.xml"),
    ):
        assert f'--junit "{label}=$RUNNER_TEMP/ci-evidence/{artifact}/{filename}"' in package
        assert (
            f'--source-receipt "{label}=$RUNNER_TEMP/ci-evidence/{artifact}/source.json"' in package
        )
    assert '--expected-commit "$RELEASE_COMMIT" --expected-version "$RELEASE_VERSION"' in package
    for image in images:
        assert image in package


def test_workflows_keep_actions_pinned_and_permissions_readonly() -> None:
    for workflow in (CI, RELEASE):
        assert block(workflow, "permissions:").strip() == "contents: read"
        assert "secrets." not in workflow and "secrets: inherit" not in workflow
        for action in re.findall(r"uses: (\S+)", workflow):
            assert action.startswith("./") or re.fullmatch(r"[\w/-]+@[a-f0-9]{40}", action)


def test_release_resolves_the_exact_tag_even_when_head_and_branch_differ(tmp_path: Path) -> None:
    def git(*arguments: str) -> str:
        result = subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *arguments],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return result.stdout.strip()

    git("init")
    git("commit", "--allow-empty", "-m", "tagged")
    git("tag", "-a", "v1.2.3", "-m", "release")
    expected = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-m", "later")
    git("branch", "v1.2.3")
    script = block(block(RELEASE, "  prepare:"), "        run: |")
    output = tmp_path / "output"
    result = run(script, tmp_path, RELEASE_VERSION="1.2.3", GITHUB_OUTPUT=str(output))
    assert result.returncode == 0, result.stderr
    assert output.read_text() == f"commit={expected}\n"
    output.unlink()
    git("tag", "-d", "v1.2.3")
    result = run(script, tmp_path, RELEASE_VERSION="1.2.3", GITHUB_OUTPUT=str(output))
    assert result.returncode != 0 and not output.exists()
    result = run(
        script, tmp_path, RELEASE_VERSION="1.2.3; touch injected", GITHUB_OUTPUT=str(output)
    )
    assert result.returncode != 0 and not (tmp_path / "injected").exists()


def test_installed_consumer_typing_and_walkthrough_are_release_gates() -> None:
    for workflow, environment in ((CI, "agentic-clean"), (RELEASE, "agentic-release")):
        gate = block(workflow, "      - name: Verify installed SDK typing and offline walkthrough")
        assert "pytest tests/test_packaging.py -m distribution -W error" in gate
        assert f"AGENTIC_INSTALLED_PYTHON: /tmp/{environment}/bin/python" in gate
        assert f"/tmp/{environment}/bin/python examples/sdk_walkthrough.py --execute" in gate  # noqa: S108 - fixed CI assertion; creates no files
        assert "continue-on-error" not in gate


def test_release_verifies_the_packed_node_distribution_without_install_scripts() -> None:
    gate = block(RELEASE, "      - name: Verify the packed Node distribution from a clean consumer")
    assert "working-directory: ${{ runner.temp }}" in gate
    assert "npm install --ignore-scripts" in gate
    assert '"$GITHUB_WORKSPACE"/dist/*.tgz' in gate
    assert "AGENTIC_NODE_PACKAGE: '@agentic-workbench/node'" in gate
    assert 'node --test "$RUNNER_TEMP/node-consumer/integration.test.mjs"' in gate
    assert "continue-on-error" not in gate and "if:" not in gate


def test_pypi_publication_is_manual_scoped_and_credentialless() -> None:
    publish = (WORKFLOWS / "publish-pypi-010.yml").read_text()
    assert block(publish, "on:").strip() == "workflow_dispatch:"
    assert block(publish, "permissions:").strip() == "contents: read"
    job = block(publish, "  publish:")
    assert "github.ref == 'refs/heads/main'" in job
    assert "environment: pypi" in job
    assert block(job, "    permissions:").strip() == "contents: read\n      id-token: write"
    assert "uv publish --trusted-publishing always" in job
    assert "https://upload.pypi.org/legacy/" in job
    assert "secrets." not in publish and "continue-on-error" not in publish
    assert "*.tar.gz" not in publish and "*.whl" not in publish
    for action in re.findall(r"uses: (\S+)", publish):
        assert re.fullmatch(r"[\w/-]+@[a-f0-9]{40}", action)


@pytest.mark.parametrize("tampered", [False, True])
def test_pypi_download_rejects_tampered_release_bytes(tmp_path: Path, tampered: bool) -> None:
    publish = (WORKFLOWS / "publish-pypi-010.yml").read_text()
    script = block(publish, "        run: |")
    expected = b"reviewed wheel bytes"
    fixed_digest = "6d14e0ea4ab46acc6331ac0afe213a3e145765c2a7d1530b17fa02229a3961c6"
    assert fixed_digest in script
    script = script.replace(fixed_digest, sha256(expected).hexdigest())
    commands = tmp_path / "bin"
    commands.mkdir()
    curl = commands / "curl"
    curl.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        "Path(sys.argv[sys.argv.index('--output') + 1]).write_bytes("
        "os.environ['TEST_RELEASE_BYTES'].encode())\n"
    )
    curl.chmod(0o755)
    result = run(
        script,
        tmp_path,
        PATH=str(commands) + os.pathsep + os.environ["PATH"],
        TEST_RELEASE_BYTES="altered wheel bytes" if tampered else expected.decode(),
    )
    assert (result.returncode != 0) is tampered, result.stderr
    if tampered:
        assert "checksum mismatch" in result.stderr
