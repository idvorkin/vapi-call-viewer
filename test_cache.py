import pytest
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch
from cache import (
    init_db,
    cache_calls,
    get_cached_calls,
    get_latest_cached_call,
    get_cache_stats,
)
from models import Call


@pytest.fixture
def sample_calls():
    now = datetime.now()
    return [
        Call(
            id="test123",
            Caller="+1234567890",
            Transcript="Hello, this is a test call",
            Summary="Test call summary",
            Start=now,
            End=now + timedelta(minutes=5),
            Cost=1.23,
            CostBreakdown={"transcription": 0.5, "analysis": 0.73},
        ),
        Call(
            id="test456",
            Caller="+0987654321",
            Transcript="Another test call",
            Summary="Another test summary",
            Start=now,
            End=now + timedelta(minutes=3),
            Cost=0.89,
            CostBreakdown={"transcription": 0.4, "analysis": 0.49},
        ),
    ]


@pytest.fixture(autouse=True)
def setup_teardown():
    # Setup: ensure we're using a temporary test database
    test_db = os.path.join(tempfile.gettempdir(), f"test_vapi_calls_{os.getpid()}.db")

    # Patch the CACHE_DB path and initialize a fresh database
    with patch("cache.CACHE_DB", test_db):
        # Remove any existing test database
        if os.path.exists(test_db):
            os.remove(test_db)

        # Initialize fresh database
        init_db()
        yield

    # Teardown: remove test database
    if os.path.exists(test_db):
        try:
            os.remove(test_db)
        except PermissionError:
            pass  # Ignore permission errors during cleanup


def test_cache_and_retrieve_calls(sample_calls):
    # Cache the calls
    cache_calls(sample_calls)

    # Retrieve them
    cached = get_cached_calls()
    assert cached is not None
    assert len(cached) == 2

    # Verify the data
    assert cached[0].id == sample_calls[0].id
    assert cached[0].Caller == sample_calls[0].Caller
    assert cached[0].Cost == sample_calls[0].Cost
    assert cached[0].CostBreakdown == sample_calls[0].CostBreakdown


def test_cache_expiry():
    """Test that cache now retains old calls (infinite cache)"""
    now = datetime.now()
    old_call = Call(
        id="test789",
        Caller="+1234567890",
        Transcript="Test call",
        Summary="Summary",
        Start=now - timedelta(hours=25),  # Call from 25 hours ago
        End=now - timedelta(hours=25) + timedelta(minutes=1),
        Cost=1.0,
        CostBreakdown={},
    )

    # Cache the old call with its timestamp from 25 hours ago
    old_cache_time = now - timedelta(hours=25)
    cache_calls([old_call], cache_time=old_cache_time)

    # Should return the old call since we now have infinite cache
    cached_calls = get_cached_calls()
    assert cached_calls is not None, "Expected calls to be returned with infinite cache"
    assert len(cached_calls) == 1, "Expected one call"
    assert cached_calls[0].id == "test789", "Expected the old call to be returned"

    # Create a new call
    new_call = Call(
        id="test790",  # Different ID
        Caller="+1234567890",
        Transcript="New test call",
        Summary="New Summary",
        Start=now,
        End=now + timedelta(minutes=1),
        Cost=1.0,
        CostBreakdown={},
    )

    # Cache the new call with current timestamp
    cache_calls([new_call])

    # Should return both calls since we have infinite cache
    cached_calls = get_cached_calls()
    assert cached_calls is not None, "Expected calls to be returned"
    assert len(cached_calls) == 2, "Expected both old and new calls"
    call_ids = {call.id for call in cached_calls}
    assert "test789" in call_ids, "Expected old call to be present"
    assert "test790" in call_ids, "Expected new call to be present"


def test_cache_update():
    now = datetime.now()
    original_call = Call(
        id="test999",
        Caller="+1234567890",
        Transcript="Original",
        Summary="Original summary",
        Start=now,
        End=now + timedelta(minutes=1),
        Cost=1.0,
        CostBreakdown={},
    )

    updated_call = Call(
        id="test999",  # Same ID
        Caller="+1234567890",
        Transcript="Updated",
        Summary="Updated summary",
        Start=now,
        End=now + timedelta(minutes=2),
        Cost=2.0,
        CostBreakdown={"new": "value"},
    )

    # Cache original call
    cache_calls([original_call])

    # Cache updated call
    cache_calls([updated_call])

    # Retrieve and verify it's updated
    cached = get_cached_calls()
    assert cached is not None
    assert len(cached) == 1
    assert cached[0].Transcript == "Updated"
    assert cached[0].Summary == "Updated summary"
    assert cached[0].Cost == 2.0
    assert cached[0].CostBreakdown == {"new": "value"}


def test_get_latest_cached_call(sample_calls):
    # Cache the calls
    cache_calls(sample_calls)

    # Get latest call
    latest = get_latest_cached_call()
    assert latest is not None

    # The latest call should be the one with the most recent Start time
    latest_sample = max(sample_calls, key=lambda x: x.Start)
    assert latest.id == latest_sample.id
    assert latest.Start == latest_sample.Start
    assert latest.End == latest_sample.End


def test_cache_stats(sample_calls):
    # Initially the cache should be empty
    stats = get_cache_stats()
    assert stats["exists"]  # True because init_db() creates the file
    assert stats["call_count"] == 0
    assert stats["oldest_call"] is None
    assert stats["newest_call"] is None

    # Cache some calls
    now = datetime.now()
    cache_calls(sample_calls, cache_time=now)

    # Check stats after caching
    stats = get_cache_stats()
    assert stats["exists"]
    assert stats["call_count"] == 2
    assert stats["size_bytes"] > 0
    assert stats["size_mb"] > 0
    assert stats["oldest_call"] == now.isoformat()
    assert stats["newest_call"] == now.isoformat()

    # Add another call with a different timestamp
    later_time = now + timedelta(hours=1)
    new_call = Call(
        id="test999",
        Caller="+1234567890",
        Transcript="New call",
        Summary="New summary",
        Start=later_time,
        End=later_time + timedelta(minutes=1),
        Cost=1.0,
        CostBreakdown={},
    )
    cache_calls([new_call], cache_time=later_time)

    # Check updated stats
    stats = get_cache_stats()
    assert stats["call_count"] == 3
    assert stats["oldest_call"] == now.isoformat()
    assert stats["newest_call"] == later_time.isoformat()
