# Known Limitations & Production Roadmap

This document outlines the known limitations of the current implementation and recommended paths for subsequent production hardening.

---

## 1. Single-Node Storage & Multi-Master Write Scaling
- **Current State:** The system uses SQLite in WAL mode with connection busy timeouts and composite indexing. This supports unlimited concurrent readers and approximately 2,000–5,000 serialized write transactions per second on modern hardware, which easily satisfies thousands of registered users and operational staff.
- **Limitation:** In a multi-datacenter active-active cluster or horizontal auto-scaling container tier (e.g. AWS ECS/EKS with multiple independent container instances writing to the same filesystem), SQLite requires a distributed storage layer or single-writer configuration.
- **Production Path:** Migrate the `app/database.py` connection layer to PostgreSQL (e.g., using `asyncpg` or `SQLAlchemy`/`Tortoise-ORM`) with read replicas and connection pooling (PgBouncer).

---

## 2. In-Process Background Job Runner vs. Distributed Work Queues
- **Current State:** The asynchronous worker runs as an autonomous `asyncio` loop within the application process, polling the persistent `async_jobs` table with atomic conditional status claims (`UPDATE ... WHERE status = 'PENDING'`), exponential backoff, and dead-letter queue routing.
- **Limitation:** If the server is stopped, background jobs will pause until the server restarts. While persistence guarantees zero job loss, execution is coupled to the server runtime.
- **Production Path:** Split the worker loop into a standalone decoupled daemon or integrate with Redis/Celery/Temporal for massive-scale distributed workflow orchestration.

---

## 3. Real-Time UI Streaming (WebSockets / Server-Sent Events)
- **Current State:** The frontend uses fast polling and reactive event refresh on action completion (claim, transition, approve). Changes made by another user appear when navigating queues or triggering actions.
- **Limitation:** If User A claims an item while User B has the page open on their monitor without interacting, User B will discover the change when clicking an action (getting an informative OCC 409 notification) rather than seeing the assignee badge live-update via WebSocket push.
- **Production Path:** Add a FastAPI WebSocket endpoint (`/ws/events`) broadcasting audit ledger changes to connected browser clients for instant UI reactivity.

---

## 4. Idempotency Key Expiration & Partitioning
- **Current State:** All idempotency receipts are permanently stored in the `idempotency_keys` table.
- **Limitation:** Over years of operation with millions of requests, the table size will grow linearly unless pruned.
- **Production Path:** Implement an automated scheduled cleanup task that deletes or archives idempotency keys older than 30 days (e.g., `DELETE FROM idempotency_keys WHERE created_at < NOW() - INTERVAL '30 days'`).

---

## 5. Enterprise Identity Provider (IdP) Integration
- **Current State:** The application provides a full multi-team RBAC model with an interactive user persona switcher in the header and header-based authentication (`X-User-Id`), ideal for testing, local pairing, and evaluation of cross-team boundaries.
- **Limitation:** Production enterprise deployments require SAML 2.0 / OIDC (Okta, Google Workspace, Azure AD) integration.
- **Production Path:** Mount an OAuth2/OIDC middleware in FastAPI that decodes JWT claims from corporate SSO and maps enterprise groups to internal teams (`tier1_support`, `incident_response`, etc.).
