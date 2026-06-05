# <harness> Worktree Flow

`worktree-flow.py` is the single entrypoint for the repeatable part of the workflow after you have an approved plan. Select the target harness with `--harness` and `--harness-dir`:

- Codex: `--harness codex --harness-dir .codex`
- Oh My Pi: `--harness omp --harness-dir .omp`

1. Creates a feature branch and Git worktree from `main`.
2. Runs <harness> implementation in that worktree.
3. Requires an implementation commit and handoff summary.
4. Runs a fresh <harness> audit pass.
5. Requires an audit summary.
6. Verifies no non-handoff changes are left pending.
7. Finishes through a temporary integration worktree.
8. Squash-merges by default and cleans up only after a successful merge.

## Quick Start

Create and approve a plan, save it as Markdown, then run the shared workflow with the desired harness settings.

Codex:

```powershell
python .\.omp\scripts\worktree-flow.py --plan docs\plans\my-plan.md --harness codex --harness-dir .codex
```

Oh My Pi:

```powershell
python .\.omp\scripts\worktree-flow.py --plan docs\plans\my-plan.md --harness omp --harness-dir .omp
```

Common options:

```powershell
# Show Git/<harness> commands without running them
python .\.omp\scripts\worktree-flow.py --plan docs\plans\my-plan.md --harness codex --harness-dir .codex --dry-run

# Implement and audit, but stop before merging
python .\.omp\scripts\worktree-flow.py --plan docs\plans\my-plan.md --harness codex --harness-dir .codex --merge-mode stop

# Keep feature/integration worktrees after completion
python .\.omp\scripts\worktree-flow.py --plan docs\plans\my-plan.md --harness codex --harness-dir .codex --keep-worktrees

# Use a non-main base branch
python .\.omp\scripts\worktree-flow.py --plan docs\plans\my-plan.md --harness codex --harness-dir .codex --base develop
```

## Required Skills

The script expects these skills to be installed in the target repo for the active harness:

- `implement-worktree`: implements the approved plan inside the script-created worktree.
- `audit-worktree`: audits the implementation in a fresh <harness> run and fixes confirmed issues.
- `merge-conflict-resolver`: resolves merge conflicts in the temporary integration worktree.

For this loadout, the source templates live under:

```text
loadouts/worktrees/.harness/skills/
```

When applying this loadout, `harness-init.ps1 -Harness <harness>` copies skills into:

```text
.<harness>/skills/
```

## Files Produced

Feature worktree:

```text
.<harness>/handoff/implementation-summary.md
.<harness>/handoff/implementation-final-response.md
.<harness>/handoff/audit-summary.md
.<harness>/handoff/audit-final-response.md
```

Conflict path only, inside the integration worktree:

```text
.<harness>/handoff/merge-conflict-context.md
.<harness>/handoff/conflict-resolution-summary.md
.<harness>/handoff/conflict-resolution-final-response.md
.<harness>/handoff/post-conflict-audit-summary.md
.<harness>/handoff/post-conflict-audit-final-response.md
```

If the plan is outside the repo, the script copies it into the feature worktree at:

```text
docs/plans/<slug>.md
```

Before cleanup, the script archives handoff files back into the primary checkout:

```text
.<harness>/worktree-flow/<slug>-<timestamp>/feature/
.<harness>/worktree-flow/<slug>-<timestamp>/integration/
```

These archive directories are the durable record after the feature and integration worktrees are removed.

## Safety Notes

- The script does not push branches or open PRs.
- `--merge-mode stop` leaves the audited feature worktree ready for manual review.
- Default merge mode is `squash`, so implementation/audit commits are treated as execution detail.
- The primary checkout is updated only after a merge succeeds in a temporary integration worktree.
- Worktrees and branches are deleted only after successful integration unless `--keep-worktrees` is set.
- The implementation phase must create at least one commit and produce a diff from the base branch.
- The audit phase may be a no-op with no new commit when the worktree is clean outside `.<harness>/handoff/`.
