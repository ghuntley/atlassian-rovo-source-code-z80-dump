from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import asdict
from typing import Any, AsyncIterator

import anyio
from loguru import logger
from pydantic_ai import Agent

from nemo.utils import MCPServerHTTP, MCPServerStdio
from rovodev.common.exceptions import MCPServerBuiltinError, MCPServerThirdPartyError


@asynccontextmanager
async def run_mcp_servers_with_error_handling(agent: Agent[Any, Any]) -> AsyncIterator[None]:
    """Run [`MCPServerStdio`s][pydantic_ai.mcp.MCPServerStdio] so they can be used by the agent.

    Returns: a context manager to start and shutdown the servers.
    """
    exit_stack = AsyncExitStack()
    try:
        mcp_server: MCPServerHTTP | MCPServerStdio
        for mcp_server in agent._mcp_servers:  # type: ignore
            try:
                await exit_stack.enter_async_context(mcp_server)
            except Exception as e:
                logger.error(f"Failed to start MCP server {asdict(mcp_server)}")
                if is_builtin_mcp_server(mcp_server):
                    raise MCPServerBuiltinError(mcp_server) from e
                else:
                    raise MCPServerThirdPartyError(mcp_server) from e
        yield
    except KeyboardInterrupt:
        logger.info("Shutting down MCP servers due to keyboard interrupt...")
        try:
            await exit_stack.aclose()
        except (anyio.ClosedResourceError, ExceptionGroup) as e:
            # Suppress cleanup errors during KeyboardInterrupt
            logger.debug(f"Suppressed MCP cleanup error during interrupt: {e}")
        raise
    finally:
        try:
            await exit_stack.aclose()
        except Exception as e:
            logger.warning(f"Error during MCP server shutdown: {e}")
            # Don't re-raise the exception to avoid masking the original exception


def is_builtin_mcp_server(mcp_server: MCPServerHTTP | MCPServerStdio) -> bool:
    """Check if the MCP server is a built-in server."""
    if isinstance(mcp_server, MCPServerHTTP):
        # Removed Atlassian-specific URL check for built-in HTTP MCP server.
        # A generic template might define its own criteria for a built-in HTTP server if needed.
        pass
    elif isinstance(mcp_server, MCPServerStdio):
        # Assuming "nautilus" is the name of the bundled STDIO MCP server for this template.
        if "nautilus" in mcp_server.command or "nautilus" in mcp_server.args:
            return True
    return False
