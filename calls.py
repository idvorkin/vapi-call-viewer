#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "typer",
#   "httpx",
#   "loguru",
#   "textual",
#   "python-dateutil",
#   "icecream",
#   "pydantic"
# ]
# ///

#!python3

import os
import json
import tempfile
import httpx
import threading
from datetime import datetime, timedelta
from dateutil import tz
from typing import List
import typer
from typer import Option
from loguru import logger
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static, Label, Button
from textual.containers import Horizontal, Container, Grid, ScrollableContainer
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.message import Message
from icecream import ic
from cache import get_cached_calls, cache_calls, get_latest_cached_call, get_cache_stats
from models import Call

# Configure logger to write to a file instead of stderr
log_file = os.path.join(tempfile.gettempdir(), "vapi_calls.log")
logger.remove()  # Remove default handler
logger.add(log_file, rotation="10 MB", level="DEBUG")  # Add file handler

# Configure icecream for silent operation
ic.configureOutput(prefix="", outputFunction=lambda *a, **kw: None)

app = typer.Typer(no_args_is_help=True)


def parse_call(call) -> Call:
    """Parse a VAPI call response into a Call model."""
    customer = ""
    if "customer" in call and "number" in call["customer"]:
        customer = call["customer"]["number"]

    created_at = call.get("createdAt")
    ended_at = call.get("endedAt", created_at)

    start_dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S.%fZ")
    end_dt = datetime.strptime(ended_at, "%Y-%m-%dT%H:%M:%S.%fZ")

    start_dt = start_dt.replace(tzinfo=tz.tzutc()).astimezone(tz.tzlocal())
    end_dt = end_dt.replace(tzinfo=tz.tzutc()).astimezone(tz.tzlocal())

    transcript = call.get("artifact", {}).get("transcript", "")
    summary = call.get("analysis", {}).get("summary", "")

    cost = call.get("cost", 0.0)
    if isinstance(cost, dict):
        cost = cost.get("total", 0.0)

    cost_breakdown = call.get("costBreakdown", {})
    ended_reason = call.get("endedReason", "")
    if ended_reason == "customer-ended-call":
        ended_reason = "Customer Ended"
    elif ended_reason == "assistant-ended-call":
        ended_reason = "Assistant Ended"
    elif ended_reason == "system-ended-call":
        ended_reason = "System Ended"
    elif ended_reason == "error":
        ended_reason = "Error"

    return Call(
        id=call["id"],
        Caller=customer,
        Transcript=transcript,
        Start=start_dt,
        End=end_dt,
        Summary=summary,
        Cost=cost,
        CostBreakdown=cost_breakdown,
        EndedReason=ended_reason,
    )


def format_phone_number(phone: str) -> str:
    """Format a phone number into a nice display format."""
    # Remove any non-digit characters
    digits = "".join(filter(str.isdigit, phone))

    # Handle different length phone numbers
    if len(digits) >= 10:  # Take last 10 digits if longer
        last_ten = digits[-10:]  # Get last 10 digits
        return f"({last_ten[:3]}){last_ten[3:6]}-{last_ten[6:]}"
    else:
        return phone  # Return original if we can't format it


class CacheUpdated(Message):
    """Event emitted when cache is updated by background thread."""

    def __init__(self, calls: List[Call]):
        self.calls = calls
        super().__init__()


def is_network_available(timeout: int = 1) -> bool:
    """Checks if the network is available by making a HEAD request."""
    try:
        response = httpx.head("https://1.1.1.1", timeout=timeout)
        logger.info(f"Network check successful: Status {response.status_code}")
        return True
    except (httpx.NetworkError, httpx.TimeoutException) as e:
        logger.warning(f"Network check failed: {e}")
        return False
    except Exception as e: # Catch any other unexpected errors
        logger.error(f"Unexpected error during network check: {e}")
        return False


class CacheUpdateManager:
    """Manages background updates of the cache."""

    def __init__(self, app=None, foreground_updates=False, offline: bool = False):
        self.app = app
        self.updating = False
        self.thread = None
        self.last_update = None
        self.foreground_updates = foreground_updates
        self.offline = offline

    def start_background_update(self):
        """Start a background thread to check for cache updates."""
        if self.updating or self.offline:
            if self.offline:
                logger.info("Offline mode: Skipping cache update.")
            return False  # Already updating or in offline mode

        self.updating = True

        if self.foreground_updates:
            # Run update in foreground
            logger.info("Running cache update in foreground")
            self._check_and_update_cache()
            return True
        else:
            # Run update in background thread
            self.thread = threading.Thread(target=self._check_and_update_cache)
            self.thread.daemon = True  # Allow app to exit even if thread is running
            self.thread.start()
            return True

    def _check_and_update_cache(self):
        """Background thread function to check and update cache."""
        if self.offline:
            logger.info("Offline (flag): Skipping cache check and update.")
            self.updating = False
            return

        if not is_network_available():
            logger.warning("Network unavailable: Skipping cache check and update for this cycle.")
            self.updating = False
            # self.last_update is set in finally
            return

        try:
            log_msg = "Checking for new calls..."
            if self.foreground_updates:
                print(log_msg)
            logger.debug(log_msg)

            # First get cached calls
            cached_calls = get_cached_calls()
            if cached_calls is None:
                # No cache yet, fetch from API only if network is available (checked above)
                log_msg = "No cache found, creating initial cache..."
                if self.foreground_updates:
                    print(log_msg)
                logger.debug(log_msg)

                new_calls = self._fetch_all_calls() # This makes an API call
                if new_calls:
                    cache_calls(new_calls)
                    log_msg = f"Initial cache created with {len(new_calls)} calls"
                    if self.foreground_updates:
                        print(log_msg)
                    logger.info(log_msg)
                    self._notify_update(new_calls)
                return

            # Check if there are new calls (makes an API call)
            try:
                log_msg = "Checking if there are new calls available..."
                if self.foreground_updates:
                    print(log_msg)
                logger.debug(log_msg)

                new_calls_available = self._check_for_new_calls()
                if new_calls_available:
                    # Fetch and cache new calls
                    log_msg = "New calls available, fetching from API..."
                    if self.foreground_updates:
                        print(log_msg)
                    logger.debug(log_msg)

                    new_calls = self._fetch_all_calls()
                    if new_calls:
                        cache_calls(new_calls)
                        log_msg = f"Updated cache with {len(new_calls)} calls"
                        if self.foreground_updates:
                            print(log_msg)
                        logger.info(log_msg)
                        self._notify_update(new_calls)
                else:
                    log_msg = "Cache is already up to date"
                    if self.foreground_updates:
                        print(log_msg)
                    logger.debug(log_msg)
            except Exception as e:
                log_msg = f"Error checking for new calls: {e}"
                if self.foreground_updates:
                    print(f"ERROR: {log_msg}")
                logger.error(log_msg)

        except Exception as e:
            log_msg = f"Update error: {e}"
            if self.foreground_updates:
                print(f"ERROR: {log_msg}")
            logger.error(log_msg)
        finally:
            self.updating = False
            self.last_update = datetime.now()
            if self.foreground_updates:
                print(
                    f"Cache update completed at {self.last_update.strftime('%H:%M:%S')}"
                )

    def _check_for_new_calls(self) -> bool:
        """Check if there are new calls available in the API."""
        headers = {
            "authorization": f"{os.environ['VAPI_API_KEY']}",
            "createdAtGE": (
                datetime.now() - timedelta(minutes=10)
            ).isoformat(),  # Look back 10 minutes
            "limit": "1",  # Only get the latest call
        }
        latest_api_call = httpx.get("https://api.vapi.ai/call", headers=headers).json()

        if not latest_api_call:
            return False

        latest_api_call = parse_call(latest_api_call[0])
        latest_cached_call = get_latest_cached_call()

        # Return True if new calls are available
        return not (latest_cached_call and latest_api_call.id == latest_cached_call.id)

    def _fetch_all_calls(self) -> List[Call]:
        """Fetch all calls from the API."""
        headers = {
            "authorization": f"{os.environ['VAPI_API_KEY']}",
            "createdAtGE": (
                datetime.now() - timedelta(days=365)
            ).isoformat(),  # Get calls from last year
            "limit": "1000",  # Get up to 1000 calls
        }
        response = httpx.get("https://api.vapi.ai/call", headers=headers)
        response.raise_for_status()
        calls_data = response.json()

        calls = [parse_call(c) for c in calls_data]
        return calls

    def _notify_update(self, calls: List[Call]):
        """Notify the app of updated calls."""
        if self.app:
            self.app.post_message(CacheUpdated(calls=calls))


# Global cache update manager - used when no app instance is available
_cache_manager = CacheUpdateManager()


def vapi_calls(
    skip_api_check: bool = False, foreground_updates: bool = False, offline: bool = False
) -> List[Call]:
    """Get all calls, using cache when possible, and handling offline status."""

    network_up = is_network_available()
    effective_offline = offline or not network_up

    logger.debug(
        f"Fetching calls (user offline: {offline}, network available: {network_up}, effective_offline: {effective_offline})..."
    )
    stats = get_cache_stats()
    logger.debug(f"Current cache stats: {stats}")

    # Set up the global cache manager with foreground_updates and effective_offline status
    # Note: The 'offline' param for CacheUpdateManager itself refers to the user flag,
    # its internal methods will use is_network_available for cycles.
    global _cache_manager
    if foreground_updates and not _cache_manager.foreground_updates:
        _cache_manager = CacheUpdateManager(
            foreground_updates=foreground_updates, offline=offline
        ) # Pass user-set offline flag

    cached_calls = get_cached_calls() # Try to get cache first

    if effective_offline:
        if offline and network_up:
            logger.info("Offline mode (flag): Operating with local data only.")
        elif not network_up:
            logger.warning("Network unavailable: Operating with local data only.")

        if cached_calls is not None:
            logger.info(f"Offline/Network down: Serving {len(cached_calls)} calls from cache.")
            return cached_calls
        else:
            logger.warning("Offline/Network down: No cache available. Returning empty list.")
            return []

    # === Online Logic ===
    # If we reach here, effective_offline is False, meaning network is available and user didn't set --offline.
    logger.debug("Online mode: Proceeding with potential API calls.")

    try:
        if cached_calls is not None:
            logger.info(f"Found {len(cached_calls)} calls in cache.")

            if skip_api_check or os.environ.get("SKIP_API_CHECK"):
                logger.info("Skipping API check for new calls (skip_api_check=True). Will update in background if needed.")
                if not _cache_manager.updating: # Avoid multiple concurrent updates
                    threading.Thread(
                        target=lambda: _cache_manager.start_background_update(),
                        daemon=True,
                    ).start()
                return cached_calls

            # Check for newer calls against API
            try:
                logger.debug("Checking for newer calls on API...")
                headers = {
                    "authorization": f"{os.environ['VAPI_API_KEY']}",
                    "createdAtGE": (datetime.now() - timedelta(minutes=10)).isoformat(),
                    "limit": "1",
                }
                latest_api_call_data = httpx.get("https://api.vapi.ai/call", headers=headers).json()

                if latest_api_call_data:
                    latest_api_call_obj = parse_call(latest_api_call_data[0])
                    latest_cached_call_obj = get_latest_cached_call()

                    if latest_cached_call_obj and latest_api_call_obj.id == latest_cached_call_obj.id:
                        logger.info("Cache is up to date. Serving from cache.")
                        return cached_calls
                    else:
                        logger.info("Newer calls detected on API. Refreshing entire cache.")
                else:
                    logger.info("No calls found on API in the recent check window. Cache assumed up to date.")
                    return cached_calls
            except Exception as e:
                logger.warning(f"Error checking for new calls: {e}. Serving from cache as fallback.")
                return cached_calls

        # If cached_calls is None or newer calls were detected, fetch all from API
        logger.info("Fetching all calls from API...")
        headers = {
            "authorization": f"{os.environ['VAPI_API_KEY']}",
            "createdAtGE": (datetime.now() - timedelta(days=365)).isoformat(),
            "limit": "1000",
        }
        response = httpx.get("https://api.vapi.ai/call", headers=headers)
        response.raise_for_status()
        calls_data = response.json()

        calls = [parse_call(c) for c in calls_data]
        logger.info(f"Fetched {len(calls)} calls from API.")

        cache_calls(calls)
        logger.info("Calls cached successfully.")
        return calls

    except Exception as e:
        logger.error(f"Error during API operations: {e}")
        if cached_calls is not None:
            logger.warning("Serving from cache due to API error.")
            return cached_calls
        # If effective_offline was somehow false but we hit an error and have no cache
        # This implies network was initially up, but failed mid-operation.
        logger.error("API error and no cache available. Returning empty list.")
        return []


class SortScreen(ModalScreen):
    """Screen for sorting options."""

    BINDINGS = [
        ("escape,q", "dismiss", "Close"),
        ("t", "sort('time')", "Sort by Time"),
        ("l", "sort('length')", "Sort by Length"),
        ("c", "sort('cost')", "Sort by Cost"),
        ("e", "sort('ended')", "Sort by Ended Reason"),
        ("r", "toggle_reverse", "Toggle Reverse Sort"),
    ]

    CSS = """
    Screen {
        align: center middle;
        background: rgba(26, 27, 38, 0.85);
    }

    #sort-container {
        width: 35;
        height: auto;
        background: #24283b;
        border: tall #414868;
        padding: 1;
    }

    #sort-grid {
        layout: grid;
        grid-size: 1;
        grid-rows: 4;
        grid-gutter: 0;
        padding: 0;
        content-align: center middle;
    }
    
    Button {
        width: 100%;
        height: 1;
        margin: 0;
        background: #1a1b26;
        color: #c0caf5;
        border: none;
        content-align: center middle;
        text-align: center;
    }

    Button:hover {
        background: #364a82;
        color: #7aa2f7;
    }

    Label {
        content-align: center middle;
        width: 100%;
        padding: 0;
        color: #c0caf5;
        text-align: center;
    }

    #sort-label {
        color: #7aa2f7;
        text-style: bold;
        padding-bottom: 1;
    }

    #reverse-label {
        color: #e0af68;
        padding-top: 1;
    }

    #reverse-status {
        color: #9ece6a;
        text-style: bold;
    }
    """

    def __init__(self):
        super().__init__()
        self.reverse_sort = False

    def compose(self) -> ComposeResult:
        with Container(id="sort-container"):
            yield Label("Sort by:", id="sort-label")
            with Grid(id="sort-grid"):
                yield Button("[T]ime", id="time", variant="primary")
                yield Button("[L]ength", id="length")
                yield Button("[C]ost", id="cost")
                yield Button("[E]nded", id="ended")
            yield Label("Press 'R' to toggle sort direction", id="reverse-label")
            yield Label("Sort: Descending", id="reverse-status")

    def action_toggle_reverse(self):
        """Toggle reverse sort order."""
        self.reverse_sort = not self.reverse_sort
        status_label = self.query_one("#reverse-status", Label)
        status_label.update(
            f"Sort: {'Ascending' if self.reverse_sort else 'Descending'}"
        )

    def action_sort(self, column: str):
        """Handle sort action for a column."""
        app = self.app
        if isinstance(app, CallBrowserApp):
            # Convert button ID to column name
            column_map = {
                "time": "time",
                "length": "length",
                "cost": "cost",
                "ended": "ended",
            }
            app.sort_calls(column_map[column], not self.reverse_sort)

        # Reset reverse sort status and dismiss
        self.reverse_sort = False
        status_label = self.query_one("#reverse-status", Label)
        status_label.update("Sort: Descending")
        self.dismiss()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        self.action_sort(event.button.id)

    def on_mount(self) -> None:
        """Reset state when screen is mounted."""
        self.reverse_sort = False
        status_label = self.query_one("#reverse-status", Label)
        status_label.update("Sort: Descending")


class HelpScreen(ModalScreen):
    """Help screen showing available commands."""

    BINDINGS = [("escape,q", "dismiss", "Close")]

    CSS = """
    Screen {
        align: center middle;
        background: rgba(26, 27, 38, 0.85);
    }

    #help-container {
        width: 35;
        background: #24283b;
        border: tall #414868;
        padding: 1;
    }

    #help-title {
        text-align: center;
        padding-bottom: 1;
        color: #7aa2f7;
        text-style: bold;
    }

    #help-content {
        padding: 1;
    }

    .command {
        text-align: left;
        padding-left: 2;
        color: #c0caf5;
    }

    .command:hover {
        color: #7aa2f7;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="help-container"):
            yield Label("Available Commands", id="help-title")
            with Container(id="help-content"):
                yield Label("? - Show help", classes="command")
                yield Label("j/k - Move up/down", classes="command")
                yield Label("h/l - Scroll left/right", classes="command")
                yield Label("v - Edit JSON", classes="command")
                yield Label("s - Sort", classes="command")
                yield Label("r - Refresh calls", classes="command")
                yield Label("q - Quit", classes="command")


class EditScreen(ModalScreen):
    """Screen for editing options."""

    BINDINGS = [
        ("escape,q", "dismiss", "Close"),
        ("f", "edit_fx", "View in fx"),
        ("s", "view_summary", "View Summary"),
        ("c", "view_conversation", "View Conversation"),
        ("v", "view_json", "View JSON in VI"),
        ("m", "toggle_mask_secrets", "Toggle Secret Masking"),
    ]

    CSS = """
    Screen {
        align: center middle;
        background: rgba(26, 27, 38, 0.85);
    }

    #edit-container {
        width: 35;
        height: auto;
        background: #24283b;
        border: tall #414868;
        padding: 1;
    }

    #edit-grid {
        layout: grid;
        grid-size: 1;
        grid-rows: 5;
        grid-gutter: 0;
        padding: 0;
        content-align: center middle;
        height: auto;
    }
    
    Button {
        width: 100%;
        height: 1;
        margin: 0;
        background: #1a1b26;
        color: #c0caf5;
        border: none;
        content-align: center middle;
        text-align: center;
    }

    Button:hover {
        background: #364a82;
        color: #7aa2f7;
    }

    Label {
        content-align: center middle;
        width: 100%;
        padding: 0;
        color: #c0caf5;
        text-align: center;
    }

    #edit-label {
        color: #7aa2f7;
        text-style: bold;
        padding-bottom: 1;
    }

    #mask-status {
        color: #9ece6a;
        text-style: bold;
        padding-bottom: 1;
    }
    """

    def __init__(self, call_data: dict):
        super().__init__()
        self.call_data = call_data
        self.mask_secrets = False

    def _mask_content(self, content: str) -> str:
        """Replace GUIDs and secrets with masked values if masking is enabled."""
        if not self.mask_secrets:
            return content

        import re

        # Pattern matches standard UUID format
        guid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        content = re.sub(
            guid_pattern, "xxx-xxx-xxx-xxx-xxx", content, flags=re.IGNORECASE
        )

        # Mask secrets in JSON content
        try:
            # Only attempt JSON parsing if it looks like JSON
            if "{" in content and "}" in content:
                data = json.loads(content)
                self._mask_secrets_recursive(data)
                return json.dumps(data, indent=2, default=str)
        except json.JSONDecodeError:
            pass

        return content

    def _mask_secrets_recursive(self, obj):
        """Recursively mask any values where the key is 'secret' or ends with 'CallId' or 'ProviderId'."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if (
                    key.lower() == "secret"
                    or key.endswith("CallId")
                    or key.endswith("ProviderId")
                ):
                    obj[key] = "secret-masked"
                elif isinstance(value, (dict, list)):
                    self._mask_secrets_recursive(value)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    self._mask_secrets_recursive(item)

    def _write_temp_file(self, content: str, suffix: str = ".json") -> str:
        """Write content to a temporary file and return its path."""
        try:
            content = self._mask_content(content)
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=suffix, delete=False
            ) as temp:
                temp.write(content)
                return temp.name
        except Exception as e:
            logger.error(f"Error writing temporary file: {e}")
            raise

    def compose(self) -> ComposeResult:
        with Container(id="edit-container"):
            yield Label("View Options (press q to close):", id="edit-label")
            yield Label("Secret Masking: Off", id="mask-status")
            with Grid(id="edit-grid"):
                yield Button("[F]x View", id="fx", variant="primary")
                yield Button("[S]ummary", id="summary")
                yield Button("[C]onversation", id="conversation")
                yield Button("[V]iew JSON", id="view_json")
                yield Button("[M]ask Secrets", id="mask_secrets")

    def action_toggle_mask_secrets(self):
        """Toggle secret masking on/off."""
        self.mask_secrets = not self.mask_secrets
        status_label = self.query_one("#mask-status", Label)
        status_label.update(f"Secret Masking: {'On' if self.mask_secrets else 'Off'}")

    def _run_external_command(self, command: str):
        """Run an external command with proper terminal handling."""
        try:
            # Remove focus to restore terminal to cooked mode
            self.app.set_focus(None)
            # Run in new tmux window with 'q to close' in title
            os.system(f'tmux new-window -n "q to close" "{command}"')
        except Exception as e:
            logger.error(f"Error running command: {e}")
        finally:
            # Restore focus to put terminal back in raw mode
            self.app.set_focus(self)

    def _get_editor(self):
        """Get the editor command from $EDITOR environment variable or fallback to vi."""
        return os.environ.get("EDITOR", "vi")

    def action_edit_fx(self):
        """Open the raw JSON in fx"""
        temp_path = self._write_temp_file(
            json.dumps(self.call_data, indent=2, default=str)
        )
        self._run_external_command(f"fx {temp_path}")

    def action_view_summary(self):
        """Edit the summary in vi"""
        summary = self.call_data.get("analysis", {}).get(
            "summary", "No summary available"
        )
        temp_path = self._write_temp_file(summary, ".txt")
        editor = self._get_editor()
        self._run_external_command(f"{editor} {temp_path}")

    def action_view_conversation(self):
        """Edit the full conversation in vi"""
        transcript = self.call_data.get("artifact", {}).get(
            "transcript", "No transcript available"
        )
        temp_path = self._write_temp_file(transcript, ".vapi_transcript.txt")
        editor = self._get_editor()
        self._run_external_command(f"{editor} {temp_path}")

    def action_view_json(self):
        """View the entire call JSON in VI"""
        temp_path = self._write_temp_file(
            json.dumps(self.call_data, indent=2, default=str)
        )
        editor = self._get_editor()
        self._run_external_command(f"{editor} {temp_path}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        button_id = event.button.id
        if button_id == "fx":
            self.action_edit_fx()
        elif button_id == "summary":
            self.action_view_summary()
        elif button_id == "conversation":
            self.action_view_conversation()
        elif button_id == "view_json":
            self.action_view_json()
        elif button_id == "mask_secrets":
            self.action_toggle_mask_secrets()


class TranscriptView(Static):
    """Handle transcript display and coloring"""

    def __init__(self):
        super().__init__("Select a call to view transcript", id="transcript")
        self.can_focus = False
        self.markup = True

    def update_transcript(self, transcript: str):
        """Update and colorize the transcript"""
        if not transcript.strip():
            self.update("[#414868]<no transcript>[/]")
            return

        # Colorize the transcript
        transcript_lines = transcript.split("\n")
        colored_lines = []
        for line in transcript_lines:
            if line.strip().startswith("AI:") or line.strip().startswith("Tony:"):
                prefix, rest = line.split(":", 1)
                colored_lines.append(f"[#7aa2f7]{prefix}:[/][#9ece6a]{rest}[/]")
            elif line.strip().startswith("User:") or line.strip().startswith("Igor:"):
                prefix, rest = line.split(":", 1)
                colored_lines.append(f"[#e0af68]{prefix}:[/][#f7768e]{rest}[/]")
            else:
                colored_lines.append(line)

        colored_transcript = "\n".join(colored_lines)
        self.update(colored_transcript)


class CallDetailsView(Static):
    """Handle call details display"""

    def __init__(self):
        super().__init__("Select a call to view details", id="details")
        self.styles.width = "50%"
        self.can_focus = False
        self.markup = True

    def update_details(self, call: Call):
        """Update the details view with call information"""
        length_seconds = call.length_in_seconds()
        minutes = int(length_seconds // 60)
        seconds = int(length_seconds % 60)
        length_str = f"{minutes}:{seconds:02d}"

        details_text = f"""[#7aa2f7]Start:[/] {call.Start.strftime("%Y-%m-%d %H:%M")}
[#e0af68]Length:[/] {length_str}
[#9ece6a]Cost:[/] ${call.Cost:.2f}
[#bb9af7]Caller:[/] {format_phone_number(call.Caller)}
[#f7768e]Ended:[/] {call.EndedReason or "Unknown"}

{call.Summary}"""
        self.update(details_text)


class CallTable(DataTable):
    """Handle call list display and sorting"""

    def __init__(self):
        super().__init__(id="calls")
        self.styles.width = "50%"
        self.cursor_type = "row"
        self.can_focus = True

        # Add columns
        self.add_column("Time")
        self.add_column("Length")
        self.add_column("Cost")
        self.add_column("Ended")

    def load_calls(self, calls: List[Call]):
        """Load calls into the table"""
        self.clear()
        for call in calls:
            start = call.Start.strftime("%Y-%m-%d %H:%M")
            length_seconds = call.length_in_seconds()
            minutes = int(length_seconds // 60)
            seconds = int(length_seconds % 60)
            length = f"{minutes}:{seconds:02d}"
            self.add_row(
                start,
                length,
                f"${call.Cost:.2f}",
                call.EndedReason or "Unknown",
                key=call.id,
            )

    def sort_calls(self, calls: List[Call], column: str, reverse: bool = False):
        """Sort calls by the specified column"""
        if column == "time":
            calls.sort(key=lambda x: x.Start, reverse=reverse)
        elif column == "length":
            calls.sort(key=lambda x: x.length_in_seconds(), reverse=reverse)
        elif column == "cost":
            calls.sort(key=lambda x: x.Cost, reverse=reverse)
        elif column == "ended":
            calls.sort(key=lambda x: x.EndedReason or "", reverse=reverse)
        self.load_calls(calls)


class CacheStatusWidget(Static):
    """Widget showing cache status and last update time."""

    def __init__(self):
        super().__init__("Cache: Loading...", id="cache-status")
        self.last_update = None
        self.styles.width = "auto"
        self.styles.min_width = "30"
        self.markup = True

    def set_status(
        self,
        status_text: str = "up to date",
        updating: bool = False,
        user_offline: bool = False,
        network_down: bool = False,
    ):
        """Update the cache status display."""
        if user_offline:
            self.update("[orange3]Status: Offline (user set)[/orange3]")
        elif network_down:
            self.update("[red]Status: Offline (network down)[/red]")
        elif updating:
            self.update("[yellow]Cache: updating...[/yellow]")
        else:
            time_str = (
                "(never)"
                if not self.last_update
                else self.last_update.strftime("%H:%M:%S")
            )
            self.update(
                f"[green]Cache: {status_text}[/green] ([blue]updated: {time_str}[/blue])"
            )
            # Only update last_update time if it's a genuine cache status update, not an offline message
            if not user_offline and not network_down and not updating:
                 self.last_update = datetime.now()


class CallBrowserApp(App):
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("j", "move_down", "Down"),
        Binding("k", "move_up", "Up"),
        Binding("down", "move_down", "Down"),
        Binding("up", "move_up", "Up"),
        Binding("g,g", "move_top", "Top"),
        Binding("G", "move_bottom", "Bottom"),
        Binding("tab", "focus_next", "Next Widget"),
        Binding("shift+tab", "focus_previous", "Previous Widget"),
        Binding("?", "help", "Help"),
        Binding("v", "edit_json", "Edit JSON"),
        Binding("s", "sort", "Sort"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "focus_next", "Next Widget"),
        Binding("h", "scroll_left", "Scroll Left"),
        Binding("l", "scroll_right", "Scroll Right"),
    ]

    CSS = """
    Screen {
        background: #1a1b26;
    }

    .top-container {
        height: 50vh;
    }
    
    .toolbar {
        dock: top;
        height: 1;
        width: 100%;
        background: #24283b;
        border-bottom: solid #414868;
        padding: 0 1;
    }
    
    #refresh-button {
        border: none;
        min-width: 15;
        background: #364a82;
        color: #c0caf5;
        height: 1;
        margin-left: 1;
    }
    
    #refresh-button:hover {
        background: #7aa2f7;
        color: #1a1b26;
    }
    
    #cache-status {
        background: #24283b;
        color: #c0caf5;
        height: 1;
    }

    #transcript-container {
        height: 50vh;
        border: solid #414868;
        background: #24283b;
        overflow-y: scroll;
        scrollbar-size: 1 1;
        padding: 0;
    }
    
    #transcript-container:focus-within {
        border: double #7aa2f7;
    }
    
    #transcript {
        width: 100%;
        padding: 0 1;
        margin: 0;
    }
    
    #details {
        border: solid #414868;
        background: #24283b;
        overflow-y: scroll;
        padding: 0 1;
        height: 100%;
    }
    
    #details:focus {
        border: double #7aa2f7;
    }
    
    #calls {
        border: solid #414868;
        background: #24283b;
        color: #c0caf5;
        scrollbar-size: 1 1;
        height: 100%;
    }
    
    #calls:focus {
        border: double #7aa2f7;
    }

    DataTable > .datatable--header {
        background: #1a1b26;
        color: #7aa2f7;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #364a82;
        color: #c0caf5;
    }

    DataTable > .datatable--hover {
        background: #283457;
    }
    """

    def on_mount(self) -> None:
        """Called when app is mounted"""
        logger.info(f"App mounted, bindings: {self.BINDINGS}")
        self.network_available = is_network_available() # Initial network check

        # Select first row on load if there are any calls
        if self.calls and len(self.calls) > 0:
            self.call_table.move_cursor(row=0)
            self.call_table.action_select_cursor()
            self._update_views_for_current_row()
            # Set initial focus to call table
            self.set_focus(self.call_table)

        # Set up cache status
        self.cache_status.set_status(
            user_offline=self.offline,
            network_down=not self.network_available,
            status_text=f"loaded ({len(self.calls)} calls)"
        )

        # Set up refresh timer for periodic background updates
        self._setup_refresh_timer()

        # Do a first background refresh a few seconds after loading
        self.set_timer(3, self.action_refresh)

    def __init__(self, foreground_updates=False, offline: bool = False):
        super().__init__()
        self.offline = offline # User-set offline flag
        self.network_available = True # Initial assumption, will be checked in on_mount & refresh
        # Create cache manager for background updates
        self.cache_manager = CacheUpdateManager(
            self, foreground_updates=foreground_updates, offline=self.offline
        )

        # Initial load - skip API check for fast startup
        self.calls = vapi_calls(
            skip_api_check=True, foreground_updates=foreground_updates, offline=self.offline
        )
        logger.info(f"Loaded {len(self.calls)} calls")
        self.current_call = None

        # Set up periodic background refresh (every 5 minutes)
        self.refresh_timer = None

    def on_cache_updated(self, event: CacheUpdated):
        """Handle cache updated event from background thread."""
        logger.info(f"Received cache update with {len(event.calls)} calls")

        # Remember current position and selection
        current_row = (
            self.call_table.cursor_row if hasattr(self, "call_table") else None
        )
        current_id = None
        if current_row is not None and 0 <= current_row < len(self.calls):
            current_id = self.calls[current_row].id

        # Update calls list with new data
        self.calls = event.calls

        # Update the table with new data
        if hasattr(self, "call_table"):
            self.call_table.load_calls(self.calls)

        # Restore selection if possible
        if current_id and hasattr(self, "call_table"):
            for i, call in enumerate(self.calls):
                if call.id == current_id:
                    self.call_table.move_cursor(row=i)
                    self.call_table.action_select_cursor()
                    self._update_views_for_current_row()
                    break

        # Update the cache status
        if hasattr(self, "cache_status"):
            self.network_available = is_network_available() # Re-check network
            self.cache_status.set_status(
                user_offline=self.offline,
                network_down=not self.network_available,
                status_text=f"updated ({len(self.calls)} calls)"
            )

    def action_refresh(self):
        """Manually refresh calls data."""
        self.network_available = is_network_available() # Check network before refresh

        if hasattr(self, "cache_status"):
            self.cache_status.set_status(
                updating=not (self.offline or not self.network_available), # Only show "updating" if actually trying
                user_offline=self.offline,
                network_down=not self.network_available
            )

        # Start an update (background or foreground depending on settings)
        # CacheUpdateManager will internally respect self.offline and network status
        self.cache_manager.start_background_update()

    def _setup_refresh_timer(self):
        """Set up a periodic refresh timer."""
        if self.refresh_timer:
            self.refresh_timer.stop()

        # Check for updates every 5 minutes
        self.refresh_timer = self.set_interval(300, self.action_refresh)

    def compose(self) -> ComposeResult:
        """Create the UI layout"""
        with Container():
            # Add a toolbar with cache status and refresh button
            with Horizontal(classes="toolbar"):
                self.cache_status = CacheStatusWidget()
                yield self.cache_status
                yield Button("Refresh [R]", id="refresh-button")

            with Horizontal(classes="top-container"):
                self.call_table = CallTable()
                self.call_table.load_calls(self.calls)
                yield self.call_table

                self.details = CallDetailsView()
                yield self.details

            with ScrollableContainer(id="transcript-container") as container:
                container.can_focus = True
                self.transcript = TranscriptView()
                yield self.transcript

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "refresh-button":
            self.action_refresh()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in the data table."""
        ic("Row selected event:", event)
        ic("Current cursor row:", self.call_table.cursor_row)
        if self.call_table.cursor_row is not None:
            self.current_call = self.calls[self.call_table.cursor_row]
            self._update_views_for_current_row()

    def action_move_down(self):
        """Move down in the focused pane"""
        if self.focused == self.call_table:
            self.call_table.action_cursor_down()
            if self.call_table.cursor_row is not None:
                self.call_table.action_select_cursor()
            self._update_views_for_current_row()
        elif self.focused == self.query_one("#transcript-container"):
            container = self.query_one("#transcript-container")
            container.scroll_down(animate=False)

    def action_move_up(self):
        """Move up in the focused pane"""
        if self.focused == self.call_table:
            self.call_table.action_cursor_up()
            if self.call_table.cursor_row is not None:
                self.call_table.action_select_cursor()
            self._update_views_for_current_row()
        elif self.focused == self.query_one("#transcript-container"):
            container = self.query_one("#transcript-container")
            container.scroll_up(animate=False)

    def action_help(self):
        """Show help screen when ? is pressed."""
        self.push_screen(HelpScreen())

    def sort_calls(self, column: str, reverse: bool = False):
        """Sort calls and update the UI."""
        logger.debug(f"Sorting by {column} (reverse={reverse})")
        self.call_table.sort_calls(self.calls, column, reverse)

        # Update cursor and views
        self.call_table.move_cursor(row=0)
        self.call_table.action_select_cursor()
        self._update_views_for_current_row()

    async def action_sort(self):
        """Show sort column selection screen"""
        logger.debug("Opening sort screen")
        screen = SortScreen()
        await self.push_screen(screen)

    def action_edit_json(self):
        """Show edit options modal"""
        selected_row = self.call_table.cursor_row
        if selected_row is None:
            logger.warning("No row selected")
            return

        try:
            call = self.calls[selected_row]
            call_id = call.id

            headers = {
                "authorization": f"{os.environ['VAPI_API_KEY']}",
            }
            response = httpx.get(f"https://api.vapi.ai/call/{call_id}", headers=headers)
            raw_call = response.json()

            self.push_screen(EditScreen(raw_call))

        except Exception as e:
            logger.error(f"Error opening edit options: {e}")

    def _update_views_for_current_row(self):
        """Update both details and transcript for current row"""
        selected_row = self.call_table.cursor_row
        ic("Updating views for row:", selected_row)

        if selected_row is None:
            ic("No row selected")
            return

        try:
            call = self.calls[selected_row]
            ic("Found call:", call.id)

            self.details.update_details(call)
            self.transcript.update_transcript(call.Transcript)

        except Exception as e:
            logger.error(f"Error updating views: {e}")
            ic("Error updating views:", str(e))
            self.details.update(f"Error loading call details: {str(e)}")
            self.transcript.update(f"Error loading transcript: {str(e)}")

    def action_move_top(self):
        """Move to top of the focused pane"""
        if self.focused == self.call_table:
            self.call_table.move_cursor(row=0)
            self.call_table.action_select_cursor()
            self._update_views_for_current_row()
        elif self.focused == self.query_one("#transcript-container"):
            container = self.query_one("#transcript-container")
            container.scroll_home(animate=False)

    def action_move_bottom(self):
        """Move to bottom of the focused pane"""
        if self.focused == self.call_table:
            last_row = len(self.calls) - 1
            self.call_table.move_cursor(row=last_row)
            self.call_table.action_select_cursor()
            self._update_views_for_current_row()
        elif self.focused == self.query_one("#transcript-container"):
            container = self.query_one("#transcript-container")
            container.scroll_end(animate=False)

    def action_focus_next(self):
        """Handle tab key to move focus between widgets"""
        if self.focused == self.call_table:
            container = self.query_one("#transcript-container")
            self.set_focus(container)
            # Select the current row when moving focus
            if self.call_table.cursor_row is not None:
                self.call_table.action_select_cursor()
                self._update_views_for_current_row()
        else:
            self.set_focus(self.call_table)

    def action_focus_previous(self):
        """Handle shift+tab to move focus between widgets in reverse"""
        if self.focused == self.call_table:
            container = self.query_one("#transcript-container")
            self.set_focus(container)
            # Select the current row when moving focus
            if self.call_table.cursor_row is not None:
                self.call_table.action_select_cursor()
                self._update_views_for_current_row()
        else:
            self.set_focus(self.call_table)

    def on_key(self, event) -> None:
        """Handle raw key events before they are processed by widgets."""
        if event.key == "enter":
            event.prevent_default()  # Stop the key from being handled by the widget
            self.action_focus_next()
        elif event.key == "up" or event.key == "down":
            event.prevent_default()  # Stop arrow keys from being handled by the widget
            if event.key == "up":
                self.action_move_up()
            else:
                self.action_move_down()
        elif self.focused == self.call_table and event.key in ("h", "l"):
            event.prevent_default()  # Stop h/l from being handled by other widgets
            if event.key == "h":
                self.call_table.scroll_left()
            else:
                self.call_table.scroll_right()


@app.command()
def browse(
    foreground_updates: bool = False,
    offline: bool = Option(False, "--offline", help="Run in offline mode, relying only on cached data.")
):
    """
    Browse calls in an interactive TUI

    Args:
        foreground_updates: If True, updates will run in the foreground with visible output
        offline: If True, run in offline mode, relying only on cached data.
    """
    app = CallBrowserApp(foreground_updates=foreground_updates, offline=offline)
    app.run()


@logger.catch()
def app_wrap_loguru():
    app()


if __name__ == "__main__":
    app_wrap_loguru()
