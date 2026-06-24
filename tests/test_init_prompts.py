from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INIT_PROMPTS = ROOT / "init-prompts"


def test_init_prompts_are_source_templates() -> None:
    readme = (INIT_PROMPTS / "README.md").read_text(encoding="utf-8")

    assert "source templates, not loadout payloads" in readme
    assert "harness-init.ps1" in readme
    assert "omp-repo-init.md" in readme


def test_omp_repo_init_prompt_contains_required_bootstrap_steps() -> None:
    prompt = (INIT_PROMPTS / "omp-repo-init.md").read_text(encoding="utf-8")

    required_phrases = (
        "Create or update `README.md`",
        "Use `web_search`",
        "5-10 high-leverage skills",
        ".omp/skills/<skill-name>/SKILL.md",
        "python ./.omp/scripts/skill-usage-manager.py record <skill-name> --scope repo --path ./.omp/skills --repo .",
        "<repo>/.omp/lsp.json",
        "do not create `.omp/lsp.json` just to restate defaults",
        "Do not store secrets in committed files",
    )
    for phrase in required_phrases:
        assert phrase in prompt
