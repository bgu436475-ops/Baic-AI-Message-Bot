from __future__ import annotations

import argparse
import html
import os
import shutil
import stat
import subprocess
import sys
import venv
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from shlex import quote as shell_quote


INSTALLER_LABEL = "com.baic.ai-news-bot.local-fallback"
DEFAULT_REPOSITORY = "bgu436475-ops/Baic-AI-Message-Bot"
DEFAULT_MODEL = "qwen3:8b"
MINIMUM_FREE_BYTES = 8 * 1024**3

CommandRunner = Callable[[Sequence[str]], int]
VenvBuilder = Callable[[Path], None]
FreeSpace = Callable[[Path], int]


class InstallerError(RuntimeError):
    """A prerequisite for the local fallback is missing or unsafe."""


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


def _build_venv(path: Path) -> None:
    venv.EnvBuilder(with_pip=True).create(path)


def _free_space(path: Path) -> int:
    return shutil.disk_usage(path).free


@dataclass(frozen=True)
class InstallerContext:
    repo_root: Path
    home: Path
    gh_path: Path
    ollama_app_path: Path
    runner: CommandRunner = _run_silently
    venv_builder: VenvBuilder = _build_venv
    free_space: FreeSpace = _free_space
    uid: int = 0
    repository: str = DEFAULT_REPOSITORY

    @property
    def runtime_root(self) -> Path:
        return self.home / "Library/Application Support/Baic-AI-Message-Bot"

    @property
    def logs_root(self) -> Path:
        return self.home / "Library/Logs/Baic-AI-Message-Bot"

    @property
    def launch_agent_path(self) -> Path:
        return self.home / "Library/LaunchAgents" / f"{INSTALLER_LABEL}.plist"

    @property
    def desktop_root(self) -> Path:
        return self.home / "Desktop"

    @property
    def run_now_path(self) -> Path:
        return self.desktop_root / "立即运行 Plan 2.command"

    @property
    def view_logs_path(self) -> Path:
        return self.desktop_root / "查看 Plan 2 日志.command"

    @property
    def env_path(self) -> Path:
        return self.runtime_root / ".env"

    @property
    def venv_python(self) -> Path:
        return self.runtime_root / "venv/bin/python"

    @property
    def installed_gh_path(self) -> Path:
        return self.runtime_root / "bin/gh"


@dataclass(frozen=True)
class LocalFallbackInstallResult:
    runtime_root: Path
    env_path: Path
    launch_agent: Path
    run_now: Path
    view_logs: Path


def _template_root() -> Path:
    return Path(__file__).resolve().parents[1] / "local-fallback"


def _read_template(name: str) -> str:
    try:
        return (_template_root() / name).read_text(encoding="utf-8")
    except OSError as error:
        raise InstallerError("installer_template_missing") from error


def _replace_xml(template: str, values: Mapping[str, str]) -> bytes:
    rendered = template
    for token, value in values.items():
        rendered = rendered.replace(token, html.escape(value, quote=False))
    return rendered.encode("utf-8")


def _replace_shell(template: str, values: Mapping[str, str]) -> str:
    rendered = template
    for token, value in values.items():
        rendered = rendered.replace(token, shell_quote(value))
    return rendered


def render_launch_agent(context: InstallerContext) -> bytes:
    """Render paths only. Secret values are read by Python from its 0600 file."""
    return _replace_xml(
        _read_template(f"{INSTALLER_LABEL}.plist.template"),
        {
            "__PYTHON__": str(context.venv_python),
            "__RUNTIME_ROOT__": str(context.runtime_root),
            "__ENV_PATH__": str(context.env_path),
            "__GH_PATH__": str(context.installed_gh_path),
            "__OLLAMA_APP_PATH__": str(context.ollama_app_path),
            "__REPOSITORY__": context.repository,
            "__STDOUT_LOG__": str(context.logs_root / "local-fallback.stdout.log"),
            "__STDERR_LOG__": str(context.logs_root / "local-fallback.stderr.log"),
        },
    )


def _render_run_now(context: InstallerContext) -> str:
    return _replace_shell(
        _read_template("run-now.command.template"),
        {
            "__PYTHON__": str(context.venv_python),
            "__RUNTIME_ROOT__": str(context.runtime_root),
            "__ENV_PATH__": str(context.env_path),
            "__GH_PATH__": str(context.installed_gh_path),
            "__OLLAMA_APP_PATH__": str(context.ollama_app_path),
            "__REPOSITORY__": context.repository,
        },
    )


def _render_view_logs(context: InstallerContext) -> str:
    return _replace_shell(
        _read_template("view-logs.command.template"),
        {"__LOGS_ROOT__": str(context.logs_root)},
    )


def _write_file(path: Path, data: bytes | str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)
    path.chmod(mode)


def _create_environment(path: Path) -> None:
    if path.exists():
        path.chmod(0o600)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as environment:
        environment.write(
            "AI_BACKEND=ollama\n"
            "OLLAMA_BASE_URL=http://127.0.0.1:11434/v1\n"
            f"OLLAMA_MODEL={DEFAULT_MODEL}\n"
            "FEISHU_WEBHOOK_URL=\n"
            "FEISHU_SIGNING_SECRET=\n"
        )
    path.chmod(0o600)


def _run_or_raise(context: InstallerContext, command: Sequence[str], reason: str) -> None:
    try:
        return_code = context.runner(command)
    except OSError as error:
        raise InstallerError(reason) from error
    if return_code != 0:
        raise InstallerError(reason)


def _validate_prerequisites(
    context: InstallerContext,
    *,
    require_recorder_workflow: bool = False,
) -> None:
    if not context.gh_path.is_file() or not os.access(context.gh_path, os.X_OK):
        raise InstallerError("github_cli")
    _run_or_raise(
        context,
        [str(context.gh_path), "auth", "status", "--hostname", "github.com"],
        "github_auth",
    )
    _run_or_raise(
        context,
        [
            str(context.gh_path),
            "repo",
            "view",
            context.repository,
            "--json",
            "nameWithOwner",
        ],
        "github_repository_access",
    )
    if require_recorder_workflow:
        _run_or_raise(
            context,
            [
                str(context.gh_path),
                "api",
                (
                    f"repos/{context.repository}/contents/.github/workflows/"
                    "record-local-delivery.yml?ref=main"
                ),
            ],
            "record_local_delivery_workflow",
        )
    if not context.ollama_app_path.is_dir():
        raise InstallerError("ollama_missing")
    try:
        free_bytes = context.free_space(context.home)
    except OSError as error:
        raise InstallerError("disk_space_unavailable") from error
    if free_bytes < MINIMUM_FREE_BYTES:
        raise InstallerError("insufficient_disk_space")


def _install_runtime(context: InstallerContext) -> None:
    runtime_root = context.runtime_root
    for directory in (
        runtime_root,
        runtime_root / "bin",
        runtime_root / "config",
        runtime_root / "state",
        runtime_root / "runs",
        context.logs_root,
        context.launch_agent_path.parent,
        context.desktop_root,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    shutil.copy2(context.gh_path, context.installed_gh_path)
    context.installed_gh_path.chmod(0o700)
    source_config = context.repo_root / "config/sources.yaml"
    if not source_config.is_file():
        raise InstallerError("sources_config_missing")
    shutil.copy2(source_config, runtime_root / "config/sources.yaml")
    _create_environment(context.env_path)

    if not context.venv_python.exists():
        context.venv_builder(runtime_root / "venv")
        if not context.venv_python.is_file():
            raise InstallerError("venv_creation_failed")
    _run_or_raise(
        context,
        [str(context.venv_python), "-m", "pip", "install", str(context.repo_root)],
        "project_install_failed",
    )

    _write_file(context.launch_agent_path, render_launch_agent(context), 0o644)
    _write_file(context.run_now_path, _render_run_now(context), 0o700)
    _write_file(context.view_logs_path, _render_view_logs(context), 0o700)


def _launch_agent_is_loaded(context: InstallerContext) -> bool:
    try:
        return context.runner(
            [
                "/bin/launchctl",
                "print",
                f"gui/{context.uid}/{INSTALLER_LABEL}",
            ]
        ) == 0
    except OSError:
        return False


def install_local_fallback(
    context: InstallerContext,
    *,
    activate_schedule: bool = False,
    smoke_validated: bool = False,
) -> LocalFallbackInstallResult:
    """Install local assets; only bootstrap after an explicit no-send validation."""
    if activate_schedule and not smoke_validated:
        raise InstallerError("smoke_validation_required")
    _validate_prerequisites(
        context,
        require_recorder_workflow=activate_schedule,
    )
    _install_runtime(context)
    if activate_schedule and not _launch_agent_is_loaded(context):
        _run_or_raise(
            context,
            ["/bin/launchctl", "bootstrap", f"gui/{context.uid}", str(context.launch_agent_path)],
            "launch_agent_bootstrap_failed",
        )
    return LocalFallbackInstallResult(
        runtime_root=context.runtime_root,
        env_path=context.env_path,
        launch_agent=context.launch_agent_path,
        run_now=context.run_now_path,
        view_logs=context.view_logs_path,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install the local AI news fallback")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--gh-path", type=Path, required=True)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--ollama-app-path", type=Path, default=None)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--smoke-validated", action="store_true")
    parser.add_argument("--activate-schedule", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    home: Path = args.home
    context = InstallerContext(
        repo_root=args.repo_root.resolve(),
        home=home,
        gh_path=args.gh_path.resolve(),
        ollama_app_path=args.ollama_app_path or home / "Applications/Ollama.app",
        uid=os.getuid(),
        repository=args.repository,
    )
    try:
        result = install_local_fallback(
            context,
            activate_schedule=args.activate_schedule,
            smoke_validated=args.smoke_validated,
        )
    except InstallerError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"runtime_root={result.runtime_root}")
    print(f"environment={result.env_path}")
    print(f"schedule_active={str(args.activate_schedule).lower()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
