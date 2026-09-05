---
name: trellis-check
description: "Comprehensive quality verification: spec compliance, lint, type-check, tests, cross-layer data flow, code reuse, and consistency checks. Use when code is written and needs quality verification, before committing changes, or to catch context drift during long sessions."
---

# Code Quality Check

Comprehensive quality verification for recently written code. Combines spec compliance, cross-layer safety, and pre-commit checks.

---

## Applicability and scope

Follow project AGENTS.md for validation scope and authorization. Read-only reviews report findings without edits. Implementation checks may repair only authorized task-scope issues. Do not treat unrelated dirty paths as task-owned changes. Small direct edits do not require task artifacts; pure documentation changes need content/reference/diff checks rather than code tests.

## Step 1: Identify What Changed

```bash
git diff --name-only HEAD
git status
```

## Step 2: Read Task Artifacts and Applicable Specs

For a formal task, read its existing artifacts in order; otherwise use the current request and inspected diff:

- `prd.md`
- `design.md` if present
- `implement.md` if present

```bash
python ./.trellis/scripts/get_context.py --mode packages
```

For each changed package/layer, read the spec index and follow its **Quality Check** section:

```bash
cat .trellis/spec/<package>/<layer>/index.md
```

Read the specific guideline files referenced — the index is a pointer, not the goal.

## Step 3: Run Project Checks

Run affected lint, type-check, and tests as required by project AGENTS.md, plus `git diff --check`. Run repository-wide gates only when its stated triggers apply. Repair in-scope failures during implementation checks; report unrelated baseline failures and their validation impact without repairing them. Stop expanding checks once sufficient validation passes and no material concern remains.

## Step 4: Review Against Checklist

### Code Quality

- [ ] Linter passes?
- [ ] Type checker passes (if applicable)?
- [ ] Tests pass?
- [ ] No debug logging left in?
- [ ] No suppressed warnings or type-safety bypasses?

### Test Coverage

- [ ] Non-trivial observable behavior or boundaries covered where needed?
- [ ] Concrete bug regression covered by an existing or necessary new test?
- [ ] Changed behavior → existing tests updated?

### Spec Sync

- [ ] Does `.trellis/spec/` need updates? (new patterns, conventions, lessons learned)

> "If I fixed a bug or discovered something non-obvious, should I document it so future me won't hit the same issue?" → If YES, update the relevant spec doc.

## Step 5: Cross-Layer Dimensions (if applicable)

Skip this step if your change is confined to a single layer.

### A. Data Flow (changes touch 3+ layers)

- [ ] Read flow traces correctly: Storage → Service → API → UI
- [ ] Write flow traces correctly: UI → API → Service → Storage
- [ ] Types/schemas correctly passed between layers?
- [ ] Errors properly propagated to caller?

### B. Code Reuse (modifying constants, creating utilities)

- [ ] Searched for existing similar code before creating new?
  Use CodeGraph first in indexed repositories, per applicable AGENTS.md; otherwise use a scoped `rg` search.
- [ ] Reuse justified by shared semantics and project abstraction constraints, rather than matching literals alone?
- [ ] After batch modification, all occurrences updated?

### C. Import/Dependency (creating new files)

- [ ] Correct import paths (relative vs absolute)?
- [ ] No circular dependencies?

### D. Same-Layer Consistency

- [ ] Other places using the same concept are consistent?

---

## Step 6: Report and Fix

Report findings with evidence. In read-only mode, do not edit. In implementation mode, repair authorized in-scope findings and rerun affected checks. Report remaining blockers without expanding scope or claiming unverified success.
