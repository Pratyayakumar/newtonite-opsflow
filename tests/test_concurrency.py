import concurrent.futures
import pytest
from starlette.testclient import TestClient
from app.main import app

def test_concurrent_claim_race_condition(client):
    """
    DANGEROUS SCENARIO:
    Two operators (Bob and Eve, both belonging to incident_response) attempt to claim
    the exact same unassigned P0 incident simultaneously over the network.
    CRITICAL BEHAVIOR:
    The database must serialize the claim conditionally. Exactly ONE must succeed (200 OK),
    and the other MUST fail with 409 Conflict without corrupting state.
    """
    target_item_id = "wi_p0_unassigned_gateway"

    # Verify initial item state is unassigned at version 1
    resp = client.get(f"/api/work-items/{target_item_id}", headers={"X-User-Id": "usr_bob"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["assignee_id"] is None
    expected_version = data["version"]

    def attempt_claim(user_id):
        # Create dedicated test client for concurrent request simulation
        with TestClient(app) as local_client:
            return local_client.post(
                f"/api/work-items/{target_item_id}/claim",
                headers={"X-User-Id": user_id},
                json={"expected_version": expected_version}
            )

    # Fire concurrent claim requests
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(attempt_claim, "usr_bob")
        f2 = executor.submit(attempt_claim, "usr_eve")
        res1 = f1.result()
        res2 = f2.result()

    status_codes = sorted([res1.status_code, res2.status_code])
    assert status_codes == [200, 409], f"Expected exactly one 200 and one 409, got {status_codes}"

    # Verify final persistent state has exactly one owner and incremented version
    final_resp = client.get(f"/api/work-items/{target_item_id}")
    assert final_resp.status_code == 200
    final_data = final_resp.json()
    assert final_data["assignee_id"] in ("usr_bob", "usr_eve")
    assert final_data["version"] == expected_version + 1

def test_optimistic_concurrency_stale_update_rejected(client):
    """
    DANGEROUS SCENARIO:
    Operator A and Operator B both load work item at version 1.
    Operator A moves it to IN_INVESTIGATION (bumping version to 2).
    Operator B subsequently submits a transition based on stale version 1.
    CRITICAL BEHAVIOR:
    Operator B's request must be rejected with 409 Conflict.
    Operator A's changes must NOT be silently clobbered.
    """
    item_id = "wi_p2_csv_export"

    # Step 1: User Alice (Tier 1 Support) transitions the item from TRIAGE to IN_INVESTIGATION
    r1 = client.post(
        f"/api/work-items/{item_id}/transition",
        headers={"X-User-Id": "usr_alice"},
        json={
            "expected_version": 1,
            "target_status": "IN_INVESTIGATION",
            "reason": "Reproduced customer timeout on large CSV payloads"
        }
    )
    assert r1.status_code == 200
    assert r1.json()["version"] == 2

    # Step 2: User Frank submits an update with stale version 1
    r2 = client.post(
        f"/api/work-items/{item_id}/transition",
        headers={"X-User-Id": "usr_frank"},
        json={
            "expected_version": 1,
            "target_status": "CANCELLED",
            "reason": "Attempting stale cancellation"
        }
    )
    assert r2.status_code == 409
    detail = r2.json()["detail"]
    assert detail["error"] == "OPTIMISTIC_CONCURRENCY_CONFLICT"
    assert detail["expected_version"] == 1
    assert detail["current_version"] == 2

    # Step 3: Verify item remains in IN_INVESTIGATION at version 2
    r_check = client.get(f"/api/work-items/{item_id}")
    assert r_check.json()["status"] == "IN_INVESTIGATION"
    assert r_check.json()["version"] == 2
