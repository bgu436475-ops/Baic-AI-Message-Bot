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


def test_daily_workflow_is_manual_no_send_diagnostics_only() -> None:
    workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert workflow["on"] == {"workflow_dispatch": ""}
    assert workflow["permissions"] == {"contents": "read"}

    steps = workflow["jobs"]["send-digest"]["steps"]
    smoke_step = next(
        step
        for step in steps
        if step.get("name") == "Validate AI backend without sending"
    )
    smoke_env = smoke_step["env"]

    assert smoke_env["CLOUDFLARE_ACCOUNT_ID"] == (
        "${{ secrets.CLOUDFLARE_ACCOUNT_ID }}"
    )
    assert smoke_env["CLOUDFLARE_AI_API_TOKEN"] == (
        "${{ secrets.CLOUDFLARE_AI_API_TOKEN }}"
    )
    expected_model = (
        "${{ vars.CLOUDFLARE_AI_MODEL || "
        "'@cf/meta/llama-3.3-70b-instruct-fp8-fast' }}"
    )
    assert smoke_env["CLOUDFLARE_AI_MODEL"] == expected_model
    expected_openai_model = "${{ vars.OPENAI_MODEL || 'gpt-5.6-luna' }}"
    assert smoke_env["OPENAI_API_KEY"] == "${{ secrets.OPENAI_API_KEY }}"
    assert smoke_env["OPENAI_MODEL"] == expected_openai_model
    assert smoke_step["run"] == "python scripts/validate_ai_backend.py"
    assert smoke_step["if"] == "github.event_name == 'workflow_dispatch'"
    assert set(smoke_env) == {
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_AI_API_TOKEN",
        "CLOUDFLARE_AI_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
    }
    assert not any("FEISHU" in name or "SITE_" in name for name in smoke_env)
    names = {step.get("name") for step in steps}
    assert "Generate daily result" not in names
    assert "Send persisted daily result" not in names
    assert "Persist latest web digest" not in names
    assert "Publish latest digest to private dashboard" not in names
    assert "Save delivery state" not in names


def test_local_delivery_workflow_records_only_a_dispatched_delivery() -> None:
    """Adding delivery side effects here could turn a sync retry into a second send."""
    workflow_text = LOCAL_DELIVERY_WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)

    assert workflow["on"]["repository_dispatch"]["types"] == [
        "local-ai-news-delivered"
    ]
    assert workflow["run-name"] == (
        "Record local delivery ${{ github.event.client_payload.delivery_id }}"
    )
    assert workflow["concurrency"]["group"] == "daily-ai-news"
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    steps = workflow["jobs"]["record-delivery"]["steps"]
    record_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Record local delivery"
    )
    cache_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Save delivery state"
    )
    assert cache_index > record_index
    assert steps[cache_index]["uses"] == "actions/cache/save@v5"
    assert "ai-news-history-" in workflow_text
    assert "FEISHU" not in workflow_text
    assert "CLOUDFLARE" not in workflow_text
    assert "ai-news-bot --dry-run" not in workflow_text
    assert "ai-news-bot --send-existing" not in workflow_text


def test_local_ollama_operator_documentation_covers_primary_delivery_contract() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    operations = OPERATIONS_PATH.read_text(encoding="utf-8")

    assert "09:05" in readme
    assert "本地主任务" in readme
    assert "qwen3:8b" in readme
    assert "uncertain_delivery" in operations
    assert "不会自动重试发送" in operations
    assert "~/Library/Application Support/Baic-AI-Message-Bot/.env" in operations
    assert "--gh-path ~/Library/Application\\ Support/Baic-AI-Message-Bot/bin/gh" in operations
