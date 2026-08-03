from __future__ import annotations

import io
import os
import plistlib
import stat
import sys
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from install_local_fallback import (  # noqa: E402
    INSTALLER_LABEL,
    InstallerContext,
    InstallerError,
    install_local_fallback,
    render_launch_agent,
)
from install_ollama_macos import (  # noqa: E402
    OllamaInstallContext,
    install_ollama,
)
import install_ollama_macos as ollama_installer  # noqa: E402
from uninstall_local_fallback import (  # noqa: E402
    UninstallContext,
    UninstallError,
    main as uninstall_main,
    parse_args as parse_uninstall_args,
    uninstall_local_fallback,
)


GIB = 1024**3


@dataclass(frozen=True)
class CommandOutcome:
    returncode: int
    stderr: str = ""


@dataclass
class RecordingRunner:
    """Controlled command boundary: no test may execute a real command."""

    results: dict[tuple[str, ...], object] = field(default_factory=dict)
    sequence_results: dict[tuple[str, ...], list[object]] = field(
        default_factory=dict
    )
    commands: list[tuple[str, ...]] = field(default_factory=list)

    def __call__(self, command: Sequence[str]) -> int:
        normalized = tuple(command)
        self.commands.append(normalized)
        if values := self.sequence_results.get(normalized):
            return values.pop(0)
        if normalized[:2] == ("/bin/launchctl", "print"):
            return self.results.get(normalized, 3)
        return self.results.get(normalized, 0)


def _build_fake_venv(path: Path) -> None:
    python = path / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o700)


def _context(
    tmp_path: Path,
    *,
    runner: RecordingRunner | None = None,
    gh_exists: bool = True,
    gh_executable: bool = True,
    ollama_exists: bool = True,
    free_bytes: int = 9 * GIB,
) -> InstallerContext:
    repo_root = tmp_path / "repository"
    sources = repo_root / "config" / "sources.yaml"
    sources.parent.mkdir(parents=True)
    sources.write_text("rss: []\n", encoding="utf-8")

    gh_path = tmp_path / "bin" / "gh"
    if gh_exists:
        gh_path.parent.mkdir(parents=True)
        gh_path.write_text("#!/bin/sh\n", encoding="utf-8")
        gh_path.chmod(0o700 if gh_executable else 0o600)

    home = tmp_path / "home"
    ollama_app = home / "Applications" / "Ollama.app"
    if ollama_exists:
        ollama_app.mkdir(parents=True)

    return InstallerContext(
        repo_root=repo_root,
        home=home,
        gh_path=gh_path,
        ollama_app_path=ollama_app,
        runner=runner or RecordingRunner(),
        venv_builder=_build_fake_venv,
        free_space=lambda _: free_bytes,
        uid=501,
    )


def test_installer_reuses_runtime_and_protects_environment(tmp_path: Path) -> None:
    """Recreating the layout must not overwrite credentials or runtime paths."""
    context = _context(tmp_path)

    first = install_local_fallback(context)
    first.env_path.write_text(
        "FEISHU_WEBHOOK_URL=https://hooks.example.test/secret\n",
        encoding="utf-8",
    )
    first.env_path.chmod(0o600)
    second = install_local_fallback(context)

    assert second.runtime_root == first.runtime_root
    assert second.env_path.read_text(encoding="utf-8") == (
        "FEISHU_WEBHOOK_URL=https://hooks.example.test/secret\n"
    )
    assert stat.S_IMODE(second.env_path.stat().st_mode) == 0o600
    assert not second.launch_agent.exists()
    assert context.staged_launch_agent_path.exists()
    assert not second.run_now.exists()
    assert second.view_logs.exists()
    assert (second.runtime_root / "config" / "sources.yaml").read_text(
        encoding="utf-8"
    ) == "rss: []\n"
    assert os.access(second.runtime_root / "bin" / "gh", os.X_OK)

    smoke_validated = install_local_fallback(context, smoke_validated=True)
    assert smoke_validated.run_now.exists()


def test_installer_reinstalls_the_project_when_a_runtime_venv_already_exists(
    tmp_path: Path,
) -> None:
    """Skipping pip after an interrupted or old install can run stale fallback code."""
    runner = RecordingRunner()
    context = _context(tmp_path, runner=runner)
    pip_install = (
        str(context.venv_python),
        "-m",
        "pip",
        "install",
        str(context.repo_root),
    )

    install_local_fallback(context)
    install_local_fallback(context)

    assert runner.commands.count(pip_install) == 2


def test_rendered_controls_schedule_0935_without_secret_values(tmp_path: Path) -> None:
    """A schedule or Desktop command carrying credentials exposes them to users."""
    context = _context(tmp_path)
    env_path = context.runtime_root / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text(
        "FEISHU_WEBHOOK_URL=https://hooks.example.test/super-secret\n",
        encoding="utf-8",
    )
    env_path.chmod(0o600)

    plist = plistlib.loads(render_launch_agent(context))
    installed = install_local_fallback(context, smoke_validated=True)
    rendered = "\n".join(
        [
            context.staged_launch_agent_path.read_text(encoding="utf-8"),
            installed.run_now.read_text(encoding="utf-8"),
            installed.view_logs.read_text(encoding="utf-8"),
        ]
    )

    assert plist["Label"] == INSTALLER_LABEL
    assert plist["StartCalendarInterval"] == {"Hour": 9, "Minute": 35}
    assert plist["ProgramArguments"][-1] == "--scheduled"
    assert "EnvironmentVariables" not in plist
    assert "super-secret" not in rendered
    assert "source " not in installed.run_now.read_text(encoding="utf-8")
    assert "--run-now" in installed.run_now.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("gh_exists", "gh_executable"),
    [(False, False), (True, False)],
)
def test_installer_refuses_missing_or_nonexecutable_github_cli(
    tmp_path: Path,
    gh_exists: bool,
    gh_executable: bool,
) -> None:
    """Accepting an unusable CLI would leave the scheduled gate unauthenticated."""
    context = _context(
        tmp_path,
        gh_exists=gh_exists,
        gh_executable=gh_executable,
    )

    with pytest.raises(InstallerError, match="github_cli"):
        install_local_fallback(context)


@pytest.mark.parametrize(
    ("command_tail", "reason"),
    [
        (("auth", "status", "--hostname", "github.com"), "github_auth"),
        (
            (
                "repo",
                "view",
                "bgu436475-ops/Baic-AI-Message-Bot",
                "--json",
                "nameWithOwner",
            ),
            "github_repository_access",
        ),
    ],
)
def test_installer_refuses_unauthenticated_repository_access(
    tmp_path: Path,
    command_tail: tuple[str, ...],
    reason: str,
) -> None:
    """A missing CLI session or private-repository grant must block installation."""
    runner = RecordingRunner()
    context = _context(tmp_path, runner=runner)
    runner.results[(str(context.gh_path), *command_tail)] = 1

    with pytest.raises(InstallerError, match=reason):
        install_local_fallback(context)


@pytest.mark.parametrize(
    ("ollama_exists", "free_bytes", "reason"),
    [
        (False, 9 * GIB, "ollama_missing"),
        (True, 8 * GIB - 1, "insufficient_disk_space"),
    ],
)
def test_installer_blocks_missing_prerequisites(
    tmp_path: Path,
    ollama_exists: bool,
    free_bytes: int,
    reason: str,
) -> None:
    """Skipping local-model or disk checks makes scheduled execution unreliable."""
    context = _context(
        tmp_path,
        ollama_exists=ollama_exists,
        free_bytes=free_bytes,
    )

    with pytest.raises(InstallerError, match=reason):
        install_local_fallback(context)


def test_schedule_bootstrap_requires_explicit_smoke_validation(tmp_path: Path) -> None:
    """Loading the agent before a no-send smoke test can trigger an unsafe send."""
    runner = RecordingRunner()
    context = _context(tmp_path, runner=runner)

    with pytest.raises(InstallerError, match="smoke_validation_required"):
        install_local_fallback(
            context,
            activate_schedule=True,
            smoke_validated=False,
        )
    assert runner.commands == []

    print_command = (
        "/bin/launchctl",
        "print",
        "gui/501/com.baic.ai-news-bot.local-fallback",
    )
    runner.results[print_command] = 3
    install_local_fallback(
        context,
        activate_schedule=True,
        smoke_validated=True,
    )

    assert (
        "/bin/launchctl",
        "bootstrap",
        "gui/501",
        str(context.launch_agent_path),
    ) in runner.commands

    runner.commands.clear()
    runner.results[print_command] = 0
    with pytest.raises(InstallerError, match="launch_agent_already_loaded"):
        install_local_fallback(
            context,
            activate_schedule=True,
            smoke_validated=True,
        )

    assert print_command in runner.commands
    assert not any(
        command[:2] == ("/bin/launchctl", "bootstrap")
        for command in runner.commands
    )


def test_inactive_install_stages_the_plist_without_loading_it(
    tmp_path: Path,
) -> None:
    """A pre-smoke install must not create a launchd-visible scheduler file."""
    runner = RecordingRunner()
    context = _context(tmp_path, runner=runner)

    install_local_fallback(context)

    status = (
        "/bin/launchctl",
        "print",
        "gui/501/com.baic.ai-news-bot.local-fallback",
    )
    staged = (
        context.runtime_root / "staging" / f"{INSTALLER_LABEL}.plist"
    )
    assert status in runner.commands
    assert staged.exists()
    assert not context.launch_agent_path.exists()
    assert not any(command[1] == "bootstrap" for command in runner.commands)


def test_schedule_activation_promotes_the_smoke_validated_staged_plist(
    tmp_path: Path,
) -> None:
    """Only explicit smoke-validated activation may expose the plist to launchd."""
    runner = RecordingRunner()
    context = _context(tmp_path, runner=runner)

    install_local_fallback(
        context,
        activate_schedule=True,
        smoke_validated=True,
    )

    staged = (
        context.runtime_root / "staging" / f"{INSTALLER_LABEL}.plist"
    )
    assert context.launch_agent_path.exists()
    assert not staged.exists()
    assert (
        "/bin/launchctl",
        "bootstrap",
        "gui/501",
        str(context.launch_agent_path),
    ) in runner.commands


def test_inactive_install_refuses_to_touch_an_existing_loaded_label(
    tmp_path: Path,
) -> None:
    """An unexpected active service must be retained for explicit operator recovery."""
    runner = RecordingRunner()
    context = _context(tmp_path, runner=runner)
    context.launch_agent_path.parent.mkdir(parents=True)
    context.launch_agent_path.write_text("existing plist", encoding="utf-8")
    status = (
        "/bin/launchctl",
        "print",
        "gui/501/com.baic.ai-news-bot.local-fallback",
    )
    runner.results[status] = 0

    with pytest.raises(InstallerError, match="launch_agent_already_loaded"):
        install_local_fallback(context)

    assert context.launch_agent_path.read_text(encoding="utf-8") == "existing plist"
    assert not (context.runtime_root / "staging").exists()


def test_inactive_install_accepts_macos_service_not_found_output(
    tmp_path: Path,
) -> None:
    """macOS rc=113 is absent only with the verified service-not-found message."""
    runner = RecordingRunner()
    context = _context(tmp_path, runner=runner)
    status = (
        "/bin/launchctl",
        "print",
        "gui/501/com.baic.ai-news-bot.local-fallback",
    )
    runner.results[status] = CommandOutcome(
        113,
        "  could NOT find   specified SERVICE\n",
    )

    install_local_fallback(context)

    assert context.staged_launch_agent_path.exists()
    assert not context.launch_agent_path.exists()


def test_inactive_install_rejects_ambiguous_macos_service_status(
    tmp_path: Path,
) -> None:
    """Exit code 113 without a service-not-found message must fail closed."""
    runner = RecordingRunner()
    context = _context(tmp_path, runner=runner)
    status = (
        "/bin/launchctl",
        "print",
        "gui/501/com.baic.ai-news-bot.local-fallback",
    )
    runner.results[status] = CommandOutcome(113, "launchctl transport error")

    with pytest.raises(InstallerError, match="launch_agent_status_failed"):
        install_local_fallback(context)

    assert not (context.runtime_root / "staging").exists()


def test_inactive_install_creates_run_now_only_after_smoke_validation(
    tmp_path: Path,
) -> None:
    """A Desktop send control must not appear before the no-send smoke check."""
    context = _context(tmp_path)

    inactive = install_local_fallback(context)
    assert inactive.view_logs.exists()
    assert not inactive.run_now.exists()

    smoke_validated = install_local_fallback(context, smoke_validated=True)
    assert smoke_validated.view_logs.exists()
    assert smoke_validated.run_now.exists()


def test_schedule_activation_refuses_a_remote_without_the_recorder_workflow(
    tmp_path: Path,
) -> None:
    """An active local sender without its remote recorder cannot safely clear sync state."""
    runner = RecordingRunner()
    context = _context(tmp_path, runner=runner)
    workflow_query = (
        str(context.gh_path),
        "api",
        (
            "repos/bgu436475-ops/Baic-AI-Message-Bot/contents/"
            ".github/workflows/record-local-delivery.yml?ref=main"
        ),
    )
    runner.results[workflow_query] = 1

    with pytest.raises(InstallerError, match="record_local_delivery_workflow"):
        install_local_fallback(
            context,
            activate_schedule=True,
            smoke_validated=True,
        )

    assert not context.launch_agent_path.exists()
    assert not any(
        command[:2] == ("/bin/launchctl", "bootstrap")
        for command in runner.commands
    )


def test_uninstall_removes_controls_and_preserves_operator_data(tmp_path: Path) -> None:
    """Rollback must not erase credentials, delivery state, models, or diagnostics."""
    install_context = _context(tmp_path)
    result = install_local_fallback(
        install_context,
        activate_schedule=True,
        smoke_validated=True,
    )
    result.env_path.write_text("FEISHU_WEBHOOK_URL=https://hooks.example.test/x\n")
    state = result.runtime_root / "state" / "daily_sends.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{}\n", encoding="utf-8")
    model = install_context.home / ".ollama" / "models" / "qwen3"
    model.parent.mkdir(parents=True)
    model.write_text("model", encoding="utf-8")
    log = install_context.logs_root / "local-fallback.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("diagnostic", encoding="utf-8")
    runner = RecordingRunner()
    runner.results[
        (
            "/bin/launchctl",
            "print",
            "gui/501/com.baic.ai-news-bot.local-fallback",
        )
    ] = 3

    summary = uninstall_local_fallback(
        UninstallContext(
            home=install_context.home,
            runner=runner,
            uid=501,
        )
    )

    assert not result.launch_agent.exists()
    assert not result.run_now.exists()
    assert not result.view_logs.exists()
    assert result.env_path.exists()
    assert state.exists()
    assert model.exists()
    assert log.exists()
    assert str(result.runtime_root) in summary
    assert str(install_context.logs_root) in summary
    assert str(install_context.home / ".ollama" / "models") in summary
    assert not any(command[1] == "bootout" for command in runner.commands)
    with pytest.raises(SystemExit):
        parse_uninstall_args(["--remove-data"])


@pytest.mark.parametrize(
    ("bootout_result", "print_result", "reason"),
    [
        (1, 0, "launch_agent_bootout_failed"),
        (0, 0, "launch_agent_still_loaded"),
    ],
)
def test_uninstall_retains_plist_when_launch_agent_cannot_be_confirmed_unloaded(
    tmp_path: Path,
    bootout_result: int,
    print_result: int,
    reason: str,
) -> None:
    """Deleting a live plist can leave an unmanageable scheduled process behind."""
    install_context = _context(tmp_path)
    result = install_local_fallback(
        install_context,
        activate_schedule=True,
        smoke_validated=True,
    )
    runner = RecordingRunner()
    bootout = (
        "/bin/launchctl",
        "bootout",
        "gui/501/com.baic.ai-news-bot.local-fallback",
    )
    status = (
        "/bin/launchctl",
        "print",
        "gui/501/com.baic.ai-news-bot.local-fallback",
    )
    runner.results[bootout] = bootout_result
    runner.sequence_results[status] = [0, print_result]
    messages: list[str] = []

    with pytest.raises(UninstallError, match=reason):
        uninstall_local_fallback(
            UninstallContext(home=install_context.home, runner=runner, uid=501),
            output=messages.append,
        )

    assert result.launch_agent.exists()
    assert messages == [reason]


def test_uninstall_checks_an_absent_plist_against_the_loaded_scheduler_label(
    tmp_path: Path,
) -> None:
    """A stale loaded label must be removed even when its plist has gone missing."""
    install_context = _context(tmp_path)
    result = install_local_fallback(
        install_context,
        activate_schedule=True,
        smoke_validated=True,
    )
    result.launch_agent.unlink()
    runner = RecordingRunner()
    status = (
        "/bin/launchctl",
        "print",
        "gui/501/com.baic.ai-news-bot.local-fallback",
    )
    runner.sequence_results[status] = [0, 3]

    uninstall_local_fallback(
        UninstallContext(home=install_context.home, runner=runner, uid=501)
    )

    assert (
        "/bin/launchctl",
        "bootout",
        "gui/501/com.baic.ai-news-bot.local-fallback",
    ) in runner.commands
    assert not result.run_now.exists()
    assert not result.view_logs.exists()


def test_uninstall_keeps_controls_when_the_loaded_label_survives_bootout(
    tmp_path: Path,
) -> None:
    """Controls remain available until launchctl confirms the scheduler is gone."""
    install_context = _context(tmp_path)
    result = install_local_fallback(
        install_context,
        activate_schedule=True,
        smoke_validated=True,
    )
    runner = RecordingRunner()
    status = (
        "/bin/launchctl",
        "print",
        "gui/501/com.baic.ai-news-bot.local-fallback",
    )
    runner.sequence_results[status] = [0, 0]
    messages: list[str] = []

    with pytest.raises(UninstallError, match="launch_agent_still_loaded"):
        uninstall_local_fallback(
            UninstallContext(home=install_context.home, runner=runner, uid=501),
            output=messages.append,
        )

    assert result.launch_agent.exists()
    assert result.run_now.exists()
    assert result.view_logs.exists()
    assert messages == ["launch_agent_still_loaded"]


def test_uninstall_is_idempotent_when_plist_and_label_are_absent(
    tmp_path: Path,
) -> None:
    """An already inactive fallback should still inspect launchctl then succeed."""
    context = _context(tmp_path)
    runner = RecordingRunner()
    status = (
        "/bin/launchctl",
        "print",
        "gui/501/com.baic.ai-news-bot.local-fallback",
    )
    runner.results[status] = 3

    summary = uninstall_local_fallback(
        UninstallContext(home=context.home, runner=runner, uid=501)
    )

    assert status in runner.commands
    assert not any(command[1] == "bootout" for command in runner.commands)
    assert str(context.runtime_root) in summary


def test_uninstall_retains_controls_when_launchctl_status_is_ambiguous(
    tmp_path: Path,
) -> None:
    """A non-service-not-found launchctl status cannot prove an absent scheduler."""
    context = _context(tmp_path)
    context.launch_agent_path.parent.mkdir(parents=True)
    context.launch_agent_path.write_text("existing plist", encoding="utf-8")
    context.run_now_path.parent.mkdir(parents=True)
    context.run_now_path.write_text("run now", encoding="utf-8")
    context.view_logs_path.write_text("view logs", encoding="utf-8")
    runner = RecordingRunner()
    status = (
        "/bin/launchctl",
        "print",
        "gui/501/com.baic.ai-news-bot.local-fallback",
    )
    runner.results[status] = 2
    messages: list[str] = []

    with pytest.raises(UninstallError, match="launch_agent_status_failed"):
        uninstall_local_fallback(
            UninstallContext(home=context.home, runner=runner, uid=501),
            output=messages.append,
        )

    assert context.launch_agent_path.exists()
    assert context.run_now_path.exists()
    assert context.view_logs_path.exists()
    assert messages == ["launch_agent_status_failed"]


def test_uninstall_accepts_macos_service_not_found_output(
    tmp_path: Path,
) -> None:
    """A fresh uninstall should accept macOS's documented absent-service response."""
    context = _context(tmp_path)
    runner = RecordingRunner()
    status = (
        "/bin/launchctl",
        "print",
        "gui/501/com.baic.ai-news-bot.local-fallback",
    )
    runner.results[status] = CommandOutcome(
        113,
        "Could not find specified service\n",
    )

    summary = uninstall_local_fallback(
        UninstallContext(home=context.home, runner=runner, uid=501)
    )

    assert str(context.runtime_root) in summary


def test_uninstall_cli_returns_nonzero_when_unload_verification_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A successful CLI exit would hide a still-running launch agent from operators."""
    import uninstall_local_fallback as uninstall_script

    monkeypatch.setattr(
        uninstall_script,
        "uninstall_local_fallback",
        lambda _context, **_kwargs: (_ for _ in ()).throw(
            UninstallError("launch_agent_still_loaded")
        ),
    )

    assert uninstall_main(["--home", str(tmp_path / "home")]) == 2


def test_ollama_download_and_healthcheck_ignore_proxy_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ollama setup network traffic must never inherit HTTP proxy settings."""
    opened: list[str] = []

    class Response(io.BytesIO):
        status = 200

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class NoProxyOpener:
        def open(self, url: str, *, timeout: int) -> Response:
            opened.append(url)
            assert timeout in {2, 30}
            return Response(b"official payload")

    def build_no_proxy_opener(
        handler: object,
    ) -> NoProxyOpener:
        assert getattr(handler, "proxies") == {}
        return NoProxyOpener()

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.test:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.test:8443")
    monkeypatch.setattr(
        ollama_installer.urllib.request,
        "build_opener",
        build_no_proxy_opener,
    )
    monkeypatch.setattr(
        ollama_installer.urllib.request,
        "urlretrieve",
        lambda *_args: (_ for _ in ()).throw(AssertionError("proxy-aware download")),
    )
    monkeypatch.setattr(
        ollama_installer.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("proxy-aware healthcheck")
        ),
    )

    destination = tmp_path / "Ollama-darwin.zip"
    ollama_installer._download("https://ollama.com/download/Ollama-darwin.zip", destination)

    assert destination.read_bytes() == b"official payload"
    assert ollama_installer._ollama_healthy() is True
    assert opened == [
        "https://ollama.com/download/Ollama-darwin.zip",
        "http://127.0.0.1:11434/api/tags",
    ]


def test_ollama_installer_verifies_download_and_never_replaces_existing_app(
    tmp_path: Path,
) -> None:
    """Bypassing verification or replacing an existing app would risk user data."""
    runner = RecordingRunner()
    downloaded: list[Path] = []

    def download(_: str, destination: Path) -> None:
        downloaded.append(destination)
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr("Ollama.app/Contents/MacOS/ollama", "binary")

    applications = tmp_path / "Applications"
    installed = install_ollama(
        OllamaInstallContext(
            applications_dir=applications,
            runner=runner,
            downloader=download,
            healthcheck=lambda: True,
            sleeper=lambda _: None,
        )
    )

    assert installed.app_path == applications / "Ollama.app"
    assert downloaded
    assert any(
        command[:4] == ("/usr/bin/codesign", "--verify", "--deep", "--strict")
        and command[-1].endswith("Ollama.app")
        for command in runner.commands
    )
    assert any(
        command[:4] == ("/usr/sbin/spctl", "--assess", "--type", "execute")
        and command[-1].endswith("Ollama.app")
        for command in runner.commands
    )

    preserved = installed.app_path / "user-data"
    preserved.write_text("do not replace", encoding="utf-8")
    runner.commands.clear()
    downloaded.clear()
    again = install_ollama(
        OllamaInstallContext(
            applications_dir=applications,
            runner=runner,
            downloader=download,
            healthcheck=lambda: True,
            sleeper=lambda _: None,
        )
    )

    assert again.app_path == installed.app_path
    assert preserved.read_text(encoding="utf-8") == "do not replace"
    assert downloaded == []
    assert any(
        command[:4] == ("/usr/bin/codesign", "--verify", "--deep", "--strict")
        and command[-1] == str(installed.app_path)
        for command in runner.commands
    )
    assert any(
        command[:4] == ("/usr/sbin/spctl", "--assess", "--type", "execute")
        and command[-1] == str(installed.app_path)
        for command in runner.commands
    )
    assert (
        "/usr/bin/open",
        "-gj",
        "-a",
        str(installed.app_path),
    ) in runner.commands
    assert (
        str(installed.app_path / "Contents/MacOS/ollama"),
        "pull",
        "qwen3:8b",
    ) in runner.commands


def test_ollama_archive_extraction_uses_ditto_to_preserve_bundle_symlinks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Python's ZipFile extraction loses app-bundle symlinks required by codesign."""
    commands: list[list[str]] = []

    class Result:
        returncode = 0

    def fake_run(command: list[str], **_: object) -> Result:
        commands.append(command)
        return Result()

    monkeypatch.setattr(ollama_installer.subprocess, "run", fake_run)

    ollama_installer._extract_ollama_archive(
        tmp_path / "Ollama-darwin.zip",
        tmp_path,
    )

    assert commands == [
        [
            "/usr/bin/ditto",
            "-x",
            "-k",
            str(tmp_path / "Ollama-darwin.zip"),
            str(tmp_path),
        ]
    ]
