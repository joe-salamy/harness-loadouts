# Harness Loadouts

Reusable configuration templates for AI coding harnesses. A loadout packages instructions, skills, hooks, agents, commands, and other repo-local files so you can apply a consistent setup across projects with one command.

The default harness is **opencode**.

## Quick Start

```powershell
# 1. Clone this repo
git clone <repo-url> && cd harness-loadouts

# 2. Create a loadout (see examples/ for reference)
mkdir loadouts/my-loadout
# Add AGENTS.md, .opencode/skills, hooks, agents, commands, or other files

# 3. Apply it to a repo using the default opencode harness
.\harness-init.ps1 -Loadout my-loadout -Target C:\path\to\repo

# Apply a loadout for another harness
.\harness-init.ps1 -Loadout my-loadout -Target C:\path\to\repo -Harness codex
.\harness-init.ps1 -Loadout my-loadout -Target C:\path\to\repo -Harness gemini
.\harness-init.ps1 -Loadout my-loadout -Target C:\path\to\repo -Harness claude-code

# List available loadouts
.\harness-init.ps1 -List
```

## Harness Conventions

| Harness  | Instructions | Skills              | Hooks/config                         | Agents/commands              |
| -------- | ------------ | ------------------- | ------------------------------------ | ---------------------------- |
| opencode | `AGENTS.md`  | `.opencode/skills/` | `opencode.json`, `.opencode/plugins/` | `.opencode/agents/`          |
| codex    | `AGENTS.md`  | `.agents/skills/`   | `.codex/hooks.json`, `.codex/config.toml` | `.codex/agents/`        |
| gemini   | `GEMINI.md`  | n/a                 | `.gemini/settings.json`, `.gemini/hooks/` | `.gemini/commands/`     |
| claude-code | `CLAUDE.md` | `.claude/skills/` | `.claude/settings.local.json`, `.claude/hooks.json` | n/a |

Anything else in a loadout is copied recursively at the matching path. This includes `.git/hooks/`, local scripts, docs, and other support files.

## How It Works

- The harness instruction file is appended to any existing target file with a dated separator, or copied fresh if none exists.
- Skills are copied recursively for harnesses with a known skills directory.
- Codex hooks in `.codex/hooks.json`, Gemini hooks in `.gemini/settings.json`, and Claude hooks in `.claude/settings.local.json` are merged by hook event while preserving existing target settings.
- opencode plugin files and any `.git/hooks/` files are copied as ordinary files/directories.
- Existing files prompt before overwrite.

`claude-init.ps1` remains as a deprecated compatibility wrapper around `harness-init.ps1`.

## Skill Usage Pruning

`scripts/skill-usage-manager.py` tracks skill loads and archives stale skills without deleting them. It supports user-level Codex skills and repo-level skill folders:

- User skills: `~/.codex/skills` -> `~/.codex/skills.archive`
- Repo skills: `.agents/skills`, `.opencode/skills`, `.claude/skills` -> sibling `skills.archive`

Pruning is based on skill-load recency, not wall-clock time. By default, a skill becomes an archive candidate after it has not been loaded in the last 100 recorded skill loads, but pruning is always dry-run unless `--apply` is passed.

```powershell
# Add one lightweight usage-recording instruction to managed SKILL.md files
python .\scripts\skill-usage-manager.py instrument --scope all

# Show user and current-repo skill usage
python .\scripts\skill-usage-manager.py scan --scope all

# Report archive candidates only
python .\scripts\skill-usage-manager.py prune --scope all

# Actually move eligible repo skills into skills.archive
python .\scripts\skill-usage-manager.py prune --scope repo --apply

# Restore an archived user skill
python .\scripts\skill-usage-manager.py restore my-skill --scope user
```

The manager pins core user skills such as `skill-creator`, `skill-installer`, and `openai-docs` by default. Repo commands target the current git root unless `--repo <path>` is supplied; reusable templates under `loadouts/` are ignored unless `--include-loadout-templates` is passed.

## License

MIT
