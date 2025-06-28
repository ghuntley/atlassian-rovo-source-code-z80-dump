"""AI Agent CLI Configuration models.""" # Changed RovoDev

from typing import Literal

from pydantic import Field

from rovodev import (
    DEFAULT_LOG_PATH,
    DEFAULT_MCP_CONFIG_PATH,
    DEFAULT_SESSIONS_PATH,
    IS_INTERNAL_USER,
)

from . import BaseConfig, DirStr, FileStr


class ExperimentalConfig(BaseConfig):
    """Experimental features configuration."""

    enable_deep_plan_tool: bool = Field(
        default=False,
        exclude=not IS_INTERNAL_USER,
        description="Enable the deep planning tool for complex task decomposition",
    )
    enable_delegation_tool: bool = Field(
        default=False, exclude=not IS_INTERNAL_USER, description="Enable task delegation to sub-agents"
    )
    enable_shadow_mode: bool = Field(
        default=False,
        description=(
            "Enable/disable the agent to run in shadow mode. This will run the agent on a temporary clone of your "
            "workspace, prompting you before any changes are applied to your working directory."
        ),
    )


class AgentConfig(BaseConfig):
    """Agent configuration."""

    additional_system_prompt: str | None = Field(
        default=None, description="Additional system prompt to append to the agent's default system prompt"
    )
    streaming: bool = Field(default=True, description="Enable streaming responses from the AI model")
    temperature: float = Field(default=0.3, description="Temperature setting for AI model responses (0.0-1.0)")
    # Hide the model_id field from external users
    model_id: str = Field(default="claude-sonnet-4@20250514", exclude=not IS_INTERNAL_USER)
    experimental: ExperimentalConfig = Field(default_factory=ExperimentalConfig)


class SessionsConfig(BaseConfig):
    """Sessions configuration."""

    auto_restore: bool = Field(default=False, description="Automatically restore the last active session on startup")
    persistence_dir: DirStr = Field(default=DEFAULT_SESSIONS_PATH, description="Directory where session data is stored")


class ConsoleConfig(BaseConfig):
    """Console configuration."""

    output_format: Literal["markdown", "simple", "raw"] = Field(
        default="markdown", description="Output format for console display (markdown, simple, or raw)"
    )
    show_tool_results: bool = Field(default=True, description="Show tool execution results in the console")


class LoggingConfig(BaseConfig):
    """Logging configuration."""

    path: FileStr = Field(default=DEFAULT_LOG_PATH, description="Path to the log file")
    # Enable prompt collection for internal users only and exclude it from config serialization for external users
    enable_prompt_collection: bool = Field(
        default=IS_INTERNAL_USER,
        exclude=not IS_INTERNAL_USER,
        description="Enable collection of prompts for debugging and analysis",
    )


class MCPConfig(BaseConfig):
    """MCP configuration."""

    mcp_config_path: FileStr = Field(
        default=DEFAULT_MCP_CONFIG_PATH, description="Path to the MCP (Model Context Protocol) configuration file"
    )


Permission = Literal["allow", "ask", "deny"]


class BashCommandConfig(BaseConfig):
    """Bash command configuration."""

    command: str
    permission: Permission


class BashPermissionConfig(BaseConfig):
    """Bash tool permissions configuration."""

    default: Permission = Field(default="ask", description="Default permission for bash commands not explicitly listed")
    commands: list[BashCommandConfig] = Field(
        default=[
            BashCommandConfig(command="ls.*", permission="allow"),
            BashCommandConfig(command="cat.*", permission="allow"),
            BashCommandConfig(command="echo.*", permission="allow"),
            BashCommandConfig(command="git status", permission="allow"),
            BashCommandConfig(command="git diff.*", permission="allow"),
            BashCommandConfig(command="git log.*", permission="allow"),
            BashCommandConfig(command="pwd", permission="allow"),
        ],
        description="List of specific bash commands with their permission settings",
    )


class ToolPermissionsConfig(BaseConfig):
    """Tool permissions configuration."""

    allow_all: bool = False
    default: Permission = Field(default="ask", description="Default permission for tools not explicitly listed")
    tools: dict[str, Permission] = Field(
        default={
            "create_file": "ask",
            "delete_file": "ask",
            "find_and_replace_code": "ask",
            "open_files": "allow",
            "expand_code_chunks": "allow",
            "expand_folder": "allow",
            "grep_file_content": "allow",
            "grep_file_paths": "allow",
            # Removed Atlassian-specific tools from default permissions:
            # "getAccessibleAtlassianResources": "allow",
            # "getConfluenceSpaces": "allow",
            # "getConfluencePages": "allow",
            # "getPagesInConfluenceSpace": "allow",
            # "getConfluencePageAncestors": "allow",
            # "getConfluencePageFooterComments": "allow",
            # "getConfluencePageInlineComments": "allow",
            # "getConfluencePageDescendants": "allow",
            # "searchConfluenceUsingCql": "allow",
            # "getJiraIssue": "allow",
            # "getTransitionsForJiraIssue": "allow",
            # "lookupJiraAccountId": "allow",
            # "searchJiraIssuesUsingJql": "allow",
            # "getJiraIssueRemoteIssueLinks": "allow",
            # "getVisibleJiraProjects": "allow",
            # "getJiraProjectIssueTypesMetadata": "allow",
            # "createConfluencePage": "ask",
            # "updateConfluencePage": "ask",
            # "createConfluenceFooterComment": "ask",
            # "createConfluenceInlineComment": "ask",
            # "editJiraIssue": "ask",
            # "createJiraIssue": "ask",
            # "transitionJiraIssue": "ask",
            # "addCommentToJiraIssue": "ask",
        },
        description="Permission settings for specific tools",
    )
    bash: BashPermissionConfig = Field(default_factory=BashPermissionConfig)
    allowed_mcp_servers: list[str] = Field(default_factory=list, description="List of allowed MCP server names")


class AIAgentConfigV1(BaseConfig): # Changed RovoDevConfigV1
    """Root configuration model V1."""

    version: Literal[1] = 1
    agent: AgentConfig = Field(default_factory=AgentConfig)
    sessions: SessionsConfig = Field(default_factory=SessionsConfig)
    console: ConsoleConfig = Field(default_factory=ConsoleConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    tool_permissions: ToolPermissionsConfig = Field(default_factory=ToolPermissionsConfig)
