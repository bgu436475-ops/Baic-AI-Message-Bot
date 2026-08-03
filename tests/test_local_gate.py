from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest

from ai_news_bot.local_gate import (
    CloudRun,
    CloudSnapshot,
    CommandResult,
    GitHubCLIClient,
    RemoteDigestProbe,
    evaluate_cloud_snapshot,
    wait_for_cloud_gate,
)
from ai_news_bot.models import (
    DigestBoards,
    EditorialDigest,
    GlobalPipelineStats,
    PipelineStats,
)


DAY = date(2026, 8, 3)


def valid_empty_digest(day: date = DAY) -> EditorialDigest:
    return EditorialDigest(
        run_status="no_qualifying_items",
        generated_at=datetime(day.year, day.month, day.day, 1, tzinfo=UTC),
        candidate_count=0,
        source_count=0,
        daily_narrative_zh="今天没有通过核验的 AI 新闻。",
        global_pipeline_stats=GlobalPipelineStats(
            candidate_count=0,
            shortlist_count=0,
            source_verified_count=0,
            rejected_count=0,
        ),
        boards=DigestBoards(),
        items=[],
        pipeline_stats=PipelineStats(
            candidate_count=0,
            shortlist_count=0,
            source_verified_count=0,
            rejected_count=0,
        ),
    )


def run_with(
    *,
    event: str = "repository_dispatch",
    status: str = "completed",
    conclusion: str | None = "failure",
    send_step: str | None = "failure",
    created_at: datetime = datetime(2026, 8, 3, 1, 5, tzinfo=UTC),
) -> CloudRun:
    return CloudRun(
        run_id=1,
        event=event,
        status=status,
        conclusion=conclusion,
        created_at=created_at,
        url="https://github.com/o/r/actions/runs/1",
        send_step_conclusion=send_step,
    )


def snapshot(
    runs: tuple[CloudRun, ...],
    digest_status: str = "missing",
    digest: EditorialDigest | None = None,
) -> CloudSnapshot:
    return CloudSnapshot(
        runs=runs,
        remote_digest=RemoteDigestProbe(digest_status, digest),
        server_time=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
    )


def test_successful_send_step_blocks_local_even_if_run_failed() -> None:
    result = evaluate_cloud_snapshot(DAY, snapshot((run_with(send_step="success"),)))
    assert result.decision == "skip_delivered"


def test_active_run_waits_instead_of_sending() -> None:
    result = evaluate_cloud_snapshot(
        DAY,
        snapshot((run_with(status="in_progress", conclusion=None, send_step=None),)),
    )
    assert result.decision == "wait"


def test_all_completed_failures_allow_local_run() -> None:
    result = evaluate_cloud_snapshot(DAY, snapshot((run_with(),)))
    assert result.decision == "run_local"


def test_malformed_remote_digest_blocks_automatic_send() -> None:
    result = evaluate_cloud_snapshot(DAY, snapshot((run_with(),), digest_status="malformed"))
    assert result.decision == "blocked"


def test_naive_remote_digest_is_blocked_as_malformed() -> None:
    naive_digest = valid_empty_digest().model_copy(
        update={"generated_at": datetime(2026, 8, 3, 1, 0)}
    )

    result = evaluate_cloud_snapshot(
        DAY,
        snapshot((run_with(),), digest_status="valid", digest=naive_digest),
    )

    assert result.decision == "blocked"
    assert result.reason_code == "remote_digest_invalid"


def test_unknown_remote_digest_status_blocks_automatic_send() -> None:
    result = evaluate_cloud_snapshot(
        DAY,
        CloudSnapshot(
            runs=(run_with(),),
            remote_digest=RemoteDigestProbe("unknown"),  # type: ignore[arg-type]
            server_time=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
        ),
    )

    assert result.decision == "blocked"
    assert result.reason_code == "remote_digest_unknown"


def test_unknown_remote_digest_status_blocks_even_when_cloud_run_is_active() -> None:
    result = evaluate_cloud_snapshot(
        DAY,
        CloudSnapshot(
            runs=(run_with(status="in_progress", conclusion=None, send_step=None),),
            remote_digest=RemoteDigestProbe("unknown"),  # type: ignore[arg-type]
            server_time=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
        ),
    )

    assert result.decision == "blocked"
    assert result.reason_code == "remote_digest_unknown"


@pytest.mark.parametrize(
    ("runs", "digest_status", "digest", "expected"),
    [
        ((), "missing", None, "run_local"),
        ((run_with(event="workflow_dispatch"),), "missing", None, "run_local"),
        ((), "valid", valid_empty_digest(), "skip_delivered"),
        ((), "valid", valid_empty_digest(date(2026, 8, 2)), "run_local"),
        ((), "unavailable", None, "blocked"),
    ],
)
def test_cloud_gate_decision_table(
    runs: tuple[CloudRun, ...],
    digest_status: str,
    digest: EditorialDigest | None,
    expected: str,
) -> None:
    result = evaluate_cloud_snapshot(DAY, snapshot(runs, digest_status, digest))
    assert result.decision == expected


class FakeCommandRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.stdin: list[str | None] = []

    def __call__(
        self,
        arguments: tuple[str, ...],
        stdin: str | None = None,
    ) -> CommandResult:
        self.calls.append(arguments)
        self.stdin.append(stdin)
        if arguments[1:4] == ("api", "-i", "rate_limit"):
            return CommandResult(
                0,
                "HTTP/2 200 OK\r\nDate: Mon, 03 Aug 2026 02:00:00 GMT\r\n\r\n{}",
            )
        if arguments[1:3] == ("run", "list"):
            return CommandResult(
                0,
                json.dumps(
                    [
                        {
                            "databaseId": 1,
                            "event": "repository_dispatch",
                            "status": "completed",
                            "conclusion": "failure",
                            "createdAt": "2026-08-03T01:05:00Z",
                            "url": "https://github.com/o/r/actions/runs/1",
                        }
                    ]
                ),
            )
        if arguments[1:3] == ("run", "view"):
            return CommandResult(
                0,
                json.dumps(
                    {
                        "jobs": [
                            {
                                "name": "send-digest",
                                "steps": [
                                    {
                                        "name": "Send persisted daily result",
                                        "conclusion": "success",
                                    }
                                ],
                            }
                        ]
                    }
                ),
            )
        if arguments[1:3] == ("api", "repos/bgu436475-ops/Baic-AI-Message-Bot/contents/web/public/data/latest.json?ref=main"):
            return CommandResult(
                0,
                json.dumps(
                    {
                        "content": base64.b64encode(
                            valid_empty_digest().model_dump_json().encode("utf-8")
                        ).decode("ascii"),
                        "encoding": "base64",
                    }
                ),
            )
        if arguments[1:3] == ("api", "repos/bgu436475-ops/Baic-AI-Message-Bot/dispatches"):
            return CommandResult(0, "")
        raise AssertionError(f"unexpected command: {arguments}")


def test_github_cli_snapshot_inspects_send_step_and_uses_server_date() -> None:
    fake = FakeCommandRunner()
    client = GitHubCLIClient(Path("/usr/local/bin/gh"), command_runner=fake)

    cloud_snapshot = client.snapshot(DAY)

    assert cloud_snapshot.runs[0].send_step_conclusion == "success"
    assert cloud_snapshot.server_time == datetime(2026, 8, 3, 2, 0, tzinfo=UTC)
    assert all(
        "token" not in argument.casefold()
        for call in fake.calls
        for argument in call
    )


def test_github_cli_dispatches_task_five_payload_only_over_stdin() -> None:
    fake = FakeCommandRunner()
    client = GitHubCLIClient(Path("/usr/local/bin/gh"), command_runner=fake)

    client.dispatch_local_delivery(DAY, "a" * 32, "published")

    assert json.loads(fake.stdin[-1] or "") == {
        "event_type": "local-ai-news-delivered",
        "client_payload": {
            "delivery_date": "2026-08-03",
            "delivery_id": "a" * 32,
            "run_status": "published",
        },
    }
    assert all(
        "token" not in argument.casefold()
        for call in fake.calls
        for argument in call
    )


def test_github_authentication_failure_blocks_automatic_local_send() -> None:
    def unauthenticated(
        arguments: tuple[str, ...], stdin: str | None = None
    ) -> CommandResult:
        del arguments, stdin
        return CommandResult(1, "", "authentication required")

    client = GitHubCLIClient(
        Path("/usr/local/bin/gh"), command_runner=unauthenticated
    )

    result = evaluate_cloud_snapshot(DAY, client.snapshot(DAY))

    assert result.decision == "blocked"
    assert result.reason_code == "cloud_snapshot_unavailable"


class SequencedSnapshotClient:
    def __init__(self, snapshots: list[CloudSnapshot]) -> None:
        self.snapshots = snapshots
        self.calls = 0

    def snapshot(self, day: date) -> CloudSnapshot:
        result = self.snapshots[min(self.calls, len(self.snapshots) - 1)]
        self.calls += 1
        return result


def test_wait_for_cloud_gate_rechecks_active_run_once_per_minute() -> None:
    client = SequencedSnapshotClient(
        [
            CloudSnapshot(
                runs=(run_with(status="in_progress", conclusion=None, send_step=None),),
                remote_digest=RemoteDigestProbe("missing"),
                server_time=datetime(2026, 8, 3, 1, 49, tzinfo=UTC),
            ),
            snapshot((run_with(send_step="success"),)),
        ]
    )
    sleeps: list[float] = []

    result = wait_for_cloud_gate(client, DAY, time(9, 50), sleeps.append)

    assert result.decision == "skip_delivered"
    assert sleeps == [60]


def test_wait_for_cloud_gate_blocks_at_deadline() -> None:
    client = SequencedSnapshotClient(
        [
            CloudSnapshot(
                runs=(run_with(status="in_progress", conclusion=None, send_step=None),),
                remote_digest=RemoteDigestProbe("missing"),
                server_time=datetime(2026, 8, 3, 1, 50, tzinfo=UTC),
            )
        ]
    )

    result = wait_for_cloud_gate(client, DAY, time(9, 50), lambda _: None)

    assert result.decision == "blocked"
    assert result.reason_code == "cloud_wait_timeout"
