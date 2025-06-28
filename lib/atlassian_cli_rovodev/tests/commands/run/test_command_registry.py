from io import StringIO

import pytest
from rich.console import Console

from rovodev.commands.run.command_registry import CommandRegistry


def test_singleton_instance():
    # Test that CommandRegistry is a singleton
    registry1 = CommandRegistry()
    registry2 = CommandRegistry()
    assert registry1 is registry2


def test_register_command():
    registry = CommandRegistry()
    registry._commands.clear()

    # Test registering a main command
    @registry.register("/test", None, "Test command")
    def test_command():
        return "test"

    assert "/test" in registry.commands
    assert registry._commands["/test"][None][1] == "Test command"

    # Test registering a subcommand
    @registry.register("/test", "sub", "Test subcommand")
    def test_subcommand():
        return "test_sub"

    assert "sub" in registry._commands["/test"]
    assert registry._commands["/test"]["sub"][1] == "Test subcommand"


def test_register_duplicate_command():
    registry = CommandRegistry()

    @registry.register("/duplicate", "sub", "First registration")
    def first_command():
        pass

    # Test that registering a duplicate command raises an AssertionError
    with pytest.raises(AssertionError):

        @registry.register("/duplicate", "sub", "Second registration")
        def second_command():
            pass


def test_register_reserved_help_command():
    registry = CommandRegistry()

    # Test that registering '/help' as command raises an AssertionError
    with pytest.raises(AssertionError):

        @registry.register("/help", None, "Help command")
        def help_command():
            pass


def test_register_reserved_help_subcommand():
    registry = CommandRegistry()

    # Test that registering 'help' as subcommand raises an AssertionError
    with pytest.raises(AssertionError):

        @registry.register("/test", "help", "Help command")
        def help_command():
            pass


def test_dispatch_command():
    registry = CommandRegistry()

    @registry.register("/dispatch", None, "Main command")
    def main_command(*args, **kwargs):
        return "main", args, kwargs

    @registry.register("/dispatch", "sub", "Sub command")
    def sub_command(*args, **kwargs):
        return "sub", args, kwargs

    @registry.register("/dispatch-non-none", "sub", "Sub command")
    def sub_command(*args, **kwargs):
        return "sub", args, kwargs

    # Test dispatching main command
    result = registry.dispatch("/dispatch", "arg1", kwarg1="value1")
    assert result[0] == "main"
    assert result[1] == ("arg1",)
    assert result[2]["kwarg1"] == "value1"

    # Test dispatching non-matching subcommand to a command with None subcommand
    result = registry.dispatch("/dispatch main_arg", "arg1", kwarg1="value1")
    assert result[0] == "main"
    assert result[1] == ("arg1",)
    assert result[2]["kwarg1"] == "value1"
    assert result[2]["_message_list"] == ["main_arg"]

    # Test dispatching subcommand with additional message parts
    result = registry.dispatch("/dispatch sub extra1 extra2", "arg1", kwarg1="value1")
    assert result[0] == "sub"
    assert result[1] == ("arg1",)
    assert result[2]["kwarg1"] == "value1"
    assert result[2]["_message_list"] == ["extra1", "extra2"]

    # Test dispatching subcommand with additional message parts in shell format
    result = registry.dispatch('/dispatch sub "extra1  extra2"', "arg1", kwarg1="value1")
    assert result[0] == "sub"
    assert result[1] == ("arg1",)
    assert result[2]["kwarg1"] == "value1"
    assert result[2]["_message_list"] == ["extra1  extra2"]

    # Test dispatching non-matching subcommand to a command without None subcommand
    result = registry.dispatch("/dispatch-non-none main_arg")
    assert result is None


def test_dispatch_help():
    registry = CommandRegistry()

    @registry.register("/help_test", None, "Test command")
    def test_command(*args, **kwargs):
        return "test"

    # Test that dispatching /help returns None
    assert registry.dispatch("/help") is None

    # Test that dispatching unknown command returns None
    assert registry.dispatch("/unknown") is None

    # Test that dispatching command help returns None
    assert registry.dispatch("/help_test help") is None


def test_commands_list():
    registry = CommandRegistry()
    registry._commands.clear()

    @registry.register("/cmd1", None, "Command 1")
    def cmd1():
        pass

    @registry.register("/cmd2", None, "Command 2")
    def cmd2():
        pass

    commands = registry.commands
    assert len(commands) == 3
    assert "/cmd1" in commands
    assert "/cmd2" in commands
    assert "/help" in commands
    assert commands == sorted(commands)  # Test that commands are sorted


def test_help_table_formatting():
    registry = CommandRegistry()

    # Register some test commands
    @registry.register("/test", None, "Main test command")
    def test_command():
        pass

    @registry.register("/test", "sub1", "First subcommand")
    def test_sub1():
        pass

    @registry.register("/test", "sub3", None)
    @registry.register("/test", "sub2", "Second subcommand")
    def test_sub2():
        pass

    @registry.register("/another", None, "Another main command")
    def another_command():
        pass

    @registry.register("/help_test_no_help", None, None)
    def test_command():
        return "test"

    # Create a string buffer to capture console output
    output = StringIO()
    console = Console(file=output, force_terminal=True)

    # Patch the Console instance in the registry
    original_console = registry.help.__globals__["Console"]
    registry.help.__globals__["Console"] = lambda: console

    try:
        # Test main help table (no specific command)
        registry.help()
        main_help_output = output.getvalue()

        # Verify main help content
        assert "/test" in main_help_output
        assert "Main test command" in main_help_output
        assert "/another" in main_help_output
        assert "Another main command" in main_help_output
        assert "/help_test_no_help" not in main_help_output

        # Clear the buffer for next test
        output.seek(0)
        output.truncate()

        # Test command-specific help table
        registry.help("/test")
        command_help_output = output.getvalue()

        # Verify command-specific help content
        assert "sub1" in command_help_output
        assert "First subcommand" in command_help_output
        assert "sub2" in command_help_output
        assert "Second subcommand" in command_help_output

        # Verify formatting elements
        assert "\x1b[1m" in main_help_output  # Check color styling
        assert "\x1b[90m" in main_help_output  # Check color styling

        # Clear the buffer for next test
        output.seek(0)
        output.truncate()

        # Test command-specific help table with subcommand
        registry.help("/test", "sub1")
        command_help_output = output.getvalue()

        # Verify command-specific help content
        assert "sub1" in command_help_output
        assert "sub2" not in command_help_output

        # Clear the buffer for next test
        output.seek(0)
        output.truncate()

        # Test command-specific help table with unknown subcommand
        registry.help("/test", "sub3")
        command_help_output = output.getvalue()

        # Verify command-specific help content
        assert "sub1" not in command_help_output
        assert "sub2" not in command_help_output
        assert "No help message found for subcommand sub3" in command_help_output

    finally:
        # Restore the original Console class
        registry.help.__globals__["Console"] = original_console


def test_internal_command():
    registry = CommandRegistry()
    registry._commands.clear() # Ensure clean state for this specific test

    # Test that a command with disable_for_external=True is NOT registered
    @registry.register(
        "/command_disabled_external", None, "Test command", disable_for_external=True # user_email removed as it's now irrelevant for this case
    )
    def test_disabled_command():
        pass

    assert "/command_disabled_external" not in registry.commands

    # Test that a command with disable_for_external=False (default) IS registered
    @registry.register(
        "/command_enabled_external", "sub", "Test subcommand" # disable_for_external defaults to False
    )
    def test_enabled_command():
        pass

    assert "/command_enabled_external" in registry.commands


def test_extended_help():
    """Test that extended help is displayed for command-specific help requests."""
    registry = CommandRegistry()

    @registry.register(
        "/test_extended", None, "Short help", "This is extended help that should only appear for '/test_extended help'."
    )
    def test_command():
        return "test"

    @registry.register("/test_no_extended", None, "Short help only")
    def test_no_extended():
        return "test"

    # Create a string buffer to capture console output
    output = StringIO()
    console = Console(file=output, force_terminal=True)

    # Patch the Console instance in the registry
    original_console = registry.help.__globals__["Console"]
    registry.help.__globals__["Console"] = lambda: console

    try:
        # Test command with extended help
        registry.help("/test_extended")
        extended_help_output = output.getvalue()

        # Verify extended help is shown
        assert "This is extended help that should only appear for" in extended_help_output
        assert "test_extended help" in extended_help_output
        assert "/test_extended" in extended_help_output

        # Clear the buffer for next test
        output.seek(0)
        output.truncate()

        # Test command without extended help
        registry.help("/test_no_extended")
        no_extended_help_output = output.getvalue()

        # Verify only regular help table is shown
        assert "This is extended help" not in no_extended_help_output
        assert "/test_no_extended" in no_extended_help_output

        # Clear the buffer for next test
        output.seek(0)
        output.truncate()

        # Test general help (should not show extended help)
        registry.help()
        general_help_output = output.getvalue()

        # Verify extended help is not shown in general help
        assert "This is extended help that should only appear for" not in general_help_output
        assert "Short help" in general_help_output

    finally:
        # Restore the original Console class
        registry.help.__globals__["Console"] = original_console


def test_dispatch_extended_help():
    """Test that dispatching 'command help' shows extended help."""
    registry = CommandRegistry()

    @registry.register("/test_dispatch", None, "Short help", "Extended help for dispatch test.")
    def test_command():
        return "test"

    # Create a string buffer to capture console output
    output = StringIO()
    console = Console(file=output, force_terminal=True)

    # Patch the Console instance in the registry
    original_console = registry.help.__globals__["Console"]
    registry.help.__globals__["Console"] = lambda: console

    try:
        # Test dispatching command help
        result = registry.dispatch("/test_dispatch help")
        dispatch_help_output = output.getvalue()

        # Should return None (help was displayed)
        assert result is None
        # Verify extended help is shown
        assert "Extended help for dispatch test." in dispatch_help_output

    finally:
        # Restore the original Console class
        registry.help.__globals__["Console"] = original_console
