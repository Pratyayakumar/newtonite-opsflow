import asyncio
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from app.config import ASYNC_WORKER_INTERVAL_SEC
from app.database import get_db_connection, db_transaction, get_utc_now_iso
from app.models import SlaRiskLevel

logger = logging.getLogger("async_worker")

def enqueue_job(
    conn: sqlite3.Connection,
    job_type: str,
    work_item_id: str,
    payload: Dict[str, Any],
    delay_seconds: int = 0
) -> str:
    """
    Enqueues a background job within the current database transaction.
    """
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    run_at = (now + timedelta(seconds=delay_seconds)).isoformat()
    now_iso = now.isoformat()
    payload_str = json.dumps(payload)

    conn.execute(
        """
        INSERT INTO async_jobs (id, job_type, work_item_id, payload_json, status, attempts, max_attempts, run_at, created_at)
        VALUES (?, ?, ?, ?, 'PENDING', 0, 3, ?, ?)
        """,
        (job_id, job_type, work_item_id, payload_str, run_at, now_iso)
    )
    return job_id

def process_sla_enrichment(conn: sqlite3.Connection, job: sqlite3.Row) -> None:
    """
    Enriches work item with SLA calculations and updates risk level.
    """
    work_item_id = job["work_item_id"]
    item = conn.execute(
        "SELECT id, created_at, target_sla_minutes, status, priority, sla_risk_level FROM work_items WHERE id = ?",
        (work_item_id,)
    ).fetchone()

    if not item or item["status"] in ("RESOLVED", "CANCELLED"):
        return

    created_at = datetime.fromisoformat(item["created_at"])
    now = datetime.now(timezone.utc)
    elapsed_minutes = (now - created_at).total_seconds() / 60.0
    sla_target = item["target_sla_minutes"]

    new_risk = SlaRiskLevel.NORMAL.value
    sla_breached = 0

    if elapsed_minutes >= sla_target:
        new_risk = SlaRiskLevel.BREACHED.value
        sla_breached = 1
    elif elapsed_minutes >= (sla_target * 0.75):
        new_risk = SlaRiskLevel.WARN.value

    # Update work item if changed
    if new_risk != item["sla_risk_level"] or sla_breached:
        conn.execute(
            """
            UPDATE work_items 
            SET sla_risk_level = ?, sla_breached = ?
            WHERE id = ?
            """,
            (new_risk, sla_breached, work_item_id)
        )
        # Record audit event
        conn.execute(
            """
            INSERT INTO work_item_events (id, work_item_id, actor_id, actor_name, event_type, details_json, created_at)
            VALUES (?, ?, 'sys_worker', 'Background SLA Engine', 'ENRICHED', ?, ?)
            """,
            (
                f"evt_{uuid.uuid4().hex[:12]}",
                work_item_id,
                json.dumps({
                    "sla_risk_level": new_risk,
                    "elapsed_minutes": round(elapsed_minutes, 1),
                    "sla_target_minutes": sla_target,
                    "breached": bool(sla_breached)
                }),
                now.isoformat()
            )
        )

def process_notification_dispatch(conn: sqlite3.Connection, job: sqlite3.Row) -> None:
    """
    Simulates asynchronous notification dispatch (Slack, PagerDuty, Webhook).
    Supports simulated failure on request to verify backoff and retry logic.
    """
    payload = json.loads(job["payload_json"])
    simulate_failure = payload.get("simulate_failure", False)
    fail_until_attempt = payload.get("fail_until_attempt", 2)
    
    # If simulated failure is requested and attempts <= fail_until_attempt, simulate a transient network fault
    if simulate_failure and job["attempts"] <= fail_until_attempt:
        raise ConnectionResetError("Simulated upstream notification gateway timeout (HTTP 504)")

    now_iso = get_utc_now_iso()
    # Record notification dispatched event in audit log
    conn.execute(
        """
        INSERT INTO work_item_events (id, work_item_id, actor_id, actor_name, event_type, details_json, created_at)
        VALUES (?, ?, 'sys_worker', 'Async Dispatcher', 'NOTIFICATION_SENT', ?, ?)
        """,
        (
            f"evt_{uuid.uuid4().hex[:12]}",
            job["work_item_id"],
            json.dumps({
                "channels": payload.get("channels", ["slack-ops", "email"]),
                "recipient": payload.get("recipient", "team-oncall"),
                "subject": payload.get("subject", "Operational Alert"),
                "attempt": job["attempts"]
            }),
            now_iso
        )
    )

def execute_single_job(job_id: str) -> bool:
    """
    Atomically claims and processes a single job.
    Returns True if job processed, False otherwise.
    """
    conn = get_db_connection()
    try:
        # Atomic claim to prevent duplicate execution across concurrent workers
        conn.execute("BEGIN IMMEDIATE;")
        claim_cursor = conn.execute(
            """
            UPDATE async_jobs 
            SET status = 'PROCESSING', attempts = attempts + 1
            WHERE id = ? AND status IN ('PENDING', 'RETRYING')
            """,
            (job_id,)
        )
        if claim_cursor.rowcount == 0:
            conn.rollback()
            return False

        job = conn.execute("SELECT * FROM async_jobs WHERE id = ?", (job_id,)).fetchone()
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        logger.error(f"Failed to claim job {job_id}: {e}")
        return False

    # Execute job body in separate transaction
    success = False
    error_msg = None
    try:
        with db_transaction() as tx:
            if job["job_type"] == "SLA_ENRICHMENT":
                process_sla_enrichment(tx, job)
            elif job["job_type"] == "NOTIFICATION_DISPATCH":
                process_notification_dispatch(tx, job)
            success = True
    except Exception as exc:
        error_msg = str(exc)
        logger.warning(f"Job {job_id} encountered error on attempt {job['attempts']}: {error_msg}")

    # Finalize status with retry / backoff or dead-letter
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc)
        if success:
            conn.execute(
                """
                UPDATE async_jobs 
                SET status = 'COMPLETED', completed_at = ?, last_error = NULL
                WHERE id = ?
                """,
                (now.isoformat(), job_id)
            )
        else:
            if job["attempts"] >= job["max_attempts"]:
                conn.execute(
                    """
                    UPDATE async_jobs 
                    SET status = 'DEAD_LETTER', last_error = ?
                    WHERE id = ?
                    """,
                    (error_msg, job_id)
                )
            else:
                # Exponential backoff: 2 ** attempts seconds
                delay = 2 ** job["attempts"]
                next_run = (now + timedelta(seconds=delay)).isoformat()
                conn.execute(
                    """
                    UPDATE async_jobs 
                    SET status = 'PENDING', run_at = ?, last_error = ?
                    WHERE id = ?
                    """,
                    (next_run, error_msg, job_id)
                )
        conn.commit()
    finally:
        conn.close()

    return success

def run_due_jobs(limit: int = 10) -> int:
    """
    Finds and processes all pending jobs whose run_at <= now.
    """
    now_iso = get_utc_now_iso()
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT id FROM async_jobs 
            WHERE status = 'PENDING' AND run_at <= ?
            ORDER BY run_at ASC
            LIMIT ?
            """,
            (now_iso, limit)
        ).fetchall()
        job_ids = [r["id"] for r in rows]
    finally:
        conn.close()

    processed_count = 0
    for jid in job_ids:
        execute_single_job(jid)
        processed_count += 1

    return processed_count

async def background_worker_loop():
    """
    Continuous worker loop running inside the FastAPI application process.
    """
    logger.info("Async background worker started.")
    while True:
        try:
            run_due_jobs()
        except Exception as e:
            logger.error(f"Error in background worker tick: {e}")
        await asyncio.sleep(ASYNC_WORKER_INTERVAL_SEC)
