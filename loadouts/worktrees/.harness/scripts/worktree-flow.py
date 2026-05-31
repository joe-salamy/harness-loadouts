#!/usr/bin/env python3
"""Run a plan -> implement -> audit -> finish harness worktree workflow."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

HARNESS_DIR = Path(Path(__file__).resolve().parent.parent.name)
if not HARNESS_DIR.name.startswith("."):
    HARNESS_DIR = Path(".harness")
DEFAULT_HARNESS = HARNESS_DIR.name.lstrip(".")
HANDOFF_DIR = HARNESS_DIR / "handoff"


class FlowError(RuntimeError):
    """A recoverable workflow error with a user-facing message."""


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    cwd: Path
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run

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
        if self.dry_run:
            return CommandResult(tuple(args), cwd, 0)

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
            )
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
        )
        if check and result.returncode != 0:
            raise FlowError(format_command_failure(result))
        return result


def format_command_failure(result: CommandResult) -> str:
    parts = [
        f"Command failed with exit code {result.returncode}: {' '.join(result.args)}",
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
    base: str
    model: str | None
    harness: str
    merge_mode: str
    keep_worktrees: bool


class HarnessWorktreeFlow:
    def __init__(self, config: FlowConfig, runner: CommandRunner) -> None:
        self.config = config
        self.runner = runner
        self.log_file: Path | None = None

    def run(self) -> None:
        repo = self.git_root(self.config.repo.resolve())
        plan = self.config.plan.resolve()
        self.validate(repo, plan)

        names = self.unique_feature_names(repo, derive_slug(plan))
        self.prepare_harness_permissions(repo / HARNESS_DIR)
        self.prepare_git_permissions(repo)
        self.start_log(repo, names.run_id)
        print(f"Feature branch: {names.branch}")
        print(f"Feature worktree: {names.worktree}")

        self.create_feature_worktree(repo, names)
        plan_in_worktree = self.ensure_plan_in_worktree(
            repo, plan, names.worktree, names.slug
        )
        self.run_implementation(names.worktree, plan_in_worktree)
        self.require_file(names.worktree / HANDOFF_DIR / "implementation-summary.md")
        self.run_audit(names.worktree, plan_in_worktree)
        self.require_file(names.worktree / HANDOFF_DIR / "audit-summary.md")
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

        self.finish(repo, names, plan_in_worktree, plan_title(plan))

    def validate(self, repo: Path, plan: Path) -> None:
        if not plan.exists():
            raise FlowError(f"Plan file does not exist: {plan}")
        self.runner.run(["git", "fetch", "--all", "--prune"], repo)
        self.runner.run(["git", "rev-parse", "--verify", self.config.base], repo)
        self.runner.run([self.config.harness, "exec", "--help"], repo)

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
                self.config.base,
            ],
            repo,
        )
        self.prepare_harness_permissions(names.worktree / HARNESS_DIR)
        self.ensure_dir(names.worktree / HANDOFF_DIR)
        self.prepare_harness_permissions(names.worktree / HARNESS_DIR)
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
- Write `{HANDOFF_DIR.as_posix()}/implementation-summary.md` with plan path, branch/worktree, changed files, behavior changes, tests run, skipped checks, assumptions, and known risks.
"""
        output = worktree / HANDOFF_DIR / "implementation-final-response.md"
        self.harness_exec(worktree, prompt, output)

    def run_audit(
        self, worktree: Path, plan_path: Path, *, post_conflict: bool = False
    ) -> None:
        summary = HANDOFF_DIR / (
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
- `{HANDOFF_DIR.as_posix()}/implementation-summary.md`
{f"- `{HANDOFF_DIR.as_posix()}/conflict-resolution-summary.md`" if post_conflict else ""}

Audit the actual diff against `{self.config.base}`. Fix confirmed issues and run relevant tests.
{audit_finish_instruction}
Write `{summary.as_posix()}` before finishing.
"""
        output = (
            worktree
            / HANDOFF_DIR
            / (
                "post-conflict-audit-final-response.md"
                if post_conflict
                else "audit-final-response.md"
            )
        )
        self.harness_exec(worktree, prompt, output)

    def harness_exec(self, cwd: Path, prompt: str, output_file: Path) -> None:
        self.ensure_dir(output_file.parent)
        args = [
            self.config.harness,
            "exec",
            "--cd",
            str(cwd),
            "--sandbox",
            "workspace-write",
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
            command=args[:-1],
        )
        result = self.runner.run(args, cwd, check=False, input_text=prompt)
        self.log_event(
            "harness_exec_finish",
            cwd=str(cwd),
            output_file=str(output_file),
            output_file_exists=output_file.exists(),
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        if result.returncode != 0:
            raise FlowError(format_command_failure(result))

    def finish(self, repo: Path, names: Names, plan_path: Path, title: str) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        integration_branch = f"integration/{names.slug}-{stamp}"
        integration_worktree = (
            repo.parent / f"{repo.name}-integrate-{names.slug}-{stamp}"
        )

        self.runner.run(["git", "fetch", "--all", "--prune"], repo)
        self.runner.run(
            [
                "git",
                "worktree",
                "add",
                str(integration_worktree),
                "-b",
                integration_branch,
                self.config.base,
            ],
            repo,
        )
        self.prepare_harness_permissions(integration_worktree / HARNESS_DIR)
        self.ensure_dir(integration_worktree / HANDOFF_DIR)
        self.prepare_harness_permissions(integration_worktree / HARNESS_DIR)
        self.prepare_git_permissions(integration_worktree)
        integration_plan = self.copy_integration_context(
            names.worktree, integration_worktree, plan_path
        )

        integrated = False
        try:
            if self.config.merge_mode == "squash":
                merge = self.runner.run(
                    ["git", "merge", "--squash", names.branch],
                    integration_worktree,
                    check=False,
                )
                if merge.returncode != 0:
                    if self.has_unmerged_paths(integration_worktree):
                        self.resolve_conflict(
                            integration_worktree, names, integration_plan
                        )
                    else:
                        raise FlowError(format_command_failure(merge))
                self.stage_integration_changes(integration_worktree)
                self.runner.run(
                    ["git", "commit", "-m", f"Harness: {title}"], integration_worktree
                )
            else:
                merge = self.runner.run(
                    ["git", "merge", "--no-ff", names.branch],
                    integration_worktree,
                    check=False,
                )
                if merge.returncode != 0:
                    if self.has_unmerged_paths(integration_worktree):
                        self.resolve_conflict(
                            integration_worktree, names, integration_plan
                        )
                    else:
                        raise FlowError(format_command_failure(merge))
                    self.stage_integration_changes(integration_worktree)
                    self.runner.run(
                        ["git", "merge", "--continue"], integration_worktree
                    )

            self.archive_handoff(
                repo, integration_worktree, names.run_id, "integration"
            )
            self.runner.run(["git", "switch", self.config.base], repo)
            self.runner.run(["git", "merge", "--ff-only", integration_branch], repo)
            integrated = True
        finally:
            if integrated and not self.config.keep_worktrees:
                self.cleanup(repo, integration_worktree, integration_branch, names)

    def resolve_conflict(
        self, integration_worktree: Path, names: Names, plan_path: Path
    ) -> None:
        context_path = integration_worktree / HANDOFF_DIR / "merge-conflict-context.md"
        self.write_text(
            context_path, self.conflict_context(integration_worktree, names, plan_path)
        )
        prompt = f"""Use the merge-conflict-resolver skill.

Resolve merge conflicts in this integration worktree.

Read:
- `{HANDOFF_DIR.as_posix()}/merge-conflict-context.md`
- `{self.rel(integration_worktree, plan_path)}`
- `{HANDOFF_DIR.as_posix()}/implementation-summary.md`
- `{HANDOFF_DIR.as_posix()}/audit-summary.md`

Preserve latest `{self.config.base}` behavior unless the approved plan explicitly supersedes it. Keep the resolution narrow, remove all conflict markers, run focused checks if possible, and write `{HANDOFF_DIR.as_posix()}/conflict-resolution-summary.md`.
Do not commit.
"""
        self.harness_exec(
            integration_worktree,
            prompt,
            integration_worktree
            / HANDOFF_DIR
            / "conflict-resolution-final-response.md",
        )
        self.require_file(
            integration_worktree / HANDOFF_DIR / "conflict-resolution-summary.md"
        )
        self.run_audit(integration_worktree, plan_path, post_conflict=True)
        self.require_file(
            integration_worktree / HANDOFF_DIR / "post-conflict-audit-summary.md"
        )

    def copy_integration_context(
        self, feature_worktree: Path, integration_worktree: Path, plan_path: Path
    ) -> Path:
        source_handoff = feature_worktree / HANDOFF_DIR
        dest_handoff = integration_worktree / HANDOFF_DIR
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
        archive_dir = repo / HARNESS_DIR / "worktree-flow" / run_id / stage
        self.ensure_dir(archive_dir)
        source = worktree / HANDOFF_DIR
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
                f":(exclude){HANDOFF_DIR.as_posix()}/**",
            ],
            worktree,
        )

    def has_unmerged_paths(self, worktree: Path) -> bool:
        result = self.runner.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            worktree,
            check=False,
        )
        return bool(result.stdout.strip())

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
        common_dir = self.git_common_dir(worktree)
        if common_dir is None or is_relative_to(common_dir, worktree):
            return []
        return [common_dir]

    def prepare_git_permissions(self, worktree: Path) -> None:
        for writable_root in self.extra_writable_roots(worktree):
            self.prepare_harness_permissions(writable_root)

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
            ["git", "merge-base", self.config.base, names.branch],
            integration_worktree,
            check=False,
        ).stdout.strip()
        base_log = ""
        feature_log = ""
        if merge_base:
            base_log = self.runner.run(
                ["git", "log", "--oneline", f"{merge_base}..{self.config.base}"],
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
- Base branch: {self.config.base}
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
        for worktree in (integration_worktree, names.worktree):
            if worktree.exists():
                self.runner.run(
                    ["git", "worktree", "remove", str(worktree)], repo, check=False
                )
        self.runner.run(["git", "branch", "-d", integration_branch], repo, check=False)
        # Squash merges do not mark the feature branch as merged, so force-delete
        # only after the integration branch has fast-forwarded successfully.
        self.runner.run(["git", "branch", "-D", names.branch], repo, check=False)

    def start_log(self, repo: Path, run_id: str) -> None:
        if self.runner.dry_run:
            return
        self.log_file = repo / HARNESS_DIR / "worktree-flow" / run_id / "workflow.jsonl"
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

    def require_file(self, path: Path) -> None:
        if not path.exists() and not self.runner.dry_run:
            raise FlowError(f"Required output file was not created: {path}")

    @staticmethod
    def rel(root: Path, path: Path) -> str:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return str(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the harness plan -> worktree -> audit -> finish workflow."
    )
    parser.add_argument("--plan", required=True, help="Approved Markdown plan file.")
    parser.add_argument(
        "--repo", default=".", help="Repository root. Defaults to current directory."
    )
    parser.add_argument(
        "--base", default="main", help="Base branch/ref. Defaults to main."
    )
    parser.add_argument("--model", help="Optional harness model override.")
    parser.add_argument(
        "--harness",
        default=DEFAULT_HARNESS,
        help=f"Harness CLI executable. Defaults to {DEFAULT_HARNESS}.",
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
        "--dry-run", action="store_true", help="Print commands without running them."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = FlowConfig(
        repo=Path(args.repo).expanduser().resolve(),
        plan=Path(args.plan).expanduser().resolve(),
        base=args.base,
        harness=args.harness,
        model=args.model,
        merge_mode=args.merge_mode,
        keep_worktrees=args.keep_worktrees,
    )
    try:
        HarnessWorktreeFlow(config, CommandRunner(args.dry_run)).run()
    except FlowError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
