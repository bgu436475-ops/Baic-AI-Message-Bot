from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal


DeliveryStatus = Literal["sent", "uncertain_delivery", "failed"]
SuccessfulRunStatus = Literal["published", "no_qualifying_items"]
_DELIVERY_ID = re.compile(r"[0-9a-f]{32}\Z")


class FallbackStateError(RuntimeError):
    """The local fallback state cannot be safely interpreted."""


class LocalRunAlreadyActive(RuntimeError):
    """Another local fallback process owns the exclusive run lock."""


@dataclass(frozen=True)
class LocalDayState:
    delivery_status: DeliveryStatus
    delivery_id: str | None
    run_status: SuccessfulRunStatus | None
    cloud_sync_pending: bool
    dashboard_pending: bool
    updated_at: datetime


def _timestamp(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("local fallback timestamps must be timezone-aware")
    return timestamp.astimezone(UTC)


def _parse_state(value: object) -> LocalDayState:
    if not isinstance(value, dict):
        raise FallbackStateError("invalid_local_state")
    try:
        delivery_status = value["delivery_status"]
        delivery_id = value["delivery_id"]
        run_status = value["run_status"]
        cloud_sync_pending = value["cloud_sync_pending"]
        dashboard_pending = value["dashboard_pending"]
        updated_at = value["updated_at"]
    except KeyError as error:
        raise FallbackStateError("invalid_local_state") from error

    if delivery_status not in {"sent", "uncertain_delivery", "failed"}:
        raise FallbackStateError("invalid_local_state")
    if not isinstance(delivery_id, (str, type(None))):
        raise FallbackStateError("invalid_local_state")
    if delivery_id is not None and not _DELIVERY_ID.fullmatch(delivery_id):
        raise FallbackStateError("invalid_local_state")
    if run_status not in {"published", "no_qualifying_items", None}:
        raise FallbackStateError("invalid_local_state")
    if not isinstance(cloud_sync_pending, bool) or not isinstance(
        dashboard_pending, bool
    ):
        raise FallbackStateError("invalid_local_state")
    if not isinstance(updated_at, str):
        raise FallbackStateError("invalid_local_state")
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError as error:
        raise FallbackStateError("invalid_local_state") from error
    if updated.tzinfo is None or updated.utcoffset() is None:
        raise FallbackStateError("invalid_local_state")

    if delivery_status == "sent":
        if delivery_id is None or run_status is None:
            raise FallbackStateError("invalid_local_state")
    elif (
        delivery_id is not None
        or run_status is not None
        or cloud_sync_pending
        or dashboard_pending
    ):
        raise FallbackStateError("invalid_local_state")

    return LocalDayState(
        delivery_status=delivery_status,
        delivery_id=delivery_id,
        run_status=run_status,
        cloud_sync_pending=cloud_sync_pending,
        dashboard_pending=dashboard_pending,
        updated_at=updated.astimezone(UTC),
    )


class FallbackLedger:
    """Atomic, local-only fallback delivery state keyed by Beijing date."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, LocalDayState]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            raise FallbackStateError("invalid_local_state") from error
        if not isinstance(payload, dict) or set(payload) != {"days"}:
            raise FallbackStateError("invalid_local_state")
        days = payload.get("days")
        if not isinstance(days, dict):
            raise FallbackStateError("invalid_local_state")
        result: dict[str, LocalDayState] = {}
        for day_text, value in days.items():
            if not isinstance(day_text, str):
                raise FallbackStateError("invalid_local_state")
            try:
                parsed_day = date.fromisoformat(day_text)
            except ValueError as error:
                raise FallbackStateError("invalid_local_state") from error
            if parsed_day.isoformat() != day_text:
                raise FallbackStateError("invalid_local_state")
            result[day_text] = _parse_state(value)
        return result

    def _write(self, states: dict[str, LocalDayState]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(
            {
                "days": {
                    day: {
                        **asdict(state),
                        "updated_at": state.updated_at.isoformat(),
                    }
                    for day, state in sorted(states.items())
                }
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            try:
                directory = os.open(self.path.parent, os.O_RDONLY)
            except OSError:
                return
            try:
                os.fsync(directory)
            except OSError:
                pass
            finally:
                os.close(directory)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def day_state(self, day: date) -> LocalDayState | None:
        return self._load().get(day.isoformat())

    def blocks_send(self, day: date) -> bool:
        state = self.day_state(day)
        return state is not None and state.delivery_status in {
            "sent",
            "uncertain_delivery",
        }

    def pending_days(self) -> tuple[date, ...]:
        """Return confirmed-delivery dates with unfinished non-send work."""
        states = self._load()
        return tuple(
            date.fromisoformat(day_text)
            for day_text, state in sorted(states.items())
            if state.delivery_status == "sent"
            and (state.cloud_sync_pending or state.dashboard_pending)
        )

    def mark_uncertain(self, day: date, *, at: datetime | None = None) -> None:
        states = self._load()
        states[day.isoformat()] = LocalDayState(
            delivery_status="uncertain_delivery",
            delivery_id=None,
            run_status=None,
            cloud_sync_pending=False,
            dashboard_pending=False,
            updated_at=_timestamp(at),
        )
        self._write(states)

    def mark_failed(self, day: date, *, at: datetime | None = None) -> None:
        states = self._load()
        states[day.isoformat()] = LocalDayState(
            delivery_status="failed",
            delivery_id=None,
            run_status=None,
            cloud_sync_pending=False,
            dashboard_pending=False,
            updated_at=_timestamp(at),
        )
        self._write(states)

    def mark_sent(
        self,
        day: date,
        delivery_id: str,
        run_status: SuccessfulRunStatus,
        *,
        at: datetime | None = None,
        cloud_sync_pending: bool = True,
        dashboard_pending: bool = False,
    ) -> None:
        if not _DELIVERY_ID.fullmatch(delivery_id):
            raise ValueError("delivery_id must be 32 lowercase hexadecimal characters")
        if run_status not in {"published", "no_qualifying_items"}:
            raise ValueError("unsupported successful run status")
        states = self._load()
        states[day.isoformat()] = LocalDayState(
            delivery_status="sent",
            delivery_id=delivery_id,
            run_status=run_status,
            cloud_sync_pending=cloud_sync_pending,
            dashboard_pending=dashboard_pending,
            updated_at=_timestamp(at),
        )
        self._write(states)

    def mark_sync_complete(
        self,
        day: date,
        *,
        at: datetime | None = None,
    ) -> None:
        self._update_pending(day, cloud_sync_pending=False, at=at)

    def mark_dashboard_complete(
        self,
        day: date,
        *,
        at: datetime | None = None,
    ) -> None:
        self._update_pending(day, dashboard_pending=False, at=at)

    def _update_pending(
        self,
        day: date,
        *,
        cloud_sync_pending: bool | None = None,
        dashboard_pending: bool | None = None,
        at: datetime | None,
    ) -> None:
        states = self._load()
        state = states.get(day.isoformat())
        if state is None or state.delivery_status != "sent":
            raise FallbackStateError("missing_confirmed_delivery")
        states[day.isoformat()] = LocalDayState(
            delivery_status=state.delivery_status,
            delivery_id=state.delivery_id,
            run_status=state.run_status,
            cloud_sync_pending=(
                state.cloud_sync_pending
                if cloud_sync_pending is None
                else cloud_sync_pending
            ),
            dashboard_pending=(
                state.dashboard_pending
                if dashboard_pending is None
                else dashboard_pending
            ),
            updated_at=_timestamp(at),
        )
        self._write(states)


class _ExclusiveRunLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: object | None = None

    def __enter__(self) -> "_ExclusiveRunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            handle.close()
            raise LocalRunAlreadyActive("local_fallback_already_active") from error
        self._handle = handle
        return self

    def __exit__(self, *unused: object) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None


def exclusive_run_lock(path: Path) -> _ExclusiveRunLock:
    return _ExclusiveRunLock(path)
