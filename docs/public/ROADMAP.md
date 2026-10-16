# WOOKhoop development roadmap

Proposed priorities, not delivery promises. The current scope is a local, supervised engineering framework. Each milestone must finish with an observable developer outcome.

| Priority | Improvement | Developer impact | Effort | Acceptance evidence |
| --- | --- | --- | --- | --- |
| 1 | Close ownership, maintainer, security-contact and release gates | Makes responsible public adoption possible | Small work, external decisions | Signed-off rights/contact/history decisions and exact artifact approval |
| 2 | Evaluate live Python repair on representative unseen defects | Establishes whether it finds useful fixes | Medium | Frozen tasks, independent hidden checks, retained failures/blocks, accepted fixes and cost/review minutes |
| 3 | Improve task-context selection and test real embeddings | Reduces missing evidence in unfamiliar repositories | Medium | Held-out anchor coverage and downstream repair outcomes with equal inputs/budgets |
| 4 | Strengthen verification plans | Reduces narrow-command false confidence | Medium | Targeted behavior plus broader regression checks bound to the same final snapshot |
| 5 | Ship one broader supervised change workflow | Helps migrations/refactors beyond existing-file Python repair | Large | Explicit file/test/config scopes, reviewed edits, interruption recovery and independent acceptance checks |
| 6 | Complete real editor tool-call coverage | Gives users trustworthy Claude Code, VS Code and Cursor recipes | Small/medium | Actual calls and denial cases per host, versions and reproducible setup |
| 7 | Run unfamiliar-developer onboarding pilots | Removes first-use friction | Small | First result without maintainer intervention; measured failure reasons and revised docs |
| 8 | Verify compatibility on hosted CI | Makes installation claims portable | Medium | Passing named Python/Node/OS matrix and clean distribution consumers; clear unsupported write paths |
| 9 | Measure large-repository, contention and recovery behavior | Makes heavy-workflow limits concrete | Medium | Representative memory/p95 latency, output/timeout bounds, conflict and crash recovery evidence |
| 10 | Maintain dependency/provenance and contribution operations | Keeps an open project supportable | Ongoing | Reviewed updates, complete notices, responsive triage, supported-version policy and reviewed translations |

## First 30 development days

The time boxes below are sequencing suggestions and depend on staffing and owner decisions.

| Window | Deliverable | Exit condition |
| --- | --- | --- |
| Days 1-5 | Resolve release gates and complete three fresh onboarding sessions | Real ownership/contact decisions; users finish the offline exercise |
| Days 6-10 | Freeze a representative Python task set and independent checks | Tasks have source/version provenance, expected behavior and recorded blocked cases |
| Days 11-15 | Run paired context/repair experiments under a chosen provider budget | Report task success, regressions, review effort, tokens, latency and actual spend without dropping failures |
| Days 16-20 | Improve the largest observed failure cause | Regression tests plus improved held-out task outcomes |
| Days 21-25 | Implement one bounded broader workflow and editor call checks | Exact review/approval/verification and interruption recovery demonstrated |
| Days 26-30 | Run hosted compatibility checks and prepare the next candidate | Clean artifacts, notices, actual hosted receipts and explicit release approval |

Do not expand to unattended cloud execution or multi-tenant hosting by simply exposing the local SDK as a service. That work needs a separate tenant, identity, isolation, authorization and operations design.
