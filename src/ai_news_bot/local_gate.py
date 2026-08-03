from __future__ import annotations

import base64
import binascii
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Literal
from zoneinfo import ZoneInfo

from .models import EditorialDigest


SHANGHAI = ZoneInfo("Asia/Shanghai")
GateDecision = Literal["skip_delivered", "wait", "run_local", "blocked"]
DigestStatus = Literal["missing", "valid", "malformed", "unavailable"]


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


CommandRunner = Callable[[tuple[str, ...], str | None], CommandResult]


def run_command(arguments: tuple[str, ...], stdin: str | None = None) -> CommandResult:
    completed = subprocess.run(
        arguments,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class CloudRun:
    run_id: int
    event: str
    status: str
    conclusion: str | None
    created_at: datetime
    url: str
    send_step_conclusion: str | None


@dataclass(frozen=True)
class CloudGateResult:
    decision: GateDecision
    reason_code: str
    run_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class RemoteDigestProbe:
    status: DigestStatus
    digest: EditorialDigest | None = None


@dataclass(frozen=True)
class CloudSnapshot:
    runs: tuple[CloudRun, ...]
    remote_digest: RemoteDigestProbe
    server_time: datetime


def _shanghai_day(value: datetime) -> date:
    return value.astimezone(SHANGHAI).date()


def _same_day_runs(day: date, runs: tuple[CloudRun, ...]) -> tuple[CloudRun, ...]:
    return tuple(
        run
        for run in runs
        if _shanghai_day(run.created_at) == day
    )


def _validated_digest(digest: EditorialDigest | None) -> EditorialDigest | None:
    if digest is None:
        return None
    try:
        return EditorialDigest.model_validate_json(digest.model_dump_json())
    except (TypeError, ValueError):
        return None


def evaluate_cloud_snapshot(day: date, snapshot: CloudSnapshot) -> CloudGateResult:
    runs = _same_day_runs(day, snapshot.runs)
    run_urls = tuple(run.url for run in runs)

    if any(run.send_step_conclusion == "success" for run in runs):
        return CloudGateResult("skip_delivered", "cloud_send_step_succeeded", run_urls)

    if snapshot.remote_digest.status == "valid":
        digest = _validated_digest(snapshot.remote_digest.digest)
        if digest is None:
            return CloudGateResult("blocked", "remote_digest_invalid", run_urls)
        if _shanghai_day(digest.generated_at) == day:
            return CloudGateResult("skip_delivered", "remote_digest_exists", run_urls)

    if any(run.status != "completed" for run in runs):
        return CloudGateResult("wait", "cloud_run_active", run_urls)

    if snapshot.remote_digest.status == "malformed":
        return CloudGateResult("blocked", "remote_digest_malformed", run_urls)
    if snapshot.remote_digest.status == "unavailable":
        return CloudGateResult("blocked", "cloud_snapshot_unavailable", run_urls)
    return CloudGateResult("run_local", "no_cloud_delivery", run_urls)


class _GitHubUnavailable(RuntimeError):
    pass


class GitHubCLIClient:
    def __init__(
        self,
        gh_path: Path,
        repository: str = "bgu436475-ops/Baic-AI-Message-Bot",
        branch: str = "main",
        command_runner: CommandRunner = run_command,
    ) -> None:
        self.gh_path = gh_path
        self.repository = repository
        self.branch = branch
        self.command_runner = command_runner

    def _run(self, *arguments: str, stdin: str | None = None) -> CommandResult:
        try:
            return self.command_runner((str(self.gh_path), *arguments), stdin)
        except OSError:
            return CommandResult(1, "", "gh execution failed")

    @staticmethod
    def _json(result: CommandResult) -> object:
        if result.returncode != 0:
            raise _GitHubUnavailable
        try:
            return json.loads(result.stdout)
        except (TypeError, ValueError) as error:
            raise _GitHubUnavailable from error

    @staticmethod
    def _server_time(result: CommandResult) -> datetime:
        if result.returncode != 0:
            raise _GitHubUnavailable
        for line in result.stdout.replace("\r\n", "\n").split("\n"):
            name, separator, value = line.partition(":")
            if separator and name.casefold() == "date":
                try:
                    return parsedate_to_datetime(value.strip()).astimezone(UTC)
                except (TypeError, ValueError) as error:
                    raise _GitHubUnavailable from error
        raise _GitHubUnavailable

    def _list_runs(self) -> tuple[CloudRun, ...]:
        value = self._json(
            self._run(
                "run",
                "list",
                "--repo",
                self.repository,
                "--branch",
                self.branch,
                "--workflow",
                "daily-ai-news.yml",
                "--limit",
                "30",
                "--json",
                "databaseId,event,status,conclusion,createdAt,url",
            )
        )
        if not isinstance(value, list):
            raise _GitHubUnavailable
        runs: list[CloudRun] = []
        for entry in value:
            if not isinstance(entry, dict):
                raise _GitHubUnavailable
            try:
                event = entry["event"]
                status = entry["status"]
                url = entry["url"]
                conclusion = entry.get("conclusion")
                if (
                    not isinstance(event, str)
                    or not event
                    or not isinstance(status, str)
                    or not status
                    or not isinstance(url, str)
                    or not url
                    or (conclusion is not None and not isinstance(conclusion, str))
                ):
                    raise ValueError
                created_at = datetime.fromisoformat(
                    str(entry["createdAt"]).replace("Z", "+00:00")
                )
                if created_at.tzinfo is None:
                    raise ValueError
                run = CloudRun(
                    run_id=int(entry["databaseId"]),
                    event=event,
                    status=status,
                    conclusion=conclusion,
                    created_at=created_at,
                    url=url,
                    send_step_conclusion=None,
                )
            except (KeyError, TypeError, ValueError) as error:
                raise _GitHubUnavailable from error
            runs.append(run)
        return tuple(runs)

    def _send_step_conclusion(self, run_id: int) -> str | None:
        value = self._json(
            self._run(
                "run",
                "view",
                str(run_id),
                "--repo",
                self.repository,
                "--json",
                "jobs",
            )
        )
        if not isinstance(value, dict) or not isinstance(value.get("jobs"), list):
            raise _GitHubUnavailable
        for job in value["jobs"]:
            if not isinstance(job, dict) or job.get("name") != "send-digest":
                continue
            steps = job.get("steps")
            if not isinstance(steps, list):
                raise _GitHubUnavailable
            for step in steps:
                if isinstance(step, dict) and step.get("name") == "Send persisted daily result":
                    conclusion = step.get("conclusion")
                    return str(conclusion) if conclusion is not None else None
        return None

    def _remote_digest(self) -> RemoteDigestProbe:
        path = (
            f"repos/{self.repository}/contents/web/public/data/latest.json"
            f"?ref={self.branch}"
        )
        result = self._run("api", path)
        if result.returncode != 0:
            if "404" in result.stderr or "404" in result.stdout:
                return RemoteDigestProbe("missing")
            return RemoteDigestProbe("unavailable")
        try:
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict) or payload.get("encoding") != "base64":
                raise ValueError
            content = payload.get("content")
            if not isinstance(content, str):
                raise ValueError
            raw = base64.b64decode(
                "".join(content.split()), validate=True
            ).decode("utf-8")
            digest = EditorialDigest.model_validate_json(raw)
        except (TypeError, UnicodeError, ValueError, binascii.Error):
            return RemoteDigestProbe("malformed")
        return RemoteDigestProbe("valid", digest)

    def snapshot(self, day: date) -> CloudSnapshot:
        del day
        fallback_time = datetime.now(UTC)
        try:
            server_time = self._server_time(self._run("api", "-i", "rate_limit"))
            runs = self._list_runs()
            inspected_runs = tuple(
                CloudRun(
                    run_id=run.run_id,
                    event=run.event,
                    status=run.status,
                    conclusion=run.conclusion,
                    created_at=run.created_at,
                    url=run.url,
                    send_step_conclusion=self._send_step_conclusion(run.run_id),
                )
                for run in runs
            )
            remote_digest = self._remote_digest()
            if remote_digest.status == "unavailable":
                raise _GitHubUnavailable
            return CloudSnapshot(inspected_runs, remote_digest, server_time)
        except _GitHubUnavailable:
            return CloudSnapshot(
                (),
                RemoteDigestProbe("unavailable"),
                fallback_time,
            )

    def dispatch_local_delivery(self, day: date, delivery_id: str) -> None:
        payload = json.dumps(
            {
                "event_type": "local-ai-news-delivered",
                "client_payload": {
                    "date": day.isoformat(),
                    "delivery_id": delivery_id,
                },
            }
        )
        result = self._run(
            "api",
            f"repos/{self.repository}/dispatches",
            "--method",
            "POST",
            "--input",
            "-",
            stdin=payload,
        )
        if result.returncode != 0:
            raise _GitHubUnavailable("repository dispatch failed")


def _deadline_at(day: date, deadline: time | datetime) -> datetime:
    if isinstance(deadline, datetime):
        return deadline.astimezone(SHANGHAI)
    return datetime.combine(day, deadline, tzinfo=SHANGHAI)


def wait_for_cloud_gate(
    client: GitHubCLIClient,
    day: date,
    deadline: time | datetime,
    sleep: Callable[[float], None],
) -> CloudGateResult:
    deadline_at = _deadline_at(day, deadline)
    while True:
        cloud_snapshot = client.snapshot(day)
        result = evaluate_cloud_snapshot(day, cloud_snapshot)
        if result.decision != "wait":
            return result
        if cloud_snapshot.server_time.astimezone(SHANGHAI) >= deadline_at:
            return CloudGateResult(
                "blocked",
                "cloud_wait_timeout",
                result.run_urls,
            )
        sleep(60)
