# Source provenance

Reviewed 14 October 2026. This record supports design work; it does not establish implemented capabilities, security findings or production readiness.

## Official public documentation

| Source | Design use |
| --- | --- |
| [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling) | The application executes validated tool calls and returns outputs tied to their call IDs; model requests do not independently authorize tools. |
| [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs) | Schema-constrained provider responses, explicit refusal/error handling and application-side validation. |
| [PyPA pyproject.toml guidance](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) | Installable Python distribution metadata, build configuration and CLI entry points. |
| [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/) | One authoritative Python lockfile and isolated, locked environment checks. |
| [uv package builds](https://docs.astral.sh/uv/guides/package/) | Wheel/source-distribution build and ordinary distribution workflows. |
| [Python 3.11 SQLite](https://docs.python.org/3.11/library/sqlite3.html) | Standard-library local transactional state with minimum-version-compatible APIs. |
| [Python 3.11 filesystem interfaces](https://docs.python.org/3.11/library/os.html) | Directory-relative file access, platform support checks and guarded POSIX mutation boundaries. |
| [Docker run reference](https://docs.docker.com/reference/cli/docker/container/run/) | Explicit network/filesystem/resource/capability restrictions and image pull policy. |
| [Docker Engine security](https://docs.docker.com/engine/security/) | Accurate distinction between container configuration, daemon authority and host/kernel risks. |
| [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use) | Pinned Actions and minimal workflow permissions. |

These pages were fetched during this task. Model availability, pricing, provider limits and API details must be checked again before any live-provider acceptance run. No paid API request was performed during this design checkpoint.

Public PyPI JSON metadata was queried with verified HTTPS on 14 October 2026. Observed latest versions: jsonschema 4.26.0, pathspec 1.1.1, openai 3.29.0, pytest 9.1.1, Ruff 0.17.0, mypy 2.4.0, build 1.6.1 and setuptools 84.0.0. This is a registry observation, not evidence of installation or compatibility. The final dependency lock and tests will establish the implementation baseline.

## Third-party design influences

| Source | License | Design use |
| --- | --- | --- |
| [Ponytail](https://github.com/DietrichGebert/ponytail), copyright (c) 2026 DietrichGebert | MIT | The engineering skill's decision order (skip unneeded work, reuse existing code, prefer the standard library and platform features, then write the minimum) and its rule that validation, data-loss handling, security and accessibility are never cut. The wording is rewritten for this framework; no Ponytail source is vendored. |

## Installed engineering skills

The design workflow consulted Token Saver, Spec-Driven Development, Planning and Task Breakdown, and Incremental Implementation. RTK shell-wrapper instructions apply to this workspace. The framework will use newly authored skills whose permissions, supported frameworks, evidence requirements and behavioral tests are explicit.

The installed Sol Advisor orchestration instructions were inspected for applicability. Its model-specific routing prerequisites are not adopted as a requirement of this provider-neutral framework, and no auxiliary agent was launched during this checkpoint.

## Earlier project design guidance

Earlier Agent Skill-Builder notes informed provider-neutral skill contracts, immutable skill versions, scoped memory, behavioral evaluation and reviewed improvement. Those notes were design-stage recommendations. They are not evidence of an existing runtime or validated product, and current market/provider claims from those notes are not carried forward as facts.

## Implementation provenance rule

Every delivered capability must have an implementation pointer and relevant verification evidence. Unsupported capabilities, skipped live-provider checks, unavailable sandbox backends and unperformed hosted runs must remain explicit limitations. Original source is authored for this repository; third-party code or skill content requires separate attribution and licensing review before inclusion.
# Release engineering references

Setuptools-scm version/fallback behavior was checked against its [official configuration documentation](https://setuptools-scm.readthedocs.io/latest/config/) on 14 October 2026. Built sdists retain PKG-INFO version metadata; tagged wheels are verified against installed metadata. Apache-2.0 license text was retrieved from [Apache's official license](https://www.apache.org/licenses/LICENSE-2.0.txt). GitHub action commit pins were resolved read-only from each action's primary repository at its documented major tag, then written to the authored workflows. These references do not imply remote CI or public publication occurred.
