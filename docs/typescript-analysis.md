# Optional TypeScript and JavaScript structure

The host can enrich approved source snapshots with TypeScript 7.0.2 native declaration
relationships. A Python installation has no implicit Node requirement. Selecting the
integration requires an explicit trusted Node executable and the directory of an
already installed `typescript` 7.0.2 package, including its matching native optional
package. There is no installation, download, workspace module discovery or application
execution.

```python
from pathlib import Path
from agentic_workbench.typescript import TypeScriptAnalyzer

analyzer = TypeScriptAnalyzer(
    node_executable=Path("/trusted/bin/node"),
    typescript_package=Path("/trusted/node_modules/typescript"),
)
facts = analyzer.analyze(index.files)
```

These paths are host configuration, never repository content or model tool arguments.
Missing files, a version mismatch, an unsupported platform or an untrusted writable
runtime produce `INTEGRATION_UNAVAILABLE`. The implementation currently supports POSIX
macOS/Linux on arm64/x64; it requires process-group termination. The host hashes and
rechecks the resolved Node binary, TypeScript JavaScript runtime tree and package
metadata, native compiler binary and metadata, and bundled bridge. `fingerprint`
identifies this parser configuration. Runtime changes fail with `CONFLICT`.

The analyzer takes `dict[str, SourceFile]`. Every fact comes from those supplied
snapshots; the parser never reopens a workspace file. Eligible extensions are `.ts`,
`.tsx`, `.mts`, `.cts`, `.js`, `.jsx`, `.mjs` and `.cjs`. Secret-flagged files are
omitted and counted in `secret_files_skipped`; their content never reaches Node.
All returned paths, hashes, UTF-16 spans, line spans, target keys and row shapes are
validated against eligible snapshots before normalized facts reach the SDK.

The fixed bridge uses `typescript/unstable/sync` and `typescript/unstable/ast`, the
TypeScript 7 native API. It does not use the TypeScript 5 compiler API. It creates one
synthetic project at `/work/tsconfig.json`, with only the supplied file list, `noLib`,
`allowJs`, `checkJs`, preserved JSX and bundler module resolution. It loads no workspace
tsconfig, plugins, dependencies, type libraries or package code. Virtual filesystem
callbacks always answer from approved snapshots: absent files return `null`, absent
directories return empty entries, and existence checks return `false`. No callback
returns the `undefined` that permits real-filesystem fallback. Map-backed directory
tables also accept valid names such as `constructor` and `__proto__`.

The result contains `symbols`, `calls`, `imports`, `references`, integer `coverage`,
`limitations` and `parser` metadata. Symbols retain `name`, `kind`, `language`, source
Evidence and an `id` computed from the canonical relative path, declaration start/end
offsets and raw source hash. Native snapshot symbol IDs are never persisted. A resolved
relationship has `resolution="declaration"` and a `target_id` referring to a returned
definition. Aliases, re-exports, namespaces, static member access and lexical shadowing
use native checker declarations. Multiple declarations remain `ambiguous` instead of
selecting a same-name target arbitrarily. Dynamic/computed calls remain `dynamic`;
unavailable packages or missing declarations remain `unresolved`. No link guarantees
runtime dispatch. Syntax errors are counted, with recoverable facts retained.

Each analysis is fresh. There is no parser cache to retain cross-file links after a
source changes. A future whole-result cache must bind every current raw and redacted
source hash and the parser fingerprint, rather than file metadata or individual-file
results.

The process receives JSON over stdin in a temporary working directory and a sanitized
environment. Inherited `NODE_OPTIONS` and `NODE_PATH` are excluded. Bounds are 1,000
supplied snapshots, 8 MiB of eligible snapshot text and serialized input, 200,000 visited
AST nodes, 20,000 total fact rows, 8 MiB combined stdout/stderr and a default 15-second
timeout (host configurable up to 120 seconds). Traversal/fact truncation is counted;
input/output overflow or timeout fails explicitly. Both normal completion and failure
terminate the process group, including the native compiler. Stderr and invalid output
are not interpolated into public errors.

Node receives `--max-old-space-size=256`. This bounds the V8 old heap, not total process
RSS or the separate native compiler's memory. The integration is trusted host process
execution with bounded inputs/lifetime, not a hard OS memory sandbox. No threaded
`preexec_fn` resource-limit hook is used.

Focused verification runs real native analysis for alias/re-export/namespace links,
shadowing, JSX, JS/MJS, malformed syntax, Unicode spans, source changes and bounded
facts; it also checks unapproved real files, application nonexecution, malformed bridge
facts, source byte/count limits, sanitized environment, timeout and combined pipe bounds.
Selecting these tests without the required installed runtime fails explicitly rather
than silently skipping parser coverage.

Native UTF-16 offsets and compiler line spans are validated against the submitted snapshot. Exposed Evidence lines are then mapped to the SDK source reader's `splitlines()` convention, including control separators inside comments, so an exact citation retrieves the cited declaration. Stable symbol IDs use raw source hash and offsets rather than display line numbers.

Native compiler tests are optional when POSIX/Node/the separately installed package is absent. CI installs the locked Node adapter dependencies with `npm ci --ignore-scripts` and sets `AGENTIC_REQUIRE_TYPESCRIPT=1`, so its selected native gate fails rather than silently skipping a missing toolchain. Set that variable when running native acceptance locally.
