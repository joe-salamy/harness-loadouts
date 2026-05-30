#!/usr/bin/env python3
"""Track Codex skill usage and archive stale skills.

The manager is intentionally conservative:
- usage is recorded explicitly from SKILL.md instrumentation,
- pruning is dry-run unless --apply is passed,
- skills are moved to sibling archive directories, never deleted.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_SKILL_DIRS = (".agents/skills", ".opencode/skills", ".claude/skills")
DEFAULT_THRESHOLD = 100
DEFAULT_MIN_ACTIVE = 8
DEFAULT_PINNED_USER = {"skill-creator", "skill-installer", "openai-docs", "skill-usage-manager"}
DEFAULT_PINNED_REPO = {"skill-usage-manager"}
MARKER = "<!-- skill-usage-manager:record -->"


@dataclass(frozen=True)
class SkillRoot:
    scope: str
    skills_dir: Path
    archive_dir: Path
    ledger_path: Path
    repo_root: Path | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(path: Path) -> str:
    return str(path.expanduser().resolve()).replace("\\", "/")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "scopes": {}}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if "version" not in data:
        data["version"] = 1
    if "scopes" not in data:
        data["scopes"] = {}
    return data


def save_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(encoded)
        temp_name = handle.name
    os.replace(temp_name, path)


def get_git_root(start: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    root = result.stdout.strip()
    return Path(root).resolve() if root else None


def default_user_skills_dir() -> Path:
    return Path.home() / ".codex" / "skills"


def user_ledger_path(skills_dir: Path) -> Path:
    # Default user skills are ~/.codex/skills, so the ledger lives beside that
    # folder. Custom test/user paths follow the same parent layout.
    return skills_dir.parent / "skill-usage.json"


def repo_ledger_path(repo_root: Path) -> Path:
    codex_dir = repo_root / ".codex"
    if codex_dir.exists():
        return codex_dir / "skill-usage.json"
    return repo_root / ".skill-usage.json"


def infer_repo_root_from_skills_dir(skills_dir: Path, explicit_repo: Path | None = None) -> Path:
    if explicit_repo:
        return explicit_repo.expanduser().resolve()
    parts = skills_dir.resolve().parts
    for harness_dir in (".agents", ".opencode", ".claude"):
        if harness_dir in parts:
            idx = parts.index(harness_dir)
            if idx > 0:
                return Path(*parts[:idx]).resolve()
    git_root = get_git_root(skills_dir if skills_dir.exists() else Path.cwd())
    if git_root:
        return git_root
    return Path.cwd().resolve()


def make_root(scope: str, skills_dir: Path | None = None, repo: Path | None = None) -> SkillRoot:
    if scope == "user":
        active = (skills_dir or default_user_skills_dir()).expanduser().resolve()
        return SkillRoot(
            scope="user",
            skills_dir=active,
            archive_dir=active.parent / "skills.archive",
            ledger_path=user_ledger_path(active),
        )

    active = (skills_dir.expanduser().resolve() if skills_dir else None)
    repo_root = infer_repo_root_from_skills_dir(active or (repo or Path.cwd()), repo)
    if active is None:
        raise ValueError("repo scope requires a concrete skills directory")
    return SkillRoot(
        scope="repo",
        skills_dir=active,
        archive_dir=active.parent / "skills.archive",
        ledger_path=repo_ledger_path(repo_root),
        repo_root=repo_root,
    )


def discover_roots(args: argparse.Namespace, scopes: Iterable[str]) -> list[SkillRoot]:
    roots: list[SkillRoot] = []
    scope_set = set(scopes)

    if "user" in scope_set:
        roots.append(make_root("user", Path(args.user_skills_dir) if args.user_skills_dir else None))

    if "repo" in scope_set:
        repo_root = Path(args.repo).expanduser().resolve() if args.repo else get_git_root(Path.cwd()) or Path.cwd().resolve()
        if args.repo_skills_dir:
            candidates = [Path(args.repo_skills_dir).expanduser().resolve()]
        else:
            candidates = [(repo_root / rel).resolve() for rel in REPO_SKILL_DIRS]
            if args.include_loadout_templates:
                candidates.extend((repo_root / "loadouts").glob("*/.opencode/skills"))
                candidates.extend((repo_root / "loadouts").glob("*/.agents/skills"))
                candidates.extend((repo_root / "loadouts").glob("*/.claude/skills"))

        for candidate in candidates:
            if candidate.exists():
                roots.append(make_root("repo", candidate, repo_root))

    return roots


def scope_names(scope: str) -> list[str]:
    if scope == "all":
        return ["user", "repo"]
    return [scope]


def root_key(root: SkillRoot) -> str:
    return f"{root.scope}:{canonical(root.skills_dir)}"


def ensure_scope(data: dict[str, Any], root: SkillRoot) -> dict[str, Any]:
    scopes = data.setdefault("scopes", {})
    key = root_key(root)
    scope_data = scopes.setdefault(
        key,
        {
            "scope": root.scope,
            "skills_dir": canonical(root.skills_dir),
            "archive_dir": canonical(root.archive_dir),
            "total_loads": 0,
            "skills": {},
        },
    )
    scope_data.setdefault("total_loads", 0)
    scope_data.setdefault("skills", {})
    scope_data["scope"] = root.scope
    scope_data["skills_dir"] = canonical(root.skills_dir)
    scope_data["archive_dir"] = canonical(root.archive_dir)
    return scope_data


def pinned_defaults(scope: str) -> set[str]:
    return set(DEFAULT_PINNED_USER if scope == "user" else DEFAULT_PINNED_REPO)


def read_pins(root: SkillRoot, data: dict[str, Any]) -> set[str]:
    pins = pinned_defaults(root.scope)
    global_pins = data.get("pinned", [])
    if isinstance(global_pins, list):
        pins.update(str(item) for item in global_pins)
    if root.repo_root:
        config = root.repo_root / ".codex" / "skill-usage.config.json"
        if config.exists():
            try:
                config_data = json.loads(config.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                config_data = {}
            repo_pins = config_data.get("pinned", [])
            if isinstance(repo_pins, list):
                pins.update(str(item) for item in repo_pins)
    return pins


def skill_dirs(root: SkillRoot) -> list[Path]:
    if not root.skills_dir.exists():
        return []
    return sorted(
        [path for path in root.skills_dir.iterdir() if path.is_dir() and (path / "SKILL.md").exists()],
        key=lambda path: path.name.lower(),
    )


def record(args: argparse.Namespace) -> int:
    root = make_root(args.scope, Path(args.path), Path(args.repo).resolve() if args.repo else None)
    data = load_json(root.ledger_path)
    scope_data = ensure_scope(data, root)
    scope_data["total_loads"] = int(scope_data.get("total_loads", 0)) + 1

    skills = scope_data.setdefault("skills", {})
    timestamp = now_iso()
    entry = skills.setdefault(args.skill_name, {})
    entry.setdefault("first_seen", timestamp)
    entry["last_seen"] = timestamp
    entry["last_load_index"] = scope_data["total_loads"]
    entry["load_count"] = int(entry.get("load_count", 0)) + 1
    entry["source_path"] = canonical(root.skills_dir / args.skill_name)
    entry["archived_at"] = None
    entry["pinned"] = args.skill_name in read_pins(root, data) or bool(entry.get("pinned", False))

    save_json_atomic(root.ledger_path, data)
    return 0


def archive_destination(root: SkillRoot, skill_name: str) -> Path:
    dest = root.archive_dir / skill_name
    if not dest.exists():
        return dest
    suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
    return root.archive_dir / f"{skill_name}.{suffix}"


def prune_candidates(
    root: SkillRoot,
    data: dict[str, Any],
    threshold: int,
    min_active: int,
    include_never_used: bool,
) -> tuple[list[tuple[str, str]], list[str]]:
    scope_data = ensure_scope(data, root)
    total_loads = int(scope_data.get("total_loads", 0))
    skills = scope_data.setdefault("skills", {})
    pins = read_pins(root, data)
    active = [path.name for path in skill_dirs(root)]
    candidates: list[tuple[str, str]] = []
    never_used: list[str] = []

    remaining = len(active)
    for name in active:
        entry = skills.get(name)
        if name in pins or (isinstance(entry, dict) and entry.get("pinned")):
            continue
        if not entry or not entry.get("last_load_index"):
            never_used.append(name)
            if not include_never_used:
                continue
            reason = "never used"
        else:
            distance = total_loads - int(entry["last_load_index"])
            if distance < threshold:
                continue
            reason = f"last loaded {distance} skill loads ago"
        if remaining - 1 < min_active:
            continue
        candidates.append((name, reason))
        remaining -= 1

    return candidates, never_used


def print_root_header(root: SkillRoot) -> None:
    print(f"{root.scope}: {root.skills_dir}")


def scan(args: argparse.Namespace) -> int:
    roots = discover_roots(args, scope_names(args.scope))
    if not roots:
        print("No matching skill directories found.")
        return 0

    for root in roots:
        data = load_json(root.ledger_path)
        scope_data = ensure_scope(data, root)
        skills = scope_data.get("skills", {})
        print_root_header(root)
        print(f"  ledger: {root.ledger_path}")
        print(f"  total_loads: {scope_data.get('total_loads', 0)}")
        for path in skill_dirs(root):
            entry = skills.get(path.name, {})
            last_index = entry.get("last_load_index", "never")
            load_count = entry.get("load_count", 0)
            pin = " pinned" if path.name in read_pins(root, data) or entry.get("pinned") else ""
            print(f"  - {path.name}: loads={load_count}, last={last_index}{pin}")
    return 0


def prune(args: argparse.Namespace) -> int:
    roots = discover_roots(args, scope_names(args.scope))
    if not roots:
        print("No matching skill directories found.")
        return 0

    moved = 0
    for root in roots:
        data = load_json(root.ledger_path)
        candidates, never_used = prune_candidates(
            root,
            data,
            threshold=args.threshold,
            min_active=args.min_active,
            include_never_used=args.include_never_used,
        )
        print_root_header(root)
        if never_used and not args.include_never_used:
            print("  never-used (reported only): " + ", ".join(never_used))
        if not candidates:
            print("  no archive candidates")
            continue

        for name, reason in candidates:
            src = root.skills_dir / name
            dest = archive_destination(root, name)
            print(f"  {'archive' if args.apply else 'would archive'} {name}: {reason}")
            if args.apply:
                root.archive_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
                scope_data = ensure_scope(data, root)
                entry = scope_data.setdefault("skills", {}).setdefault(name, {})
                entry["archived_at"] = now_iso()
                entry["archive_path"] = canonical(dest)
                moved += 1
        if args.apply:
            save_json_atomic(root.ledger_path, data)

    if not args.apply:
        print("\nDry run only. Re-run with --apply to archive candidates.")
    else:
        print(f"\nArchived {moved} skill(s).")
    return 0


def restore(args: argparse.Namespace) -> int:
    if args.path:
        roots = [make_root(args.scope, Path(args.path), Path(args.repo).resolve() if args.repo else None)]
    elif args.scope == "user":
        roots = [make_root("user", Path(args.user_skills_dir) if args.user_skills_dir else None)]
    else:
        roots = discover_roots(args, ["repo"])

    for root in roots:
        if not root.archive_dir.exists():
            continue

        matches = sorted(root.archive_dir.glob(f"{args.skill_name}*"), key=lambda path: path.stat().st_mtime, reverse=True)
        matches = [path for path in matches if path.is_dir() and (path.name == args.skill_name or path.name.startswith(args.skill_name + "."))]
        if not matches:
            continue

        src = matches[0]
        dest = root.skills_dir / args.skill_name
        if dest.exists():
            print(f"Active skill already exists: {dest}", file=sys.stderr)
            return 1

        root.skills_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        data = load_json(root.ledger_path)
        scope_data = ensure_scope(data, root)
        entry = scope_data.setdefault("skills", {}).setdefault(args.skill_name, {})
        entry["archived_at"] = None
        entry["archive_path"] = None
        entry["source_path"] = canonical(dest)
        save_json_atomic(root.ledger_path, data)
        print(f"Restored {args.skill_name} to {dest}")
        return 0

    print(f"No archived skill found for {args.skill_name}", file=sys.stderr)
    return 1


def split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "", text
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return "".join(lines[: idx + 1]), "".join(lines[idx + 1 :])
    return "", text


def record_instruction(skill_name: str, root: SkillRoot) -> str:
    script = Path(__file__).resolve()
    python_exe = sys.executable or "python"
    repo_arg = f' --repo "{root.repo_root}"' if root.repo_root else ""
    return (
        f"{MARKER}\n"
        "When this skill is loaded, first run "
        f"`\"{python_exe}\" \"{script}\" record \"{skill_name}\" --scope {root.scope} --path \"{root.skills_dir}\"{repo_arg}`.\n\n"
    )


def instrument_file(skill_md: Path, root: SkillRoot) -> bool:
    text = skill_md.read_text(encoding="utf-8")
    if MARKER in text:
        return False
    frontmatter, body = split_frontmatter(text)
    new_text = frontmatter + ("\n" if frontmatter and not body.startswith("\n") else "") + record_instruction(skill_md.parent.name, root) + body.lstrip("\n")
    skill_md.write_text(new_text, encoding="utf-8", newline="")
    return True


def instrument(args: argparse.Namespace) -> int:
    roots = discover_roots(args, scope_names(args.scope))
    changed = 0
    for root in roots:
        print_root_header(root)
        for path in skill_dirs(root):
            skill_md = path / "SKILL.md"
            if instrument_file(skill_md, root):
                changed += 1
                print(f"  instrumented {path.name}")
            else:
                print(f"  already instrumented {path.name}")
    print(f"Instrumented {changed} skill(s).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track and prune user/repo Codex skills.")
    parser.add_argument("--repo", help="Repository root for repo-scope operations.")
    parser.add_argument("--user-skills-dir", help="Override user skill directory.")
    parser.add_argument("--repo-skills-dir", help="Override repo skill directory.")
    parser.add_argument(
        "--include-loadout-templates",
        action="store_true",
        help="Include loadouts/* skill template directories when discovering repo skills.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_discovery_options(sub: argparse.ArgumentParser, include_repo: bool = True) -> None:
        if include_repo:
            sub.add_argument("--repo", default=argparse.SUPPRESS, help="Repository root for repo-scope operations.")
        sub.add_argument("--user-skills-dir", default=argparse.SUPPRESS, help="Override user skill directory.")
        sub.add_argument("--repo-skills-dir", default=argparse.SUPPRESS, help="Override repo skill directory.")
        sub.add_argument(
            "--include-loadout-templates",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Include loadouts/* skill template directories when discovering repo skills.",
        )

    record_parser = subparsers.add_parser("record", help="Record one skill load.")
    record_parser.add_argument("skill_name")
    record_parser.add_argument("--scope", choices=["user", "repo"], required=True)
    record_parser.add_argument("--path", required=True, help="Active skills directory containing the skill.")
    record_parser.add_argument("--repo", help="Repository root for repo scope.")
    record_parser.set_defaults(func=record)

    for name, help_text in (("scan", "List skills and usage."), ("prune", "Report or archive stale skills."), ("instrument", "Add record instructions to SKILL.md files.")):
        sub = subparsers.add_parser(name, help=help_text)
        add_discovery_options(sub)
        sub.add_argument("--scope", choices=["user", "repo", "all"], default="all")
        if name == "prune":
            sub.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
            sub.add_argument("--min-active", type=int, default=DEFAULT_MIN_ACTIVE)
            sub.add_argument("--include-never-used", action="store_true")
            sub.add_argument("--apply", action="store_true")
        sub.set_defaults(func=globals()[name])

    restore_parser = subparsers.add_parser("restore", help="Restore one archived skill.")
    restore_parser.add_argument("skill_name")
    add_discovery_options(restore_parser, include_repo=False)
    restore_parser.add_argument("--scope", choices=["user", "repo"], required=True)
    restore_parser.add_argument("--path", help="Active skills directory to restore into.")
    restore_parser.add_argument("--repo", help="Repository root for repo scope.")
    restore_parser.set_defaults(func=restore)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
