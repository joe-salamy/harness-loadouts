#!/usr/bin/env python3
"""Track harness skill usage and archive stale skills.

The manager is intentionally conservative:
- usage is recorded explicitly from centralized AGENTS.md instructions,
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

HARNESS_DIR = Path(Path(__file__).resolve().parent.parent.name)
if not HARNESS_DIR.name.startswith("."):
    HARNESS_DIR = Path(".harness")
LEGACY_HARNESS_DIRS = (".codex", ".opencode", ".claude", ".omp", ".agents")
KNOWN_HARNESS_DIRS = tuple(
    dict.fromkeys((HARNESS_DIR.as_posix(), ".harness", *LEGACY_HARNESS_DIRS))
)
REPO_SKILL_DIRS = tuple(f"{harness_dir}/skills" for harness_dir in KNOWN_HARNESS_DIRS)
REPO_SCOPE_KEY = "repo"
DEFAULT_THRESHOLD = 100
DEFAULT_MIN_ACTIVE = 8
DEFAULT_PINNED_USER = {
    "skill-creator",
    "skill-installer",
    "openai-docs",
    "skill-usage-manager",
}
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
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


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
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
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
    return Path.home() / HARNESS_DIR / "skills"


def user_ledger_path(skills_dir: Path) -> Path:
    # Default user skills live under the active harness directory, so the ledger
    # lives beside that folder. Custom test/user paths follow the same layout.
    return skills_dir.parent / "skill-usage.json"


def repo_ledger_path(repo_root: Path) -> Path:
    for harness_dir in KNOWN_HARNESS_DIRS:
        candidate = repo_root / harness_dir
        if candidate.exists():
            return candidate / "skill-usage.json"
    return repo_root / ".skill-usage.json"


def infer_repo_root_from_skills_dir(
    skills_dir: Path, explicit_repo: Path | None = None
) -> Path:
    if explicit_repo:
        return explicit_repo.expanduser().resolve()
    parts = skills_dir.resolve().parts
    for harness_dir in KNOWN_HARNESS_DIRS:
        if harness_dir in parts:
            idx = parts.index(harness_dir)
            if idx > 0:
                return Path(*parts[:idx]).resolve()
    git_root = get_git_root(skills_dir if skills_dir.exists() else Path.cwd())
    if git_root:
        return git_root
    return Path.cwd().resolve()


def repo_root_for_local_skills_dir(
    skills_dir: Path, explicit_repo: Path | None = None
) -> Path | None:
    repo_root = (
        explicit_repo.expanduser().resolve()
        if explicit_repo
        else get_git_root(skills_dir if skills_dir.exists() else Path.cwd())
    )
    if repo_root is None:
        return None
    active = skills_dir.expanduser().resolve()
    for rel in REPO_SKILL_DIRS:
        if active == (repo_root / rel).resolve():
            return repo_root
    return None


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def is_loadout_skills_dir(repo_root: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(repo_root / "loadouts")
    except ValueError:
        return False
    return (
        len(rel.parts) >= 3
        and rel.parts[-1] == "skills"
        and rel.parts[-2] in KNOWN_HARNESS_DIRS
    )


def repo_skills_dir(repo_root: Path, requested: Path | None = None) -> Path:
    repo_root = repo_root.expanduser().resolve()
    active = requested.expanduser().resolve() if requested is not None else None
    known_dirs = [(repo_root / rel).resolve() for rel in REPO_SKILL_DIRS]

    if active is not None:
        for skills_dir in known_dirs:
            if is_relative_to(active, skills_dir):
                return skills_dir
        if is_loadout_skills_dir(repo_root, active):
            return active
        if (active / "SKILL.md").exists():
            return active.parent
        if active.name == "SKILL.md":
            return active.parent.parent

    harness_skills = (repo_root / HARNESS_DIR / "skills").resolve()
    if harness_skills.exists():
        return harness_skills
    for skills_dir in known_dirs:
        if skills_dir.exists():
            return skills_dir
    return harness_skills


def make_root(
    scope: str, skills_dir: Path | None = None, repo: Path | None = None
) -> SkillRoot:
    if scope == "user":
        active = (skills_dir or default_user_skills_dir()).expanduser().resolve()
        repo_root = repo_root_for_local_skills_dir(active, repo)
        if repo_root is not None:
            return make_root("repo", active, repo_root)
        return SkillRoot(
            scope="user",
            skills_dir=active,
            archive_dir=active.parent / "skills.archive",
            ledger_path=user_ledger_path(active),
        )

    active = skills_dir.expanduser().resolve() if skills_dir else None
    repo_root = infer_repo_root_from_skills_dir(active or (repo or Path.cwd()), repo)
    normalized_skills_dir = repo_skills_dir(repo_root, active)
    return SkillRoot(
        scope="repo",
        skills_dir=normalized_skills_dir,
        archive_dir=normalized_skills_dir.parent / "skills.archive",
        ledger_path=repo_ledger_path(repo_root),
        repo_root=repo_root,
    )


def discover_roots(args: argparse.Namespace, scopes: Iterable[str]) -> list[SkillRoot]:
    roots: list[SkillRoot] = []
    scope_set = set(scopes)

    if "user" in scope_set:
        roots.append(
            make_root(
                "user", Path(args.user_skills_dir) if args.user_skills_dir else None
            )
        )

    if "repo" in scope_set:
        repo_root = (
            Path(args.repo).expanduser().resolve()
            if args.repo
            else get_git_root(Path.cwd()) or Path.cwd().resolve()
        )
        if args.repo_skills_dir:
            candidates = [Path(args.repo_skills_dir).expanduser().resolve()]
        else:
            candidates = [repo_skills_dir(repo_root)]
            if args.include_loadout_templates:
                for harness_dir in KNOWN_HARNESS_DIRS:
                    candidates.extend(
                        (repo_root / "loadouts").glob(f"*/{harness_dir}/skills")
                    )

        for candidate in candidates:
            if candidate.exists():
                roots.append(make_root("repo", candidate, repo_root))

    return roots


def scope_names(scope: str) -> list[str]:
    if scope == "all":
        return ["user", "repo"]
    return [scope]


def root_key(root: SkillRoot) -> str:
    if root.scope == "repo":
        return REPO_SCOPE_KEY
    return f"user:{canonical(root.skills_dir)}"


def ensure_scope(data: dict[str, Any], root: SkillRoot) -> dict[str, Any]:
    if root.scope == "repo":
        collapse_repo_scopes(data, root)
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
        for harness_dir in KNOWN_HARNESS_DIRS:
            config = root.repo_root / harness_dir / "skill-usage.config.json"
            if not config.exists():
                continue
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
        [
            path
            for path in root.skills_dir.iterdir()
            if path.is_dir() and (path / "SKILL.md").exists()
        ],
        key=lambda path: path.name.lower(),
    )


def record(args: argparse.Namespace) -> int:
    root = make_root(
        args.scope, Path(args.path), Path(args.repo).resolve() if args.repo else None
    )
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
    entry["pinned"] = args.skill_name in read_pins(root, data) or bool(
        entry.get("pinned", False)
    )

    save_json_atomic(root.ledger_path, data)
    return 0


def is_under_canonical(path_text: str, parent_text: str) -> bool:
    normalized = path_text.replace("\\", "/").rstrip("/")
    parent = parent_text.replace("\\", "/").rstrip("/")
    return normalized == parent or normalized.startswith(parent + "/")


def remap_canonical_path(path_text: Any, source_repo: Path, target_repo: Path) -> Any:
    if not isinstance(path_text, str) or not path_text:
        return path_text
    source = canonical(source_repo)
    target = canonical(target_repo)
    normalized = canonical(Path(path_text))
    if not is_under_canonical(normalized, source):
        return normalized
    suffix = normalized[len(source) :].lstrip("/")
    return target if not suffix else f"{target}/{suffix}"


def merge_skill_metadata(
    existing: dict[str, Any], incoming: dict[str, Any], *, load_count: int | None = None
) -> dict[str, Any]:
    merged = dict(existing)
    if load_count is None:
        load_count = int(existing.get("load_count", 0)) + int(
            incoming.get("load_count", 0)
        )
    merged["load_count"] = load_count

    first_seen = [
        value
        for value in (existing.get("first_seen"), incoming.get("first_seen"))
        if value
    ]
    if first_seen:
        merged["first_seen"] = min(str(value) for value in first_seen)

    last_seen = [
        value
        for value in (existing.get("last_seen"), incoming.get("last_seen"))
        if value
    ]
    if last_seen:
        merged["last_seen"] = max(str(value) for value in last_seen)

    if incoming.get("source_path"):
        merged["source_path"] = incoming["source_path"]
    merged["archived_at"] = incoming.get("archived_at", existing.get("archived_at"))
    merged["pinned"] = bool(existing.get("pinned", False)) or bool(
        incoming.get("pinned", False)
    )
    if incoming.get("archive_path"):
        merged["archive_path"] = incoming["archive_path"]
    if incoming.get("last_load_index") is not None:
        merged["last_load_index"] = incoming["last_load_index"]
    return merged


def reset_archive_metadata(entry: dict[str, Any]) -> None:
    if entry.get("archived_at"):
        return
    entry["archived_at"] = None
    entry.pop("archive_path", None)


def rebuild_load_indexes(scope_data: dict[str, Any]) -> None:
    running_total = 0
    skills = scope_data.setdefault("skills", {})
    for skill_name, entry in sorted(
        skills.items(),
        key=lambda item: (str(item[1].get("last_seen") or ""), item[0]),
    ):
        running_total += int(entry.get("load_count", 0))
        entry["last_load_index"] = running_total


def collapse_repo_scopes(data: dict[str, Any], root: SkillRoot) -> None:
    scopes = data.setdefault("scopes", {})
    repo_items = [
        (key, scope_data)
        for key, scope_data in scopes.items()
        if isinstance(scope_data, dict)
        and (
            scope_data.get("scope") == "repo"
            or key == REPO_SCOPE_KEY
            or key.startswith("repo:")
        )
    ]
    if not repo_items or all(key == REPO_SCOPE_KEY for key, _scope_data in repo_items):
        return

    merged_scope: dict[str, Any] = {
        "scope": "repo",
        "skills_dir": canonical(root.skills_dir),
        "archive_dir": canonical(root.archive_dir),
        "total_loads": 0,
        "skills": {},
    }
    merged_skills = merged_scope["skills"]
    for _key, legacy_scope in repo_items:
        merged_scope["total_loads"] = int(merged_scope["total_loads"]) + int(
            legacy_scope.get("total_loads", 0)
        )
        for skill_name, raw_entry in legacy_scope.get("skills", {}).items():
            if not isinstance(raw_entry, dict):
                continue
            entry = dict(raw_entry)
            entry["source_path"] = canonical(root.skills_dir / skill_name)
            existing = merged_skills.get(skill_name, {})
            merged = merge_skill_metadata(existing, entry)
            reset_archive_metadata(merged)
            merged_skills[skill_name] = merged

    rebuild_load_indexes(merged_scope)
    for key, _legacy_scope in repo_items:
        if key != REPO_SCOPE_KEY:
            scopes.pop(key, None)
    scopes[REPO_SCOPE_KEY] = merged_scope


def is_repo_scope_key(scope: str, key: str) -> bool:
    return scope == "repo" or key == REPO_SCOPE_KEY or key.startswith("repo:")


def normalized_scope_key(scope: str, skills_dir: str) -> str:
    if scope == "repo":
        return REPO_SCOPE_KEY
    return f"{scope}:{skills_dir}"


def normalize_ledger_for_consolidation(
    data: dict[str, Any], source_repo: Path, target_repo: Path
) -> dict[str, Any]:
    normalized: dict[str, Any] = {"version": data.get("version", 1), "scopes": {}}
    if "pinned" in data:
        normalized["pinned"] = data["pinned"]

    target_repo_skills_dir = repo_skills_dir(target_repo)
    repo_scopes_to_rebuild: set[str] = set()
    for key, raw_scope in data.get("scopes", {}).items():
        if not isinstance(raw_scope, dict):
            continue
        scope = str(raw_scope.get("scope") or key.split(":", 1)[0])
        if is_repo_scope_key(scope, key):
            scope = "repo"
            skills_dir = canonical(target_repo_skills_dir)
            archive_dir = canonical(target_repo_skills_dir.parent / "skills.archive")
        else:
            skills_dir = remap_canonical_path(
                raw_scope.get("skills_dir", key.split(":", 1)[-1]),
                source_repo,
                target_repo,
            )
            archive_dir = remap_canonical_path(
                raw_scope.get("archive_dir", ""), source_repo, target_repo
            )
            if not isinstance(skills_dir, str) or not skills_dir:
                continue

        target_key = normalized_scope_key(scope, skills_dir)
        if scope == "repo" and (
            key != REPO_SCOPE_KEY or target_key in normalized["scopes"]
        ):
            repo_scopes_to_rebuild.add(target_key)
        scope_data = normalized["scopes"].setdefault(
            target_key,
            {
                "scope": scope,
                "skills_dir": skills_dir,
                "archive_dir": archive_dir,
                "total_loads": 0,
                "skills": {},
            },
        )
        scope_data["total_loads"] = int(scope_data.get("total_loads", 0)) + int(
            raw_scope.get("total_loads", 0)
        )
        if archive_dir:
            scope_data["archive_dir"] = archive_dir

        skills = scope_data.setdefault("skills", {})
        for name, raw_entry in raw_scope.get("skills", {}).items():
            if not isinstance(raw_entry, dict):
                continue
            entry = dict(raw_entry)
            if scope == "repo":
                entry["source_path"] = canonical(target_repo_skills_dir / name)
            elif entry.get("source_path"):
                entry["source_path"] = remap_canonical_path(
                    entry["source_path"], source_repo, target_repo
                )
            if entry.get("archive_path"):
                entry["archive_path"] = remap_canonical_path(
                    entry["archive_path"], source_repo, target_repo
                )
            existing = skills.get(name, {})
            skills[name] = merge_skill_metadata(existing, entry)

    for scope_key in repo_scopes_to_rebuild:
        scope_data = normalized["scopes"].get(scope_key)
        if isinstance(scope_data, dict):
            rebuild_load_indexes(scope_data)

    return normalized


def ensure_normalized_scope(
    data: dict[str, Any], source_scope: dict[str, Any]
) -> dict[str, Any]:
    key = normalized_scope_key(source_scope["scope"], source_scope["skills_dir"])
    scope_data = data.setdefault("scopes", {}).setdefault(
        key,
        {
            "scope": source_scope["scope"],
            "skills_dir": source_scope["skills_dir"],
            "archive_dir": source_scope.get("archive_dir", ""),
            "total_loads": 0,
            "skills": {},
        },
    )
    scope_data["scope"] = source_scope["scope"]
    scope_data["skills_dir"] = source_scope["skills_dir"]
    scope_data["archive_dir"] = source_scope.get("archive_dir", "")
    scope_data.setdefault("total_loads", 0)
    scope_data.setdefault("skills", {})
    return scope_data


def target_pins_for_scope(
    target_data: dict[str, Any], target_repo: Path, scope_data: dict[str, Any]
) -> set[str]:
    root = SkillRoot(
        scope=str(scope_data["scope"]),
        skills_dir=Path(str(scope_data["skills_dir"])),
        archive_dir=Path(str(scope_data.get("archive_dir") or "")),
        ledger_path=Path("."),
        repo_root=target_repo if scope_data["scope"] == "repo" else None,
    )
    return read_pins(root, target_data)


def consolidate(args: argparse.Namespace) -> int:
    source_repo = Path(args.source_repo).expanduser().resolve()
    target_worktree = (
        Path(args.target_worktree or args.target_repo).expanduser().resolve()
    )
    target_repo = Path(args.target_repo).expanduser().resolve()
    source_data = normalize_ledger_for_consolidation(
        load_json(Path(args.source_ledger)), source_repo, target_repo
    )
    base_data = normalize_ledger_for_consolidation(
        load_json(Path(args.base_ledger)), source_repo, target_repo
    )
    target_path = Path(args.target_ledger)
    target_data = normalize_ledger_for_consolidation(
        load_json(target_path), target_worktree, target_repo
    )

    for scope_key, source_scope in source_data.get("scopes", {}).items():
        base_scope = base_data.get("scopes", {}).get(scope_key, {})
        target_scope = ensure_normalized_scope(target_data, source_scope)
        pins = target_pins_for_scope(target_data, target_repo, target_scope)
        target_skills = target_scope.setdefault("skills", {})
        base_skills = base_scope.get("skills", {})

        for skill_name, source_entry in source_scope.get("skills", {}).items():
            base_entry = base_skills.get(skill_name, {})
            delta = int(source_entry.get("load_count", 0)) - int(
                base_entry.get("load_count", 0)
            )
            if delta <= 0:
                continue

            target_scope["total_loads"] = (
                int(target_scope.get("total_loads", 0)) + delta
            )
            existing = target_skills.get(skill_name, {})
            new_count = int(existing.get("load_count", 0)) + delta
            merged = merge_skill_metadata(existing, source_entry, load_count=new_count)
            merged["last_load_index"] = target_scope["total_loads"]
            if source_entry.get("source_path"):
                merged["source_path"] = source_entry["source_path"]
            merged["archived_at"] = None
            merged["pinned"] = (
                bool(existing.get("pinned", False))
                or bool(source_entry.get("pinned", False))
                or skill_name in pins
            )
            target_skills[skill_name] = merged

    save_json_atomic(target_path, target_data)
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
            pin = (
                " pinned"
                if path.name in read_pins(root, data) or entry.get("pinned")
                else ""
            )
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
        roots = [
            make_root(
                args.scope,
                Path(args.path),
                Path(args.repo).resolve() if args.repo else None,
            )
        ]
    elif args.scope == "user":
        roots = [
            make_root(
                "user", Path(args.user_skills_dir) if args.user_skills_dir else None
            )
        ]
    else:
        roots = discover_roots(args, ["repo"])

    for root in roots:
        if not root.archive_dir.exists():
            continue

        matches = sorted(
            root.archive_dir.glob(f"{args.skill_name}*"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        matches = [
            path
            for path in matches
            if path.is_dir()
            and (
                path.name == args.skill_name
                or path.name.startswith(args.skill_name + ".")
            )
        ]
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


def remove_legacy_record_instruction(text: str) -> tuple[str, bool]:
    if MARKER not in text:
        return text, False

    lines = text.splitlines(keepends=True)
    cleaned: list[str] = []
    removed = False
    idx = 0
    while idx < len(lines):
        if lines[idx].strip() != MARKER:
            cleaned.append(lines[idx])
            idx += 1
            continue

        removed = True
        idx += 1
        if idx < len(lines) and "When this skill is loaded" in lines[idx]:
            idx += 1
        if idx < len(lines) and not lines[idx].strip():
            idx += 1

    return "".join(cleaned), removed


def instrument_file(skill_md: Path, _root: SkillRoot) -> bool:
    text = skill_md.read_text(encoding="utf-8")
    new_text, changed = remove_legacy_record_instruction(text)
    if not changed:
        return False
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
                print(f"  removed legacy instruction from {path.name}")
            else:
                print(f"  no legacy instruction in {path.name}")
    print(f"Cleaned {changed} skill(s).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Track and prune user/repo harness skills."
    )
    parser.add_argument("--repo", help="Repository root for repo-scope operations.")
    parser.add_argument("--user-skills-dir", help="Override user skill directory.")
    parser.add_argument("--repo-skills-dir", help="Override repo skill directory.")
    parser.add_argument(
        "--include-loadout-templates",
        action="store_true",
        help="Include loadouts/* skill template directories when discovering repo skills.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_discovery_options(
        sub: argparse.ArgumentParser, include_repo: bool = True
    ) -> None:
        if include_repo:
            sub.add_argument(
                "--repo",
                default=argparse.SUPPRESS,
                help="Repository root for repo-scope operations.",
            )
        sub.add_argument(
            "--user-skills-dir",
            default=argparse.SUPPRESS,
            help="Override user skill directory.",
        )
        sub.add_argument(
            "--repo-skills-dir",
            default=argparse.SUPPRESS,
            help="Override repo skill directory.",
        )
        sub.add_argument(
            "--include-loadout-templates",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Include loadouts/* skill template directories when discovering repo skills.",
        )

    record_parser = subparsers.add_parser("record", help="Record one skill load.")
    record_parser.add_argument("skill_name")
    record_parser.add_argument("--scope", choices=["user", "repo"], required=True)
    record_parser.add_argument(
        "--path", required=True, help="Active skills directory containing the skill."
    )
    record_parser.add_argument("--repo", help="Repository root for repo scope.")
    record_parser.set_defaults(func=record)

    consolidate_parser = subparsers.add_parser(
        "consolidate",
        help=(
            "One-shot semantic merge of positive skill-usage deltas from a "
            "source ledger into a target ledger."
        ),
        description=(
            "One-shot command: apply positive source-minus-base skill usage "
            "deltas once. Replaying the same source/base pair against an "
            "already-updated target ledger will add the same deltas again."
        ),
    )
    consolidate_parser.add_argument("--source-ledger", required=True)
    consolidate_parser.add_argument("--base-ledger", required=True)
    consolidate_parser.add_argument("--target-ledger", required=True)
    consolidate_parser.add_argument("--source-repo", required=True)
    consolidate_parser.add_argument("--target-repo", required=True)
    consolidate_parser.add_argument(
        "--target-worktree",
        help=(
            "Filesystem root whose paths are present in the target ledger. "
            "Defaults to --target-repo."
        ),
    )
    consolidate_parser.set_defaults(func=consolidate)

    for name, help_text in (
        ("scan", "List skills and usage."),
        ("prune", "Report or archive stale skills."),
        ("instrument", "Remove legacy record instructions from SKILL.md files."),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        add_discovery_options(sub)
        sub.add_argument("--scope", choices=["user", "repo", "all"], default="all")
        if name == "prune":
            sub.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
            sub.add_argument("--min-active", type=int, default=DEFAULT_MIN_ACTIVE)
            sub.add_argument("--include-never-used", action="store_true")
            sub.add_argument("--apply", action="store_true")
        sub.set_defaults(func=globals()[name])

    restore_parser = subparsers.add_parser(
        "restore", help="Restore one archived skill."
    )
    restore_parser.add_argument("skill_name")
    add_discovery_options(restore_parser, include_repo=False)
    restore_parser.add_argument("--scope", choices=["user", "repo"], required=True)
    restore_parser.add_argument(
        "--path", help="Active skills directory to restore into."
    )
    restore_parser.add_argument("--repo", help="Repository root for repo scope.")
    restore_parser.set_defaults(func=restore)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
