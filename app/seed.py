import json
import uuid
from datetime import datetime, timezone, timedelta
from app.database import get_db_connection, init_db

USERS = [
    {
        "id": "usr_alice",
        "name": "Alice Chen",
        "email": "alice.chen@newtonite.internal",
        "title": "Tier 1 Support Lead",
        "teams": ["tier1_support"]
    },
    {
        "id": "usr_bob",
        "name": "Bob Martinez",
        "email": "bob.martinez@newtonite.internal",
        "title": "Incident Commander",
        "teams": ["incident_response"]
    },
    {
        "id": "usr_carol",
        "name": "Carol Danvers",
        "email": "carol.danvers@newtonite.internal",
        "title": "VP of Finance & Commercial Approvals",
        "teams": ["finance_approvals"]
    },
    {
        "id": "usr_dave",
        "name": "Dave Wilson",
        "email": "dave.wilson@newtonite.internal",
        "title": "Staff Security Analyst",
        "teams": ["secops"]
    },
    {
        "id": "usr_eve",
        "name": "Eve Adams",
        "email": "eve.adams@newtonite.internal",
        "title": "VP of Infrastructure & Ops Admin",
        "teams": ["ops_admin", "incident_response"]
    },
    {
        "id": "usr_frank",
        "name": "Frank Miller",
        "email": "frank.miller@newtonite.internal",
        "title": "Operations & Billing Specialist",
        "teams": ["tier1_support", "finance_approvals"]
    }
]

TEAMS = [
    {
        "id": "tier1_support",
        "name": "Tier 1 Customer Support",
        "description": "Frontline customer issue intake, triage, initial diagnostics, and customer liaison."
    },
    {
        "id": "incident_response",
        "name": "Incident Response Engineering",
        "description": "High-urgency system outages, degradation mitigation, and P0/P1 emergency response."
    },
    {
        "id": "secops",
        "name": "Security Operations (SecOps)",
        "description": "Threat assessment, vulnerability remediation, access control, and compliance reviews."
    },
    {
        "id": "finance_approvals",
        "name": "Finance & Commercial Approvals",
        "description": "Approval authority for enterprise SLA credits, refunds, and emergency infrastructure expenditure."
    },
    {
        "id": "ops_admin",
        "name": "Operations Administration",
        "description": "Global administration, emergency cross-team overrides, workflow policy configurations."
    }
]

WORK_ITEMS_DATA = [
    {
        "id": "wi_p0_db_pool",
        "title": "Database Connection Pool Exhaustion in EU-West-1 Core Cluster",
        "description": "Spike in HTTP 500 errors across primary payment processing service. Connection pool utilization sustained at 100%. Active thread dumps indicate hung queries on ledger reconciliation lock.",
        "category": "incident",
        "status": "IN_INVESTIGATION",
        "priority": "P0",
        "creator_id": "usr_bob",
        "assignee_id": "usr_bob",
        "assigned_team": "incident_response",
        "target_sla_minutes": 60,
        "age_minutes": 45,
        "metadata": {"impact": "Critical", "region": "eu-west-1", "affected_services": ["payment-gw", "ledger"]}
    },
    {
        "id": "wi_p0_unassigned_gateway",
        "title": "CRITICAL: Payment Gateway Webhook Deadlock - Dropping Live Transactions",
        "description": "Inbound stripe webhooks returning 504 gateway timeout. Automated retry queues filling memory fast. Requires immediate triage and cluster thread-dump capture.",
        "category": "incident",
        "status": "TRIAGE",
        "priority": "P0",
        "creator_id": "usr_alice",
        "assignee_id": None, # Unassigned for claiming demo
        "assigned_team": "incident_response",
        "target_sla_minutes": 60,
        "age_minutes": 15,
        "metadata": {"impact": "High", "affected_transactions": 340}
    },
    {
        "id": "wi_p1_auth_memory",
        "title": "Memory Leak in User Authentication & JWT Token Verification Microservice",
        "description": "Worker nodes restarted 8 times in last 3 hours due to OOM kills. Heap profile shows uncollected session cache entries with unbounded TTL under peak token rotation.",
        "category": "incident",
        "status": "IN_PROGRESS",
        "priority": "P1",
        "creator_id": "usr_bob",
        "assignee_id": "usr_eve",
        "assigned_team": "incident_response",
        "target_sla_minutes": 120,
        "age_minutes": 70,
        "metadata": {"oom_restarts": 8, "service": "auth-jwt"}
    },
    {
        "id": "wi_p1_sec_bruteforce",
        "title": "Potential Credential Stuffing Distributed Attack on Enterprise SSO",
        "description": "WAF flagged anomalous ingress spike from 2,300 rotating residential IPs hitting /api/v1/auth/login. Rate limiting triggered but requiring SecOps IP CIDR block confirmation.",
        "category": "incident",
        "status": "IN_INVESTIGATION",
        "priority": "P1",
        "creator_id": "usr_dave",
        "assignee_id": "usr_dave",
        "assigned_team": "secops",
        "target_sla_minutes": 120,
        "age_minutes": 95,
        "metadata": {"ip_count": 2300, "attack_type": "credential_stuffing"}
    },
    {
        "id": "wi_p2_refund_acme",
        "title": "Enterprise SLA Credit Request ($18,500) - Acme Corporation Outage Dispute",
        "description": "Account executive submitted formal SLA dispute credit request for Acme Corp following Q3 infrastructure downtime. Requires Finance VP sign-off per commercial matrix.",
        "category": "approval_request",
        "status": "PENDING_APPROVAL",
        "priority": "P2",
        "creator_id": "usr_frank",
        "assignee_id": "usr_carol",
        "assigned_team": "finance_approvals",
        "target_sla_minutes": 480,
        "age_minutes": 120,
        "metadata": {"customer": "Acme Corp", "amount_usd": 18500, "contract_id": "CNT-99042"}
    },
    {
        "id": "wi_p2_unassigned_refund",
        "title": "Vendor Emergency Cloud Capacity Overdraft Approval ($6,200)",
        "description": "Automated AWS auto-scaling budget ceiling exceeded during unplanned traffic burst. Requires finance approval to raise regional billing threshold.",
        "category": "approval_request",
        "status": "PENDING_APPROVAL",
        "priority": "P2",
        "creator_id": "usr_eve",
        "assignee_id": None, # Unassigned approval
        "assigned_team": "finance_approvals",
        "target_sla_minutes": 480,
        "age_minutes": 300,
        "metadata": {"amount_usd": 6200, "provider": "AWS"}
    },
    {
        "id": "wi_p2_csv_export",
        "title": "Bulk CSV Data Export Failing on Enterprise Accounts with >50,000 Rows",
        "description": "Customer reported export job times out at 30 seconds. Background worker memory cap terminates worker before stream finishes serialization.",
        "category": "customer_issue",
        "status": "TRIAGE",
        "priority": "P2",
        "creator_id": "usr_alice",
        "assignee_id": None, # Unassigned for claiming
        "assigned_team": "tier1_support",
        "target_sla_minutes": 480,
        "age_minutes": 510, # Breached!
        "metadata": {"customer_tier": "Enterprise", "reported_by": "zendesk_ticket_4412"}
    },
    {
        "id": "wi_p3_darkmode_glitch",
        "title": "Billing Dashboard Dark Mode Contrast Ratio Accessibility Glitch",
        "description": "Secondary buttons in the invoice settlement tab are using dark gray text on dark slate background in Chrome 124+. Need CSS contrast token update.",
        "category": "customer_issue",
        "status": "IN_PROGRESS",
        "priority": "P3",
        "creator_id": "usr_alice",
        "assignee_id": "usr_alice",
        "assigned_team": "tier1_support",
        "target_sla_minutes": 1440,
        "age_minutes": 240,
        "metadata": {"browser": "Chrome", "wcag_standard": "AA"}
    },
    {
        "id": "wi_p1_kafka_rebalance",
        "title": "Kafka Cluster Rebalancing for Partition Lag Remediation",
        "description": "Partition lag on analytics-stream topic reached 4.2 million messages. Broker 3 disk throughput throttled. Awaiting vendor disk IOPS expansion before rebalancing partitions.",
        "category": "operational_task",
        "status": "BLOCKED",
        "priority": "P1",
        "creator_id": "usr_bob",
        "assignee_id": "usr_bob",
        "assigned_team": "incident_response",
        "target_sla_minutes": 120,
        "age_minutes": 140, # Breached!
        "metadata": {"blocker_reason": "Waiting for Cloud Provider IOPS Burst Quota increase"}
    },
    {
        "id": "wi_p2_cert_rotation",
        "title": "Quarterly Wildcard SSL/TLS Certificate & Secret Rotation",
        "description": "Rotate *.newtonite.internal wildcard certificates and update secrets in HashiCorp Vault. Completed verification on staging and production ingress controllers.",
        "category": "operational_task",
        "status": "RESOLVED",
        "priority": "P2",
        "creator_id": "usr_dave",
        "assignee_id": "usr_dave",
        "assigned_team": "secops",
        "target_sla_minutes": 480,
        "age_minutes": 600,
        "metadata": {"vault_cluster": "vault-prod-01", "cert_serial": "99A-44B"}
    },
    {
        "id": "wi_p3_api_docs",
        "title": "Update Public Webhook API Documentation for HMAC Signature Verification",
        "description": "Developers on developer portal reported confusion regarding timestamp header casing in HMAC digest calculation. Updated code samples for Python, Node, and Go.",
        "category": "operational_task",
        "status": "RESOLVED",
        "priority": "P3",
        "creator_id": "usr_frank",
        "assignee_id": "usr_frank",
        "assigned_team": "tier1_support",
        "target_sla_minutes": 1440,
        "age_minutes": 1500,
        "metadata": {"docs_pr": "https://github.com/newtonite/docs/pull/88"}
    },
    {
        "id": "wi_p2_unassigned_sec",
        "title": "S3 Data Ingestion Bucket Cross-Account IAM Policy Audit Alert",
        "description": "Automated security scanner detected overly broad s3:GetObject permission on external vendor drop folder. Requires review and least-privilege scoping.",
        "category": "incident",
        "status": "TRIAGE",
        "priority": "P2",
        "creator_id": "usr_dave",
        "assignee_id": None,
        "assigned_team": "secops",
        "target_sla_minutes": 480,
        "age_minutes": 60,
        "metadata": {"bucket_name": "newtonite-vendor-inbound"}
    }
]

def seed_database(reset: bool = True):
    init_db()
    conn = get_db_connection()
    try:
        if reset:
            conn.execute("DELETE FROM work_item_events;")
            conn.execute("DELETE FROM idempotency_keys;")
            conn.execute("DELETE FROM async_jobs;")
            conn.execute("DELETE FROM work_items;")
            conn.execute("DELETE FROM team_memberships;")
            conn.execute("DELETE FROM teams;")
            conn.execute("DELETE FROM users;")

        # Insert Users
        for u in USERS:
            conn.execute(
                """
                INSERT OR REPLACE INTO users (id, name, email, title, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (u["id"], u["name"], u["email"], u["title"], datetime.now(timezone.utc).isoformat())
            )

        # Insert Teams
        for t in TEAMS:
            conn.execute(
                """
                INSERT OR REPLACE INTO teams (id, name, description)
                VALUES (?, ?, ?)
                """,
                (t["id"], t["name"], t["description"])
            )

        # Insert Team Memberships
        for u in USERS:
            for tid in u["teams"]:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO team_memberships (user_id, team_id, role_in_team)
                    VALUES (?, ?, 'member')
                    """,
                    (u["id"], tid)
                )

        now = datetime.now(timezone.utc)

        # Insert Work Items & Events
        for item in WORK_ITEMS_DATA:
            created_at = (now - timedelta(minutes=item["age_minutes"])).isoformat()
            updated_at = (now - timedelta(minutes=max(1, item["age_minutes"] - 10))).isoformat()
            resolved_at = updated_at if item["status"] == "RESOLVED" else None

            # Calculate SLA risk level
            target_sla = item["target_sla_minutes"]
            age_m = item["age_minutes"]
            is_breached = 1 if (age_m >= target_sla and item["status"] not in ("RESOLVED", "CANCELLED")) else 0
            
            if is_breached:
                risk_level = "BREACHED"
            elif (age_m >= target_sla * 0.75 and item["status"] not in ("RESOLVED", "CANCELLED")):
                risk_level = "WARN"
            else:
                risk_level = "NORMAL"

            conn.execute(
                """
                INSERT OR REPLACE INTO work_items 
                (id, title, description, category, status, priority, creator_id, assignee_id, assigned_team, 
                 version, target_sla_minutes, created_at, updated_at, resolved_at, sla_breached, sla_risk_level, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["id"],
                    item["title"],
                    item["description"],
                    item["category"],
                    item["status"],
                    item["priority"],
                    item["creator_id"],
                    item["assignee_id"],
                    item["assigned_team"],
                    target_sla,
                    created_at,
                    updated_at,
                    resolved_at,
                    is_breached,
                    risk_level,
                    json.dumps(item["metadata"])
                )
            )

            # Audit Log: Creation event
            conn.execute(
                """
                INSERT INTO work_item_events (id, work_item_id, actor_id, actor_name, event_type, from_state, to_state, details_json, created_at)
                VALUES (?, ?, ?, ?, 'CREATED', NULL, 'TRIAGE', ?, ?)
                """,
                (
                    f"evt_{uuid.uuid4().hex[:12]}",
                    item["id"],
                    item["creator_id"],
                    next(u["name"] for u in USERS if u["id"] == item["creator_id"]),
                    json.dumps({"priority": item["priority"], "category": item["category"]}),
                    created_at
                )
            )

            # Audit Log: Additional event if not in TRIAGE
            if item["status"] != "TRIAGE":
                event_type = "RESOLVED" if item["status"] == "RESOLVED" else "STATUS_CHANGED"
                conn.execute(
                    """
                    INSERT INTO work_item_events (id, work_item_id, actor_id, actor_name, event_type, from_state, to_state, details_json, created_at)
                    VALUES (?, ?, ?, ?, ?, 'TRIAGE', ?, ?, ?)
                    """,
                    (
                        f"evt_{uuid.uuid4().hex[:12]}",
                        item["id"],
                        item["assignee_id"] or item["creator_id"],
                        next(u["name"] for u in USERS if u["id"] == (item["assignee_id"] or item["creator_id"])),
                        event_type,
                        item["status"],
                        json.dumps({"notes": f"Progressed to {item['status']}"}),
                        updated_at
                    )
                )

        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    seed_database(reset=True)
    print("Database successfully initialized and seeded with rich operational data!")
