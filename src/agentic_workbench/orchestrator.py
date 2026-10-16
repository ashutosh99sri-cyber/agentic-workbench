"""Persisted acyclic workflows with bounded concurrent read-only specialists."""

from __future__ import annotations

import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from typing import Any

from .agents import AgentRuntime, WorkerLease
from .errors import WorkbenchError
from .skills import ROLES


@dataclass(frozen=True)
class Node:
    id: str
    role: str
    dependencies: tuple[str, ...] = ()
    instruction: str | None = None


def _node_data(node: Node) -> dict[str, Any]:
    data = asdict(node)
    if node.instruction is None:
        del data["instruction"]
    return data


def validate_graph(nodes: list[Node]) -> list[list[Node]]:
    if not 1 <= len(nodes) <= 32 or len({n.id for n in nodes}) != len(nodes):
        raise WorkbenchError("VALIDATION_ERROR", "Workflow needs 1–32 unique nodes")
    identifiers = {n.id for n in nodes}
    if any(
        n.role not in ROLES
        or not n.id
        or len(n.id) > 64
        or not set(n.dependencies) <= identifiers
        or len(set(n.dependencies)) != len(n.dependencies)
        or n.instruction is not None
        and (
            not isinstance(n.instruction, str)
            or not n.instruction.strip()
            or len(n.instruction.encode()) > 65_536
        )
        for n in nodes
    ):
        raise WorkbenchError("VALIDATION_ERROR", "Invalid workflow role or dependency")
    pending = list(nodes)
    done: set[str] = set()
    levels: list[list[Node]] = []
    while pending:
        ready = [node for node in pending if set(node.dependencies) <= done]
        if not ready:
            raise WorkbenchError("VALIDATION_ERROR", "Workflow graph contains a cycle")
        levels.append(ready)
        done.update(n.id for n in ready)
        pending = [n for n in pending if n.id not in done]
    return levels


def planning_graph(include_ux: bool = True) -> list[Node]:
    analysis = ["intelligence", "architecture"] + (["ux"] if include_ux else [])
    return [
        Node("discovery", "discovery"),
        *[Node(r, r, ("discovery",)) for r in analysis],
        Node("engineering", "engineering", tuple(analysis)),
        Node("testing", "testing", ("engineering",)),
        Node("documentation", "documentation", ("engineering",)),
    ]


class Orchestrator:
    def __init__(self, runtime: AgentRuntime, *, concurrency: int = 2) -> None:
        if type(concurrency) is not int or not 1 <= concurrency <= 2:
            raise WorkbenchError("VALIDATION_ERROR", "Read coordination supports concurrency 1–2")
        self.runtime, self.store, self.concurrency = runtime, runtime.store, concurrency

    def execute(
        self, instruction: str, nodes: list[Node] | None = None, *, root_id: str | None = None
    ) -> dict[str, Any]:
        if nodes is None:
            nodes = planning_graph(
                any(p.endswith((".tsx", ".jsx", ".html")) for p in self.runtime.index.files)
            )
        validate_graph(nodes)
        graph = [_node_data(node) for node in nodes]
        pins = {**self.runtime.pins("orchestrator"), "graph": graph}
        if root_id is None:
            root_id = self.store.create_task("orchestrator", instruction, pins)
            task_ids = {
                n.id: self.store.create_task(
                    n.role,
                    n.instruction or instruction,
                    self.runtime.pins(n.role),
                    root_id,
                    root_id,
                )
                for n in nodes
            }
            self.store.save("workflow", root_id, {"nodes": graph, "task_ids": task_ids})
        else:
            root = self.store.get_task(root_id)
            saved = self.store.load("workflow", root_id)
            self.runtime.verify_task(root, "orchestrator", instruction, {"graph": graph})
            if saved is None or saved["nodes"] != [
                _node_data(n) | {"dependencies": list(n.dependencies)} for n in nodes
            ]:
                raise WorkbenchError("CONFLICT", "Persisted workflow graph changed")
            task_ids = saved["task_ids"]
            for node in nodes:
                child = self.store.get_task(task_ids[node.id])
                self.runtime.verify_task(child, node.role, node.instruction or instruction)
                if child["root_id"] != root_id or child["parent_id"] != root_id:
                    raise WorkbenchError("CONFLICT", "Workflow child ownership changed")
            if root["state"] == "succeeded":
                return root["result"]  # type: ignore[no-any-return]
            self.store.resume(root_id, pins)
        owner = uuid.uuid4().hex
        if not self.store.claim(root_id, owner):
            raise WorkbenchError("CONFLICT", "Workflow is already owned")
        lease = WorkerLease(self.store, root_id, owner)
        lease.start()
        completed: dict[str, dict[str, Any]] = {}
        try:

            def run(node: Node) -> tuple[str, dict[str, Any]]:
                task_id = task_ids[node.id]
                status = self.store.get_task(task_id)
                if status["state"] in {"failed", "interrupted"}:
                    self.store.resume(task_id, self.runtime.pins(node.role))
                result = self.runtime.run(
                    node.role,
                    node.instruction or instruction,
                    task_id=task_id,
                    dependencies=[completed[d] for d in node.dependencies],
                )
                return node.id, result

            pending = {node.id: node for node in nodes}
            active: set[Future[tuple[str, dict[str, Any]]]] = set()
            with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                while pending or active:
                    if self.store.get_task(root_id)["state"] == "cancelled":
                        raise WorkbenchError("CANCELLED", "Workflow was cancelled by the host")
                    lease.check()
                    for node in list(pending.values()):
                        if len(active) >= self.concurrency:
                            break
                        if set(node.dependencies) <= completed.keys():
                            active.add(pool.submit(run, node))
                            del pending[node.id]
                    finished, active = wait(active, return_when=FIRST_COMPLETED)
                    for future in finished:
                        identifier, result = future.result()
                        completed[identifier] = result
                    self.store.heartbeat(root_id, owner)
            results = [completed[node.id] for node in nodes]
            proposals = [p for r in results for p in r["proposal_ids"]]
            output = {
                "task_id": root_id,
                "proposal_ids": proposals,
                "proposals": [self.runtime.changes.review(p) for p in proposals],
                "results": results,
            }
            lease.check()
            lease.close()
            self.store.transition(root_id, "running", "succeeded", result=output)
            return output
        except WorkbenchError as error:
            if self.store.get_task(root_id)["state"] == "running":
                self.store.transition(root_id, "running", "failed", error=error.to_dict())
            raise
        except BaseException:
            self.store.transition(
                root_id,
                "running",
                "interrupted",
                error={"code": "INTERRUPTED", "message": "Workflow stopped before completion"},
            )
            raise
        finally:
            lease.close()
