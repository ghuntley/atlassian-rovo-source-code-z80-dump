"""The serve command handler for AI Agent CLI.""" # Changed Rovo Dev

from typing import Annotated

import rich
import typer

from rovodev import DEFAULT_CONFIG_PATH
from rovodev.commands.serve.api import start_server
from rovodev.common.agent import create_agent_factory
from rovodev.common.banner import BANNER
from rovodev.common.config import load_config

app = typer.Typer(pretty_exceptions_show_locals=False, pretty_exceptions_enable=False)


@app.command()
def serve(
    port: Annotated[int, typer.Argument()],
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
):
    """Run AI Agent CLI in server mode.""" # Changed RovoDev
    rich.print(BANNER)
    config = load_config(config_file)

    # Set CLI provided options
    if shadow is not None:
        config.agent.experimental.enable_shadow_mode = shadow

    agent_factory = create_agent_factory(config=config, config_file=config_file, interactive=False)
    agent = agent_factory.create()

    # Join message parts into a single string if provided
    initial_message = None
    if message and len(message) > 0:
        initial_message = " ".join(message)

    start_server(
        agent=agent,
        agent_factory=agent_factory,
        port=port,
        streaming=config.agent.streaming,
        initial_message=initial_message,
    )
