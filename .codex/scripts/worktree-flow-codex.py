#!/usr/bin/env python3
"""Codex compatibility wrapper for the shared worktree flow."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HARNESS_DIR = Path(".codex")
DEFAULT_HARNESS = "codex"
HANDOFF_DIR = HARNESS_DIR / "handoff"


def load_shared_module():
    script = Path(__file__).resolve().with_name("worktree-flow.py")
    spec = importlib.util.spec_from_file_location("worktree_flow_shared", script)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_shared = load_shared_module()

FlowError = _shared.FlowError
CommandResult = _shared.CommandResult
CommandRunner = _shared.CommandRunner
FlowConfig = _shared.FlowConfig
HarnessWorktreeFlow = _shared.HarnessWorktreeFlow
Names = _shared.Names
format_command_failure = _shared.format_command_failure


def build_parser():
    return _shared.build_parser(
        default_harness=DEFAULT_HARNESS,
        default_harness_dir=HARNESS_DIR,
    )


def main(argv: list[str] | None = None) -> int:
    return _shared.main(
        argv,
        default_harness=DEFAULT_HARNESS,
        default_harness_dir=HARNESS_DIR,
    )


if __name__ == "__main__":
    raise SystemExit(main())
