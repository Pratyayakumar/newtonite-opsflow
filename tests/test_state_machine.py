import pytest

def test_illegal_state_jump_rejected(client):
    """
    DANGEROUS SCENARIO:
    An operator attempts to jump directly from TRIAGE to RESOLVED,
    skipping necessary investigation and operational progress.
    CRITICAL BEHAVIOR:
    State machine graph validation must block illegal edge with 400 Bad Request.
    """
    item_id = "wi_p0_unassigned_gateway" # Status: TRIAGE

    res = client.post(
        f"/api/work-items/{item_id}/transition",
        headers={"X-User-Id": "usr_bob"},
        json={
            "expected_version": 1,
            "target_status": "RESOLVED",
            "reason": "Trying to bypass workflow",
            "resolution_notes": "Premature resolution"
        }
    )
    assert res.status_code == 400
    assert "Illegal State Machine Transition" in res.json()["detail"]

def test_resolve_guard_requires_resolution_notes(client):
    """
    DANGEROUS SCENARIO:
    An engineer attempts to mark an active IN_PROGRESS incident as RESOLVED
    without providing mandatory resolution notes explaining the fix.
    CRITICAL BEHAVIOR:
    Transition guard must reject with 422 Unprocessable Entity.
    """
    item_id = "wi_p1_auth_memory" # Status: IN_PROGRESS

    res = client.post(
        f"/api/work-items/{item_id}/transition",
        headers={"X-User-Id": "usr_eve"},
        json={
            "expected_version": 1,
            "target_status": "RESOLVED",
            "reason": "Fixed issue",
            "resolution_notes": "" # Missing notes
        }
    )
    assert res.status_code == 422
    assert "Guard Failure: Transitioning to RESOLVED requires comprehensive resolution_notes" in res.json()["detail"]

def test_approval_bypass_blocked(client):
    """
    DANGEROUS SCENARIO:
    A user attempts to bypass the formal approval workflow by sending a plain
    transition from PENDING_APPROVAL to IN_PROGRESS.
    CRITICAL BEHAVIOR:
    System must reject the bypass with 400 Bad Request, requiring the /approve endpoint.
    """
    item_id = "wi_p2_refund_acme" # Status: PENDING_APPROVAL

    res = client.post(
        f"/api/work-items/{item_id}/transition",
        headers={"X-User-Id": "usr_carol"},
        json={
            "expected_version": 1,
            "target_status": "IN_PROGRESS",
            "reason": "Bypassing formal approval"
        }
    )
    assert res.status_code == 400
    assert "must be advanced using the formal /approve endpoint" in res.json()["detail"]

def test_next_actions_computation(client):
    """
    SCENARIO:
    Inspect computed next required actions for an unassigned incident.
    CRITICAL BEHAVIOR:
    Actions must list 'CLAIM' as permitted for incident_response members (Bob),
    but NOT permitted for tier1_support members (Alice).
    """
    item_id = "wi_p0_unassigned_gateway"

    # Alice views item
    r_alice = client.get(f"/api/work-items/{item_id}", headers={"X-User-Id": "usr_alice"})
    actions_alice = {a["action_type"]: a["permitted_for_viewer"] for a in r_alice.json()["next_required_actions"]}
    assert actions_alice["CLAIM"] is False

    # Bob views item
    r_bob = client.get(f"/api/work-items/{item_id}", headers={"X-User-Id": "usr_bob"})
    actions_bob = {a["action_type"]: a["permitted_for_viewer"] for a in r_bob.json()["next_required_actions"]}
    assert actions_bob["CLAIM"] is True
