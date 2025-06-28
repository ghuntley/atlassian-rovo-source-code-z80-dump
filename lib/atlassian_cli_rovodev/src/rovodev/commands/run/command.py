"""The run command handler for Rovo Dev CLI."""

import asyncio
import shutil
import sys
import uuid
from pathlib import Path
from typing import Annotated, Any, cast
from urllib.parse import quote

import logfire
import rich
import typer
from loguru import logger
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model, ModelRequestParameters, ModelSettings
from pydantic_ai.models.fallback import FallbackModel
from rich.console import Console

import nemo
from nemo.agent import get_model
from nemo.cli import _run_agent
from nemo.constants import DEFAULT_EXIT_COMMANDS
from nemo.context import DefaultSessionContext
from nemo.models import ModelMessageHistory
from nemo.pruners import ToolResultPruner
from rovodev import DEFAULT_CONFIG_PATH, DEFAULT_PROMPT_HISTORY_PATH, IS_INTERNAL_USER, VERSION_INFO, __version__
from rovodev.commands.run.command_registry import registry
from rovodev.common import dynamic_configuration
from rovodev.common.agent import create_agent_factory
from rovodev.common.banner import BANNER
from rovodev.common.config import load_config
from rovodev.common.config_model import AIAgentConfig # Changed RovoDevConfig
from rovodev.common.exceptions import RateLimitExceededError, RequestTooLargeError, AIAgentError # Changed RovoDevError
from rovodev.modules.adaptive_fallback_model import AdaptiveFallbackModel
# from rovodev.modules.analytics import initialize_analytics # Removed
# from rovodev.modules.analytics.instrumentation.session import track_session_created, track_session_restored # Removed
from rovodev.modules.instructions import handle_instructions_command
from rovodev.modules.logging import setup_logging
from rovodev.modules.mcp_utils import run_mcp_servers_with_error_handling
from rovodev.modules.memory import handle_memory_command, handle_memory_note
from rovodev.modules.models import handle_models_command
from rovodev.modules.sessions import Session, get_most_recent_session, get_sessions, handle_sessions_command
from rovodev.modules.usage import get_usage, handle_usage_command
from rovodev.ui.prompt_session import FilteredFileHistory, PromptSession

app = typer.Typer(pretty_exceptions_show_locals=False, pretty_exceptions_enable=False)
console = Console()


BANNER_TEMPLATE = f"""\
{BANNER}

Here are some quick tips:

• Ask AI Agent anything in your own words - from "explain this repo" to "add unit tests".
• Type "/" at any time to see available commands.
• Use CTRL+C to interrupt the agent during generation.
• Use /exit to quit.

Working in [blue bold]{{root_path}}[/blue bold]
"""

# INTERNAL_PROMPT_COLLECTION = """...""" # Removed as it's Atlassian-specific internal use message

HOME_DIR_WARNING = """\
[red]WARNING: You are running AI Agent in your home directory.
This directory may be too large to process efficiently.
Consider running in a more targeted directory for better results.[/red]\
""" # Changed Rovo Dev

FEEDBACK_TEMPLATE = """
[bold]Leave feedback[/bold]
[bright_black]\
Thank you for taking the time to leave feedback on AI Agent CLI. We will use your feedback to debug issues or improve \
the current functionality.[/bright_black]

[nc bold]Report a bug[/nc bold]
[bright_black]
To report a bug, please open an issue on the project's issue tracker.
Include your log file to help diagnose the problem:
{log_file_path}
Version Info:
{version_info}
[/bright_black]


[nc bold]Leave feedback or ask questions[/nc bold]
[bright_black]
Please use the project's discussion forum or issue tracker for feedback and questions.
[/bright_black]
""" # Genericized feedback, removed Atlassian links


@registry.register(
    "/models",
    None,
    "View and select from available models.",
    """\
[default bold]Model Selection[/default bold]
This command allows you to view and switch between different AI models available for your AI Agent session.

The selected model will be used for all subsequent interactions until you restart the CLI or run the `/models` command \
again.\
""", # Changed Rovo Dev
    disable_for_external=True,
)
def model_command(*args, **kwargs) -> None:
    agent_factory = kwargs["agent_factory"]
    agent = kwargs["agent"]
    new_model = handle_models_command(current_model=agent_factory.model)
    logger.bind(role="info").info(f"Selected model: {new_model}")
    agent_factory.model = new_model
    agent.model = get_model(agent_factory.model)
    if isinstance(agent.model, FallbackModel):
        agent.model = AdaptiveFallbackModel(agent.model.models[0], *agent.model.models[1:])
    return None


@registry.register(
    "/sessions",
    None,
    "View and manage for agent sessions.",
    """\
[default bold]Sessions[/default bold]
Sessions allow you to maintain conversation history and context across multiple interactions with AI Agent.

Key features:
• Session Management: Create, switch between, and manage multiple conversation sessions
• Context Preservation: Each session maintains its own message history and context
• Workspace Isolation: Sessions are tied to specific workspaces for better organization
• Session Forking: Create new sessions based on existing ones

Sessions are automatically saved and can be restored when you restart AI Agent using the `--restore` flag.\
""", # Changed Rovo Dev
)
def session_command(*args, **kwargs) -> dict[str, Any] | None:
    persistence_dir = kwargs["persistence_dir"]
    session_id = kwargs["session_id"]
    selected_session, is_new_session = handle_sessions_command(
        persistence_dir=persistence_dir, current_session_id=session_id, root_path=kwargs["agent_factory"].root_path
    )
    if is_new_session and not selected_session:
        selected_session = Session()
        console.print(f"Created and switched to new session")
        return {"continue": True, "message_history": [], "session_id": selected_session.session_id}
    elif selected_session and selected_session.session_id != session_id:
        console.print(
            f"[bright_black]Switched to session '{selected_session.title}' ({selected_session.session_id}) with "
            f"{selected_session.num_messages} messages[/bright_black]"
        )
        return {
            "continue": True,
            "message_history": ModelMessageHistory.model_validate(selected_session.message_history).root,
            "session_id": selected_session.session_id,
        }
    return


@registry.register(
    "/clear",
    None,
    "Clear the current session's message history.",
    """\
[default bold]Clear Session[/default bold]
This command clears the current session's message history, resetting the conversation to a fresh state.

Note that this operation cannot be undone. If you want to preserve the current session's history, try creating a new \
session using the `/sessions` command, or reducing the size of the current session using the `/prune` command.\
""",
)
def clear_command(*args, **kwargs) -> dict[str, Any]:
    persistence_dir = kwargs["persistence_dir"]
    session_id = kwargs["session_id"]
    session_path = Path(persistence_dir) / session_id
    if session_path.exists() and session_path.is_dir():
        try:
            logger.info(f"Removing session: {session_path}")
            shutil.rmtree(session_path)
        except:
            logger.warning(f"Failed to remove session directory: {session_path}")

    logger.bind(role="info").info("Session history cleared")
    # Add instrumentation for new session creation - REMOVED
    # track_session_created(session_id) # Removed
    return {"continue": True, "message_history": None, "session_id": session_id}


@registry.register(
    "/prune",
    None,
    "Reduce the token size of the current session's message history while retaining context.",
    """\
[default bold]Prune Session[/default bold]
This command reduces the token size of the current session's message history while retaining important context.

Sessions are pruned by removing tool results from the message history. As a result, the agent may need to re-run some \
tool calls if future requests require the same information.\
""",
)
def prune_command(*args, **kwargs) -> dict[str, Any] | None:
    persistence_dir = kwargs["persistence_dir"]
    session_id = kwargs["session_id"]
    session_path = Path(persistence_dir) / session_id
    if session_path.exists() and session_path.is_dir() and (session_path / "session_context.json").exists():
        try:
            session_context = DefaultSessionContext.model_validate_json(
                (session_path / "session_context.json").read_text()
            )
        except Exception as e:
            logger.bind(role="error").error(f"Failed to load session context from {session_path}")
            return
    else:
        logger.bind(role="warning").warning("No session history to prune.")
        return
    session_context.message_history = ToolResultPruner()(session_context.message_history)

    try:
        # Update the Usage object in the final message to reflect the new token count
        # We do this by making a single-token request to the model with the pruned message history
        model = kwargs["agent"].model
        # Fallback model wrappers will retry multiple times if rate limits are hit - we don't want that here, so we just
        # try once use a generic message if it fails
        while isinstance(model, (AdaptiveFallbackModel, FallbackModel)):
            model = model.models[0]
        response = asyncio.run(
            model.request(
                messages=session_context.message_history[:-1],
                model_settings=ModelSettings(max_tokens=1),
                model_request_parameters=ModelRequestParameters(
                    function_tools=[], allow_text_output=True, output_tools=[]
                ),
            )
        )
        final_usage = session_context.message_history[-1].usage  # type: ignore
        original_context_tokens = final_usage.total_tokens
        final_usage.request_tokens = response.usage.request_tokens
        final_usage.total_tokens = final_usage.request_tokens + final_usage.response_tokens

        logger.bind(role="info").info(
            f"Context tokens reduced from {original_context_tokens} to {final_usage.total_tokens} tokens."
        )
    except:
        logger.warning("Failed to update context tokens in the final message.")
        logger.bind(role="info").info("Conversation pruned - context tokens will be updated in the next request.")

    (session_path / "session_context.json").write_text(session_context.model_dump_json(indent=4))
    return {"continue": True, "message_history": session_context.message_history, "session_id": session_id}


@registry.register(
    "/instructions",
    None,
    "Run saved instructions.",
    """\
[default bold]Instructions[/default bold]
This command allows you to run pre-defined instruction templates that help with common tasks.

Built-in instructions include:
• Code review and analysis
• Documentation generation and improvement
• Unit test creation and coverage improvement
• Confluence page summarization
• Jira issue analysis

You can also create custom instructions by:

1. Creating an instructions file at .ai_agent/instructions.yml:
    ```yaml
    instructions:
      - name: my-custom-instruction
        description: My custom instruction description
        content_file: my_custom_instruction.md
    ```
2. Writing the instruction content in a Markdown file in the .ai_agent folder (e.g., `.ai_agent/my_custom_instruction.md`)

Usage:
• `/instructions` - View and select from available instructions
• `/instructions <name>` - Run a specific instruction by name
• `/instructions <name> <extra>` - Run instruction with additional instructions or context\
""",
)
def instruction_command(*args, **kwargs) -> dict:
    instruction_args = " ".join(kwargs["_message_list"])
    message = handle_instructions_command(instruction_args or None)
    return {"message": message, "continue": True if message else False}


@registry.register(
    "/memory",
    None,
    "Memory file management.",
    """\
[default bold]Memory[/default bold]
Memory files help AI Agent remember important information about your project and preferences.

Types of memory:
• Project Memory: Stored in your current directory (.agent.md and .agent.local.md)
• User Memory: Global memory stored in your home directory (~/.ai_agent/agent.md)

Memory files are written in Markdown and can contain:
• Project-specific context and conventions
• Coding standards and preferences
• Important architectural decisions
• Frequently used patterns or snippets

Use `#` to add quick notes to project memory, and `#!` to remove them.\
""",
)
def memory_command(*args, **kwargs) -> dict[str, str | None]:
    memory = " ".join(kwargs["_message_list"])
    message = handle_memory_command(memory or None)
    return {"message": message}


@registry.register("/memory", "user", "Create/open your user-level memory file.")
def memory_user_command(*args, **kwargs) -> dict[str, str | None]:
    """Handle the /memory user command."""
    message = handle_memory_command("user")
    return {"message": message}


@registry.register(
    "/memory",
    "init",
    "Generate or update the current directory's memory file using AI.",
    """\
[default bold]Memory Initialization[/default bold]
This command uses AI Agent to automatically generate or update the current directory's memory file based on your \
project.

AI Agent will analyze your codebase and create a memory file containing:
• Coding patterns and conventions used in the project
• Key dependencies and technologies
• Important files and their purposes
• Development workflow and best practices
• Information from other common memory files present in the workspace (e.g., CLAUDE.md, codex.md, rules.md)\
""",
)
def memory_init_command(*args, **kwargs) -> dict[str, str | None]:
    """Handle the /memory init command."""
    message = handle_memory_command("init")
    return {"message": message}


@registry.register("#", None, "Add a note to AI Agent's local memory file.") # Changed Rovo Dev
def memory_note_command(*args, **kwargs) -> None:
    agent_factory = kwargs["agent_factory"]
    agent = kwargs["agent"]
    memory = " ".join(kwargs["_message_list"])
    agent_factory.instructions = handle_memory_note(memory)
    agent._instructions = agent_factory.instructions
    return None


@registry.register("#!", None, "Remove a note from AI Agent's local memory file.") # Changed Rovo Dev
def memory_note_removal_command(*args, **kwargs) -> None:
    agent_factory = kwargs["agent_factory"]
    agent = kwargs["agent"]
    memory = " ".join(kwargs["_message_list"])
    agent_factory.instructions = handle_memory_note("!" + memory)
    agent._instructions = agent_factory.instructions
    return None


@registry.register("/feedback", None, "Provide feedback or report a bug on AI Agent CLI.") # Changed Rovo Dev
def feedback_command(*args, **kwargs) -> None:
    config: AIAgentConfig = kwargs["config"] # Changed RovoDevConfig
    log_file_path = config.logging.path
    rich.print(
        FEEDBACK_TEMPLATE.format(
            version_info=VERSION_INFO,
            encoded_version_info=quote(VERSION_INFO),
            log_file_path=log_file_path,
        )
    )


@registry.register("exit", None, None)  # Set help to None so help() will not show it as a separate command
@registry.register("quit", None, None)
@registry.register("q", None, None)
@registry.register("/quit", None, None)
@registry.register("/q", None, None)
@registry.register("/exit", None, "Exit the application. Can also be `/quit`, `/q`, `exit`, `quit`, or `q`.")
def exit_command(*args, **kwargs) -> None:
    raise typer.Exit(code=0)


@app.command()
def run(
    config_file: Annotated[str, typer.Option(help="Config file.")] = DEFAULT_CONFIG_PATH,
    message: Annotated[list[str] | None, typer.Argument(help="Initial instruction for the agent.")] = None,  # type: ignore[assignment]
    shadow: Annotated[
        bool | None,
        typer.Option(
            ...,
            "--shadow",
            help=(
                "Enable/disable the agent to run in shadow mode. This will run the agent on a temporary clone of your "
                "workspace, prompting you before any changes are applied to your working directory. If set, this flag "
                "will override the config file setting agent.experimental.enableShadowMode"
            ),
        ),
    ] = None,
    verbose: Annotated[
        bool | None,
        typer.Option(
            ...,
            "--verbose",
            help=(
                "Enable/disable verbose tool output. If set, this will override the config file setting "
                "console.showToolResults"
            ),
        ),
    ] = None,
    restore: Annotated[
        bool | None,
        typer.Option(
            ...,
            "--restore",
            help=(
                "Continue the last session if available. By default, a new session is started. If set, this flag will "
                "override the config file setting sessions.autoRestore"
            ),
        ),
    ] = None,
):
    """Run the AI coding agent.""" # Changed Rovo Dev
    console.print(BANNER_TEMPLATE.format(root_path=Path.cwd()), highlight=False)
    config = load_config(config_file)

    # Removed INTERNAL_PROMPT_COLLECTION display as it was Atlassian-specific
    # if config.logging.enable_prompt_collection and IS_INTERNAL_USER:
    #     console.print(INTERNAL_PROMPT_COLLECTION, highlight=False)

    # Initialize the logger before any logging occurs to prevent cluttering the UI
    setup_logging(
        log_file=config.logging.path,
        output_format=config.console.output_format,
        show_tool_results=config.console.show_tool_results,
    )

    # Set CLI provided options
    if shadow is not None:
        config.agent.experimental.enable_shadow_mode = shadow
    if verbose is not None:
        config.console.show_tool_results = verbose
    if restore is not None:
        config.sessions.auto_restore = restore

    if nemo.AUTH_METHOD == "api_token" and "/usage" not in registry._commands:

        @registry.register("/usage", None, "Show your daily LLM token usage.")
        def usage_command(*args, **kwargs):
            handle_usage_command()
            return None

    logger.info("Starting AI Agent CLI") # Changed Rovo Dev
    logger.info(f"Working directory: {Path.cwd()}")
    logger.info(f"Config file: {config_file}")
    logger.debug(config.model_dump_json(indent=2))

    # Initialize analytics - REMOVED
    # initialize_analytics(__version__, config)

    # Join message parts into a single string if provided
    if message and len(message) > 0:
        message = " ".join(message)  # type: ignore[assignment]
    message: str | None = cast(str, message) if message else None
    # If the command is /instructions, reconstruct the full command from sys.argv
    if message and message.startswith("/instructions"):
        try:
            idx = sys.argv.index("/instructions")
            # Reconstruct everything after /instructions as the instruction input
            instruction_input = " ".join(sys.argv[idx + 1 :])
            message = f"/instructions {instruction_input}" if instruction_input else "/instructions"
        except ValueError:
            pass

    restore_session_override = False  # Flag used to force restoring a session we resuming after an agent interrupt
    while True:
        try:
            if nemo.AUTH_METHOD == "api_token":
                # Call the check endpoint to ensure the user's organization is set up correctly
                get_usage()

            # Get most recent session or start a new one based on config
            current_workspace = Path.cwd()
            sessions = get_sessions(Path(config.sessions.persistence_dir), workspace_path=current_workspace)
            if (config.sessions.auto_restore or restore_session_override) and sessions:
                most_recent = get_most_recent_session(sessions)
                session_id, session_info = most_recent  # type: ignore
                message_history = ModelMessageHistory.model_validate(session_info.message_history).root
                if not restore_session_override:
                    console.print(
                        f"[bright_black]Restoring most recent session '{session_info.title}' with {len(message_history)} "
                        "messages[/bright_black]"
                    )
                    # Add instrumentation for session restoration
                    logger.info(f"Restoring session with ID: {session_id}, title: {session_info.title}")
                # track_session_restored(session_id, title=session_info.title, num_messages=len(message_history)) # Removed
            else:
                session_id = str(uuid.uuid4())
                message_history = None
                logger.info(f"Starting new session")
                # Add instrumentation for new session creation
                # track_session_created(session_id) # Removed

            # Future iterations in the while loop are triggered by exceptions being raised, so we need to set this
            # to True to ensure the correct session is restored
            restore_session_override = True

            result = asyncio.run(
                asyncio.gather(  # type: ignore
                    arun(config_file, config, message, session_id, message_history),
                    return_exceptions=True,
                )
            )
            # Check if the result contains an exception
            if result and len(result) > 0 and isinstance(result[0], Exception):
                raise result[0]
            return
        except KeyboardInterrupt:
            logger.bind(role="warning").warning("Agent interrupted")
        except typer.Exit:
            return
        except AIAgentError as e: # Changed RovoDevError
            logger.bind(role=e.role, title=e.title).error(e.message)
            if IS_INTERNAL_USER: # This will be False by default now
                logger.exception(e)
            if isinstance(e, (RateLimitExceededError, RequestTooLargeError)):
                continue
            return
        except Exception as e:
            # Track crash in analytics
            logfire.error(
                "Application crash",
                error_type=type(e).__name__,
                error_message=str(e),
                command_context=message if "message" in locals() else None,
                _tags=["crash", "error"],
            )

            logger.bind(role="error").error("An unexpected error occurred, exiting.")
            if IS_INTERNAL_USER:
                logger.add(sys.stderr)
                logger.exception(e)
            return


async def arun(
    config_file: str,
    config: AIAgentConfig, # Changed RovoDevConfig
    message: str | None,
    session_id: str,
    message_history: list[ModelMessage] | None,
) -> None:
    """Async function to run the rovodev command.""" # Docstring already generic enough
    prompt_session: PromptSession | None
    prompt_history: FilteredFileHistory | None
    if sys.stdin.isatty() and not message:
        prompt_history_path = DEFAULT_PROMPT_HISTORY_PATH
        prompt_history = FilteredFileHistory(prompt_history_path)
        prompt_session = PromptSession(
            enable_history_search=True,
            history=prompt_history,
            auto_suggest=AutoSuggestFromHistory(),
        )
    else:
        prompt_session = None
        prompt_history = None

    if message and message.startswith("/instructions"):
        message = handle_instructions_command(message[13:].strip() or None)

    agent_factory = create_agent_factory(config=config, config_file=config_file, interactive=True)

    message_future = None
    if not message and prompt_session:
        # If no message is provided and we are in interactive mode, prompt the user in the background so we can create
        # the agent and start MCP servers in the background without blocking
        message_future = asyncio.create_task(prompt_session.prompt_async("> "))

        # Add a done callback to handle SystemExit exceptions immediately
        def handle_task_exception(task):
            try:
                # This will raise the exception if one occurred
                task.result()
            except SystemExit:
                # SystemExit from Ctrl-C is expected, just ignore it
                pass
            except Exception:
                # Other exceptions should still be logged
                pass

        message_future.add_done_callback(handle_task_exception)

    persistence_dir = Path(config.sessions.persistence_dir)

    # Start any MCP servers. Currently, the user has no in-app way to modify the configured MCP servers, so we only
    # need to do this once at the start. In future, if we allow the user to modify the MCP servers on the fly without
    # restarting the app, we can just wrap everything below in an outer while loop break out of the inner loop when we
    # need to update and restart the servers.
    agent = agent_factory.create()

    # If the user has a dynamic configuration, we use the provided model ids
    if dynamic_configuration is not None:
        model_ids = dynamic_configuration.config().model_id
        models = []
        if model_ids:
            for model_id in model_ids:
                models.append(get_model(model_id, use_known_fallbacks=False))
            fallback_model = AdaptiveFallbackModel(models[0], *models[1:])
            agent.model = fallback_model

    if not isinstance(agent.model, AdaptiveFallbackModel):
        # If the model is not already an AdaptiveFallbackModel, we wrap it in one
        if isinstance(agent.model, FallbackModel):
            agent.model = AdaptiveFallbackModel(agent.model.models[0], *agent.model.models[1:])
        elif isinstance(agent.model, Model):
            agent.model = AdaptiveFallbackModel(agent.model)

    logger.info("Starting MCP servers")
    async with run_mcp_servers_with_error_handling(agent):
        logger.info("MCP servers started successfully")
        if message_future is not None:
            # Block until the user provides a message
            try:
                if message_future.done():
                    # Task already completed, get result (may raise SystemExit)
                    message = message_future.result()
                else:
                    # Task still running, await it
                    message = await message_future
            except SystemExit:
                # User pressed Ctrl-C, treat as exit command
                message = "exit"
            message_future = None

        current_session_context = None
        while True:
            session_context = await _run_agent(
                agent_factory=agent_factory,
                problem_statement=message,
                prompt_session=prompt_session,
                streaming=config.agent.streaming,
                message_history=message_history,
                exit_commands=DEFAULT_EXIT_COMMANDS + registry.commands,
                log_dir=(persistence_dir / session_id).as_posix(),
                agent_instance=agent,
                session_context=current_session_context,  # Pass previous context for token display
            )
            message = None
            if session_context:
                message_history = session_context.message_history
                current_session_context = session_context  # Store for next iteration
            if prompt_history is None:
                break
            user_prompt = prompt_history.last_string
            try:
                result_dict = registry.dispatch(
                    user_prompt,
                    agent_factory=agent_factory,
                    prompt_history=prompt_history,
                    persistence_dir=persistence_dir,
                    session_id=session_id,
                    agent=agent,
                    config=config,
                )
                if result_dict is None:
                    continue

                if "message" in result_dict:
                    message = result_dict["message"]
                if "message_history" in result_dict:
                    message_history = result_dict["message_history"]
                if "session_id" in result_dict:
                    session_id = result_dict["session_id"]

                if "continue" in result_dict and result_dict["continue"]:
                    continue

            except (KeyboardInterrupt, SystemExit):
                continue
