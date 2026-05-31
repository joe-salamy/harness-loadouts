from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "harness-init.ps1"


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

            script = root / "harness-init.ps1"
            script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
