import asyncio
import json
import re
import sys
from typing import Any, Dict, Literal

import bashlex
import logfire
from pydantic_ai.messages import ModelResponse, ToolCallPart

from nemo.context import SessionContext
from rovodev.common.config import load_config, save_config
from rovodev.common.config_model import AIAgentConfig # Changed RovoDevConfig
from rovodev.common.config_versions.v1 import BashCommandConfig
from rovodev.ui.components import Choice, user_menu_panel_sync

Permission = Literal["allow", "deny", "ask"]
PermissionScope = Literal["always", "session", "once"]


class ToolPermissionManager:
    """Tool permission manager for AI Agent CLI.""" # Changed RovoDev

    def __init__(self, config: AIAgentConfig, config_path: str, interactive: bool = True) -> None: # Changed RovoDevConfig
        self._tool_permissions = config.tool_permissions
        self._config_path = config_path
        self._interactive = interactive and sys.stdin.isatty()

    def handle_tool_calls(self, model_response: ModelResponse, ctx: SessionContext) -> ModelResponse:
        """Handle tool calls and update tool permissions."""
        denied_tool_calls = set()
        for part in model_response.parts:
            if isinstance(part, ToolCallPart):
                if self._tool_permissions.allow_all:
                    logfire.info(
                        "Tool permission decision",
                        tool_name=part.tool_name,
                        decision="allow",
                        scope="session",
                        source="config",
                        _tags=["permission"],
                    )
                    continue
                if part.tool_name == "bash":
                    args = json.loads(part.args) if isinstance(part.args, str) else part.args
                    command = args.get("command", "no command")
                    is_compound_or_redirection = False
                    try:
                        for ast in bashlex.parse(command):
                            if _has_compound_or_redirection(ast):
                                is_compound_or_redirection = True
                                break
                    except bashlex.errors.ParsingError:
                        # If parsing fails, treat it as a complex command
                        is_compound_or_redirection = True
                    bash_tool_permission = None
                    for cmd_with_perm in self._tool_permissions.bash.commands:
                        # Check for exact match first
                        if command == cmd_with_perm.command:
                            bash_tool_permission = cmd_with_perm
                            break
                    if not bash_tool_permission and not is_compound_or_redirection:
                        # If this is a simple command, check for regex match
                        for cmd_with_perm in self._tool_permissions.bash.commands:
                            if valid_regex(cmd_with_perm.command) and re.fullmatch(cmd_with_perm.command, command):
                                bash_tool_permission = cmd_with_perm
                                break
                    if not bash_tool_permission:
                        # If no match found, create a new permission entry
                        bash_tool_permission = BashCommandConfig(
                            command=command, permission=self._tool_permissions.bash.default
                        )
                        self._tool_permissions.bash.commands.append(bash_tool_permission)
                    if bash_tool_permission.permission == "ask":
                        pattern = None
                        if not is_compound_or_redirection:
                            pattern = command.split()[0] + ".*"
                        pattern_or_command, permission, scope = self._ask_tool_permission(
                            f"bash with command '{command}'",
                            pattern=pattern,
                        )
                        if pattern_or_command == pattern:
                            bash_tool_permission.command = pattern
                        if scope == "always":
                            # Write the permission to the config file
                            self._write_bash_tool_permission(bash_tool_permission.command, permission)
                        if scope in ["session", "always"]:
                            # Write the permission to the current session config
                            bash_tool_permission.permission = permission
                        # Log permission decision
                        logfire.info(
                            "Tool permission decision",
                            tool_name=part.tool_name,
                            command=command,
                            decision=permission,
                            scope=scope,
                            source="user_decision",
                            is_compound_command=is_compound_or_redirection,
                            pattern_used=(pattern_or_command != command),
                            _tags=["permission"],
                        )

                        if permission == "deny":
                            denied_tool_calls.add(part.tool_name)
                            self._suppress_tool_call(part, scope)
                    elif bash_tool_permission.permission == "allow":
                        # Log permission allow from config
                        logfire.info(
                            "Tool permission decision",
                            tool_name=part.tool_name,
                            command=command,
                            decision="allow",
                            scope="session",
                            source="config",
                            is_compound_command=is_compound_or_redirection,
                            _tags=["permission"],
                        )
                    if bash_tool_permission.permission == "deny":
                        # Log permission denial from config
                        logfire.info(
                            "Tool permission decision",
                            tool_name=part.tool_name,
                            command=command,
                            decision="deny",
                            scope="session",
                            source="config",
                            _tags=["permission"],
                        )

                        denied_tool_calls.add(part.tool_name)
                        self._suppress_tool_call(part, "session")
                elif part.tool_name == "powershell":
                    args = json.loads(part.args) if isinstance(part.args, str) else part.args
                    command = args.get("command", "no command")
                    powershell_tool_permission = None

                    # Check for exact match
                    for cmd_with_perm in self._tool_permissions.bash.commands:
                        if command == cmd_with_perm.command:
                            bash_tool_permission = cmd_with_perm
                            break

                    if not powershell_tool_permission:
                        # If no match found, create a new permission entry
                        powershell_tool_permission = BashCommandConfig(
                            command=command, permission=self._tool_permissions.bash.default
                        )
                        self._tool_permissions.bash.commands.append(powershell_tool_permission)

                    if powershell_tool_permission.permission == "ask":
                        command, permission, scope = self._ask_tool_permission(
                            f"powershell with command '{command}'",
                        )
                        if scope == "always":
                            # Write the permission to the config file
                            self._write_bash_tool_permission(powershell_tool_permission.command, permission)
                        if scope in ["session", "always"]:
                            # Write the permission to the current session config
                            powershell_tool_permission.permission = permission
                        # Log permission decision
                        logfire.info(
                            "Tool permission decision",
                            tool_name=part.tool_name,
                            command=command,
                            decision=permission,
                            scope=scope,
                            source="user_decision",
                            _tags=["permission"],
                        )

                        if permission == "deny":
                            denied_tool_calls.add(part.tool_name)
                            self._suppress_tool_call(part, scope)
                    elif powershell_tool_permission.permission == "allow":
                        # Log permission allow from config
                        logfire.info(
                            "Tool permission decision",
                            tool_name=part.tool_name,
                            command=command,
                            decision="allow",
                            scope="session",
                            source="config",
                            _tags=["permission"],
                        )

                    if powershell_tool_permission.permission == "deny":
                        # Log permission denial from config
                        logfire.info(
                            "Tool permission decision",
                            tool_name=part.tool_name,
                            command=command,
                            decision="deny",
                            scope="session",
                            source="config",
                            _tags=["permission"],
                        )

                        denied_tool_calls.add(part.tool_name)
                        self._suppress_tool_call(part, "session")
                else:
                    if part.tool_name not in self._tool_permissions.tools:
                        self._tool_permissions.tools[part.tool_name] = self._tool_permissions.default
                    if self._tool_permissions.tools[part.tool_name] == "ask":
                        _, permission, scope = self._ask_tool_permission(part.tool_name)
                        if scope == "always":
                            # Write the permission to the config file
                            self._write_tool_permission(part.tool_name, permission)
                        if scope in ["session", "always"]:
                            # Write the permission to the current session config
                            self._tool_permissions.tools[part.tool_name] = permission
                        # Log permission decision
                        logfire.info(
                            "Tool permission decision",
                            tool_name=part.tool_name,
                            decision=permission,
                            scope=scope,
                            source="user_decision",
                            _tags=["permission"],
                        )

                        if permission == "deny":
                            denied_tool_calls.add(part.tool_name)
                            self._suppress_tool_call(part, scope)
                    elif self._tool_permissions.tools[part.tool_name] == "allow":
                        # Log permission allow from config
                        logfire.info(
                            "Tool permission decision",
                            tool_name=part.tool_name,
                            decision="allow",
                            scope="session",
                            source="config",
                            _tags=["permission"],
                        )
                    if self._tool_permissions.tools[part.tool_name] == "deny":
                        # Log permission denial from config
                        logfire.info(
                            "Tool permission decision",
                            tool_name=part.tool_name,
                            decision="deny",
                            scope="session",
                            source="config",
                            _tags=["permission"],
                        )

                        denied_tool_calls.add(part.tool_name)
                        self._suppress_tool_call(part, "session")

        return model_response

    def _write_tool_permission(self, tool_name: str, tool_permission: Permission) -> None:
        """Write tool permissions to the config file."""
        config = load_config(self._config_path)
        config.tool_permissions.tools[tool_name] = tool_permission
        save_config(config, self._config_path)

    def _write_bash_tool_permission(self, command: str, tool_permission: Permission) -> None:
        """Write tool permissions to the config file."""
        config = load_config(self._config_path)
        for command_permission in config.tool_permissions.bash.commands:
            if command_permission.command == command:
                command_permission.permission = tool_permission
                break
        else:
            config.tool_permissions.bash.commands.append(BashCommandConfig(command=command, permission=tool_permission))
        save_config(config, self._config_path)

    def _ask_tool_permission(
        self,
        tool_name: str,
        pattern: str | None = None,
    ) -> tuple[str, Permission, PermissionScope]:
        """Ask the user for tool permission."""
        if not self._interactive:
            return tool_name, "deny", "session"

        shown_tool_name = tool_name
        enable_always = True
        if len(shown_tool_name) > 200:
            shown_tool_name = shown_tool_name[:200] + "..."
            # Prevent storing very long commands in the config file
            enable_always = False

        choices = [
            Choice(value=(tool_name, "allow", "once"), name="Allow (once)"),
            Choice(value=(tool_name, "allow", "session"), name="Allow (session)"),
        ]
        if enable_always:
            choices.append(Choice(value=(tool_name, "allow", "always"), name="Allow (always)"))
        if pattern:
            pattern_command = pattern.rstrip(".*")
            choices.append(
                Choice(
                    value=(pattern, "allow", "always"),
                    name=f"Allow (always) for all '{pattern_command}' commands",
                )
            )
        choices.extend(
            [
                Choice(value=(tool_name, "deny", "once"), name="Deny (once)"),
                Choice(value=(tool_name, "deny", "session"), name="Deny (session)"),
            ]
        )
        if enable_always:
            choices.append(Choice(value=(tool_name, "deny", "always"), name="Deny (always)"))
        return user_menu_panel_sync(
            message=f"Requesting permission to use tool {shown_tool_name}. Would you like to allow this tool?",
            choices=choices,
            title="Permissions required",
            escape_return_value=(tool_name, "deny", "once"),
        )

    def _suppress_tool_call(self, tool_call_part: ToolCallPart, scope: PermissionScope) -> None:
        """Suppress tool call."""
        if scope in ["session", "always"]:
            tool_call_part.args = {
                "_suppress_tool_call": (
                    "User denied permission to use this function. DO NOT attempt to use this function again."
                )
            }
        else:
            tool_call_part.args = {"_suppress_tool_call": "User denied permission to make this function call."}


def _has_compound_or_redirection(ast_node):
    """Detect any redirections or compound statements."""
    if hasattr(ast_node, "kind"):
        if ast_node.kind in ("operator", "redirect", "commandsubstitution", "processsubstitution", "pipe"):
            return True
        # Recursively check children
        for attr in ("parts", "list", "command"):
            value = getattr(ast_node, attr, None)
            if value:
                if isinstance(value, list):
                    for node in value:
                        if _has_compound_or_redirection(node):
                            return True
                else:
                    if _has_compound_or_redirection(value):
                        return True
    return False


def valid_regex(pattern: str) -> bool:
    """Check if a string is a valid regex pattern."""
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False
