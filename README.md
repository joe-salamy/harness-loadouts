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

## License

MIT
