from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / ".codex" / "scripts" / "skill-usage-manager.py"
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


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ledger(scope: str, skills_dir: Path, loads: dict[str, int]) -> dict:
    total = sum(loads.values())
    return {
        "version": 1,
        "scopes": {
            f"{scope}:{manager.canonical(skills_dir)}": {
                "scope": scope,
                "skills_dir": manager.canonical(skills_dir),
                "archive_dir": manager.canonical(skills_dir.parent / "skills.archive"),
                "total_loads": total,
                "skills": {
                    name: {
                        "first_seen": "2026-01-01T00:00:00Z",
                        "last_seen": f"2026-01-01T00:00:0{index}Z",
                        "last_load_index": count,
                        "load_count": count,
                        "source_path": manager.canonical(skills_dir / name),
                        "archived_at": "old",
                        "pinned": False,
                    }
                    for index, (name, count) in enumerate(loads.items())
                },
            }
        },
    }


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
            repo_ledger = json.loads((repo / ".agents" / "skill-usage.json").read_text(encoding="utf-8"))
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

    def test_instrument_removes_legacy_instruction_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp) / ".codex" / "skills"
            skill_dir = make_skill(skills, "example")
            skill_md = skill_dir / "SKILL.md"
            text = skill_md.read_text(encoding="utf-8")
            skill_md.write_text(
                text.replace(
                    "# example\n",
                    (
                        f"{manager.MARKER}\n"
                        "When this skill is loaded, first run "
                        '`"python" "skill-usage-manager.py" record "example" --scope user --path "skills"`.\n\n'
                        "# example\n"
                    ),
                ),
                encoding="utf-8",
            )

            manager.main(["--user-skills-dir", str(skills), "instrument", "--scope", "user"])
            manager.main(["--user-skills-dir", str(skills), "instrument", "--scope", "user"])

            text = (skills / "example" / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\nname: example\n"))
            self.assertNotIn(manager.MARKER, text)
            self.assertNotIn('record "example" --scope user', text)
            self.assertIn("# example\n", text)

    def test_repo_instrument_leaves_uninstrumented_skill_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            skills = repo / "loadouts" / "python" / ".harness" / "skills"
            make_skill(skills, "example")
            before = (skills / "example" / "SKILL.md").read_text(encoding="utf-8")

            manager.main(["--repo", str(repo), "--include-loadout-templates", "instrument", "--scope", "repo"])

            after = (skills / "example" / "SKILL.md").read_text(encoding="utf-8")
            self.assertEqual(after, before)

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

    def test_consolidate_adds_only_feature_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_repo = root / "repo-feature"
            target_repo = root / "repo"
            source_skills = source_repo / ".codex" / "skills"
            target_skills = target_repo / ".codex" / "skills"
            base = root / "base.json"
            source = source_repo / ".codex" / "skill-usage.json"
            target = target_repo / ".codex" / "skill-usage.json"
            write_json(base, ledger("repo", source_skills, {"implement-worktree": 2}))
            write_json(source, ledger("repo", source_skills, {"implement-worktree": 5}))
            write_json(target, ledger("repo", target_skills, {"implement-worktree": 10}))

            self.assertEqual(
                manager.main(
                    [
                        "consolidate",
                        "--source-ledger",
                        str(source),
                        "--base-ledger",
                        str(base),
                        "--target-ledger",
                        str(target),
                        "--source-repo",
                        str(source_repo),
                        "--target-repo",
                        str(target_repo),
                    ]
                ),
                0,
            )

            data = json.loads(target.read_text(encoding="utf-8"))
            scope = data["scopes"][f"repo:{manager.canonical(target_skills)}"]
            self.assertEqual(scope["total_loads"], 13)
            self.assertEqual(scope["skills"]["implement-worktree"]["load_count"], 13)
            self.assertEqual(scope["skills"]["implement-worktree"]["last_load_index"], 13)

    def test_consolidate_remaps_repo_scope_to_target_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_repo = root / "repo-feature"
            target_repo = root / "repo"
            source_skills = source_repo / ".codex" / "skills"
            target_skills = target_repo / ".codex" / "skills"
            base = root / "missing-base.json"
            source = source_repo / ".codex" / "skill-usage.json"
            target = target_repo / ".codex" / "skill-usage.json"
            write_json(source, ledger("repo", source_skills, {"audit-worktree": 1}))

            manager.main(
                [
                    "consolidate",
                    "--source-ledger",
                    str(source),
                    "--base-ledger",
                    str(base),
                    "--target-ledger",
                    str(target),
                    "--source-repo",
                    str(source_repo),
                    "--target-repo",
                    str(target_repo),
                ]
            )

            data = json.loads(target.read_text(encoding="utf-8"))
            scope = data["scopes"][f"repo:{manager.canonical(target_skills)}"]
            self.assertEqual(scope["skills_dir"], manager.canonical(target_skills))
            self.assertEqual(
                scope["skills"]["audit-worktree"]["source_path"],
                manager.canonical(target_skills / "audit-worktree"),
            )


    def test_consolidate_remaps_target_worktree_scope_to_target_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_repo = root / "repo-feature"
            integration_repo = root / "repo-integrate"
            target_repo = root / "repo"
            source_skills = source_repo / ".codex" / "skills"
            integration_skills = integration_repo / ".codex" / "skills"
            target_skills = target_repo / ".codex" / "skills"
            base = root / "base.json"
            source = source_repo / ".codex" / "skill-usage.json"
            target = integration_repo / ".codex" / "skill-usage.json"
            write_json(source, ledger("repo", source_skills, {"audit-worktree": 1}))
            write_json(target, ledger("repo", integration_skills, {"merge-conflict-resolver": 2}))

            manager.main(
                [
                    "consolidate",
                    "--source-ledger",
                    str(source),
                    "--base-ledger",
                    str(base),
                    "--target-ledger",
                    str(target),
                    "--source-repo",
                    str(source_repo),
                    "--target-repo",
                    str(target_repo),
                    "--target-worktree",
                    str(integration_repo),
                ]
            )

            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(
                set(data["scopes"]),
                {f"repo:{manager.canonical(target_skills)}"},
            )
            scope = data["scopes"][f"repo:{manager.canonical(target_skills)}"]
            self.assertEqual(scope["skills"]["audit-worktree"]["load_count"], 1)
            self.assertEqual(scope["skills"]["merge-conflict-resolver"]["load_count"], 2)
            self.assertEqual(
                scope["skills"]["merge-conflict-resolver"]["source_path"],
                manager.canonical(target_skills / "merge-conflict-resolver"),
            )

    def test_consolidate_preserves_target_activity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_repo = root / "repo-feature"
            target_repo = root / "repo"
            source_skills = source_repo / ".codex" / "skills"
            target_skills = target_repo / ".codex" / "skills"
            base = root / "base.json"
            source = source_repo / ".codex" / "skill-usage.json"
            target = target_repo / ".codex" / "skill-usage.json"
            write_json(base, ledger("repo", source_skills, {"python-pro": 1}))
            write_json(source, ledger("repo", source_skills, {"python-pro": 2}))
            target_data = ledger("repo", target_skills, {"python-pro": 4, "save-plan": 3})
            target_scope = next(iter(target_data["scopes"].values()))
            target_scope["skills"]["python-pro"]["pinned"] = True
            write_json(target, target_data)

            manager.main(
                [
                    "consolidate",
                    "--source-ledger",
                    str(source),
                    "--base-ledger",
                    str(base),
                    "--target-ledger",
                    str(target),
                    "--source-repo",
                    str(source_repo),
                    "--target-repo",
                    str(target_repo),
                ]
            )

            data = json.loads(target.read_text(encoding="utf-8"))
            scope = data["scopes"][f"repo:{manager.canonical(target_skills)}"]
            self.assertEqual(scope["total_loads"], 8)
            self.assertEqual(scope["skills"]["python-pro"]["load_count"], 5)
            self.assertEqual(scope["skills"]["save-plan"]["load_count"], 3)
            self.assertTrue(scope["skills"]["python-pro"]["pinned"])

    def test_consolidate_help_documents_one_shot_semantics(self) -> None:
        stdout = io.StringIO()
        with self.assertRaises(SystemExit), redirect_stdout(stdout):
            manager.build_parser().parse_args(["consolidate", "--help"])
        help_text = stdout.getvalue()
        self.assertIn("One-shot", help_text)
        self.assertIn("Replaying", help_text)


if __name__ == "__main__":
    unittest.main()
