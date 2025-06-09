import pytest
import httpx
import os
import tempfile # Added for unique temp DBs
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# Assuming models.py and cache.py are in the same directory or PYTHONPATH is set
from models import Call
from cache import init_db, cache_calls, get_cached_calls, CACHE_DB
from calls import is_network_available, vapi_calls, CacheUpdateManager

# Dummy call data for testing
DUMMY_CALL_DATA_1 = {
    "id": "call_1",
    "customer": {"number": "1234567890"},
    "createdAt": (datetime.now() - timedelta(days=1)).isoformat() + "Z",
    "endedAt": datetime.now().isoformat() + "Z",
    "artifact": {"transcript": "Hello world"},
    "analysis": {"summary": "Test summary 1"},
    "cost": 0.05,
    "endedReason": "completed",
}

DUMMY_CALL_DATA_2 = {
    "id": "call_2",
    "customer": {"number": "0987654321"},
    "createdAt": (datetime.now() - timedelta(hours=2)).isoformat() + "Z",
    "endedAt": (datetime.now() - timedelta(hours=1)).isoformat() + "Z",
    "artifact": {"transcript": "Another call"},
    "analysis": {"summary": "Test summary 2"},
    "cost": 0.15,
    "endedReason": "customer-ended-call",
}

# Helper to parse raw dicts into Call models, similar to calls.parse_call
def parse_to_call_model(call_dict_list):
    calls = []
    for c_dict in call_dict_list:
        # Simplified parsing for test setup, adapt if full parsing needed
        calls.append(
            Call(
                id=c_dict["id"],
                Caller=c_dict.get("customer", {}).get("number", ""),
                Transcript=c_dict.get("artifact", {}).get("transcript", ""),
                Start=datetime.strptime(c_dict["createdAt"], "%Y-%m-%dT%H:%M:%S.%fZ") if isinstance(c_dict["createdAt"], str) else c_dict["createdAt"],
                End=datetime.strptime(c_dict["endedAt"], "%Y-%m-%dT%H:%M:%S.%fZ") if isinstance(c_dict["endedAt"], str) else c_dict["endedAt"],
                Summary=c_dict.get("analysis", {}).get("summary", ""),
                Cost=c_dict.get("cost", 0.0),
                CostBreakdown=c_dict.get("costBreakdown", {}),
                EndedReason=c_dict.get("endedReason", ""),
            )
        )
    return calls

DUMMY_CALLS_MODELS = parse_to_call_model([DUMMY_CALL_DATA_1, DUMMY_CALL_DATA_2])


@pytest.fixture
def temp_cache_db(monkeypatch):
    """
    Creates a temporary, unique cache DB for each test.
    Patches cache.CACHE_DB and calls.CACHE_DB (if directly used) for the test's duration.
    """
    # Create a truly temporary file for the database
    temp_db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    temp_db_path = temp_db_file.name
    temp_db_file.close() # Close it so sqlite3 can open it

    # Patch the CACHE_DB constant in the 'cache' module
    monkeypatch.setattr('cache.CACHE_DB', temp_db_path)

    # If calls.py also imports CACHE_DB directly, patch it there too.
    # Based on current usage, it seems calls.py uses cache.py's functions,
    # which will then use the patched cache.CACHE_DB.
    # If direct usage was found: monkeypatch.setattr('calls.CACHE_DB', temp_db_path)

    # Initialize the new temporary database
    init_db() # This will now use the temp_db_path due to the patch

    yield temp_db_path # Provide the path to the unique DB for this test

    # Teardown: remove the temporary database file
    if os.path.exists(temp_db_path):
        os.remove(temp_db_path)

# Test cases will be added below

# --- Tests for is_network_available ---

@patch('calls.httpx.head')
def test_is_network_available_success(mock_head):
    """Test is_network_available returns True on successful HEAD request."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_head.return_value = mock_response
    assert is_network_available() is True
    mock_head.assert_called_once_with("https://1.1.1.1", timeout=1)

@patch('calls.httpx.head', side_effect=httpx.NetworkError("Network error"))
def test_is_network_available_network_error(mock_head):
    """Test is_network_available returns False on httpx.NetworkError."""
    assert is_network_available() is False
    mock_head.assert_called_once_with("https://1.1.1.1", timeout=1)

@patch('calls.httpx.head', side_effect=httpx.TimeoutException("Timeout"))
def test_is_network_available_timeout_exception(mock_head):
    """Test is_network_available returns False on httpx.TimeoutException."""
    assert is_network_available() is False
    mock_head.assert_called_once_with("https://1.1.1.1", timeout=1)

@patch('calls.httpx.head', side_effect=Exception("Some other error"))
def test_is_network_available_other_exception(mock_head):
    """Test is_network_available returns False on any other Exception."""
    assert is_network_available() is False
    mock_head.assert_called_once_with("https://1.1.1.1", timeout=1)

# --- Tests for vapi_calls ---

@patch('calls.httpx.get') # To ensure no API calls are made
@patch('calls.is_network_available', return_value=True) # Mock network as available
def test_vapi_calls_offline_flag_cache_exists(mock_is_net_available, mock_http_get, temp_cache_db):
    """
    Test vapi_calls with offline=True and cache exists.
    Should return cached calls and not call httpx.get.
    """
    # 1. Pre-populate cache
    cache_calls(DUMMY_CALLS_MODELS)
    cached_on_disk = get_cached_calls()
    assert len(cached_on_disk) == len(DUMMY_CALLS_MODELS)

    # 2. Call vapi_calls with offline=True
    # VAPI_API_KEY needs to be set for the module that uses it, even if not called
    with patch.dict(os.environ, {"VAPI_API_KEY": "test_key"}):
        returned_calls = vapi_calls(offline=True)

    # 3. Assertions
    assert len(returned_calls) == len(DUMMY_CALLS_MODELS)
    # Compare by IDs or a more robust Pydantic model comparison if needed
    assert sorted([call.id for call in returned_calls]) == sorted([call.id for call in DUMMY_CALLS_MODELS])

    mock_http_get.assert_not_called() # Crucial: No API call should be made
    mock_is_net_available.assert_called_once() # is_network_available is checked once at the start

@patch('calls.httpx.get') # To ensure no API calls are made
@patch('calls.is_network_available', return_value=True) # Mock network as available
def test_vapi_calls_offline_flag_no_cache(mock_is_net_available, mock_http_get, temp_cache_db):
    """
    Test vapi_calls with offline=True and no cache exists.
    Should return an empty list and not call httpx.get.
    """
    # 1. Ensure cache is empty (fixture already does this, but good to be explicit)
    assert get_cached_calls() is None

    # 2. Call vapi_calls with offline=True
    with patch.dict(os.environ, {"VAPI_API_KEY": "test_key"}):
        returned_calls = vapi_calls(offline=True)

    # 3. Assertions
    assert returned_calls == []
    mock_http_get.assert_not_called()
    mock_is_net_available.assert_called_once()

@patch('calls.httpx.get')
@patch('calls.is_network_available', return_value=True) # Mock network as available
@patch('calls.get_latest_cached_call', return_value=None) # Mock no latest cached call to force full fetch
@patch('calls.cache_calls') # To verify it's called
def test_vapi_calls_online_normal_operation_empty_cache(
    mock_cache_calls_func,
    mock_get_latest_cached,
    mock_is_net_available,
    mock_http_get,
    temp_cache_db
):
    """
    Test vapi_calls in normal online mode with an empty cache.
    Should fetch from API, return calls, and populate cache.
    """
    # 1. Ensure cache is empty
    assert get_cached_calls() is None

    # 2. Mock httpx.get to return dummy API data
    # The vapi_calls makes two calls if cache is empty: one for latest check (empty), one for all.
    # Or, if skip_api_check is false and no cache, it might go straight to full fetch.
    # For this test, we simulate the "fetch all calls" path.
    mock_http_get.return_value = MagicMock(
        json=lambda: [DUMMY_CALL_DATA_1, DUMMY_CALL_DATA_2], # Simulate full fetch data
        raise_for_status=lambda: None
    )

    # 3. Call vapi_calls
    with patch.dict(os.environ, {"VAPI_API_KEY": "test_key"}):
        # skip_api_check=False by default
        returned_calls = vapi_calls(offline=False, skip_api_check=False)

    # 4. Assertions
    assert len(returned_calls) == len(DUMMY_CALLS_MODELS)
    assert sorted([call.id for call in returned_calls]) == sorted([call.id for call in DUMMY_CALLS_MODELS])

    # Check that httpx.get was called (at least for the full fetch)
    # The exact number of calls to httpx.get might vary based on internal logic (e.g. latest call check)
    # For this specific path (empty cache, online), it should call for full list.
    # A more specific check could be `mock_http_get.assert_any_call(...)` with the full fetch URL.
    assert mock_http_get.called

    # Assert that is_network_available was called
    mock_is_net_available.assert_called_once()

    # Assert that cache_calls was called with the fetched calls
    mock_cache_calls_func.assert_called_once()
    # To be more precise, check what it was called with:
    # args, _ = mock_cache_calls_func.call_args
    # assert len(args[0]) == len(DUMMY_CALLS_MODELS)

    # 5. Verify cache is populated (optional, as we mocked cache_calls, but good for integration sense)
    # This requires cache_calls *not* to be mocked if we want to check actual db content.
    # For now, mocking cache_calls is fine to unit test vapi_calls' interaction.
    # If we remove @patch('calls.cache_calls'), then the following would work:
    # final_cached_calls = get_cached_calls()
    # assert len(final_cached_calls) == len(DUMMY_CALLS_MODELS)

# --- Tests for CacheUpdateManager ---

@patch('calls.CacheUpdateManager._fetch_all_calls')
@patch('calls.CacheUpdateManager._check_for_new_calls')
@patch('calls.is_network_available', return_value=True) # Network is up
def test_cache_update_manager_offline_flag(
    mock_is_net_available,
    mock_check_new,
    mock_fetch_all,
    temp_cache_db
):
    """
    Test CacheUpdateManager with offline=True.
    It should not attempt any API calls.
    """
    manager = CacheUpdateManager(app=None, foreground_updates=True, offline=True)

    # Call the method that would normally perform API calls
    manager._check_and_update_cache()

    mock_is_net_available.assert_not_called() # Should not even check network if offline flag is true
    mock_check_new.assert_not_called()
    mock_fetch_all.assert_not_called()

    # Also test start_background_update
    result = manager.start_background_update()
    assert result is False # Should indicate update was skipped
    mock_is_net_available.assert_not_called()
    mock_check_new.assert_not_called()
    mock_fetch_all.assert_not_called()

@patch('calls.CacheUpdateManager._fetch_all_calls')
@patch('calls.CacheUpdateManager._check_for_new_calls')
@patch('calls.is_network_available', return_value=False) # Network is down
def test_cache_update_manager_network_down(
    mock_is_net_available,
    mock_check_new,
    mock_fetch_all,
    temp_cache_db
):
    """
    Test CacheUpdateManager with offline=False but network is down.
    It should attempt to check network, then not attempt API calls.
    """
    manager = CacheUpdateManager(app=None, foreground_updates=True, offline=False)

    # Call the method that would normally perform API calls
    manager._check_and_update_cache()

    mock_is_net_available.assert_called_once() # Should check network
    mock_check_new.assert_not_called() # API call methods should not be called
    mock_fetch_all.assert_not_called()

    # Reset mock for start_background_update test
    mock_is_net_available.reset_mock()
    mock_check_new.reset_mock()
    mock_fetch_all.reset_mock()

    # Also test start_background_update
    # In CacheUpdateManager.start_background_update, if offline is False, it proceeds to create a thread
    # The actual check of network happens inside _check_and_update_cache.
    # So, start_background_update itself doesn't directly prevent action due to network_available here.
    # The critical part is that _check_and_update_cache, when run, will stop due to network.

    # We need to ensure that when _check_and_update_cache is called by the thread, it behaves as tested above.
    # For simplicity here, we're testing the direct call again, assuming the threading works.
    # A more complex test could involve checking mocks after a thread join, but that's more involved.

    manager.start_background_update() # This will run _check_and_update_cache in foreground due to True

    mock_is_net_available.assert_called_once()
    mock_check_new.assert_not_called()
    mock_fetch_all.assert_not_called()

@patch('calls.httpx.get') # To ensure no API calls are made
@patch('calls.is_network_available', return_value=False) # Mock network as unavailable
def test_vapi_calls_network_down_cache_exists(mock_is_net_available, mock_http_get, temp_cache_db):
    """
    Test vapi_calls with network down (offline=False) and cache exists.
    Should return cached calls and not call httpx.get.
    """
    # 1. Pre-populate cache
    cache_calls(DUMMY_CALLS_MODELS)
    assert len(get_cached_calls()) == len(DUMMY_CALLS_MODELS)

    # 2. Call vapi_calls with offline=False, network is down
    with patch.dict(os.environ, {"VAPI_API_KEY": "test_key"}):
        returned_calls = vapi_calls(offline=False)

    # 3. Assertions
    assert len(returned_calls) == len(DUMMY_CALLS_MODELS)
    assert sorted([call.id for call in returned_calls]) == sorted([call.id for call in DUMMY_CALLS_MODELS])
    mock_http_get.assert_not_called()
    mock_is_net_available.assert_called_once()

@patch('calls.httpx.get') # To ensure no API calls are made
@patch('calls.is_network_available', return_value=False) # Mock network as unavailable
def test_vapi_calls_network_down_no_cache(mock_is_net_available, mock_http_get, temp_cache_db):
    """
    Test vapi_calls with network down (offline=False) and no cache.
    Should return an empty list and not call httpx.get.
    """
    # 1. Ensure cache is empty
    assert get_cached_calls() is None

    # 2. Call vapi_calls with offline=False, network is down
    with patch.dict(os.environ, {"VAPI_API_KEY": "test_key"}):
        returned_calls = vapi_calls(offline=False)

    # 3. Assertions
    assert returned_calls == []
    mock_http_get.assert_not_called()
    mock_is_net_available.assert_called_once()
