from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_news_bot.feishu import FeishuDeliveryRejected, FeishuDeliveryUncertain
from ai_news_bot.local_fallback import (
    GitHubStateSyncError,
    LocalFallbackConfig,
    LocalFallbackDependencies,
    _clock_checked_cloud_gate,
    load_local_environment,
    ollama_preflight_reason,
    parse_args,
    preflight_reason,
    prune_runtime_artifacts,
    run_local_fallback,
    set_process_timezone,
)
from ai_news_bot import local_fallback
from ai_news_bot.local_gate import (
    CloudGateResult,
    CloudRun,
    CloudSnapshot,
    RemoteDigestProbe,
)
from ai_news_bot.local_state import FallbackLedger
from ai_news_bot.models import (
    DigestBoards,
    EditorialDigest,
    GlobalPipelineStats,
    PipelineStats,
)
from ai_news_bot.send_ledger import SendLedger


DAY = date(2026, 8, 3)
NOW = datetime(2026, 8, 3, 2, 0, tzinfo=UTC)


def _empty_digest() -> EditorialDigest:
    return EditorialDigest(
        run_status="no_qualifying_items",
        generated_at=NOW,
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


class Calls:
    def __init__(self, values: list[object] | None = None) -> None:
        self.values = values or []
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object) -> object:
        self.calls.append(args)
        value = self.values.pop(0) if self.values else None
        if isinstance(value, BaseException):
            raise value
        return value


@pytest.fixture
def config(tmp_path: Path) -> LocalFallbackConfig:
    return LocalFallbackConfig(
        runtime_root=tmp_path / "runtime",
        env_path=tmp_path / ".env",
        gh_path=Path("/usr/local/bin/gh"),
        ollama_app_path=Path("/Applications/Ollama.app"),
        repository="owner/repository",
    )


@pytest.fixture
def deps(config: LocalFallbackConfig) -> LocalFallbackDependencies:
    digest = _empty_digest()
    generate = Calls([digest])

    def write_generated(path: Path) -> EditorialDigest:
        generate(path)
        path.write_text(digest.model_dump_json(), encoding="utf-8")
        return digest

    return LocalFallbackDependencies(
        cloud_gate=Calls(
            [
                CloudGateResult("run_local", "cloud_failed"),
                CloudGateResult("run_local", "cloud_failed"),
                CloudGateResult("run_local", "cloud_failed"),
            ]
        ),
        generate=write_generated,
        send=Calls([digest]),
        dispatch_delivery=Calls(),
        publish_dashboard=Calls(),
        notify=Calls(),
        send_ledger=SendLedger(config.runtime_root / "state" / "daily_sends.json"),
        fallback_ledger=FallbackLedger(
            config.runtime_root / "state" / "fallback.json"
        ),
        now=lambda: NOW,
        sleep=lambda _: None,
        preflight=lambda _: None,
    )


def test_cloud_success_never_generates_or_sends(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """Changing the delivered branch to run local would duplicate Feishu."""
    gate = Calls([CloudGateResult("skip_delivered", "cloud_send_step")])
    deps.cloud_gate = gate
    generated: list[Path] = []
    deps.generate = lambda path: generated.append(path) or _empty_digest()

    assert run_local_fallback(config, deps) == 0

    assert generated == []
    assert deps.send.calls == []  # type: ignore[attr-defined]


def test_unknown_cloud_reason_is_redacted_from_notifications(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """Forwarding an untrusted cloud reason could disclose a secret in macOS."""
    deps.cloud_gate = Calls([CloudGateResult("blocked", "actualsecretvalue")])

    assert run_local_fallback(config, deps) == 2

    assert deps.notify.calls == [("local_fallback_failed",)]  # type: ignore[attr-defined]


def test_cloud_failure_generates_rechecks_and_sends_once(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """Removing the second gate would let a delayed cloud send race local send."""
    assert run_local_fallback(config, deps) == 0

    assert len(deps.cloud_gate.calls) == 3  # type: ignore[attr-defined]
    assert len(deps.send.calls) == 1  # type: ignore[attr-defined]
    assert len(deps.dispatch_delivery.calls) == 1  # type: ignore[attr-defined]


def test_delayed_cloud_success_on_second_gate_discards_local_preview(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """Sending after a newly delivered cloud result would create a duplicate."""
    deps.cloud_gate = Calls(
        [
            CloudGateResult("run_local", "cloud_failed"),
            CloudGateResult("skip_delivered", "cloud_completed_during_generation"),
        ]
    )

    assert run_local_fallback(config, deps) == 0

    assert len(deps.send.calls) == 0  # type: ignore[attr-defined]


def test_final_cloud_gate_blocks_a_delayed_cloud_delivery(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """A cloud run that finishes after preview generation must still block Feishu."""
    deps.cloud_gate = Calls(
        [
            CloudGateResult("run_local", "cloud_failed"),
            CloudGateResult("run_local", "cloud_failed"),
            CloudGateResult("skip_delivered", "cloud_completed_before_send"),
        ]
    )

    assert run_local_fallback(config, deps) == 0

    assert len(deps.cloud_gate.calls) == 3  # type: ignore[attr-defined]
    assert deps.send.calls == []  # type: ignore[attr-defined]
    assert deps.fallback_ledger.day_state(DAY) is None


def test_local_send_waits_until_the_cloud_window_is_closed(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """An early local clock must fail closed instead of sending before 09:50."""
    deps.now = lambda: datetime(2026, 8, 3, 1, 40, tzinfo=UTC)
    generate = Calls([_empty_digest()])
    deps.generate = generate  # type: ignore[assignment]

    assert run_local_fallback(config, deps) == 2

    assert len(deps.cloud_gate.calls) == 1  # type: ignore[attr-defined]
    assert generate.calls == []
    assert deps.send.calls == []  # type: ignore[attr-defined]
    assert deps.notify.calls == [("cloud_schedule_window_open",)]  # type: ignore[attr-defined]


def test_primary_mode_sends_before_cloud_window_without_cloud_gate(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """Primary mode must not retain fallback-only cloud waiting behavior."""
    config = LocalFallbackConfig(
        **{
            **config.__dict__,
            "primary_mode": True,
            "scheduled": True,
        }
    )
    deps.now = lambda: datetime(2026, 8, 3, 1, 5, tzinfo=UTC)

    assert run_local_fallback(config, deps) == 0

    assert deps.cloud_gate.calls == []  # type: ignore[attr-defined]
    assert len(deps.send.calls) == 1  # type: ignore[attr-defined]


def test_local_send_refreshes_the_beijing_clock_after_a_cloud_gate_wait(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """The 09:50 decision must use time observed after cloud polling completes."""
    deps.now = lambda: datetime(2026, 8, 3, 1, 35, tzinfo=UTC)
    gate_calls = 0

    def gate(_: date) -> CloudGateResult:
        nonlocal gate_calls
        gate_calls += 1
        if gate_calls == 1:
            deps.now = lambda: datetime(2026, 8, 3, 1, 50, tzinfo=UTC)
        return CloudGateResult("run_local", "cloud_failed")

    deps.cloud_gate = gate

    assert run_local_fallback(config, deps) == 0

    assert gate_calls == 3
    assert len(deps.send.calls) == 1  # type: ignore[attr-defined]


def test_corrupt_send_ledger_blocks_new_send_and_pending_sync(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """Malformed delivery evidence must never be treated as a blank ledger."""
    deps.send_ledger.path.parent.mkdir(parents=True)
    deps.send_ledger.path.write_text("not json", encoding="utf-8")
    deps.fallback_ledger.mark_sent(
        DAY,
        "a" * 32,
        "published",
        at=NOW,
        cloud_sync_pending=True,
    )

    assert run_local_fallback(config, deps) == 2

    assert deps.send.calls == []  # type: ignore[attr-defined]
    assert deps.dispatch_delivery.calls == []  # type: ignore[attr-defined]
    assert deps.notify.calls == [("local_send_ledger_invalid",)]  # type: ignore[attr-defined]


def test_no_qualifying_items_is_a_valid_send(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """Rejecting a schema-valid empty board would weaken the agreed delivery contract."""
    assert run_local_fallback(config, deps) == 0

    state = deps.fallback_ledger.day_state(DAY)
    assert state is not None
    assert state.delivery_status == "sent"
    assert state.run_status == "no_qualifying_items"


def test_invalid_persisted_digest_never_reaches_feishu(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """Skipping persisted-artifact validation could send an invalid preview."""
    def generate_invalid(path: Path) -> EditorialDigest:
        path.write_text("{}", encoding="utf-8")
        return _empty_digest()

    deps.generate = generate_invalid

    assert run_local_fallback(config, deps) == 2

    assert deps.send.calls == []  # type: ignore[attr-defined]


def test_feishu_timeout_records_uncertain_and_never_dispatches(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """Retrying an indeterminate delivery could produce a second card."""
    deps.send = Calls([FeishuDeliveryUncertain("webhook-secret")])

    assert run_local_fallback(config, deps) == 2

    state = deps.fallback_ledger.day_state(DAY)
    assert state is not None
    assert state.delivery_status == "uncertain_delivery"
    assert deps.dispatch_delivery.calls == []  # type: ignore[attr-defined]
    assert all("webhook-secret" not in str(call) for call in deps.notify.calls)  # type: ignore[attr-defined]


def test_interrupted_send_is_durably_uncertain_before_feishu(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """An interrupt after request dispatch must not permit a same-day retry."""
    deps.send = Calls([KeyboardInterrupt()])

    with pytest.raises(KeyboardInterrupt):
        run_local_fallback(config, deps)

    assert deps.fallback_ledger.blocks_send(DAY) is True
    assert deps.send_ledger.was_sent(DAY) is False
    assert run_local_fallback(config, deps) == 2
    assert len(deps.send.calls) == 1  # type: ignore[attr-defined]


def test_definite_feishu_rejection_transitions_pre_send_state_to_failed(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """A rejected request is retryable state, unlike an indeterminate request."""
    deps.send = Calls([FeishuDeliveryRejected("ignored")])

    assert run_local_fallback(config, deps) == 2

    state = deps.fallback_ledger.day_state(DAY)
    assert state is not None
    assert state.delivery_status == "failed"
    assert deps.send_ledger.was_sent(DAY) is False


def test_sync_failure_never_resends_and_retries_only_sync(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """Regenerating after confirmed delivery would risk resending Feishu."""
    deps.dispatch_delivery = Calls([GitHubStateSyncError("sync-secret"), None])

    assert run_local_fallback(config, deps) == 2
    state = deps.fallback_ledger.day_state(DAY)
    assert state is not None
    assert state.delivery_status == "sent"
    assert state.cloud_sync_pending is True

    assert run_local_fallback(config, deps) == 0

    assert len(deps.send.calls) == 1  # type: ignore[attr-defined]
    assert len(deps.dispatch_delivery.calls) == 2  # type: ignore[attr-defined]


def test_dashboard_failure_is_retried_without_resending(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """Retrying the full flow after dashboard failure would duplicate Feishu."""
    config = LocalFallbackConfig(
        **{**config.__dict__, "dashboard_enabled": True}
    )
    deps.publish_dashboard = Calls([RuntimeError("dashboard-secret"), None])

    assert run_local_fallback(config, deps) == 2
    state = deps.fallback_ledger.day_state(DAY)
    assert state is not None
    assert state.dashboard_pending is True

    assert run_local_fallback(config, deps) == 0

    assert len(deps.send.calls) == 1  # type: ignore[attr-defined]
    assert len(deps.publish_dashboard.calls) == 2  # type: ignore[attr-defined]


def test_strict_environment_rejects_unsafe_and_permissive_files(
    tmp_path: Path,
) -> None:
    """Accepting shell syntax or public secret files could expose credentials."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "FEISHU_WEBHOOK_URL=https://open.feishu.cn/hook/token\n"
        "OLLAMA_MODEL=$(curl example.test)\n",
        encoding="utf-8",
    )
    env_path.chmod(0o600)

    with pytest.raises(ValueError, match="invalid_local_environment"):
        load_local_environment(env_path)

    env_path.write_text("FEISHU_WEBHOOK_URL=https://open.feishu.cn/hook/token\n")
    env_path.chmod(0o644)
    with pytest.raises(ValueError, match="invalid_local_environment"):
        load_local_environment(env_path)


def test_strict_environment_rejects_blank_lines(tmp_path: Path) -> None:
    """Ignoring non-assignment lines would violate the literal file format."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "FEISHU_WEBHOOK_URL=https://open.feishu.cn/hook/first\n\n",
        encoding="utf-8",
    )
    env_path.chmod(0o600)

    with pytest.raises(ValueError, match="invalid_local_environment"):
        load_local_environment(env_path)


def test_strict_environment_rejects_unicode_control_characters(
    tmp_path: Path,
) -> None:
    """C1 controls must not be accepted merely because they are not ASCII."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "FEISHU_WEBHOOK_URL=https://open.feishu.cn/hook/token\u009bvalue\n",
        encoding="utf-8",
    )
    env_path.chmod(0o600)

    with pytest.raises(ValueError, match="invalid_local_environment"):
        load_local_environment(env_path)


def test_unknown_timezone_fails_closed_before_generation(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """Treating an unclassifiable local date as sendable could duplicate today."""
    config = LocalFallbackConfig(**{**config.__dict__, "timezone": "Missing/Zone"})

    assert run_local_fallback(config, deps) == 2

    assert deps.send.calls == []  # type: ignore[attr-defined]


def test_scheduled_preflight_requires_shanghai_timezone_symlink(
    tmp_path: Path,
    config: LocalFallbackConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allowing a scheduled run under another system day can duplicate delivery."""
    zone = tmp_path / "zoneinfo" / "Asia" / "Shanghai"
    zone.parent.mkdir(parents=True)
    zone.write_text("zone", encoding="utf-8")
    localtime = tmp_path / "localtime"
    localtime.symlink_to(zone)
    config = LocalFallbackConfig(
        **{
            **config.__dict__,
            "scheduled": True,
            "localtime_path": localtime,
            "minimum_free_bytes": 0,
        }
    )
    monkeypatch.setattr(local_fallback, "ollama_preflight_reason", lambda *args: None)

    assert preflight_reason(config, lambda _: None) is None

    other_zone = tmp_path / "zoneinfo" / "America" / "New_York"
    other_zone.parent.mkdir(parents=True)
    other_zone.write_text("zone", encoding="utf-8")
    localtime.unlink()
    localtime.symlink_to(other_zone)
    assert preflight_reason(config, lambda _: None) == "timezone_mismatch"


def test_preflight_blocks_when_free_space_is_below_minimum(
    config: LocalFallbackConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generating without model headroom could leave an incomplete local run."""
    monkeypatch.setattr(
        local_fallback.shutil,
        "disk_usage",
        lambda _: SimpleNamespace(free=8 * 1024**3 - 1),
    )

    assert preflight_reason(config, lambda _: None) == "insufficient_disk_space"


def test_ollama_preflight_rejects_a_missing_model_without_starting_download(
    config: LocalFallbackConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Treating a reachable but model-less runtime as ready could pull at schedule time."""
    monkeypatch.setattr(local_fallback, "_ollama_models", lambda _: set())

    assert ollama_preflight_reason(config, lambda _: None) == "ollama_model_missing"


def test_ollama_tags_check_uses_the_proxy_disabled_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A loopback tags health check must not honor HTTP proxy environment variables."""
    session_calls: list[str] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"models": [{"name": "qwen3:8b"}]}

    class Session:
        def get(self, url: str, *, timeout: int) -> Response:
            session_calls.append(url)
            assert timeout == 2
            return Response()

        def close(self) -> None:
            return None

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.test:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.test:8443")
    monkeypatch.setattr(
        local_fallback,
        "create_ollama_session",
        lambda: Session(),
    )

    assert local_fallback._ollama_models("http://127.0.0.1:11434/v1") == {
        "qwen3:8b"
    }
    assert session_calls == ["http://127.0.0.1:11434/api/tags"]


def test_github_clock_drift_blocks_the_local_gate(
    config: LocalFallbackConfig,
) -> None:
    """Ignoring a stale local clock could make the date gate evaluate the wrong day."""
    class DriftedClient:
        def snapshot(self, day: date) -> CloudSnapshot:
            del day
            return CloudSnapshot(
                runs=(),
                remote_digest=RemoteDigestProbe("missing"),
                server_time=datetime(2026, 8, 3, 2, 6, tzinfo=UTC),
            )

    gate = _clock_checked_cloud_gate(
        DriftedClient(),  # type: ignore[arg-type]
        config,
        lambda: NOW,
        lambda _: None,
    )

    assert gate(DAY) == CloudGateResult("blocked", "github_clock_drift")


def test_active_cloud_uses_local_deadline_when_server_time_is_stale(
    config: LocalFallbackConfig,
) -> None:
    """A stale GitHub Date header must not make local polling pass 09:50."""
    class StaleServerClient:
        def snapshot(self, day: date) -> CloudSnapshot:
            return CloudSnapshot(
                runs=(
                    CloudRun(
                        run_id=1,
                        event="schedule",
                        status="in_progress",
                        conclusion=None,
                        created_at=datetime(day.year, day.month, day.day, 1, tzinfo=UTC),
                        url="https://github.com/owner/repository/actions/runs/1",
                        send_step_conclusion=None,
                    ),
                ),
                remote_digest=RemoteDigestProbe("missing"),
                server_time=datetime(day.year, day.month, day.day, 1, 49, tzinfo=UTC),
            )

    def no_sleep(seconds: float) -> None:
        raise AssertionError(f"unexpected polling sleep: {seconds}")

    gate = _clock_checked_cloud_gate(
        StaleServerClient(),  # type: ignore[arg-type]
        config,
        lambda: datetime(2026, 8, 3, 1, 50, tzinfo=UTC),
        no_sleep,
    )

    result = gate(DAY)
    assert result.decision == "blocked"
    assert result.reason_code == "cloud_wait_timeout"


def test_active_cloud_does_not_use_server_time_as_the_local_cutoff(
    config: LocalFallbackConfig,
) -> None:
    """A valid +5-minute server skew must not end local polling at 09:45."""
    class SlightlyAheadServerClient:
        def snapshot(self, day: date) -> CloudSnapshot:
            return CloudSnapshot(
                runs=(
                    CloudRun(
                        run_id=1,
                        event="schedule",
                        status="in_progress",
                        conclusion=None,
                        created_at=datetime(day.year, day.month, day.day, 1, tzinfo=UTC),
                        url="https://github.com/owner/repository/actions/runs/1",
                        send_step_conclusion=None,
                    ),
                ),
                remote_digest=RemoteDigestProbe("missing"),
                server_time=datetime(day.year, day.month, day.day, 1, 50, tzinfo=UTC),
            )

    class PollingContinues(Exception):
        pass

    sleeps: list[float] = []

    def stop_after_poll_interval(seconds: float) -> None:
        sleeps.append(seconds)
        raise PollingContinues

    gate = _clock_checked_cloud_gate(
        SlightlyAheadServerClient(),  # type: ignore[arg-type]
        config,
        lambda: datetime(2026, 8, 3, 1, 45, tzinfo=UTC),
        stop_after_poll_interval,
    )

    with pytest.raises(PollingContinues):
        gate(DAY)
    assert sleeps == [60]


def test_completed_cloud_failure_waits_until_the_local_deadline(
    config: LocalFallbackConfig,
) -> None:
    """A conclusive early cloud failure must not make the local path send at 09:35."""
    class FailedCloudClient:
        def __init__(self) -> None:
            self.calls = 0

        def snapshot(self, day: date) -> CloudSnapshot:
            self.calls += 1
            return CloudSnapshot(
                runs=(),
                remote_digest=RemoteDigestProbe("missing"),
                server_time=datetime(
                    day.year,
                    day.month,
                    day.day,
                    1,
                    30 + 10 * self.calls,
                    tzinfo=UTC,
                ),
            )

    timestamps = iter(
        [
            datetime(2026, 8, 3, 1, 40, tzinfo=UTC),
            datetime(2026, 8, 3, 1, 50, tzinfo=UTC),
        ]
    )
    sleeps: list[float] = []
    gate = _clock_checked_cloud_gate(
        FailedCloudClient(),  # type: ignore[arg-type]
        config,
        lambda: next(timestamps),
        sleeps.append,
    )

    assert gate(DAY).decision == "run_local"
    assert sleeps == [60]


def test_stale_pending_delivery_blocks_a_new_day_send(
    deps: LocalFallbackDependencies,
    config: LocalFallbackConfig,
) -> None:
    """Dispatching a prior date is forbidden, so a stale pending state blocks rollover."""
    previous_day = date(2026, 8, 2)
    deps.fallback_ledger.mark_sent(
        previous_day,
        "a" * 32,
        "published",
        at=NOW,
        cloud_sync_pending=True,
    )

    assert run_local_fallback(config, deps) == 2

    assert deps.send.calls == []  # type: ignore[attr-defined]
    assert deps.dispatch_delivery.calls == []  # type: ignore[attr-defined]
    assert deps.notify.calls == [("stale_pending_delivery",)]  # type: ignore[attr-defined]


def test_retention_keeps_recent_runs_and_removes_old_logs(tmp_path: Path) -> None:
    """Keeping every artifact forever would exhaust the fallback runtime disk."""
    runtime = tmp_path / "runtime"
    runs = runtime / "runs"
    logs = runtime / "logs"
    runs.mkdir(parents=True)
    logs.mkdir()
    for index in range(16):
        path = runs / f"202608{index:02d}T020000Z"
        path.mkdir()
        os.utime(path, (index, index))
    old_log = logs / "old.log"
    old_log.write_text("reason_code=old", encoding="utf-8")
    os.utime(old_log, (0, 0))
    recent_log = logs / "recent.log"
    recent_log.write_text("reason_code=recent", encoding="utf-8")
    os.utime(recent_log, (NOW.timestamp(), NOW.timestamp()))

    prune_runtime_artifacts(runtime, NOW)

    assert len([path for path in runs.iterdir() if path.is_dir()]) == 14
    assert old_log.exists() is False
    assert recent_log.exists() is True


def test_retention_uses_the_configured_external_log_directory(tmp_path: Path) -> None:
    """Ignoring the configured log root would retain private logs indefinitely."""
    runtime = tmp_path / "runtime"
    external_logs = tmp_path / "Library" / "Logs" / "Baic-AI-Message-Bot"
    external_logs.mkdir(parents=True)
    old_log = external_logs / "old.log"
    old_log.write_text("reason_code=old", encoding="utf-8")
    os.utime(old_log, (0, 0))

    prune_runtime_artifacts(runtime, NOW, logs_root=external_logs)

    assert old_log.exists() is False


def test_console_modes_keep_the_cloud_gate_and_reject_force_send() -> None:
    """A force-send CLI flag would expose an unsafe Desktop bypass path."""
    assert parse_args(["--scheduled"]).scheduled is True
    assert parse_args(["--run-now"]).run_now is True
    assert parse_args(["--check-only"]).check_only is True
    assert parse_args(["--dry-run"]).dry_run is True
    assert parse_args(["--primary-scheduled"]).primary_scheduled is True

    with pytest.raises(SystemExit):
        parse_args(["--force-send"])


def test_runner_configures_diagnostic_logging_for_launchd_stderr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Without a logging handler, documented launchd diagnostic files stay empty."""
    configured: dict[str, object] = {}
    monkeypatch.setattr(
        local_fallback.logging,
        "basicConfig",
        lambda **kwargs: configured.update(kwargs),
    )
    monkeypatch.setattr(
        local_fallback,
        "load_local_environment",
        lambda _: (_ for _ in ()).throw(ValueError("invalid")),
    )

    assert local_fallback.main(["--runtime-root", str(tmp_path / "runtime")]) == 2

    assert configured["level"] == local_fallback.logging.INFO
    assert configured["stream"] is sys.stderr
    assert "%(levelname)s" in str(configured["format"])


def test_runner_sets_the_process_timezone_before_native_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leaving the process timezone unchanged can make child code use another day."""
    calls: list[str] = []
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setattr(local_fallback.monotonic_time, "tzset", lambda: calls.append("tzset"))

    set_process_timezone("Asia/Shanghai")

    assert os.environ["TZ"] == "Asia/Shanghai"
    assert calls == ["tzset"]
