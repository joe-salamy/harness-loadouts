from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / ".codex" / "scripts" / "worktree-flow.py"
SPEC = importlib.util.spec_from_file_location("codex_worktree_flow", SCRIPT_PATH)
flow = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = flow
SPEC.loader.exec_module(flow)


class FakeRunner:
    def __init__(self, outputs: dict[tuple[str, ...], list[str] | str] | None = None) -> None:
        self.outputs = outputs or {}
        self.calls: list[tuple[tuple[str, ...], Path, bool]] = []
        self.dry_run = False

    def run(self, args, cwd, *, check=True, capture=True):
        key = tuple(args)
        self.calls.append((key, Path(cwd), check))
        value = self.outputs.get(key, "")
        if isinstance(value, list):
            stdout = value.pop(0) if value else ""
        else:
            stdout = value
        return flow.CommandResult(key, Path(cwd), 0, stdout, "")


class FailingFastForwardRunner(FakeRunner):
    def run(self, args, cwd, *, check=True, capture=True):
        if tuple(args[:3]) == ("git", "merge", "--ff-only"):
            result = flow.CommandResult(tuple(args), Path(cwd), 1, "", "not a fast-forward")
            if check:
                raise flow.FlowError(flow.format_command_failure(result))
            return result
        return super().run(args, cwd, check=check, capture=capture)


class CommandRunnerTests(unittest.TestCase):
    def test_run_resolves_executable_before_invoking_subprocess(self) -> None:
        completed = subprocess.CompletedProcess(
            ["C:/bin/codex.CMD", "exec", "--help"],
            0,
            "ok",
            "",
        )
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(flow.shutil, "which", return_value="C:/bin/codex.CMD") as which,
            mock.patch.object(flow.subprocess, "run", return_value=completed) as run,
        ):
            result = flow.CommandRunner().run(["codex", "exec", "--help"], Path(temp))

        which.assert_called_once_with("codex")
        run.assert_called_once()
        self.assertEqual(
            run.call_args.args[0],
            ["C:/bin/codex.CMD", "exec", "--help"],
        )
        self.assertEqual(result.args, ("codex", "exec", "--help"))
        self.assertEqual(result.stdout, "ok")

    def test_run_reports_missing_executable_as_flow_error(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(flow.shutil, "which", return_value=None),
            mock.patch.object(flow.subprocess, "run") as run,
            self.assertRaisesRegex(flow.FlowError, "Executable not found on PATH: codex"),
        ):
            flow.CommandRunner().run(["codex", "exec", "--help"], Path(temp))

        run.assert_not_called()

    def test_run_reports_launch_oserror_as_flow_error(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(flow.shutil, "which", return_value="C:/bin/codex.CMD"),
            mock.patch.object(
                flow.subprocess,
                "run",
                side_effect=FileNotFoundError("missing shim target"),
            ),
            self.assertRaisesRegex(flow.FlowError, "Failed to run command: codex exec --help"),
        ):
            flow.CommandRunner().run(["codex", "exec", "--help"], Path(temp))


class HarnessWorktreeFlowTests(unittest.TestCase):
    def test_slug_uses_first_h1(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            plan = Path(temp) / "plan.md"
            plan.write_text("# Add Better Audit Flow!\n\nBody", encoding="utf-8")
            self.assertEqual(flow.derive_slug(plan), "add-better-audit-flow")

    def test_slug_falls_back_to_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            plan = Path(temp) / "My Plan File.md"
            plan.write_text("No heading", encoding="utf-8")
            self.assertEqual(flow.derive_slug(plan), "my-plan-file")

    def test_unique_names_skip_existing_branch_and_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            (Path(temp) / "repo-example").mkdir()
            runner = FakeRunner(
                {
                    ("git", "branch", "--list", "feature/example"): "feature/example\n",
                    ("git", "branch", "--list", "feature/example-2"): "",
                }
            )
            config = self.config(repo, repo / "plan.md")
            names = flow.HarnessWorktreeFlow(config, runner).unique_feature_names(repo, "example")
            self.assertEqual(names.branch, "feature/example-2")
            self.assertEqual(names.worktree.name, "repo-example-2")

    def test_plan_inside_repo_uses_same_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            plan = repo / "docs" / "plans" / "p.md"
            target = worktree / "docs" / "plans" / "p.md"
            plan.parent.mkdir(parents=True)
            target.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            target.write_text("# Plan", encoding="utf-8")
            actual = flow.HarnessWorktreeFlow(self.config(repo, plan), FakeRunner()).ensure_plan_in_worktree(repo, plan, worktree, "plan")
            self.assertEqual(actual, target)

    def test_plan_outside_repo_is_copied(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            plan = Path(temp) / "external.md"
            repo.mkdir()
            worktree.mkdir()
            plan.write_text("# External", encoding="utf-8")
            actual = flow.HarnessWorktreeFlow(self.config(repo, plan), FakeRunner()).ensure_plan_in_worktree(repo, plan, worktree, "external")
            self.assertEqual(actual, worktree / "docs" / "plans" / "external.md")
            self.assertEqual(actual.read_text(encoding="utf-8"), "# External")

    def test_harness_command_includes_model_and_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            plan = repo / "plan.md"
            config = self.config(repo, plan, model="gpt-5")
            runner = FakeRunner()
            flow.HarnessWorktreeFlow(config, runner).harness_exec(repo, "Prompt", repo / "out.md")
            args = runner.calls[0][0]
            self.assertEqual(args[:2], ("codex", "exec"))
            self.assertIn("--model", args)
            self.assertIn("gpt-5", args)
            self.assertIn("--output-last-message", args)
            self.assertEqual(args[-1], "Prompt")

    def test_stop_merge_mode_does_not_finish(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-plan"
            plan = repo / "docs" / "plans" / "plan.md"
            repo.mkdir()
            (worktree / "docs" / "plans").mkdir(parents=True)
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            (worktree / "docs" / "plans" / "plan.md").write_text("# Plan", encoding="utf-8")
            handoff = worktree / ".codex" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "implementation-summary.md").write_text("impl", encoding="utf-8")
            (handoff / "audit-summary.md").write_text("audit", encoding="utf-8")

            runner = FakeRunner(
                {
                    ("git", "branch", "--list", "feature/plan"): "",
                }
            )
            config = self.config(repo, plan, merge_mode="stop")
            subject = flow.HarnessWorktreeFlow(config, runner)
            subject.create_feature_worktree = lambda _repo, _names: None
            subject.run_implementation = lambda _worktree, _plan: None
            subject.run_audit = lambda _worktree, _plan: None
            subject.unique_feature_names = lambda _repo, _slug: flow.Names("plan", "feature/plan", worktree, "plan-run")
            subject.validate = lambda _repo, _plan: None
            subject.finish = lambda *_args: (_ for _ in ()).throw(AssertionError("finish should not run"))

            subject.run()

    def test_conflict_context_contains_files_and_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            plan = repo / "plan.md"
            runner = FakeRunner(
                {
                    ("git", "status", "--short"): "UU app.py\n",
                    ("git", "diff", "--name-only", "--diff-filter=U"): "app.py\n",
                    ("git", "merge-base", "main", "feature/plan"): "abc123\n",
                    ("git", "log", "--oneline", "abc123..main"): "base commit\n",
                    ("git", "log", "--oneline", "abc123..feature/plan"): "feature commit\n",
                }
            )
            text = flow.HarnessWorktreeFlow(self.config(repo, plan), runner).conflict_context(
                repo,
                flow.Names("plan", "feature/plan", repo, "plan-run"),
                plan,
            )
            self.assertIn("app.py", text)
            self.assertIn("Latest base behavior is presumed correct", text)
            self.assertIn("feature commit", text)

    def test_post_conflict_audit_prompt_does_not_allow_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            runner = FakeRunner()
            flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner).run_audit(
                repo,
                repo / "plan.md",
                post_conflict=True,
            )
            prompt = runner.calls[0][0][-1]
            self.assertIn("Do not commit", prompt)
            self.assertNotIn("commit audit fixes if changes are made", prompt.lower())

    def test_finish_does_not_cleanup_if_primary_merge_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            feature = Path(temp) / "repo-plan"
            plan = feature / "docs" / "plans" / "plan.md"
            repo.mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            handoff = feature / ".codex" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "implementation-summary.md").write_text("impl", encoding="utf-8")
            (handoff / "audit-summary.md").write_text("audit", encoding="utf-8")

            subject = flow.HarnessWorktreeFlow(self.config(repo, plan), FailingFastForwardRunner())
            subject.cleanup = lambda *_args: (_ for _ in ()).throw(AssertionError("cleanup should not run"))
            subject.archive_handoff = lambda *_args: repo / ".codex" / "archive"

            with self.assertRaises(flow.FlowError):
                subject.finish(
                    repo,
                    flow.Names("plan", "feature/plan", feature, "plan-run"),
                    plan,
                    "Plan",
                )

    def test_local_git_worktree_and_squash_merge(self) -> None:
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "file.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)

            feature = Path(temp) / "repo-feature"
            subprocess.run(["git", "worktree", "add", str(feature), "-b", "feature/test", "main"], cwd=repo, check=True, capture_output=True)
            (feature / "file.txt").write_text("feature\n", encoding="utf-8")
            subprocess.run(["git", "add", "file.txt"], cwd=feature, check=True)
            subprocess.run(["git", "commit", "-m", "feature"], cwd=feature, check=True, capture_output=True)

            integration = Path(temp) / "repo-integration"
            subprocess.run(["git", "worktree", "add", str(integration), "-b", "integration/test", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "merge", "--squash", "feature/test"], cwd=integration, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Harness: test"], cwd=integration, check=True, capture_output=True)
            subprocess.run(["git", "switch", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "merge", "--ff-only", "integration/test"], cwd=repo, check=True, capture_output=True)

            self.assertEqual((repo / "file.txt").read_text(encoding="utf-8"), "feature\n")

    def config(
        self,
        repo: Path,
        plan: Path,
        *,
        model: str | None = None,
        merge_mode: str = "squash",
    ):
        return flow.FlowConfig(
            repo=repo,
            plan=plan,
            base="main",
            model=model,
            harness="codex",
            merge_mode=merge_mode,
            keep_worktrees=False,
            yes=True,
        )


if __name__ == "__main__":
    unittest.main()
