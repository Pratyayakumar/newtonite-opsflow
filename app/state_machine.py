from typing import List, Dict, Tuple, Optional
from fastapi import HTTPException, status
from app.models import WorkStatus, NextAction, UserInfo

VALID_TRANSITIONS: Dict[str, List[str]] = {
    WorkStatus.TRIAGE.value: [
        WorkStatus.IN_INVESTIGATION.value,
        WorkStatus.PENDING_APPROVAL.value,
        WorkStatus.IN_PROGRESS.value,
        WorkStatus.CANCELLED.value,
    ],
    WorkStatus.IN_INVESTIGATION.value: [
        WorkStatus.PENDING_APPROVAL.value,
        WorkStatus.IN_PROGRESS.value,
        WorkStatus.BLOCKED.value,
        WorkStatus.CANCELLED.value,
    ],
    WorkStatus.PENDING_APPROVAL.value: [
        WorkStatus.IN_PROGRESS.value,       # Allowed via approval workflow
        WorkStatus.IN_INVESTIGATION.value,
        WorkStatus.CANCELLED.value,         # Allowed via rejection workflow
    ],
    WorkStatus.IN_PROGRESS.value: [
        WorkStatus.PENDING_APPROVAL.value,
        WorkStatus.BLOCKED.value,
        WorkStatus.RESOLVED.value,
        WorkStatus.CANCELLED.value,
    ],
    WorkStatus.BLOCKED.value: [
        WorkStatus.IN_PROGRESS.value,
        WorkStatus.IN_INVESTIGATION.value,
        WorkStatus.CANCELLED.value,
    ],
    WorkStatus.RESOLVED.value: [
        WorkStatus.IN_INVESTIGATION.value,  # Re-open
    ],
    WorkStatus.CANCELLED.value: [],         # Terminal state
}

def validate_transition(
    current_status: str,
    target_status: str,
    work_item: dict,
    user: UserInfo,
    resolution_notes: Optional[str] = None
) -> None:
    """
    Validates state machine transitions against the allowable graph and business guards.
    """
    if current_status == target_status:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Work item is already in status '{current_status}'."
        )

    allowed_targets = VALID_TRANSITIONS.get(current_status, [])
    if target_status not in allowed_targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Illegal State Machine Transition: Cannot move from '{current_status}' to '{target_status}'. "
                f"Valid next states are: {allowed_targets or ['None (terminal state)']}"
            )
        )

    # Guard 1: Resolution notes required for RESOLVED
    if target_status == WorkStatus.RESOLVED.value:
        if not resolution_notes or len(resolution_notes.strip()) < 5:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Guard Failure: Transitioning to RESOLVED requires comprehensive resolution_notes (at least 5 characters)."
            )

    # Guard 2: Direct bypass of PENDING_APPROVAL via plain status update
    if current_status == WorkStatus.PENDING_APPROVAL.value and target_status == WorkStatus.IN_PROGRESS.value:
        # Must be approved through approval endpoint, not manual status override unless ops_admin
        if "ops_admin" not in user.teams:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Guard Failure: Items in PENDING_APPROVAL must be advanced using the formal /approve endpoint with reviewer attestation."
            )

    # Guard 3: Re-opening a RESOLVED item requires team lead or ops_admin
    if current_status == WorkStatus.RESOLVED.value:
        if "ops_admin" not in user.teams:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Guard Failure: Re-opening a RESOLVED item is restricted to 'ops_admin'."
            )

    # Guard 4: Must have an assignee to be IN_PROGRESS
    if target_status == WorkStatus.IN_PROGRESS.value:
        assignee_id = work_item.get("assignee_id")
        if not assignee_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Guard Failure: Cannot move work item to IN_PROGRESS without an active assignee. Claim or assign the item first."
            )

def compute_next_actions(work_item: dict, viewer: Optional[UserInfo] = None) -> List[NextAction]:
    """
    Computes dynamic, contextual 'Next Required Actions' for a work item
    based on current status, assignment, category, and viewer privileges.
    """
    actions: List[NextAction] = []
    status = work_item["status"]
    assigned_team = work_item["assigned_team"]
    assignee_id = work_item["assignee_id"]
    category = work_item["category"]

    viewer_teams = set(viewer.teams) if viewer else set()
    is_admin = "ops_admin" in viewer_teams
    is_team_member = assigned_team in viewer_teams or is_admin
    is_assignee = (viewer and viewer.id == assignee_id) or is_admin

    if not assignee_id and status in (WorkStatus.TRIAGE.value, WorkStatus.IN_INVESTIGATION.value):
        actions.append(NextAction(
            action_type="CLAIM",
            label="Claim Ownership",
            description=f"Take responsibility for this {category} within team {assigned_team}.",
            allowed_roles_or_teams=[assigned_team, "ops_admin"],
            permitted_for_viewer=is_team_member
        ))

    if status == WorkStatus.TRIAGE.value:
        actions.append(NextAction(
            action_type="INVESTIGATE",
            label="Begin Investigation",
            description="Move to IN_INVESTIGATION to begin root cause analysis or reproduce issue.",
            allowed_roles_or_teams=[assigned_team, "ops_admin"],
            permitted_for_viewer=is_team_member
        ))

    elif status == WorkStatus.PENDING_APPROVAL.value:
        required_team = "finance_approvals" if (assigned_team == "finance_approvals" or category == "approval_request") else ("secops" if assigned_team == "secops" else assigned_team)
        can_approve = (required_team in viewer_teams or is_admin) and not (viewer and viewer.id == work_item.get("creator_id") and work_item.get("priority") in ("P0", "P1"))
        
        actions.append(NextAction(
            action_type="APPROVE",
            label="Review & Approve",
            description=f"Formal review required by {required_team} before execution can proceed.",
            allowed_roles_or_teams=[required_team, "ops_admin"],
            permitted_for_viewer=can_approve
        ))
        actions.append(NextAction(
            action_type="REJECT",
            label="Reject & Cancel",
            description=f"Decline approval and cancel this request.",
            allowed_roles_or_teams=[required_team, "ops_admin"],
            permitted_for_viewer=can_approve
        ))

    elif status == WorkStatus.IN_PROGRESS.value:
        actions.append(NextAction(
            action_type="RESOLVE",
            label="Mark as Resolved",
            description="Complete the work and record formal resolution notes.",
            allowed_roles_or_teams=[assigned_team, "ops_admin"],
            permitted_for_viewer=is_assignee or is_team_member
        ))
        actions.append(NextAction(
            action_type="REQUEST_APPROVAL",
            label="Escalate for Approval",
            description="Pause execution and escalate for managerial or cross-functional sign-off.",
            allowed_roles_or_teams=[assigned_team, "ops_admin"],
            permitted_for_viewer=is_assignee or is_team_member
        ))
        actions.append(NextAction(
            action_type="BLOCK",
            label="Mark as Blocked",
            description="Flag dependency blocker or external impediment.",
            allowed_roles_or_teams=[assigned_team, "ops_admin"],
            permitted_for_viewer=is_assignee or is_team_member
        ))

    elif status == WorkStatus.BLOCKED.value:
        actions.append(NextAction(
            action_type="UNBLOCK",
            label="Unblock & Resume",
            description="Blocker cleared; resume active execution in IN_PROGRESS.",
            allowed_roles_or_teams=[assigned_team, "ops_admin"],
            permitted_for_viewer=is_assignee or is_team_member
        ))

    return actions
