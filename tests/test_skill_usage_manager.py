from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / ".opencode" / "scripts" / "skill-usage-manager.py"
SPEC = importlib.util.spec_from_file_location("skill_usage_manager", SCRIPT_PATH)
manager = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = manager
SPEC.loader.exec_module(manager)


def make_skill(skills_dir: Path, name: str) -> Path:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    return skill_dir


class SkillUsageManagerTests(unittest.TestCase):
    def test_records_user_and_repo_skill_names_separately(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            user_skills = root / "user" / ".codex" / "skills"
            repo = root / "repo"
            repo_skills = repo / ".agents" / "skills"
            make_skill(user_skills, "reviewer")
            make_skill(repo_skills, "reviewer")

            self.assertEqual(
                manager.main(["record", "reviewer", "--scope", "user", "--path", str(user_skills)]),
                0,
            )
            self.assertEqual(
                manager.main(["record", "reviewer", "--scope", "repo", "--path", str(repo_skills), "--repo", str(repo)]),
                0,
            )

            user_ledger = json.loads((user_skills.parent / "skill-usage.json").read_text(encoding="utf-8"))
            repo_ledger = json.loads((repo / ".skill-usage.json").read_text(encoding="utf-8"))
            self.assertEqual(len(user_ledger["scopes"]), 1)
            self.assertEqual(len(repo_ledger["scopes"]), 1)
            self.assertIn("reviewer", next(iter(user_ledger["scopes"].values()))["skills"])
            self.assertIn("reviewer", next(iter(repo_ledger["scopes"].values()))["skills"])

    def test_prune_is_dry_run_until_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp) / ".codex" / "skills"
            make_skill(skills, "old-skill")
            make_skill(skills, "fresh-skill")

            manager.main(["record", "old-skill", "--scope", "user", "--path", str(skills)])
            for _ in range(101):
                manager.main(["record", "fresh-skill", "--scope", "user", "--path", str(skills)])

            manager.main(["--user-skills-dir", str(skills), "prune", "--scope", "user", "--threshold", "100", "--min-active", "1"])
            self.assertTrue((skills / "old-skill").exists())
            self.assertFalse((skills.parent / "skills.archive" / "old-skill").exists())

            manager.main(
                [
                    "--user-skills-dir",
                    str(skills),
                    "prune",
                    "--scope",
                    "user",
                    "--threshold",
                    "100",
                    "--min-active",
                    "1",
                    "--apply",
                ]
            )
            self.assertFalse((skills / "old-skill").exists())
            self.assertTrue((skills.parent / "skills.archive" / "old-skill").exists())

    def test_prune_never_archives_pinned_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp) / ".codex" / "skills"
            make_skill(skills, "openai-docs")
            make_skill(skills, "fresh-skill")

            manager.main(["record", "openai-docs", "--scope", "user", "--path", str(skills)])
            for _ in range(101):
                manager.main(["record", "fresh-skill", "--scope", "user", "--path", str(skills)])

            manager.main(
                [
                    "--user-skills-dir",
                    str(skills),
                    "prune",
                    "--scope",
                    "user",
                    "--threshold",
                    "100",
                    "--min-active",
                    "0",
                    "--apply",
                ]
            )
            self.assertTrue((skills / "openai-docs").exists())

    def test_instrument_preserves_frontmatter_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp) / ".codex" / "skills"
            make_skill(skills, "example")

            manager.main(["--user-skills-dir", str(skills), "instrument", "--scope", "user"])
            manager.main(["--user-skills-dir", str(skills), "instrument", "--scope", "user"])

            text = (skills / "example" / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\nname: example\n"))
            self.assertEqual(text.count(manager.MARKER), 1)
            self.assertIn('record "example" --scope user', text)

    def test_repo_instrument_records_with_resolved_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            skills = repo / "loadouts" / "python" / ".opencode" / "skills"
            make_skill(skills, "example")

            manager.main(["--repo", str(repo), "--include-loadout-templates", "instrument", "--scope", "repo"])

            text = (skills / "example" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn('record "example" --scope repo', text)
            self.assertIn(f'--repo "{repo.resolve()}"', text)

    def test_restore_moves_archived_skill_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp) / ".codex" / "skills"
            make_skill(skills, "old-skill")
            make_skill(skills, "fresh-skill")

            manager.main(["record", "old-skill", "--scope", "user", "--path", str(skills)])
            for _ in range(101):
                manager.main(["record", "fresh-skill", "--scope", "user", "--path", str(skills)])
            manager.main(["--user-skills-dir", str(skills), "prune", "--scope", "user", "--threshold", "100", "--min-active", "1", "--apply"])

            self.assertEqual(
                manager.main(["--user-skills-dir", str(skills), "restore", "old-skill", "--scope", "user"]),
                0,
            )
            self.assertTrue((skills / "old-skill" / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
