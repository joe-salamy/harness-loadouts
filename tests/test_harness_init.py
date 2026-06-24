from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "harness-init.ps1"
UPDATE_SCRIPT = ROOT / "update-loadout-repos.ps1"


def copy_scripts_to_temp_root(root: Path) -> tuple[Path, Path]:
    harness_init = root / "harness-init.ps1"
    update_loadout_repos = root / "update-loadout-repos.ps1"
    harness_init.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    update_loadout_repos.write_text(UPDATE_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    return harness_init, update_loadout_repos



class HarnessInitTests(unittest.TestCase):
    def setUp(self) -> None:
        if not shutil.which("pwsh"):
            self.skipTest("pwsh is not installed")

    def run_init(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args],
            cwd=cwd or ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_harness_flag_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "target"
            target.mkdir()
            result = self.run_init("-Loadout", "worktrees", "-Target", str(target))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("-Harness is required", result.stdout)

    def test_harness_template_directory_maps_to_selected_harness(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loadout = root / "loadouts" / "custom"
            target = root / "target"
            (loadout / ".harness" / "skills" / "demo").mkdir(parents=True)
            target.mkdir()
            (loadout / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            (loadout / ".harness" / "settings.txt").write_text("setting\n", encoding="utf-8")
            (loadout / ".harness" / "skills" / "demo" / "SKILL.md").write_text("# Demo\n", encoding="utf-8")

            script, _ = copy_scripts_to_temp_root(root)
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Loadout", "custom", "-Target", str(target), "-Harness", "codex"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((target / "AGENTS.md").exists())
            self.assertTrue((target / ".codex" / "settings.txt").exists())
            self.assertTrue((target / ".codex" / "skills" / "demo" / "SKILL.md").exists())
            self.assertFalse((target / ".harness").exists())

    def test_generated_python_cache_files_are_not_copied(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loadout = root / "loadouts" / "custom"
            target = root / "target"
            (loadout / ".harness" / "scripts" / "__pycache__").mkdir(parents=True)
            (loadout / ".harness" / "skills" / "demo" / "__pycache__").mkdir(parents=True)
            target.mkdir()
            (loadout / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            (loadout / "root.pyc").write_bytes(b"cache")
            (loadout / ".harness" / "scripts" / "tool.py").write_text("print('ok')\n", encoding="utf-8")
            (loadout / ".harness" / "scripts" / "tool.pyc").write_bytes(b"cache")
            (loadout / ".harness" / "scripts" / "__pycache__" / "tool.cpython-313.pyc").write_bytes(b"cache")
            (loadout / ".harness" / "skills" / "demo" / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
            (loadout / ".harness" / "skills" / "demo" / "__pycache__" / "skill.cpython-313.pyc").write_bytes(b"cache")

            script, _ = copy_scripts_to_temp_root(root)
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Loadout", "custom", "-Target", str(target), "-Harness", "codex"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((target / ".codex" / "scripts" / "tool.py").exists())
            self.assertTrue((target / ".codex" / "skills" / "demo" / "SKILL.md").exists())
            self.assertFalse((target / "root.pyc").exists())
            self.assertFalse((target / ".codex" / "scripts" / "tool.pyc").exists())
            self.assertFalse((target / ".codex" / "scripts" / "__pycache__").exists())
            self.assertFalse((target / ".codex" / "skills" / "demo" / "__pycache__").exists())

    def test_records_and_upserts_repo_per_loadout(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loadout = root / "loadouts" / "custom"
            target = root / "target"
            loadout.mkdir(parents=True)
            target.mkdir()
            (loadout / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            script, _ = copy_scripts_to_temp_root(root)

            command = ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Loadout", "custom", "-Target", str(target), "-Harness", "codex"]
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            usage_path = root / "applied-repos.json"
            registry = json.loads(usage_path.read_text(encoding="utf-8"))
            data = registry["loadouts"]["custom"]
            self.assertEqual(registry["version"], 1)
            self.assertEqual(data["loadout"], "custom")
            self.assertEqual(len(data["repos"]), 1)
            self.assertEqual(data["repos"][0]["path"], str(target.resolve()))
            self.assertEqual(data["repos"][0]["harness"], "codex")
            self.assertTrue(data["repos"][0]["lastAppliedAt"])

            result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(usage_path.read_text(encoding="utf-8"))["loadouts"]["custom"]
            self.assertEqual(len(data["repos"]), 1)
            self.assertEqual(data["repos"][0]["path"], str(target.resolve()))
            self.assertEqual(data["repos"][0]["harness"], "codex")

    def test_root_usage_registry_is_not_copied_to_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loadout = root / "loadouts" / "custom"
            target = root / "target"
            loadout.mkdir(parents=True)
            target.mkdir()
            (loadout / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            (root / "applied-repos.json").write_text(
                json.dumps({"version": 1, "loadouts": {"custom": {"loadout": "custom", "repos": []}}}),
                encoding="utf-8",
            )
            script, _ = copy_scripts_to_temp_root(root)

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Loadout", "custom", "-Target", str(target), "-Harness", "codex"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((target / "applied-repos.json").exists())
            self.assertFalse((target / ".harness-loadout").exists())

    def test_force_overwrites_existing_file_without_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loadout = root / "loadouts" / "custom"
            target = root / "target"
            (loadout / ".harness").mkdir(parents=True)
            (target / ".codex").mkdir(parents=True)
            (loadout / ".harness" / "settings.txt").write_text("new", encoding="utf-8")
            (target / ".codex" / "settings.txt").write_text("old", encoding="utf-8")
            script, _ = copy_scripts_to_temp_root(root)

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Loadout", "custom", "-Target", str(target), "-Harness", "codex", "-Force"],
                cwd=root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((target / ".codex" / "settings.txt").read_text(encoding="utf-8"), "new")

    def test_update_loadout_repos_updates_recorded_repos_and_skips_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loadout = root / "loadouts" / "custom"
            target1 = root / "target1"
            target2 = root / "target2"
            missing = root / "missing"
            (loadout / ".harness").mkdir(parents=True)
            target1.mkdir()
            target2.mkdir()
            (loadout / ".harness" / "settings.txt").write_text("v1", encoding="utf-8")
            script, updater = copy_scripts_to_temp_root(root)

            for target in (target1, target2):
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Loadout", "custom", "-Target", str(target), "-Harness", "codex", "-Force"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            usage_path = root / "applied-repos.json"
            usage_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "loadouts": {
                            "custom": {
                                "loadout": "custom",
                                "repos": [
                                    {"path": str(target1.resolve()), "harness": "codex", "lastAppliedAt": "2026-06-24T00:00:00.0000000Z"},
                                    {"path": str(target2.resolve()), "harness": "codex", "lastAppliedAt": "2026-06-24T00:00:00.0000000Z"},
                                    {"path": str(missing.resolve()), "harness": "codex", "lastAppliedAt": "2026-06-24T00:00:00.0000000Z"},
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (loadout / ".harness" / "settings.txt").write_text("v2", encoding="utf-8")

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(updater), "-Loadout", "custom"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((target1 / ".codex" / "settings.txt").read_text(encoding="utf-8"), "v2")
            self.assertEqual((target2 / ".codex" / "settings.txt").read_text(encoding="utf-8"), "v2")
            self.assertIn("Skipping missing repo", result.stdout + result.stderr)
            data = json.loads(usage_path.read_text(encoding="utf-8"))
            self.assertIn(str(missing.resolve()), [repo["path"] for repo in data["loadouts"]["custom"]["repos"]])

    def test_update_loadout_repos_whatif_does_not_change_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loadout = root / "loadouts" / "custom"
            target = root / "target"
            (loadout / ".harness").mkdir(parents=True)
            target.mkdir()
            (loadout / ".harness" / "settings.txt").write_text("v1", encoding="utf-8")
            script, updater = copy_scripts_to_temp_root(root)

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Loadout", "custom", "-Target", str(target), "-Harness", "codex", "-Force"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            usage_path = root / "applied-repos.json"
            usage_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "loadouts": {
                            "custom": {
                                "loadout": "custom",
                                "repos": [
                                    {"path": str(target.resolve()), "harness": "codex", "lastAppliedAt": "2026-06-24T00:00:00.0000000Z"}
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (loadout / ".harness" / "settings.txt").write_text("v2", encoding="utf-8")

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(updater), "-Loadout", "custom", "-WhatIf"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((target / ".codex" / "settings.txt").read_text(encoding="utf-8"), "v1")
            self.assertIn("Planned update for repo:", result.stdout)
            self.assertIn("[WOULD CHANGE] .codex/settings.txt", result.stdout)


if __name__ == "__main__":
    unittest.main()
