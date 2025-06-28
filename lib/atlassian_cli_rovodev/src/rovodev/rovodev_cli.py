"""AI Agent CLI.""" # Changed RovoDev

import sys

import rich
import typer

from nautilus.main import app as nautilus_app
from rovodev import IS_INTERNAL_USER, VERSION_INFO
# from rovodev.commands.auth.command import app as auth_command # Removed
from rovodev.commands.config.command import app as config_command
from rovodev.commands.log.command import app as log_command
from rovodev.commands.mcp.command import app as mcp_command
from rovodev.commands.run.command import app as run_command
from rovodev.commands.serve.command import app as serve_command

app = typer.Typer(
    help="AI Agent CLI", # Changed
    pretty_exceptions_show_locals=False,
    pretty_exceptions_enable=False,
    add_completion=False,
)
app.add_typer(nautilus_app, name="nautilus", help="Nautilus MCP Server CLI", hidden=True)
# app.add_typer(auth_command, name="auth")  # Removed
app.add_typer(run_command)
app.add_typer(config_command)
app.add_typer(log_command)
app.add_typer(mcp_command)

if IS_INTERNAL_USER: # Keep for now, will investigate IS_INTERNAL_USER later
    app.add_typer(serve_command)


@app.callback(invoke_without_command=True)
def cli(version: bool | None = typer.Option(None, "--version", help="Show the AI Agent CLI version.", is_eager=True)): # Changed
    if version:
        rich.print(VERSION_INFO)
        raise typer.Exit()


# Redirect the command to run if no command is provided
commands = {"nautilus", "run", "config", "log", "mcp"} # Removed "auth"
if IS_INTERNAL_USER: # Keep for now
    commands.add("serve")

# Run the "run" command by default if no command is specified and no top-level flags are used
if not any(flag in sys.argv for flag in ["--help", "-h", "--version", "-v"]) and (
    len(sys.argv) <= 1 or sys.argv[1] not in commands
):
    sys.argv.insert(1, "run")

# Rewrite -h to --help to enable invoking help with -h
sys.argv = [arg if arg != "-h" else "--help" for arg in sys.argv]  # Replace -h with --help

# Removed Atlassian-specific argv rewriting:
# if "--help" in sys.argv:
#     # Detect if the CLI was invoked with `atlassian_cli_rovodev` and change it to `acli rovodev`
#     if "atlassian_cli_rovodev" in sys.argv[0]:
#         sys.argv[0] = "acli rovodev"
