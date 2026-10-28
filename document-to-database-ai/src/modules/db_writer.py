"""
modules/db_writer.py
─────────────────────
Handles async database operations: table creation, upsert, and retrieval.

Uses SQLAlchemy async sessions so this module is safe for use in async
web frameworks (FastAPI, etc.) without blocking the event loop.

Design:
  - DatabaseWriter is a context manager → always cleans up its engine.
  - Upsert logic: if invoice_number already exists, skip (idempotent pipeline).
  - All DB errors are caught, logged, and re-raised so the agent can react.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.config import settings
from src.models.db_schema import Base, Invoice as InvoiceORM

logger = logging.getLogger(__name__)


class DatabaseWriter:
    """
    Async database writer backed by SQLAlchemy.

    Usage (async context manager):
        async with DatabaseWriter() as writer:
            result = await writer.save_invoice(orm_invoice)
    """

    def __init__(self, database_url: str | None = None) -> None:
        url = database_url or settings.database_url
        self._engine = create_async_engine(url, echo=False, future=True)
        self._session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    # ── Context manager ───────────────────────────────────────────────────────
    async def __aenter__(self) -> "DatabaseWriter":
        await self._create_tables()
        return self

    async def __aexit__(self, *_) -> None:
        await self._engine.dispose()

    # ── Public API ────────────────────────────────────────────────────────────
    async def save_invoice(self, orm_invoice: InvoiceORM) -> dict:
        """
        Persist an InvoiceORM (with its line items) to the database.

        Behaviour:
          - If invoice_number already exists: skip and return {"status": "skipped"}.
          - On success: return {"status": "created", "id": <new_id>}.
          - On DB error: raises RuntimeError with context.
        """
        async with self._get_session() as session:
            # Idempotency check — avoid duplicate invoices
            existing = await self._find_by_invoice_number(
                session, orm_invoice.invoice_number
            )
            if existing:
                logger.info(
                    "Invoice %s already exists (id=%d) — skipping.",
                    orm_invoice.invoice_number, existing.id,
                )
                return {"status": "skipped", "id": existing.id}

            try:
                session.add(orm_invoice)
                await session.commit()
                await session.refresh(orm_invoice)
                logger.info(
                    "Invoice %s saved (id=%d, %d line items).",
                    orm_invoice.invoice_number,
                    orm_invoice.id,
                    len(orm_invoice.line_items),
                )
                return {"status": "created", "id": orm_invoice.id}

            except IntegrityError as exc:
                await session.rollback()
                raise RuntimeError(
                    f"DB integrity error for invoice {orm_invoice.invoice_number}: {exc}"
                ) from exc
            except Exception as exc:
                await session.rollback()
                raise RuntimeError(
                    f"Unexpected DB error for invoice {orm_invoice.invoice_number}: {exc}"
                ) from exc

    # ── Private helpers ───────────────────────────────────────────────────────
    async def _create_tables(self) -> None:
        """Create all tables if they do not yet exist (safe to call repeatedly)."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.debug("Database tables verified/created.")

    @asynccontextmanager
    async def _get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield a session, rolling back automatically on any exception."""
        async with self._session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    @staticmethod
    async def _find_by_invoice_number(
        session: AsyncSession, invoice_number: str
    ) -> InvoiceORM | None:
        result = await session.execute(
            select(InvoiceORM).where(InvoiceORM.invoice_number == invoice_number)
        )
        return result.scalars().first()
