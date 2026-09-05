---
name: trellis-finish-work
description: "Wrap up the current session: verify completion, archive explicitly selected completed tasks without committing, and record authorized session progress to the developer journal. Use when done coding and ready to end the session."
---

# Finish Work

Wrap up the current session: archive the active task (and any other completed-but-unarchived tasks the user wants to clean up) and record the session journal. Code commits are separate, explicitly authorized work; they are not a prerequisite for recordkeeping.

## Authorization gate

Use this bookkeeping flow only when the user requests it or the current task explicitly authorizes it. Finishing an edit does not require archive/journal commits. Use the no-commit commands below for authorized recordkeeping. Lion disables session auto-commit; do not enable it as part of finishing. Without recordkeeping authorization, deliver the validated result without executing bookkeeping. Do not inspect unrelated session records or offer cleanup of unrelated tasks by default.

## Step 1: Survey current state

```bash
python ./.trellis/scripts/get_context.py --mode record
```

This prints:

- **My active tasks** — use only the task explicitly selected for this bookkeeping request; do not expand to other tasks.
- **Git status** — quick visual on what's dirty.
- **Recent commits** — you'll need their hashes in Step 4 for `--commit`.

Ignore unrelated tasks unless the user requested cleanup of those tasks. Archive only completed tasks within the authorized scope.

## Step 2: Sanity check — classify dirty paths

Run:

```bash
git status --porcelain
```

Inspect task-owned paths under `.trellis/workspace/` and `.trellis/tasks/` separately; preserve any existing edits there and avoid overwriting them during recordkeeping. No paths are staged or committed by this flow.

For each remaining dirty path, decide whether it belongs to **the current task** or to **other parallel work** (e.g., another terminal window editing the same repo). Heuristics:

- Paths referenced in the current task's `prd.md` / `implement.jsonl` / `check.jsonl` → current task
- Paths in code areas matching the task's stated scope, or that you remember editing this session → current task
- Paths in unrelated areas you have no recollection of touching this session → other parallel work

Then route:

- **Any remaining path looks like current-task work** — skip auto-committing bookkeeping and report:
  > "This task has uncommitted changes: `<list>`. Preserve them; authorized recordkeeping can use `--no-commit`."

  Do NOT run `git commit` here. Do NOT prompt the user to commit. Uncommitted code does not block authorized no-commit recordkeeping when acceptance criteria are met. Do not archive incomplete tasks.
- **All remaining paths look unrelated** (other parallel-window work) — report them once and continue to Step 3:
  > "FYI, dirty files outside this task's scope — leaving them for the other window: `<list>`."
- **Ownership unclear** — leave those paths untouched. Ask only if the ambiguity prevents determining completion or safely writing the requested bookkeeping files.

## Step 3: Archive task(s)

```bash
python ./.trellis/scripts/task.py archive <task-name> --no-commit
```

Archive only completed tasks covered by the user's authorization, including the current task if applicable. The command moves task files without committing.

If there is no active task and the user did not confirm any cleanup archives, skip this step.

## Step 4: Record session journal

```bash
python ./.trellis/scripts/add_session.py \
  --no-commit \
  --title "Session Title" \
  --commit "hash1,hash2" \
  --summary "Brief summary"
```

Use the work-commit hashes produced in Phase 3.4 (visible in Step 1's `Recent commits` list, or via `git log --oneline`) for `--commit`. Do not include the archive commit hashes from Step 3. Use `--commit "-"` when there are no work commits. This writes the journal without committing.

Report files changed and task status. Git history remains unchanged by these no-commit commands.
