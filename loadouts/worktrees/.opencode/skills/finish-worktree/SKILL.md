---
name: finish-worktree
description: Merges a completed git worktree branch back into main, verifies the result, removes the worktree, and deletes the merged branch. Use when a Codex plan was implemented in a separate worktree and all changes are already committed on that worktree's branch; also use when the user asks to finish, integrate, merge back, clean up, remove a completed worktree, or close out a plan-worktree branch.
---

# Finish Worktree

Use this skill after a plan has been implemented and committed in a separate worktree branch.

## Assumptions

- The implementation worktree exists.
- All intended changes are committed on the worktree's branch.
- The branch should be merged into `main`.
- The worktree and branch should be deleted only after the merge succeeds.

If any assumption is false, stop and report what needs attention.

## Workflow

1. Identify the worktree path and branch:

```powershell
git worktree list
```

If the user did not provide the worktree path or branch and there is more than one plausible completed worktree, ask which one to finish.

2. Inspect the implementation worktree:

```powershell
Set-Location <worktree-path>
git status --short
git branch --show-current
git log --oneline main..HEAD
```

Stop if the worktree has uncommitted changes. Do not stash, discard, or auto-commit unless the user explicitly asks.

3. Return to the primary checkout, usually the original repository directory. Confirm it is on `main` and clean enough for integration:

```powershell
Set-Location <primary-checkout-path>
git switch main
git status --short
```

If `main` has unrelated uncommitted changes, stop and report them. Do not overwrite or revert user work.

4. Update `main` if a remote is configured:

```powershell
git fetch --all --prune
git pull --ff-only
```

If there is no remote or `pull --ff-only` is not possible, report that and continue only when local `main` is the intended base.

5. Merge the completed branch into `main`:

```powershell
git merge --no-ff <branch-name>
```

If conflicts occur, stop after reporting conflicted files. Do not delete the worktree or branch. Resolve conflicts only if the user asked for automatic conflict resolution.

6. Run verification appropriate to the change. Prefer the checks already run by the implementation agent, then add focused integration checks when the merge touched shared code.

For this repository, use the project venv for Python commands:

```powershell
& .\venv\Scripts\Activate.ps1
```

7. After the merge and verification succeed, remove the worktree and delete the branch:

```powershell
git worktree remove <worktree-path>
git branch -d <branch-name>
```

Use `git branch -D` only if the branch is definitely merged and `-d` fails due to stale metadata or an equivalent known-safe reason. Never force-delete to hide an unresolved merge problem.

8. Final response must include:
   - Merged branch name
   - Removed worktree path
   - Merge commit SHA, or note if the merge fast-forwarded
   - Tests/checks run
   - Any conflicts, skipped cleanup, or residual risks

## Safety Rules

- Do not merge if the implementation worktree is dirty.
- Do not delete the worktree before a successful merge.
- Do not delete the branch before confirming it is merged.
- Do not run destructive cleanup commands outside the identified worktree path.
- Do not touch `scratchpad.md`.
