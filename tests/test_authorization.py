import pytest

def test_cross_team_claim_rejected(client):
    """
    DANGEROUS SCENARIO:
    A user belonging only to 'tier1_support' attempts to claim a P0 emergency incident
    assigned strictly to 'incident_response'.
    CRITICAL BEHAVIOR:
    Server-side authorization must block the claim with 403 Forbidden.
    Hiding buttons in the frontend is not trusted.
    """
    item_id = "wi_p0_unassigned_gateway" # assigned_team: incident_response

    res = client.post(
        f"/api/work-items/{item_id}/claim",
        headers={"X-User-Id": "usr_alice"}, # Alice belongs only to tier1_support
        json={"expected_version": 1}
    )
    assert res.status_code == 403
    assert "Authorization Failure" in res.json()["detail"]

    # Verify item remains unassigned
    check = client.get(f"/api/work-items/{item_id}")
    assert check.json()["assignee_id"] is None

def test_unauthorized_approval_rejected(client):
    """
    DANGEROUS SCENARIO:
    An incident engineer (Bob) attempts to approve an $18,500 financial refund
    assigned to 'finance_approvals'.
    CRITICAL BEHAVIOR:
    The request must be rejected with 403 Forbidden.
    Only authorized members of finance_approvals or ops_admin can approve.
    """
    item_id = "wi_p2_refund_acme"

    res = client.post(
        f"/api/work-items/{item_id}/approve",
        headers={"X-User-Id": "usr_bob"}, # Bob is incident_response only
        json={
            "expected_version": 1,
            "approved": True,
            "notes": "Unauthorized approval attempt"
        }
    )
    assert res.status_code == 403
    assert "requires 'finance_approvals'" in res.json()["detail"]

def test_multi_team_user_permitted(client):
    """
    SCENARIO:
    User Frank belongs to both 'tier1_support' AND 'finance_approvals'.
    CRITICAL BEHAVIOR:
    Frank must be permitted to participate in both team workflows.
    """
    # 1. Frank claims an unassigned finance approval
    item_id = "wi_p2_unassigned_refund"
    res = client.post(
        f"/api/work-items/{item_id}/claim",
        headers={"X-User-Id": "usr_frank"},
        json={"expected_version": 1}
    )
    assert res.status_code == 200
    assert res.json()["assignee_id"] == "usr_frank"

def test_separation_of_duties_self_approval_blocked(client):
    """
    DANGEROUS SCENARIO:
    Creator of a high-severity (P0) item attempts to approve their own request.
    CRITICAL BEHAVIOR:
    Separation of duties guard must reject with 403 Forbidden.
    """
    # Create P0 item as Eve
    create_res = client.post(
        "/api/work-items",
        headers={"X-User-Id": "usr_eve"},
        json={
            "title": "Emergency Production Core Router Bypass",
            "description": "Bypassing primary border gateway protocol filter.",
            "category": "approval_request",
            "priority": "P0",
            "assigned_team": "ops_admin"
        }
    )
    assert create_res.status_code == 201
    item_id = create_res.json()["id"]

    # Eve tries to approve her own P0 request
    approve_res = client.post(
        f"/api/work-items/{item_id}/approve",
        headers={"X-User-Id": "usr_eve"},
        json={
            "expected_version": 1,
            "approved": True,
            "notes": "Attempting self-approval"
        }
    )
    assert approve_res.status_code == 403
    assert "Separation of Duties" in approve_res.json()["detail"]
