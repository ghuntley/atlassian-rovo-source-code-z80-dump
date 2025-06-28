"""Command Registry for Rovo Dev CLI.

To register a command:

```
from command_registry import registry

# Command.
@registry.register("/sessions", None, "Help message.", "Extended help shown only for '/sessions help'.")
def foo(...):
    ...

# Sub-command.
@registry.register("/sessions", "fork", "Help message.", "Extended help for subcommand.")
def bar(...):
    ...

# Set help message `None` so `registry.help()` will not list it as a separate command. We can
# use it to give aliases to commands and sub-commands. All the commands and sub-commands below
# are implemented by a single method `baz(...)`.
@registry.register("/sessions", "fork", None)
@registry.register("/sessions", "fork-alias", None)
@registry.register("/sessions-alias", None, "Help message.")
def baz(...):
    ...
```

To dispatch command:

```
# Returns `None` if nothing is executed and help message is printed out.
registry.dispatch("/session fork", foo, bar, baz="baz")
registry.dispatch("/session")
```

Will automatically display help message when encounters:
  * An unknown command
  * /help
  * /command help

How `/foo bar baz` is dispatched.
  * If there is only `@registry.register("/foo", None)`, the command `/foo` will be invoked with
    keyword argument `_message_list=["bar", "baz"]`.
  * If there are `@registry.register("/foo", None)` and `@registry.register("/foo", `<sub-command>`)`
    but none of the `<sub-command>` matches `bar`, the command `/foo` will be invoked with keyword
    argument `_message_list=["bar", "baz"]`.
  * If there are `@registry.register("/foo", None)` and `@registry.register("/foo", `bar`)`, the
    command `/foo bar` will be invoked with keyword argument `_message_list=["baz"]`.
  * If there is only `@registry.register("/foo", `bar`)`, the command `/foo bar` will be invoked
    with keyword argument `_message_list=["baz"]`.
  * If there is only `@registry.register("/foo", `<sub-command>`)` but none of the `<sub-command>`
    matches `bar`, help message of command `/foo` will be printed out.
"""

from collections import defaultdict
from typing import Any

import bashlex
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table

from nemo.constants import DEFAULT_PANEL_WIDTH
from rovodev import USER_EMAIL
from rovodev.modules.analytics.instrumentation.command import track_command

HELP_PREFIX = """\
[bold]Tools[/bold]
[bright_black]AI Agent uses a range of tools to best execute on your requests, simply ask AI Agent to complete a task \
and it will use code navigation, search, and editing tools to best achieve your outcomes. AI Agent can perform actions \
against your workspace and access your tasks and documents (if configured). AI Agent will only complete actions \
it has permission to do so.[/bright_black]

[bold]Commands[/bold]
[bright_black]Commands allow you to quickly execute pre-defined AI Agent features.[/bright_black]
""" # Changed Rovo Dev


class CommandRegistry:
    _instance = None
    _commands = defaultdict(
        defaultdict
    )  # command: str -> {sub_command: str | None -> (func: callable, help: str, extended_help: str | None)}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(
        self,
        command: str,
        sub_command: str | None,
        help: str | None,
        extended_help: str | None = None,
        disable_for_external: bool = False,
        user_email: str = USER_EMAIL,
    ):
        def decorator(func):
            assert command != "/help", "Command `/help` is reserved."
            assert sub_command != "help", "Subcommand `help` is reserved."
            # If disable_for_external is True, command is not registered in a generic template.
            # User can change this logic or a config to enable such commands.
            # The original check was: user_email.endswith("@atlassian.com")
            if not disable_for_external:
                assert (
                    sub_command not in self._commands[command]
                ), f"Registry for {command}, {sub_command} already exists."
                self._commands[command][sub_command] = (func, help, extended_help)
            return func

        return decorator

    @property
    def commands(self) -> list[str]:
        return list(self._commands) + ["/help"]

    def dispatch(self, message: str, *args, **kwargs) -> Any:
        if not message:
            return None

        try:
            parts = [item.word for item in bashlex.parse(message)[0].parts]
        except Exception:
            # Fall back to simple split if quote parsing fails
            parts = [part for part in message.split() if part.strip()]
        command = parts[0]
        command_args = parts[1:]

        # First check if this is a valid command
        if command not in self.commands:
            return None

        # Set subcommand for help commands first
        if command_args and command_args[0] == "help":
            sub_command = "help"
        else:
            # Check if this command has any registered subcommands
            has_subcommands = len(self._commands[command]) > 1 or (
                len(self._commands[command]) == 1 and None not in self._commands[command]
            )

            # Only treat first arg as subcommand if command supports subcommands and it's a valid one
            if has_subcommands and command_args and command_args[0] in self._commands[command]:
                sub_command = command_args[0]
            else:
                sub_command = None

        # Track the command execution
        with track_command(command, sub_command):
            # Handle help commands
            if "/help" == command:
                self.help()
                return None
            elif sub_command == "help":
                self.help(command)
                return None
            result = None

            def run_sub_command(command, sub_command, command_args):
                assert sub_command is not None, "Assume sub_command is not None."
                if command_args[1:] == ["help"]:
                    self.help(command, sub_command)
                    return None
                kwargs["_message_list"] = command_args[1:]
                return self._commands[command][sub_command][0](*args, **kwargs)

            if None in self._commands[command] and len(self._commands[command]) == 1:
                # Command has no non-None sub-command
                kwargs["_message_list"] = command_args
                result = self._commands[command][None][0](*args, **kwargs)
            elif None in self._commands[command]:
                if sub_command != None and sub_command in self._commands[command]:
                    # Command has a matching non-None sub-command
                    result = run_sub_command(command, sub_command, command_args)
                else:
                    # No matching non-None sub-command
                    kwargs["_message_list"] = command_args
                    result = self._commands[command][None][0](*args, **kwargs)
            elif sub_command not in self._commands[command]:
                # Cannot fall back to None sub-command
                Console().print(
                    f"[yellow]Unknown subcommand [magenta]{sub_command}[/magenta] for command "
                    f"[magenta]{command}[/magenta]. Valid subcommands are:[/yellow]"
                )
                self.help(command, show_header=False)
                return None
            else:
                # Matching non-None sub-command
                result = run_sub_command(command, sub_command, command_args)

            return result

    def render_help_table(
        self,
        command: str | None = None,
        sub_command: str | None = None,
        show_header: bool = True,
        command_filter: str | None = None,
    ):
        """Render help message as a rich renderable for the command or all commands if no command is specified."""
        table = Table(show_header=show_header, box=None, pad_edge=False, padding=(0, 5))
        table.add_column("Command", style="bright_black", no_wrap=True)
        table.add_column("Description", style="bright_black")
        if command and sub_command:
            help = self._commands[command][sub_command][1]
            if not help:
                help = f"No help message found for subcommand {sub_command}. Use `{command} help` to see more help."
            table.add_row(self.transform_keys(command + " " + sub_command), help)
        elif command:
            for key in self._commands[command]:
                command_full = command
                if key:
                    command_full += " " + key
                help = self._commands[command][key][1]
                if help:
                    table.add_row(self.transform_keys(command_full), help)
        else:
            # Ensure /exit is always at the end of the list
            command_keys = [key for key in self._commands if key != "/exit"] + ["/exit"]
            if command_filter:
                command_keys = [key for key in command_keys if key.startswith(command_filter)]
            if not command_keys:
                raise ValueError(f"No commands found matching filter: {command_filter}")
            for key in command_keys:
                help = (
                    self._commands[key][None][1]
                    if None in self._commands[key]
                    else f"Type `{key} help` to see subcommands."
                )
                if help:
                    table.add_row(self.transform_keys(key), help)
        return table

    def help(self, command: str | None = None, sub_command: str | None = None, show_header: bool = True):
        """Display help message for the command or all commands if no command is specified."""
        console = Console()

        # Check if we should show extended help for a command-specific help request
        if command and not sub_command and command in self._commands:
            # Check if the command has extended help
            command_data = None
            if None in self._commands[command]:
                command_data = self._commands[command][None]
            elif len(self._commands[command]) == 1:
                # If there's only one subcommand, use that
                command_data = next(iter(self._commands[command].values()))

            if command_data and len(command_data) >= 3 and command_data[2]:  # extended_help exists
                extended_help = "[bright_black]" + command_data[2] + "[/bright_black]"
                console.print(Panel(extended_help, width=DEFAULT_PANEL_WIDTH, box=box.SIMPLE))

        # Always show the regular help table
        renderable = self.render_help_table(command, sub_command, show_header)
        if not command and not sub_command:
            renderable = Group(HELP_PREFIX, renderable)
        console.print(Panel(renderable, width=DEFAULT_PANEL_WIDTH, box=box.SIMPLE))

    def transform_keys(self, key: str) -> str:
        """Apply custom transformation to keys for display."""
        if key.strip().startswith("#"):
            return f"{key} <note>"
        return key


registry = CommandRegistry()
