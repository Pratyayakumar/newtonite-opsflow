import sqlite3
from typing import Optional, Tuple, Dict, Any
from fastapi import HTTPException, status
from app.database import get_utc_now_iso

def verify_and_increment_version(
    conn: sqlite3.Connection,
    work_item_id: str,
    expected_version: int
) -> int:
    """
    Checks if current database version matches expected_version.
    If not, raises 409 Conflict with detailed diagnostic state.
    Returns the new incremented version.
    """
    row = conn.execute(
        "SELECT version, title, status, assignee_id, updated_at FROM work_items WHERE id = ?",
        (work_item_id,)
    ).fetchone()
    
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work item '{work_item_id}' not found."
        )

    current_version = row["version"]
    if current_version != expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "OPTIMISTIC_CONCURRENCY_CONFLICT",
                "message": (
                    f"Conflict detected for work item '{work_item_id}'. "
                    f"Your request was based on stale version {expected_version}, "
                    f"but the current database version is {current_version}. "
                    f"Another operator modified this record at {row['updated_at']}."
                ),
                "expected_version": expected_version,
                "current_version": current_version,
                "current_status": row["status"],
                "current_assignee": row["assignee_id"]
            }
        )

    return current_version + 1

def atomic_claim_work_item(
    conn: sqlite3.Connection,
    work_item_id: str,
    expected_version: int,
    user_id: str
) -> Tuple[bool, int, Optional[str]]:
    """
    Atomically claims an unassigned work item using conditional WHERE.
    Guarantees that if two workers attempt to claim simultaneously, exactly one succeeds.
    Returns (success, new_version, failure_reason)
    """
    now = get_utc_now_iso()
    
    # Check current state first
    current = conn.execute(
        "SELECT version, assignee_id, status FROM work_items WHERE id = ?",
        (work_item_id,)
    ).fetchone()
    
    if not current:
        return False, 0, "Item not found"
        
    if current["assignee_id"] and current["assignee_id"] != user_id:
        return False, current["version"], f"Item is already claimed by user '{current['assignee_id']}'"
        
    if current["version"] != expected_version:
        return False, current["version"], f"Version mismatch: expected {expected_version}, found {current['version']}"

    # Atomic conditional update
    cursor = conn.execute(
        """
        UPDATE work_items
        SET assignee_id = ?,
            version = version + 1,
            updated_at = ?,
            status = CASE WHEN status = 'TRIAGE' THEN 'IN_INVESTIGATION' ELSE status END
        WHERE id = ? 
          AND version = ? 
          AND (assignee_id IS NULL OR assignee_id = '');
        """,
        (user_id, now, work_item_id, expected_version)
    )

    if cursor.rowcount == 0:
        # Another transaction raced and committed first
        latest = conn.execute("SELECT version, assignee_id FROM work_items WHERE id = ?", (work_item_id,)).fetchone()
        return False, latest["version"] if latest else 0, f"Race condition: item claimed concurrently by '{latest['assignee_id'] if latest else 'unknown'}'"

    new_version = expected_version + 1
    return True, new_version, None
