from pathlib import Path

import yaml


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1] / ".github/workflows/daily-ai-news.yml"
)


def test_non_main_manual_validation_smokes_cloudflare_without_send_secrets() -> None:
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["send-digest"]["steps"]
    generate_step = next(step for step in steps if step.get("name") == "Generate daily result")
    smoke_step = next(
        step
        for step in steps
        if step.get("name") == "Validate AI backend without sending"
    )
    generate_env = generate_step["env"]
    smoke_env = smoke_step["env"]

    assert generate_env["CLOUDFLARE_ACCOUNT_ID"] == (
        "${{ secrets.CLOUDFLARE_ACCOUNT_ID }}"
    )
    assert generate_env["CLOUDFLARE_AI_API_TOKEN"] == (
        "${{ secrets.CLOUDFLARE_AI_API_TOKEN }}"
    )
    expected_model = (
        "${{ vars.CLOUDFLARE_AI_MODEL || "
        "'@cf/meta/llama-3.1-8b-instruct-fast' }}"
    )
    assert generate_env["CLOUDFLARE_AI_MODEL"] == expected_model
    assert smoke_env["CLOUDFLARE_AI_MODEL"] == expected_model
    assert generate_env["OPENAI_API_KEY"] == "${{ secrets.OPENAI_API_KEY }}"
    expected_openai_model = "${{ vars.OPENAI_MODEL || 'gpt-5.6-luna' }}"
    assert generate_env["OPENAI_MODEL"] == expected_openai_model
    assert smoke_env["OPENAI_API_KEY"] == "${{ secrets.OPENAI_API_KEY }}"
    assert smoke_env["OPENAI_MODEL"] == expected_openai_model
    assert "GITHUB_MODELS_MODEL" not in generate_env
    assert smoke_step["run"] == "python scripts/validate_ai_backend.py"
    assert smoke_step["if"] == (
        "github.event_name == 'workflow_dispatch' && github.ref != 'refs/heads/main'"
    )
    assert set(smoke_env) == {
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_AI_API_TOKEN",
        "CLOUDFLARE_AI_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
    }
    assert not any("FEISHU" in name or "SITE_" in name for name in smoke_env)
