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
    GitHubStateSyncError,
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
            if "record-local-delivery.yml" in arguments:
                return CommandResult(
                    0,
                    json.dumps(
                        [
                            {
                                "databaseId": 99,
                                "displayTitle": (
                                    "Record local delivery " + "a" * 32
                                ),
                                "status": "completed",
                                "conclusion": "success",
                            }
                        ]
                    ),
                )
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
            if arguments[3] == "99":
                return CommandResult(
                    0,
                    json.dumps(
                        {
                            "jobs": [
                                {
                                    "name": "record-delivery",
                                    "steps": [
                                        {
                                            "name": "Save delivery state",
                                            "conclusion": "success",
                                        }
                                    ],
                                }
                            ]
                        }
                    ),
                )
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

    dispatch_index = next(
        index
        for index, call in enumerate(fake.calls)
        if call[1:3]
        == ("api", "repos/bgu436475-ops/Baic-AI-Message-Bot/dispatches")
    )
    assert json.loads(fake.stdin[dispatch_index] or "") == {
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


def test_github_cli_confirms_the_associated_recorder_cache_before_syncing() -> None:
    """Dispatch acceptance alone does not prove that GitHub persisted the local send."""
    delivery_id = "a" * 32

    class RecorderRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []
            self.polls = 0

        def __call__(
            self,
            arguments: tuple[str, ...],
            stdin: str | None = None,
        ) -> CommandResult:
            del stdin
            self.calls.append(arguments)
            if arguments[1:3] == (
                "api",
                "repos/bgu436475-ops/Baic-AI-Message-Bot/dispatches",
            ):
                return CommandResult(0, "")
            if arguments[1:3] == ("run", "list"):
                self.polls += 1
                return CommandResult(
                    0,
                    json.dumps(
                        [
                            {
                                "databaseId": 99,
                                "displayTitle": (
                                    f"Record local delivery {delivery_id}"
                                ),
                                "status": (
                                    "completed"
                                    if self.polls == 2
                                    else "in_progress"
                                ),
                                "conclusion": (
                                    "success" if self.polls == 2 else None
                                ),
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
                                    "name": "record-delivery",
                                    "steps": [
                                        {
                                            "name": "Save delivery state",
                                            "conclusion": "success",
                                        }
                                    ],
                                }
                            ]
                        }
                    ),
                )
            raise AssertionError(f"unexpected command: {arguments}")

    runner = RecorderRunner()
    sleeps: list[float] = []
    client = GitHubCLIClient(
        Path("/usr/local/bin/gh"),
        command_runner=runner,
        sync_sleep=sleeps.append,
        sync_monotonic=lambda: 0,
    )

    client.dispatch_local_delivery(DAY, delivery_id, "published")

    assert runner.polls == 2
    assert sleeps == [2]
    assert any(
        "record-local-delivery.yml" in command
        and "repository_dispatch" in command
        for command in runner.calls
    )
    assert any(command[1:3] == ("run", "view") for command in runner.calls)


def test_github_cli_keeps_sync_unconfirmed_when_recorder_fails() -> None:
    """A failed recorder workflow must not clear the local cloud-sync pending bit."""
    delivery_id = "a" * 32

    def failed_recorder(
        arguments: tuple[str, ...], stdin: str | None = None
    ) -> CommandResult:
        del stdin
        if arguments[1:3] == (
            "api",
            "repos/bgu436475-ops/Baic-AI-Message-Bot/dispatches",
        ):
            return CommandResult(0, "")
        if arguments[1:3] == ("run", "list"):
            return CommandResult(
                0,
                json.dumps(
                    [
                        {
                            "databaseId": 99,
                            "displayTitle": f"Record local delivery {delivery_id}",
                            "status": "completed",
                            "conclusion": "failure",
                        }
                    ]
                ),
            )
        raise AssertionError(f"unexpected command: {arguments}")

    client = GitHubCLIClient(
        Path("/usr/local/bin/gh"), command_runner=failed_recorder
    )

    with pytest.raises(GitHubStateSyncError, match="cloud_sync_failed"):
        client.dispatch_local_delivery(DAY, delivery_id, "published")


def test_github_cli_keeps_sync_unconfirmed_when_recorder_workflow_is_missing() -> None:
    """A missing remote recorder must block sync completion rather than accept dispatch."""
    def missing_workflow(
        arguments: tuple[str, ...], stdin: str | None = None
    ) -> CommandResult:
        del stdin
        if arguments[1:3] == (
            "api",
            "repos/bgu436475-ops/Baic-AI-Message-Bot/dispatches",
        ):
            return CommandResult(0, "")
        if arguments[1:3] == ("run", "list"):
            return CommandResult(1, "", "workflow not found")
        raise AssertionError(f"unexpected command: {arguments}")

    client = GitHubCLIClient(
        Path("/usr/local/bin/gh"), command_runner=missing_workflow
    )

    with pytest.raises(GitHubStateSyncError, match="cloud_sync_unavailable"):
        client.dispatch_local_delivery(DAY, "a" * 32, "published")


def test_github_cli_keeps_sync_unconfirmed_when_recorder_times_out() -> None:
    """An accepted dispatch with no associated recorder run is still indeterminate."""
    def no_recorder(
        arguments: tuple[str, ...], stdin: str | None = None
    ) -> CommandResult:
        del stdin
        if arguments[1:3] == (
            "api",
            "repos/bgu436475-ops/Baic-AI-Message-Bot/dispatches",
        ):
            return CommandResult(0, "")
        if arguments[1:3] == ("run", "list"):
            return CommandResult(0, "[]")
        raise AssertionError(f"unexpected command: {arguments}")

    monotonic_ticks = iter((0.0, 0.0, 3.0))
    client = GitHubCLIClient(
        Path("/usr/local/bin/gh"),
        command_runner=no_recorder,
        sync_monotonic=lambda: next(monotonic_ticks),
        sync_timeout_seconds=3,
        sync_sleep=lambda _: None,
    )

    with pytest.raises(GitHubStateSyncError, match="cloud_sync_timeout"):
        client.dispatch_local_delivery(DAY, "a" * 32, "published")


def test_github_cli_scans_more_than_thirty_runs_for_current_day_success() -> None:
    """Normal historical volume must not hide a current-day successful send."""
    runs = [
        {
            "databaseId": index + 1,
            "event": "repository_dispatch",
            "status": "completed",
            "conclusion": "failure",
            "createdAt": "2026-08-03T01:05:00Z",
            "url": f"https://github.com/o/r/actions/runs/{index + 1}",
        }
        for index in range(31)
    ]

    def capped_runs(
        arguments: tuple[str, ...], stdin: str | None = None
    ) -> CommandResult:
        del stdin
        if arguments[1:4] == ("api", "-i", "rate_limit"):
            return CommandResult(
                0,
                "HTTP/2 200 OK\r\nDate: Mon, 03 Aug 2026 02:00:00 GMT\r\n\r\n{}",
            )
        if arguments[1:3] == ("run", "list"):
            return CommandResult(0, json.dumps(runs))
        if arguments[1:3] == ("run", "view"):
            conclusion = "success" if arguments[3] == "31" else "failure"
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
                                        "conclusion": conclusion,
                                    }
                                ],
                            }
                        ]
                    }
                ),
            )
        if arguments[1:3] == (
            "api",
            "repos/bgu436475-ops/Baic-AI-Message-Bot/contents/"
            "web/public/data/latest.json?ref=main",
        ):
            return CommandResult(1, "", "404")
        raise AssertionError(f"unexpected command: {arguments}")

    client = GitHubCLIClient(
        Path("/usr/local/bin/gh"), command_runner=capped_runs
    )

    result = evaluate_cloud_snapshot(DAY, client.snapshot(DAY))

    assert result.decision == "skip_delivered"


def test_github_cli_sync_scans_more_than_thirty_recorder_runs(
) -> None:
    """The just-dispatched recorder must remain discoverable after normal history."""
    delivery_id = "a" * 32
    recorder_runs = [
        {
            "databaseId": index + 1,
            "displayTitle": f"unrelated recorder run {index}",
            "status": "completed",
            "conclusion": "success",
        }
        for index in range(30)
    ] + [
        {
            "databaseId": 99,
            "displayTitle": f"Record local delivery {delivery_id}",
            "status": "completed",
            "conclusion": "success",
        }
    ]

    def historical_recorder_runs(
        arguments: tuple[str, ...], stdin: str | None = None
    ) -> CommandResult:
        del stdin
        if arguments[1:3] == (
            "api",
            "repos/bgu436475-ops/Baic-AI-Message-Bot/dispatches",
        ):
            return CommandResult(0, "")
        if arguments[1:3] == ("run", "list"):
            return CommandResult(0, json.dumps(recorder_runs))
        if arguments[1:3] == ("run", "view") and arguments[3] == "99":
            return CommandResult(
                0,
                json.dumps(
                    {
                        "jobs": [
                            {
                                "name": "record-delivery",
                                "steps": [
                                    {
                                        "name": "Save delivery state",
                                        "conclusion": "success",
                                    }
                                ],
                            }
                        ]
                    }
                ),
            )
        raise AssertionError(f"unexpected command: {arguments}")

    client = GitHubCLIClient(
        Path("/usr/local/bin/gh"),
        command_runner=historical_recorder_runs,
        sync_monotonic=lambda: 0,
    )

    client.dispatch_local_delivery(DAY, delivery_id, "published")


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
