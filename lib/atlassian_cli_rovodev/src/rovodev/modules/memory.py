"""Utilities for persisting and loading 'memory'."""

import re
from pathlib import Path

from loguru import logger
from rich.console import Console

from rovodev.commands.config.command import open_file_in_editor
from rovodev.constants import USER_MEMORY_FILE_NAMES, WORKSPACE_MEMORY_FILE_NAMES

console = Console()

USER_MEMORY_PROMPT_TEMPLATE = """\
Here are information or guidelines that you should consider when resolving requests:
{memory}\
"""

WORKSPACE_MEMORY_PROMPT_TEMPLATE = """\
Here are information or guidelines specific to this workspace that you should consider when resolving requests:
{memory}\
"""

MEMORY_INIT_PROMPT = """\
Your goal is to explore the current workspace and create or update the top-level .agent.md file with information that \
will be useful for developers working on this project.

You should aim to include:
- Key information about the project (purpose, language, frameworks, etc.)
- Important files and directories
- Best practices and conventions you observe

Don't call grep tools with overly broad patterns at it will be very slow and provide noisy output.

Format the file primarily as lists of instructions grouped by simple markdown headers.
In addition, if any of the following files are present in the root directory (not sub-directories), you should migrate \
their content to the .agent.md file:
- CLAUDE.md, CLAUDE.local.md
- codex.md, .codex/*.md
- .cursor/rules/*.mdc, .cursorrules.md, .cursorrules
- rules.md, .rules.md\
"""


def load_memories_from_file_system(path: str | Path | None) -> tuple[str | None, list[Path]]:
    """Load memory from markdown files in the file system.

    This function will search the current and ancestor directories of the current workspace, and for memory files in the
    user's home directory.

    Args:
        path: The path to the file or directory to load memory from. If None, the current working directory will be
            used.

    Returns:
        The loaded memory from all matching files loaded as a string.
    """
    path = Path.cwd() if path is None else Path(path).expanduser().absolute().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Path {path} does not exist")
    if path.is_file():
        path = path.parent

    # Check the workspace directories
    memory_paths = []
    workspace_memories = []
    for parent_level, workspace_dir in enumerate([path] + list(path.parents)):
        for pattern in WORKSPACE_MEMORY_FILE_NAMES:
            matches = list(workspace_dir.glob(pattern))
            if matches:
                if path == workspace_dir:
                    prefix = "Instructions for the current directory (these take precedence if relevant):\n\n"
                else:
                    prefix = f"Instructions for ancestor directory {'../' * parent_level}:\n\n"
                memory_paths.extend(["../" * parent_level + m.name for m in matches])
                workspace_memories.extend([prefix + sanitize_file_content(match.read_text()) for match in matches])

    # Check the user's home directory
    home_dir = Path.home()
    user_memories = []
    for pattern in USER_MEMORY_FILE_NAMES:
        matches = list(home_dir.glob(pattern))
        if matches:
            memory_paths.extend(matches)
            user_memories.extend([sanitize_file_content(match.read_text()) for match in matches])

    memory = []
    user_memories = [mem for mem in user_memories if mem.strip()]
    if user_memories:
        memory.append(
            USER_MEMORY_PROMPT_TEMPLATE.format(
                memory="\n".join([f"<user_instruction>\n{mem}\n</user_instruction>" for mem in user_memories])
            )
        )

    workspace_memories = [mem for mem in workspace_memories if mem.strip()]
    if workspace_memories:
        # Reverse the order of workspace memories to put those in the current directory last
        memory.append(
            WORKSPACE_MEMORY_PROMPT_TEMPLATE.format(
                memory="\n".join(
                    [f"<workspace_instruction>\n{mem}\n</workspace_instruction>" for mem in workspace_memories[::-1]]
                )
            )
        )

    return "\n".join(memory) if memory else None, memory_paths


def handle_memory_note(note: str) -> str:
    """Handle a memory note and return the updated additional_system_prompt."""
    # Add note to current directory memory file
    note = note.lstrip("#").strip()
    memory_path = Path(".agent.md")
    memory_content = sanitize_file_content(memory_path.read_text()) if memory_path.exists() else ""
    existing_notes_section = re.search(r"(?:^|\n)# Workspace notes\s*\n(?:- [^\n]+(?:\n|$))*", memory_content)
    if note.startswith("!"):
        note = note[1:].strip()
        if not memory_content.find(note):
            logger.bind(role="warning").warning(f"Note not found in memory file")
            return get_memory_instructions()
        memory_content = "\n".join([line for line in memory_content.splitlines() if note not in line])
        verb = "removed from"
    else:
        if not existing_notes_section:
            memory_content = memory_content + f"\n\n# Workspace notes\n\n- {note}\n"
        else:
            # Append the note to the existing notes
            existing_notes = existing_notes_section.group()
            memory_content = memory_content.replace(existing_notes, existing_notes.rstrip() + f"\n- {note}\n")
        verb = "added to"
    memory_path.write_text(memory_content.strip() + "\n")

    logger.bind(role="info").info(f"Memory note {verb} .agent.md file.")

    # Load memories from file system
    return get_memory_instructions()


def handle_memory_command(command: str | None) -> str | None:
    """Handle the /memory command."""
    if command is None or command == "user":
        if command is None:
            # For /memory (no args), open the workspace .agent.md
            memory_path = Path.cwd() / ".agent.md"
        else:
            # For /memory user, open the user-level .ai_agent/.agent.md
            memory_path = Path.home() / ".ai_agent" / ".agent.md" # Changed path
        return open_file_in_editor(str(memory_path))
    # Otherwise, init was called
    return MEMORY_INIT_PROMPT


def sanitize_file_content(content: str) -> str:
    """
    Remove unicode characters in the ranges:
    - U+E0001 to U+E007F (language tag to cancel tag)
    - U+E0100 to U+E01EF (variation selector 17 to variation selector 256)
    - U+2061 to U+2065 (invisible times to invisible operators undefined)
        - This range contains invisible plus and invisible times which are used by default by
          ASCII smuggler for "sneaky bits". Need to do more research into "sneaky bits" to ensure we cover all cases.
    tag characters that can be used to inject invisible instructions.
    """
    import re

    # Match any character in the range U+E0001 to U+E007F using 8-digit Unicode escapes
    return re.sub(r"[\U000E0001-\U000E007F\U000E0100-\U000E01EF\u2061-\u2065]", "", content)


def get_memory_instructions(log_paths: bool = False) -> str:
    """Add memories to the instructions."""
    instructions = ""
    memory, memory_paths = load_memories_from_file_system(Path.cwd())
    if memory:
        if log_paths:
            console.print(
                f"[bright_black]Loaded memory from {', '.join([str(p) for p in memory_paths])}[/bright_black]"
            )
        instructions = memory
    instructions += """

Location-specific best practices, tips, and patterns may be found throughout the current workspace in .agent.md \
files. Before making any changes in a subdirectory, please read the contents of its .agent.md if present.\
"""
    return instructions.strip()
