import pytest
from app.database import get_db_connection, db_transaction
from app.async_worker import enqueue_job, execute_single_job, run_due_jobs

def test_async_job_enqueue_on_creation(client):
    """
    SCENARIO:
    A new operational work item is created.
    CRITICAL BEHAVIOR:
    Secondary background jobs (SLA_ENRICHMENT, NOTIFICATION_DISPATCH) must be
    enqueued atomically into the async_jobs table.
    """
    res = client.post(
        "/api/work-items",
        headers={"X-User-Id": "usr_alice"},
        json={
            "title": "Async Worker Integration Verification Item",
            "description": "Verifying asynchronous secondary jobs are enqueued.",
            "category": "operational_task",
            "priority": "P2",
            "assigned_team": "tier1_support"
        }
    )
    assert res.status_code == 201
    item_id = res.json()["id"]

    conn = get_db_connection()
    try:
        jobs = conn.execute(
            "SELECT id, job_type, status FROM async_jobs WHERE work_item_id = ?",
            (item_id,)
        ).fetchall()
        job_types = {j["job_type"] for j in jobs}
        assert "SLA_ENRICHMENT" in job_types
        assert "NOTIFICATION_DISPATCH" in job_types
    finally:
        conn.close()

def test_async_job_failure_retry_and_dead_letter():
    """
    DANGEROUS SCENARIO:
    A secondary external dispatch job experiences repeated network timeouts.
    CRITICAL BEHAVIOR:
    The worker must increment attempts, record last_error, and upon exceeding
    max_attempts (3), safely transition to DEAD_LETTER status without losing the record.
    """
    conn = get_db_connection()
    try:
        with db_transaction() as tx:
            job_id = enqueue_job(
                tx,
                job_type="NOTIFICATION_DISPATCH",
                work_item_id="wi_p0_db_pool",
                payload={"recipient": "ops-oncall", "simulate_failure": True, "fail_until_attempt": 99}
            )
    finally:
        conn.close()

    # Attempt 1: Fails, increments attempts to 1, sets status to PENDING with backoff
    execute_single_job(job_id)
    conn = get_db_connection()
    try:
        j1 = conn.execute("SELECT attempts, status, last_error FROM async_jobs WHERE id = ?", (job_id,)).fetchone()
        assert j1["attempts"] == 1
        assert j1["status"] == "PENDING"
        assert "504" in j1["last_error"]
    finally:
        conn.close()

    # Attempt 2: Fails, increments attempts to 2, backoff
    execute_single_job(job_id)
    conn = get_db_connection()
    try:
        j2 = conn.execute("SELECT attempts, status, last_error FROM async_jobs WHERE id = ?", (job_id,)).fetchone()
        assert j2["attempts"] == 2
        assert j2["status"] == "PENDING"
    finally:
        conn.close()

    # Force max attempts limit test: Manually set attempts to 3
    conn = get_db_connection()
    try:
        conn.execute("UPDATE async_jobs SET attempts = 3 WHERE id = ?", (job_id,))
        conn.commit()
    finally:
        conn.close()

    # Attempt 3: Exceeds max_attempts -> DEAD_LETTER
    execute_single_job(job_id)
    conn = get_db_connection()
    try:
        j3 = conn.execute("SELECT status, attempts, last_error FROM async_jobs WHERE id = ?", (job_id,)).fetchone()
        assert j3["status"] == "DEAD_LETTER"
        assert j3["last_error"] is not None
    finally:
        conn.close()
