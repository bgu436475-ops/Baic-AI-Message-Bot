from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from install_local_fallback import INSTALLER_LABEL


CommandRunner = Callable[[Sequence[str]], int]


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


@dataclass(frozen=True)
class UninstallContext:
    home: Path
    runner: CommandRunner = _run_silently
    uid: int = 0

    @property
    def runtime_root(self) -> Path:
        return self.home / "Library/Application Support/Baic-AI-Message-Bot"

    @property
    def logs_root(self) -> Path:
        return self.home / "Library/Logs/Baic-AI-Message-Bot"

    @property
    def model_root(self) -> Path:
        return self.home / ".ollama/models"

    @property
    def launch_agent_path(self) -> Path:
        return self.home / "Library/LaunchAgents" / f"{INSTALLER_LABEL}.plist"

    @property
    def run_now_path(self) -> Path:
        return self.home / "Desktop/立即运行 Plan 2.command"

    @property
    def view_logs_path(self) -> Path:
        return self.home / "Desktop/查看 Plan 2 日志.command"


def uninstall_local_fallback(
    context: UninstallContext,
    output: Callable[[str], None] = print,
) -> str:
    """Unload only the agent and exact Desktop controls; preserve all diagnostics."""
    if context.launch_agent_path.exists():
        try:
            context.runner(
                [
                    "/bin/launchctl",
                    "bootout",
                    f"gui/{context.uid}",
                    str(context.launch_agent_path),
                ]
            )
        except OSError:
            pass
        context.launch_agent_path.unlink()
    for path in (context.run_now_path, context.view_logs_path):
        if path.exists():
            path.unlink()
    summary = (
        "Preserved runtime/state/environment: "
        f"{context.runtime_root}\nPreserved logs: {context.logs_root}\n"
        f"Preserved Ollama model data: {context.model_root}"
    )
    output(summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remove local fallback controls")
    parser.add_argument("--home", type=Path, default=Path.home())
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    uninstall_local_fallback(UninstallContext(home=args.home, uid=os.getuid()))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
