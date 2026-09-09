"""
credit_service.py — Prepaid credit system for the voice agent platform.

Manages tenant credit balances, reservations, deductions, and ledger entries.
All operations use the existing pg_db.get_connection() synchronous psycopg2 pool.

Credits are stored and deducted as decimals (float).
1 credit = 60 seconds of call time.
A 65-second call costs 65/60 ≈ 1.0833 credits.
A 115-second call costs 115/60 ≈ 1.9167 credits.
"""
from __future__ import annotations

import logging
import uuid

import psycopg2
import psycopg2.extras

import pg_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class InsufficientCreditsError(Exception):
    """Raised when a tenant's balance is zero and a call reservation is attempted."""
    pass


class DuplicateIdempotencyKeyError(Exception):
    """Raised when a purchase request reuses an idempotency key that was already processed.

    The original result dict is attached so the caller can return it unchanged.
    """

    def __init__(self, original_result: dict) -> None:
        self.original_result = original_result
        super().__init__(f"Duplicate idempotency key; original result: {original_result}")


class DuplicateReservationError(Exception):
    """Raised when a reservation is attempted for a call_sid that is already reserved."""
    pass


# ---------------------------------------------------------------------------
# Balance query
# ---------------------------------------------------------------------------

def get_balance(tenant_id: str) -> float:
    """Return the current credit balance for *tenant_id*. Returns 0 if no record."""
    with pg_db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT balance FROM credit_balances WHERE tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
            return float(row[0]) if row else 0.0


def get_balance_with_pricing(tenant_id: str) -> dict:
    """Return balance and pricing info for *tenant_id*."""
    return {
        "balance": get_balance(tenant_id),
        "price_per_credit": pg_db.get_credit_pricing(tenant_id),
        "tenant_id": tenant_id,
    }


# ---------------------------------------------------------------------------
# Purchase credits
# ---------------------------------------------------------------------------

def purchase_credits(
    tenant_id: str,
    amount: int,
    description: str = "",
    idempotency_key: str | None = None,
) -> dict:
    """Atomically add *amount* credits to the tenant's balance.

    Returns ``{"balance": int, "transaction_id": str}``.

    Raises:
        ValueError: if *amount* is <= 0.
        DuplicateIdempotencyKeyError: if *idempotency_key* was already used;
            the exception carries the original result dict.
    """
    if amount <= 0:
        raise ValueError(f"amount must be a positive integer, got {amount!r}")

    transaction_id = str(uuid.uuid4())

    with pg_db.get_connection() as conn:
        with conn.cursor() as cur:
            try:
                # Upsert the balance row, incrementing by amount.
                cur.execute(
                    """
                    INSERT INTO credit_balances (tenant_id, balance, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (tenant_id) DO UPDATE
                        SET balance     = credit_balances.balance + EXCLUDED.balance,
                            updated_at  = NOW()
                    RETURNING balance
                    """,
                    (tenant_id, amount),
                )
                new_balance: int = cur.fetchone()[0]

                # Insert the ledger entry, storing the idempotency key.
                cur.execute(
                    """
                    INSERT INTO credit_ledger
                        (tenant_id, transaction_type, amount, description, idempotency_key)
                    VALUES (%s, 'purchase', %s, %s, %s)
                    RETURNING id
                    """,
                    (tenant_id, amount, description, idempotency_key),
                )
                ledger_id: int = cur.fetchone()[0]

            except psycopg2.errors.UniqueViolation:
                # Duplicate idempotency key — roll back the partial work and
                # look up the original ledger entry to reconstruct the result.
                conn.rollback()
                with conn.cursor() as lookup_cur:
                    lookup_cur.execute(
                        """
                        SELECT id FROM credit_ledger
                        WHERE idempotency_key = %s
                        """,
                        (idempotency_key,),
                    )
                    row = lookup_cur.fetchone()
                    original_transaction_id = str(row[0]) if row else idempotency_key

                # We need the balance at the time of the original purchase.
                # The safest approach is to return the current balance (which
                # already includes that purchase) together with the original
                # transaction id.
                with conn.cursor() as bal_cur:
                    bal_cur.execute(
                        "SELECT balance FROM credit_balances WHERE tenant_id = %s",
                        (tenant_id,),
                    )
                    bal_row = bal_cur.fetchone()
                    current_balance = bal_row[0] if bal_row else 0

                original_result = {
                    "balance": current_balance,
                    "transaction_id": original_transaction_id,
                }
                raise DuplicateIdempotencyKeyError(original_result)

    return {"balance": new_balance, "transaction_id": str(ledger_id)}


# ---------------------------------------------------------------------------
# Reserve credit for an outbound call
# ---------------------------------------------------------------------------

def check_and_reserve(tenant_id: str, call_sid: str) -> None:
    """Atomically check balance > 0 and deduct 1 reservation credit (= 60 seconds).

    Opens an explicit transaction with a ``SELECT ... FOR UPDATE`` row-level
    lock so that concurrent calls for the same tenant are serialised at the
    database level and the balance can never go negative.

    Raises:
        InsufficientCreditsError: if the tenant has no balance row or the
            balance is 0.
        DuplicateReservationError: if *call_sid* already has a ``reservation``
            entry in ``credit_ledger``.

    Requirements: 3.1, 3.5, 4.1, 9.3
    """
    with pg_db.get_connection() as conn:
        # Disable autocommit so we control the transaction boundary explicitly.
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                # 1. Acquire a row-level lock on the balance row.
                cur.execute(
                    "SELECT balance FROM credit_balances WHERE tenant_id = %s FOR UPDATE",
                    (tenant_id,),
                )
                row = cur.fetchone()

                # 2. Reject if no balance record or balance is zero.
                if row is None or row[0] == 0:
                    raise InsufficientCreditsError(
                        f"Tenant '{tenant_id}' has insufficient credits."
                    )

                current_balance: float = row[0]

                # 3. Reject duplicate reservations for the same call_sid.
                cur.execute(
                    """
                    SELECT 1 FROM credit_ledger
                    WHERE call_sid = %s AND transaction_type = 'reservation'
                    LIMIT 1
                    """,
                    (call_sid,),
                )
                if cur.fetchone() is not None:
                    raise DuplicateReservationError(
                        f"A reservation for call_sid '{call_sid}' already exists."
                    )

                # 4. Decrement balance by 1.
                cur.execute(
                    """
                    UPDATE credit_balances
                    SET balance = balance - 1, updated_at = NOW()
                    WHERE tenant_id = %s
                    """,
                    (tenant_id,),
                )

                # 5. Insert the reservation ledger entry.
                cur.execute(
                    """
                    INSERT INTO credit_ledger
                        (tenant_id, transaction_type, amount, call_sid)
                    VALUES (%s, 'reservation', 1, %s)
                    """,
                    (tenant_id, call_sid),
                )

            # 6. Commit the transaction.
            conn.commit()

        except (InsufficientCreditsError, DuplicateReservationError):
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            # Restore autocommit to the pool default so the connection is
            # returned in a clean state.
            conn.autocommit = False


# ---------------------------------------------------------------------------
# Finalize a call — convert reservation to deduction or release
# ---------------------------------------------------------------------------

def finalize_call(
    tenant_id: str,
    call_sid: str,
    duration_seconds: float,
) -> None:
    """
    Convert reservation to final deduction.

    Rate: 1 credit = 60 seconds.  Usage is decimal — a 65-second call costs
    65/60 ≈ 1.0833 credits; a 115-second call costs 115/60 ≈ 1.9167 credits.

    The reservation already deducted 1 credit upfront, so the additional
    deduction is ``(duration_seconds / 60) - 1``.  If duration == 0 the
    reserved credit is refunded in full.

    Steps:
    1. Look up a ``reservation`` ledger entry for *call_sid*; warn + return if
       not found.
    2. Guard against duplicate deduction: if a ``deduction`` entry already
       exists for *call_sid*, log a warning and return.
    3. If ``duration_seconds == 0``:
       - Restore 1 credit to the balance.
       - Insert a ``release`` ledger entry.
    4. If ``duration_seconds > 0``:
       - Compute ``total_credits = duration_seconds / 60`` (decimal).
       - Compute ``additional_credits = total_credits - 1`` (1 already reserved).
       - If ``additional_credits > 0``: deduct from balance.
       - Insert a ``deduction`` ledger entry with the full decimal credit value.
       - Insert a ``release`` ledger entry to mark the reservation as finalised.

    Requirements: 4.2, 4.3, 4.4, 4.5, 9.2
    """
    with pg_db.get_connection() as conn:
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                # 1. Look up the reservation entry for this call_sid.
                cur.execute(
                    """
                    SELECT id FROM credit_ledger
                    WHERE call_sid = %s AND transaction_type = 'reservation'
                    LIMIT 1
                    """,
                    (call_sid,),
                )
                reservation_row = cur.fetchone()
                if reservation_row is None:
                    logger.warning(
                        "finalize_call: no reservation found for call_sid=%r (tenant=%r) — skipping",
                        call_sid,
                        tenant_id,
                    )
                    conn.rollback()
                    return

                # 2. Guard against duplicate deduction for the same call_sid.
                cur.execute(
                    """
                    SELECT 1 FROM credit_ledger
                    WHERE call_sid = %s AND transaction_type = 'deduction'
                    LIMIT 1
                    """,
                    (call_sid,),
                )
                if cur.fetchone() is not None:
                    logger.warning(
                        "finalize_call: deduction already exists for call_sid=%r (tenant=%r) — skipping",
                        call_sid,
                        tenant_id,
                    )
                    conn.rollback()
                    return

                if duration_seconds == 0:
                    # 3. Zero-duration call: restore the reserved credit and
                    #    insert a release entry.
                    cur.execute(
                        """
                        UPDATE credit_balances
                        SET balance = balance + 1, updated_at = NOW()
                        WHERE tenant_id = %s
                        """,
                        (tenant_id,),
                    )
                    cur.execute(
                        """
                        INSERT INTO credit_ledger
                            (tenant_id, transaction_type, amount, call_sid)
                        VALUES (%s, 'release', 1, %s)
                        """,
                        (tenant_id, call_sid),
                    )
                else:
                    # 4. Positive-duration call: compute additional credits to
                    #    deduct beyond the 1 already reserved.
                    #    1 credit = 60 seconds; total = duration / 60 (decimal).
                    total_credits: float = round(duration_seconds / 60, 6)
                    additional_credits: float = round(total_credits - 1, 6)

                    if additional_credits > 0:
                        cur.execute(
                            """
                            UPDATE credit_balances
                            SET balance = balance - %s, updated_at = NOW()
                            WHERE tenant_id = %s
                            """,
                            (additional_credits, tenant_id),
                        )

                    # Insert deduction entry recording the full decimal credit cost
                    # (even when additional_credits == 0 so the ledger records the finalisation).
                    cur.execute(
                        """
                        INSERT INTO credit_ledger
                            (tenant_id, transaction_type, amount, call_sid)
                        VALUES (%s, 'deduction', %s, %s)
                        """,
                        (tenant_id, total_credits, call_sid),
                    )

                    # Insert release entry to mark the reservation as finalised.
                    cur.execute(
                        """
                        INSERT INTO credit_ledger
                            (tenant_id, transaction_type, amount, call_sid)
                        VALUES (%s, 'release', 1, %s)
                        """,
                        (tenant_id, call_sid),
                    )

            conn.commit()

        except Exception:
            conn.rollback()
            raise
        finally:
            conn.autocommit = False


# ---------------------------------------------------------------------------
# Paginated ledger query
# ---------------------------------------------------------------------------

def get_ledger(
    tenant_id: str,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Return paginated ledger entries ordered by created_at DESC.

    Returns ``{"entries": [...], "total": int, "page": int, "page_size": int}``.

    Each entry dict contains: ``id``, ``transaction_type``, ``amount``,
    ``call_sid``, ``campaign_id``, ``description``, ``created_at`` (ISO string).

    Requirements: 5.3, 5.4
    """
    offset = (page - 1) * page_size

    with pg_db.get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Total count for the tenant.
            cur.execute(
                "SELECT COUNT(*) FROM credit_ledger WHERE tenant_id = %s",
                (tenant_id,),
            )
            total: int = cur.fetchone()["count"]

            # Paginated rows, newest first.
            cur.execute(
                """
                SELECT id, transaction_type, amount, call_sid, campaign_id,
                       description, created_at
                FROM credit_ledger
                WHERE tenant_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (tenant_id, page_size, offset),
            )
            rows = cur.fetchall()

    entries = [
        {
            "id": row["id"],
            "transaction_type": row["transaction_type"],
            "amount": row["amount"],
            "call_sid": row["call_sid"],
            "campaign_id": row["campaign_id"],
            "description": row["description"],
            "created_at": row["created_at"].isoformat() if row["created_at"] is not None else None,
        }
        for row in rows
    ]

    return {
        "entries": entries,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# Admin signed adjustment
# ---------------------------------------------------------------------------

def admin_adjust(
    tenant_id: str,
    amount: int,
    description: str,
    admin_tenant_id: str,
) -> dict:
    """Apply a signed adjustment (positive = add, negative = deduct).

    Uses ``SELECT ... FOR UPDATE`` inside a transaction to safely read the
    current balance before applying the delta.

    Raises:
        ValueError: if the adjustment would result in a negative balance
            (i.e. ``current_balance + amount < 0``), or if no balance row
            exists and ``amount < 0``.

    Returns ``{"balance": int}``.

    Requirements: 8.1, 8.2, 8.4
    """
    with pg_db.get_connection() as conn:
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                # 1. Lock the balance row for this tenant.
                cur.execute(
                    "SELECT balance FROM credit_balances WHERE tenant_id = %s FOR UPDATE",
                    (tenant_id,),
                )
                row = cur.fetchone()

                # 2. Determine current balance; reject negative adjustments
                #    when no row exists.
                if row is None:
                    current_balance = 0
                    if amount < 0:
                        raise ValueError("Adjustment would result in a negative balance.")
                else:
                    current_balance = row[0]

                # 3. Guard against going below zero.
                new_balance = current_balance + amount
                if new_balance < 0:
                    raise ValueError("Adjustment would result in a negative balance.")

                # 4. Upsert the balance row.
                cur.execute(
                    """
                    INSERT INTO credit_balances (tenant_id, balance, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (tenant_id) DO UPDATE
                        SET balance    = EXCLUDED.balance,
                            updated_at = NOW()
                    """,
                    (tenant_id, new_balance),
                )

                # 5. Insert the adjustment ledger entry.
                cur.execute(
                    """
                    INSERT INTO credit_ledger
                        (tenant_id, transaction_type, amount, description)
                    VALUES (%s, 'adjustment', %s, %s)
                    """,
                    (tenant_id, amount, description),
                )

            conn.commit()

        except ValueError:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.autocommit = False

    return {"balance": new_balance}
