"""
pg_db.py — PostgreSQL (Neon) connection and schema management.

Handles campaigns, contacts, call_logs, tenants, and credit tables.
MongoDB handles call_insights and lead_info (AI analysis).
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from functools import lru_cache
from typing import Optional

import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool

from config import DATABASE_URL

logger = logging.getLogger(__name__)

# Connection pool (min=1, max=10 connections)
_pool: Optional[SimpleConnectionPool] = None


def get_pool() -> SimpleConnectionPool:
    """Return the connection pool singleton."""
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set in environment variables.")
        _pool = SimpleConnectionPool(1, 10, DATABASE_URL)
        logger.info("PostgreSQL connection pool created")
    return _pool


@contextmanager
def get_connection():
    """Context manager for getting a connection from the pool."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def init_db() -> None:
    """Create all required tables if they don't exist."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # campaigns table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS campaigns (
                    campaign_id VARCHAR(255) PRIMARY KEY,
                    client_id VARCHAR(255) NOT NULL DEFAULT 'default',
                    name VARCHAR(500) NOT NULL,
                    status VARCHAR(50) NOT NULL DEFAULT 'Idle',
                    concurrency_limit INTEGER NOT NULL DEFAULT 5,
                    virtual_number VARCHAR(50) NOT NULL,
                    inter_call_delay_ms INTEGER NOT NULL DEFAULT 1000,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    finished_at TIMESTAMP WITH TIME ZONE,
                    original_columns JSONB DEFAULT '[]'::jsonb
                );
            """)
            
            # Add client_id column if it doesn't exist (migration)
            cur.execute("""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='campaigns' AND column_name='client_id'
                    ) THEN
                        ALTER TABLE campaigns ADD COLUMN client_id VARCHAR(255) NOT NULL DEFAULT 'default';
                    END IF;
                END $$;
            """)
            
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_campaigns_client_id ON campaigns(client_id);
                CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status);
                CREATE INDEX IF NOT EXISTS idx_campaigns_created_at ON campaigns(created_at DESC);
            """)

            # contacts table (leads)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS contacts (
                    lead_id VARCHAR(255) PRIMARY KEY,
                    campaign_id VARCHAR(255) NOT NULL,
                    client_id VARCHAR(255) NOT NULL DEFAULT 'default',
                    name VARCHAR(500),
                    phone VARCHAR(50) NOT NULL,
                    company VARCHAR(500),
                    extra JSONB DEFAULT '{}'::jsonb,
                    status VARCHAR(50) NOT NULL DEFAULT 'Pending',
                    classification VARCHAR(50),
                    call_sid VARCHAR(255),
                    call_duration_seconds NUMERIC(10, 2),
                    transcript_summary TEXT,
                    error TEXT,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                );
            """)
            
            # Add missing columns if they don't exist (migration)
            cur.execute("""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='contacts' AND column_name='client_id'
                    ) THEN
                        ALTER TABLE contacts ADD COLUMN client_id VARCHAR(255) NOT NULL DEFAULT 'default';
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='contacts' AND column_name='classification'
                    ) THEN
                        ALTER TABLE contacts ADD COLUMN classification VARCHAR(50);
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='contacts' AND column_name='call_sid'
                    ) THEN
                        ALTER TABLE contacts ADD COLUMN call_sid VARCHAR(255);
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='contacts' AND column_name='call_duration_seconds'
                    ) THEN
                        ALTER TABLE contacts ADD COLUMN call_duration_seconds NUMERIC(10, 2);
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='contacts' AND column_name='transcript_summary'
                    ) THEN
                        ALTER TABLE contacts ADD COLUMN transcript_summary TEXT;
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='contacts' AND column_name='error'
                    ) THEN
                        ALTER TABLE contacts ADD COLUMN error TEXT;
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='contacts' AND column_name='extra'
                    ) THEN
                        ALTER TABLE contacts ADD COLUMN extra JSONB DEFAULT '{}'::jsonb;
                    END IF;
                END $$;
            """)
            
            # Add foreign key constraint if it doesn't exist
            cur.execute("""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.table_constraints 
                        WHERE constraint_name='contacts_campaign_id_fkey'
                    ) THEN
                        ALTER TABLE contacts ADD CONSTRAINT contacts_campaign_id_fkey 
                        FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE;
                    END IF;
                END $$;
            """)
            
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_contacts_campaign_id ON contacts(campaign_id);
                CREATE INDEX IF NOT EXISTS idx_contacts_client_id ON contacts(client_id);
                CREATE INDEX IF NOT EXISTS idx_contacts_status ON contacts(status);
                CREATE INDEX IF NOT EXISTS idx_contacts_call_sid ON contacts(call_sid);
                CREATE INDEX IF NOT EXISTS idx_contacts_classification ON contacts(classification);
            """)

            # billing table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS billing (
                    id SERIAL PRIMARY KEY,
                    lead_id VARCHAR(255) NOT NULL UNIQUE,
                    campaign_id VARCHAR(255) NOT NULL,
                    client_id VARCHAR(255) NOT NULL DEFAULT 'default',
                    lead_name VARCHAR(500),
                    lead_phone VARCHAR(50),
                    duration_seconds NUMERIC(10, 2) NOT NULL,
                    billed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    month VARCHAR(7) NOT NULL
                );
            """)
            
            # Add missing columns if they don't exist (migration)
            cur.execute("""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='billing' AND column_name='client_id'
                    ) THEN
                        ALTER TABLE billing ADD COLUMN client_id VARCHAR(255) NOT NULL DEFAULT 'default';
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='billing' AND column_name='month'
                    ) THEN
                        ALTER TABLE billing ADD COLUMN month VARCHAR(7) NOT NULL DEFAULT TO_CHAR(NOW(), 'YYYY-MM');
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='billing' AND column_name='lead_name'
                    ) THEN
                        ALTER TABLE billing ADD COLUMN lead_name VARCHAR(500);
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='billing' AND column_name='lead_phone'
                    ) THEN
                        ALTER TABLE billing ADD COLUMN lead_phone VARCHAR(50);
                    END IF;
                END $$;
            """)
            
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_billing_client_month ON billing(client_id, month);
                CREATE INDEX IF NOT EXISTS idx_billing_campaign_month ON billing(campaign_id, month);
                CREATE INDEX IF NOT EXISTS idx_billing_billed_at ON billing(billed_at DESC);
            """)

            # call_logs table (Exotel events)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS call_logs (
                    id SERIAL PRIMARY KEY,
                    campaign_id VARCHAR(255),
                    execution_id VARCHAR(255),
                    call_sid VARCHAR(255),
                    status VARCHAR(100),
                    event_data JSONB DEFAULT '{}'::jsonb,
                    received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                );
            """)
            
            # Add missing columns if they don't exist (migration)
            cur.execute("""
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='call_logs' AND column_name='call_sid'
                    ) THEN
                        ALTER TABLE call_logs ADD COLUMN call_sid VARCHAR(255);
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='call_logs' AND column_name='execution_id'
                    ) THEN
                        ALTER TABLE call_logs ADD COLUMN execution_id VARCHAR(255);
                    END IF;
                    
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name='call_logs' AND column_name='event_data'
                    ) THEN
                        ALTER TABLE call_logs ADD COLUMN event_data JSONB DEFAULT '{}'::jsonb;
                    END IF;
                END $$;
            """)
            
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_call_logs_campaign_id ON call_logs(campaign_id);
                CREATE INDEX IF NOT EXISTS idx_call_logs_call_sid ON call_logs(call_sid);
                CREATE INDEX IF NOT EXISTS idx_call_logs_received_at ON call_logs(received_at DESC);
            """)

            # ── Multi-tenant tables ───────────────────────────────────────────

            cur.execute("""
                CREATE TABLE IF NOT EXISTS tenants (
                    tenant_id          VARCHAR(255) PRIMARY KEY,
                    name               VARCHAR(500) NOT NULL,
                    plan               VARCHAR(50)  NOT NULL DEFAULT 'starter',
                    parent_id          VARCHAR(255) REFERENCES tenants(tenant_id),
                    price_per_credit   NUMERIC(10,2) NOT NULL DEFAULT 10.00,
                    created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
                );
            """)

            # Add price_per_credit column if it doesn't exist (migration)
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='tenants' AND column_name='price_per_credit'
                    ) THEN
                        ALTER TABLE tenants ADD COLUMN price_per_credit NUMERIC(10,2) NOT NULL DEFAULT 10.00;
                    END IF;
                END $$;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id      VARCHAR(255) PRIMARY KEY,
                    tenant_id   VARCHAR(255) NOT NULL REFERENCES tenants(tenant_id),
                    key_hash    VARCHAR(255) NOT NULL UNIQUE,
                    name        VARCHAR(255),
                    role        VARCHAR(50)  NOT NULL DEFAULT 'manager',
                    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                    last_used   TIMESTAMPTZ,
                    revoked     BOOLEAN      NOT NULL DEFAULT FALSE
                );
            """)

            # Add role column to api_keys if it doesn't exist (migration)
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='api_keys' AND column_name='role'
                    ) THEN
                        ALTER TABLE api_keys ADD COLUMN role VARCHAR(50) NOT NULL DEFAULT 'manager';
                    END IF;
                END $$;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS campaign_templates (
                    template_id         VARCHAR(255) PRIMARY KEY,
                    tenant_id           VARCHAR(255) NOT NULL,
                    name                VARCHAR(500) NOT NULL,
                    concurrency_limit   INTEGER,
                    inter_call_delay_ms INTEGER,
                    script_config       JSONB DEFAULT '{}'::jsonb,
                    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS lead_interactions (
                    id          SERIAL PRIMARY KEY,
                    lead_id     VARCHAR(255) NOT NULL,
                    tenant_id   VARCHAR(255) NOT NULL,
                    type        VARCHAR(50)  NOT NULL,
                    summary     TEXT,
                    metadata    JSONB DEFAULT '{}'::jsonb,
                    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS follow_ups (
                    id           SERIAL PRIMARY KEY,
                    lead_id      VARCHAR(255) NOT NULL,
                    campaign_id  VARCHAR(255),
                    tenant_id    VARCHAR(255) NOT NULL,
                    scheduled_at TIMESTAMPTZ NOT NULL,
                    status       VARCHAR(50) NOT NULL DEFAULT 'pending',
                    notes        TEXT,
                    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

            # ── Composite indexes on existing tables ──────────────────────────
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_contacts_score
                    ON contacts(((extra->>'lead_score')::int) DESC);
            """)
            # updated_at index — only if the column exists
            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='contacts' AND column_name='updated_at'
                    ) THEN
                        CREATE INDEX IF NOT EXISTS idx_contacts_updated
                            ON contacts(updated_at DESC);
                    END IF;
                END $$;
            """)
            # tenant_id index — only if the column exists
            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='billing' AND column_name='tenant_id'
                    ) THEN
                        CREATE INDEX IF NOT EXISTS idx_billing_month_tenant
                            ON billing(tenant_id, month);
                    END IF;
                END $$;
            """)

            # Add tenant_id column to billing if it doesn't exist (migration)
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='billing' AND column_name='tenant_id'
                    ) THEN
                        ALTER TABLE billing ADD COLUMN tenant_id VARCHAR(255);
                    END IF;
                END $$;
            """)

            # Add calling_window and min_connection_rate to campaigns (migration)
            cur.execute("""
                ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS calling_window JSONB DEFAULT NULL;
                ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS min_connection_rate FLOAT DEFAULT NULL;
            """)

            # ── Credit system tables ──────────────────────────────────────────

            cur.execute("""
                CREATE TABLE IF NOT EXISTS credit_balances (
                    tenant_id   VARCHAR(255) PRIMARY KEY REFERENCES tenants(tenant_id),
                    balance     NUMERIC(14,6) NOT NULL DEFAULT 0,
                    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
                    CONSTRAINT  balance_non_negative CHECK (balance >= 0)
                );
            """)

            # Migrate balance column from INTEGER to NUMERIC if needed
            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='credit_balances' AND column_name='balance'
                          AND data_type='integer'
                    ) THEN
                        ALTER TABLE credit_balances ALTER COLUMN balance TYPE NUMERIC(14,6);
                    END IF;
                END $$;
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS credit_ledger (
                    id               BIGSERIAL     PRIMARY KEY,
                    tenant_id        VARCHAR(255)  NOT NULL REFERENCES tenants(tenant_id),
                    transaction_type VARCHAR(20)   NOT NULL
                                     CHECK (transaction_type IN ('purchase','reservation','deduction','release','adjustment')),
                    amount           NUMERIC(14,6) NOT NULL,
                    call_sid         VARCHAR(255),
                    campaign_id      VARCHAR(255),
                    description      TEXT,
                    idempotency_key  VARCHAR(255),
                    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
                );
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_credit_ledger_tenant_created
                    ON credit_ledger(tenant_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_credit_ledger_call_sid
                    ON credit_ledger(call_sid)
                    WHERE call_sid IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_ledger_idempotency
                    ON credit_ledger(idempotency_key)
                    WHERE idempotency_key IS NOT NULL;
            """)

            logger.info("PostgreSQL schema initialized")


# ── Campaign operations ───────────────────────────────────────────────────────

def create_campaign(
    campaign_id: str,
    client_id: str,
    name: str,
    concurrency_limit: int,
    virtual_number: str,
    inter_call_delay_ms: int,
    original_columns: list[str],
    calling_window: Optional[dict] = None,
    min_connection_rate: Optional[float] = None,
) -> None:
    """Insert a new campaign record."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO campaigns (
                    campaign_id, client_id, name, status, concurrency_limit,
                    virtual_number, inter_call_delay_ms, original_columns,
                    calling_window, min_connection_rate
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                campaign_id, client_id, name, "Idle", concurrency_limit,
                virtual_number, inter_call_delay_ms, psycopg2.extras.Json(original_columns),
                psycopg2.extras.Json(calling_window) if calling_window is not None else None,
                min_connection_rate,
            ))


def update_campaign_status(campaign_id: str, status: str, finished_at=None) -> None:
    """Update campaign status and optionally set finished_at timestamp."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if finished_at:
                cur.execute("""
                    UPDATE campaigns SET status = %s, finished_at = %s WHERE campaign_id = %s
                """, (status, finished_at, campaign_id))
            else:
                cur.execute("""
                    UPDATE campaigns SET status = %s WHERE campaign_id = %s
                """, (status, campaign_id))


def get_campaign(campaign_id: str) -> Optional[dict]:
    """Fetch a single campaign by ID."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM campaigns WHERE campaign_id = %s", (campaign_id,))
            return cur.fetchone()


def list_campaigns(client_id: str, limit: int = 100) -> list[dict]:
    """List all campaigns for a client, most recent first."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM campaigns WHERE client_id = %s
                ORDER BY created_at DESC LIMIT %s
            """, (client_id, limit))
            return cur.fetchall()


# ── Contact/Lead operations ───────────────────────────────────────────────────

def insert_contacts(contacts: list[dict]) -> None:
    """Bulk insert contacts/leads."""
    if not contacts:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO contacts (
                    lead_id, campaign_id, client_id, name, phone, company, extra, status
                ) VALUES (%(lead_id)s, %(campaign_id)s, %(client_id)s, %(name)s, %(phone)s, %(company)s, %(extra)s, %(status)s)
            """, contacts)


def get_contact(lead_id: str) -> Optional[dict]:
    """Fetch a single contact by lead_id."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM contacts WHERE lead_id = %s", (lead_id,))
            return cur.fetchone()


def get_contact_by_call_sid(call_sid: str) -> Optional[dict]:
    """Fetch a contact by call_sid."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM contacts WHERE call_sid = %s", (call_sid,))
            return cur.fetchone()


def update_contact_status(lead_id: str, status: str) -> None:
    """Update contact status."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE contacts SET status = %s, updated_at = NOW() WHERE lead_id = %s
            """, (status, lead_id))


def update_contact_call_sid(lead_id: str, call_sid: str) -> None:
    """Set call_sid for a contact."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE contacts SET call_sid = %s, updated_at = NOW() WHERE lead_id = %s
            """, (call_sid, lead_id))


def update_contact_call_result(
    lead_id: str,
    status: str,
    duration: Optional[float] = None,
    classification: Optional[str] = None,
    transcript_summary: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Update contact with call results."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE contacts SET
                    status = %s,
                    call_duration_seconds = COALESCE(%s, call_duration_seconds),
                    classification = COALESCE(%s, classification),
                    transcript_summary = COALESCE(%s, transcript_summary),
                    error = COALESCE(%s, error),
                    updated_at = NOW()
                WHERE lead_id = %s
            """, (status, duration, classification, transcript_summary, error, lead_id))


def list_contacts(campaign_id: str, status: Optional[str] = None) -> list[dict]:
    """List contacts for a campaign, optionally filtered by status."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if status:
                cur.execute("""
                    SELECT * FROM contacts WHERE campaign_id = %s AND status = %s
                    ORDER BY created_at
                """, (campaign_id, status))
            else:
                cur.execute("""
                    SELECT * FROM contacts WHERE campaign_id = %s ORDER BY created_at
                """, (campaign_id,))
            return cur.fetchall()


def get_campaign_stats(campaign_id: str) -> dict:
    """Aggregate stats for a campaign."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE status = 'Pending') as pending,
                    COUNT(*) FILTER (WHERE status = 'Dialing') as dialing,
                    COUNT(*) FILTER (WHERE status = 'In_Progress') as in_progress,
                    COUNT(*) FILTER (WHERE status = 'Completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'Failed') as failed,
                    COUNT(*) FILTER (WHERE status = 'Not_Picked') as not_picked,
                    COUNT(*) FILTER (WHERE status = 'Cancelled') as cancelled,
                    COUNT(*) FILTER (WHERE classification = 'Hot') as hot,
                    COUNT(*) FILTER (WHERE classification = 'Warm') as warm,
                    COUNT(*) FILTER (WHERE classification = 'Cold') as cold,
                    COUNT(*) FILTER (WHERE classification = 'Not_Picked') as not_picked_classification
                FROM contacts WHERE campaign_id = %s
            """, (campaign_id,))
            return cur.fetchone() or {}

# ── Call logs ─────────────────────────────────────────────────────────────────

def log_call_event(
    campaign_id: Optional[str],
    execution_id: Optional[str],
    call_sid: Optional[str],
    status: str,
    event_data: dict,
) -> None:
    """Insert a call event log."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO call_logs (campaign_id, execution_id, call_sid, status, event_data)
                VALUES (%s, %s, %s, %s, %s)
            """, (campaign_id, execution_id, call_sid, status, psycopg2.extras.Json(event_data)))


# ── Tenant operations ─────────────────────────────────────────────────────────

def create_tenant(
    pool,
    tenant_id: str,
    name: str,
    plan: str = "starter",
    parent_id: Optional[str] = None,
    price_per_credit: float = 10.00,
) -> None:
    """Insert a new tenant record."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tenants (tenant_id, name, plan, parent_id, price_per_credit)
                VALUES (%s, %s, %s, %s, %s)
            """, (tenant_id, name, plan, parent_id, price_per_credit))


def get_credit_pricing(tenant_id: str) -> float:
    """Return the price per credit (INR) for a tenant. Defaults to ₹10.00 if not set."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT price_per_credit FROM tenants WHERE tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
            if row is None:
                return 10.00
            return float(row[0])


def set_credit_pricing(tenant_id: str, price_per_credit: float) -> float:
    """Set the price per credit (INR) for a tenant. Returns the new price."""
    if price_per_credit <= 0:
        raise ValueError("price_per_credit must be a positive number")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tenants SET price_per_credit = %s WHERE tenant_id = %s
                RETURNING price_per_credit
                """,
                (price_per_credit, tenant_id),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Tenant '{tenant_id}' not found")
            return float(row[0])


# ── API key operations ────────────────────────────────────────────────────────

def create_api_key(
    pool,
    key_id: str,
    tenant_id: str,
    key_hash: str,
    name: Optional[str] = None,
    role: str = "manager",
) -> dict:
    """Insert a new API key and return the created record."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO api_keys (key_id, tenant_id, key_hash, name, role)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
            """, (key_id, tenant_id, key_hash, name, role))
            return dict(cur.fetchone())


def get_api_key_by_hash(pool, key_hash: str) -> Optional[dict]:
    """Return the API key record (including tenant_id and role) for a given hash, or None."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM api_keys WHERE key_hash = %s AND revoked = FALSE
            """, (key_hash,))
            row = cur.fetchone()
            return dict(row) if row else None


def revoke_api_key(pool, key_id: str, tenant_id: str) -> None:
    """Mark an API key as revoked (scoped to the owning tenant)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE api_keys SET revoked = TRUE
                WHERE key_id = %s AND tenant_id = %s
            """, (key_id, tenant_id))


# ── Campaign template operations ──────────────────────────────────────────────

def save_template(
    pool,
    template_id: str,
    tenant_id: str,
    name: str,
    concurrency_limit: Optional[int] = None,
    inter_call_delay_ms: Optional[int] = None,
    script_config: Optional[dict] = None,
) -> None:
    """Insert or replace a campaign template."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO campaign_templates
                    (template_id, tenant_id, name, concurrency_limit, inter_call_delay_ms, script_config)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (template_id) DO UPDATE SET
                    name                = EXCLUDED.name,
                    concurrency_limit   = EXCLUDED.concurrency_limit,
                    inter_call_delay_ms = EXCLUDED.inter_call_delay_ms,
                    script_config       = EXCLUDED.script_config
            """, (
                template_id, tenant_id, name,
                concurrency_limit, inter_call_delay_ms,
                psycopg2.extras.Json(script_config or {}),
            ))


def list_templates(pool, tenant_id: str) -> list[dict]:
    """Return all templates for a tenant, newest first."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM campaign_templates
                WHERE tenant_id = %s
                ORDER BY created_at DESC
            """, (tenant_id,))
            return [dict(r) for r in cur.fetchall()]


def clone_campaign(
    pool,
    source_campaign_id: str,
    new_campaign_id: str,
    new_name: str,
    tenant_id: str,
) -> dict:
    """Clone a campaign (config only, no leads) and return the new campaign record."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO campaigns
                    (campaign_id, client_id, name, status, concurrency_limit,
                     virtual_number, inter_call_delay_ms, original_columns)
                SELECT
                    %s, %s, %s, 'Idle', concurrency_limit,
                    virtual_number, inter_call_delay_ms, original_columns
                FROM campaigns
                WHERE campaign_id = %s
                RETURNING *
            """, (new_campaign_id, tenant_id, new_name, source_campaign_id))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Source campaign '{source_campaign_id}' not found")
            return dict(row)


# ── Lead interaction operations ───────────────────────────────────────────────

def insert_interaction(
    pool,
    lead_id: str,
    tenant_id: str,
    type: str,
    summary: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Record a lead interaction event."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO lead_interactions (lead_id, tenant_id, type, summary, metadata)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                lead_id, tenant_id, type, summary,
                psycopg2.extras.Json(metadata or {}),
            ))


# ── Follow-up operations ──────────────────────────────────────────────────────

def upsert_follow_up(
    pool,
    lead_id: str,
    tenant_id: str,
    scheduled_at,
    campaign_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """Insert or update a follow-up task for a lead; returns the upserted record."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO follow_ups (lead_id, tenant_id, campaign_id, scheduled_at, notes)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING *
            """, (lead_id, tenant_id, campaign_id, scheduled_at, notes))
            row = cur.fetchone()
            if row is None:
                # Row already existed — update scheduled_at and notes, return updated row
                cur.execute("""
                    UPDATE follow_ups
                    SET scheduled_at = %s,
                        notes        = COALESCE(%s, notes),
                        campaign_id  = COALESCE(%s, campaign_id)
                    WHERE lead_id = %s AND tenant_id = %s AND status = 'pending'
                    RETURNING *
                """, (scheduled_at, notes, campaign_id, lead_id, tenant_id))
                row = cur.fetchone()
            return dict(row) if row else {}
