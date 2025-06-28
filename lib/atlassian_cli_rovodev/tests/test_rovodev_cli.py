"""Tests for rovodev_cli.py."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

import nemo
from rovodev import __version__
from rovodev.commands.run.command import handle_models_command, run
from rovodev.common.config import load_config
from rovodev.common.config_model import AIAgentConfig # Changed RovoDevConfig
from rovodev.rovodev_cli import app


@pytest.fixture
def minimal_config(tmp_path):
    return AIAgentConfig() # Changed RovoDevConfig


def test_load_config(tmp_path):
    """Test the load_config function."""
    config_path = tmp_path / "config.yaml"
    config = {
        "agent": {
            "additionalSystemPrompt": "test prompt",
            "streaming": False,
            "temperature": 0.5,
            "experimental": {
                "enableDeepPlanTool": True,
                "enableDelegationTool": True,
            },
        },
        "console": {
            "outputFormat": "markdown",
        },
        "sessions": {
            "persistenceDir": str(tmp_path / "sessions"),
        },
        "mcp": {
            "mcpConfigPath": str(tmp_path / "mcp.json"),
        },
    }
    config_path.write_text(yaml.dump(config))

    result = load_config(str(config_path))
    assert result.agent.additional_system_prompt == "test prompt"
    assert result.console.output_format == "markdown"
    assert result.agent.streaming is False
    assert result.agent.model_id == "claude-sonnet-4@20250514"
    assert result.agent.temperature == 0.5
    assert result.agent.experimental.enable_deep_plan_tool is True
    assert result.agent.experimental.enable_delegation_tool is True
    assert Path(result.sessions.persistence_dir).as_posix() == (tmp_path / "sessions").as_posix()
    assert Path(result.mcp.mcp_config_path).as_posix() == (tmp_path / "mcp.json").as_posix()


def test_load_config_defaults(tmp_path):
    """Test the load_config function with empty config."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({}))

    result = load_config(str(config_path))
    assert result.agent.additional_system_prompt is None
    assert result.console.output_format == "markdown"
    assert result.agent.streaming is True
    assert result.agent.model_id == "claude-sonnet-4@20250514"
    assert result.agent.temperature == 0.3
    assert result.agent.experimental.enable_deep_plan_tool is False
    assert result.agent.experimental.enable_delegation_tool is False
    assert Path(result.sessions.persistence_dir).as_posix().endswith(".ai_agent/sessions") # Changed path


def test_run(mock_get_model, tmp_path):
    """Test the run function."""
    config_path = tmp_path / "config.yaml"
    config = {
        "agent": {
            "additionalSystemPrompt": "test prompt",
            "streaming": False,
            "temperature": 0.5,
        },
        "console": {
            "outputFormat": "markdown",
        },
    }
    config_path.write_text(yaml.dump(config))

    with patch("rovodev.commands.run.command._run_agent") as mock_run_agent:
        run(config_file=str(config_path), message=["test"])
        mock_run_agent.assert_called_once()


def test_handle_models_command():
    """Test the handle_models_command function."""
    # Test case 1: User selects a model
    with patch("rovodev.modules.models.user_menu_panel_sync") as mock_select:
        mock_select.return_value = "test-model"
        new_model = handle_models_command("old-model")
        assert new_model == "test-model"

    # Test case 2: User presses ESC (cancels selection)
    with patch("rovodev.modules.models.user_menu_panel_sync") as mock_select:
        mock_select.return_value = "current-model"  # This is what happens when ESC is pressed
        new_model = handle_models_command("current-model")
        assert new_model == "current-model"  # Should return the original model unchanged


@patch("rovodev.commands.run.command.get_usage", return_value="usage handled")
def test_run_instructions_message_reconstruction(tmp_path, minimal_config):
    """Test that /instructions command reconstructs the message from sys.argv correctly."""
    nemo.AUTH_METHOD = "api_token"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("console:\n  outputFormat: markdown\nsessions:\n  persistenceDir:\n    'sessions'\n")
    fake_argv = ["rovodev", "run", "/instructions", "autoreview-local", "/tmp/instructions.txt"]

    with patch.object(sys, "argv", fake_argv):
        with patch("rovodev.commands.run.command._run_agent") as mock_run_agent:
            with patch("rovodev.commands.run.command.load_config", return_value=minimal_config):
                with patch(
                    "rovodev.commands.run.command.handle_instructions_command"
                ) as mock_handle_instructions_command:
                    mock_handle_instructions_command.return_value = "handled"
                    run(
                        config_file=str(config_path),
                        message=["/instructions", "autoreview-local", "/tmp/instructions.txt"],
                    )
                    mock_handle_instructions_command.assert_called_once_with("autoreview-local /tmp/instructions.txt")
                    mock_run_agent.assert_called_once()


@patch("rovodev.commands.run.command.get_usage", return_value="usage handled")
def test_run_instructions_message_reconstruction_edge_cases(tmp_path, minimal_config):
    """Test edge cases for /instructions command message reconstruction."""
    nemo.AUTH_METHOD = "api_token"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("console:\n  outputFormat: markdown\nsessions:\n    persistenceDir: 'sessions'\n")

    # Test: empty message list
    with patch.object(sys, "argv", ["rovodev", "run"]):
        with patch("rovodev.commands.run.command._run_agent") as mock_run_agent:
            with patch("rovodev.commands.run.command.load_config", return_value=minimal_config):
                run(config_file=str(config_path), message=[])
                mock_run_agent.assert_called_once()

    # Test: /instructions with no arguments
    with patch.object(sys, "argv", ["rovodev", "run", "/instructions"]):
        with patch("rovodev.commands.run.command._run_agent") as mock_run_agent:
            with patch("rovodev.commands.run.command.load_config", return_value=minimal_config):
                with patch(
                    "rovodev.commands.run.command.handle_instructions_command"
                ) as mock_handle_instructions_command:
                    run(config_file=str(config_path), message=["/instructions"])
                    mock_handle_instructions_command.assert_called_once_with(None)
                    mock_run_agent.assert_called_once()


def test_models_command_integration():
    """Test the integration of handle_models_command with the command loop."""
    # Create a mock for agent_factory
    mock_agent_factory = MagicMock()
    mock_agent_factory.model = "original-model"

    # Test case 1: When a new model is selected
    with patch("rovodev.modules.models.handle_models_command") as mock_handle_models:
        mock_handle_models.return_value = "new-model"

        # This simulates the command.py behavior
        new_model = mock_handle_models(current_model=mock_agent_factory.model)
        if new_model != mock_agent_factory.model:
            mock_agent_factory.model = new_model

        mock_handle_models.assert_called_once_with(current_model="original-model")
        assert mock_agent_factory.model == "new-model"

    # Reset mock
    mock_agent_factory.model = "original-model"

    # Test case 2: When ESC is pressed (no model change)
    with patch("rovodev.modules.models.handle_models_command") as mock_handle_models:
        mock_handle_models.return_value = "original-model"  # Same as current, as if ESC was pressed

        # This simulates the command.py behavior
        new_model = mock_handle_models(current_model=mock_agent_factory.model)
        if new_model != mock_agent_factory.model:
            mock_agent_factory.model = "this-should-not-happen"

        mock_handle_models.assert_called_once_with(current_model="original-model")
        assert mock_agent_factory.model == "original-model"  # Model should not be changed


def test_rovodev_version_flag():
    """Test the --version flag."""
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output
