import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator
from app.config import DB_PATH

def get_utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # High-concurrency WAL configuration
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn

@contextmanager
def db_transaction() -> Generator[sqlite3.Connection, None, None]:
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    conn = get_db_connection()
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS teams (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS team_memberships (
            user_id TEXT NOT NULL,
            team_id TEXT NOT NULL,
            role_in_team TEXT NOT NULL DEFAULT 'member',
            PRIMARY KEY (user_id, team_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS work_items (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT NOT NULL,
            priority TEXT NOT NULL,
            creator_id TEXT NOT NULL,
            assignee_id TEXT,
            assigned_team TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            target_sla_minutes INTEGER NOT NULL DEFAULT 240,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resolved_at TEXT,
            sla_breached INTEGER NOT NULL DEFAULT 0,
            sla_risk_level TEXT NOT NULL DEFAULT 'NORMAL',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (creator_id) REFERENCES users(id),
            FOREIGN KEY (assignee_id) REFERENCES users(id),
            FOREIGN KEY (assigned_team) REFERENCES teams(id)
        );

        CREATE TABLE IF NOT EXISTS work_item_events (
            id TEXT PRIMARY KEY,
            work_item_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            actor_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            from_state TEXT,
            to_state TEXT,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (work_item_id) REFERENCES work_items(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS idempotency_keys (
            idempotency_key TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            request_path TEXT NOT NULL,
            request_payload_hash TEXT NOT NULL,
            response_status_code INTEGER NOT NULL,
            response_body TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS async_jobs (
            id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            work_item_id TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'PENDING',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            last_error TEXT,
            run_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            completed_at TEXT
        );

        -- Crucial composite and covering indexes for scale (tens of thousands of items)
        CREATE INDEX IF NOT EXISTS idx_work_items_status_priority ON work_items(status, priority);
        CREATE INDEX IF NOT EXISTS idx_work_items_team_status ON work_items(assigned_team, status);
        CREATE INDEX IF NOT EXISTS idx_work_items_assignee_status ON work_items(assignee_id, status);
        CREATE INDEX IF NOT EXISTS idx_work_items_created ON work_items(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_events_work_item ON work_item_events(work_item_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_async_jobs_pending ON async_jobs(status, run_at);
        CREATE INDEX IF NOT EXISTS idx_idempotency_lookup ON idempotency_keys(idempotency_key, user_id);
        """)
    conn.close()
