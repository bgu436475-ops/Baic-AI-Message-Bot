from __future__ import annotations

from ai_news_bot.workflow_mode import main, resolve_workflow_mode


VALIDATION_REF = (
    "refs/heads/codex/validate-grounded-action-editor"
)


def test_manual_validation_branch_cannot_deliver() -> None:
    mode = resolve_workflow_mode("workflow_dispatch", VALIDATION_REF)

    assert mode.is_validation is True
    assert mode.allow_delivery is False


def test_main_automatic_run_can_deliver() -> None:
    mode = resolve_workflow_mode("schedule", "refs/heads/main")

    assert mode.is_validation is False
    assert mode.allow_delivery is True


def test_other_branch_cannot_generate_or_deliver() -> None:
    mode = resolve_workflow_mode(
        "workflow_dispatch",
        "refs/heads/untrusted",
    )

    assert mode.is_validation is False
    assert mode.allow_delivery is False


def test_cli_emits_github_boolean_outputs(capsys) -> None:
    assert main(
        [
            "--event",
            "workflow_dispatch",
            "--ref",
            VALIDATION_REF,
        ]
    ) == 0

    assert capsys.readouterr().out.splitlines() == [
        "is_validation=true",
        "allow_delivery=false",
    ]
