## Skill Usage Logging

- When loading any skill, record the load with the target repo's active harness copy of `skill-usage-manager.py`.
- Use `python ./.<harness>/scripts/skill-usage-manager.py record <skill-name> --scope user --path <skills-dir>` for user skills.
- Use `python ./.<harness>/scripts/skill-usage-manager.py record <skill-name> --scope repo --path <skills-dir> --repo <repo-root>` for repo skills.
