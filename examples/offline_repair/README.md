# Offline approved repair walkthrough

This exercise runs an actual failing test, proposes the percentage fix, waits for
an exact change approval, verifies the repaired source, and restores the original
fixture through an approved rollback. It uses the public `Workbench` SDK with
`provider = "none"` and no network grant. No provider credentials are needed.

Install the package using the repository's setup instructions, then run from the
repository root with that environment's Python:

```sh
python -B examples/offline_repair/walkthrough.py --trusted-host
```

The script creates a new retained temporary directory and prints `WORKSPACE:`
before copying only `app.py` and `test_app.py` from `examples/python_app`.
The checked-in examples stay unchanged. To choose where the exercise lives:

```sh
python -B examples/offline_repair/walkthrough.py --trusted-host --workspace /path/to/new-demo
```

The destination's parent must exist. Any existing destination, including a file,
directory, or dangling symlink, is refused without touching it. Omitting
`--trusted-host` refuses the exercise before workspace creation.

`trusted-host` runs the reviewed Python command on your host with **weaker
isolation than Docker**. The command uses an absolute path to the running Python
interpreter and `-B -m unittest -q` against the runner's disposable source
snapshot. This flag is permission for this known fixture; the host backend does
not provide Docker's network or operating-system isolation. Mutation and
rollback in this exercise require POSIX. The portable read-only setup remains
available on other platforms.

Read each displayed review and digest, then type the separate approval word:

1. `BASELINE` approves the initial command. Its two regression tests fail because
   the fixture subtracts a percentage directly from the amount in cents.
2. `APPLY` approves the displayed patch and its digest. The first `execute()` call
   reports `awaiting_approval` and leaves the original source intact; resuming
   with this approval applies the change and pauses before the repaired check.
3. `CHECK` approves the repaired source snapshot and command digest. The workflow
   resumes the same task, reuses the already applied change, and completes when
   the tests actually pass.
4. `ROLLBACK` approves the exact journal and current target hashes. It restores
   the original buggy fixture while keeping the successful repair trace.

The script closes and reopens `Workbench` at every approval boundary. Authority
comes from the current answer; approval words and digests are never treated as
blanket permission. There is no automatic approval option.

Any other answer, end of input, or Ctrl-C at a prompt pauses the exercise with
exit code 1 and retains its workspace. A declined patch leaves the original
source untouched. A declined repaired check or rollback leaves the approved
patch applied. The script prints task, proposal, and change references as each
becomes available. Configuration for the `unit` command is persisted in
`.agentic/config.toml`, so inspect a retained task using the installed CLI:

```sh
agentic status TASK_ID --root WORKSPACE_PATH
agentic trace TASK_ID --root WORKSPACE_PATH
```

The trace retains the actual repaired command receipt and durable execution
phases. After rollback, its successful verification describes the historical
repaired snapshot; the current source has the deliberate bug again. The baseline
receipt is displayed in the terminal transcript.

Existing directories are always refused by this script, including a paused
exercise directory. A host application can continue a paused task using
`Workbench.execute()` with the printed task/proposal references and newly
reviewed approvals. Keep the returned `change_id` to review and approve rollback.
The exercise never deletes a directory; remove its retained workspace yourself
when inspection is complete. Exit code 0 means repair, actual verification, and
exact rollback all completed; exit code 2 indicates invalid arguments or a
workflow error.
