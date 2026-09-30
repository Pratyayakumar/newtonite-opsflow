from typing import List, Optional
from fastapi import Request, HTTPException, status
from app.database import get_db_connection
from app.models import UserInfo

def get_current_user_from_db(user_id: str) -> Optional[UserInfo]:
    conn = get_db_connection()
    try:
        user_row = conn.execute("SELECT id, name, email, title FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user_row:
            return None
        teams_rows = conn.execute("SELECT team_id FROM team_memberships WHERE user_id = ?", (user_id,)).fetchall()
        teams = [r["team_id"] for r in teams_rows]
        return UserInfo(
            id=user_row["id"],
            name=user_row["name"],
            email=user_row["email"],
            title=user_row["title"],
            teams=teams
        )
    finally:
        conn.close()

def get_current_user(request: Request) -> UserInfo:
    """
    Extract user from X-User-Id header, cookie, or query param.
    Defaults to 'usr_alice' (Tier 1 Support Lead) if not provided.
    """
    user_id = (
        request.headers.get("X-User-Id")
        or request.cookies.get("user_id")
        or request.query_params.get("user_id")
        or "usr_alice"
    )
    
    user = get_current_user_from_db(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"User identity '{user_id}' does not exist in the system."
        )
    return user

def check_permission_to_claim(user: UserInfo, work_item: dict) -> None:
    """
    User can only claim an item if:
    1. They belong to the assigned team, OR
    2. They belong to ops_admin
    """
    assigned_team = work_item["assigned_team"]
    user_teams = set(user.teams)
    
    if "ops_admin" in user_teams:
        return
        
    if assigned_team not in user_teams:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Authorization Failure: User '{user.name}' ({user.id}) belongs to teams "
                f"[{', '.join(user.teams)}], but item '{work_item['id']}' is assigned to team '{assigned_team}'. "
                f"Only members of '{assigned_team}' or 'ops_admin' may claim this work item."
            )
        )

def check_permission_to_transition(user: UserInfo, work_item: dict, target_status: str) -> None:
    """
    Enforces server-side permissions for state transitions.
    """
    user_teams = set(user.teams)
    is_admin = "ops_admin" in user_teams
    assigned_team = work_item["assigned_team"]
    is_team_member = assigned_team in user_teams
    is_assignee = work_item["assignee_id"] == user.id

    if is_admin:
        return

    # To work on or resolve an item, user must be the assignee or a member of the assigned team
    if not (is_assignee or is_team_member):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Authorization Failure: Transitioning work item '{work_item['id']}' to '{target_status}' "
                f"requires being assigned to the item or being a member of '{assigned_team}'. "
                f"User teams: [{', '.join(user.teams)}]."
            )
        )

def check_permission_to_approve(user: UserInfo, work_item: dict) -> None:
    """
    Enforces strict authorization for approvals:
    - Finance approval requests require membership in 'finance_approvals' or 'ops_admin'.
    - Security-related investigations/incidents require membership in 'secops' or 'ops_admin'.
    - Self-approval restriction: Creator cannot approve their own high-severity request.
    """
    user_teams = set(user.teams)
    category = work_item["category"]
    priority = work_item["priority"]
    creator_id = work_item["creator_id"]
    assigned_team = work_item["assigned_team"]

    if "ops_admin" in user_teams:
        # Admins can approve, but let's check self-approval guard if P0
        if priority == "P0" and creator_id == user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Separation of Duties Violation: You cannot approve your own P0 critical work item."
            )
        return

    if assigned_team == "finance_approvals" or category == "approval_request":
        if "finance_approvals" not in user_teams:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Authorization Failure: Approval for item '{work_item['id']}' requires 'finance_approvals' team membership. "
                    f"User '{user.name}' has teams: [{', '.join(user.teams)}]."
                )
            )

    if assigned_team == "secops":
        if "secops" not in user_teams:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Authorization Failure: Security item approval requires 'secops' team membership. "
                    f"User '{user.name}' has teams: [{', '.join(user.teams)}]."
                )
            )

    # General self-approval guard for high priority items
    if creator_id == user.id and priority in ("P0", "P1"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Separation of Duties: Creator cannot approve their own P0/P1 operational item."
        )
