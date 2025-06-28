"""Rovodev session menu panel."""

from __future__ import annotations

import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from textwrap import wrap
from typing import TYPE_CHECKING, TypedDict

from humanize import metric, naturaldate, naturaltime
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.output import DummyOutput
from pydantic_ai.messages import ModelRequest, ModelResponse
from rich.columns import Columns
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel

from nemo.constants import DEFAULT_PANEL_WIDTH
from nemo.models import ForkData, SessionMetadata
from nemo.utils.logging import truncate_message
# from rovodev.modules.analytics.instrumentation.session import track_session_deleted, track_session_forked # Removed
from rovodev.ui.components.user_menu_panel import Choice, user_menu_panel

if TYPE_CHECKING:
    from rovodev.modules.sessions import Session

console = Console()

MAX_VISIBLE_ITEMS = 15
TITLE_WIDTH = 40
USAGE_WIDTH = 10
TITLE_TEMPLATE = "{title:<34} {message_cnt:>9} {last_activity:>16}  {usage:<10}"
MENU_TEMPLATE = "{title:<40} {message_cnt:>3} {last_activity:>16}  {usage:<10}"
DETAILS_WIDTH = 39
DETAILS_TEMPLATE = """

[bold]{title}[/bold]
[bright_black]{session_id}[/bright_black]
Created [bright_black]{created}[/bright_black]

🔎 Message Analysis
User: [bright_black]{user_cnt}[/bright_black] Assistant: [bright_black]{assistant_cnt}[/bright_black] Total: \
[bright_black]{message_cnt}[/bright_black]

Cumulative Token Usage:
Input: [bright_black]{input_tokens}[/bright_black] Output: [bright_black]{output_tokens}[/bright_black]

💬 Conversation
Initial Prompt: [bright_black]{initial_prompt}[/bright_black]
Latest Message: [bright_black]{latest_message}[/bright_black]
"""
FOOTER = """\
[bright_black]↑ ↓: Navigate | n: New session | f: Fork session | d: Delete session | Enter: Select session | \
q: Quit[/bright_black]\
"""


class SelectionInfo(TypedDict):
    """Selection information for the session menu panel."""

    index: int
    choice: Session | None
    is_new: bool
    deleted_session: str | None


async def session_menu_panel(
    sessions: dict[str, Session],
    current_session_id: str,
    persistence_dir: Path,
    root_path: str | None = None,
) -> tuple[Session | None, bool]:
    """Display a session menu panel for viewing and selecting sessions.

    Args:
        sessions: Dictionary of available sessions.
        current_session_id: Currently active session ID.
        persistence_dir: Directory containing session data.
    """
    buffer = Buffer()
    kb = KeyBindings()
    session_ids = list(sessions)
    selection_info: SelectionInfo = {
        "index": session_ids.index(current_session_id),
        "choice": sessions[current_session_id],
        "is_new": False,
        "deleted_session": None,
    }

    @kb.add("c-c")
    def _(event: KeyPressEvent) -> None:
        """Ctrl-C to cancel"""
        event.app.exit(exception=SystemExit(0))

    @kb.add("down")
    def _(event: KeyPressEvent) -> None:
        selection_info["index"] = (selection_info["index"] + 1) % len(session_ids)
        selection_info["choice"] = sessions[session_ids[selection_info["index"]]]

    @kb.add("up")
    def _(event: KeyPressEvent) -> None:
        selection_info["index"] = (selection_info["index"] - 1) % len(session_ids)
        selection_info["choice"] = sessions[session_ids[selection_info["index"]]]

    @kb.add("enter")
    def _(event: KeyPressEvent) -> None:
        """Enter to accept"""
        event.app.exit()

    @kb.add("q")
    def _(event: KeyPressEvent) -> None:
        """Handle q key"""
        selection_info["choice"] = None
        event.app.exit()

    @kb.add("d")
    def _(event: KeyPressEvent) -> None:
        """Delete a session"""
        assert selection_info["choice"], "No session selected for deletion"
        selection_info["deleted_session"] = selection_info["choice"].session_id
        event.app.exit()

    @kb.add("n")
    def _(event: KeyPressEvent) -> None:
        """Create a new session"""
        selection_info["choice"] = None
        selection_info["is_new"] = True
        event.app.exit()

    @kb.add("f")
    def _(event: KeyPressEvent) -> None:
        """Fork a session"""
        session = selection_info["choice"]
        assert session, "No session selected for forking"
        # Create a new session ID and copy the session data
        fork_session_id = str(uuid.uuid4())
        title = f"Fork of {session.title}"
        fork_path = persistence_dir / fork_session_id
        fork_path.mkdir(parents=True, exist_ok=True)
        if session.path and session.path.exists():
            shutil.copytree(session.path, fork_path, dirs_exist_ok=True)
        metadata = SessionMetadata(
            title=title,
            workspace_path=str(Path(root_path).resolve() if root_path else Path.cwd()),  # Use root_path if available
            fork_data=ForkData(
                parent_session_id=session.session_id,
                fork_point=len(session.message_history),
            ),
        )
        (fork_path / "metadata.json").write_text(metadata.model_dump_json(indent=2))

        # Track the fork event - REMOVED
        # track_session_forked(
        #     parent_session_id=session.session_id,
        #     new_session_id=fork_session_id,
        #     title=title,
        # )

        # Update the session information
        session.session_id = fork_session_id
        session.title = title
        session.path = fork_path
        selection_info["is_new"] = True
        event.app.exit()

    # Create dummy layout for prompt-toolkit
    layout = Layout(Window(BufferControl(buffer=buffer)))

    # Create application
    app = Application(
        output=DummyOutput(),
        layout=layout,
        key_bindings=kb,
        full_screen=False,
        erase_when_done=True,
        mouse_support=False,
        paste_mode=True,
    )

    def create_panel() -> Group:
        """Create the session menu panel on each refresh."""
        menu_text = [
            "[bold]  "
            + TITLE_TEMPLATE.format(
                title="Title", message_cnt="Messages", last_activity="Last Activity", usage="Context"
            )
            + "[/bold]"
        ]

        first_visible_item = max(0, selection_info["index"] - MAX_VISIBLE_ITEMS // 2)
        last_visible_item = min(len(session_ids), first_visible_item + MAX_VISIBLE_ITEMS)
        first_visible_item = max(0, last_visible_item - MAX_VISIBLE_ITEMS)
        visible_session_ids = session_ids[first_visible_item:last_visible_item]
        if first_visible_item > 0:
            menu_text.append("[bright_black]  ...[/bright_black]")
        else:
            menu_text.append("")

        details_text = ""
        for session_id in visible_session_ids:
            session = sessions[session_id]
            session_entry = MENU_TEMPLATE.format(
                title=(
                    session._display_title
                    if len(session._display_title) < TITLE_WIDTH
                    else session._display_title[: (TITLE_WIDTH - 4)] + "..."
                ),
                message_cnt=session.num_messages,
                last_activity=_format_datetime(session.last_saved),
                usage=_format_usage(session.latest_usage.total_tokens, session.context_limit),
            )
            if selection_info["choice"] and session_id == selection_info["choice"].session_id:
                details_text = _format_details(session)
                menu_text.append(f"[blue bold]> {session_entry}[/blue bold]")
            else:
                menu_text.append(f"[bright_black]  {session_entry}[/bright_black]")

        if last_visible_item < len(session_ids) - 1:
            menu_text.append("[bright_black]  ...[/bright_black]")
        else:
            menu_text.append("")

        panel_content = Columns(["\n" + "\n".join(menu_text), details_text], padding=(0, 2))

        return Group(
            "",
            Panel(panel_content, width=DEFAULT_PANEL_WIDTH, title="Session management", title_align="left"),
            FOOTER,
        )

    if console._live is not None:
        console._live.stop()
        console._live = None
    with Live(create_panel(), auto_refresh=False, transient=True) as live:

        def before_render(_: Application) -> None:
            live.update(create_panel())
            live.refresh()

        app.before_render += before_render
        await app.run_async()

    if selection_info["deleted_session"]:
        if len(sessions) == 1:
            console.print("[red]Cannot delete the only remaining session.[/red]")
            return await session_menu_panel(sessions, current_session_id, persistence_dir)
        session_to_delete = sessions[selection_info["deleted_session"]]
        response = await user_menu_panel(
            choices=[Choice(name="Yes", value=True), Choice(name="No", value=False)],
            message=f"Are you sure you want to delete session '{session_to_delete.title}'?",
        )
        if response:
            # Track the deletion event before actually deleting - REMOVED
            # track_session_deleted(
            #     session_id=session_to_delete.session_id,
            #     title=session_to_delete.title,
            # )

            if session_to_delete.path and session_to_delete.path.exists():
                shutil.rmtree(session_to_delete.path)
            if current_session_id != session_to_delete.session_id:
                selection_info["choice"] = None
            else:
                selection_info["choice"] = next(
                    (s for s in sessions.values() if s.session_id != session_to_delete.session_id), None
                )
                current_session_id = selection_info["choice"].session_id
            del sessions[selection_info["deleted_session"]]
            for other_session in sessions.values():
                if other_session.parent_session_id == session_to_delete.session_id:
                    other_session._display_title = other_session.title
            console.print(f"[green]Deleted session: {selection_info['deleted_session']}[/green]")
        if sessions:
            return await session_menu_panel(sessions, current_session_id, persistence_dir)

    return selection_info["choice"], selection_info["is_new"]


def _format_datetime(dt_str: str | None) -> str:
    """Format datetime in a human-readable way using humanize."""
    if not dt_str:
        return "-"
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        # For recent times use naturaltime
        time_ago = naturaltime(dt)

        # For older dates (more than 7 days), use naturaldate
        if (datetime.now() - dt).days > 7:
            time_ago = naturaldate(dt)

        return time_ago
    except ValueError:
        return dt_str


def _format_usage(latest_tokens: int | None, context_limit: int) -> str:
    """Format usage information."""
    context_proportion = min((latest_tokens or 0) / context_limit, 1)
    filled_bars = int(context_proportion * USAGE_WIDTH)
    empty_bars = USAGE_WIDTH - filled_bars
    context_bar = "[bold blue]" + "▮" * filled_bars
    context_bar += "[dim]" + "▮" * empty_bars + "[/dim][/bold blue]"
    return context_bar


def _format_details(session: Session) -> str:
    """Format session details."""
    responses = [m for m in session.message_history if isinstance(m, ModelResponse)]
    requests = [m for m in session.message_history if isinstance(m, ModelRequest)]
    user_prompt_requests = [m for m in requests if any(p.part_kind == "user-prompt" for p in m.parts)]
    first_request = requests[0] if requests else None
    last_response = responses[-1] if responses else None

    initial_prompt = "-"
    if first_request:
        for part in first_request.parts:
            if part.part_kind == "user-prompt":
                initial_prompt_lines = wrap(str(part.content).split("\n")[0], DETAILS_WIDTH, initial_indent=" " * 16)
                initial_prompt = "\n".join(initial_prompt_lines[:3]).strip()
                if len(initial_prompt_lines) > 3:
                    initial_prompt = initial_prompt[:-3] + "..."
                break
    initial_prompt += "\n" * max(0, 2 - initial_prompt.count("\n"))

    latest_message = "-"
    if last_response:
        for part in last_response.parts:
            if part.part_kind == "text":
                latest_message_lines = wrap(part.content.split("\n")[0], DETAILS_WIDTH, initial_indent=" " * 16)
                latest_message = "\n".join(latest_message_lines[:2]).strip()
                if len(latest_message) > 2:
                    latest_message = latest_message[:-3] + "..."
                break
    latest_message += "\n" * max(0, 1 - latest_message.count("\n"))

    details_text = DETAILS_TEMPLATE.format(
        title=truncate_message(session.title, DETAILS_WIDTH, 1),
        session_id=session.session_id,
        created=_format_datetime(session.created or ""),
        last_updated=_format_datetime(session.last_saved or ""),
        message_cnt=session.num_messages,
        user_cnt=len(user_prompt_requests),
        assistant_cnt=len(responses),
        input_tokens=metric(session.total_usage.request_tokens or 0, "").replace(" ", ""),
        output_tokens=metric(session.total_usage.response_tokens or 0, "").replace(" ", ""),
        total_tokens=metric(session.total_usage.total_tokens or 0, "").replace(" ", ""),
        initial_prompt=initial_prompt,
        latest_message=latest_message,
    )

    return details_text
