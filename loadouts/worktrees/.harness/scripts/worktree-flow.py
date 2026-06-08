#!/usr/bin/env python3
"""Run a plan -> implement -> audit -> finish harness worktree workflow."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

EMPTY_SKILL_USAGE_LEDGER = {"version": 1, "scopes": {}}
MAX_LOG_OUTPUT_CHARS = 20_000
DEFAULT_BASE_CANDIDATES = ("main", "master")


def decode_subprocess_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def truncate_log_text(text: str) -> dict[str, object]:
    original_chars = len(text)
    return {
        "text": text[:MAX_LOG_OUTPUT_CHARS],
        "truncated": original_chars > MAX_LOG_OUTPUT_CHARS,
        "original_chars": original_chars,
    }


def logged_command(args: Sequence[str]) -> list[str]:
    command = list(args)
    if command and command[-1] == "-":
        command.pop()
    return command


def positive_seconds(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def infer_default_harness_dir(script_path: Path | None = None) -> Path:
    script = script_path or Path(__file__)
    parent = script.resolve().parent.parent.name
    if parent.startswith("."):
        return Path(parent)
    return Path(".harness")


def infer_default_harness(harness_dir: Path) -> str:
    name = harness_dir.name
    return name[1:] if name.startswith(".") and len(name) > 1 else name


HARNESS_DIR = infer_default_harness_dir()
DEFAULT_HARNESS = infer_default_harness(HARNESS_DIR)
HANDOFF_DIR = HARNESS_DIR / "handoff"


class FlowError(RuntimeError):
    """A recoverable workflow error with a user-facing message."""


class CommandFailureError(FlowError):
    """A command failure that carries the structured command result."""

    def __init__(self, result: "CommandResult") -> None:
        self.result = result
        super().__init__(format_command_failure(result))


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    cwd: Path
    returncode: int
    stdout: str = ""
    stderr: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int | None = None
    timed_out: bool = False


class CommandRunner:
    def __init__(
        self, dry_run: bool = False, command_timeout_seconds: float | None = None
    ) -> None:
        self.dry_run = dry_run
        self.command_timeout_seconds = command_timeout_seconds

    def run(
        self,
        args: Sequence[str],
        cwd: Path,
        *,
        check: bool = True,
        capture: bool = True,
        input_text: str | None = None,
    ) -> CommandResult:
        display = " ".join(args)
        print(f"+ ({cwd}) {display}")
        started_at = now_iso()
        start = time.perf_counter()
        if self.dry_run:
            return CommandResult(
                tuple(args),
                cwd,
                0,
                started_at=started_at,
                finished_at=now_iso(),
                duration_ms=0,
            )

        executable = shutil.which(args[0])
        if executable is None:
            raise FlowError(f"Executable not found on PATH: {args[0]}")
        resolved_args = [executable, *args[1:]]
        try:
            completed = subprocess.run(
                resolved_args,
                cwd=cwd,
                check=False,
                capture_output=capture,
                text=True,
                input=input_text,
                timeout=self.command_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            result = CommandResult(
                tuple(args),
                cwd,
                -9,
                decode_subprocess_output(exc.stdout),
                decode_subprocess_output(exc.stderr),
                started_at=started_at,
                finished_at=now_iso(),
                duration_ms=int((time.perf_counter() - start) * 1000),
                timed_out=True,
            )
            if check:
                raise CommandFailureError(result) from exc
            return result
        except OSError as exc:
            raise FlowError(
                f"Failed to run command: {display}\ncwd: {cwd}\n{exc}"
            ) from exc
        result = CommandResult(
            tuple(args),
            cwd,
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
            started_at=started_at,
            finished_at=now_iso(),
            duration_ms=int((time.perf_counter() - start) * 1000),
        )
        if check and result.returncode != 0:
            raise CommandFailureError(result)
        return result


def format_command_failure(result: CommandResult) -> str:
    status = (
        f"Command timed out: {' '.join(result.args)}"
        if result.timed_out
        else f"Command failed with exit code {result.returncode}: {' '.join(result.args)}"
    )
    parts = [
        status,
        f"cwd: {result.cwd}",
    ]
    if result.stdout.strip():
        parts.append("stdout:\n" + result.stdout.strip())
    if result.stderr.strip():
        parts.append("stderr:\n" + result.stderr.strip())
    return "\n".join(parts)


def slugify(value: str, *, max_words: int = 6, max_len: int = 60) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    words = [part for part in cleaned.split("-") if part]
    slug = "-".join(words[:max_words]) or "harness-plan"
    return slug[:max_len].strip("-") or "harness-plan"


def plan_title(plan_path: Path) -> str:
    text = plan_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return plan_path.stem


def derive_slug(plan_path: Path) -> str:
    return slugify(plan_title(plan_path))


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8", newline="\n")


@dataclass(frozen=True)
class Names:
    slug: str
    branch: str
    worktree: Path
    run_id: str


@dataclass(frozen=True)
class FlowConfig:
    repo: Path
    plan: Path
    base: str | None
    model: str | None
    harness: str
    harness_dir: Path
    merge_mode: str
    keep_worktrees: bool

    command_timeout_seconds: float | None = None


class HarnessWorktreeFlow:
    def __init__(self, config: FlowConfig, runner: CommandRunner) -> None:
        self.config = config
        self.runner = runner
        self.log_file: Path | None = None
        self._base = config.base

    @property
    def base(self) -> str:
        if self._base is None:
            raise FlowError("Base ref has not been resolved.")
        return self._base

    @property
    def harness_dir(self) -> Path:
        return self.config.harness_dir

    @property
    def handoff_dir(self) -> Path:
        return self.config.harness_dir / "handoff"

    def run(self) -> None:
        repo = self.git_root(self.config.repo.resolve())
        plan = self.config.plan.resolve()
        self.validate(repo, plan)

        names = self.unique_feature_names(repo, derive_slug(plan))
        self.prepare_harness_permissions(repo / self.harness_dir)
        self.prepare_git_permissions(repo)
        self.start_log(repo, names.run_id)
        print(f"Feature branch: {names.branch}")
        print(f"Feature worktree: {names.worktree}")

        try:
            self.create_feature_worktree(repo, names)
            plan_in_worktree = self.ensure_plan_in_worktree(
                repo, plan, names.worktree, names.slug
            )
            self.snapshot_skill_usage_baseline(names.worktree, repo)
            self.run_implementation(names.worktree, plan_in_worktree)
            self.require_file(
                names.worktree / self.handoff_dir / "implementation-summary.md"
            )
            self.require_no_tracked_handoff_artifacts(names.worktree, names.branch)
            self.require_implementation_invariants(names.worktree, names.branch)
            audit_head_before = self.head_rev(names.worktree)
            self.run_audit(names.worktree, plan_in_worktree)
            self.require_file(names.worktree / self.handoff_dir / "audit-summary.md")
            self.require_no_tracked_handoff_artifacts(names.worktree, names.branch)
            self.require_audit_invariants(
                names.worktree, names.branch, audit_head_before
            )
            archive_dir = self.archive_handoff(
                repo, names.worktree, names.run_id, "feature"
            )
            print(f"Handoff archive: {archive_dir}")

            if self.config.merge_mode == "stop":
                print("Stopped before merge by request.")
                print(f"Plan: {plan_in_worktree}")
                print(f"Worktree: {names.worktree}")
                print(f"Branch: {names.branch}")
                return

            self.require_ready_for_integration(names.worktree, names.branch)
            self.finish(repo, names, plan_in_worktree, plan_title(plan))
        except CommandFailureError as exc:
            self.log_command_result(
                "command_failure",
                exc.result,
                phase="workflow",
                step="checked_command",
            )
            raise

    def validate(self, repo: Path, plan: Path) -> None:
        if not plan.exists():
            raise FlowError(f"Plan file does not exist: {plan}")
        self.runner.run(["git", "fetch", "--all", "--prune"], repo)
        self._base = self.resolve_base(repo)
        self.runner.run([self.config.harness, "exec", "--help"], repo)

    def resolve_base(self, repo: Path) -> str:
        if self._base:
            if self.ref_exists(repo, self._base):
                return self._base
            raise FlowError(
                f"Base ref does not exist: {self._base}. Pass --base <branch> "
                "or create the branch before running the workflow."
            )

        for candidate in DEFAULT_BASE_CANDIDATES:
            if self.ref_exists(repo, candidate):
                return candidate

        current = self.current_branch(repo)
        if current:
            return current

        raise FlowError(
            "Could not infer a base branch. Pass --base <branch> explicitly."
        )

    def ref_exists(self, repo: Path, ref: str) -> bool:
        return (
            self.runner.run(
                ["git", "rev-parse", "--verify", "--quiet", ref],
                repo,
                check=False,
            ).returncode
            == 0
        )

    def current_branch(self, repo: Path) -> str:
        result = self.runner.run(
            ["git", "branch", "--show-current"],
            repo,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def git_root(self, start: Path) -> Path:
        result = self.runner.run(["git", "rev-parse", "--show-toplevel"], start)
        root = result.stdout.strip()
        return Path(root).resolve() if root else start

    def unique_feature_names(self, repo: Path, slug: str) -> Names:
        repo_name = repo.name
        parent = repo.parent
        suffix = 1
        while True:
            candidate_slug = slug if suffix == 1 else f"{slug}-{suffix}"
            branch = f"feature/{candidate_slug}"
            worktree = parent / f"{repo_name}-{candidate_slug}"
            branch_exists = self.runner.run(
                ["git", "branch", "--list", branch], repo
            ).stdout.strip()
            if not branch_exists and not worktree.exists():
                run_id = datetime.now().strftime(f"{candidate_slug}-%Y%m%d-%H%M%S")
                return Names(candidate_slug, branch, worktree, run_id)
            suffix += 1

    def create_feature_worktree(self, repo: Path, names: Names) -> None:
        self.runner.run(
            [
                "git",
                "worktree",
                "add",
                str(names.worktree),
                "-b",
                names.branch,
                self.base,
            ],
            repo,
        )
        self.prepare_harness_permissions(names.worktree / self.harness_dir)
        self.ensure_dir(names.worktree / self.handoff_dir)
        self.prepare_harness_permissions(names.worktree / self.harness_dir)
        self.prepare_git_permissions(names.worktree)

    def ensure_plan_in_worktree(
        self, repo: Path, plan: Path, worktree: Path, slug: str
    ) -> Path:
        if is_relative_to(plan, repo):
            rel = plan.relative_to(repo)
            target = worktree / rel
            if target.exists():
                return target
        else:
            rel = Path("docs") / "plans" / f"{slug}.md"
            target = worktree / rel

        self.ensure_dir(target.parent)
        self.copy_file(plan, target)
        return target

    def run_implementation(self, worktree: Path, plan_path: Path) -> None:
        prompt = f"""Use the implement-worktree skill.

Implement the approved plan in `{self.rel(worktree, plan_path)}` inside this worktree.

Requirements:
- Do not create, switch, merge, delete, or rebase worktrees.
- Keep edits scoped to the plan.
- Run focused tests or checks appropriate to the change.
- Commit the completed implementation.
- Write `{self.handoff_dir.as_posix()}/implementation-summary.md` with plan path, branch/worktree, changed files, behavior changes, tests run, skipped checks, assumptions, and known risks.
- Do not commit files under `{self.handoff_dir.as_posix()}/`; they are workflow artifacts and must remain untracked.
"""
        output = worktree / self.handoff_dir / "implementation-final-response.md"
        self.harness_exec(worktree, prompt, output)

    def run_audit(
        self, worktree: Path, plan_path: Path, *, post_conflict: bool = False
    ) -> None:
        summary = self.handoff_dir / (
            "post-conflict-audit-summary.md" if post_conflict else "audit-summary.md"
        )
        audit_finish_instruction = (
            "Do not commit. Leave all resolved merge state and audit fixes staged or unstaged for the workflow script to finalize."
            if post_conflict
            else "Commit audit fixes if changes are made."
        )
        prompt = f"""Use the audit-worktree skill.

Fresh audit pass in this worktree.

Read:
- `{self.rel(worktree, plan_path)}`
- `{self.handoff_dir.as_posix()}/implementation-summary.md`
{f"- `{self.handoff_dir.as_posix()}/conflict-resolution-summary.md`" if post_conflict else ""}

Audit the actual diff against `{self.base}`. Fix confirmed issues and run relevant tests.
{audit_finish_instruction}
Do not commit files under `{self.handoff_dir.as_posix()}/`; they are workflow artifacts and must remain untracked.
Write `{summary.as_posix()}` before finishing.
"""
        output = (
            worktree
            / self.handoff_dir
            / (
                "post-conflict-audit-final-response.md"
                if post_conflict
                else "audit-final-response.md"
            )
        )
        self.harness_exec(worktree, prompt, output)

    def harness_sandbox_mode(self) -> str:
        if os.name == "nt":
            return "danger-full-access"
        return "workspace-write"

    def harness_exec(self, cwd: Path, prompt: str, output_file: Path) -> None:
        self.ensure_dir(output_file.parent)
        args = [
            self.config.harness,
            "exec",
            "--cd",
            str(cwd),
            "--sandbox",
            self.harness_sandbox_mode(),
        ]
        for writable_root in self.extra_writable_roots(cwd):
            args.extend(["--add-dir", str(writable_root)])
        if self.config.model:
            args.extend(["--model", self.config.model])
        args.extend(["--output-last-message", str(output_file), "-"])
        self.log_event(
            "harness_exec_start",
            cwd=str(cwd),
            output_file=str(output_file),
            command=logged_command(args),
        )
        result = self.runner.run(args, cwd, check=False, input_text=prompt)
        output_fields = {
            "output_file": str(output_file),
            "output_file_exists": output_file.exists(),
        }
        self.log_command_result(
            "harness_exec_finish",
            result,
            **output_fields,
        )
        if result.returncode != 0 or result.timed_out:
            self.log_command_result(
                "harness_exec_failure",
                result,
                **output_fields,
            )
            raise FlowError(format_command_failure(result))

    def finish(self, repo: Path, names: Names, plan_path: Path, title: str) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        integration_branch = f"integration/{names.slug}-{stamp}"
        integration_worktree = (
            repo.parent / f"{repo.name}-integrate-{names.slug}-{stamp}"
        )

        self.require_no_tracked_handoff_artifacts(repo, names.branch)
        self.require_ready_for_integration(names.worktree, names.branch)
        self.runner.run(["git", "fetch", "--all", "--prune"], repo)
        self.runner.run(
            [
                "git",
                "worktree",
                "add",
                str(integration_worktree),
                "-b",
                integration_branch,
                self.base,
            ],
            repo,
        )
        self.prepare_harness_permissions(integration_worktree / self.harness_dir)
        self.ensure_dir(integration_worktree / self.handoff_dir)
        self.prepare_harness_permissions(integration_worktree / self.harness_dir)
        self.prepare_git_permissions(integration_worktree)
        integration_plan = self.copy_integration_context(
            names.worktree, integration_worktree, plan_path
        )
        feature_baseline = (
            integration_worktree / self.handoff_dir / "skill-usage-baseline.json"
        )

        integrated = False
        try:
            skill_usage_restored = False
            if self.config.merge_mode == "squash":
                merge = self.runner.run(
                    ["git", "merge", "--squash", names.branch],
                    integration_worktree,
                    check=False,
                )
                if merge.returncode != 0:
                    if merge.timed_out:
                        self.log_command_result(
                            "command_failure",
                            merge,
                            phase="finish",
                            step="squash_merge",
                        )
                        raise FlowError(format_command_failure(merge))
                    unmerged = self.unmerged_paths(integration_worktree)
                    if unmerged:
                        self.restore_integration_skill_usage_to_head(
                            integration_worktree, repo
                        )
                        skill_usage_restored = True
                    if unmerged and not self.only_skill_usage_unmerged(unmerged):
                        self.resolve_conflict(
                            integration_worktree, names, integration_plan
                        )
                    elif not unmerged:
                        self.log_command_result(
                            "command_failure",
                            merge,
                            phase="finish",
                            step="squash_merge",
                        )
                        raise FlowError(format_command_failure(merge))
            else:
                merge = self.runner.run(
                    ["git", "merge", "--no-ff", "--no-commit", names.branch],
                    integration_worktree,
                    check=False,
                )
                if merge.returncode != 0:
                    if merge.timed_out:
                        self.log_command_result(
                            "command_failure",
                            merge,
                            phase="finish",
                            step="no_ff_merge",
                        )
                        raise FlowError(format_command_failure(merge))
                    unmerged = self.unmerged_paths(integration_worktree)
                    if unmerged:
                        self.restore_integration_skill_usage_to_head(
                            integration_worktree, repo
                        )
                        skill_usage_restored = True
                    if unmerged and not self.only_skill_usage_unmerged(unmerged):
                        self.resolve_conflict(
                            integration_worktree, names, integration_plan
                        )
                    elif not unmerged:
                        self.log_command_result(
                            "command_failure",
                            merge,
                            phase="finish",
                            step="no_ff_merge",
                        )
                        raise FlowError(format_command_failure(merge))

            if not skill_usage_restored:
                self.restore_integration_skill_usage_to_head(integration_worktree, repo)
            self.consolidate_skill_usage(
                names.worktree, integration_worktree, repo, feature_baseline
            )
            self.stage_integration_changes(integration_worktree)
            self.runner.run(
                ["git", "commit", "-m", f"Harness: {title}"], integration_worktree
            )

            self.archive_handoff(
                repo, integration_worktree, names.run_id, "integration"
            )
            self.runner.run(["git", "switch", self.base], repo)
            fast_forward = self.runner.run(
                ["git", "merge", "--ff-only", integration_branch],
                repo,
                check=False,
            )
            if fast_forward.returncode != 0:
                self.log_command_result(
                    "command_failure",
                    fast_forward,
                    phase="finish",
                    step="fast_forward_merge",
                )
                raise FlowError(format_command_failure(fast_forward))
            integrated = True
        finally:
            if integrated and not self.config.keep_worktrees:
                self.cleanup(repo, integration_worktree, integration_branch, names)

    def resolve_conflict(
        self, integration_worktree: Path, names: Names, plan_path: Path
    ) -> None:
        context_path = (
            integration_worktree / self.handoff_dir / "merge-conflict-context.md"
        )
        self.write_text(
            context_path, self.conflict_context(integration_worktree, names, plan_path)
        )
        prompt = f"""Use the merge-conflict-resolver skill.

Resolve merge conflicts in this integration worktree.

Read:
- `{self.handoff_dir.as_posix()}/merge-conflict-context.md`
- `{self.rel(integration_worktree, plan_path)}`
- `{self.handoff_dir.as_posix()}/implementation-summary.md`
- `{self.handoff_dir.as_posix()}/audit-summary.md`

Preserve latest `{self.base}` behavior unless the approved plan explicitly supersedes it. Keep the resolution narrow, remove all conflict markers, run focused checks if possible, and write `{self.handoff_dir.as_posix()}/conflict-resolution-summary.md`.
Do not commit.
"""
        self.harness_exec(
            integration_worktree,
            prompt,
            integration_worktree
            / self.handoff_dir
            / "conflict-resolution-final-response.md",
        )
        self.require_file(
            integration_worktree / self.handoff_dir / "conflict-resolution-summary.md"
        )
        self.run_audit(integration_worktree, plan_path, post_conflict=True)
        self.require_file(
            integration_worktree / self.handoff_dir / "post-conflict-audit-summary.md"
        )

    def copy_integration_context(
        self, feature_worktree: Path, integration_worktree: Path, plan_path: Path
    ) -> Path:
        source_handoff = feature_worktree / self.handoff_dir
        dest_handoff = integration_worktree / self.handoff_dir
        self.ensure_dir(dest_handoff)
        if source_handoff.exists():
            for item in source_handoff.iterdir():
                if item.is_file():
                    self.copy_file(item, dest_handoff / item.name)

        try:
            rel_plan = plan_path.resolve().relative_to(feature_worktree.resolve())
        except ValueError:
            rel_plan = Path("docs") / "plans" / plan_path.name
        dest_plan = integration_worktree / rel_plan
        self.ensure_dir(dest_plan.parent)
        if plan_path.exists():
            self.copy_file(plan_path, dest_plan)
        return dest_plan

    def archive_handoff(
        self, repo: Path, worktree: Path, run_id: str, stage: str
    ) -> Path:
        archive_dir = repo / self.harness_dir / "worktree-flow" / run_id / stage
        self.ensure_dir(archive_dir)
        source = worktree / self.handoff_dir
        if source.exists():
            for item in source.iterdir():
                if item.is_file():
                    self.copy_file(item, archive_dir / item.name)
        return archive_dir

    def stage_integration_changes(self, worktree: Path) -> None:
        self.runner.run(
            [
                "git",
                "add",
                "-A",
                "--",
                ".",
                f":(exclude){self.handoff_dir.as_posix()}/**",
            ],
            worktree,
        )

    def skill_usage_script(self, worktree: Path) -> Path:
        return worktree / self.harness_dir / "scripts" / "skill-usage-manager.py"

    def skill_usage_ledger(self, repo_root: Path) -> Path:
        for harness_dir in (
            self.harness_dir.as_posix(),
            ".harness",
            ".codex",
            ".opencode",
            ".claude",
            ".omp",
            ".agents",
        ):
            candidate = repo_root / harness_dir
            if candidate.exists():
                return candidate / "skill-usage.json"
        return repo_root / ".skill-usage.json"

    def skill_usage_ledger_in_worktree(
        self, worktree: Path, reference_repo: Path
    ) -> Path:
        rel = self.skill_usage_ledger(reference_repo).relative_to(reference_repo)
        return worktree / rel

    def snapshot_skill_usage_baseline(
        self, worktree: Path, reference_repo: Path | None = None
    ) -> Path:
        baseline = worktree / self.handoff_dir / "skill-usage-baseline.json"
        ledger = (
            self.skill_usage_ledger_in_worktree(worktree, reference_repo)
            if reference_repo is not None
            else self.skill_usage_ledger(worktree)
        )
        if self.runner.dry_run:
            print(f"+ snapshot skill usage {ledger} {baseline}")
            return baseline
        self.ensure_dir(baseline.parent)
        if ledger.exists():
            self.copy_file(ledger, baseline)
        else:
            baseline.write_text(
                json.dumps(EMPTY_SKILL_USAGE_LEDGER, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        return baseline

    def restore_integration_skill_usage_to_head(
        self, integration_worktree: Path, reference_repo: Path | None = None
    ) -> None:
        ledger = (
            self.skill_usage_ledger_in_worktree(integration_worktree, reference_repo)
            if reference_repo is not None
            else self.skill_usage_ledger(integration_worktree)
        )
        rel = ledger.relative_to(integration_worktree).as_posix()
        exists_at_head = (
            self.runner.run(
                ["git", "cat-file", "-e", f"HEAD:{rel}"],
                integration_worktree,
                check=False,
            ).returncode
            == 0
        )
        if exists_at_head:
            self.runner.run(
                ["git", "checkout", "HEAD", "--", rel], integration_worktree
            )
        else:
            self.runner.run(
                ["git", "rm", "-f", "--ignore-unmatch", "--", rel],
                integration_worktree,
                check=False,
            )
            if not self.runner.dry_run and ledger.exists():
                ledger.unlink()

    def consolidate_skill_usage(
        self,
        source_worktree: Path,
        integration_worktree: Path,
        target_repo: Path,
        baseline_path: Path,
    ) -> None:
        self.runner.run(
            [
                sys.executable,
                str(self.skill_usage_script(integration_worktree)),
                "consolidate",
                "--source-ledger",
                str(self.skill_usage_ledger_in_worktree(source_worktree, target_repo)),
                "--base-ledger",
                str(baseline_path),
                "--target-ledger",
                str(
                    self.skill_usage_ledger_in_worktree(
                        integration_worktree, target_repo
                    )
                ),
                "--source-repo",
                str(source_worktree),
                "--target-repo",
                str(target_repo),
                "--target-worktree",
                str(integration_worktree),
            ],
            integration_worktree,
        )

    def has_unmerged_paths(self, worktree: Path) -> bool:
        return bool(self.unmerged_paths(worktree))

    def unmerged_paths(self, worktree: Path) -> list[str]:
        result = self.runner.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            worktree,
            check=False,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def only_skill_usage_unmerged(self, paths: Sequence[str]) -> bool:
        expected = {
            f"{harness_dir}/skill-usage.json"
            for harness_dir in (
                self.harness_dir.as_posix(),
                ".harness",
                ".codex",
                ".opencode",
                ".claude",
                ".omp",
                ".agents",
            )
        }
        return bool(paths) and all(
            path.replace("\\", "/") in expected for path in paths
        )

    def require_no_tracked_handoff_artifacts(
        self, worktree: Path, treeish: str
    ) -> None:
        result = self.runner.run(
            [
                "git",
                "ls-tree",
                "-r",
                "--name-only",
                treeish,
                "--",
                self.handoff_dir.as_posix(),
            ],
            worktree,
            check=False,
        )
        tracked = result.stdout.strip()
        if result.returncode != 0 or not tracked:
            return
        raise FlowError(
            "Workflow handoff artifacts were committed, but they must remain "
            f"untracked:\n{tracked}\nRemove them from the branch index before "
            f"merging, for example: git rm --cached -- {self.handoff_dir.as_posix()}/*"
        )

    def head_rev(self, worktree: Path) -> str:
        result = self.runner.run(["git", "rev-parse", "HEAD"], worktree)
        return result.stdout.strip()

    def commit_count_since_base(self, worktree: Path, branch: str) -> int:
        result = self.runner.run(
            ["git", "rev-list", "--count", f"{self.base}..{branch}"],
            worktree,
        )
        raw = result.stdout.strip()
        return int(raw) if raw else 0

    def require_commits_since_base(
        self, worktree: Path, branch: str, phase_name: str
    ) -> None:
        count = self.commit_count_since_base(worktree, branch)
        if count <= 0:
            raise FlowError(
                f"{phase_name} did not create any commits on {branch} after "
                f"{self.base}. Commit the completed implementation before "
                "continuing."
            )

    def require_branch_changed_since_base(self, worktree: Path, branch: str) -> None:
        result = self.runner.run(
            ["git", "diff", "--quiet", f"{self.base}...{branch}", "--", "."],
            worktree,
            check=False,
        )
        if result.returncode == 1:
            return
        if result.returncode == 0:
            raise FlowError(
                f"{branch} has no file changes compared with {self.base}. "
                "The workflow cannot integrate a no-op implementation."
            )
        raise FlowError(format_command_failure(result))

    def non_handoff_status(self, worktree: Path) -> list[str]:
        result = self.runner.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            worktree,
        )
        return [
            line
            for line in result.stdout.splitlines()
            if line.strip() and not self.status_line_is_handoff(line)
        ]

    def status_line_is_handoff(self, line: str) -> bool:
        path_text = line[3:].strip()
        paths = [part.strip() for part in path_text.split(" -> ")]
        return all(self.path_is_handoff(path) for path in paths if path)

    def path_is_handoff(self, path: str) -> bool:
        normalized = path.replace("\\", "/").strip('"')
        handoff = self.handoff_dir.as_posix().rstrip("/")
        return normalized == handoff or normalized.startswith(f"{handoff}/")

    def require_clean_except_handoff(self, worktree: Path, phase_name: str) -> None:
        status = self.non_handoff_status(worktree)
        if not status:
            return
        raise FlowError(
            f"{phase_name} left pending non-handoff changes in {worktree}:\n"
            + "\n".join(status)
        )

    def require_implementation_invariants(self, worktree: Path, branch: str) -> None:
        self.require_commits_since_base(worktree, branch, "Implementation")
        self.require_branch_changed_since_base(worktree, branch)
        self.require_clean_except_handoff(worktree, "Implementation")

    def require_audit_invariants(
        self, worktree: Path, branch: str, head_before: str
    ) -> None:
        self.require_clean_except_handoff(worktree, "Audit")
        head_after = self.head_rev(worktree)
        if head_after != head_before:
            self.require_branch_changed_since_base(worktree, branch)

    def require_ready_for_integration(self, worktree: Path, branch: str) -> None:
        self.require_no_tracked_handoff_artifacts(worktree, branch)
        self.require_clean_except_handoff(worktree, "Pre-integration")
        self.require_branch_changed_since_base(worktree, branch)

    def git_common_dir(self, worktree: Path) -> Path | None:
        result = self.runner.run(
            ["git", "rev-parse", "--git-common-dir"],
            worktree,
            check=False,
        )
        raw = result.stdout.strip()
        if result.returncode != 0 or not raw:
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = worktree / path
        return path.resolve()

    def extra_writable_roots(self, worktree: Path) -> list[Path]:
        roots: list[Path] = []
        harness_dir = worktree / self.harness_dir
        if harness_dir.exists():
            roots.append(harness_dir.resolve())

        common_dir = self.git_common_dir(worktree)
        if common_dir is not None and not is_relative_to(common_dir, worktree):
            roots.append(common_dir)
        return roots

    def prepare_git_permissions(self, worktree: Path) -> None:
        common_dir = self.git_common_dir(worktree)
        if common_dir is not None and not is_relative_to(common_dir, worktree):
            self.prepare_harness_permissions(common_dir)

    def ensure_dir(self, path: Path) -> None:
        if self.runner.dry_run:
            print(f"+ mkdir -p {path}")
            return
        ensure_dir(path)

    def copy_file(self, source: Path, dest: Path) -> None:
        if self.runner.dry_run:
            print(f"+ copy {source} {dest}")
            return
        shutil.copy2(source, dest)

    def write_text(self, path: Path, text: str) -> None:
        if self.runner.dry_run:
            print(f"+ write {path}")
            return
        write_text(path, text)

    def prepare_harness_permissions(self, harness_dir: Path) -> None:
        if self.runner.dry_run or os.name != "nt" or not harness_dir.exists():
            return
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if shell is None:
            print(
                f"Warning: could not grant sandbox write permissions for {harness_dir}: "
                "PowerShell was not found.",
                file=sys.stderr,
            )
            return
        group = os.environ.get("CODEX_SANDBOX_GROUP", "CodexSandboxUsers")
        script = r"""
$Root = $env:CODEX_PERMISSION_ROOT
$Group = $env:CODEX_PERMISSION_GROUP
$ErrorActionPreference = 'Stop'
$identity = New-Object System.Security.Principal.NTAccount($Group)
$rights = [System.Security.AccessControl.FileSystemRights]::Modify
$propagate = [System.Security.AccessControl.PropagationFlags]::None
$items = @((Get-Item -LiteralPath $Root -Force))
$items += @(Get-ChildItem -LiteralPath $Root -Force -Recurse)
foreach ($item in $items) {
    $acl = Get-Acl -LiteralPath $item.FullName
    foreach ($rule in @($acl.Access)) {
        if ($rule.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Deny) {
            [void]$acl.RemoveAccessRuleSpecific($rule)
        }
    }
    if ($item.PSIsContainer) {
        $inherit = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
    } else {
        $inherit = [System.Security.AccessControl.InheritanceFlags]::None
    }
    $allow = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $identity,
        $rights,
        $inherit,
        $propagate,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    $acl.SetAccessRule($allow)
    Set-Acl -LiteralPath $item.FullName -AclObject $acl
}
"""
        completed = subprocess.run(
            [
                shell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            check=False,
            capture_output=True,
            env={
                **os.environ,
                "CODEX_PERMISSION_ROOT": str(harness_dir),
                "CODEX_PERMISSION_GROUP": group,
            },
            text=True,
        )
        if completed.returncode != 0:
            print(
                "Warning: could not grant sandbox write permissions for "
                f"{harness_dir}: {(completed.stderr or completed.stdout).strip()}",
                file=sys.stderr,
            )

    def conflict_context(
        self, integration_worktree: Path, names: Names, plan_path: Path
    ) -> str:
        status = self.runner.run(
            ["git", "status", "--short"], integration_worktree, check=False
        ).stdout
        conflicted = self.runner.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            integration_worktree,
            check=False,
        ).stdout
        merge_base = self.runner.run(
            ["git", "merge-base", self.base, names.branch],
            integration_worktree,
            check=False,
        ).stdout.strip()
        base_log = ""
        feature_log = ""
        if merge_base:
            base_log = self.runner.run(
                ["git", "log", "--oneline", f"{merge_base}..{self.base}"],
                integration_worktree,
                check=False,
            ).stdout
            feature_log = self.runner.run(
                ["git", "log", "--oneline", f"{merge_base}..{names.branch}"],
                integration_worktree,
                check=False,
            ).stdout

        return f"""# Merge Conflict Context

## Branches
- Base branch: {self.base}
- Feature branch: {names.branch}

## Plan
- Path: {self.rel(integration_worktree, plan_path)}

## Merge base
{merge_base or "unknown"}

## Conflicted files
{conflicted.strip() or "unknown"}

## Status
```text
{status.strip()}
```

## Base commits since merge base
```text
{base_log.strip()}
```

## Feature commits since merge base
```text
{feature_log.strip()}
```

## Resolution rules
1. Latest base behavior is presumed correct unless the approved plan explicitly supersedes it.
2. Feature intent comes from the approved plan and implementation summary.
3. Preserve audited feature behavior when compatible with latest base.
4. Prefer the smallest conflict-only edit.
5. Remove all conflict markers.
"""

    def cleanup(
        self,
        repo: Path,
        integration_worktree: Path,
        integration_branch: str,
        names: Names,
    ) -> None:
        repo_root = repo.resolve()
        for worktree in (integration_worktree, names.worktree):
            self.runner.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                repo,
                check=False,
            )
            if worktree.exists():
                if worktree.resolve() == repo_root:
                    raise FlowError(
                        "Refusing to remove repository root during cleanup."
                    )
                shutil.rmtree(worktree)
        self.runner.run(["git", "worktree", "prune"], repo, check=False)
        self.runner.run(["git", "branch", "-d", integration_branch], repo, check=False)
        # Squash merges do not mark the feature branch as merged, so force-delete
        # only after the integration branch has fast-forwarded successfully.
        self.runner.run(["git", "branch", "-D", names.branch], repo, check=False)

    def start_log(self, repo: Path, run_id: str) -> None:
        if self.runner.dry_run:
            return
        self.log_file = (
            repo / self.harness_dir / "worktree-flow" / run_id / "workflow.jsonl"
        )
        ensure_dir(self.log_file.parent)
        self.log_event("workflow_log_started", log_file=str(self.log_file))

    def log_event(self, event: str, **fields: object) -> None:
        if self.log_file is None:
            return
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            **fields,
        }
        with self.log_file.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_command_result(
        self, event: str, result: CommandResult, **fields: object
    ) -> None:
        self.log_event(
            event,
            cwd=str(result.cwd),
            command=logged_command(result.args),
            returncode=result.returncode,
            timed_out=result.timed_out,
            started_at=result.started_at,
            finished_at=result.finished_at,
            duration_ms=result.duration_ms,
            stdout=truncate_log_text(result.stdout),
            stderr=truncate_log_text(result.stderr),
            **fields,
        )

    def require_file(self, path: Path) -> None:
        if not path.exists() and not self.runner.dry_run:
            raise FlowError(f"Required output file was not created: {path}")

    @staticmethod
    def rel(root: Path, path: Path) -> str:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return str(path)


def build_parser(
    *,
    default_harness: str = DEFAULT_HARNESS,
    default_harness_dir: Path = HARNESS_DIR,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the harness plan -> worktree -> audit -> finish workflow."
    )
    parser.add_argument("--plan", required=True, help="Approved Markdown plan file.")
    parser.add_argument(
        "--repo", default=".", help="Repository root. Defaults to current directory."
    )
    parser.add_argument(
        "--base",
        help=(
            "Base branch/ref. Defaults to the first existing branch among main, "
            "master, then the current branch."
        ),
    )
    parser.add_argument("--model", help="Optional harness model override.")
    parser.add_argument(
        "--harness",
        default=default_harness,
        help=f"Harness CLI executable. Defaults to {default_harness}.",
    )
    parser.add_argument(
        "--harness-dir",
        default=default_harness_dir.as_posix(),
        help=f"Harness artifact directory. Defaults to {default_harness_dir.as_posix()}.",
    )
    parser.add_argument(
        "--merge-mode", choices=["squash", "no-ff", "stop"], default="squash"
    )
    parser.add_argument(
        "--keep-worktrees",
        action="store_true",
        help="Do not remove feature/integration worktrees.",
    )
    parser.add_argument(
        "--command-timeout-seconds",
        type=positive_seconds,
        help="Optional timeout for each subprocess command.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print commands without running them."
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    default_harness: str = DEFAULT_HARNESS,
    default_harness_dir: Path = HARNESS_DIR,
) -> int:
    parser = build_parser(
        default_harness=default_harness,
        default_harness_dir=default_harness_dir,
    )
    args = parser.parse_args(argv)
    harness_dir = Path(args.harness_dir)
    config = FlowConfig(
        repo=Path(args.repo).expanduser().resolve(),
        plan=Path(args.plan).expanduser().resolve(),
        base=args.base,
        harness=args.harness,
        command_timeout_seconds=args.command_timeout_seconds,
        harness_dir=harness_dir,
        model=args.model,
        merge_mode=args.merge_mode,
        keep_worktrees=args.keep_worktrees,
    )
    try:
        HarnessWorktreeFlow(
            config,
            CommandRunner(
                args.dry_run,
                command_timeout_seconds=config.command_timeout_seconds,
            ),
        ).run()
    except FlowError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
