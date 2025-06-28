import asyncio
import base64

import rich
from loguru import logger

from nemo.agents import AcraMini
from nemo.constants import DEFAULT_MAX_TOKENS
from nemo.utils import MCPServerHTTP, MCPServerStdio
from rovodev import USER_API_TOKEN, USER_EMAIL
from rovodev.common import dynamic_configuration
from rovodev.common.config import load_mcp_servers_from_json, save_config
from rovodev.common.config_model import AIAgentConfig # Changed RovoDevConfig
from rovodev.modules.memory import get_memory_instructions
from rovodev.modules.tool_permissions import ToolPermissionManager
from rovodev.ui.components import Choice, user_menu_panel_sync

MCP_3P_DISCLAIMER = """\
Would you like to allow the use of the following third-party MCP server:
  
  {server_id}

When integrating with third party products, please comply with their terms of use.\
"""


def check_mcp_server_allowed(server_id: str) -> bool:
    """Check if the user wants to allow the MCP server."""
    return user_menu_panel_sync(
        message=MCP_3P_DISCLAIMER.format(server_id=server_id),
        choices=[Choice(name="Yes", value=True), Choice(name="No", value=False)],
        title="Third-party MCP server",
    )


def create_agent_factory(config: AIAgentConfig, config_file: str, interactive: bool = True) -> AcraMini: # Changed RovoDevConfig
    """Create the agent factory."""
    # Ensure that user has agreed to allow the use of any additional MCP servers
    additional_mcp_servers = []
    for mcp_server in load_mcp_servers_from_json(config.mcp.mcp_config_path):
        if isinstance(mcp_server, MCPServerHTTP):
            server_id = mcp_server.url
        else:
            server_id = " ".join([mcp_server.command] + list(mcp_server.args))
        if server_id not in config.tool_permissions.allowed_mcp_servers:
            server_allowed = check_mcp_server_allowed(server_id)
            if server_allowed:
                config.tool_permissions.allowed_mcp_servers.append(server_id)
                save_config(config, config_file)
        if server_id not in config.tool_permissions.allowed_mcp_servers:
            logger.warning(f"[yellow]MCP server '{server_id}' denied by the user.[/yellow]")
            rich.print(f"[yellow]MCP server '{server_id}' denied by the user.[/yellow]")
            continue
        else:
            additional_mcp_servers.append(mcp_server)

    # b64_email_token = base64.b64encode(f"{USER_EMAIL}:{USER_API_TOKEN}".encode()).decode() # Potentially generic auth header
    # auth_header = f"Basic {b64_email_token}" # Potentially generic auth header
    # Removed hardcoded Atlassian MCP server addition:
    # if USER_EMAIL and USER_API_TOKEN:
    #     additional_mcp_servers.append(
    #         MCPServerHTTP("https://mcp.atlassian.com/v1/native/mcp", {"Authorization": auth_header})
    #     )
    #     additional_mcp_servers[-1].exclude_tools = ["atlassianUserInfo"]
    for mcp_server in additional_mcp_servers:
        if isinstance(mcp_server, MCPServerStdio):
            # Redirect MCP server logs to the log file
            mcp_server.log_file = config.logging.path

    tool_permission_manager = ToolPermissionManager(config=config, config_path=config_file, interactive=interactive)
    prompt_version = "acra-mini"
    if dynamic_configuration and dynamic_configuration.config().enable_efficient_agent:
        prompt_version = "efficient"

    return AcraMini(
        name="Response",
        model=config.agent.model_id,
        model_settings={"temperature": config.agent.temperature, "max_tokens": DEFAULT_MAX_TOKENS},
        additional_system_prompt=config.agent.additional_system_prompt,
        instructions=get_memory_instructions(log_paths=True),
        enable_deep_plan=config.agent.experimental.enable_deep_plan_tool,
        enable_delegation=config.agent.experimental.enable_delegation_tool,
        enable_shadow_mode=config.agent.experimental.enable_shadow_mode,
        additional_mcp_servers=additional_mcp_servers,  # type: ignore
        tool_call_validator=tool_permission_manager.handle_tool_calls,
        save_patch_artifact=False,
        workspace_kwargs={"workspace_view_max_files": 1000},
        prompt_version=prompt_version,
    )
