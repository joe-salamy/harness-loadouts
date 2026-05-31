---
name: plan-worktree
description: Creates an isolated git worktree and unique feature branch for implementing a written plan. Use when <harness> is asked to implement a plan, plan file, docs/plans/*.md file, <harness> plan, or another agent's plan without touching the current checkout; when the user declines an "Implement plan" / "Start" screen and instead references this skill; or when multiple <harness> agents will implement different plans in parallel.
---

# Plan Worktree

Use this skill before implementing a plan when the work should happen in a new worktree instead of the current checkout. This includes workflows where the user declines an "Implement plan" or "Start" UI and asks <harness> to use this skill instead.

## Workflow

1. Read the requested plan first. If the plan path is not provided, find the most likely file under `docs/plans/` by name; ask only if there is no reasonable match.

2. Derive a short slug from the plan itself:
   - Prefer the first Markdown H1 text in the plan.
   - Otherwise use the plan filename without `.md`.
   - Normalize to lowercase kebab-case.
   - Remove characters outside `a-z`, `0-9`, and `-`.
   - Keep it specific but short, usually 3-6 words.

3. Create unique names from the slug:
   - Branch: `feature/<slug>`
   - Worktree path: `..\<repo-name>-<slug>`
   - If either already exists, append `-2`, `-3`, etc. until both are unused.

4. Create the worktree from `main`:

```powershell
git fetch --all --prune
git worktree add ..\<repo-name>-<slug> -b feature/<slug> main
```

If `main` is not available locally, inspect branches and use the repository's default branch. Do not merge or rebase as part of setup unless the user explicitly asked.

5. Move into the new worktree and do all implementation there:

```powershell
Set-Location ..\<repo-name>-<slug>
```

Do not edit the original checkout after the worktree has been created, except to report status.

6. Implement the plan completely in the worktree. Follow this repository's AGENTS.md instructions, especially:
   - Preserve CLI and web behavior alignment.
   - Do not route around `EssayPipeline.run_step()`.
   - Keep prompt/schema changes paired where appropriate.
   - Never read, write, or diff `scratchpad.md`.

7. Verify the work in the worktree with focused tests or checks appropriate to the changed files. If the implementation worktree does not have its own `venv`, run Python/test commands from the worktree but activate the original checkout's virtualenv path:

```powershell
& <primary-checkout>\venv\Scripts\Activate.ps1
```

Keep all file operations in the implementation worktree.

8. Commit the completed implementation on the worktree branch. Do not merge into `main`.

9. Final response must include:
   - Plan path
   - Worktree path
   - Branch name
   - Commit SHA, or a clear note if no commit was created
   - Tests/checks run
   - Complete summary of all changes made, grouped by area or file
   - Implementation decisions and tradeoffs, including why notable approaches were chosen
   - Blockers or known follow-up work

The change summary must be detailed enough for a later context-cleared <harness> session to audit the worktree without rediscovering intent from scratch. Include renamed files, new files, removed code paths, schema/API contract changes, behavior changes, verification coverage, skipped checks, and any assumptions made during implementation.

## Collision Checks

Before creating the worktree, check both branch and directory collisions:

```powershell
git branch --list feature/<slug>
Test-Path ..\<repo-name>-<slug>
```

If either command shows a collision, choose the next numeric suffix and check again.
