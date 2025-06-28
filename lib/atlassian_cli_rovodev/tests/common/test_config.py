import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError

from nemo.utils import MCPServerHTTP, MCPServerStdio
from rovodev import DEFAULT_MCP_CONFIG_PATH
from rovodev.common.config import add_yaml_config_documentation, load_config, load_mcp_servers_from_json, save_config
from rovodev.common.config_model import AIAgentConfig # Changed RovoDevConfig


@pytest.fixture
def mock_accept_terms_and_conditions():
    """Mock the accept_terms_and_conditions function."""
    with patch("rovodev.common.config.accept_terms_and_conditions") as mock_accept:
        mock_accept.return_value = True
        yield


def test_load_config_flattened_keys(tmp_path):
    """Test loading a config file with flattened keys."""
    config_file = tmp_path / "config.yml"
    mcp_file = tmp_path / "mcp.json"
    config_file.write_text(f"mcp.mcp_config_path: {mcp_file.as_posix()}\n")


def test_load_config_flattened_keys_duplicated(tmp_path):
    """Test loading a config file with flattened keys raises on duplicate keys."""
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        """\
agent:
    modelId: test-model
agent.modelId: test-model\
"""
    )

    with pytest.raises(ValueError, match="Key 'agent' is duplicated in the config file."):
        load_config(config_file.as_posix())


def test_default_config():
    """Test creating a default configuration."""
    config = AIAgentConfig() # Changed RovoDevConfig

    # Test default values
    assert config.agent.model_id == "claude-sonnet-4@20250514"
    assert config.agent.streaming is True
    assert config.agent.experimental.enable_deep_plan_tool is False
    assert config.mcp.mcp_config_path == DEFAULT_MCP_CONFIG_PATH
    assert config.tool_permissions.default == "ask"


def test_partial_config(tmp_path):
    """Test loading a partial configuration merges with defaults."""
    config_file = tmp_path / "config.yml"
    partial_config = {"agent": {"modelId": "claude-3-5-sonnet-v2@20241022", "streaming": False}}
    config_file.write_text(yaml.safe_dump(partial_config))

    config = load_config(config_file.as_posix())

    # Check custom values
    assert config.agent.model_id == "claude-3-5-sonnet-v2@20241022"
    assert config.agent.streaming is False

    # Check defaults are preserved
    assert config.agent.experimental.enable_deep_plan_tool is False
    assert config.tool_permissions.default == "ask"


def test_save_and_load_config(tmp_path):
    """Test saving and loading a configuration preserves all values."""
    config_file = tmp_path / "config.yml"

    # Create a custom config
    original_config = AIAgentConfig() # Changed RovoDevConfig
    original_config.tool_permissions.default = "deny"

    # Save it
    save_config(original_config, config_file.as_posix())

    # Load it back
    loaded_config = load_config(config_file.as_posix())

    # Verify all values match
    assert loaded_config.tool_permissions.default == "deny"


def test_empty_config_file(tmp_path, mock_accept_terms_and_conditions):
    """Test loading an empty config file returns defaults."""
    config_file = tmp_path / "config.yml"
    config_file.write_text("")

    config = load_config(config_file.as_posix())
    assert isinstance(config, AIAgentConfig) # Changed RovoDevConfig
    assert config.agent.model_id == "claude-sonnet-4@20250514"


def test_mcp_config_path_should_load_mcp_servers_from_file(tmp_path):
    """Test that the mcp_config_path loads MCP servers from a file."""
    config_file = tmp_path / "config.yml"
    mcp_file = tmp_path / "mcp.json"
    config_dict = {
        "mcp": {
            "mcp_config_path": mcp_file.as_posix(),
        }
    }
    config_file.write_text(yaml.safe_dump(config_dict))
    mcp_config = {
        "mcpServers": {
            "custom-command": {
                "command": "custom-command",
                "args": ["arg1", "arg2"],
            },
            "http-server": {
                "url": "http://localhost:8080",
            },
        }
    }

    mcp_file.write_text(json.dumps(mcp_config))
    config = load_config(config_file.as_posix())
    mcp_servers = load_mcp_servers_from_json(mcp_file.as_posix())
    assert Path(config.mcp.mcp_config_path).as_posix() == mcp_file.as_posix()
    assert len(mcp_servers) == 2
    assert isinstance(mcp_servers[0], MCPServerStdio)
    assert mcp_servers[0].command == "custom-command"
    assert mcp_servers[0].args == ["arg1", "arg2"]
    assert isinstance(mcp_servers[1], MCPServerHTTP)
    assert mcp_servers[1].url == "http://localhost:8080"

    # test empty mcp file
    Path(mcp_file).write_text("{}")
    with pytest.raises(ValidationError):
        load_mcp_servers_from_json(mcp_file.as_posix())

    # test mcp file with no mcpServers
    Path(mcp_file).write_text(json.dumps({"mcpServers": {}}))
    config_dict = {
        "mcp": {
            "mcp_config_path": mcp_file.as_posix(),
        }
    }
    config_file.write_text(yaml.safe_dump(config_dict))
    empty_config = load_config(config_file.as_posix())
    no_mcp_servers = load_mcp_servers_from_json(empty_config.mcp.mcp_config_path)
    assert len(no_mcp_servers) == 0


def test_load_mcp_servers_from_json_empty_file(tmp_path):
    """Test loading MCP servers from an empty JSON file."""
    mcp_file = tmp_path / "mcp.json"
    mcp_file.write_text("")

    mcp_servers = load_mcp_servers_from_json(mcp_file)
    assert len(mcp_servers) == 0


def test_add_yaml_config_documentation():
    """Test that documentation is correctly added to YAML config."""
    # Create a simple config
    config = AIAgentConfig() # Changed RovoDevConfig

    # Generate basic YAML
    config_yaml = yaml.safe_dump(
        config.model_dump(by_alias=True, exclude={"mcp": {"additional_servers"}}),
        sort_keys=False,
    )

    # Add documentation
    documented_yaml = add_yaml_config_documentation(config_yaml)

    # Check field comments
    assert "# Additional system prompt to append to the agent's default system prompt" in documented_yaml
    assert "# Enable streaming responses from the AI model" in documented_yaml
    assert "# Temperature setting for AI model responses (0.0-1.0)" in documented_yaml

    # Check that the original YAML structure is preserved
    lines = documented_yaml.split("\n")
    yaml_lines = [line for line in lines if not line.strip().startswith("#") and line.strip()]
    original_lines = [line for line in config_yaml.split("\n") if line.strip()]

    # Remove empty lines for comparison
    yaml_content = "\n".join(yaml_lines)
    original_content = "\n".join(original_lines)

    # Parse both to ensure they're equivalent
    parsed_documented = yaml.safe_load(yaml_content)
    parsed_original = yaml.safe_load(original_content)

    assert parsed_documented == parsed_original


def test_add_yaml_config_documentation_long_comments():
    """Test that long comments are properly wrapped."""
    # Create a minimal YAML with a field that has a long description
    test_yaml = """
agent:
  experimental:
    enableShadowMode: false
"""

    documented_yaml = add_yaml_config_documentation(test_yaml.strip())

    # Check that the long shadow mode description is wrapped
    lines = documented_yaml.split("\n")
    shadow_mode_comment_lines = []
    in_shadow_mode_comment = False

    for line in lines:
        if "Enable/disable the agent to run in shadow mode" in line:
            in_shadow_mode_comment = True

        if in_shadow_mode_comment and line.strip().startswith("#"):
            shadow_mode_comment_lines.append(line)
        elif in_shadow_mode_comment and not line.strip().startswith("#"):
            break

    # Should have multiple comment lines for the long description
    assert len(shadow_mode_comment_lines) > 1

    # Each line should be reasonably short
    for line in shadow_mode_comment_lines:
        # Remove indentation and comment prefix for length check
        comment_text = line.strip()[1:].strip()
        assert len(comment_text) <= 80


def test_add_yaml_config_documentation_preserves_structure():
    """Test that the YAML structure is preserved after adding documentation."""
    original_yaml = """
version: 1
agent:
  streaming: true
  temperature: 0.3
sessions:
  autoRestore: false
"""

    documented_yaml = add_yaml_config_documentation(original_yaml.strip())

    # Extract non-comment lines
    non_comment_lines = [
        line for line in documented_yaml.split("\n") if not line.strip().startswith("#") and line.strip()
    ]

    reconstructed_yaml = "\n".join(non_comment_lines)

    # Both should parse to the same structure
    original_data = yaml.safe_load(original_yaml)
    reconstructed_data = yaml.safe_load(reconstructed_yaml)

    assert original_data == reconstructed_data


def test_add_yaml_config_documentation_empty_input():
    """Test handling of empty or invalid input."""
    # Empty string
    result = add_yaml_config_documentation("")
    assert result == ""

    # Only comments
    comment_only = "# This is a comment\n# Another comment"
    result = add_yaml_config_documentation(comment_only)
    assert result == comment_only

    # Only whitespace
    whitespace_only = "   \n  \n   "
    result = add_yaml_config_documentation(whitespace_only)
    assert result == whitespace_only
