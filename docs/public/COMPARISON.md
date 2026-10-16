# How WOOKhoop Agentic Workbench fits

Choose by the workflow you need to own. These projects serve overlapping developer needs with different starting points; a role comparison is more useful here than an unsupported feature scoreboard.

Reference set: the official documentation linked below, reviewed for this release work on **15 October 2026**. Product behavior depends on version, configuration and deployment. This page does not claim benchmark superiority or that another project lacks a capability.

| Project | Role described by its documentation | A useful evaluation question |
| --- | --- | --- |
| **WOOKhoop Agentic Workbench** | A local framework for source evidence, reviewable proposals, host-owned grants, exact approvals, durable tasks and approved verification. Python owns policy; CLI, SDK, Node and restricted MCP surfaces share it. [Implementation](../../README.md), [security boundaries](../security.md). | Do you need supervised repository investigation and bounded Python repair, with explicit approval of the source change and the check? |
| **OpenAI Agents SDK** | A framework for building agent applications with tools, handoffs, guardrails and tracing. [Official documentation](https://openai.github.io/openai-agents-python/). | Do you need to build an agent application around the SDK's agent, tool and handoff abstractions? |
| **LangGraph** | An orchestration framework for long-running, stateful agents, including durable execution and human-in-the-loop workflows. [Official overview](https://docs.langchain.com/oss/python/langgraph/overview). | Do you need to design the graph, persisted state and orchestration behavior of an agent application? |
| **OpenHands SDK** | A software development kit for building and running software agents, with composable agent and tool capabilities. [Official SDK documentation](https://docs.openhands.dev/sdk). | Do you need a software-agent foundation to embed in a product or custom development workflow? |
| **Aider** | A terminal coding assistant with Git integration for reviewing changes, commits and undo operations. [Official Git integration documentation](https://aider.chat/docs/git.html). | Do you want an interactive coding workflow centered on your terminal and Git history? |

The external descriptions above are concise role summaries of those sources. They are not exhaustive inventories or independent product acceptance tests. Read the current official documentation and try your actual task before deciding.

## Evaluate Workbench on its own contract

Workbench's implemented contract is local, supervised repository work. Its built-in repair path accepts **1–20 existing non-test Python source files** and **1–4 attempts**, with separate baseline, change and verification approvals. It does not allow that repair path to modify tests/configuration, create files or delete files. Broader workflows require trusted host planning, tools and verification logic. See [Python repair](../python-repair.md) and the [harness](../harness.md).

The default approved runner uses a disposable snapshot in Docker with no network and read-only source. A separately selected trusted-host runner has no OS sandbox. Source excerpts can reach an enabled provider or an editor model; known-secret redaction is not a substitute for reviewing business-sensitive context. See the [security model](../security.md).

The Python core works without a provider. Optional model and embedding calls require external credentials and an explicit network grant. The Node adapter delegates to the installed CLI, and inbound MCP exposes read/proposal-review tools without approval, mutation or test-execution tools. These interfaces are implemented contracts, not claims of automatic interoperability with the projects above. An integration would need its own design and validation.

## Compare evidence before comparing outcomes

Retained Workbench evidence covers **869 offline tests and 8 actual Docker acceptance tests** at implementation baseline `1e21f8a532ba7167dad26e8875a54ce487d03542`. It is not a fresh run of this documentation change. Deterministic candidate and known-patch replay checks validate workflow controls and grading; they do not measure an LLM's ability to repair a defect.

There is no established comparative task-success, time-saving, cost-saving or live-model quality result in this release record. Choose a representative task, define the same acceptance condition for each candidate tool, record provider/model/version/cost settings, and distinguish a proposed patch from an approved passing check. See [validation](../validation.md), [repair evaluation](../python-repair-evaluation.md) and [release readiness](READINESS.md).

Workbench is a **public supervised developer preview**. Version `v0.1.0` is published on PyPI and npm, with a GitHub prerelease designation. See the [current release notes](../releases/0.1.0.md) for artifact hashes, fresh consumer verification and known limits. Review [publication requirements](PUBLICATION.md) and the [roadmap](ROADMAP.md).

[Back to the README](../../README.md) · [Developer field guide](GUIDE.md) · [PDF guide](WOOKhoop-Agentic-Workbench-Guide.pdf)
