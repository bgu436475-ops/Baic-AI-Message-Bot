from pathlib import Path

import yaml


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1] / ".github/workflows/daily-ai-news.yml"
)
LOCAL_DELIVERY_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/record-local-delivery.yml"
)
README_PATH = Path(__file__).resolve().parents[1] / "README.md"
OPERATIONS_PATH = (
    Path(__file__).resolve().parents[1] / "docs/local-ollama-fallback-operations.md"
)


def test_non_main_manual_validation_smokes_cloudflare_without_send_secrets() -> None:
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert "models" not in workflow["permissions"]

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


def test_local_delivery_workflow_records_only_a_dispatched_delivery() -> None:
    """Adding delivery side effects here could turn a sync retry into a second send."""
    workflow_text = LOCAL_DELIVERY_WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)

    assert workflow["on"]["repository_dispatch"]["types"] == [
        "local-ai-news-delivered"
    ]
    assert workflow["concurrency"]["group"] == "daily-ai-news"
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    assert "ai-news-history-" in workflow_text
    assert "FEISHU" not in workflow_text
    assert "CLOUDFLARE" not in workflow_text
    assert "ai-news-bot --dry-run" not in workflow_text
    assert "ai-news-bot --send-existing" not in workflow_text


def test_local_ollama_operator_documentation_covers_safe_fallback_contract() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    operations = OPERATIONS_PATH.read_text(encoding="utf-8")

    assert "09:35" in readme
    assert "qwen3:8b" in readme
    assert "uncertain_delivery" in operations
    assert "不会自动重试发送" in operations
    assert "~/Library/Application Support/Baic-AI-Message-Bot/.env" in operations
    assert "--gh-path ~/Library/Application\\ Support/Baic-AI-Message-Bot/bin/gh" in operations
