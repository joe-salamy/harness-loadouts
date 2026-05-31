# Fix <harness> Worktree Flow Audit Findings

## Goal

Fix every issue identified in the read-only audit of `.<harness>/scripts/worktree-flow.py`, and keep the exported <harness> loadout copy in sync.

## Original Findings to Address

1. Final squash/conflict commits can accidentally include `.<harness>/handoff/*` artifacts because integration context is copied into the integration worktree and then `git add -A` is used.
2. `--dry-run` still mutates the filesystem by creating directories/copying files/archiving handoff content even though help says it only prints commands.
3. Any nonzero `git merge` result is treated as a resolvable conflict, including failures with no unmerged paths.
4. `--yes` is accepted and stored but unused.

## Constraints and Repository Rules

- Do not read, write, or diff `scratchpad.md`.
- When changing any script in `.codex/scripts/`, copy the same change to `loadouts/worktrees/.<harness>/scripts/`.
- Preserve existing workflow behavior unless the behavior is one of the audited defects.
- Add focused tests for the behavioral fixes.
- Keep the implementation narrow; no broad workflow redesign.

## Critical Files to Modify

- `.<harness>/scripts/worktree-flow.py`
- `loadouts/worktrees/.harness/scripts/worktree-flow.py`
- `tests/test_codex_worktree_flow.py`

## Recommended Approach

### 1. Prevent handoff artifacts from entering final commits

Replace broad `git add -A` staging during integration with staging that explicitly excludes workflow-private handoff files.

Implementation details:

- Add a helper on `CodexWorktreeFlow`, e.g. `stage_integration_changes(worktree: Path)`, that runs the equivalent of:
  - `git add -A -- . ":(exclude).<harness>/handoff/**"`
- Use an argument list, not shell quoting, so the pathspec is passed exactly on Windows.
- For squash merges:
  - Run `git merge --squash <feature-branch>`.
  - If merge fails and real conflicts exist, run conflict resolution and post-conflict audit.
  - Stage through the helper, not plain `git add -A`.
  - Commit `Harness: <title>`.
- For no-ff merge conflict resolution:
  - After resolver/audit, stage through the same helper before `git merge --continue`.
- Keep `archive_handoff(...)` behavior so handoff records still land under the primary repo archive path.

Rationale:

- Handoff files are workflow metadata, not product changes.
- Pathspec exclusion is narrower and safer than trying to reconstruct every product path from merge output, while still allowing legitimate added/modified/deleted product files to be staged.

### 2. Make dry-run actually non-mutating

Centralize filesystem side effects behind methods that respect `runner.dry_run`.

Implementation details:

- Add small instance methods such as:
  - `ensure_dir(path)` wrapper that prints/skips when dry-run is active.
  - `copy_file(source, dest)` wrapper that prints/skips when dry-run is active.
  - `write_text(path, text)` wrapper for conflict context that prints/skips when dry-run is active.
- Use these wrappers in:
  - `create_feature_worktree`
  - `ensure_plan_in_worktree`
  - `finish`
  - `resolve_conflict`
  - `copy_integration_context`
  - `archive_handoff`
- Keep `require_file(...)` dry-run bypass as-is.
- Ensure dry-run can traverse the workflow without creating directories or copying files.

Rationale:

- The CLI help promises dry-run prints commands without executing them; filesystem effects must follow that contract.

### 3. Distinguish real merge conflicts from other merge failures

Add a helper that checks whether a failed merge produced unmerged paths.

Implementation details:

- Add `has_unmerged_paths(worktree: Path) -> bool` using `git diff --name-only --diff-filter=U` with `check=False`.
- In both squash and no-ff merge paths:
  - If merge return code is nonzero and unmerged paths exist, call `resolve_conflict(...)`.
  - If merge return code is nonzero and no unmerged paths exist, raise `FlowError(format_command_failure(merge))` instead of invoking the conflict resolver.

Rationale:

- Resolver agents should only run on actual conflict states. Other merge failures need immediate, accurate failure reporting.

### 4. Remove the unused `--yes` option

Eliminate the dead CLI/config path instead of leaving a misleading reserved flag.

Implementation details:

- Remove `yes: bool` from `FlowConfig`.
- Remove parser argument `--yes`.
- Remove `yes=args.yes` in `main(...)`.
- Update test helper construction accordingly.

Rationale:

- There are no confirmation prompts. Keeping an unused bypass flag makes the interface misleading.

## Tests to Add or Update

Add focused tests in `tests/test_codex_worktree_flow.py`:

1. Handoff files are not staged/committed in squash integration:
   - Use a temp git repo.
   - Create a feature branch/worktree with a product file change.
   - Ensure `.<harness>/handoff/implementation-summary.md` exists in copied integration context.
   - Exercise the relevant staging helper or full `finish(...)` path with controlled runner where practical.
   - Assert committed files exclude `.<harness>/handoff/*` and include the product change.

2. Dry-run filesystem wrappers do not mutate:
   - Run representative methods in dry-run mode, such as `ensure_plan_in_worktree(...)` for an external plan and `archive_handoff(...)`.
   - Assert expected destination files/directories were not created.

3. Non-conflict merge failures do not invoke conflict resolver:
   - Fake a merge command returning nonzero with no unmerged paths.
   - Assert `FlowError` is raised and `resolve_conflict(...)` is not called.

4. Real merge conflicts still invoke conflict resolver:
   - Fake a merge command returning nonzero and unmerged paths from `git diff --name-only --diff-filter=U`.
   - Assert `resolve_conflict(...)` is called.

5. `--yes` removal:
   - Update existing `FlowConfig` construction.
   - Optionally assert parser rejects `--yes` if parser coverage already exists or is easy to add.

## Verification

Run:

- `python -m py_compile .<harness>/scripts/worktree-flow.py loadouts/worktrees/.harness/scripts/worktree-flow.py`
- `python -m unittest tests.test_codex_worktree_flow`

If implementation uses a temporary git repo test, ensure it is skipped only when `git` is unavailable, matching the existing test style.

## Expected Outcome

- Integration commits contain only intended product changes, not `.<harness>/handoff` workflow artifacts.
- Dry-run performs no filesystem mutations from this script.
- Non-conflict merge failures fail with a precise `FlowError` instead of delegating to conflict resolution.
- CLI/config no longer exposes unused `--yes` plumbing.
- The canonical script and exported <harness> loadout script remain synchronized.
