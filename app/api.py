import json
import uuid
import sqlite3
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Header, Query
from app.config import DB_PATH
from app.database import get_db_connection, db_transaction, get_utc_now_iso
from app.models import (
    UserInfo, TeamInfo, WorkItemCreate, WorkItemClaimRequest, 
    WorkItemTransitionRequest, WorkItemApprovalRequest, AddCommentRequest,
    WorkItemResponse, PaginatedWorkItems, DashboardKPIs, AsyncJobResponse,
    WorkStatus, WorkPriority, SlaRiskLevel, WorkCategory
)
from app.auth import (
    get_current_user, check_permission_to_claim, 
    check_permission_to_transition, check_permission_to_approve
)
from app.state_machine import validate_transition, compute_next_actions
from app.concurrency import verify_and_increment_version, atomic_claim_work_item
from app.idempotency import compute_payload_hash, check_idempotency, record_idempotency
from app.async_worker import enqueue_job, run_due_jobs

router = APIRouter()

def serialize_work_item_row(row: sqlite3.Row, viewer: Optional[UserInfo] = None, include_events: bool = False, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    item_dict = dict(row)
    item_dict["sla_breached"] = bool(item_dict["sla_breached"])
    try:
        item_dict["metadata"] = json.loads(item_dict.get("metadata_json") or "{}")
    except Exception:
        item_dict["metadata"] = {}

    item_dict["next_required_actions"] = [
        a.model_dump() if hasattr(a, "model_dump") else a 
        for a in compute_next_actions(item_dict, viewer)
    ]

    if include_events and conn:
        event_rows = conn.execute(
            """
            SELECT id, work_item_id, actor_id, actor_name, event_type, from_state, to_state, details_json, created_at
            FROM work_item_events
            WHERE work_item_id = ?
            ORDER BY created_at DESC
            """,
            (item_dict["id"],)
        ).fetchall()
        events = []
        for er in event_rows:
            ed = dict(er)
            try:
                ed["details"] = json.loads(ed.get("details_json") or "{}")
            except Exception:
                ed["details"] = {}
            events.append(ed)
        item_dict["events"] = events

    return item_dict

# ----------------- IDENTITY & TEAMS -----------------

@router.get("/me", response_model=UserInfo)
def get_my_profile(current_user: UserInfo = Depends(get_current_user)):
    return current_user

@router.get("/users", response_model=List[UserInfo])
def list_users():
    conn = get_db_connection()
    try:
        users_rows = conn.execute("SELECT id, name, email, title FROM users ORDER BY name").fetchall()
        results = []
        for u in users_rows:
            teams_rows = conn.execute("SELECT team_id FROM team_memberships WHERE user_id = ?", (u["id"],)).fetchall()
            results.append(UserInfo(
                id=u["id"],
                name=u["name"],
                email=u["email"],
                title=u["title"],
                teams=[t["team_id"] for t in teams_rows]
            ))
        return results
    finally:
        conn.close()

@router.get("/teams", response_model=List[TeamInfo])
def list_teams():
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT t.id, t.name, t.description, COUNT(tm.user_id) as member_count
            FROM teams t
            LEFT JOIN team_memberships tm ON t.id = tm.team_id
            GROUP BY t.id
            ORDER BY t.name
            """
        ).fetchall()
        return [TeamInfo(**dict(r)) for r in rows]
    finally:
        conn.close()

# ----------------- DASHBOARD OVERVIEW -----------------

@router.get("/dashboard")
def get_dashboard_overview(current_user: UserInfo = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        user_teams_sql = ",".join(f"'{t}'" for t in current_user.teams) or "''"

        # High-performance single aggregation query using indexed expressions
        summary_row = conn.execute(
            f"""
            SELECT 
                COUNT(*) as total_count,
                SUM(CASE WHEN status NOT IN ('RESOLVED', 'CANCELLED') THEN 1 ELSE 0 END) as total_active,
                SUM(CASE WHEN status = 'TRIAGE' THEN 1 ELSE 0 END) as triage_count,
                SUM(CASE WHEN status = 'PENDING_APPROVAL' THEN 1 ELSE 0 END) as pending_approvals_count,
                SUM(CASE WHEN sla_risk_level = 'BREACHED' AND status NOT IN ('RESOLVED', 'CANCELLED') THEN 1 ELSE 0 END) as sla_breach_count,
                SUM(CASE WHEN sla_risk_level = 'WARN' AND status NOT IN ('RESOLVED', 'CANCELLED') THEN 1 ELSE 0 END) as sla_warn_count,
                SUM(CASE WHEN assignee_id = ? AND status NOT IN ('RESOLVED', 'CANCELLED') THEN 1 ELSE 0 END) as my_assigned_count,
                SUM(CASE WHEN assigned_team IN ({user_teams_sql}) AND status NOT IN ('RESOLVED', 'CANCELLED') THEN 1 ELSE 0 END) as my_team_active_count
            FROM work_items
            """,
            (current_user.id,)
        ).fetchone()

        # Priority breakdown
        priority_rows = conn.execute(
            """
            SELECT priority, COUNT(*) as count 
            FROM work_items 
            WHERE status NOT IN ('RESOLVED', 'CANCELLED') 
            GROUP BY priority
            """
        ).fetchall()
        by_priority = {r["priority"]: r["count"] for r in priority_rows}

        # Status breakdown
        status_rows = conn.execute(
            """
            SELECT status, COUNT(*) as count 
            FROM work_items 
            GROUP BY status
            """
        ).fetchall()
        by_status = {r["status"]: r["count"] for r in status_rows}

        # Top Attention Queues (Limited to 5 per queue for fast instant triage view)
        triage_queue = conn.execute(
            """
            SELECT w.*, u.name as creator_name, t.name as assigned_team_name 
            FROM work_items w
            LEFT JOIN users u ON w.creator_id = u.id
            LEFT JOIN teams t ON w.assigned_team = t.id
            WHERE w.status = 'TRIAGE'
            ORDER BY CASE w.priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END, w.created_at ASC
            LIMIT 5
            """
        ).fetchall()

        approvals_queue = conn.execute(
            """
            SELECT w.*, u.name as creator_name, t.name as assigned_team_name 
            FROM work_items w
            LEFT JOIN users u ON w.creator_id = u.id
            LEFT JOIN teams t ON w.assigned_team = t.id
            WHERE w.status = 'PENDING_APPROVAL'
            ORDER BY CASE w.priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END, w.created_at ASC
            LIMIT 5
            """
        ).fetchall()

        sla_risk_queue = conn.execute(
            """
            SELECT w.*, u.name as creator_name, a.name as assignee_name, t.name as assigned_team_name 
            FROM work_items w
            LEFT JOIN users u ON w.creator_id = u.id
            LEFT JOIN users a ON w.assignee_id = a.id
            LEFT JOIN teams t ON w.assigned_team = t.id
            WHERE w.sla_risk_level IN ('BREACHED', 'WARN') AND w.status NOT IN ('RESOLVED', 'CANCELLED')
            ORDER BY CASE w.sla_risk_level WHEN 'BREACHED' THEN 0 ELSE 1 END, w.created_at ASC
            LIMIT 5
            """
        ).fetchall()

        my_items = conn.execute(
            """
            SELECT w.*, u.name as creator_name, a.name as assignee_name, t.name as assigned_team_name 
            FROM work_items w
            LEFT JOIN users u ON w.creator_id = u.id
            LEFT JOIN users a ON w.assignee_id = a.id
            LEFT JOIN teams t ON w.assigned_team = t.id
            WHERE w.assignee_id = ? AND w.status NOT IN ('RESOLVED', 'CANCELLED')
            ORDER BY CASE w.priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END, w.updated_at DESC
            LIMIT 5
            """,
            (current_user.id,)
        ).fetchall()

        return {
            "kpis": {
                "total_active": summary_row["total_active"] or 0,
                "triage_count": summary_row["triage_count"] or 0,
                "pending_approvals_count": summary_row["pending_approvals_count"] or 0,
                "sla_breach_count": summary_row["sla_breach_count"] or 0,
                "sla_warn_count": summary_row["sla_warn_count"] or 0,
                "my_assigned_count": summary_row["my_assigned_count"] or 0,
                "my_team_active_count": summary_row["my_team_active_count"] or 0,
                "by_priority": by_priority,
                "by_status": by_status,
            },
            "queues": {
                "triage": [serialize_work_item_row(r, current_user) for r in triage_queue],
                "approvals": [serialize_work_item_row(r, current_user) for r in approvals_queue],
                "sla_risks": [serialize_work_item_row(r, current_user) for r in sla_risk_queue],
                "my_items": [serialize_work_item_row(r, current_user) for r in my_items],
            }
        }
    finally:
        conn.close()

# ----------------- WORK ITEMS LIST & PAGINATION -----------------

@router.get("/work-items", response_model=PaginatedWorkItems)
def list_work_items(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    assigned_team: Optional[str] = None,
    assignee_id: Optional[str] = None,
    sla_risk_level: Optional[str] = None,
    unassigned_only: Optional[bool] = False,
    search: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: UserInfo = Depends(get_current_user)
):
    conn = get_db_connection()
    try:
        where_clauses = []
        params = []

        if status:
            where_clauses.append("w.status = ?")
            params.append(status)
        if priority:
            where_clauses.append("w.priority = ?")
            params.append(priority)
        if category:
            where_clauses.append("w.category = ?")
            params.append(category)
        if assigned_team:
            where_clauses.append("w.assigned_team = ?")
            params.append(assigned_team)
        if assignee_id:
            where_clauses.append("w.assignee_id = ?")
            params.append(assignee_id)
        if unassigned_only:
            where_clauses.append("(w.assignee_id IS NULL OR w.assignee_id = '')")
        if sla_risk_level:
            where_clauses.append("w.sla_risk_level = ?")
            params.append(sla_risk_level)
        if search:
            where_clauses.append("(w.title LIKE ? OR w.description LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # Total count query
        count_query = f"SELECT COUNT(*) as total FROM work_items w {where_sql}"
        total = conn.execute(count_query, params).fetchone()["total"]

        # Scalable indexed paginated query
        data_query = f"""
            SELECT w.*, u.name as creator_name, a.name as assignee_name, t.name as assigned_team_name
            FROM work_items w
            LEFT JOIN users u ON w.creator_id = u.id
            LEFT JOIN users a ON w.assignee_id = a.id
            LEFT JOIN teams t ON w.assigned_team = t.id
            {where_sql}
            ORDER BY 
                CASE w.priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                w.created_at DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(data_query, params + [limit, offset]).fetchall()

        items = [serialize_work_item_row(r, current_user) for r in rows]

        return PaginatedWorkItems(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
            has_more=(offset + limit) < total
        )
    finally:
        conn.close()

# ----------------- CREATE WORK ITEM (IDEMPOTENT) -----------------

@router.post("/work-items", response_model=WorkItemResponse)
def create_work_item(
    payload: WorkItemCreate,
    request: Request,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: UserInfo = Depends(get_current_user)
):
    req_hash = compute_payload_hash(payload.model_dump())
    
    # Check Idempotency if provided
    if idempotency_key:
        conn = get_db_connection()
        try:
            cached = check_idempotency(conn, idempotency_key, current_user.id, request.url.path, req_hash)
            if cached:
                cached_status, cached_body = cached
                response.headers["X-Idempotency-Replay"] = "true"
                response.status_code = cached_status
                return cached_body
        finally:
            conn.close()

    # Determine default SLA target minutes based on priority if not specified
    sla_defaults = {
        WorkPriority.P0: 60,
        WorkPriority.P1: 120,
        WorkPriority.P2: 480,
        WorkPriority.P3: 1440
    }
    target_sla = payload.target_sla_minutes or sla_defaults.get(payload.priority, 240)
    work_item_id = f"wi_{uuid.uuid4().hex[:10]}"
    now = get_utc_now_iso()

    # Set initial status: approval_request starts in PENDING_APPROVAL, others in TRIAGE
    initial_status = WorkStatus.PENDING_APPROVAL.value if payload.category == WorkCategory.APPROVAL_REQUEST else WorkStatus.TRIAGE.value

    with db_transaction() as tx:
        tx.execute(
            """
            INSERT INTO work_items (
                id, title, description, category, status, priority, creator_id, assignee_id, assigned_team,
                version, target_sla_minutes, created_at, updated_at, sla_breached, sla_risk_level, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 1, ?, ?, ?, 0, 'NORMAL', ?)
            """,
            (
                work_item_id, payload.title, payload.description, payload.category.value,
                initial_status, payload.priority.value, current_user.id, payload.assigned_team,
                target_sla, now, now, json.dumps(payload.metadata or {})
            )
        )

        # Audit Event
        tx.execute(
            """
            INSERT INTO work_item_events (id, work_item_id, actor_id, actor_name, event_type, from_state, to_state, details_json, created_at)
            VALUES (?, ?, ?, ?, 'CREATED', NULL, ?, ?, ?)
            """,
            (
                f"evt_{uuid.uuid4().hex[:12]}",
                work_item_id,
                current_user.id,
                current_user.name,
                initial_status,
                json.dumps({"priority": payload.priority.value, "assigned_team": payload.assigned_team}),
                now
            )
        )

        # Enqueue Asynchronous Secondary Tasks
        enqueue_job(tx, "SLA_ENRICHMENT", work_item_id, {"initial_sla": target_sla}, delay_seconds=0)
        enqueue_job(tx, "NOTIFICATION_DISPATCH", work_item_id, {
            "recipient": payload.assigned_team,
            "subject": f"[{payload.priority.value}] New {payload.category.value}: {payload.title[:50]}",
            "channels": ["slack", "email"]
        }, delay_seconds=1)

    # Fetch created record to return
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT w.*, u.name as creator_name, a.name as assignee_name, t.name as assigned_team_name
            FROM work_items w
            LEFT JOIN users u ON w.creator_id = u.id
            LEFT JOIN users a ON w.assignee_id = a.id
            LEFT JOIN teams t ON w.assigned_team = t.id
            WHERE w.id = ?
            """,
            (work_item_id,)
        ).fetchone()
        result = serialize_work_item_row(row, current_user, include_events=True, conn=conn)

        if idempotency_key:
            record_idempotency(conn, idempotency_key, current_user.id, request.url.path, req_hash, 201, result)
            conn.commit()

        response.status_code = status.HTTP_201_CREATED
        return result
    finally:
        conn.close()

# ----------------- GET WORK ITEM DETAIL & AUDIT TIMELINE -----------------

@router.get("/work-items/{work_item_id}", response_model=WorkItemResponse)
def get_work_item(work_item_id: str, current_user: UserInfo = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT w.*, u.name as creator_name, a.name as assignee_name, t.name as assigned_team_name
            FROM work_items w
            LEFT JOIN users u ON w.creator_id = u.id
            LEFT JOIN users a ON w.assignee_id = a.id
            LEFT JOIN teams t ON w.assigned_team = t.id
            WHERE w.id = ?
            """,
            (work_item_id,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Work item '{work_item_id}' not found.")

        return serialize_work_item_row(row, current_user, include_events=True, conn=conn)
    finally:
        conn.close()

# ----------------- ATOMIC CLAIM (RACE CONDITION PREVENTION) -----------------

@router.post("/work-items/{work_item_id}/claim", response_model=WorkItemResponse)
def claim_work_item(
    work_item_id: str,
    payload: WorkItemClaimRequest,
    request: Request,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: UserInfo = Depends(get_current_user)
):
    req_hash = compute_payload_hash(payload.model_dump())
    
    if idempotency_key:
        conn = get_db_connection()
        try:
            cached = check_idempotency(conn, idempotency_key, current_user.id, request.url.path, req_hash)
            if cached:
                cached_status, cached_body = cached
                response.headers["X-Idempotency-Replay"] = "true"
                response.status_code = cached_status
                return cached_body
        finally:
            conn.close()

    # Pre-check authorization at server/resource level
    conn = get_db_connection()
    try:
        item = conn.execute("SELECT * FROM work_items WHERE id = ?", (work_item_id,)).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Work item not found")
        check_permission_to_claim(current_user, dict(item))
    finally:
        conn.close()

    # Atomic OCC Claim execution
    with db_transaction() as tx:
        success, new_version, failure_reason = atomic_claim_work_item(
            tx, work_item_id, payload.expected_version, current_user.id
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "CONCURRENCY_CLAIM_CONFLICT",
                    "message": f"Claim failed: {failure_reason}",
                    "current_version": new_version,
                    "expected_version": payload.expected_version
                }
            )

        now = get_utc_now_iso()
        # Record Audit Event
        tx.execute(
            """
            INSERT INTO work_item_events (id, work_item_id, actor_id, actor_name, event_type, details_json, created_at)
            VALUES (?, ?, ?, ?, 'CLAIMED', ?, ?)
            """,
            (
                f"evt_{uuid.uuid4().hex[:12]}",
                work_item_id,
                current_user.id,
                current_user.name,
                json.dumps({"claimed_by": current_user.name, "user_id": current_user.id}),
                now
            )
        )
        # Secondary async notification
        enqueue_job(tx, "NOTIFICATION_DISPATCH", work_item_id, {
            "recipient": current_user.email,
            "subject": f"Ownership confirmed for work item {work_item_id}",
            "channels": ["slack"]
        })

    # Return updated item
    conn = get_db_connection()
    try:
        updated_row = conn.execute(
            """
            SELECT w.*, u.name as creator_name, a.name as assignee_name, t.name as assigned_team_name
            FROM work_items w
            LEFT JOIN users u ON w.creator_id = u.id
            LEFT JOIN users a ON w.assignee_id = a.id
            LEFT JOIN teams t ON w.assigned_team = t.id
            WHERE w.id = ?
            """,
            (work_item_id,)
        ).fetchone()
        result = serialize_work_item_row(updated_row, current_user, include_events=True, conn=conn)

        if idempotency_key:
            record_idempotency(conn, idempotency_key, current_user.id, request.url.path, req_hash, 200, result)
            conn.commit()

        return result
    finally:
        conn.close()

# ----------------- STATE MACHINE TRANSITIONS (GUARDED) -----------------

@router.post("/work-items/{work_item_id}/transition", response_model=WorkItemResponse)
def transition_work_item(
    work_item_id: str,
    payload: WorkItemTransitionRequest,
    request: Request,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: UserInfo = Depends(get_current_user)
):
    req_hash = compute_payload_hash(payload.model_dump())

    if idempotency_key:
        conn = get_db_connection()
        try:
            cached = check_idempotency(conn, idempotency_key, current_user.id, request.url.path, req_hash)
            if cached:
                cached_status, cached_body = cached
                response.headers["X-Idempotency-Replay"] = "true"
                response.status_code = cached_status
                return cached_body
        finally:
            conn.close()

    conn = get_db_connection()
    try:
        item_row = conn.execute("SELECT * FROM work_items WHERE id = ?", (work_item_id,)).fetchone()
        if not item_row:
            raise HTTPException(status_code=404, detail="Work item not found")
        item_dict = dict(item_row)

        # 1. Authorization check
        check_permission_to_transition(current_user, item_dict, payload.target_status.value)

        # 2. OCC Check
        verify_and_increment_version(conn, work_item_id, payload.expected_version)

        # 3. State Machine Guard validation
        validate_transition(
            item_dict["status"],
            payload.target_status.value,
            item_dict,
            current_user,
            payload.resolution_notes
        )
    finally:
        conn.close()

    now = get_utc_now_iso()
    is_resolving = payload.target_status == WorkStatus.RESOLVED
    resolved_at = now if is_resolving else item_dict["resolved_at"]

    with db_transaction() as tx:
        new_version = payload.expected_version + 1
        new_assignee = payload.new_assignee_id if payload.new_assignee_id is not None else item_dict["assignee_id"]
        new_priority = payload.new_priority.value if payload.new_priority else item_dict["priority"]

        tx.execute(
            """
            UPDATE work_items
            SET status = ?,
                version = ?,
                assignee_id = ?,
                priority = ?,
                updated_at = ?,
                resolved_at = ?
            WHERE id = ? AND version = ?
            """,
            (
                payload.target_status.value,
                new_version,
                new_assignee,
                new_priority,
                now,
                resolved_at,
                work_item_id,
                payload.expected_version
            )
        )

        # Audit Event
        tx.execute(
            """
            INSERT INTO work_item_events (id, work_item_id, actor_id, actor_name, event_type, from_state, to_state, details_json, created_at)
            VALUES (?, ?, ?, ?, 'STATUS_CHANGED', ?, ?, ?, ?)
            """,
            (
                f"evt_{uuid.uuid4().hex[:12]}",
                work_item_id,
                current_user.id,
                current_user.name,
                item_dict["status"],
                payload.target_status.value,
                json.dumps({
                    "reason": payload.reason,
                    "resolution_notes": payload.resolution_notes,
                    "new_assignee": new_assignee,
                    "new_priority": new_priority
                }),
                now
            )
        )

        # Enqueue async secondary jobs
        enqueue_job(tx, "NOTIFICATION_DISPATCH", work_item_id, {
            "recipient": item_dict["assigned_team"],
            "subject": f"Work Item {work_item_id} transitioned: {item_dict['status']} -> {payload.target_status.value}",
            "channels": ["slack"]
        })

    # Return updated item
    conn = get_db_connection()
    try:
        updated_row = conn.execute(
            """
            SELECT w.*, u.name as creator_name, a.name as assignee_name, t.name as assigned_team_name
            FROM work_items w
            LEFT JOIN users u ON w.creator_id = u.id
            LEFT JOIN users a ON w.assignee_id = a.id
            LEFT JOIN teams t ON w.assigned_team = t.id
            WHERE w.id = ?
            """,
            (work_item_id,)
        ).fetchone()
        result = serialize_work_item_row(updated_row, current_user, include_events=True, conn=conn)

        if idempotency_key:
            record_idempotency(conn, idempotency_key, current_user.id, request.url.path, req_hash, 200, result)
            conn.commit()

        return result
    finally:
        conn.close()

# ----------------- MULTI-STAGE APPROVAL WORKFLOW -----------------

@router.post("/work-items/{work_item_id}/approve", response_model=WorkItemResponse)
def approve_work_item(
    work_item_id: str,
    payload: WorkItemApprovalRequest,
    request: Request,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: UserInfo = Depends(get_current_user)
):
    req_hash = compute_payload_hash(payload.model_dump())

    if idempotency_key:
        conn = get_db_connection()
        try:
            cached = check_idempotency(conn, idempotency_key, current_user.id, request.url.path, req_hash)
            if cached:
                cached_status, cached_body = cached
                response.headers["X-Idempotency-Replay"] = "true"
                response.status_code = cached_status
                return cached_body
        finally:
            conn.close()

    conn = get_db_connection()
    try:
        item_row = conn.execute("SELECT * FROM work_items WHERE id = ?", (work_item_id,)).fetchone()
        if not item_row:
            raise HTTPException(status_code=404, detail="Work item not found")
        item_dict = dict(item_row)

        if item_dict["status"] != WorkStatus.PENDING_APPROVAL.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Work item '{work_item_id}' is not in PENDING_APPROVAL status (current: {item_dict['status']})."
            )

        # 1. Authorization check
        check_permission_to_approve(current_user, item_dict)

        # 2. OCC Check
        verify_and_increment_version(conn, work_item_id, payload.expected_version)
    finally:
        conn.close()

    target_status = WorkStatus.IN_PROGRESS.value if payload.approved else WorkStatus.CANCELLED.value
    event_type = "APPROVED" if payload.approved else "REJECTED"
    now = get_utc_now_iso()
    new_version = payload.expected_version + 1

    with db_transaction() as tx:
        tx.execute(
            """
            UPDATE work_items
            SET status = ?,
                version = ?,
                updated_at = ?
            WHERE id = ? AND version = ?
            """,
            (target_status, new_version, now, work_item_id, payload.expected_version)
        )

        tx.execute(
            """
            INSERT INTO work_item_events (id, work_item_id, actor_id, actor_name, event_type, from_state, to_state, details_json, created_at)
            VALUES (?, ?, ?, ?, ?, 'PENDING_APPROVAL', ?, ?, ?)
            """,
            (
                f"evt_{uuid.uuid4().hex[:12]}",
                work_item_id,
                current_user.id,
                current_user.name,
                event_type,
                target_status,
                json.dumps({
                    "approved": payload.approved,
                    "decision_notes": payload.notes,
                    "approver_title": current_user.title
                }),
                now
            )
        )

        enqueue_job(tx, "NOTIFICATION_DISPATCH", work_item_id, {
            "recipient": item_dict["creator_id"],
            "subject": f"Approval decision for {work_item_id}: {event_type}",
            "channels": ["slack", "email"]
        })

    conn = get_db_connection()
    try:
        updated_row = conn.execute(
            """
            SELECT w.*, u.name as creator_name, a.name as assignee_name, t.name as assigned_team_name
            FROM work_items w
            LEFT JOIN users u ON w.creator_id = u.id
            LEFT JOIN users a ON w.assignee_id = a.id
            LEFT JOIN teams t ON w.assigned_team = t.id
            WHERE w.id = ?
            """,
            (work_item_id,)
        ).fetchone()
        result = serialize_work_item_row(updated_row, current_user, include_events=True, conn=conn)

        if idempotency_key:
            record_idempotency(conn, idempotency_key, current_user.id, request.url.path, req_hash, 200, result)
            conn.commit()

        return result
    finally:
        conn.close()

# ----------------- COMMENTS & AUDIT LOG -----------------

@router.post("/work-items/{work_item_id}/comments")
def add_comment(
    work_item_id: str,
    payload: AddCommentRequest,
    current_user: UserInfo = Depends(get_current_user)
):
    conn = get_db_connection()
    try:
        item = conn.execute("SELECT id FROM work_items WHERE id = ?", (work_item_id,)).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="Work item not found")
    finally:
        conn.close()

    now = get_utc_now_iso()
    with db_transaction() as tx:
        tx.execute(
            """
            INSERT INTO work_item_events (id, work_item_id, actor_id, actor_name, event_type, details_json, created_at)
            VALUES (?, ?, ?, ?, 'COMMENT_ADDED', ?, ?)
            """,
            (
                f"evt_{uuid.uuid4().hex[:12]}",
                work_item_id,
                current_user.id,
                current_user.name,
                json.dumps({"comment": payload.comment}),
                now
            )
        )
        tx.execute("UPDATE work_items SET updated_at = ? WHERE id = ?", (now, work_item_id))

    return {"message": "Comment recorded in audit trail", "timestamp": now}

# ----------------- ASYNC JOBS INSPECTOR & RUNNER -----------------

@router.get("/async-jobs", response_model=List[AsyncJobResponse])
def list_async_jobs(limit: int = 25):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, job_type, work_item_id, status, attempts, max_attempts, last_error, run_at, created_at, completed_at
            FROM async_jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()
        return [AsyncJobResponse(**dict(r)) for r in rows]
    finally:
        conn.close()

@router.post("/async-jobs/run-pending")
def trigger_due_async_jobs():
    processed = run_due_jobs()
    return {"message": f"Processed {processed} due async background jobs"}

# ----------------- DEMO SEED RESET -----------------

@router.post("/reset-demo")
def reset_demo_database():
    from app.seed import seed_database
    seed_database(reset=True)
    return {"message": "Operational coordinator database successfully reset to clean demonstration state"}
