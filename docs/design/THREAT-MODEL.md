# Threat model and abuse-driven verification

Assets: source code, credentials, later user edits, approval authority, task/backup state, provider budget and host execution privileges. Trust boundaries: repository/configuration/skills → runtime; retrieval/memory → provider; model/tool output → policy; human approval → writer/runner; registry packages → build environment; source snapshot → container/host runner.

| Threat | Required control and test |
| --- | --- |
| Source/skill instructions impersonate an approver | Host grants are separate typed data; malicious context cannot mint approval or expose mutating tools |
| File/parent swap or alias reaches another project | Bounded rooted reads; no-follow directory-relative writes; symlink/hard-link and swap tests |
| Proposal, configuration or base changes after review | Canonical digest and current base/policy/skill checks; stale/tampered approval tests |
| Crash or concurrent application leaves partial changes | Writer lock, durable journal, per-file atomic replace, fault injection and explicit recovery state |
| Rollback overwrites a later edit | Preflight resulting hashes for every target and fail without overwriting conflicts |
| Secrets leak through source, logs or errors | Exclude secret paths, redact known/pattern credentials before every sink, prohibit secret-bearing replacements, capture output/state tests |
| Provider request retries create uncertain paid duplicates | Intent before request, hidden retries disabled, bounded explicit rate-limit retries, OUTCOME_UNKNOWN without replay |
| Context/tool loops consume unbounded resources | Byte/file/token/request/round/time/output limits and adversarial limit tests |
| Poisoned/stale retrieval produces unsupported claims | Workspace partition, source/model/vector hashes, current-source checks and citation tests |
| Tests execute hostile application code on the host | Execution denied by default; exact command/snapshot/backend approval; hardened Docker with no original repo/credentials/socket mounts |
| Dependency/CI tooling expands authority | Locked inputs, source/provenance review, Node install scripts blocked, audited dependencies and SHA-pinned minimal-permission Actions |

A trusted same-OS-user process can modify source/state or steal that user's credentials independently of this tool. Containers retain host/kernel risk. The framework must describe those boundaries accurately; prompt instructions and local logs are not a substitute for OS/deployment security.
