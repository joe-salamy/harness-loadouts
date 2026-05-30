# Skill Usage Manager

`skill-usage-manager.py` has two main jobs. In this repo, the script lives at `.codex/scripts/skill-usage-manager.py`; in exported loadouts, use the copy under the target repo's active harness directory, usually `.opencode/scripts/skill-usage-manager.py` or `.codex/scripts/skill-usage-manager.py`.

1. AGENTS.md tells Codex to call it whenever a skill is loaded.
2. Users call it to review, prune, or restore skills.

## Usage Logging

Usage logging is centralized in AGENTS.md, not repeated in every `SKILL.md`.
The repo AGENTS.md uses this repo's `.codex\scripts` path; exported loadouts
should use the target repo's active harness script path.

When loading a user skill, Codex records it with:

```powershell
python .\.codex\scripts\skill-usage-manager.py record <skill-name> --scope user --path <skills-dir>
```

When loading a repo skill, Codex records it with:

```powershell
python .\.codex\scripts\skill-usage-manager.py record <skill-name> --scope repo --path <skills-dir> --repo <repo-root>
```

For repos that received an opencode loadout, use the same commands with
`.\.opencode\scripts\skill-usage-manager.py`.

The `instrument` command is retained only as a cleanup helper. It removes legacy
per-skill recording instructions from managed `SKILL.md` files.

The ledger is stored at:

- User skills: `~/.codex/skill-usage.json`
- Repo skills: `<repo>/.codex/skill-usage.json` if `.codex/` exists, otherwise `<repo>/.skill-usage.json`

## User Maintenance

Scan current usage:

```powershell
python .\.codex\scripts\skill-usage-manager.py scan --scope all
```

Preview stale skills:

```powershell
python .\.codex\scripts\skill-usage-manager.py prune --scope all
```

Archive eligible skills:

```powershell
python .\.codex\scripts\skill-usage-manager.py prune --scope all --apply
```

Restore an archived skill:

```powershell
python .\.codex\scripts\skill-usage-manager.py restore <skill-name> --scope user
```

Pruning is based on recorded skill-load distance, not wall-clock time. By
default, a skill is eligible after 100 other skill loads, pruning keeps at least
8 active skills per root, pinned skills are skipped, and nothing moves unless
`--apply` is passed.
