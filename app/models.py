from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class WorkCategory(str, Enum):
    INCIDENT = "incident"
    CUSTOMER_ISSUE = "customer_issue"
    APPROVAL_REQUEST = "approval_request"
    OPERATIONAL_TASK = "operational_task"

class WorkStatus(str, Enum):
    TRIAGE = "TRIAGE"
    IN_INVESTIGATION = "IN_INVESTIGATION"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"

class WorkPriority(str, Enum):
    P0 = "P0" # Critical (SLA: 60m)
    P1 = "P1" # High (SLA: 120m)
    P2 = "P2" # Medium (SLA: 480m)
    P3 = "P3" # Low (SLA: 1440m)

class SlaRiskLevel(str, Enum):
    NORMAL = "NORMAL"
    WARN = "WARN"
    BREACHED = "BREACHED"

class UserInfo(BaseModel):
    id: str
    name: str
    email: str
    title: str
    teams: List[str] = []

class TeamInfo(BaseModel):
    id: str
    name: str
    description: str
    member_count: Optional[int] = 0

class WorkItemCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=150)
    description: str = Field(..., min_length=5, max_length=5000)
    category: WorkCategory
    priority: WorkPriority
    assigned_team: str
    target_sla_minutes: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None

class WorkItemClaimRequest(BaseModel):
    expected_version: int

class WorkItemTransitionRequest(BaseModel):
    expected_version: int
    target_status: WorkStatus
    reason: str = Field(..., min_length=2, max_length=1000)
    resolution_notes: Optional[str] = None
    new_assignee_id: Optional[str] = None
    new_priority: Optional[WorkPriority] = None

class WorkItemApprovalRequest(BaseModel):
    expected_version: int
    approved: bool
    notes: str = Field(..., min_length=2, max_length=1000)

class AddCommentRequest(BaseModel):
    comment: str = Field(..., min_length=1, max_length=2000)

class NextAction(BaseModel):
    action_type: str # 'CLAIM', 'APPROVE', 'INVESTIGATE', 'RESOLVE', 'TRIAGE', 'UNBLOCK'
    label: str
    description: str
    allowed_roles_or_teams: List[str]
    permitted_for_viewer: bool

class WorkItemEventResponse(BaseModel):
    id: str
    work_item_id: str
    actor_id: str
    actor_name: str
    event_type: str
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    details: Dict[str, Any]
    created_at: str

class WorkItemResponse(BaseModel):
    id: str
    title: str
    description: str
    category: WorkCategory
    status: WorkStatus
    priority: WorkPriority
    creator_id: str
    creator_name: Optional[str] = None
    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None
    assigned_team: str
    assigned_team_name: Optional[str] = None
    version: int
    target_sla_minutes: int
    created_at: str
    updated_at: str
    resolved_at: Optional[str] = None
    sla_breached: bool
    sla_risk_level: SlaRiskLevel
    metadata: Dict[str, Any]
    next_required_actions: List[NextAction] = []
    events: Optional[List[WorkItemEventResponse]] = None

class PaginatedWorkItems(BaseModel):
    items: List[WorkItemResponse]
    total: int
    limit: int
    offset: int
    has_more: bool

class DashboardKPIs(BaseModel):
    total_active: int
    triage_count: int
    sla_breach_count: int
    sla_warn_count: int
    pending_approvals_count: int
    my_assigned_count: int
    by_priority: Dict[str, int]
    by_status: Dict[str, int]

class AsyncJobResponse(BaseModel):
    id: str
    job_type: str
    work_item_id: str
    status: str
    attempts: int
    max_attempts: int
    last_error: Optional[str]
    run_at: str
    created_at: str
    completed_at: Optional[str]
