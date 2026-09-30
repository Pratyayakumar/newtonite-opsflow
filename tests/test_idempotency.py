import uuid
import pytest

def test_idempotent_work_item_creation(client):
    """
    DANGEROUS SCENARIO:
    A network retry or browser double-click causes the POST /api/work-items request
    to be transmitted twice with the same Idempotency-Key.
    CRITICAL BEHAVIOR:
    The second request must return the cached 201 response with X-Idempotency-Replay: true.
    Exactly one work item must exist in the database; no duplicate records created.
    """
    idempotency_key = f"idem_create_{uuid.uuid4().hex}"
    payload = {
        "title": "Automated Kafka MirrorMaker Lag Alert",
        "description": "Cross-datacenter topic replication lag exceeded 10,000 offsets.",
        "category": "incident",
        "priority": "P1",
        "assigned_team": "incident_response"
    }

    # First attempt
    res1 = client.post(
        "/api/work-items",
        headers={"X-User-Id": "usr_bob", "Idempotency-Key": idempotency_key},
        json=payload
    )
    assert res1.status_code == 201
    item_id = res1.json()["id"]
    assert "X-Idempotency-Replay" not in res1.headers

    # Second attempt (network retry simulation)
    res2 = client.post(
        "/api/work-items",
        headers={"X-User-Id": "usr_bob", "Idempotency-Key": idempotency_key},
        json=payload
    )
    assert res2.status_code == 201
    assert res2.headers.get("X-Idempotency-Replay") == "true"
    assert res2.json()["id"] == item_id

    # Verify only 1 work item was created
    list_res = client.get("/api/work-items?search=Automated+Kafka+MirrorMaker")
    assert list_res.json()["total"] == 1

def test_idempotent_approval_retry(client):
    """
    DANGEROUS SCENARIO:
    Finance executive submits a $18,500 refund approval. Due to slow mobile Wi-Fi,
    the client retries the POST request.
    CRITICAL BEHAVIOR:
    The approval must execute once. The second call must replay the response
    without double-incrementing the version or appending redundant approval events.
    """
    item_id = "wi_p2_refund_acme"
    idempotency_key = f"idem_approve_{uuid.uuid4().hex}"
    payload = {
        "expected_version": 1,
        "approved": True,
        "notes": "Approved per executive agreement."
    }

    # First submission
    r1 = client.post(
        f"/api/work-items/{item_id}/approve",
        headers={"X-User-Id": "usr_carol", "Idempotency-Key": idempotency_key},
        json=payload
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "IN_PROGRESS"
    assert r1.json()["version"] == 2

    # Second submission (replay)
    r2 = client.post(
        f"/api/work-items/{item_id}/approve",
        headers={"X-User-Id": "usr_carol", "Idempotency-Key": idempotency_key},
        json=payload
    )
    assert r2.status_code == 200
    assert r2.headers.get("X-Idempotency-Replay") == "true"
    assert r2.json()["version"] == 2

    # Verify audit log contains exactly 1 APPROVED event
    detail_res = client.get(f"/api/work-items/{item_id}")
    approval_events = [e for e in detail_res.json()["events"] if e["event_type"] == "APPROVED"]
    assert len(approval_events) == 1

def test_idempotency_key_payload_conflict_rejected(client):
    """
    DANGEROUS SCENARIO:
    A client bug attempts to reuse an existing idempotency key with a DIFFERENT payload.
    CRITICAL BEHAVIOR:
    Server must detect payload hash mismatch and reject with 422 Unprocessable Entity.
    """
    idempotency_key = f"idem_conflict_{uuid.uuid4().hex}"
    
    # Original request
    r1 = client.post(
        "/api/work-items",
        headers={"X-User-Id": "usr_alice", "Idempotency-Key": idempotency_key},
        json={
            "title": "First Original Task",
            "description": "Original description for first task",
            "category": "operational_task",
            "priority": "P3",
            "assigned_team": "tier1_support"
        }
    )
    assert r1.status_code == 201

    # Conflicting reuse with different title/payload
    r2 = client.post(
        "/api/work-items",
        headers={"X-User-Id": "usr_alice", "Idempotency-Key": idempotency_key},
        json={
            "title": "Completely Different Task Reusing Key",
            "description": "Conflicting payload",
            "category": "operational_task",
            "priority": "P2",
            "assigned_team": "tier1_support"
        }
    )
    assert r2.status_code == 422
    assert "Idempotency Key Conflict" in r2.json()["detail"]
