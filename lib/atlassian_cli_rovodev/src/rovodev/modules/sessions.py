"""Session management module."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.usage import Usage

from nemo.context import DefaultSessionContext
from nemo.models import SessionMetadata
from rovodev.ui.components import session_menu_panel

# Import session instrumentation - REMOVED as analytics module was deleted
# from .analytics.instrumentation.session import track_session_created, track_session_forked, track_session_switched

default_context_limit = 200000


class Session(BaseModel):
    """Session model."""

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str = "Untitled Session"
    created: str | None = None
    last_saved: str | None = None
    num_messages: int = 0
    total_usage: Usage = Field(default_factory=Usage)
    latest_usage: Usage = Field(default_factory=Usage)
    context_limit: int = default_context_limit
    initial_prompt: str | None = None
    message_history: list[ModelMessage] = Field(default_factory=list)
    path: Path | None = None
    parent_session_id: str | None = None
    _parent_session: "Session | None" = None
    _sort_key: str = ""
    _display_title: str = ""

    def model_post_init(self, context):
        """Post-initialization for the model."""
        self._sort_key = self.last_saved or self.created or ""
        self._display_title = self.title
        return super().model_post_init(context)

    def _get_sort_key(self) -> str:
        """Get the sort key for sorting sessions."""
        sub_sort_key = (self.last_saved or self.created or "") + "_" * 10
        if self._parent_session:
            return self._parent_session._get_sort_key().rstrip("_") + sub_sort_key
        return sub_sort_key

    def _get_display_title(self) -> str:
        """Get the display title for the session."""
        if self._parent_session:
            current = self
            depth = 0
            while current._parent_session:
                current = current._parent_session
                depth += 1
            return "  " * (depth - 1) + "└─" + self.title
        return self.title


def get_sessions(persistence_dir: Path, workspace_path: Path | None = None) -> dict[str, Session]:
    """Get the sessions.

    Args:
        persistence_dir: Directory containing session data
        workspace_path: If provided, only return sessions created in this workspace.
                      Should be an absolute path.

    Returns:
        Dictionary of session data filtered by workspace if specified
    """
    sessions: dict[str, Session] = {}
    # Get all subdirectories that contain session_context.json files
    for session_context_path in persistence_dir.rglob("session_context.json"):
        session_dir = session_context_path.parent
        session_context = DefaultSessionContext.model_validate_json(session_context_path.read_text())
        session_messages = session_context.message_history
        created_time = datetime.fromtimestamp(session_context.timestamp)
        last_saved_time = datetime.fromtimestamp(session_context_path.stat().st_mtime)

        title = "Untitled Session"
        metadata_path = session_dir / "metadata.json"
        parent_session_id = None
        if metadata_path.exists():
            try:
                metadata = SessionMetadata.model_validate_json(metadata_path.read_text())
                # Handle workspace path filtering
                if workspace_path:
                    # For sessions with workspace path, filter by matching path
                    if metadata.workspace_path:
                        session_workspace = Path(metadata.workspace_path).resolve()
                        if session_workspace != workspace_path.resolve():
                            continue
                    else:
                        # For legacy sessions without workspace path, show them in all workspaces
                        # This maintains backward compatibility until they're migrated
                        pass

                title = metadata.title or "Untitled Session"
                if metadata.fork_data:
                    parent_session_id = metadata.fork_data.parent_session_id
            except Exception:
                # Skip sessions with invalid metadata
                continue

        session_info = Session(
            session_id=session_dir.stem,
            title=title,
            created=created_time.strftime("%Y-%m-%d %H:%M:%S"),
            last_saved=last_saved_time.strftime("%Y-%m-%d %H:%M:%S"),
            num_messages=len(session_messages),
            total_usage=session_context.usage,
            latest_usage=get_latest_usage(session_messages),
            context_limit=default_context_limit,
            initial_prompt=session_context.initial_prompt[:100] + "...",
            message_history=session_context.message_history,
            path=session_dir,
            parent_session_id=parent_session_id,
        )
        sessions[session_info.session_id] = session_info

    for session in sessions.values():
        # Set parent session if available
        if session.parent_session_id and session.parent_session_id in sessions:
            session._parent_session = sessions[session.parent_session_id]
    for session in sessions.values():
        # Set sort key and display title
        session._sort_key = session._get_sort_key()
        session._display_title = session._get_display_title()

    # Sort sessions by last_saved time (most recent first) and convert back to dict
    sorted_sessions = dict(sorted(sessions.items(), key=lambda item: item[1]._sort_key, reverse=True))
    return sorted_sessions


def get_most_recent_session(sessions: dict[str, Session]) -> tuple[str, Session] | None:
    """Get the most recently active session.

    Args:
        sessions: Dictionary of sessions

    Returns:
        Tuple of (session_id, session) for most recent session, or None if no sessions
    """
    if not sessions:
        return None

    # Sort by last_saved/created time and get most recent
    sorted_sessions = sorted(
        sessions.items(), key=lambda item: item[1].last_saved or item[1].created or "", reverse=True
    )
    return sorted_sessions[0]


def get_latest_usage(message_history: list[ModelMessage]) -> Usage:
    """Get the latest usage from message history.

    Args:
        message_history: List of message history

    Returns:
        Dictionary of latest usage
    """
    responses = [m for m in message_history if isinstance(m, ModelResponse)]
    if not responses:
        return Usage()
    return responses[-1].usage


def handle_sessions_command(
    persistence_dir: Path | str, current_session_id: str, root_path: str | None = None
) -> tuple[Session | None, bool]:
    """Handle the /sessions command.

    Args:
        persistence_dir: Directory containing session data
        current_session_id: Currently active session ID
        root_path: The workspace root path. If None, uses current directory.

    Returns:
        Tuple of (selected session ID, message history or None)
    """
    persistence_dir = Path(persistence_dir)

    # Get available sessions for current workspace
    workspace_path = Path(root_path).resolve() if root_path else Path.cwd()
    sessions = get_sessions(persistence_dir, workspace_path=workspace_path)

    if current_session_id not in sessions:
        sessions = {
            current_session_id: Session(
                session_id=current_session_id,
                path=persistence_dir / current_session_id,
            )
        } | sessions

    selected_session, is_new_session = asyncio.run(session_menu_panel(sessions, current_session_id, persistence_dir))

    # Add instrumentation for session events - REMOVED as analytics module was deleted
    if is_new_session and not selected_session:
        # Creating a new session - persistence will happen when session is actually used
        new_session = Session()
        # track_session_created(new_session.session_id) # Removed
        return new_session, is_new_session
    elif selected_session and selected_session.session_id != current_session_id:
        # Switching to an existing session
        # track_session_switched(current_session_id, selected_session.session_id) # Removed
        pass # Keep the logic flow, just don't track

    return selected_session, is_new_session
