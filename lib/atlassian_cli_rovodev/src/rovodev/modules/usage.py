"""Utilities for reporting usage statistics."""

from typing import Any

# import httpx # Removed
# import humanize # Removed
import rich # Kept for potential rich.print usage
from loguru import logger # Kept for logging
# from rich import box # Removed
from rich.console import Console # Kept
# from rich.panel import Panel # Removed

import nemo # Kept for nemo.AUTH_METHOD check, though this might become irrelevant
# from nemo.constants import DEFAULT_PANEL_WIDTH # Removed
# from nemo.utils.ai_gateway import get_ai_gateway_headers # Removed
# from rovodev.common.exceptions import EntitlementCheckFailed, RovoDevError, UnauthorizedError # Removed, as get_usage is removed

console = Console()

# USAGE_TEMPLATE = """...""" # Removed template


# def get_usage() -> dict[str, Any] | str: # Removed function
#     """Fetch the current usage statistics from the API."""
#     # ... (Atlassian-specific implementation removed) ...
#     pass


def handle_usage_command() -> str | None:
    """Handle the /usage command."""
    # The original /usage command was tied to Atlassian's credit system.
    # For a generic template, this functionality is removed.
    # nemo.AUTH_METHOD check might also need to be re-evaluated or removed
    # if the concept of specific auth methods tied to usage is removed.
    message = (
        "Usage tracking is not configured for this AI agent.\n"
        "If you need to track token usage, this would typically be handled by your LLM provider or a custom backend."
    )
    rich.print(message)
    return
