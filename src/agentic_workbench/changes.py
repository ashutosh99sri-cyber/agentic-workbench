"""Immutable exact-content proposals, host approvals and recoverable source writes."""

from __future__ import annotations

import difflib
import os
import stat
import uuid
from collections.abc import Callable
from typing import Any

from .errors import WorkbenchError
from .models import canonical_hash, text_hash, validate
from .policy import WorkspacePolicy
from .state import StateStore
from .writer import (
    cleanup_stages,
    ensure_parents,
    remove_created_directories,
    replace_source,
    writer_lock,
)


class ChangeWorkflow:
    def __init__(
        self,
        policy: WorkspacePolicy,
        store: StateStore,
        *,
        skill_pins: Callable[[], list[dict[str, str]]] | None = None,
    ) -> None:
        self.policy, self.store = policy, store
        self.skill_pins = skill_pins or (lambda: [])

    def _pins(self) -> dict[str, Any]:
        return {
            "workspace": self.policy.workspace_id,
            "config": self.policy.config.fingerprint,
            "skills": self.skill_pins(),
        }

    def _base(self, path: str) -> tuple[str | None, str | None, int]:
        parts = self.policy.check_source(path)
        if os.name == "posix":
            for depth in range(1, len(parts) + 1):
                with self.policy.directory(parts[: depth - 1]) as parent:
                    try:
                        info = os.stat(parts[depth - 1], dir_fd=parent, follow_symlinks=False)
                    except FileNotFoundError:
                        return None, None, 0o644
                    if depth < len(parts):
                        if not stat.S_ISDIR(info.st_mode):
                            raise WorkbenchError("POLICY_DENIED", "Source parent is unsafe")
                    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise WorkbenchError("POLICY_DENIED", "Source target is unsafe")
            source = self.policy.read_source(path)
            if source.contains_secrets:
                raise WorkbenchError("POLICY_DENIED", "Secret-bearing source cannot be replaced")
            return source.source_hash, source.text, stat.S_IMODE(info.st_mode)
        target = self.policy.root.joinpath(*parts)
        if target.resolve() != target:
            raise WorkbenchError("POLICY_DENIED", "Source alias is prohibited")
        if not target.exists():
            return None, None, 0o644
        source = self.policy.read_source(path)
        if source.contains_secrets:
            raise WorkbenchError("POLICY_DENIED", "Secret-bearing source cannot be replaced")
        return source.source_hash, source.text, stat.S_IMODE(target.stat().st_mode)

    def propose(
        self,
        edits: list[dict[str, Any]],
        *,
        rationale: str,
        task_id: str | None = None,
        instruction: str = "",
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if (
            not isinstance(rationale, str)
            or not 1 <= len(rationale) <= 8192
            or len(instruction) > 8192
        ):
            raise WorkbenchError(
                "VALIDATION_ERROR", "Proposal requires bounded rationale/instruction"
            )
        if self.policy.redactor.contains_secret(rationale + instruction):
            raise WorkbenchError("POLICY_DENIED", "Proposal contains credential material")
        if not isinstance(edits, list) or not 1 <= len(edits) <= 20:
            raise WorkbenchError("LIMIT_EXCEEDED", "Proposal requires 1–20 edits")
        seen: set[str] = set()
        size = 0
        for edit in edits:
            validate("CandidateEdit", edit)
            path, content = edit["path"], edit["content"]
            self.policy.check_source(path)
            if path in seen or any(
                path.startswith(p + "/") or p.startswith(path + "/") for p in seen
            ):
                raise WorkbenchError("VALIDATION_ERROR", "Conflicting edit paths")
            seen.add(path)
            if edit["delete"]:
                if content is not None or edit["base_hash"] is None:
                    raise WorkbenchError(
                        "VALIDATION_ERROR", "Deletion requires a base and no content"
                    )
            elif (
                content is None
                or "\x00" in content
                or self.policy.redactor.contains_secret(content)
            ):
                raise WorkbenchError("POLICY_DENIED", "Replacement requires safe UTF-8 text")
            if content is not None:
                size += len(content.encode())
                if len(content.encode()) > self.policy.config.scan.max_file_bytes:
                    raise WorkbenchError("LIMIT_EXCEEDED", "Replacement exceeds source byte limit")
            base, _, _ = self._base(path)
            if base != edit["base_hash"]:
                raise WorkbenchError("STALE", "Proposal base differs from current source")
        if size > 1_048_576:
            raise WorkbenchError("LIMIT_EXCEEDED", "Proposal content exceeds 1 MiB")
        for citation in evidence or []:
            validate("Evidence", citation)
            source = self.policy.read_source(citation["path"])
            if source.source_hash != citation["source_hash"] or not 1 <= citation[
                "start_line"
            ] <= citation["end_line"] <= max(1, len(source.text.splitlines())):
                raise WorkbenchError("STALE", "Proposal evidence is stale")
        identifier = uuid.uuid4().hex
        proposal = {
            "schema_version": 1,
            "proposal_id": identifier,
            "pins": self._pins(),
            "task_id": task_id,
            "instruction": instruction,
            "rationale": rationale,
            "evidence": evidence or [],
            "edits": edits,
        }
        digest = canonical_hash(proposal)
        self.store.save("proposal", identifier, {"proposal": proposal, "digest": digest})
        return self.review(identifier)

    def review(self, identifier: str) -> dict[str, Any]:
        saved = self.store.load("proposal", identifier)
        if saved is None:
            raise WorkbenchError("VALIDATION_ERROR", "Proposal is unavailable")
        proposal = saved["proposal"]
        if canonical_hash(proposal) != saved["digest"] or proposal["pins"] != self._pins():
            raise WorkbenchError("STALE", "Proposal content, configuration or skills changed")
        diff: list[str] = []
        metadata = []
        for edit in proposal["edits"]:
            base, text, _ = self._base(edit["path"])
            if base != edit["base_hash"]:
                raise WorkbenchError("STALE", "Proposal source changed")
            after = edit["content"] or ""
            diff.extend(
                difflib.unified_diff(
                    (text or "").splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    fromfile=f"a/{edit['path']}",
                    tofile=f"b/{edit['path']}",
                )
            )
            metadata.append(
                {
                    "path": edit["path"],
                    "base_hash": base,
                    "result_hash": None if edit["delete"] else text_hash(after),
                    "delete": edit["delete"],
                }
            )
        return {
            "proposal_id": identifier,
            "digest": saved["digest"],
            "rationale": proposal["rationale"],
            "edits": metadata,
            "diff": "".join(diff),
            "dry_run": True,
        }

    def apply(
        self, identifier: str, *, approval: str | None = None, dry_run: bool = False
    ) -> dict[str, Any]:
        review = self.review(identifier)
        if dry_run:
            return review
        if approval != review["digest"]:
            raise WorkbenchError("APPROVAL_REQUIRED", "Apply requires the exact reviewed digest")
        for edit in review["edits"]:
            self.policy.check_write(edit["path"])
        with writer_lock(self.policy):
            self.review(identifier)
            for record in self.store.list_records("journal"):
                if record["value"].get("state") in {"recovery_required", "applying"}:
                    raise WorkbenchError("CONFLICT", "Recover the interrupted source journal first")
            proposal = self.store.load("proposal", identifier)["proposal"]
            rows = []
            for edit in proposal["edits"]:
                base, text, mode = self._base(edit["path"])
                if base != edit["base_hash"]:
                    raise WorkbenchError(
                        "CONFLICT", "Source changed before its backup was captured"
                    )
                rows.append(
                    {
                        **edit,
                        "original": text,
                        "mode": mode,
                        "result_hash": None if edit["delete"] else text_hash(edit["content"]),
                        "written": False,
                    }
                )
            change_id = uuid.uuid4().hex
            journal: dict[str, Any] = {
                "change_id": change_id,
                "proposal_id": identifier,
                "pins": self._pins(),
                "state": "applying",
                "edits": rows,
                "created_directories": [],
                "stages": [],
            }
            self.store.save("journal", change_id, journal)
            try:
                for row in rows:
                    ensure_parents(
                        self.policy,
                        row["path"],
                        journal["created_directories"],
                        persist=lambda: self._persist(journal),
                    )
                    base, _, _ = self._base(row["path"])
                    if base != row["base_hash"]:
                        raise WorkbenchError("CONFLICT", "Source changed before write")
                    replace_source(
                        self.policy,
                        row["path"],
                        row["content"],
                        row["mode"],
                        row["base_hash"],
                        stages=journal["stages"],
                        persist=lambda: self._persist(journal),
                    )
                    row["written"] = True
                    self.store.update("journal", change_id, journal)
                journal["state"] = "applied"
                self.store.update("journal", change_id, journal)
            except Exception:
                journal["state"] = "recovery_required"
                try:
                    self._persist(journal)
                    self._restore(journal)
                except Exception:
                    journal["state"] = "recovery_required"
                    journal["recovery_issues"] = ["compensation_incomplete"]
                    try:
                        self._persist(journal)
                    except WorkbenchError:
                        # The last durable applying record still requires explicit recovery.
                        pass
                raise
            except BaseException:
                journal["state"] = "recovery_required"
                self._persist(journal)
                raise
            return {
                "change_id": change_id,
                "proposal_id": identifier,
                "state": "applied",
                "digest": approval,
                "dry_run": False,
            }

    def _persist(self, journal: dict[str, Any]) -> None:
        self.store.update("journal", journal["change_id"], journal)

    def _restore(self, journal: dict[str, Any]) -> None:
        # Preflight every target before restoring any part of the operation.
        for row in journal["edits"]:
            current, _, _ = self._base(row["path"])
            original_hash = None if row["original"] is None else text_hash(row["original"])
            if original_hash != row["base_hash"] or current not in {
                row["base_hash"],
                row["result_hash"],
            }:
                raise WorkbenchError("CONFLICT", "Later source edits prevent safe compensation")
        journal["state"] = "recovery_required"
        journal.setdefault("stages", [])
        self._persist(journal)
        for row in reversed(journal["edits"]):
            current, _, _ = self._base(row["path"])
            if current != row["base_hash"]:
                if current != row["result_hash"]:
                    raise WorkbenchError("CONFLICT", "Source changed during compensation")
                replace_source(
                    self.policy,
                    row["path"],
                    row["original"],
                    row["mode"],
                    current,
                    stages=journal["stages"],
                    persist=lambda: self._persist(journal),
                )
        issues = cleanup_stages(
            self.policy, journal["stages"], persist=lambda: self._persist(journal)
        )
        issues.extend(
            remove_created_directories(
                self.policy, journal["created_directories"], persist=lambda: self._persist(journal)
            )
        )
        journal["recovery_issues"] = issues
        journal["state"] = "recovery_required" if issues else "rolled_back"
        self._persist(journal)

    def review_rollback(self, change_id: str) -> dict[str, Any]:
        journal = self.store.load("journal", change_id)
        if journal is None:
            raise WorkbenchError("VALIDATION_ERROR", "Rollback journal is unavailable")
        if (
            journal["state"] not in {"applied", "applying", "recovery_required"}
            or journal["pins"] != self._pins()
        ):
            raise WorkbenchError("STALE", "Journal is unavailable or its policy changed")
        targets = []
        for row in journal["edits"]:
            current, _, _ = self._base(row["path"])
            if current not in {row["base_hash"], row["result_hash"]} or (
                journal["state"] == "applied" and current != row["result_hash"]
            ):
                raise WorkbenchError("CONFLICT", "Later source edits prevent rollback")
            targets.append(
                {"path": row["path"], "current_hash": current, "restore_hash": row["base_hash"]}
            )
        digest = canonical_hash({"journal": journal, "targets": targets, "action": "rollback"})
        return {
            "change_id": change_id,
            "digest": digest,
            "state": journal["state"],
            "targets": targets,
            "resources": {
                "directories": journal["created_directories"],
                "stages": journal.get("stages", []),
            },
            "recovery_issues": journal.get("recovery_issues", []),
            "dry_run": True,
        }

    def rollback(
        self, change_id: str, *, approval: str | None = None, dry_run: bool = False
    ) -> dict[str, Any]:
        review = self.review_rollback(change_id)
        if dry_run:
            return review
        if approval != review["digest"]:
            raise WorkbenchError("APPROVAL_REQUIRED", "Rollback requires the exact reviewed digest")
        for row in review["targets"]:
            self.policy.check_write(row["path"])
        with writer_lock(self.policy):
            if self.review_rollback(change_id)["digest"] != approval:
                raise WorkbenchError(
                    "STALE_APPROVAL", "Rollback review changed before the writer lock"
                )
            journal = self.store.load("journal", change_id)
            try:
                self._restore(journal)
            except BaseException:
                journal["state"] = "recovery_required"
                self.store.update("journal", change_id, journal)
                raise
        return {
            "change_id": change_id,
            "state": journal["state"],
            "recovery_issues": journal.get("recovery_issues", []),
            "digest": approval,
            "dry_run": False,
        }
