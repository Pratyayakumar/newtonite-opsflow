# Newtonite OpsFlow

A full-stack operational work management system built for the **Newtonite Software Engineering Challenge**.

OpsFlow is designed to help teams create, assign, track, collaborate on, and resolve operational work items while maintaining authorization, auditability, concurrency safety, and reliable state transitions.

## Overview

Modern operational teams often manage work through chat messages, spreadsheets, emails, and direct conversations. As the organization grows, this can lead to:

* unclear ownership
* duplicated work
* stale updates
* lost requests
* inconsistent workflow transitions
* limited visibility into what changed and why

**Newtonite OpsFlow** provides a centralized system for managing operational work items with a focus on reliability and correctness rather than simple CRUD functionality.

## Key Features

### Work Item Management

* Create and manage operational work items
* Assign work to responsible users
* Track priority and status
* Add descriptions and comments
* View the complete history of important changes

### Workflow Management

Supported workflow:

```text
OPEN
  ↓
IN_PROGRESS
  ↓
BLOCKED
  ↓
RESOLVED
  ↓
CLOSED
```

The backend validates workflow transitions rather than relying only on frontend controls.

### Authorization

The application includes backend-enforced authorization based on users, teams, and responsibilities.

Authorization is enforced at the API/resource level and does not depend only on hiding frontend controls.

### Concurrency Control

The system handles concurrent updates using optimistic concurrency control.

Each work item maintains a version number. If a user attempts to update stale information, the server detects the version conflict instead of silently overwriting another user's changes.

```text
User A reads Version 5
        ↓
User B updates → Version 6
        ↓
User A submits Version 5
        ↓
HTTP 409 Conflict
```

### Idempotent Operations

The application supports idempotency for operations where repeated requests could otherwise create duplicate actions.

This protects against scenarios such as network retries or users accidentally submitting the same request multiple times.

### Activity History

Important changes are recorded so users can understand how a work item evolved.

Examples include:

* assignment changes
* status changes
* priority changes
* comments
* other important workflow actions

### Asynchronous Processing

Secondary processing can be handled asynchronously so that the primary user operation does not unnecessarily depend on background work completing immediately.

The implementation also considers delayed or repeated background execution.

## Architecture

```text
┌─────────────────────────────┐
│          Browser            │
│      HTML / CSS / JS        │
└──────────────┬──────────────┘
               │ HTTP
               ▼
┌─────────────────────────────┐
│        Application API      │
│                             │
│ Authentication              │
│ Authorization               │
│ Validation                  │
│ Workflow Rules              │
│ Concurrency Control         │
│ Idempotency                 │
└──────────────┬──────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
┌──────────────┐  ┌───────────────┐
│   Database   │  │ Async Worker  │
│              │  │               │
│ Work Items   │  │ Background    │
│ Users        │  │ Processing    │
│ Teams        │  │ Jobs          │
│ History      │  │               │
└──────────────┘  └───────────────┘
```

## Project Structure

```text
newtonite-opsflow/
│
├── app/
│   ├── api.py
│   ├── async_worker.py
│   ├── auth.py
│   ├── concurrency.py
│   ├── config.py
│   ├── database.py
│   ├── idempotency.py
│   ├── main.py
│   ├── models.py
│   ├── seed.py
│   ├── state_machine.py
│   └── static/
│       ├── app.js
│       ├── index.html
│       └── style.css
│
├── tests/
│   ├── conftest.py
│   ├── test_async_jobs.py
│   ├── test_authorization.py
│   ├── test_concurrency.py
│   ├── test_idempotency.py
│   └── test_state_machine.py
│
├── ENGINEERING_DECISIONS.md
├── KNOWN_LIMITATIONS.md
├── README.md
├── requirements.txt
└── run.py
```

## Technology Stack

* **Python**
* **FastAPI**
* **SQLite**
* **Pydantic**
* **Pytest**
* HTML5
* CSS3
* JavaScript

The implementation intentionally keeps the architecture lightweight so that the core reliability and correctness behaviours can be demonstrated within the one-day assessment constraint.

## Running Locally

### 1. Clone the repository

```bash
git clone https://github.com/Pratyayakumar/newtonite-opsflow.git
cd newtonite-opsflow
```

### 2. Create a virtual environment

#### Windows

```bash
python -m venv .venv
.venv\Scripts\activate
```

#### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Start the application

```bash
python run.py
```

The application will start locally.

Open the URL shown in the terminal in your browser.

## Running Tests

Run the complete automated test suite:

```bash
pytest -q
```

The test suite covers important behaviours including:

* authorization
* concurrent operations
* idempotency
* workflow/state transitions
* asynchronous processing

## Important Correctness Behaviours

The implementation specifically addresses scenarios that require more than basic CRUD operations.

### 1. Concurrent Updates

Multiple users can interact with the same work item. Optimistic concurrency prevents stale updates from silently overwriting newer changes.

### 2. Duplicate Requests

Idempotency mechanisms prevent repeated requests from producing unintended duplicate operations.

### 3. Workflow Enforcement

The backend validates allowed state transitions, preventing invalid workflow changes even when requests bypass the frontend.

### 4. Authorization

Permissions are enforced by the server at the resource/action level rather than relying only on UI visibility.

## Engineering Decisions

Detailed architectural and implementation decisions are documented in:

**[ENGINEERING_DECISIONS.md](ENGINEERING_DECISIONS.md)**

The document explains the reasoning and trade-offs behind the main design choices.

## Known Limitations

Known limitations and intentionally deferred functionality are documented in:

**[KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)**

The project prioritizes a smaller, reliable implementation over an unnecessarily large feature set.

## Testing Philosophy

The testing strategy focuses on behaviours where a defect could cause serious operational problems.

Instead of targeting an arbitrary coverage percentage, tests concentrate on:

```text
Authorization
      ↓
Concurrency
      ↓
Idempotency
      ↓
Workflow correctness
      ↓
Async processing
```

## Future Improvements

If the system were developed further, potential improvements would include:

* PostgreSQL for larger production workloads
* Redis-backed distributed job processing
* real-time updates using WebSockets
* advanced search and filtering
* notification preferences
* richer team administration
* observability and structured logging
* distributed tracing
* production-grade authentication and SSO
* horizontal scaling and deployment automation

## Assessment Context

This project was developed as a solution for the:

**Newtonite Software Engineering Challenge — Operations Under Pressure**

The implementation focuses on demonstrating practical engineering judgement around:

* data modelling
* API design
* authorization
* concurrency
* idempotency
* workflow consistency
* asynchronous processing
* automated testing
* maintainability

---

**Author:** Pratyaya Kumar
**Repository:** `newtonite-opsflow`
