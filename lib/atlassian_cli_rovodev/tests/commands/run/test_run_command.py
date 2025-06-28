"""Unit tests for the run command functions."""

from unittest.mock import patch

import pytest

from rovodev.commands.run.command import clear_command, feedback_command
from rovodev.common.config_model import AIAgentConfig # Changed import


@pytest.fixture
def mock_session_setup(tmp_path):
    """Set up a mock session directory for testing."""
    persistence_dir = tmp_path / "sessions"
    persistence_dir.mkdir()
    session_id = "test-session-123"
    session_dir = persistence_dir / session_id
    session_dir.mkdir()

    # Create some dummy files in the session directory
    (session_dir / "messages.json").write_text('{"messages": []}')
    (session_dir / "metadata.json").write_text('{"created": "2024-01-01"}')

    return {"persistence_dir": str(persistence_dir), "session_id": session_id, "session_dir": session_dir}


@patch("rovodev.commands.run.command.track_session_created")
@patch("rovodev.commands.run.command.logger")
def test_clear_command_success(mock_logger, mock_track_session, mock_session_setup):
    """Test successful clearing of session history."""
    # Arrange
    kwargs = {
        "persistence_dir": mock_session_setup["persistence_dir"],
        "session_id": mock_session_setup["session_id"],
    }

    # Verify session directory exists before clearing
    assert mock_session_setup["session_dir"].exists()
    assert mock_session_setup["session_dir"].is_dir()

    # Act
    result = clear_command(**kwargs)

    # Assert
    # Check that the old session directory was removed
    assert not mock_session_setup["session_dir"].exists()

    # Check that logger.info was called for session removal
    mock_logger.info.assert_called_with(f"Removing session: {mock_session_setup['session_dir']}")

    # Check that logger.bind().info was called for session cleared message
    mock_logger.bind.assert_called_with(role="info")
    mock_logger.bind.return_value.info.assert_called_with("Session history cleared")

    # Check that track_session_created was called with original session ID
    mock_track_session.assert_called_once_with(mock_session_setup["session_id"])

    # Check return value
    expected_result = {"continue": True, "message_history": None, "session_id": mock_session_setup["session_id"]}
    assert result == expected_result


@patch("rovodev.commands.run.command.track_session_created")
@patch("rovodev.commands.run.command.logger")
def test_clear_command_nonexistent_session(mock_logger, mock_track_session, tmp_path):
    """Test clearing when session directory doesn't exist."""
    # Arrange
    persistence_dir = tmp_path / "sessions"
    persistence_dir.mkdir()
    nonexistent_session_id = "nonexistent-session"

    kwargs = {"persistence_dir": str(persistence_dir), "session_id": nonexistent_session_id}

    # Act
    result = clear_command(**kwargs)

    # Assert
    # Check that logger.info was NOT called for session removal (since directory doesn't exist)
    mock_logger.info.assert_not_called()

    # Check that logger.bind().info was still called for session cleared message
    mock_logger.bind.assert_called_with(role="info")
    mock_logger.bind.return_value.info.assert_called_with("Session history cleared")

    # Check that track_session_created was called with original session ID
    mock_track_session.assert_called_once_with(nonexistent_session_id)

    # Check return value
    expected_result = {"continue": True, "message_history": None, "session_id": nonexistent_session_id}
    assert result == expected_result


@patch("rovodev.commands.run.command.track_session_created")
@patch("rovodev.commands.run.command.logger")
@patch("rovodev.commands.run.command.shutil.rmtree")
def test_clear_command_removal_failure(mock_rmtree, mock_logger, mock_track_session, mock_session_setup):
    """Test behavior when session directory removal fails."""
    # Arrange
    mock_rmtree.side_effect = OSError("Permission denied")

    kwargs = {
        "persistence_dir": mock_session_setup["persistence_dir"],
        "session_id": mock_session_setup["session_id"],
    }

    # Act
    result = clear_command(**kwargs)

    # Assert
    # Check that logger.info was called for session removal attempt
    mock_logger.info.assert_called_with(f"Removing session: {mock_session_setup['session_dir']}")

    # Check that logger.warning was called for removal failure
    mock_logger.warning.assert_called_with(f"Failed to remove session directory: {mock_session_setup['session_dir']}")

    # Check that logger.bind().info was still called for session cleared message
    mock_logger.bind.assert_called_with(role="info")
    mock_logger.bind.return_value.info.assert_called_with("Session history cleared")

    # Check that track_session_created was called with original session ID
    mock_track_session.assert_called_once_with(mock_session_setup["session_id"])

    # Check return value
    expected_result = {"continue": True, "message_history": None, "session_id": mock_session_setup["session_id"]}
    assert result == expected_result


@patch("rovodev.commands.run.command.rich.print")
def test_feedback_command(mock_rich_print):
    """Test that feedback_command displays the correct feedback information."""
    # Act
    feedback_command(config=AIAgentConfig()) # Changed RovoDevConfig

    # Verify that rich.print was called once
    mock_rich_print.assert_called_once()

    # Get the Panel object that was passed to rich.print
    call_args = mock_rich_print.call_args[0]
    text = call_args[0]

    # Verify that the panel contains generic feedback instructions
    assert "project's issue tracker" in text
    assert "discussion forum" in text
    assert "AI Agent CLI" in text # Check for new branding
    # Ensure old Atlassian links are NOT present
    assert "https://rovodevagents.atlassian.net" not in text
    assert "https://community.atlassian.com" not in text
