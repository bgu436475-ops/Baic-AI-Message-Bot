from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


OLLAMA_DOWNLOAD_URL = "https://ollama.com/download/Ollama-darwin.zip"
DEFAULT_MODEL = "qwen3:8b"

CommandRunner = Callable[[Sequence[str]], int]
Downloader = Callable[[str, Path], None]
Healthcheck = Callable[[], bool]
Sleeper = Callable[[float], None]


class OllamaInstallError(RuntimeError):
    """The user-local Ollama setup could not be completed safely."""


@dataclass(frozen=True)
class OllamaInstallContext:
    applications_dir: Path
    model: str = DEFAULT_MODEL
    runner: CommandRunner = None  # type: ignore[assignment]
    downloader: Downloader = None  # type: ignore[assignment]
    healthcheck: Healthcheck = None  # type: ignore[assignment]
    sleeper: Sleeper = time.sleep
    health_attempts: int = 30

    def __post_init__(self) -> None:
        if self.runner is None:
            object.__setattr__(self, "runner", _run_silently)
        if self.downloader is None:
            object.__setattr__(self, "downloader", _download)
        if self.healthcheck is None:
            object.__setattr__(self, "healthcheck", _ollama_healthy)

    @property
    def app_path(self) -> Path:
        return self.applications_dir / "Ollama.app"


@dataclass(frozen=True)
class OllamaInstallResult:
    app_path: Path
    installed: bool


def _run_silently(command: Sequence[str]) -> int:
    try:
        return subprocess.run(
            list(command),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
    except OSError:
        return 127


def _no_proxy_opener() -> urllib.request.OpenerDirector:
    """Do not let setup traffic inherit operator proxy environment variables."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _download(url: str, destination: Path) -> None:
    with _no_proxy_opener().open(url, timeout=30) as response:
        with destination.open("wb") as archive:
            shutil.copyfileobj(response, archive)


def _ollama_healthy() -> bool:
    try:
        with _no_proxy_opener().open(
            "http://127.0.0.1:11434/api/tags",
            timeout=2,
        ) as response:
            return 200 <= response.status < 300
    except OSError:
        return False


def _require_success(runner: CommandRunner, command: Sequence[str], reason: str) -> None:
    if runner(command) != 0:
        raise OllamaInstallError(reason)


def _safe_ollama_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    for member in archive.infolist():
        path = PurePosixPath(member.filename)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not member.filename.startswith("Ollama.app/")
        ):
            raise OllamaInstallError("ollama_archive_invalid")
        members.append(member)
    if not members:
        raise OllamaInstallError("ollama_archive_invalid")
    return members


def _wait_for_health(context: OllamaInstallContext) -> None:
    for attempt in range(context.health_attempts):
        if context.healthcheck():
            return
        if attempt + 1 < context.health_attempts:
            context.sleeper(1)
    raise OllamaInstallError("ollama_healthcheck_failed")


def _verify_ollama(
    context: OllamaInstallContext,
    app_path: Path,
) -> None:
    _require_success(
        context.runner,
        ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app_path)],
        "ollama_codesign_verification_failed",
    )
    _require_success(
        context.runner,
        ["/usr/sbin/spctl", "--assess", "--type", "execute", str(app_path)],
        "ollama_spctl_verification_failed",
    )


def _start_and_prepare_ollama(
    context: OllamaInstallContext,
    app_path: Path,
) -> None:
    _require_success(
        context.runner,
        ["/usr/bin/open", "-gj", "-a", str(app_path)],
        "ollama_start_failed",
    )
    _wait_for_health(context)
    _require_success(
        context.runner,
        [str(app_path / "Contents/MacOS/ollama"), "pull", context.model],
        "ollama_model_pull_failed",
    )


def install_ollama(context: OllamaInstallContext) -> OllamaInstallResult:
    """Install a verified app once; never replace an existing user application."""
    if context.app_path.exists():
        _verify_ollama(context, context.app_path)
        _start_and_prepare_ollama(context, context.app_path)
        return OllamaInstallResult(app_path=context.app_path, installed=False)

    context.applications_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="baic-ollama-") as temporary:
        temporary_path = Path(temporary)
        archive_path = temporary_path / "Ollama-darwin.zip"
        try:
            context.downloader(OLLAMA_DOWNLOAD_URL, archive_path)
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(temporary_path, members=_safe_ollama_members(archive))
        except (OSError, zipfile.BadZipFile) as error:
            raise OllamaInstallError("ollama_download_failed") from error

        extracted_app = temporary_path / "Ollama.app"
        if not extracted_app.is_dir():
            raise OllamaInstallError("ollama_archive_invalid")
        _verify_ollama(context, extracted_app)

        # Do not race an app another installer created while we verified ours.
        if context.app_path.exists():
            _verify_ollama(context, context.app_path)
            _start_and_prepare_ollama(context, context.app_path)
            return OllamaInstallResult(app_path=context.app_path, installed=False)
        shutil.move(str(extracted_app), str(context.app_path))

    _start_and_prepare_ollama(context, context.app_path)
    return OllamaInstallResult(app_path=context.app_path, installed=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install Ollama for the local fallback")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--applications-dir", type=Path, default=Path.home() / "Applications")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        print("macos_apple_silicon_required")
        return 2
    try:
        result = install_ollama(
            OllamaInstallContext(applications_dir=args.applications_dir, model=args.model)
        )
    except OllamaInstallError as error:
        print(str(error))
        return 2
    print(f"ollama_app={result.app_path} installed={str(result.installed).lower()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
