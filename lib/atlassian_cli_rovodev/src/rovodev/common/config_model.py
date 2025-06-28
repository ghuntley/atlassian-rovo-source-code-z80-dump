"""Rovo Dev CLI Configuration models."""

from typing import Sequence

from pydantic import BaseModel, Field

from nemo.utils import MCPServerHTTP, MCPServerStdio
from rovodev.common.config_versions import BaseConfig
from rovodev.common.config_versions.v1 import AIAgentConfigV1 # Changed RovoDevConfigV1


class MCPServerStdioConfig(BaseModel, MCPServerStdio):
    """MCP server configuration for stdio."""

    args: Sequence[str] = Field(default_factory=list)

    def model_dump(self, *args, **kwargs):
        data = super().model_dump(*args, **kwargs)
        data.pop("log_file", None)
        return data


class MCPServersFileConfig(BaseConfig):
    """MCP servers file configuration."""

    mcp_servers: dict[str, MCPServerHTTP | MCPServerStdioConfig]


AIAgentConfig = AIAgentConfigV1 # Changed RovoDevConfig
