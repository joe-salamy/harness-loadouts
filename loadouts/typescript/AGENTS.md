## Overview

[Run this command after applying the loadout to auto-generate the overview:]
`<harness> run "Read the top-level README, package.json, tsconfig.json, and the main entry point(s) of this repo. Then replace the line containing this instruction in AGENTS.md with exactly 3 sentences: (1) what the project does and who it's for, (2) the core tech stack and architecture pattern, (3) any non-obvious conventions or constraints a contributor must know. Be specific-name frameworks, key modules, and data flows. Do not be generic."`

## Code Quality

- Run `npm run lint` (or the project's lint script) before committing. Fix all errors; do not disable rules inline without justification.
- Run `npm run typecheck` (or `npx tsc --noEmit`) to verify the project compiles cleanly.
- Prefer early returns over deeply nested conditionals.

## Git & Commits

- Read `.gitignore` before running any git commit to know what files to exclude.

## Off-Limits Files

- Never read from, write to, or git diff `scratchpad.md`.
- When running `/code-reviewer` or `/typescript-code-review`, exclude diffs of files in `.<harness>/` and `docs/` - these are settings/prose, not reviewable code.

## Plan Mode

- When asking clarifying questions in plan mode, be liberal; when in doubt, ask more rather than fewer.

## Design System

This project uses the design system in `design.md`. Always reference it for colors, typography, spacing, components, and styles. Generate UI that strictly matches the tokens and patterns defined there.

## Documentation

- Keep READMEs concise.
