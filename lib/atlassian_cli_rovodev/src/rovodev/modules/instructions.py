"""Instruction handling functionality for Rovo Dev CLI."""

from pathlib import Path

import yaml
from loguru import logger
from pydantic import BaseModel
from rich.console import Console

from rovodev.ui.components import Choice, user_menu_panel_sync

console = Console()

INSTRUCTIONS_MESSAGE = """[bright_black]Speed up your development flow with pre-created prompts that can be run anytime.
You can also view, edit, and create new instructions in the [bold].ai_agent/instructions.yml[/bold] file.[/bright_black]

Select an instruction to run:"""


class Instruction(BaseModel):
    """Instruction model."""

    name: str
    description: str | None = None
    content_file: str
    content: str | None = None


class InstructionConfig(BaseModel):
    """Instruction configuration model."""

    instructions: list[Instruction] = []


def get_config_locations(sub_path: str) -> list[Path]:
    """Get configuration file locations in order of precedence."""
    locations = []

    # Add repository root .rovodev if found
    current = Path.cwd()
    while current.parent != current:  # Stop at root directory
        if (current / ".git").exists():
            locations.append(current / ".ai_agent" / sub_path) # Changed path
            break
        current = current.parent

    # Add current directory .ai_agent
    locations.append(Path.cwd() / ".ai_agent" / sub_path) # Changed path

    # Add current file directory (e.g., bundled instructions)
    locations.append(Path(__file__).parent / "instructions" / sub_path)

    # Add user home config
    locations.append(Path.home() / ".ai_agent" / sub_path) # Changed path

    return locations


def load_instruction_content(config_file_path: Path, instruction: Instruction) -> str | None:
    """Load the content of an instruction from its file."""
    candidate_paths = [
        # Relative to the config YAML file location
        Path(config_file_path).parent / instruction.content_file,
        # Relative to the repo root
        Path(config_file_path).parent.parent / instruction.content_file,
        # Absolute
        Path(instruction.content_file),
    ]
    for path in candidate_paths:
        if path.exists():
            return path.read_text()
    return None


def load_instruction_file(file_path: Path | str) -> InstructionConfig | None:
    """Load a set of instructions from a YAML file."""
    config_data = yaml.safe_load(Path(file_path).read_text())
    if config_data:
        instruction_config = InstructionConfig.model_validate(config_data)
        for instruction in instruction_config.instructions:
            content = load_instruction_content(Path(file_path), instruction)
            if not content:
                logger.bind(role="warning").warning(f"Instruction content file not found: {instruction.content_file}")
            instruction.content = content
        instruction_config.instructions = [inst for inst in instruction_config.instructions if inst.content is not None]
        return instruction_config


def load_instruction_config() -> InstructionConfig | None:
    """Load and merge instruction configurations from all possible locations."""
    config_locations = get_config_locations("instructions.yml")

    merged_config = InstructionConfig()
    for config_file in config_locations:
        try:
            if not config_file.exists():
                continue

            config = load_instruction_file(config_file)
            if config:
                existing_instruction_names = {instruction.name for instruction in merged_config.instructions}
                for instruction in config.instructions:
                    if instruction.name not in existing_instruction_names:
                        merged_config.instructions.append(instruction)
                        existing_instruction_names.add(instruction.name)
        except FileNotFoundError:
            continue
        except Exception as e:
            logger.bind(role="error").error(f"Error reading {config_file}: {str(e)}")
            return None

    if not merged_config.instructions:
        return None

    return merged_config


def handle_instructions_command(instruction_input: str | None = None) -> str | None:
    """Handle the /instructions command."""
    instruction_config = load_instruction_config()
    if not instruction_config:
        logger.bind(role="warning").warning("No instructions found in configuration files")
        return None

    # Create choices for instructions
    instruction_choices = []
    for instruction in instruction_config.instructions:
        instruction_choices.append(Choice(value=instruction, name=instruction.description or instruction.name))

    if not instruction_choices:
        logger.bind(role="warning").warning("No instructions available")
        return None

    if instruction_input:
        instruction_name, *additional_inputs = instruction_input.split(maxsplit=1)
        additional_input = additional_inputs[0] if additional_inputs else None

        selected_instruction = next(
            (inst for inst in instruction_config.instructions if inst.name == instruction_name), None
        )
        if not selected_instruction:
            logger.bind(role="error").error(f"Instruction '{instruction_name}' not found")
            return None
    else:
        # Select instruction interactively
        selected_instruction = user_menu_panel_sync(
            title="Instructions",
            message=INSTRUCTIONS_MESSAGE,
            choices=instruction_choices,
            border_color="none",
            title_color="none",
            action_name="Run instruction",
        )
        additional_input = None

        if selected_instruction is None:
            return None

    # Use the template content directly from the instruction
    result = selected_instruction.content

    if additional_input:
        result = f"{result}\n\nAdditional instructions: {additional_input}"

    return result
