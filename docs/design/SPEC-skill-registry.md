# Specification: skill-registry

Depends on `core-contracts` and `workspace-policy`.

## Objective and contract

Discover and select original, provider-neutral skill packages. A package consists of `skill.toml` metadata, `SKILL.md` instructions and bounded optional reference files. Metadata declares id, semantic version, description, agent roles, framework/language matches, required tools, input/output contract version, evidence requirements and provenance. The content hash covers metadata, instructions and loaded references.

Ship original skills for discovery, code explanation/investigation, engineering planning, architecture review, UX source review, testing, documentation and orchestration, plus targeted Python and TypeScript guidance. Installed third-party skills inform design; their text is not vendored without licensing evidence.

Bundled resources are resolved from the installed package. Workspace skill directories must be explicitly declared; external directories require an explicit host read scope. Package paths, instruction lengths, duplicate IDs, versions, tool names, references and metadata fields are validated. Unknown metadata is rejected. References cannot escape their package. Skill scripts are never auto-executed.

Selection uses detected framework evidence and requested agent role. Each task records selected ids, versions and hashes; changed skill content invalidates resume. A skill can request a smaller tool set but cannot grant permissions, substitute approval or change provider scope. Instruction text is context, not an authorization boundary.

## Structure and style

Own `skills.py`, `bundled_skills/` and `tests/test_skills.py`. Public API: `registry.select(agent, frameworks, languages)` returns validated immutable Skill records. Every bundled skill describes objective, boundaries, evidence, output and missing-input behavior.

## Commands and verification

`uv run --locked pytest tests/test_skills.py`. Validate positive, irrelevant-framework, malformed-metadata, duplicate-id, hostile-instruction, reference-escape and changed-hash cases. Wheel-install tests confirm every bundled skill is available outside the source checkout.

## Success criteria

- Relevant original skills load automatically from actual detection results; selection and hashes are deterministic.
- Invalid or permission-expanding skills fail before tool access; changed versions cannot silently enter an in-flight task.
- The skill-authoring guide explains the format and includes a validated example with behavioral checks.

## Boundaries and open questions

Always validate skill packages and pin task content hashes. Ask before activating new executable skill integrations. Never infer that skill generation, a descriptive prompt or an installed plugin proves behavioral capability.
