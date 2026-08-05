from __future__ import annotations

import argparse
import contextlib
import logging
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time as monotonic_time
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from .cli import run as run_editorial_cli
from .cli import send_existing_daily_result
from .config import Settings
from .feishu import FeishuDeliveryRejected, FeishuDeliveryUncertain
from .local_gate import (
    CloudGateResult,
    GitHubCLIClient,
    GitHubStateSyncError,
    evaluate_cloud_snapshot,
)
from .local_state import (
    FallbackLedger,
    FallbackStateError,
    LocalDayState,
    LocalRunAlreadyActive,
    exclusive_run_lock,
)
from .model_backend import create_ollama_session, normalize_ollama_base_url
from .models import EditorialDigest
from .send_ledger import SendLedger, SendLedgerCorruptionError


LOGGER = logging.getLogger(__name__)
_REASON_CODE = re.compile(r"[a-z0-9_]{1,64}\Z")
_SAFE_REASON_CODES = frozenset(
    {
        "cloud_gate_invalid",
        "cloud_gate_unavailable",
        "cloud_run_active",
        "cloud_snapshot_unavailable",
        "cloud_schedule_window_open",
        "cloud_sync_pending",
        "cloud_wait_timeout",
        "dashboard_digest_missing",
        "dashboard_pending",
        "disk_space_unavailable",
        "feishu_delivery_rejected",
        "github_clock_drift",
        "github_clock_invalid",
        "insufficient_disk_space",
        "invalid_local_digest",
        "invalid_local_environment",
        "invalid_local_state",
        "local_fallback_clock_invalid",
        "local_fallback_failed",
        "local_send_ledger_delivered",
        "local_send_ledger_invalid",
        "local_state_invalid",
        "local_state_write_failed",
        "ollama_model_missing",
        "ollama_unavailable",
        "ollama_url_invalid",
        "preflight_failed",
        "remote_digest_exists",
        "remote_digest_invalid",
        "remote_digest_malformed",
        "remote_digest_unknown",
        "stale_pending_delivery",
        "timezone_mismatch",
        "uncertain_delivery",
    }
)
_ENVIRONMENT_KEY = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_UNSAFE_ENV_VALUE = re.compile(r"[\$`;|&<>()\\]")
_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "AI_BACKEND",
        "FEISHU_SIGNING_SECRET",
        "FEISHU_WEBHOOK_URL",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "SITE_BYPASS_TOKEN",
        "SITE_DIGEST_ENDPOINT",
        "SITE_DIGEST_UPDATE_SECRET",
    }
)
_SUCCESSFUL_RUN_STATUS = frozenset({"published", "no_qualifying_items"})


@dataclass(frozen=True)
class LocalFallbackConfig:
    runtime_root: Path
    env_path: Path
    gh_path: Path
    ollama_app_path: Path
    repository: str
    cloud_wait_deadline: time = time(9, 50)
    timezone: str = "Asia/Shanghai"
    model: str = "qwen3:8b"
    minimum_free_bytes: int = 8 * 1024**3
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    scheduled: bool = False
    primary_mode: bool = False
    check_only: bool = False
    dry_run: bool = False
    dashboard_enabled: bool = False
    localtime_path: Path = Path("/etc/localtime")
    logs_root: Path | None = None
    sources_path: Path | None = None


@dataclass
class LocalFallbackDependencies:
    cloud_gate: Callable[[date], CloudGateResult]
    generate: Callable[[Path], EditorialDigest]
    send: Callable[[Path], EditorialDigest]
    dispatch_delivery: Callable[[date, str, str], None]
    publish_dashboard: Callable[[Path], None]
    notify: Callable[[str], None]
    send_ledger: SendLedger
    fallback_ledger: FallbackLedger
    now: Callable[[], datetime]
    sleep: Callable[[float], None]
    preflight: Callable[[LocalFallbackConfig], str | None] | None = None


def _safe_reason_code(value: str) -> str:
    if _REASON_CODE.fullmatch(value) and value in _SAFE_REASON_CODES:
        return value
    return "local_fallback_failed"


def _report(dependencies: LocalFallbackDependencies, reason_code: str) -> None:
    safe_reason = _safe_reason_code(reason_code)
    LOGGER.info("local_fallback_reason=%s", safe_reason)
    try:
        dependencies.notify(safe_reason)
    except Exception:
        # A notification is never allowed to turn a safe no-send outcome into
        # a retry path, and its failure must not leak command output.
        LOGGER.info("local_fallback_reason=notification_failed")


def load_local_environment(path: Path) -> dict[str, str]:
    """Read a literal, protected local environment file without shell parsing."""
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise ValueError("invalid_local_environment")
        raw = path.read_bytes()
    except (OSError, ValueError) as error:
        raise ValueError("invalid_local_environment") from error
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("invalid_local_environment") from error
    if "\x00" in text or "\r" in text:
        raise ValueError("invalid_local_environment")

    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line:
            raise ValueError("invalid_local_environment")
        if any(
            ord(character) < 32
            or ord(character) == 127
            or unicodedata.category(character).startswith("C")
            for character in line
        ):
            raise ValueError("invalid_local_environment")
        key, separator, value = line.partition("=")
        if (
            not separator
            or not _ENVIRONMENT_KEY.fullmatch(key)
            or key not in _ENVIRONMENT_ALLOWLIST
            or key in values
            or _UNSAFE_ENV_VALUE.search(value)
        ):
            raise ValueError("invalid_local_environment")
        values[key] = value
    if values.get("AI_BACKEND", "ollama") != "ollama":
        raise ValueError("invalid_local_environment")
    return values


def _ollama_tags_url(base_url: str) -> str:
    normalized = normalize_ollama_base_url(base_url)
    parsed = urlsplit(normalized)
    return urlunsplit((parsed.scheme, parsed.netloc, "/api/tags", "", ""))


def _ollama_models(base_url: str) -> set[str] | None:
    session = create_ollama_session()
    try:
        response = session.get(_ollama_tags_url(base_url), timeout=2)
        response.raise_for_status()
        payload = response.json()
    except (OSError, ValueError, requests.RequestException):
        return None
    finally:
        session.close()
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        return None
    names = {
        entry.get("name")
        for entry in payload["models"]
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    return {name for name in names if isinstance(name, str)}


def ollama_preflight_reason(
    config: LocalFallbackConfig,
    sleep: Callable[[float], None],
) -> str | None:
    """Confirm local Ollama health and a preinstalled model without pulling."""
    try:
        models = _ollama_models(config.ollama_base_url)
    except ValueError:
        return "ollama_url_invalid"
    if models is None:
        try:
            completed = subprocess.run(
                (
                    "/usr/bin/open",
                    "-gj",
                    "-a",
                    str(config.ollama_app_path),
                ),
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return "ollama_unavailable"
        if completed.returncode != 0:
            return "ollama_unavailable"
        deadline = monotonic_time.monotonic() + 30
        while models is None and monotonic_time.monotonic() < deadline:
            sleep(1)
            try:
                models = _ollama_models(config.ollama_base_url)
            except ValueError:
                return "ollama_url_invalid"
    if models is None:
        return "ollama_unavailable"
    if config.model not in models:
        return "ollama_model_missing"
    return None


def _system_timezone_matches(config: LocalFallbackConfig) -> bool:
    try:
        resolved = config.localtime_path.resolve(strict=True)
    except OSError:
        return False
    return resolved.as_posix().endswith(config.timezone)


def preflight_reason(
    config: LocalFallbackConfig,
    sleep: Callable[[float], None],
) -> str | None:
    if config.scheduled and not _system_timezone_matches(config):
        return "timezone_mismatch"
    try:
        free_bytes = shutil.disk_usage(config.runtime_root.parent).free
    except OSError:
        return "disk_space_unavailable"
    if free_bytes < config.minimum_free_bytes:
        return "insufficient_disk_space"
    return ollama_preflight_reason(config, sleep)


def _state_path(config: LocalFallbackConfig) -> Path:
    return config.runtime_root / "state"


def _logs_path(config: LocalFallbackConfig) -> Path:
    return config.logs_root or config.runtime_root / "logs"


def _shanghai_day(timestamp: datetime, timezone: str) -> date:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("local_fallback_clock_invalid")
    return timestamp.astimezone(ZoneInfo(timezone)).date()


def _cloud_schedule_window_reason(
    timestamp: datetime,
    expected_day: date,
    config: LocalFallbackConfig,
) -> str | None:
    """Require a reliable Beijing timestamp after the cloud schedule window."""
    try:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError
        deadline = config.cloud_wait_deadline
        if not isinstance(deadline, time) or deadline.tzinfo is not None:
            raise ValueError
        local_time = timestamp.astimezone(ZoneInfo(config.timezone))
        if local_time.date() != expected_day:
            raise ValueError
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return "local_fallback_clock_invalid"
    if local_time.time() < deadline:
        return "cloud_schedule_window_open"
    return None


def _latest_digest_path(config: LocalFallbackConfig) -> Path | None:
    runs_path = config.runtime_root / "runs"
    try:
        candidates = sorted(
            (
                path / "latest.json"
                for path in runs_path.iterdir()
                if path.is_dir() and (path / "latest.json").is_file()
            ),
            key=lambda path: path.parent.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    return candidates[0] if candidates else None


def _validated_digest(path: Path, expected_day: date, timezone: str) -> EditorialDigest:
    try:
        digest = EditorialDigest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError("invalid_local_digest") from error
    if _shanghai_day(digest.generated_at, timezone) != expected_day:
        raise ValueError("invalid_local_digest")
    return digest


def _run_directory(config: LocalFallbackConfig, now: datetime) -> Path:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("local_fallback_clock_invalid")
    name = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = config.runtime_root / "runs"
    candidate = root / name
    suffix = 1
    while candidate.exists():
        candidate = root / f"{name}-{suffix}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def _retry_pending_work(
    config: LocalFallbackConfig,
    dependencies: LocalFallbackDependencies,
    day: date,
    state: LocalDayState,
) -> int:
    if state.delivery_status != "sent":
        _report(dependencies, "uncertain_delivery")
        return 2
    if state.cloud_sync_pending:
        if state.delivery_id is None or state.run_status is None:
            _report(dependencies, "invalid_local_state")
            return 2
        try:
            dependencies.dispatch_delivery(day, state.delivery_id, state.run_status)
            dependencies.fallback_ledger.mark_sync_complete(
                day,
                at=dependencies.now(),
            )
        except Exception:
            _report(dependencies, "cloud_sync_pending")
            return 2
        state = dependencies.fallback_ledger.day_state(day) or state
    if state.dashboard_pending:
        path = _latest_digest_path(config)
        if path is None:
            _report(dependencies, "dashboard_digest_missing")
            return 2
        try:
            _validated_digest(path, day, config.timezone)
            dependencies.publish_dashboard(path)
            dependencies.fallback_ledger.mark_dashboard_complete(
                day,
                at=dependencies.now(),
            )
        except Exception:
            _report(dependencies, "dashboard_pending")
            return 2
    return 0


def _cloud_allows_local(
    dependencies: LocalFallbackDependencies,
    day: date,
) -> tuple[bool, int]:
    try:
        result = dependencies.cloud_gate(day)
    except Exception:
        _report(dependencies, "cloud_gate_unavailable")
        return False, 2
    if not isinstance(result, CloudGateResult):
        _report(dependencies, "cloud_gate_invalid")
        return False, 2
    if result.decision == "run_local":
        return True, 0
    if result.decision == "skip_delivered":
        return False, 0
    _report(dependencies, result.reason_code)
    return False, 2


def _local_delivery_allowed(
    config: LocalFallbackConfig,
    dependencies: LocalFallbackDependencies,
    day: date,
) -> tuple[bool, int]:
    """Primary mode owns delivery; fallback mode remains cloud-gated."""
    if config.primary_mode:
        return True, 0
    return _cloud_allows_local(dependencies, day)


def _run_locked(
    config: LocalFallbackConfig,
    dependencies: LocalFallbackDependencies,
) -> int:
    now = dependencies.now()
    try:
        day = _shanghai_day(now, config.timezone)
    except (ValueError, ZoneInfoNotFoundError):
        _report(dependencies, "local_fallback_clock_invalid")
        return 2

    if any(
        pending_day < day
        for pending_day in dependencies.fallback_ledger.pending_days()
    ):
        # Task 5 accepts only the current Beijing date.  Dispatching an older
        # delivery would be rejected there, so do not risk a new date until an
        # operator reconciles the older pending state.
        _report(dependencies, "stale_pending_delivery")
        return 2

    try:
        send_ledger_delivered = dependencies.send_ledger.was_sent(day)
    except SendLedgerCorruptionError:
        _report(dependencies, "local_send_ledger_invalid")
        return 2

    state = dependencies.fallback_ledger.day_state(day)
    if state is not None:
        if state.delivery_status == "uncertain_delivery":
            _report(dependencies, "uncertain_delivery")
            return 2
        if state.delivery_status == "sent":
            return _retry_pending_work(config, dependencies, day, state)
    if send_ledger_delivered:
        # `send_existing_daily_result` writes this ledger before returning.  If
        # the process then dies before local state is persisted, no retry is
        # safer than a duplicate delivery.
        _report(dependencies, "local_send_ledger_delivered")
        return 0

    preflight = dependencies.preflight or (
        lambda active_config: preflight_reason(active_config, dependencies.sleep)
    )
    try:
        reason = preflight(config)
    except Exception:
        _report(dependencies, "preflight_failed")
        return 2
    if reason is not None:
        _report(dependencies, reason)
        return 2

    allowed, exit_code = _local_delivery_allowed(config, dependencies, day)
    if not allowed:
        return exit_code
    if config.check_only:
        return 0

    generation_now = dependencies.now()
    if not config.dry_run and not config.primary_mode:
        reason = _cloud_schedule_window_reason(generation_now, day, config)
        if reason is not None:
            _report(dependencies, reason)
            return 2

    run_path = _run_directory(config, generation_now)
    digest_path = run_path / "latest.json"
    try:
        generated = dependencies.generate(digest_path)
        if not digest_path.exists():
            digest_path.write_text(generated.model_dump_json(), encoding="utf-8")
        digest = _validated_digest(digest_path, day, config.timezone)
    except Exception as error:
        LOGGER.info("local_generation_error=%s", type(error).__name__)
        _report(dependencies, "invalid_local_digest")
        return 2

    allowed, exit_code = _local_delivery_allowed(config, dependencies, day)
    if not allowed:
        return exit_code
    if config.dry_run:
        return 0

    final_now = dependencies.now()
    if not config.primary_mode:
        reason = _cloud_schedule_window_reason(final_now, day, config)
        if reason is not None:
            _report(dependencies, reason)
            return 2
    allowed, exit_code = _local_delivery_allowed(config, dependencies, day)
    if not allowed:
        return exit_code

    try:
        # The local lock serializes local invocations, but GitHub and Feishu do
        # not provide a shared atomic lock.  This durable pre-send marker makes
        # the final checked decision fail closed if the process is interrupted.
        dependencies.fallback_ledger.mark_uncertain(day, at=final_now)
    except Exception:
        _report(dependencies, "local_state_write_failed")
        return 2
    try:
        sent_digest = dependencies.send(digest_path)
        if sent_digest.run_status not in _SUCCESSFUL_RUN_STATUS:
            raise ValueError("invalid_local_digest")
    except FeishuDeliveryRejected:
        dependencies.fallback_ledger.mark_failed(day, at=dependencies.now())
        _report(dependencies, "feishu_delivery_rejected")
        return 2
    except Exception:
        # A failure from the send wrapper can happen after the request was
        # accepted (for example while persisting its success ledger), so it is
        # always terminal for the date.
        dependencies.fallback_ledger.mark_uncertain(day, at=dependencies.now())
        _report(dependencies, "uncertain_delivery")
        return 2

    delivery_id = secrets.token_hex(16)
    try:
        dependencies.fallback_ledger.mark_sent(
            day,
            delivery_id,
            digest.run_status,
            at=dependencies.now(),
            cloud_sync_pending=True,
            dashboard_pending=config.dashboard_enabled,
        )
    except Exception:
        _report(dependencies, "local_state_write_failed")
        return 2

    state = dependencies.fallback_ledger.day_state(day)
    if state is None:
        _report(dependencies, "local_state_write_failed")
        return 2
    return _retry_pending_work(config, dependencies, day, state)


def prune_runtime_artifacts(
    runtime_root: Path,
    now: datetime,
    *,
    logs_root: Path | None = None,
) -> None:
    """Keep the latest 14 run directories and 30 days of logs only."""
    if now.tzinfo is None or now.utcoffset() is None:
        return
    runs_path = runtime_root / "runs"
    try:
        runs = sorted(
            (path for path in runs_path.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        runs = []
    for path in runs[14:]:
        try:
            shutil.rmtree(path)
        except OSError:
            pass

    cutoff = now.astimezone(UTC).timestamp() - timedelta(days=30).total_seconds()
    logs_path = logs_root or runtime_root / "logs"
    try:
        logs = tuple(path for path in logs_path.iterdir() if path.is_file())
    except OSError:
        logs = ()
    for path in logs:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def run_local_fallback(
    config: LocalFallbackConfig,
    dependencies: LocalFallbackDependencies,
) -> int:
    """Run one fail-closed local fallback attempt and return a shell exit code."""
    try:
        with exclusive_run_lock(_state_path(config) / "run.lock"):
            return _run_locked(config, dependencies)
    except LocalRunAlreadyActive:
        return 0
    except (FallbackStateError, OSError, ValueError):
        _report(dependencies, "local_state_invalid")
        return 2
    finally:
        try:
            prune_runtime_artifacts(
                config.runtime_root,
                dependencies.now(),
                logs_root=_logs_path(config),
            )
        except Exception:
            LOGGER.info("local_fallback_reason=retention_failed")


def _clock_checked_cloud_gate(
    client: GitHubCLIClient,
    config: LocalFallbackConfig,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> Callable[[date], CloudGateResult]:
    def cloud_gate(day: date) -> CloudGateResult:
        deadline = datetime.combine(
            day,
            config.cloud_wait_deadline,
            tzinfo=ZoneInfo(config.timezone),
        )
        while True:
            snapshot = client.snapshot(day)
            try:
                current = now()
                if current.tzinfo is None or current.utcoffset() is None:
                    raise ValueError
                local_now = current.astimezone(UTC)
                drift = abs(
                    (snapshot.server_time.astimezone(UTC) - local_now).total_seconds()
                )
            except (ValueError, ZoneInfoNotFoundError):
                return CloudGateResult("blocked", "github_clock_invalid")
            if drift > 5 * 60:
                return CloudGateResult("blocked", "github_clock_drift")
            result = evaluate_cloud_snapshot(day, snapshot)
            local_beijing_now = local_now.astimezone(ZoneInfo(config.timezone))
            if result.decision == "skip_delivered":
                return result
            if local_beijing_now >= deadline:
                if result.decision == "wait":
                    return CloudGateResult(
                        "blocked",
                        "cloud_wait_timeout",
                        result.run_urls,
                    )
                return result
            if result.decision not in {"wait", "run_local"}:
                return result
            # A completed cloud failure is not enough before the entire cloud
            # schedule window has closed; keep observing until the deadline.
            sleep(60)

    return cloud_gate


@contextlib.contextmanager
def _temporary_environment(values: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _notify_macos(reason_code: str) -> None:
    safe_reason = _safe_reason_code(reason_code)
    try:
        subprocess.run(
            (
                "/usr/bin/osascript",
                "-e",
                (
                    'display notification "'
                    f"{safe_reason}"
                    '" with title "AI News Fallback"'
                ),
            ),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        pass


def set_process_timezone(timezone: str) -> None:
    """Make native code and child processes use the fallback's intended day."""
    os.environ["TZ"] = timezone
    tzset = getattr(monotonic_time, "tzset", None)
    if tzset is not None:
        tzset()


def _build_dependencies(
    config: LocalFallbackConfig,
    values: dict[str, str],
) -> LocalFallbackDependencies:
    required = values.get("FEISHU_WEBHOOK_URL", "")
    if not required:
        raise ValueError("invalid_local_environment")
    dashboard_values = [
        values.get("SITE_DIGEST_ENDPOINT", ""),
        values.get("SITE_BYPASS_TOKEN", ""),
        values.get("SITE_DIGEST_UPDATE_SECRET", ""),
    ]
    if any(dashboard_values) and not all(dashboard_values):
        raise ValueError("invalid_local_environment")

    settings = Settings(
        ai_backend_name="ollama",
        ollama_base_url=config.ollama_base_url,
        ollama_model=config.model,
        feishu_webhook_url=required,
        feishu_signing_secret=values.get("FEISHU_SIGNING_SECRET", ""),
        state_path=_state_path(config) / "history.json",
        event_history_path=_state_path(config) / "events.json",
        send_ledger_path=_state_path(config) / "daily_sends.json",
        audit_path=_state_path(config) / "latest_audit.json",
    )
    client = GitHubCLIClient(config.gh_path, repository=config.repository)

    def generate(output: Path) -> EditorialDigest:
        sources = config.sources_path or config.runtime_root / "config" / "sources.yaml"
        environment = {
            "AI_BACKEND": "ollama",
            "OLLAMA_BASE_URL": config.ollama_base_url,
            "OLLAMA_MODEL": config.model,
            "FEISHU_WEBHOOK_URL": required,
            "FEISHU_SIGNING_SECRET": values.get("FEISHU_SIGNING_SECRET", ""),
            "STATE_PATH": str(settings.state_path),
            "EVENT_HISTORY_PATH": str(settings.event_history_path),
            "SEND_LEDGER_PATH": str(settings.send_ledger_path),
            "AUDIT_PATH": str(settings.audit_path),
        }
        with _temporary_environment(environment):
            exit_code = run_editorial_cli(
                argparse.Namespace(
                    sources=sources,
                    dry_run=True,
                    send_existing=False,
                    skip_ai=False,
                    lookback_hours=None,
                    web_output=output,
                    log_level="INFO",
                )
            )
        if exit_code != 0:
            raise ValueError("invalid_local_digest")
        return _validated_digest(
            output,
            _shanghai_day(datetime.now(UTC), config.timezone),
            config.timezone,
        )

    def publish_dashboard(path: Path) -> None:
        if not all(dashboard_values):
            return
        response = requests.post(
            dashboard_values[0],
            data=path.read_bytes(),
            headers={
                "Content-Type": "application/json",
                "OAI-Sites-Authorization": f"Bearer {dashboard_values[1]}",
                "Authorization": f"Bearer {dashboard_values[2]}",
            },
            timeout=20,
        )
        response.raise_for_status()

    current = lambda: datetime.now(UTC)
    return LocalFallbackDependencies(
        cloud_gate=_clock_checked_cloud_gate(
            client,
            config,
            current,
            lambda seconds: monotonic_time.sleep(seconds),
        ),
        generate=generate,
        send=lambda output: send_existing_daily_result(output, settings),
        dispatch_delivery=client.dispatch_local_delivery,
        publish_dashboard=publish_dashboard,
        notify=_notify_macos,
        send_ledger=SendLedger(settings.send_ledger_path),
        fallback_ledger=FallbackLedger(_state_path(config) / "fallback.json"),
        now=current,
        sleep=lambda seconds: monotonic_time.sleep(seconds),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local AI news fallback")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--scheduled", action="store_true")
    mode.add_argument("--run-now", action="store_true")
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--primary-scheduled", action="store_true")
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path.home() / "Library/Application Support/Baic-AI-Message-Bot",
    )
    parser.add_argument("--env-path", type=Path, default=None)
    parser.add_argument("--gh-path", type=Path, default=Path("/usr/local/bin/gh"))
    parser.add_argument(
        "--ollama-app-path",
        type=Path,
        default=Path.home() / "Applications/Ollama.app",
    )
    parser.add_argument(
        "--repository",
        default="bgu436475-ops/Baic-AI-Message-Bot",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    args = parse_args(argv)
    set_process_timezone("Asia/Shanghai")
    runtime_root: Path = args.runtime_root
    env_path: Path = args.env_path or runtime_root / ".env"
    try:
        values = load_local_environment(env_path)
        config = LocalFallbackConfig(
            runtime_root=runtime_root,
            env_path=env_path,
            gh_path=args.gh_path,
            ollama_app_path=args.ollama_app_path,
            repository=args.repository,
            ollama_base_url=values.get(
                "OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"
            ),
            model=values.get("OLLAMA_MODEL", "qwen3:8b"),
            scheduled=args.scheduled or args.primary_scheduled,
            primary_mode=args.primary_scheduled,
            check_only=args.check_only,
            dry_run=args.dry_run,
            logs_root=Path.home() / "Library/Logs/Baic-AI-Message-Bot",
            dashboard_enabled=all(
                values.get(key, "")
                for key in (
                    "SITE_DIGEST_ENDPOINT",
                    "SITE_BYPASS_TOKEN",
                    "SITE_DIGEST_UPDATE_SECRET",
                )
            ),
        )
        dependencies = _build_dependencies(config, values)
    except Exception:
        _notify_macos("invalid_local_environment")
        LOGGER.info("local_fallback_reason=invalid_local_environment")
        return 2
    return run_local_fallback(config, dependencies)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
