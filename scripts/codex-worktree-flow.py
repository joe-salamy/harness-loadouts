#!/usr/bin/env python3
"""Run a plan -> implement -> audit -> finish Codex worktree workflow."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence


HANDOFF_DIR = Path(".codex") / "handoff"


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
    ) -> CommandResult:
        display = " ".join(args)
        print(f"+ ({cwd}) {display}")
        if self.dry_run:
            return CommandResult(tuple(args), cwd, 0)

        completed = subprocess.run(
            list(args),
            cwd=cwd,
            check=False,
            capture_output=capture,
            text=True,
        )
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
    slug = "-".join(words[:max_words]) or "codex-plan"
    return slug[:max_len].strip("-") or "codex-plan"


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
    merge_mode: str
    keep_worktrees: bool
    yes: bool


class CodexWorktreeFlow:
    def __init__(self, config: FlowConfig, runner: CommandRunner) -> None:
        self.config = config
        self.runner = runner

    def run(self) -> None:
        repo = self.git_root(self.config.repo.resolve())
        plan = self.config.plan.resolve()
        self.validate(repo, plan)

        names = self.unique_feature_names(repo, derive_slug(plan))
        print(f"Feature branch: {names.branch}")
        print(f"Feature worktree: {names.worktree}")

        self.create_feature_worktree(repo, names)
        plan_in_worktree = self.ensure_plan_in_worktree(repo, plan, names.worktree, names.slug)
        self.run_implementation(names.worktree, plan_in_worktree)
        self.require_file(names.worktree / HANDOFF_DIR / "implementation-summary.md")
        self.run_audit(names.worktree, plan_in_worktree)
        self.require_file(names.worktree / HANDOFF_DIR / "audit-summary.md")
        archive_dir = self.archive_handoff(repo, names.worktree, names.run_id, "feature")
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
        self.runner.run(["codex", "exec", "--help"], repo)

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
            branch_exists = self.runner.run(["git", "branch", "--list", branch], repo).stdout.strip()
            if not branch_exists and not worktree.exists():
                run_id = datetime.now().strftime(f"{candidate_slug}-%Y%m%d-%H%M%S")
                return Names(candidate_slug, branch, worktree, run_id)
            suffix += 1

    def create_feature_worktree(self, repo: Path, names: Names) -> None:
        self.runner.run(
            ["git", "worktree", "add", str(names.worktree), "-b", names.branch, self.config.base],
            repo,
        )
        ensure_dir(names.worktree / HANDOFF_DIR)

    def ensure_plan_in_worktree(self, repo: Path, plan: Path, worktree: Path, slug: str) -> Path:
        if is_relative_to(plan, repo):
            rel = plan.relative_to(repo)
            target = worktree / rel
            if target.exists():
                return target
        else:
            rel = Path("docs") / "plans" / f"{slug}.md"
            target = worktree / rel

        ensure_dir(target.parent)
        shutil.copy2(plan, target)
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
        self.codex_exec(worktree, prompt, output)

    def run_audit(self, worktree: Path, plan_path: Path, *, post_conflict: bool = False) -> None:
        summary = HANDOFF_DIR / ("post-conflict-audit-summary.md" if post_conflict else "audit-summary.md")
        prompt = f"""Use the audit-worktree skill.

Fresh audit pass in this worktree.

Read:
- `{self.rel(worktree, plan_path)}`
- `{HANDOFF_DIR.as_posix()}/implementation-summary.md`
{f"- `{HANDOFF_DIR.as_posix()}/conflict-resolution-summary.md`" if post_conflict else ""}

Audit the actual diff against `{self.config.base}`. Fix confirmed issues, run relevant tests, and commit audit fixes if changes are made.
Write `{summary.as_posix()}` before finishing.
"""
        output = worktree / HANDOFF_DIR / ("post-conflict-audit-final-response.md" if post_conflict else "audit-final-response.md")
        self.codex_exec(worktree, prompt, output)

    def codex_exec(self, cwd: Path, prompt: str, output_file: Path) -> None:
        ensure_dir(output_file.parent)
        args = ["codex", "exec", "--cd", str(cwd), "--sandbox", "workspace-write"]
        if self.config.model:
            args.extend(["--model", self.config.model])
        args.extend(["--output-last-message", str(output_file), prompt])
        self.runner.run(args, cwd)

    def finish(self, repo: Path, names: Names, plan_path: Path, title: str) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        integration_branch = f"integration/{names.slug}-{stamp}"
        integration_worktree = repo.parent / f"{repo.name}-integrate-{names.slug}-{stamp}"

        self.runner.run(["git", "fetch", "--all", "--prune"], repo)
        self.runner.run(
            ["git", "worktree", "add", str(integration_worktree), "-b", integration_branch, self.config.base],
            repo,
        )
        ensure_dir(integration_worktree / HANDOFF_DIR)
        integration_plan = self.copy_integration_context(names.worktree, integration_worktree, plan_path)

        try:
            if self.config.merge_mode == "squash":
                merge = self.runner.run(["git", "merge", "--squash", names.branch], integration_worktree, check=False)
                if merge.returncode != 0:
                    self.resolve_conflict(integration_worktree, names, integration_plan)
                self.runner.run(["git", "add", "-A"], integration_worktree)
                self.runner.run(["git", "commit", "-m", f"Codex: {title}"], integration_worktree)
            else:
                merge = self.runner.run(["git", "merge", "--no-ff", names.branch], integration_worktree, check=False)
                if merge.returncode != 0:
                    self.resolve_conflict(integration_worktree, names, integration_plan)
                    self.runner.run(["git", "add", "-A"], integration_worktree)
                    self.runner.run(["git", "merge", "--continue"], integration_worktree)

            self.archive_handoff(repo, integration_worktree, names.run_id, "integration")
            self.runner.run(["git", "switch", self.config.base], repo)
            self.runner.run(["git", "merge", "--ff-only", integration_branch], repo)
        finally:
            if not self.config.keep_worktrees:
                self.cleanup(repo, integration_worktree, integration_branch, names)

    def resolve_conflict(self, integration_worktree: Path, names: Names, plan_path: Path) -> None:
        context_path = integration_worktree / HANDOFF_DIR / "merge-conflict-context.md"
        write_text(context_path, self.conflict_context(integration_worktree, names, plan_path))
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
        self.codex_exec(integration_worktree, prompt, integration_worktree / HANDOFF_DIR / "conflict-resolution-final-response.md")
        self.require_file(integration_worktree / HANDOFF_DIR / "conflict-resolution-summary.md")
        self.run_audit(integration_worktree, plan_path, post_conflict=True)
        self.require_file(integration_worktree / HANDOFF_DIR / "post-conflict-audit-summary.md")

    def copy_integration_context(self, feature_worktree: Path, integration_worktree: Path, plan_path: Path) -> Path:
        source_handoff = feature_worktree / HANDOFF_DIR
        dest_handoff = integration_worktree / HANDOFF_DIR
        ensure_dir(dest_handoff)
        if source_handoff.exists():
            for item in source_handoff.iterdir():
                if item.is_file():
                    shutil.copy2(item, dest_handoff / item.name)

        try:
            rel_plan = plan_path.resolve().relative_to(feature_worktree.resolve())
        except ValueError:
            rel_plan = Path("docs") / "plans" / plan_path.name
        dest_plan = integration_worktree / rel_plan
        ensure_dir(dest_plan.parent)
        if plan_path.exists():
            shutil.copy2(plan_path, dest_plan)
        return dest_plan

    def archive_handoff(self, repo: Path, worktree: Path, run_id: str, stage: str) -> Path:
        archive_dir = repo / ".codex" / "worktree-flow" / run_id / stage
        ensure_dir(archive_dir)
        source = worktree / HANDOFF_DIR
        if source.exists():
            for item in source.iterdir():
                if item.is_file():
                    shutil.copy2(item, archive_dir / item.name)
        return archive_dir

    def conflict_context(self, integration_worktree: Path, names: Names, plan_path: Path) -> str:
        status = self.runner.run(["git", "status", "--short"], integration_worktree, check=False).stdout
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

    def cleanup(self, repo: Path, integration_worktree: Path, integration_branch: str, names: Names) -> None:
        for worktree in (integration_worktree, names.worktree):
            if worktree.exists():
                self.runner.run(["git", "worktree", "remove", str(worktree)], repo, check=False)
        self.runner.run(["git", "branch", "-d", integration_branch], repo, check=False)
        # Squash merges do not mark the feature branch as merged, so force-delete
        # only after the integration branch has fast-forwarded successfully.
        self.runner.run(["git", "branch", "-D", names.branch], repo, check=False)

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
    parser = argparse.ArgumentParser(description="Run the Codex plan -> worktree -> audit -> finish workflow.")
    parser.add_argument("--plan", required=True, help="Approved Markdown plan file.")
    parser.add_argument("--repo", default=".", help="Repository root. Defaults to current directory.")
    parser.add_argument("--base", default="main", help="Base branch/ref. Defaults to main.")
    parser.add_argument("--model", help="Optional Codex model override.")
    parser.add_argument("--merge-mode", choices=["squash", "no-ff", "stop"], default="squash")
    parser.add_argument("--keep-worktrees", action="store_true", help="Do not remove feature/integration worktrees.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    parser.add_argument("--yes", action="store_true", help="Reserved for future confirmation prompts.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = FlowConfig(
        repo=Path(args.repo).expanduser().resolve(),
        plan=Path(args.plan).expanduser().resolve(),
        base=args.base,
        model=args.model,
        merge_mode=args.merge_mode,
        keep_worktrees=args.keep_worktrees,
        yes=args.yes,
    )
    try:
        CodexWorktreeFlow(config, CommandRunner(args.dry_run)).run()
    except FlowError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
