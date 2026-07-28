from __future__ import annotations

import argparse
from dataclasses import dataclass


MAIN_REF = "refs/heads/main"
VALIDATION_REF = (
    "refs/heads/codex/validate-grounded-action-editor"
)


@dataclass(frozen=True)
class WorkflowMode:
    is_validation: bool
    allow_delivery: bool


def resolve_workflow_mode(
    event_name: str,
    ref: str,
) -> WorkflowMode:
    return WorkflowMode(
        is_validation=(
            event_name == "workflow_dispatch"
            and ref == VALIDATION_REF
        ),
        allow_delivery=ref == MAIN_REF,
    )


def _github_bool(value: bool) -> str:
    return "true" if value else "false"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True)
    parser.add_argument("--ref", required=True)
    args = parser.parse_args(argv)

    mode = resolve_workflow_mode(args.event, args.ref)
    print(f"is_validation={_github_bool(mode.is_validation)}")
    print(f"allow_delivery={_github_bool(mode.allow_delivery)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
