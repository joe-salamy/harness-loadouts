---
name: save-plan
description: Saves an approved implementation plan from the current conversation into a Markdown file, defaulting to docs/plans/, and returns the relative path for use with scripts/worktree-flow.py --plan. Use after plan mode or whenever the user asks to persist a plan as a reusable plan file without implementing it.
---

# Save Plan

Save the approved plan to a Markdown file and return the relative path.

## Skill Usage Logging

When loading this skill, record the usage with forward-slash paths:

```powershell
python .<harness>/scripts/skill-usage-manager.py record save-plan --scope user --path .<harness>/skills
```

Do not use backslash-escaped script paths inside Bash/JSON strings; `.\.<harness>\scripts\...` can be mangled into an invalid path.

## Workflow

- Default to `docs/plans/`.
- Create the directory if needed.
- Use a concise kebab-case filename derived from the plan title or goal.
- Preserve the plan content without adding implementation work.
- If the path already exists, choose a unique suffix unless the user asked to overwrite.
- When the plan already exists as a file or harness URI such as `local://PLAN.md`, copy the source file directly to the destination instead of reading the whole plan into the assistant response/tool input and rewriting it. This avoids wasting tokens and preserves the content exactly.
- Use `write` only when the plan content exists only in conversation text and there is no source file to copy.
- Final response should be only the relative path, unless the user asks for more.
