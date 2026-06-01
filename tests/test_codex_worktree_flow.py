from __future__ import annotations

import importlib.util
import json
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
    def __init__(
        self,
        outputs: dict[
            tuple[str, ...], flow.CommandResult | list[str] | str
        ] | None = None,
        *,
        dry_run: bool = False,
    ) -> None:
        self.outputs = outputs or {}
        self.calls: list[tuple[tuple[str, ...], Path, bool]] = []
        self.inputs: list[str | None] = []
        self.dry_run = dry_run

    def run(self, args, cwd, *, check=True, capture=True, input_text=None):
        key = tuple(args)
        self.calls.append((key, Path(cwd), check))
        self.inputs.append(input_text)
        value = self.outputs.get(key, "")
        if isinstance(value, flow.CommandResult):
            return value
        if isinstance(value, list):
            stdout = value.pop(0) if value else ""
        else:
            stdout = value
        return flow.CommandResult(key, Path(cwd), 0, stdout, "")


class FailingFastForwardRunner(FakeRunner):
    def run(self, args, cwd, *, check=True, capture=True, input_text=None):
        if tuple(args[:3]) == ("git", "merge", "--ff-only"):
            result = flow.CommandResult(tuple(args), Path(cwd), 1, "", "not a fast-forward")
            if check:
                raise flow.FlowError(flow.format_command_failure(result))
            return result
        return super().run(args, cwd, check=check, capture=capture, input_text=input_text)


class FailingSquashMergeRunner(FakeRunner):
    def __init__(self, *, unmerged_paths: str) -> None:
        super().__init__()
        self.unmerged_paths = unmerged_paths

    def run(self, args, cwd, *, check=True, capture=True, input_text=None):
        key = tuple(args)
        if key[:3] == ("git", "merge", "--squash"):
            self.calls.append((key, Path(cwd), check))
            return flow.CommandResult(key, Path(cwd), 1, "", "merge failed")
        if key == ("git", "diff", "--name-only", "--diff-filter=U"):
            self.calls.append((key, Path(cwd), check))
            return flow.CommandResult(key, Path(cwd), 0, self.unmerged_paths, "")
        return super().run(args, cwd, check=check, capture=capture, input_text=input_text)


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

    def test_dry_run_plan_copy_does_not_mutate_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            plan = Path(temp) / "external.md"
            repo.mkdir()
            worktree.mkdir()
            plan.write_text("# External", encoding="utf-8")

            actual = flow.HarnessWorktreeFlow(
                self.config(repo, plan), FakeRunner(dry_run=True)
            ).ensure_plan_in_worktree(repo, plan, worktree, "external")

            self.assertEqual(actual, worktree / "docs" / "plans" / "external.md")
            self.assertFalse(actual.exists())

    def test_dry_run_archive_handoff_does_not_mutate_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            source = worktree / ".codex" / "handoff"
            repo.mkdir()
            source.mkdir(parents=True)
            (source / "implementation-summary.md").write_text("impl", encoding="utf-8")

            archive = flow.HarnessWorktreeFlow(
                self.config(repo, repo / "plan.md"), FakeRunner(dry_run=True)
            ).archive_handoff(repo, worktree, "plan-run", "feature")

            self.assertFalse(archive.exists())

    def test_prepare_harness_permissions_grants_sandbox_group_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            harness_dir = Path(temp) / ".codex"
            harness_dir.mkdir()
            completed = subprocess.CompletedProcess(["pwsh"], 0, "", "")
            subject = flow.HarnessWorktreeFlow(
                self.config(Path(temp), Path(temp) / "plan.md"), FakeRunner()
            )

            with (
                mock.patch.object(flow.os, "name", "nt"),
                mock.patch.object(flow.shutil, "which", return_value="C:/PowerShell/pwsh.exe"),
                mock.patch.object(flow.subprocess, "run", return_value=completed) as run,
            ):
                subject.prepare_harness_permissions(harness_dir)

            args = run.call_args.args[0]
            kwargs = run.call_args.kwargs
            self.assertEqual(args[0], "C:/PowerShell/pwsh.exe")
            self.assertEqual(kwargs["env"]["CODEX_PERMISSION_ROOT"], str(harness_dir))
            self.assertEqual(kwargs["env"]["CODEX_PERMISSION_GROUP"], "CodexSandboxUsers")
            self.assertIn("RemoveAccessRuleSpecific", args[4])

    def test_prepare_git_permissions_grants_external_common_git_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            common_git = repo / ".git"
            repo.mkdir()
            worktree.mkdir()
            common_git.mkdir()
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, repo / "plan.md"),
                FakeRunner(
                    {
                        ("git", "rev-parse", "--git-common-dir"): str(common_git),
                    }
                ),
            )
            prepared: list[Path] = []
            subject.prepare_harness_permissions = prepared.append

            subject.prepare_git_permissions(worktree)

            self.assertEqual(prepared, [common_git.resolve()])

    def test_extra_writable_roots_include_harness_and_external_git_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            common_git = repo / ".git"
            harness_dir = worktree / ".codex"
            repo.mkdir()
            worktree.mkdir()
            common_git.mkdir()
            harness_dir.mkdir()
            runner = FakeRunner(
                {
                    ("git", "rev-parse", "--git-common-dir"): str(common_git),
                }
            )
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            roots = subject.extra_writable_roots(worktree)

            self.assertEqual(roots, [harness_dir.resolve(), common_git.resolve()])


    def test_harness_exec_adds_harness_and_common_git_dirs_as_writable_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            common_git = repo / ".git"
            harness_dir = worktree / ".codex"
            repo.mkdir()
            worktree.mkdir()
            common_git.mkdir()
            harness_dir.mkdir()
            runner = FakeRunner(
                {
                    ("git", "rev-parse", "--git-common-dir"): str(common_git),
                }
            )
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            subject.harness_exec(
                worktree,
                "Prompt",
                worktree / ".codex" / "handoff" / "implementation-final-response.md",
            )

            args = runner.calls[-1][0]
            writable_roots = [
                args[index + 1]
                for index, value in enumerate(args)
                if value == "--add-dir"
            ]
            self.assertEqual(
                writable_roots,
                [str(harness_dir.resolve()), str(common_git.resolve())],
            )

    def test_harness_exec_uses_full_access_sandbox_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            runner = FakeRunner()
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            with mock.patch.object(flow.os, "name", "nt"):
                subject.harness_exec(repo, "Prompt", repo / "out.md")

            args = runner.calls[-1][0]
            sandbox_index = args.index("--sandbox")
            self.assertEqual(args[sandbox_index + 1], "danger-full-access")

    def test_harness_exec_uses_workspace_write_sandbox_off_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            runner = FakeRunner()
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            with mock.patch.object(flow.os, "name", "posix"):
                subject.harness_exec(repo, "Prompt", repo / "out.md")

            args = runner.calls[-1][0]
            sandbox_index = args.index("--sandbox")
            self.assertEqual(args[sandbox_index + 1], "workspace-write")

    def test_run_prepares_primary_repo_permissions_before_logging(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-plan"
            plan = repo / "docs" / "plans" / "plan.md"
            repo.mkdir()
            (repo / ".codex").mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            (worktree / "docs" / "plans").mkdir(parents=True)
            (worktree / "docs" / "plans" / "plan.md").write_text("# Plan", encoding="utf-8")
            handoff = worktree / ".codex" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "implementation-summary.md").write_text("impl", encoding="utf-8")
            (handoff / "audit-summary.md").write_text("audit", encoding="utf-8")
            runner = FakeRunner(
                {
                    ("git", "branch", "--list", "feature/plan"): "",
                    ("git", "rev-parse", "--git-common-dir"): ".git",
                }
            )
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, plan, merge_mode="stop"), runner
            )
            prepared: list[Path] = []
            subject.prepare_harness_permissions = prepared.append
            subject.create_feature_worktree = lambda _repo, _names: None
            subject.run_implementation = lambda _worktree, _plan: None
            subject.run_audit = lambda _worktree, _plan: None
            subject.unique_feature_names = lambda _repo, _slug: flow.Names(
                "plan", "feature/plan", worktree, "plan-run"
            )
            subject.validate = lambda _repo, _plan: None
            subject.finish = lambda *_args: (_ for _ in ()).throw(
                AssertionError("finish should not run")
            )

            subject.run()

            self.assertEqual(prepared[0], repo / ".codex")

    def test_stage_integration_changes_excludes_handoff_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            runner = FakeRunner()
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            subject.stage_integration_changes(repo)

            self.assertEqual(
                runner.calls[0][0],
                (
                    "git",
                    "add",
                    "-A",
                    "--",
                    ".",
                    ":(exclude).codex/handoff/**",
                ),
            )


    def test_tracked_handoff_artifacts_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            runner = FakeRunner(
                {
                    (
                        "git",
                        "ls-tree",
                        "-r",
                        "--name-only",
                        "feature/plan",
                        "--",
                        ".codex/handoff",
                    ): ".codex/handoff/audit-summary.md\n",
                }
            )
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            with self.assertRaisesRegex(flow.FlowError, "Workflow handoff artifacts"):
                subject.require_no_tracked_handoff_artifacts(repo, "feature/plan")

    def test_handoff_prompts_forbid_committing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            runner = FakeRunner()
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            subject.run_implementation(repo, repo / "plan.md")
            subject.run_audit(repo, repo / "plan.md")

            prompts = [value for value in runner.inputs if value is not None]
            self.assertIn("Do not commit files under `.codex/handoff/`", prompts[-2])
            self.assertIn("Do not commit files under `.codex/handoff/`", prompts[-1])

    def test_snapshot_skill_usage_baseline_writes_empty_ledger_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            worktree = Path(temp) / "repo-feature"
            (worktree / ".codex").mkdir(parents=True)
            subject = flow.HarnessWorktreeFlow(
                self.config(worktree, worktree / "plan.md"), FakeRunner()
            )

            baseline = subject.snapshot_skill_usage_baseline(worktree)

            self.assertEqual(baseline, worktree / ".codex" / "handoff" / "skill-usage-baseline.json")
            self.assertEqual(
                json.loads(baseline.read_text(encoding="utf-8")),
                {"version": 1, "scopes": {}},
            )

    def test_finish_restores_and_consolidates_before_staging_in_squash_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            feature = Path(temp) / "repo-plan"
            plan = feature / "docs" / "plans" / "plan.md"
            repo.mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            handoff = feature / ".codex" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "skill-usage-baseline.json").write_text("{}", encoding="utf-8")
            subject = flow.HarnessWorktreeFlow(self.config(repo, plan), FakeRunner())
            subject.prepare_harness_permissions = lambda _path: None
            events: list[str] = []
            subject.restore_integration_skill_usage_to_head = lambda _worktree: events.append("restore")
            subject.consolidate_skill_usage = lambda *_args: events.append("consolidate")
            subject.stage_integration_changes = lambda _worktree: events.append("stage")
            subject.archive_handoff = lambda *_args: repo / ".codex" / "archive"

            subject.finish(
                repo,
                flow.Names("plan", "feature/plan", feature, "plan-run"),
                plan,
                "Plan",
            )

            self.assertEqual(events, ["restore", "consolidate", "stage"])


    def test_consolidate_skill_usage_targets_primary_repo_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            feature = root / "repo-plan"
            integration = root / "repo-integrate"
            repo = root / "repo"
            baseline = feature / ".codex" / "handoff" / "skill-usage-baseline.json"
            runner = FakeRunner()

            flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner).consolidate_skill_usage(
                feature,
                integration,
                repo,
                baseline,
            )

            args = runner.calls[-1][0]
            self.assertIn("--target-repo", args)
            self.assertEqual(args[args.index("--target-repo") + 1], str(repo))
            self.assertIn("--target-worktree", args)
            self.assertEqual(args[args.index("--target-worktree") + 1], str(integration))

    def test_no_ff_merge_uses_no_commit_and_workflow_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            feature = Path(temp) / "repo-plan"
            plan = feature / "docs" / "plans" / "plan.md"
            repo.mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            (feature / ".codex" / "handoff").mkdir(parents=True)
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, plan, merge_mode="no-ff"), FakeRunner()
            )
            subject.prepare_harness_permissions = lambda _path: None
            subject.restore_integration_skill_usage_to_head = lambda _worktree: None
            subject.consolidate_skill_usage = lambda *_args: None
            subject.stage_integration_changes = lambda _worktree: None
            subject.archive_handoff = lambda *_args: repo / ".codex" / "archive"

            subject.finish(
                repo,
                flow.Names("plan", "feature/plan", feature, "plan-run"),
                plan,
                "Plan",
            )

            calls = [call[0] for call in subject.runner.calls]
            self.assertIn(("git", "merge", "--no-ff", "--no-commit", "feature/plan"), calls)
            self.assertIn(("git", "commit", "-m", "Harness: Plan"), calls)
            self.assertNotIn(("git", "merge", "--continue"), calls)

    def test_restore_skill_usage_to_head_restores_tracked_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            (repo / ".codex").mkdir(parents=True)
            runner = FakeRunner(
                {
                    ("git", "cat-file", "-e", "HEAD:.codex/skill-usage.json"): flow.CommandResult(
                        ("git", "cat-file", "-e", "HEAD:.codex/skill-usage.json"),
                        repo,
                        0,
                    )
                }
            )
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            subject.restore_integration_skill_usage_to_head(repo)

            calls = [call[0] for call in runner.calls]
            self.assertIn(("git", "checkout", "HEAD", "--", ".codex/skill-usage.json"), calls)

    def test_only_skill_usage_conflict_skips_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            feature = Path(temp) / "repo-plan"
            plan = feature / "docs" / "plans" / "plan.md"
            repo.mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            (feature / ".codex" / "handoff").mkdir(parents=True)
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, plan),
                FailingSquashMergeRunner(unmerged_paths=".codex/skill-usage.json\n"),
            )
            subject.prepare_harness_permissions = lambda _path: None
            subject.resolve_conflict = lambda *_args: (_ for _ in ()).throw(
                AssertionError("resolver should not run for usage-only conflicts")
            )
            subject.restore_integration_skill_usage_to_head = lambda _worktree: None
            subject.consolidate_skill_usage = lambda *_args: None
            subject.stage_integration_changes = lambda _worktree: None
            subject.archive_handoff = lambda *_args: repo / ".codex" / "archive"

            subject.finish(
                repo,
                flow.Names("plan", "feature/plan", feature, "plan-run"),
                plan,
                "Plan",
            )

    def test_conflict_restores_skill_usage_before_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            feature = Path(temp) / "repo-plan"
            plan = feature / "docs" / "plans" / "plan.md"
            repo.mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            (feature / ".codex" / "handoff").mkdir(parents=True)
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, plan),
                FailingSquashMergeRunner(unmerged_paths="app.py\n"),
            )
            subject.prepare_harness_permissions = lambda _path: None
            events: list[str] = []
            subject.restore_integration_skill_usage_to_head = lambda _worktree: events.append("restore")
            subject.resolve_conflict = lambda *_args: events.append("resolve")
            subject.consolidate_skill_usage = lambda *_args: events.append("consolidate")
            subject.stage_integration_changes = lambda _worktree: events.append("stage")
            subject.archive_handoff = lambda *_args: repo / ".codex" / "archive"

            subject.finish(
                repo,
                flow.Names("plan", "feature/plan", feature, "plan-run"),
                plan,
                "Plan",
            )

            self.assertEqual(events, ["restore", "resolve", "consolidate", "stage"])

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
            args = runner.calls[-1][0]
            self.assertEqual(args[:2], ("codex", "exec"))
            self.assertIn("--model", args)
            self.assertIn("gpt-5", args)
            self.assertEqual(args[-1], "-")
            self.assertEqual(runner.inputs[-1], "Prompt")
            self.assertIn("--output-last-message", args)

    def test_harness_exec_logs_jsonl_to_main_repo_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            repo.mkdir()
            worktree.mkdir()
            output_file = worktree / ".codex" / "handoff" / "implementation-final-response.md"
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), FakeRunner())

            subject.start_log(repo, "plan-run")
            subject.harness_exec(worktree, "Secret prompt", output_file)

            log_file = repo / ".codex" / "worktree-flow" / "plan-run" / "workflow.jsonl"
            records = [
                json.loads(line)
                for line in log_file.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(log_file, subject.log_file)
            self.assertEqual(
                [record["event"] for record in records],
                [
                    "workflow_log_started",
                    "harness_exec_start",
                    "harness_exec_finish",
                ],
            )
            self.assertEqual(records[1]["cwd"], str(worktree))
            self.assertNotIn("Secret prompt", records[1]["command"])
            self.assertFalse(records[2]["output_file_exists"])
            self.assertEqual(records[2]["returncode"], 0)

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
            prompt = runner.inputs[-1]
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
            subject.prepare_harness_permissions = lambda _path: None

            with self.assertRaises(flow.FlowError):
                subject.finish(
                    repo,
                    flow.Names("plan", "feature/plan", feature, "plan-run"),
                    plan,
                    "Plan",
                )

    def test_non_conflict_squash_merge_failure_does_not_run_resolver(self) -> None:
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
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, plan), FailingSquashMergeRunner(unmerged_paths="")
            )
            subject.prepare_harness_permissions = lambda _path: None
            subject.resolve_conflict = lambda *_args: (_ for _ in ()).throw(
                AssertionError("resolver should not run")
            )

            with self.assertRaisesRegex(flow.FlowError, "merge --squash"):
                subject.finish(
                    repo,
                    flow.Names("plan", "feature/plan", feature, "plan-run"),
                    plan,
                    "Plan",
                )

    def test_conflict_squash_merge_failure_runs_resolver(self) -> None:
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
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, plan), FailingSquashMergeRunner(unmerged_paths="app.py\n")
            )
            resolved = []
            subject.prepare_harness_permissions = lambda _path: None
            subject.resolve_conflict = lambda *_args: resolved.append(True)
            subject.archive_handoff = lambda *_args: repo / ".codex" / "archive"

            subject.finish(
                repo,
                flow.Names("plan", "feature/plan", feature, "plan-run"),
                plan,
                "Plan",
            )

            self.assertEqual(resolved, [True])

    def test_parser_rejects_removed_yes_option(self) -> None:
        with self.assertRaises(SystemExit):
            flow.build_parser().parse_args(["--plan", "plan.md", "--yes"])

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
            (integration / ".codex" / "handoff").mkdir(parents=True)
            (integration / ".codex" / "handoff" / "implementation-summary.md").write_text("impl", encoding="utf-8")
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, repo / "plan.md"), flow.CommandRunner()
            )
            subject.stage_integration_changes(integration)
            subprocess.run(["git", "commit", "-m", "Harness: test"], cwd=integration, check=True, capture_output=True)
            subprocess.run(["git", "switch", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "merge", "--ff-only", "integration/test"], cwd=repo, check=True, capture_output=True)

            committed = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            self.assertEqual((repo / "file.txt").read_text(encoding="utf-8"), "feature\n")
            self.assertIn("file.txt", committed)
            self.assertNotIn(".codex/handoff/implementation-summary.md", committed)

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
        )

if __name__ == "__main__":
    unittest.main()
