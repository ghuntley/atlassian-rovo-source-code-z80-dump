import json
from unittest.mock import Mock, patch

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from pydantic_ai.messages import ModelResponse, ToolCallPart

from rovodev.common.config import load_config, save_config
from rovodev.common.config_model import AIAgentConfig # Changed RovoDevConfig
from rovodev.common.config_versions.v1 import ToolPermissionsConfig
from rovodev.modules.tool_permissions import ToolPermissionManager
from rovodev.ui.components.user_menu_panel import Choice


@pytest.fixture(autouse=True, scope="function")
def mock_input():
    with create_pipe_input() as pipe_input:
        with create_app_session(input=pipe_input, output=DummyOutput()):
            yield pipe_input


@pytest.fixture
def config_path(tmp_path):
    return str(tmp_path / "config.yml")


@pytest.fixture
def config(config_path):
    config = AIAgentConfig() # Changed RovoDevConfig
    config.tool_permissions = ToolPermissionsConfig.model_validate(
        {"default": "ask", "tools": {}, "bash": {"default": "ask", "commands": []}}
    )
    save_config(config, config_path)
    return config


@pytest.fixture
def tool_permission_manager(config, config_path):
    return ToolPermissionManager(config, config_path)


@pytest.fixture
def mock_select():
    """Mock the user_menu_panel function."""
    with patch("rovodev.modules.tool_permissions.user_menu_panel_sync") as mock_select:
        yield mock_select


def test_init_tool_permission_manager(config, config_path):
    manager = ToolPermissionManager(config, config_path)
    assert manager._config_path == config_path
    assert manager._interactive is False


def test_handle_non_bash_tool_allow(tool_permission_manager, config_path, mock_select):
    mock_select.return_value = ("test_tool_allow", "allow", "always")
    tool_permission_manager._interactive = True

    response = ModelResponse(parts=[ToolCallPart(tool_name="test_tool_allow", args={"test": "value"})])

    result = tool_permission_manager.handle_tool_calls(response, Mock())

    assert "test_tool_allow" in tool_permission_manager._tool_permissions.tools
    assert tool_permission_manager._tool_permissions.tools["test_tool_allow"] == "allow"
    assert result.parts[0].args == {"test": "value"}

    # Check that the permission is saved to the config file because it's always-scoped
    assert load_config(config_path).tool_permissions.tools["test_tool_allow"] == "allow"


def test_handle_non_bash_tool_deny(tool_permission_manager, config_path, mock_select):
    mock_select.return_value = ("test_tool_deny", "deny", "session")
    tool_permission_manager._interactive = True

    response = ModelResponse(parts=[ToolCallPart(tool_name="test_tool_deny", args={"test": "value"})])

    result = tool_permission_manager.handle_tool_calls(response, Mock())

    assert "test_tool_deny" in tool_permission_manager._tool_permissions.tools
    assert tool_permission_manager._tool_permissions.tools["test_tool_deny"] == "deny"
    assert "_suppress_tool_call" in result.parts[0].args

    # Check that the permission is not saved to the config file because it's session-scoped
    assert "test_tool_deny" not in load_config(config_path).tool_permissions.tools


def test_handle_bash_tool_allow(tool_permission_manager, config_path, mock_select):
    mock_select.return_value = ("echo test", "allow", "always")
    tool_permission_manager._interactive = True

    response = ModelResponse(parts=[ToolCallPart(tool_name="bash", args=json.dumps({"command": "echo test"}))])

    result = tool_permission_manager.handle_tool_calls(response, Mock())

    bash_permission = next(
        perm for perm in tool_permission_manager._tool_permissions.bash.commands if perm.command == "echo test"
    )
    assert bash_permission.permission == "allow"
    assert result.parts[0].args == json.dumps({"command": "echo test"})

    # Check that the permission is saved to the config file because it's always-scoped
    config = load_config(config_path)
    assert config.tool_permissions.bash.commands[0].command == "echo test"
    assert config.tool_permissions.bash.commands[0].permission == "allow"


def test_handle_bash_tool_deny(tool_permission_manager, config_path, mock_select):
    mock_select.return_value = ("echo test", "deny", "session")
    tool_permission_manager._interactive = True

    response = ModelResponse(parts=[ToolCallPart(tool_name="bash", args=json.dumps({"command": "echo test"}))])

    result = tool_permission_manager.handle_tool_calls(response, Mock())

    bash_permission = next(
        perm for perm in tool_permission_manager._tool_permissions.bash.commands if perm.command == "echo test"
    )
    assert bash_permission.permission == "deny"
    assert "_suppress_tool_call" in result.parts[0].args

    # Check that the permission is not saved to the config file because it's session-scoped
    commands_with_permissions = [perm.command for perm in load_config(config_path).tool_permissions.bash.commands]
    assert "echo test" not in commands_with_permissions


def test_handle_compound_bash_command(tool_permission_manager, config_path, mock_select):
    """Test that compound commands (with pipes, redirections etc) are handled correctly."""
    mock_select.return_value = ("echo test | grep test", "allow", "always")
    tool_permission_manager._interactive = True

    # First try with a compound command
    response = ModelResponse(
        parts=[ToolCallPart(tool_name="bash", args=json.dumps({"command": "echo test | grep test"}))]
    )
    tool_permission_manager.handle_tool_calls(response, Mock())

    # Verify the command is stored exactly as is, not as a pattern
    bash_permission = next(
        perm
        for perm in tool_permission_manager._tool_permissions.bash.commands
        if perm.command == "echo test | grep test"
    )
    assert bash_permission.permission == "allow"
    assert not any(
        "|" in perm.command
        for perm in load_config(config_path).tool_permissions.bash.commands
        if perm.command != "echo test | grep test"
    )


def test_handle_powershell_tool_allow(tool_permission_manager, config_path, mock_select):
    """Test handling of powershell commands with allow permission."""
    mock_select.return_value = ("Get-Process", "allow", "always")
    tool_permission_manager._interactive = True

    response = ModelResponse(parts=[ToolCallPart(tool_name="powershell", args=json.dumps({"command": "Get-Process"}))])

    result = tool_permission_manager.handle_tool_calls(response, Mock())

    # Verify command was added with allow permission
    bash_permission = next(
        perm for perm in tool_permission_manager._tool_permissions.bash.commands if perm.command == "Get-Process"
    )
    assert bash_permission.permission == "allow"
    assert result.parts[0].args == json.dumps({"command": "Get-Process"})

    # Check that the permission is saved to the config file
    config = load_config(config_path)
    assert config.tool_permissions.bash.commands[0].command == "Get-Process"
    assert config.tool_permissions.bash.commands[0].permission == "allow"


def test_handle_powershell_tool_deny(tool_permission_manager, config_path, mock_select):
    """Test handling of powershell commands with deny permission."""
    mock_select.return_value = ("Get-Service", "deny", "session")
    tool_permission_manager._interactive = True

    response = ModelResponse(parts=[ToolCallPart(tool_name="powershell", args=json.dumps({"command": "Get-Service"}))])

    result = tool_permission_manager.handle_tool_calls(response, Mock())

    # Verify command was added with deny permission
    bash_permission = next(
        perm for perm in tool_permission_manager._tool_permissions.bash.commands if perm.command == "Get-Service"
    )
    assert bash_permission.permission == "deny"
    assert "_suppress_tool_call" in result.parts[0].args

    # Check that the permission is not saved to the config file (session-scoped)
    commands_with_permissions = [perm.command for perm in load_config(config_path).tool_permissions.bash.commands]
    assert "Get-Service" not in commands_with_permissions


def test_handle_powershell_compound_command(tool_permission_manager, config_path, mock_select):
    """Test that powershell commands with pipes are handled without bashlex parsing."""
    mock_select.return_value = ("Get-Process | Where-Object { $_.CPU -gt 10 }", "allow", "always")
    tool_permission_manager._interactive = True

    response = ModelResponse(
        parts=[
            ToolCallPart(
                tool_name="powershell",
                args=json.dumps({"command": "Get-Process | Where-Object { $_.CPU -gt 10 }"}),
            )
        ]
    )
    result = tool_permission_manager.handle_tool_calls(response, Mock())

    # Verify the command is stored and no parsing error occurred
    config = load_config(config_path)
    assert len(config.tool_permissions.bash.commands) == 1
    assert config.tool_permissions.bash.commands[0].command == "Get-Process | Where-Object { $_.CPU -gt 10 }"
    assert config.tool_permissions.bash.commands[0].permission == "allow"

    # Verify that a pattern option was not offered
    choices = mock_select.call_args[1]["choices"]
    pattern_choices = [choice for choice in choices if "all 'Get-Process'" in choice["name"]]
    assert len(pattern_choices) == 0


def test_pattern_matching_behavior(tool_permission_manager, config_path, mock_select):
    """Test that pattern matching works correctly for simple commands but not compound ones."""
    # Set up a pattern permission
    mock_select.return_value = ("git.*", "deny", "always")
    tool_permission_manager._interactive = True

    response = ModelResponse(parts=[ToolCallPart(tool_name="bash", args=json.dumps({"command": "git status"}))])
    tool_permission_manager.handle_tool_calls(response, Mock())

    # Test pattern matches simple command
    response = ModelResponse(parts=[ToolCallPart(tool_name="bash", args=json.dumps({"command": "git log"}))])
    result = tool_permission_manager.handle_tool_calls(response, Mock())
    assert "_suppress_tool_call" in result.parts[0].args

    # Test pattern doesn't match compound command
    mock_select.return_value = ("git log | grep test", "allow", "always")
    response = ModelResponse(
        parts=[ToolCallPart(tool_name="bash", args=json.dumps({"command": "git log | grep test"}))]
    )
    result = tool_permission_manager.handle_tool_calls(response, Mock())
    assert "_suppress_tool_call" not in result.parts[0].args


def test_long_command_handling(tool_permission_manager, config_path, mock_select):
    """Test that very long commands (>200 chars) are handled correctly."""
    # Create a command that's over 200 characters
    tool_permission_manager._interactive = True
    long_command = "echo " + "very_long_argument_" * 15
    assert len(long_command) > 200

    mock_select.return_value = (long_command, "allow", "session")

    response = ModelResponse(parts=[ToolCallPart(tool_name="bash", args=json.dumps({"command": long_command}))])
    tool_permission_manager.handle_tool_calls(response, Mock())

    # Verify the command was processed
    bash_permission = next(
        perm for perm in tool_permission_manager._tool_permissions.bash.commands if perm.command == long_command
    )
    assert bash_permission.permission == "allow"

    # Verify it wasn't saved to config (since "always" permission is disabled for long commands)
    config = load_config(config_path)
    assert not any(perm.command == long_command for perm in config.tool_permissions.bash.commands)

    # Verify the menu was shown with truncated command
    tool_name = f"bash with command '{long_command}'"
    truncated_command = tool_name[:200] + "..."
    mock_select.assert_called_with(
        message=f"Requesting permission to use tool {truncated_command}. Would you like to allow this tool?",
        choices=[
            Choice(value=(tool_name, "allow", "once"), name="Allow (once)"),
            Choice(value=(tool_name, "allow", "session"), name="Allow (session)"),
            Choice(value=("echo.*", "allow", "always"), name="Allow (always) for all 'echo' commands"),
            Choice(value=(tool_name, "deny", "once"), name="Deny (once)"),
            Choice(value=(tool_name, "deny", "session"), name="Deny (session)"),
        ],
        title="Permissions required",
        escape_return_value=(tool_name, "deny", "once"),
    )


def test_escape_behavior(tool_permission_manager, mock_input):
    """Test that hitting escape returns the default deny-once behavior."""
    mock_input.send_text("\x1b")  # Simulate escape key press
    tool_permission_manager._interactive = True

    response = ModelResponse(parts=[ToolCallPart(tool_name="test_tool", args={"test": "value"})])
    result = tool_permission_manager.handle_tool_calls(response, Mock())

    # Verify the tool call is suppressed and default deny-once behavior is applied
    assert "_suppress_tool_call" in result.parts[0].args
    assert tool_permission_manager._tool_permissions.tools == {
        "test_tool": "ask"
    }  # Assert that the session permission is not set to deny
    assert tool_permission_manager._config_path.endswith("config.yml")


def test_non_interactive_mode(tool_permission_manager, config_path):
    """Test that in non-interactive mode, tools with ask permission are denied."""
    tool_permission_manager._interactive = False
    tool_permission_manager._tool_permissions.tools["test_tool"] = "ask"

    response = ModelResponse(parts=[ToolCallPart(tool_name="test_tool", args={"test": "value"})])
    tool_permission_manager.handle_tool_calls(response, Mock())

    # Verify the tool call is suppressed for the session
    tool_permission_manager._tool_permissions.tools["test_tool"] = "deny"
