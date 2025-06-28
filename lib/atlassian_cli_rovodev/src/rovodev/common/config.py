"""Rovo Dev CLI Configuration."""

import asyncio
import json
import sys
import textwrap
from pathlib import Path
from typing import get_args, get_origin

import yaml
from pydantic.fields import FieldInfo

import nemo
from nemo.utils import MCPServerHTTP, MCPServerStdio
from rovodev import USER_API_TOKEN, USER_EMAIL # Removed PIPELINES_JWT_TOKEN
from rovodev.common.config_model import MCPServersFileConfig, AIAgentConfig # Changed RovoDevConfig
from rovodev.modules.models import AVAILABLE_MODELS
from rovodev.ui.components import Choice, user_menu_panel_sync

# TERMS_AND_CONDITIONS = """...""" # Removed Atlassian-specific T&C

# def accept_terms_and_conditions() -> bool: # Removed Atlassian-specific T&C
#     """Prompt the user to accept the terms and conditions.
#
#     If the user does not accept, the program will exit.
#     """
#     choice = user_menu_panel_sync(
#         message=TERMS_AND_CONDITIONS,
#         choices=[Choice(name="I agree", value=True), Choice(name="Exit", value=False)],
#         title="Terms and conditions",
#     )
#     if not choice:
#         sys.exit(0)
#     return choice


def load_config(config_file: str) -> AIAgentConfig: # Changed RovoDevConfig
    """Load the configuration file."""
    config_path = Path(config_file)
    if not config_path.exists() or not config_path.read_text().strip():
        is_new_config = True
        # accept_terms_and_conditions() # Call removed, T&C removed
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config = AIAgentConfig() # Changed RovoDevConfig
    else:
        is_new_config = False
        config_dict = yaml.safe_load(config_path.read_text()) or {}
        # Handle "flattened" keys in the config file (e.g., mcp.additionalServers)
        for key in list(config_dict):
            if "." in key:
                value = config_dict.pop(key)
                config_section = config_dict
                subkeys = key.split(".")
                for subkey in subkeys[:-1]:
                    if subkey in config_section:
                        raise ValueError(f"Key '{subkey}' is duplicated in the config file.")
                    config_section[subkey] = {}
                    config_section = config_section[subkey]
                config_section[subkeys[-1]] = value
        config = AIAgentConfig.model_validate(config_dict) # Changed RovoDevConfig

    # Expand any tilde paths in the configuration
    config.sessions.persistence_dir = str(Path(config.sessions.persistence_dir).expanduser())

    if is_new_config:
        # If this is a new config, write the default config to the file
        save_config(config, config_file)

    assert config.agent.model_id in AVAILABLE_MODELS, f"Model should be one of {AVAILABLE_MODELS}"
    # Simplified nemo auth setup - user may need to configure this further for their needs
    if USER_API_TOKEN and USER_EMAIL:
        nemo.AUTH_METHOD = "api_token" # Assuming "api_token" is a generic method in nemo
        nemo.USER_EMAIL = USER_EMAIL
        nemo.USER_API_TOKEN = USER_API_TOKEN
        # nemo.CLOUD_ID = "unknown" # CLOUD_ID might be Atlassian specific, commenting out
    # elif PIPELINES_JWT_TOKEN: # Removed Atlassian specific pipeline auth
    #     nemo.AUTH_METHOD = "pipelines"
    #     nemo.PIPELINES_JWT_TOKEN = PIPELINES_JWT_TOKEN
    #     # Set CLOUD_ID for internal users to match AI Gateway default
    #     # nemo.CLOUD_ID = "a436116f-02ce-4520-8fbb-7301462a1674"  # Default AI Gateway cloud ID
    else:
        # nemo.AUTH_METHOD = "slauth" # "slauth" is likely Atlassian specific, commenting out
        # If no specific auth method is set, nemo might have a default or require user configuration
        pass
        # Set CLOUD_ID for internal users to match AI Gateway default
        # nemo.CLOUD_ID = "a436116f-02ce-4520-8fbb-7301462a1674"  # Default AI Gateway cloud ID

    return config


def save_config(config: AIAgentConfig, config_file: str) -> None: # Changed RovoDevConfig
    """Save the configuration file."""
    config_path = Path(config_file)
    config_yaml = yaml.safe_dump(
        config.model_dump(by_alias=True, exclude={"mcp": {"additional_servers"}}),
        sort_keys=False,
    )

    # Add whitespace between top-level keys
    config_yaml = "\n".join([line if line.startswith(" ") else f"\n{line}" for line in config_yaml.split("\n")])

    # Add documentation comments to the YAML
    config_yaml = add_yaml_config_documentation(config_yaml)

    config_path.write_text(config_yaml.strip() + "\n")


def load_mcp_servers_from_json(mcp_config_path: str | Path) -> list[MCPServerHTTP | MCPServerStdio]:
    """Load the MCP servers from the JSON file if it exists."""
    mcp_config_path = Path(mcp_config_path).expanduser()
    if not mcp_config_path.exists() or not mcp_config_path.read_text().strip():
        return []
    with mcp_config_path.open("r") as f:
        mcp_servers_config = json.load(f)
    # Removed Atlassian-specific filtering of MCP servers
    # if mcp_servers_config and USER_API_TOKEN and USER_EMAIL:
    #     server_dict = {
    #         key: value
    #         for key, value in mcp_servers_config["mcpServers"].items()
    #         if not any(
    #             s in str(value)
    #             for s in [
    #                 "mcp.atlassian.com/v1/sse",
    #                 "mcp.atlassian.com/v1/native/sse",
    #                 "atlassian-remote-mcp-staging.atlassian-remote-mcp-server-staging.workers.dev/v1/native/sse",
    #                 "mcp.atlassian.com/v1/mcp",
    #                 "mcp.atlassian.com/v1/native/mcp",
    #                 "atlassian-remote-mcp-staging.atlassian-remote-mcp-server-staging.workers.dev/v1/native/mcp",
    #             ]
    #         )
    #     }
    #     mcp_servers_config["mcpServers"] = server_dict
    if not mcp_servers_config or "mcpServers" not in mcp_servers_config:
        return []
    return list(MCPServersFileConfig.model_validate(mcp_servers_config).mcp_servers.values())


def add_yaml_config_documentation(config_yaml: str) -> str:
    """Add documentation to the YAML configuration file."""
    if not config_yaml.strip():
        return config_yaml

    descriptions = get_field_descriptions(AIAgentConfig) # Changed RovoDevConfig
    lines = config_yaml.split("\n")
    documented_lines = []
    key_stack = []  # Track nested keys

    for line in lines:
        # Skip empty lines and comments
        if not line.strip() or line.strip().startswith("#"):
            documented_lines.append(line)
            continue

        # Calculate indentation and extract key
        stripped = line.lstrip()
        if ":" not in stripped:
            documented_lines.append(line)
            continue

        indent = len(line) - len(stripped)
        level = indent // 2  # YAML uses 2 spaces per level
        key = stripped.split(":")[0].strip()

        # Update key stack based on current level
        key_stack = key_stack[:level] + [key]
        full_key = ".".join(key_stack)

        # Add comment if description exists
        if full_key in descriptions:
            comment_indent = " " * indent
            # Use textwrap to wrap long descriptions
            wrapped_lines = textwrap.wrap(
                descriptions[full_key],
                width=78 - indent,  # Leave room for indent and "# "
                break_long_words=False,
                break_on_hyphens=False,
            )
            for wrapped_line in wrapped_lines:
                documented_lines.append(f"{comment_indent}# {wrapped_line}")

        documented_lines.append(line)

    return "\n".join(documented_lines)


def get_field_descriptions(model_class, prefix=""):
    """Extract field descriptions from a Pydantic model recursively."""
    descriptions = {}

    # Get the model fields
    if hasattr(model_class, "model_fields"):
        for field_name, field_info in model_class.model_fields.items():
            # Convert field name to camelCase for YAML keys
            yaml_key = field_info.alias or field_name
            full_key = f"{prefix}.{yaml_key}" if prefix else yaml_key

            # Get description from Field
            description = None
            if isinstance(field_info, FieldInfo) and field_info.description:
                description = field_info.description

            if description:
                descriptions[full_key] = description

            # Handle nested models
            field_type = field_info.annotation
            if field_type and hasattr(field_type, "model_fields"):
                # It's a nested Pydantic model
                nested_descriptions = get_field_descriptions(field_type, full_key)
                descriptions.update(nested_descriptions)
            elif get_origin(field_type) is list:
                # Handle list types
                args = get_args(field_type)
                if args and hasattr(args[0], "model_fields"):
                    nested_descriptions = get_field_descriptions(args[0], full_key)
                    descriptions.update(nested_descriptions)

    return descriptions
