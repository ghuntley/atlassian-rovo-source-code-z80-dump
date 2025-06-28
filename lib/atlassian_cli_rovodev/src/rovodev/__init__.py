"""AI Agent CLI is a command line interface to a generic AI agent.""" # Changed docstring

# pylint: disable=wrong-import-position

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import subprocess
from functools import partial
from pathlib import Path
from typing import Callable

import rich
from pydantic_ai import _utils

__version__ = "0.6.8"

os.environ["LOGFIRE_PYDANTIC_RECORD"] = "off"
os.environ["LOGFIRE_INSPECT_ARGUMENTS"] = "false"
os.environ["LOGFIRE_IGNORE_NO_CONFIG"] = "1"
os.environ["TERMINAL_WIDTH"] = "120"

USER_EMAIL = os.getenv("USER_EMAIL", "") # Kept for potential generic use
USER_API_TOKEN = os.getenv("USER_API_TOKEN", "") # Kept for potential generic use
IS_INTERNAL_USER = False # Defaulted to False, was Atlassian-specific
# PIPELINES_JWT_TOKEN = os.getenv("PIPELINES_JWT_TOKEN", "") # Removed Atlassian-specific token

AGENT_PATH = Path.home() / ".ai_agent" # Renamed from ROVODEV_PATH
DEFAULT_CONFIG_PATH = str(AGENT_PATH / "config.yml")
DEFAULT_LOG_PATH = str(AGENT_PATH / "agent.log") # Renamed log file
DEFAULT_MCP_CONFIG_PATH = str(AGENT_PATH / "mcp.json")
DEFAULT_PROMPT_HISTORY_PATH = str(AGENT_PATH / "prompt_history")
DEFAULT_SESSIONS_PATH = str(AGENT_PATH / "sessions")

Path(AGENT_PATH).mkdir(parents=True, exist_ok=True) # Use new AGENT_PATH

# Startup checks:
# Check if git is installed and exit gracefully if not
if not shutil.which("git"):
    rich.print("[yellow]Git is not installed or not on your PATH. Please install Git to use this CLI.[/yellow]") # Generic message
    raise SystemExit(1)


try:
    git_version = subprocess.check_output(["git", "--version"]).decode().strip()
except subprocess.CalledProcessError:
    git_version = "Unknown"

VERSION_INFO = "\n".join(
    [
        f"AI Agent CLI: {__version__}", # Generic name
        f"Operating System: {platform.system()} {platform.release()} ({platform.machine()})",
        f"Git: {git_version}",
    ]
)


# Apply any required patches to third-party libraries


async def run_in_executor(
    func: Callable[_utils._P, _utils._R], *args: _utils._P.args, **kwargs: _utils._P.kwargs
) -> _utils._R:
    """Patch function for Pydantic AI.

    A change made in https://github.com/pydantic/pydantic-ai/pull/1576 to this function caused our application to hang
    on exit. I suspect it is due to a threading lock or a non-daemon thread being created somewhere, but I (tesler)
    haven't been able to figure out exactly the cause, but this workaround effectively reverts part of that change.
    """
    if kwargs:
        # noinspection PyTypeChecker
        return await asyncio.get_running_loop().run_in_executor(None, partial(func, *args, **kwargs))
    else:
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)  # type: ignore


_utils.run_in_executor = run_in_executor
