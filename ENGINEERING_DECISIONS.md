# Engineering Decisions & Architectural Trade-offs

This document details five major architectural decisions and trade-offs made in the design and implementation of the **Newtonite Operations Coordinator** system, representing one working day of focused engineering effort.

---

## 1. Concurrency Architecture: Optimistic Concurrency Control (OCC) vs. Pessimistic Row Locking

### Context & Problem
Operational coordination tools frequently experience "split-brain" or duplicate work: two engineers simultaneously click "Claim" on an unassigned P0 incident, or two support agents update status and notes on the same ticket while working from slightly stale browser tabs.

### Options Considered
- **Pessimistic Row Locking (`SELECT ... FOR UPDATE`):** Locks the record for the duration of a transaction or session.
- **Optimistic Concurrency Control (`version` integer / CAS):** Records an incremental version integer on every entity. Mutations require the client to present the `expected_version` they observed.
- **Last-Write-Wins (LWW):** Unconditional updates where the last database write silently clobbers previous edits.

### Decision & Trade-offs
We implemented **Optimistic Concurrency Control paired with Atomic Conditional Updates**:
1. Every `work_items` record carries an integer `version` (default 1).
2. On any state transition or edit, the backend verifies `current_version == expected_version` and atomically increments the counter (`version = version + 1`).
3. For work item claiming, an atomic conditional update query is used:
   ```sql
   UPDATE work_items
   SET assignee_id = :user_id,
       version = version + 1,
       updated_at = :now,
       status = CASE WHEN status = 'TRIAGE' THEN 'IN_INVESTIGATION' ELSE status END
   WHERE id = :work_item_id
     AND version = :expected_version
     AND (assignee_id IS NULL OR assignee_id = '');
   ```
   If two operators attempt to claim simultaneously, SQLite's atomic write serialization ensures exactly one transaction matches `rowcount == 1`. The second transaction matches `rowcount == 0` and is rejected with `HTTP 409 Conflict`.

**Trade-offs Accepted:**
- *Pros:* Zero risk of long-lived lock starvation or deadlocks when humans take minutes to read ticket descriptions before clicking submit; predictable sub-millisecond query execution.
- *Cons:* The losing client must catch the 409 Conflict and reload the fresh state rather than automatically waiting in a lock queue.

---

## 2. Request Idempotency via Transaction-Coupled Receipts

### Context & Problem
In fast-paced incident scenarios or mobile network conditions, network timeouts, browser double-clicks, or automated retried webhooks can cause duplicate submissions. Duplicating a financial approval ($18,500 credit) or duplicate ticket provisioning can have severe operational and financial ramifications.

### Options Considered
- **Stateless deduplication (Client-side debouncing only):** Easily bypassed by network retries, browser refreshes, or third-party automated scripts.
- **External Redis distributed lock / cache:** Requires maintaining an external Redis instance with TTL expiry, risking split-brain if Redis and SQLite/Postgres commit out of phase.
- **Transaction-Coupled Idempotency Table in Primary DB:** Persisting the idempotency receipt in the same atomic database transaction as the entity mutation.

### Decision & Trade-offs
We implemented **Transaction-Coupled Idempotency Receipts**:
- Clients supply an `Idempotency-Key: <unique-token>` HTTP header.
- The server hashes the request payload (`SHA-256`) and checks the `idempotency_keys` table.
- If the key exists with an identical payload hash, the server replays the stored response code and JSON body with the header `X-Idempotency-Replay: true`.
- If the key exists with a *differing* payload hash, the server halts with `HTTP 422 Unprocessable Content` to prevent key hijacking.
- In new requests, the entity mutation and the idempotency receipt are inserted within the exact same `BEGIN IMMEDIATE ... COMMIT` block.

**Trade-offs Accepted:**
- *Pros:* Strict ACID consistency—it is physically impossible for the business entity mutation to succeed while the idempotency record fails to persist (or vice versa).
- *Cons:* Slightly larger database storage footprint over time; requires periodic housekeeping jobs to archive idempotency keys older than 30 days.

---

## 3. Synchronous Critical Path vs. Resilient Asynchronous Worker Queue

### Context & Problem
Operations systems must balance fast user responsiveness (sub-50ms API responses) with secondary side-effects (calculating dynamic SLA breach countdowns, sending external notifications to Slack/PagerDuty, persisting audit webhooks, or syncing external ticketing systems). Coupling external network calls to the user mutation path introduces latency, cascading failures, and lost updates when downstream notification endpoints fail.

### Options Considered
- **Inline Synchronous Processing:** Calling webhook APIs and running calculations in the HTTP request thread before returning to the browser.
- **Ephemeral Background Tasks (`asyncio.create_task` in-memory):** Fast, but lost permanently if the application restarts, crashes, or is redeployed.
- **Transactional Outbox / Persistent Job Queue (`async_jobs` table):** Inserting job records into SQLite within the primary transaction, processed by an autonomous background worker loop.

### Decision & Trade-offs
We implemented the **Transactional Outbox Worker Pattern**:
1. When a work item is created or updated, secondary jobs (`SLA_ENRICHMENT`, `NOTIFICATION_DISPATCH`) are written to `async_jobs` inside the same database transaction.
2. The asynchronous background worker continuously monitors due jobs (`run_at <= now AND status = 'PENDING'`).
3. **Idempotent Job Claiming:** Workers conditionally claim jobs using `UPDATE async_jobs SET status = 'PROCESSING', attempts = attempts + 1 WHERE id = ? AND status = 'PENDING'`, preventing duplicate execution even across multiple concurrent worker threads.
4. **Exponential Backoff & Dead-Letter Safety:** Transient failures (e.g., HTTP 504 network blips) trigger exponential backoff (`run_at = now + 2^attempts seconds`). If attempts exceed `max_attempts` (3), the job transitions to `DEAD_LETTER` with `last_error` recorded for operator inspection.

**Trade-offs Accepted:**
- *Pros:* Zero external infrastructure dependencies (e.g. RabbitMQ/Celery); guaranteed persistence across server restarts; complete auditability of background work.
- *Cons:* Notification dispatch is eventually consistent (typically ~500ms to 1.5s delay) rather than instantaneous.

---

## 4. Server-Enforced Multi-Team RBAC & Separation of Duties

### Context & Problem
Growing companies have specialized teams (Tier 1 Support, Incident Response, SecOps, Finance Approvals, Ops Administration). A common antipattern is client-side permission enforcement (hiding the "Approve" button in HTML/JS) while leaving the REST API endpoints vulnerable to direct curl or Postman requests.

### Options Considered
- **UI-Only Role Guards:** Hiding or disabling buttons based on user role. Insecure.
- **Coarse Role Model (Admin vs. Regular User):** Does not reflect real multi-team matrix organizations where an operator might belong to Support and Finance, but not SecOps.
- **Resource-Aware Multi-Team RBAC with State Machine Guards:** Server-level enforcement checking user team memberships against both the work item's assigned team and the specific workflow transition.

### Decision & Trade-offs
We implemented **Server-Enforced Resource-Aware RBAC with Separation of Duties**:
- Users belong to multiple teams via the `team_memberships` relation.
- Every API endpoint (`/claim`, `/transition`, `/approve`) resolves the actor from session/header and validates permissions against the specific record before executing:
  * **Claiming:** User must be a member of the assigned team or `ops_admin`. Support engineers cannot claim Incident Response or SecOps tickets (`403 Forbidden`).
  * **Approvals:** Financial requests require `finance_approvals` membership; security requests require `secops`.
  * **Separation of Duties Guard:** A user cannot approve their own high-severity (P0/P1) requests, preventing rogue self-authorization.
  * **State Machine Guards:** Terminal states cannot be skipped (e.g. jumping directly from `TRIAGE` to `RESOLVED` triggers `400 Bad Request`); resolving an item strictly requires non-empty `resolution_notes` (`422 Unprocessable Content`).

**Trade-offs Accepted:**
- *Pros:* Bulletproof security guarantees; impossible for UI tampering or automated scripts to violate governance rules.
- *Cons:* Authorization logic must be thoroughly tested for every state edge and team permutation.

---

## 5. Storage Engine & Scale Architecture: SQLite WAL + Composite Indexing

### Context & Problem
The system must support continuing growth: thousands of registered users, up to a few thousand concurrent users, and tens of thousands of active work items, without depending on loading the entire dataset into browser memory or server memory.

### Options Considered
- **In-Memory Store (Dicts / Lists):** Fast to develop, but loses data on restart and crashes on large datasets.
- **Full PostgreSQL / Distributed SQL:** Enterprise grade, but adds substantial operational complexity, external process dependencies, and connection pool configuration for a one-day delivery challenge.
- **SQLite 3 in WAL Mode with Covering Indexes:** Embedded, zero-configuration engine operating with modern Write-Ahead Logging (WAL) concurrency.

### Decision & Trade-offs
We selected **SQLite 3 in WAL Mode (`PRAGMA journal_mode=WAL;`) with Composite B-Tree Indexes**:
1. **WAL Concurrency:** SQLite in WAL mode permits unlimited concurrent readers while a single writer commits, eliminating read-write blocking.
2. **Server-Side Pagination:** All queries enforce `LIMIT` and `OFFSET` (or keyset cursor); the browser never loads more than 15-25 items at a time.
3. **Targeted Composite Indexes:**
   - `idx_work_items_status_priority`: Enables sub-millisecond filtering on `status` and `priority` for the dashboard overview.
   - `idx_work_items_team_status`: Fast index-only scans for team queues.
   - `idx_work_items_assignee_status`: Instant retrieval of "My Open Items".
   - `idx_work_items_created`: Fast reverse chronological sorting without full table sorting.
   - `idx_async_jobs_pending`: Instant lookup of pending background tasks due for execution.
4. **Append-Only Audit Ledger:** Changes to work items do not overwrite historical records; they write immutable events to `work_item_events`.

**Trade-offs Accepted:**
- *Pros:* Single-file deployment, zero external services to configure or fail, microsecond query execution on tens of thousands of records, zero container network overhead.
- *Cons:* Write throughput is serialized to a single writer thread (~2,000–5,000 writes/sec), which easily accommodates thousands of operational users but would require migrating to PostgreSQL if scaling to tens of thousands of writes per second.
