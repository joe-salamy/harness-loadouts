# Codex Worktree Flow

`scripts/codex-worktree-flow.py` runs the repeatable part of the workflow after you have an approved plan:

1. Creates a feature branch and Git worktree from `main`.
2. Runs Codex implementation in that worktree.
3. Requires an implementation commit and handoff summary.
4. Runs a fresh Codex audit pass.
5. Requires an audit summary.
6. Finishes through a temporary integration worktree.
7. Squash-merges by default and cleans up only after a successful merge.

## Quick Start

Create and approve a plan in Codex plan mode, save it as Markdown, then run:

```powershell
python .\scripts\codex-worktree-flow.py --plan docs\plans\my-plan.md
```

Common options:

```powershell
# Show Git/Codex commands without running them
python .\scripts\codex-worktree-flow.py --plan docs\plans\my-plan.md --dry-run

# Implement and audit, but stop before merging
python .\scripts\codex-worktree-flow.py --plan docs\plans\my-plan.md --merge-mode stop

# Keep feature/integration worktrees after completion
python .\scripts\codex-worktree-flow.py --plan docs\plans\my-plan.md --keep-worktrees

# Use a non-main base branch
python .\scripts\codex-worktree-flow.py --plan docs\plans\my-plan.md --base develop
```

## Required Skills

The script expects these skills to be installed in the target repo for the active harness:

- `implement-worktree`: implements the approved plan inside the script-created worktree.
- `audit-worktree`: audits the implementation in a fresh Codex run and fixes confirmed issues.
- `merge-conflict-resolver`: resolves merge conflicts in the temporary integration worktree.

For this loadout, the source templates live under:

```text
loadouts/worktrees/.opencode/skills/
```

When applying this loadout for Codex, `harness-init.ps1 -Harness codex` copies skills into:

```text
.agents/skills/
```

`plan-worktree` is still available for manual worktree setup, but this script is the preferred workflow owner. The script creates, merges, and removes worktrees; the skills only guide agent behavior inside the prepared worktree.

## Files Produced

Feature worktree:

```text
.codex/handoff/implementation-summary.md
.codex/handoff/implementation-final-response.md
.codex/handoff/audit-summary.md
.codex/handoff/audit-final-response.md
```

Conflict path only, inside the integration worktree:

```text
.codex/handoff/merge-conflict-context.md
.codex/handoff/conflict-resolution-summary.md
.codex/handoff/conflict-resolution-final-response.md
.codex/handoff/post-conflict-audit-summary.md
.codex/handoff/post-conflict-audit-final-response.md
```

If the plan is outside the repo, the script copies it into the feature worktree at:

```text
docs/plans/<slug>.md
```

Before cleanup, the script archives handoff files back into the primary checkout:

```text
.codex/worktree-flow/<slug>-<timestamp>/feature/
.codex/worktree-flow/<slug>-<timestamp>/integration/
```

These archive directories are the durable record after the feature and integration worktrees are removed.

## Safety Notes

- The script does not push branches or open PRs.
- `--merge-mode stop` leaves the audited feature worktree ready for manual review.
- Default merge mode is `squash`, so implementation/audit commits are treated as execution detail.
- The primary checkout is updated only after a merge succeeds in a temporary integration worktree.
- Worktrees and branches are deleted only after successful integration unless `--keep-worktrees` is set.
