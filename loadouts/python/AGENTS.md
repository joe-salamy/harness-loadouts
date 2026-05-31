## Overview

[Run this command after applying the loadout to auto-generate the overview:]
`<harness> run "Read the top-level README, pyproject.toml or setup.py, and the main entry point(s) of this repo. Then replace the line containing this instruction in AGENTS.md with exactly 3 sentences: (1) what the project does and who it's for, (2) the core tech stack and architecture pattern, (3) any non-obvious conventions or constraints a contributor must know. Be specific-name frameworks, key modules, and data flows. Do not be generic."`

## Environment

- Activate venv before any pip/python commands: `venv\Scripts\Activate.ps1`
- Never pip install into the global or user environment — always use the venv.

## Git & Commits

- Read `.gitignore` before running any git commit to know what files to exclude.

## Off-Limits Files

- Never read from, write to, or git diff `scratchpad.md`.
- When running `/code-reviewer` or `/python-pro`, exclude diffs of files in `.<harness>/` and `docs/` - these are settings/prose, not reviewable code.

## Plan Mode

- When asking clarifying questions in plan mode, be liberal; when in doubt, ask more rather than fewer.

## Documentation

- Keep READMEs concise.
