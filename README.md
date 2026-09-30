# Newtonite Operations Coordinator

A high-reliability, full-stack operational work coordination platform built to replace fragmented spreadsheets, emails, and chat for rapidly growing companies managing customer escalations, production incidents, and multi-team approvals.

Developed for the **Newtonite Software Engineering Challenge**, this solution demonstrates thoughtful systems architecture, concurrency control, strict resource-level authorization, and asynchronous secondary processing representing one focused working day of engineering effort.

---

## 🌟 Key Capabilities

### 1. Operational Work Coordination & Visible History
- **Rich Work Items:** Supports operational incidents, customer issues, approval requests, and operational maintenance tasks.
- **Dynamic Context:** Every item displays purpose, current workflow state, severity/priority (P0 to P3), responsible owner, assigned team, SLA target countdown, and dynamically computed **Next Required Actions**.
- **Immutable Audit Ledger:** Every state transition, claim, assignment, comment, or approval records an append-only event in the `work_item_events` table, preventing silent changes.

### 2. High-Efficiency Overview Dashboard
- **Instant Triage:** Instant KPI counters for Active Items, Triage Needed, Pending Approvals, SLA Breaches, and My Assigned Items.
- **Attention Queues:** Dedicated live queues for immediate triage of unassigned items, pending approval sign-offs, and critical SLA risk items.
- **Zero Full-Dataset Browser Dumping:** Paginated, server-side indexed queries (`LIMIT` / `OFFSET`) ensure the browser never loads tens of thousands of items into client memory.

### 3. Server-Enforced Multi-Team RBAC & Separation of Duties
- **Multi-Team Membership:** Users can belong to multiple teams with distinct responsibilities (`tier1_support`, `incident_response`, `secops`, `finance_approvals`, `ops_admin`).
- **Resource-Level Security:** Authorization is strictly validated on the backend. Attempting to claim or transition items across unauthorized team boundaries fails with `HTTP 403 Forbidden` with detailed diagnostic feedback.
- **Separation of Duties Guard:** High-severity (P0/P1) creators cannot approve their own requests.

### 4. Critical Behaviors Beyond Simple CRUD
1. **Optimistic Concurrency Control (OCC) & Atomic Claims:**
   - Work items carry a `version` key.
   - Updates with stale versions are rejected with `HTTP 409 Conflict`.
   - Simultaneous claims on unassigned items use atomic conditional updates (`UPDATE ... WHERE version = ? AND assignee_id IS NULL`), ensuring exactly one operator succeeds while the other is rejected with 409 Conflict.
2. **Request Deduplication & Idempotent Actions:**
   - Full support for `Idempotency-Key` headers.
   - Network retries and duplicate submissions replay cached responses with `X-Idempotency-Replay: true`.
   - Idempotency key reuse with conflicting payloads is rejected with `HTTP 422 Unprocessable Content`.
3. **Multi-Stage Approval State Machine with Guard Rails:**
   - Formal approval endpoints (`/approve`) enforce transition graphs and approval team sign-offs.
   - Cannot bypass approvals via plain status changes.
   - Transitioning to `RESOLVED` strictly requires non-empty `resolution_notes`.
4. **Resilient Asynchronous Worker Queue:**
   - Secondary processing (dynamic SLA risk calculations, multi-channel notifications) is offloaded to a transactional outbox queue (`async_jobs`).
   - Handles network delays, exponential retry backoff (`2^attempts`), and dead-letter routing upon exceeding max attempts.

---

## 🏗️ Architecture & Tech Stack

```
                        ┌────────────────────────────────────────┐
                        │ Modern SPA Frontend (HTML5, CSS, JS)   │
                        │ - Dark Glassmorphism UI (Inter font)   │
                        │ - Persona Switcher & Live Attention Queues│
                        │ - Interactive Concurrency Test Bench   │
                        └───────────────────┬────────────────────┘
                                            │ REST / JSON (with Idempotency-Key)
                                            ▼
                        ┌────────────────────────────────────────┐
                        │ FastAPI Application Backend            │
                        │ ├─ Multi-Team RBAC & Guard Middleware  │
                        │ ├─ Optimistic Concurrency Engine (OCC) │
                        │ ├─ Idempotency Ledger Handler          │
                        │ └─ State Machine Transition Validator  │
                        └──────────┬──────────────────┬──────────┘
                                   │                  │
               Transactional Outbox│                  │ Serialized WAL Writes
                                   ▼                  ▼
                    ┌─────────────────────────┐  ┌─────────────────────────┐
                    │ Async Background Worker │  │ SQLite 3 (WAL Mode)     │
                    │ - Exponential Backoff   │  │ - Composite B-Tree Idxs │
                    │ - Dead-Letter Queue     │  │ - Append-Only Audit Log │
                    │ - Idempotent Claiming   │  │ - Idempotency Receipts  │
                    └─────────────────────────┘  └─────────────────────────┘
```

- **Backend:** Python 3.11, FastAPI, Pydantic v2, Uvicorn
- **Database:** SQLite 3 configured in WAL (Write-Ahead Logging) mode with composite indexes
- **Frontend:** Vanilla CSS3 (curated dark slate theme, responsive layout, glassmorphic cards, micro-animations) & Vanilla ES6+ JavaScript
- **Test Suite:** Pytest with HTTPX TestClient

---

## 🚀 Quick Start Guide

### Prerequisites
- Python 3.10+ (Python 3.11 recommended)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Application
```bash
python run.py
```
The application will automatically:
1. Initialize the SQLite database at `data/ops_coordinator.db` with WAL mode and composite indexes.
2. Seed the database with realistic operational incidents, customer tickets, approvals, and 6 team personas.
3. Start the background async worker loop.
4. Launch the web server on `http://127.0.0.1:8000`.

Open your browser and navigate to:
👉 **`http://127.0.0.1:8000`**

---

## 🧪 Running Automated Tests

The automated test suite specifically targets critical and dangerous architectural behaviors:
- **`test_concurrency.py`:** Concurrent multi-threaded claim race conditions and stale OCC update rejection.
- **`test_idempotency.py`:** Network retry replay caching, duplicate prevention, and conflicting payload rejection.
- **`test_authorization.py`:** Cross-team claim blocking, unauthorized approvals, and separation-of-duties self-approval blocking.
- **`test_state_machine.py`:** Illegal state jumps, approval bypass prevention, and mandatory resolution notes guards.
- **`test_async_jobs.py`:** Outbox job queueing, retry backoff calculation, and dead-letter queue routing.

To execute the test suite:
```bash
python -m pytest tests/ -v
```

Expected result:
```
======================= 15 passed in ~2.0s =======================
```

---

## 🎮 Interactive Test Bench & Persona Switcher

In the running web application:
1. **Persona Switcher (Header):**
   - Switch between **Alice Chen** (Tier 1 Support), **Bob Martinez** (Incident Commander), **Carol Danvers** (Finance Approvals), **Dave Wilson** (SecOps), **Eve Adams** (Ops Admin), and **Frank Miller** (Multi-team Support & Finance).
   - Watch the header badges, "My Items" queue, and permitted action buttons instantly adapt.
2. **Concurrency & Behaviors Tab:**
   - Click **"1. Simulate Concurrent Race Condition Claim"** to fire two simultaneous HTTP claims against an unassigned ticket. Observe exactly one 200 OK and one 409 Conflict.
   - Click **"2. Simulate Stale Version OCC Conflict"** to observe OCC rejection when submitting a mutation with an outdated version.
   - Click **"3. Simulate Idempotency-Key Network Retry Replay"** to watch the server detect duplicate request tokens and safely return the cached receipt.
   - Click **"4. Simulate Cross-Team Unauthorized Claim"** to confirm server-enforced 403 Forbidden protection.
3. **Async Background Jobs Tab:**
   - Inspect the live queue of secondary tasks, attempt counters, and execution statuses.
   - Click **"Run Due Jobs Now"** to trigger pending background tasks on demand.
4. **Reset Demo Button:**
   - Click **↺ Reset Demo** at any time in the top header to restore the database to the clean initial seed state.

---

## 📚 Deliverable Documents
- **`ENGINEERING_DECISIONS.md`**: In-depth analysis of 5 major trade-offs (Data modeling & audit ledger, OCC vs locking, idempotency mechanics, sync vs async outbox, and authorization logic).
- **`KNOWN_LIMITATIONS.md`**: Detailed evaluation of single-node storage limits, distributed job workers, WebSocket live streaming, and production roadmap.
