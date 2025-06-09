import sqlite3
import json
import os
import tempfile
from datetime import datetime, timedelta
from typing import List, Optional
from models import Call
from loguru import logger

CACHE_DB = os.path.join(tempfile.gettempdir(), "vapi_calls.db")
logger.debug(f"Cache database location: {CACHE_DB}")


def init_db() -> bool:
    """Initialize the SQLite database and create the calls table if it doesn't exist"""
    try:
        conn = sqlite3.connect(CACHE_DB)
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS calls
               (id TEXT PRIMARY KEY,
                caller TEXT,
                transcript TEXT,
                summary TEXT,
                start TEXT,
                end TEXT,
                cost REAL,
                cost_breakdown TEXT,
                ended_reason TEXT,
                cached_at TEXT)"""
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error as e:
        logger.error(f"Error initializing database: {e}")
        if conn:
            conn.close()
        return False


def get_latest_cached_call() -> Optional[Call]:
    """Get the most recent call from the cache based on Start time"""
    logger.debug("Fetching latest cached call")
    if not os.path.exists(CACHE_DB):
        logger.debug("Cache database does not exist")
        return None

    conn = sqlite3.connect(CACHE_DB)
    c = conn.cursor()
    c.execute("""SELECT * FROM calls ORDER BY start DESC LIMIT 1""")

    row = c.fetchone()
    conn.close()

    if not row:
        logger.debug("No calls found in cache")
        return None

    call = Call(
        id=row[0],
        Caller=row[1],
        Transcript=row[2],
        Summary=row[3],
        Start=datetime.fromisoformat(row[4]),
        End=datetime.fromisoformat(row[5]),
        Cost=row[6],
        CostBreakdown=json.loads(row[7]),
        EndedReason=row[8] if len(row) > 8 else "",
    )
    logger.debug(f"Found latest cached call: {call.id} from {call.Start}")
    return call


def cache_calls(calls: List[Call], cache_time: Optional[datetime] = None):
    """
    Cache the calls in the database.
    :param calls: List of calls to cache
    :param cache_time: Optional datetime to use as cache time (for testing)
    """
    logger.debug(f"Caching {len(calls)} calls")

    # Ensure database and table exist
    if not init_db():
        logger.error("Failed to initialize database")
        return

    try:
        conn = sqlite3.connect(CACHE_DB)
        c = conn.cursor()
        cache_time = cache_time or datetime.now()
        logger.debug(f"Using cache timestamp: {cache_time.isoformat()}")

        for call in calls:
            c.execute(
                """INSERT OR REPLACE INTO calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    call.id,
                    call.Caller,
                    call.Transcript,
                    call.Summary,
                    call.Start.isoformat(),
                    call.End.isoformat(),
                    call.Cost,
                    json.dumps(call.CostBreakdown),
                    call.EndedReason,
                    cache_time.isoformat(),
                ),
            )
            logger.debug(f"Cached call {call.id} from {call.Start}")

        conn.commit()
        conn.close()
        logger.debug("Cache operation completed")
    except sqlite3.Error as e:
        logger.error(f"Error caching calls: {e}")
        if conn:
            conn.close()


def get_cached_calls(max_age_minutes: Optional[int] = None) -> Optional[List[Call]]:
    """Get cached calls if they exist"""
    logger.debug("Retrieving calls from cache")
    if not os.path.exists(CACHE_DB):
        logger.debug("Cache database does not exist")
        return None

    conn = sqlite3.connect(CACHE_DB)

    # Enable SQLite datetime functions
    conn.create_function("DATETIME", 1, lambda x: x)

    c = conn.cursor()
    
    # Get all calls without age restriction
    c.execute(
        """
        SELECT * FROM calls 
        ORDER BY datetime(cached_at) DESC
    """
    )

    rows = c.fetchall()
    conn.close()

    if not rows:
        logger.debug("No cached calls found")
        return None

    calls = [
        Call(
            id=row[0],
            Caller=row[1],
            Transcript=row[2],
            Summary=row[3],
            Start=datetime.fromisoformat(row[4]),
            End=datetime.fromisoformat(row[5]),
            Cost=row[6],
            CostBreakdown=json.loads(row[7]),
            EndedReason=row[8] if len(row) > 8 else "",
        )
        for row in rows
    ]

    logger.debug(f"Retrieved {len(calls)} cached calls")
    return calls


def get_cache_stats() -> dict:
    """Get statistics about the cache"""
    stats = {
        "exists": False,
        "size_bytes": 0,
        "call_count": 0,
        "oldest_call": None,
        "newest_call": None,
        "size_mb": 0.0, # Ensure float for consistency
        "status": "not_exists", # Added status field
        "cache_file": CACHE_DB
    }

    if not os.path.exists(CACHE_DB):
        return stats # Returns stats with exists=False, status="not_exists"

    stats["exists"] = True # File exists, so update this

    try:
        conn = sqlite3.connect(CACHE_DB)
        c = conn.cursor()

        # Check if table exists
        c.execute(
            """SELECT name FROM sqlite_master WHERE type='table' AND name='calls' """
        )
        if not c.fetchone():
            conn.close()
            stats["exists"] = True  # File exists but table doesn't
            return stats

        # Get total number of calls
        c.execute("SELECT COUNT(*) FROM calls")
        call_count = c.fetchone()[0]

        # Get oldest and newest cached times
        c.execute("SELECT MIN(cached_at), MAX(cached_at) FROM calls")
        oldest, newest = c.fetchone()

        # Get database file size
        size_bytes = os.path.getsize(CACHE_DB)

        conn.close()

        stats.update(
            {
                "size_bytes": size_bytes,
                "size_mb": round(size_bytes / (1024 * 1024), 2),
                "call_count": call_count,
                "oldest_call": oldest,
                "newest_call": newest,
                "status": "ok", # Update status
            }
        )

    except sqlite3.Error as e:
        logger.error(f"Error getting cache stats: {e}")
        # Attempt to get size even if DB operations fail, if file exists
        if os.path.exists(CACHE_DB):
            try:
                stats["size_bytes"] = os.path.getsize(CACHE_DB)
                stats["size_mb"] = round(stats["size_bytes"] / (1024 * 1024), 2)
            except OSError:
                pass # Could not get size
        stats["status"] = "error_db_operation"


    return stats


# Initialize the database when the module is imported
init_db()
