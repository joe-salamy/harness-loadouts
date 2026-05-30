# Skill Usage Manager

`skill-usage-manager.py` has two main jobs. In this repo, the script lives at `.codex/scripts/skill-usage-manager.py`; in the exported opencode worktree loadout, the copy lives at `.opencode/scripts/skill-usage-manager.py`.

1. Skills call it to record that they were loaded.
2. Users call it to review, prune, or restore skills.

## Usage Logging

Run `instrument` once to add a lightweight recording instruction to each managed
`SKILL.md`:

```powershell
python .\.codex\scripts\skill-usage-manager.py instrument --scope all
```

After applying the worktrees loadout to another repo with the default opencode harness, use the exported copy from that target repo:

```powershell
python .\.opencode\scripts\skill-usage-manager.py instrument --scope all
```

The commands below use this repo's `.codex\scripts` path; use `.opencode\scripts` for repos that received the opencode loadout.

After instrumentation, each skill tells Codex to run the manager's `record`
command when the skill is loaded:

```powershell
python .\.codex\scripts\skill-usage-manager.py record <skill-name> --scope user --path <skills-dir>
python .\.codex\scripts\skill-usage-manager.py record <skill-name> --scope repo --path <skills-dir> --repo <repo-root>
```

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
