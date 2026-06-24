# Init Prompts

Reusable prompts for initializing target repositories. These are source templates, not loadout payloads: `harness-init.ps1` only applies files under `loadouts/<name>/`.

Use root prompts when the prompt can inspect a target repo and decide what README, skills, LSP, or OMP setup it needs independently of any one loadout. Put a prompt inside a loadout only when it must ship with files from that loadout.

- `omp-repo-init.md` — direct-execution prompt for preparing a repository for OMP coding-agent work.
