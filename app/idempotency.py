import hashlib
import json
import sqlite3
from typing import Optional, Tuple, Dict, Any
from fastapi import Request, HTTPException, status
from app.database import get_utc_now_iso

def compute_payload_hash(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

def check_idempotency(
    conn: sqlite3.Connection,
    idempotency_key: str,
    user_id: str,
    path: str,
    payload_hash: str
) -> Optional[Tuple[int, Dict[str, Any]]]:
    """
    Checks if an idempotency key has already been processed for this user.
    If found and payload matches, returns (status_code, response_body_dict).
    If found and payload differs, raises 422 Unprocessable Entity.
    """
    row = conn.execute(
        """
        SELECT request_payload_hash, response_status_code, response_body
        FROM idempotency_keys
        WHERE idempotency_key = ? AND user_id = ?
        """,
        (idempotency_key, user_id)
    ).fetchone()

    if not row:
        return None

    if row["request_payload_hash"] != payload_hash:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Idempotency Key Conflict: The key '{idempotency_key}' was previously used with a different request payload. "
                "Idempotency keys must not be reused across distinct mutation payloads."
            )
        )

    try:
        body = json.loads(row["response_body"])
    except Exception:
        body = {"raw": row["response_body"]}

    return (row["response_status_code"], body)

def record_idempotency(
    conn: sqlite3.Connection,
    idempotency_key: str,
    user_id: str,
    path: str,
    payload_hash: str,
    status_code: int,
    response_body: Dict[str, Any]
) -> None:
    """
    Persists the idempotency receipt within the current database transaction.
    """
    now = get_utc_now_iso()
    serialized_body = json.dumps(response_body, default=str)
    conn.execute(
        """
        INSERT OR REPLACE INTO idempotency_keys 
        (idempotency_key, user_id, request_path, request_payload_hash, response_status_code, response_body, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (idempotency_key, user_id, path, payload_hash, status_code, serialized_body, now)
    )
