import pytest
from datetime import datetime
from dateutil import tz
from calls import (
    parse_call,
    format_phone_number,
    Call,
    CallBrowserApp,
    HelpScreen,
    EditScreen,
)
from textual.widgets import Label
import json


@pytest.fixture
def sample_call():
    """Create a sample call for testing"""
    return Call(
        id="test-id",
        Caller="1234567890",
        Transcript="Tony: Hello\nIgor: Hi",
        Summary="Test summary",
        Start=datetime(2024, 1, 15, 14, 30, tzinfo=tz.tzutc()),
        End=datetime(2024, 1, 15, 14, 35, tzinfo=tz.tzutc()),
        Cost=1.23,
        CostBreakdown={"transcription": 0.5, "analysis": 0.73},
    )


@pytest.fixture
def long_transcript_call():
    """Create a sample call with a long transcript for testing scrolling"""
    # Create a transcript that's definitely longer than the viewport
    lines = []
    for i in range(100):
        if i % 2 == 0:
            lines.append(f"Tony: Line {i}")
        else:
            lines.append(f"Igor: Line {i}")

    return Call(
        id="test-id",
        Caller="1234567890",
        Transcript="\n".join(lines),
        Summary="Test summary",
        Start=datetime(2024, 1, 15, 14, 30, tzinfo=tz.tzutc()),
        End=datetime(2024, 1, 15, 14, 35, tzinfo=tz.tzutc()),
        Cost=1.23,
        CostBreakdown={"transcription": 0.5, "analysis": 0.73},
    )


def test_format_phone_number():
    """Test phone number formatting"""
    assert format_phone_number("1234567890") == "(123)456-7890"
    assert format_phone_number("+11234567890") == "(123)456-7890"
    assert format_phone_number("123-456-7890") == "(123)456-7890"
    assert (
        format_phone_number("invalid") == "invalid"
    )  # Returns original if can't format
    assert format_phone_number("12345") == "12345"  # Returns original if too short


def test_parse_call():
    """Test parsing a call from API response"""
    sample_call = {
        "id": "test-id",
        "customer": {"number": "1234567890"},
        "createdAt": "2024-01-15T14:30:00.000Z",
        "endedAt": "2024-01-15T14:35:00.000Z",
        "artifact": {"transcript": "Sample transcript"},
        "analysis": {"summary": "Sample summary"},
        "cost": 1.23,
        "costBreakdown": {"transcription": 0.5, "analysis": 0.73},
    }

    call = parse_call(sample_call)

    assert isinstance(call, Call)
    assert call.id == "test-id"
    assert call.Caller == "1234567890"
    assert call.Transcript == "Sample transcript"
    assert call.Summary == "Sample summary"
    assert call.Cost == 1.23
    assert isinstance(call.Start, datetime)
    assert isinstance(call.End, datetime)
    assert call.Start.tzinfo is not None  # Should be timezone-aware
    assert call.End.tzinfo is not None

    # Test length calculation
    length = call.length_in_seconds()
    assert length == 300.0  # 5 minutes = 300 seconds


@pytest.mark.asyncio
async def test_pane_navigation(sample_call):
    """Test navigation between widgets"""
    app = CallBrowserApp()
    app.calls = [sample_call]  # Use sample call for testing

    async with app.run_test() as pilot:
        # Test initial focus
        assert app.focused == app.call_table

        # Test tab navigation
        await pilot.press("tab")
        await pilot.pause()
        transcript_container = app.query_one("#transcript-container")
        assert app.focused == transcript_container

        await pilot.press("tab")
        await pilot.pause()
        assert app.focused == app.call_table

        # Test reverse tab navigation
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.focused == transcript_container

        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.focused == app.call_table


@pytest.mark.asyncio
async def test_pane_scrolling(sample_call):
    """Test scrolling behavior in different widgets"""
    app = CallBrowserApp()
    app.calls = [sample_call]

    async with app.run_test() as pilot:
        # Test call table navigation
        await pilot.press("j")  # Move down
        assert app.call_table.cursor_row == 0  # Only one row
        await pilot.press("k")  # Move up
        assert app.call_table.cursor_row == 0

        # Test transcript scrolling
        await pilot.press("tab")  # Focus transcript container
        await pilot.pause()
        transcript_container = app.query_one("#transcript-container")
        assert app.focused == transcript_container

        # Test scroll commands
        await pilot.press("g")  # Top
        await pilot.press("g")
        await pilot.press("G")  # Bottom
        await pilot.press("j")  # Down
        await pilot.press("k")  # Up


@pytest.mark.asyncio
async def test_focus_indicators(sample_call):
    """Test that focus is visually indicated"""
    app = CallBrowserApp()
    app.calls = [sample_call]

    async with app.run_test() as pilot:
        # Check initial focus border
        call_table = app.query_one("#calls")
        assert call_table.styles.border_top[0] == "double"

        # Check focus change updates borders
        await pilot.press("tab")
        transcript_container = app.query_one("#transcript-container")
        assert transcript_container.styles.border_top[0] == "double"
        assert call_table.styles.border_top[0] == "solid"

        # Verify details pane never gets focus border
        details = app.query_one("#details")
        assert not details.can_focus


def test_parse_call_missing_fields():
    """Test parsing a call with missing optional fields"""
    minimal_call = {
        "id": "test-id",
        "createdAt": "2024-01-15T14:30:00.000Z",
    }

    call = parse_call(minimal_call)

    assert call.id == "test-id"
    assert call.Caller == ""  # Empty string for missing customer
    assert call.Transcript == ""  # Empty string for missing transcript
    assert call.Summary == ""  # Empty string for missing summary
    assert call.Cost == 0.0  # Zero for missing cost
    assert isinstance(call.Start, datetime)
    assert isinstance(call.End, datetime)
    assert call.Start == call.End  # End time defaults to start time


def test_parse_call_cost_formats():
    """Test parsing different cost formats"""
    # Test numeric cost
    call_numeric = parse_call(
        {"id": "test", "createdAt": "2024-01-15T14:30:00.000Z", "cost": 1.23}
    )
    assert call_numeric.Cost == 1.23

    # Test dictionary cost
    call_dict = parse_call(
        {"id": "test", "createdAt": "2024-01-15T14:30:00.000Z", "cost": {"total": 2.34}}
    )
    assert call_dict.Cost == 2.34

    # Test missing cost
    call_no_cost = parse_call({"id": "test", "createdAt": "2024-01-15T14:30:00.000Z"})
    assert call_no_cost.Cost == 0.0


@pytest.mark.asyncio
async def test_transcript_scrolling(long_transcript_call):
    """Test scrolling behavior in transcript widget"""
    app = CallBrowserApp()
    app.calls = [long_transcript_call]

    async with app.run_test() as pilot:
        # Focus the transcript container directly
        await pilot.press("tab")
        await pilot.pause()
        container = app.query_one("#transcript-container")
        assert app.focused == container

        # Get initial scroll position
        initial_scroll_y = container.scroll_y

        # Scroll down multiple times
        for _ in range(5):
            await pilot.press("j")
        assert container.scroll_y > initial_scroll_y

        # Scroll up
        current_scroll_y = container.scroll_y
        for _ in range(3):
            await pilot.press("k")
        assert container.scroll_y < current_scroll_y

        # Test gg (top)
        await pilot.press("g")
        await pilot.press("g")
        assert container.scroll_y == 0

        # Test G (bottom)
        await pilot.press("G")
        assert container.scroll_y > 0  # Should be scrolled down

        # Verify we can scroll up from bottom
        current_scroll_y = container.scroll_y
        await pilot.press("k")
        assert container.scroll_y < current_scroll_y


@pytest.mark.asyncio
async def test_help_screen_dismiss():
    """Test that help screen dismisses on both escape and q, but q doesn't quit the app"""
    app = CallBrowserApp()

    async with app.run_test() as pilot:
        # Open help screen
        await pilot.press("?")
        await pilot.pause()

        # Verify help screen is shown
        help_screen = app.query_one(HelpScreen)
        assert help_screen is not None

        # Press 'q' - should dismiss help screen but not quit app
        await pilot.press("q")
        await pilot.pause()

        # Verify help screen is dismissed
        help_screen = app.query(HelpScreen)
        assert len(help_screen) == 0

        # Verify app is still running (can open help screen again)
        await pilot.press("?")
        await pilot.pause()
        help_screen = app.query_one(HelpScreen)
        assert help_screen is not None

        # Press escape - should also dismiss
        await pilot.press("escape")
        await pilot.pause()
        help_screen = app.query(HelpScreen)
        assert len(help_screen) == 0


@pytest.mark.asyncio
async def test_enter_key_navigation(sample_call):
    """Test that Enter key behaves like Tab for widget focus navigation."""
    app = CallBrowserApp()
    app.calls = [sample_call]  # Use sample call for testing

    async with app.run_test() as pilot:
        # Test initial focus
        assert app.focused == app.call_table

        # Test enter navigation
        await pilot.press("enter")
        await pilot.pause()  # Add pause to allow focus change to complete
        transcript_container = app.query_one("#transcript-container")
        assert app.focused == transcript_container

        await pilot.press("enter")
        await pilot.pause()  # Add pause to allow focus change to complete
        assert app.focused == app.call_table

        # Verify it behaves the same as tab
        await pilot.press("tab")
        await pilot.pause()  # Add pause to allow focus change to complete
        assert app.focused == transcript_container

        await pilot.press("tab")
        await pilot.pause()  # Add pause to allow focus change to complete
        assert app.focused == app.call_table


@pytest.mark.asyncio
async def test_arrow_key_navigation():
    """Test that arrow keys behave the same as j/k for navigation"""
    app = CallBrowserApp()
    # Create two calls with different IDs
    call1 = Call(
        id="test-id-1",
        Caller="1234567890",
        Transcript="Tony: Hello\nIgor: Hi",
        Summary="Test summary 1",
        Start=datetime(2024, 1, 15, 14, 30, tzinfo=tz.tzutc()),
        End=datetime(2024, 1, 15, 14, 35, tzinfo=tz.tzutc()),
        Cost=1.23,
        CostBreakdown={"transcription": 0.5, "analysis": 0.73},
    )
    call2 = Call(
        id="test-id-2",
        Caller="1234567890",
        Transcript="Tony: Hello again\nIgor: Hi again",
        Summary="Test summary 2",
        Start=datetime(2024, 1, 15, 14, 40, tzinfo=tz.tzutc()),
        End=datetime(2024, 1, 15, 14, 45, tzinfo=tz.tzutc()),
        Cost=1.23,
        CostBreakdown={"transcription": 0.5, "analysis": 0.73},
    )
    app.calls = [call1, call2]

    async with app.run_test() as pilot:
        # Test initial state
        assert app.call_table.cursor_row == 0
        assert (
            app.transcript.renderable
            == "[#7aa2f7]Tony:[/][#9ece6a] Hello[/]\n[#e0af68]Igor:[/][#f7768e] Hi[/]"
        )

        # Test down arrow
        await pilot.press("down")
        await pilot.pause()
        assert app.call_table.cursor_row == 1
        assert (
            app.transcript.renderable
            == "[#7aa2f7]Tony:[/][#9ece6a] Hello again[/]\n[#e0af68]Igor:[/][#f7768e] Hi again[/]"
        )

        # Test up arrow
        await pilot.press("up")
        await pilot.pause()
        assert app.call_table.cursor_row == 0
        assert (
            app.transcript.renderable
            == "[#7aa2f7]Tony:[/][#9ece6a] Hello[/]\n[#e0af68]Igor:[/][#f7768e] Hi[/]"
        )

        # Test that j/k and arrow keys move to the same rows
        await pilot.press("j")
        await pilot.pause()
        j_row = app.call_table.cursor_row
        await pilot.press("k")
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        down_row = app.call_table.cursor_row
        assert j_row == down_row == 1  # Both should move to row 1

        await pilot.press("up")
        await pilot.pause()
        up_row = app.call_table.cursor_row
        await pilot.press("j")
        await pilot.pause()
        await pilot.press("k")
        await pilot.pause()
        k_row = app.call_table.cursor_row
        assert up_row == k_row == 0  # Both should move to row 0


@pytest.mark.asyncio
async def test_empty_transcript_placeholder():
    """Test that empty transcripts show a placeholder message"""
    app = CallBrowserApp()
    # Create a call with no transcript
    call_no_transcript = Call(
        id="test-id-empty",
        Caller="1234567890",
        Transcript="",
        Summary="Test summary",
        Start=datetime(2024, 1, 15, 14, 30, tzinfo=tz.tzutc()),
        End=datetime(2024, 1, 15, 14, 35, tzinfo=tz.tzutc()),
        Cost=1.23,
        CostBreakdown={"transcription": 0.5, "analysis": 0.73},
    )
    app.calls = [call_no_transcript]

    async with app.run_test():  # Remove pilot variable since it's not used
        # Verify placeholder is shown
        assert app.transcript.renderable == "[#414868]<no transcript>[/]"


@pytest.mark.asyncio
async def test_sort_updates_views():
    """Test that sorting updates the transcript and details views"""
    app = CallBrowserApp()
    # Create two calls with different timestamps and transcripts
    call1 = Call(
        id="test-id-1",
        Caller="1234567890",
        Transcript="Tony: First call\nIgor: Hi",
        Summary="First summary",
        Start=datetime(2024, 1, 15, 14, 30, tzinfo=tz.tzutc()),
        End=datetime(2024, 1, 15, 14, 35, tzinfo=tz.tzutc()),
        Cost=1.23,
        CostBreakdown={"transcription": 0.5, "analysis": 0.73},
    )
    call2 = Call(
        id="test-id-2",
        Caller="1234567890",
        Transcript="Tony: Second call\nIgor: Hello",
        Summary="Second summary",
        Start=datetime(2024, 1, 15, 14, 40, tzinfo=tz.tzutc()),
        End=datetime(2024, 1, 15, 14, 45, tzinfo=tz.tzutc()),
        Cost=2.34,
        CostBreakdown={"transcription": 1.0, "analysis": 1.34},
    )
    app.calls = [call1, call2]

    async with app.run_test() as pilot:
        # Initial state should show first call
        assert "First call" in app.transcript.renderable
        assert "First summary" in app.details.renderable

        # Open sort screen
        await pilot.press("s")
        await pilot.pause()

        # Sort by cost (should put call2 first)
        await pilot.press("c")
        await pilot.pause()

        # Verify views updated to show the new first call
        assert "Second call" in app.transcript.renderable
        assert "Second summary" in app.details.renderable
        assert app.call_table.cursor_row == 0


@pytest.mark.asyncio
async def test_secret_masking_toggle():
    """Test that secret masking can be toggled on and off."""
    app = CallBrowserApp()
    # Create a sample call with a GUID and secret
    sample_data = {
        "id": "984bf60e-c2e9-4677-9122-868a4ce1e6ff",
        "secret": "super-secret-value",
        "analysis": {"summary": "Test summary"},
        "artifact": {"transcript": "Test transcript"},
    }

    edit_screen = EditScreen(sample_data)

    async with app.run_test() as pilot:
        # Push the edit screen
        app.push_screen(edit_screen)
        await pilot.pause()

        # Check initial state
        status_label = edit_screen.query_one("#mask-status", Label)
        assert "Off" in status_label.renderable
        assert not edit_screen.mask_secrets

        # Test toggle via keyboard
        await pilot.press("m")
        await pilot.pause()
        assert "On" in status_label.renderable
        assert edit_screen.mask_secrets

        # Test toggle again via keyboard
        await pilot.press("m")
        await pilot.pause()
        assert "Off" in status_label.renderable
        assert not edit_screen.mask_secrets


@pytest.mark.asyncio
async def test_guid_masking():
    """Test that GUIDs are properly masked when secret masking is enabled."""
    app = CallBrowserApp()
    # Sample data with multiple GUIDs in different formats
    sample_data = {
        "id": "984bf60e-c2e9-4677-9122-868a4ce1e6ff",
        "related_id": "ABCDEF12-C2E9-4677-9122-868A4CE1E6FF",  # Upper case
        "another_id": "00000000-0000-0000-0000-000000000000",  # All zeros
        "analysis": {
            "summary": "Test summary with guid: 984bf60e-c2e9-4677-9122-868a4ce1e6ff"
        },
        "artifact": {"transcript": "Test transcript"},
    }

    edit_screen = EditScreen(sample_data)

    async with app.run_test() as pilot:
        app.push_screen(edit_screen)
        await pilot.pause()

        # Enable masking
        await pilot.press("m")
        await pilot.pause()

        # Test masking in JSON content
        masked_content = edit_screen._mask_content(json.dumps(sample_data, indent=2))

        # Verify all GUIDs are masked
        assert "984bf60e-c2e9-4677-9122-868a4ce1e6ff" not in masked_content
        assert "ABCDEF12-C2E9-4677-9122-868A4CE1E6FF" not in masked_content
        assert "00000000-0000-0000-0000-000000000000" not in masked_content

        # Verify mask format
        assert "xxx-xxx-xxx-xxx-xxx" in masked_content

        # Count occurrences of masked GUIDs
        assert (
            masked_content.count("xxx-xxx-xxx-xxx-xxx") == 4
        )  # Should be 4 GUIDs total


@pytest.mark.asyncio
async def test_masking_persistence():
    """Test that secret masking state persists across different view actions."""
    app = CallBrowserApp()
    sample_data = {
        "id": "984bf60e-c2e9-4677-9122-868a4ce1e6ff",
        "secret": "top-secret",
        "analysis": {
            "summary": "Test summary with guid: 984bf60e-c2e9-4677-9122-868a4ce1e6ff"
        },
        "artifact": {
            "transcript": "Test transcript with guid: 984bf60e-c2e9-4677-9122-868a4ce1e6ff"
        },
    }

    edit_screen = EditScreen(sample_data)

    async with app.run_test() as pilot:
        app.push_screen(edit_screen)
        await pilot.pause()

        # Enable masking
        await pilot.press("m")
        await pilot.pause()

        # Test masking in different views
        summary_content = edit_screen._mask_content(sample_data["analysis"]["summary"])
        transcript_content = edit_screen._mask_content(
            sample_data["artifact"]["transcript"]
        )
        json_content = edit_screen._mask_content(json.dumps(sample_data))

        # Verify masking is consistent across all views
        assert "984bf60e-c2e9-4677-9122-868a4ce1e6ff" not in summary_content
        assert "984bf60e-c2e9-4677-9122-868a4ce1e6ff" not in transcript_content
        assert "984bf60e-c2e9-4677-9122-868a4ce1e6ff" not in json_content
        assert "top-secret" not in json_content
        assert "secret-masked" in json_content

        assert "xxx-xxx-xxx-xxx-xxx" in summary_content
        assert "xxx-xxx-xxx-xxx-xxx" in transcript_content
        assert json_content.count("xxx-xxx-xxx-xxx-xxx") == 3  # Should be 3 GUIDs total


@pytest.mark.asyncio
async def test_secret_value_masking():
    """Test that secret values are properly masked."""
    app = CallBrowserApp()
    # Sample data with secrets at different levels
    sample_data = {
        "id": "984bf60e-c2e9-4677-9122-868a4ce1e6ff",
        "secret": "super-secret-value",
        "nested": {"secret": "nested-secret-value", "normal": "normal-value"},
        "list_with_secrets": [
            {"secret": "secret-in-list"},
            {"normal": "normal-in-list"},
        ],
        "deep_nested": {"level1": {"level2": {"secret": "deep-secret-value"}}},
    }

    edit_screen = EditScreen(sample_data)

    async with app.run_test() as pilot:
        app.push_screen(edit_screen)
        await pilot.pause()

        # Enable masking
        await pilot.press("m")
        await pilot.pause()

        # Test masking in JSON content
        masked_content = edit_screen._mask_content(json.dumps(sample_data, indent=2))
        masked_data = json.loads(masked_content)

        # Verify all secrets are masked
        assert masked_data["secret"] == "secret-masked"
        assert masked_data["nested"]["secret"] == "secret-masked"
        assert masked_data["list_with_secrets"][0]["secret"] == "secret-masked"
        assert (
            masked_data["deep_nested"]["level1"]["level2"]["secret"] == "secret-masked"
        )

        # Verify non-secret values are unchanged
        assert masked_data["nested"]["normal"] == "normal-value"
        assert masked_data["list_with_secrets"][1]["normal"] == "normal-in-list"

        # Verify GUID is still masked
        assert "984bf60e-c2e9-4677-9122-868a4ce1e6ff" not in masked_content
        assert "xxx-xxx-xxx-xxx-xxx" in masked_content


@pytest.mark.asyncio
async def test_mixed_content_masking():
    """Test that masking works on both JSON and non-JSON content."""
    app = CallBrowserApp()
    # Test with both JSON and plain text
    json_data = {"id": "984bf60e-c2e9-4677-9122-868a4ce1e6ff", "secret": "secret-value"}
    plain_text = "GUID: 984bf60e-c2e9-4677-9122-868a4ce1e6ff and some text"

    edit_screen = EditScreen(json_data)

    async with app.run_test() as pilot:
        app.push_screen(edit_screen)
        await pilot.pause()

        # Enable masking
        await pilot.press("m")
        await pilot.pause()

        # Test JSON content
        masked_json = edit_screen._mask_content(json.dumps(json_data))
        masked_json_data = json.loads(masked_json)
        assert masked_json_data["secret"] == "secret-masked"
        assert "xxx-xxx-xxx-xxx-xxx" in masked_json

        # Test plain text content
        masked_text = edit_screen._mask_content(plain_text)
        assert "984bf60e-c2e9-4677-9122-868a4ce1e6ff" not in masked_text
        assert "xxx-xxx-xxx-xxx-xxx" in masked_text


@pytest.mark.asyncio
async def test_id_field_masking():
    """Test that fields ending in CallId or ProviderId are properly masked."""
    app = CallBrowserApp()
    # Sample data with various ID fields (using non-GUID format for IDs to test separately)
    sample_data = {
        "id": "regular-id",  # Regular id, should not be masked
        "parentCallId": "abc-123-call-id",  # Should be masked
        "voipProviderId": "provider-456",  # Should be masked
        "normalField": "normal-value",  # Should not be masked
        "nested": {
            "customerCallId": "customer-789",  # Should be masked
            "normal": "normal-value",
        },
        "list_with_ids": [
            {"serviceCallId": "service-123"},  # Should be masked
            {"normal": "normal-value"},
        ],
        "deep_nested": {
            "level1": {
                "level2": {
                    "integrationProviderId": "integration-xyz"  # Should be masked
                }
            }
        },
    }

    edit_screen = EditScreen(sample_data)

    async with app.run_test() as pilot:
        app.push_screen(edit_screen)
        await pilot.pause()

        # Enable masking
        await pilot.press("m")
        await pilot.pause()

        # Test masking in JSON content
        masked_content = edit_screen._mask_content(json.dumps(sample_data, indent=2))
        masked_data = json.loads(masked_content)

        # Verify all CallId and ProviderId fields are masked
        assert masked_data["parentCallId"] == "secret-masked"
        assert masked_data["voipProviderId"] == "secret-masked"
        assert masked_data["nested"]["customerCallId"] == "secret-masked"
        assert masked_data["list_with_ids"][0]["serviceCallId"] == "secret-masked"
        assert (
            masked_data["deep_nested"]["level1"]["level2"]["integrationProviderId"]
            == "secret-masked"
        )

        # Verify non-matching fields are unchanged
        assert (
            masked_data["id"] == "regular-id"
        )  # Should not be masked as it's not a GUID or special ID
        assert masked_data["normalField"] == "normal-value"
        assert masked_data["nested"]["normal"] == "normal-value"
        assert masked_data["list_with_ids"][1]["normal"] == "normal-value"


@pytest.mark.asyncio
async def test_combined_guid_and_id_masking():
    """Test that both GUID and ID field masking work together."""
    app = CallBrowserApp()
    sample_data = {
        "id": "984bf60e-c2e9-4677-9122-868a4ce1e6ff",  # Should be masked as GUID
        "parentCallId": "abc-123-call-id",  # Should be masked as CallId
        "voipProviderId": "provider-456",  # Should be masked as ProviderId
        "normalField": "normal-value",  # Should not be masked
        "guidField": "00000000-0000-0000-0000-000000000000",  # Should be masked as GUID
        "nested": {
            "customerCallId": "customer-789",  # Should be masked as CallId
            "anotherGuid": "ABCDEF12-C2E9-4677-9122-868A4CE1E6FF",  # Should be masked as GUID
        },
    }

    edit_screen = EditScreen(sample_data)

    async with app.run_test() as pilot:
        app.push_screen(edit_screen)
        await pilot.pause()

        # Enable masking
        await pilot.press("m")
        await pilot.pause()

        # Test masking in JSON content
        masked_content = edit_screen._mask_content(json.dumps(sample_data, indent=2))
        masked_data = json.loads(masked_content)

        # Verify GUID masking
        assert "xxx-xxx-xxx-xxx-xxx" in masked_content
        assert (
            masked_content.count("xxx-xxx-xxx-xxx-xxx") == 3
        )  # Should be 3 GUIDs total

        # Verify ID field masking
        assert masked_data["parentCallId"] == "secret-masked"
        assert masked_data["voipProviderId"] == "secret-masked"
        assert masked_data["nested"]["customerCallId"] == "secret-masked"

        # Verify non-matching fields are unchanged
        assert masked_data["normalField"] == "normal-value"


@pytest.mark.asyncio
async def test_view_json_keybinding(sample_call):
    """Test that 'v' key opens the edit screen."""
    app = CallBrowserApp()
    app.calls = [sample_call]  # Use sample call for testing

    async with app.run_test() as pilot:
        # Press 'v' to open edit screen
        await pilot.press("v")
        await pilot.pause()

        # Verify edit screen is shown
        edit_screen = app.query_one(EditScreen)
        assert edit_screen is not None

        # Press 'q' to dismiss
        await pilot.press("q")
        await pilot.pause()

        # Verify edit screen is dismissed
        edit_screen = app.query(EditScreen)
        assert len(edit_screen) == 0
