# Retained release-note outline

These notes concern a future tagged prerelease, separate from the owner-approved
[public source preview](PUBLICATION.md). No tagged or registry release is claimed.

The selected first version is **v0.1.0**. Use the [current release notes](../releases/0.1.0.md) for status and installation. This retained outline is background, not a registry-publication receipt.

WOOKhoop Agentic Workbench brings source inspection, reviewed changes, approved commands and durable recovery into a Python framework for supervised engineering workflows.

## Included capabilities

- CLI and Python SDK for repository inventory, source-grounded role analysis, lexical and impact context, review and retained task state.
- Bounded Python repair for existing non-test source files, with distinct baseline, change and verification approvals, exact source/digest checks and resumable recovery.
- Typed tool/provider extension points, controlled execution loops, budgets, checkpoints, cancellation and dependency-aware custom plans.
- Node subprocess adapter, optional native TypeScript structural analysis, eight read/review MCP tools and documented editor recipes.
- WOOKhoop README, a 25-page developer field guide, editable Markdown, Mermaid/SVG diagrams, license notices and public-release guidance.

## Compatibility

Python 3.11 or later. Guarded mutation and the command runner require POSIX support; Node integration requires Node 24 or later. Docker checks require a local trusted daemon and an explicitly approved image already present. See the [support matrix](../support-matrix.md) and [installation guide](../installation.md).

WOOKhoop is the presentation brand. Existing Python distribution/import names, CLI entry points and the Node protocol remain compatible.

## Known limits

The packaged repair path does not create/delete files, edit tests/configuration or perform general repository-wide migrations. Local callbacks and trusted-host execution rely on the operator's trust boundary. There is no established authenticated multi-tenant service. Optional model calls need explicit configuration and grants; live repair effectiveness and comparative cost savings are unmeasured.

Static review found no confirmed vulnerabilities in reviewed paths, with partial overall coverage. This is not a security certification. Private reporting, legal rights and the selected artifact/history must be accepted before publication.

## Validation to attach before publication

Record the exact commit/tag, Python/Node/OS versions, source and Docker checks, Node checks, clean installed wheel/sdist results, dependency advisories and SHA-256 values. Link actual hosted checks after they exist. Do not substitute retained baseline results for fresh evidence on a changed candidate.

See [readiness](READINESS.md), [contribution guidance](../../CONTRIBUTING.md) and [publication procedure](PUBLICATION.md).
