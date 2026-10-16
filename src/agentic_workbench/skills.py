"""Validated, immutable instruction packages; skills cannot grant authority."""

from __future__ import annotations

import re
import stat
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .config import READ_TOOLS
from .errors import WorkbenchError
from .models import canonical_hash
from .policy import WorkspacePolicy

ROLES = (
    "discovery",
    "intelligence",
    "engineering",
    "architecture",
    "ux",
    "testing",
    "documentation",
    "orchestrator",
)


@dataclass(frozen=True)
class Skill:
    id: str
    version: str
    description: str
    roles: tuple[str, ...]
    frameworks: tuple[str, ...]
    languages: tuple[str, ...]
    required_tools: tuple[str, ...]
    instructions: str
    content_hash: str
    provenance: str

    def pin(self) -> dict[str, str]:
        return {"id": self.id, "version": self.version, "hash": self.content_hash}


def _read(package: Path, name: str) -> str:
    if not name or "\\" in name or any(p in {"", ".", ".."} for p in name.split("/")):
        raise WorkbenchError("VALIDATION_ERROR", "Invalid skill reference")
    target = package / name
    if target.resolve() != target or target.is_symlink():
        raise WorkbenchError("POLICY_DENIED", "Skill references cannot use aliases")
    try:
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65_536:
            raise WorkbenchError("LIMIT_EXCEEDED", "Skill file is unsafe or oversized")
        data = target.read_bytes()
        if len(data) > 65_536:
            raise WorkbenchError("LIMIT_EXCEEDED", "Skill file exceeds byte limit")
        after = target.lstat()
        if (info.st_ino, info.st_mtime_ns, info.st_size) != (
            after.st_ino,
            after.st_mtime_ns,
            after.st_size,
        ):
            raise WorkbenchError("CONFLICT", "Skill changed while being loaded")
        return data.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise WorkbenchError("VALIDATION_ERROR", "Skill file unavailable") from error


class SkillRegistry:
    def __init__(
        self,
        policy: WorkspacePolicy,
        *,
        directories: list[Path] | None = None,
        external_scopes: tuple[Path, ...] = (),
    ) -> None:
        bundled = Path(str(files("agentic_workbench").joinpath("bundled_skills"))).resolve()
        roots = [bundled]
        for supplied in directories or []:
            root = supplied.absolute()
            if root.is_symlink() or root.resolve() != root:
                raise WorkbenchError("POLICY_DENIED", "Skill directories cannot use aliases")
            if not root.is_relative_to(policy.root) and root not in external_scopes:
                raise WorkbenchError("POLICY_DENIED", "External skills need a host read scope")
            roots.append(root)
        self.skills: list[Skill] = []
        for root in roots:
            try:
                packages = sorted(root.iterdir())
            except OSError as error:
                raise WorkbenchError("VALIDATION_ERROR", "Skill directory unavailable") from error
            if len(packages) > 100:
                raise WorkbenchError("LIMIT_EXCEEDED", "Too many skill packages")
            for package in packages:
                if package.is_dir():
                    self.skills.append(self._load(package, policy))
        if len({s.id for s in self.skills}) != len(self.skills):
            raise WorkbenchError("VALIDATION_ERROR", "Duplicate skill identifier")
        self.skills.sort(key=lambda skill: skill.id)

    def _load(self, package: Path, policy: WorkspacePolicy) -> Skill:
        metadata_text = _read(package, "skill.toml")
        try:
            raw = tomllib.loads(metadata_text)
        except tomllib.TOMLDecodeError as error:
            raise WorkbenchError("VALIDATION_ERROR", "Invalid skill metadata") from error
        fields = {
            "id",
            "version",
            "description",
            "roles",
            "frameworks",
            "languages",
            "required_tools",
            "contract_version",
            "evidence",
            "references",
            "provenance",
        }
        if (
            set(raw) != fields
            or raw["contract_version"] != 1
            or type(raw["contract_version"]) is not int
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Unknown or missing skill metadata")
        for name in ("id", "version", "description", "provenance", "evidence"):
            if not isinstance(raw[name], str) or not 1 <= len(raw[name]) <= 1000:
                raise WorkbenchError("VALIDATION_ERROR", "Invalid skill text metadata")
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", raw["id"]) or not re.fullmatch(
            r"\d+\.\d+\.\d+", raw["version"]
        ):
            raise WorkbenchError("VALIDATION_ERROR", "Invalid skill identifier/version")
        for name in ("roles", "frameworks", "languages", "required_tools", "references"):
            if (
                not isinstance(raw[name], list)
                or len(raw[name]) > 32
                or not all(isinstance(x, str) and 1 <= len(x) <= 256 for x in raw[name])
            ):
                raise WorkbenchError("VALIDATION_ERROR", "Invalid skill list metadata")
        if (
            not raw["roles"]
            or not set(raw["roles"]) <= set(ROLES)
            or not set(raw["required_tools"]) <= set(READ_TOOLS)
        ):
            raise WorkbenchError("POLICY_DENIED", "Skill requests unsupported roles or tools")
        instructions = _read(package, "SKILL.md")
        references = {name: _read(package, name) for name in raw["references"]}
        content = (
            instructions
            + "\n"
            + "\n".join(f"Reference {name}:\n{text}" for name, text in references.items())
        )
        if len(content.encode()) > 262_144 or policy.redactor.contains_secret(content):
            raise WorkbenchError(
                "POLICY_DENIED", "Skill content is oversized or contains credentials"
            )
        return Skill(
            raw["id"],
            raw["version"],
            raw["description"],
            tuple(raw["roles"]),
            tuple(raw["frameworks"]),
            tuple(raw["languages"]),
            tuple(raw["required_tools"]),
            content,
            canonical_hash(
                {"metadata": metadata_text, "instructions": instructions, "references": references}
            ),
            raw["provenance"],
        )

    def select(self, agent: str, frameworks: list[str], languages: list[str]) -> list[Skill]:
        if agent not in ROLES:
            raise WorkbenchError("VALIDATION_ERROR", "Unknown agent role")
        return [
            s
            for s in self.skills
            if agent in s.roles
            and (not s.frameworks or set(s.frameworks) & set(frameworks))
            and (not s.languages or set(s.languages) & set(languages))
        ]
