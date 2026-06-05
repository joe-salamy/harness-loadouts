---
name: save-plan
description: Persists an approved implementation plan into a real file in the current repository, defaulting to docs/plans/, verifies the repo file exists, and returns only the repo-relative path. Use after plan mode or whenever the user asks to save a plan locally/in this repo without implementing it.
---

# Save Plan

Persist the approved plan into the current repository and return the repository-relative path.

## Non-negotiable behavior

- `local://PLAN.md` is only a temporary harness/session file. It is not the saved plan.
- Do not report a destination path until that file exists in the current repository.
- Default destination is `docs/plans/`.
- If the user says "save-plan", "save it locally", "save it in this repo", or asks for a path usable with `worktree-flow.py --plan`, create a real repo file under `docs/plans/` unless they named another repo-relative path.
- After copying, read the saved repo file (at least the beginning and end) to verify it exists and contains the plan.
- Final response should be only the repository-relative path, unless the user asks for more.

## Workflow

1. Identify the source plan:
   - Prefer an existing plan file or harness URI such as `local://PLAN.md`.
   - If the plan only exists in conversation text, use that text.
2. Choose the destination:
   - Default to `docs/plans/`.
   - Create the directory if needed.
   - Use a concise kebab-case filename derived from the plan title or goal.
   - If the path already exists, choose a unique suffix unless the user asked to overwrite.
3. Persist the plan:
   - When the source is a file or harness URI such as `local://PLAN.md`, preserve the content exactly in the repo destination by using Bash `cp` (or the platform-equivalent shell copy command). Do not use the `write` tool for file-to-file or URI-to-file plan copies.
   - Use `write` only when creating the repo destination from conversation text because no source file exists to copy.
   - Do not edit implementation files and do not implement the plan.
4. Verify:
   - Read the destination file from the repo path.
   - Confirm the read succeeds before responding.
