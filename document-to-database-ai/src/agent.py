"""
agent.py
─────────
DocumentToDatabaseAgent — the central orchestrator.

This class wires together every module in the pipeline:

  [File Path]
      │
      ▼
  DocumentLoader        → plain text
      │
      ▼
  LLMExtractor          → InvoiceData (Pydantic, validated by schema)
      │
      ▼
  BusinessValidator     → ValidationResult (domain rules)
      │
      ▼
  SchemaMapper          → InvoiceORM (SQLAlchemy)
      │
      ▼
  DatabaseWriter        → persisted row + result dict

The agent returns a structured ProcessingResult for every document,
so callers always receive a predictable interface regardless of
whether the document succeeded, was skipped, or failed.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from src.modules.document_loader import load_document
from src.modules.llm_extractor import LLMExtractor
from src.modules.validator import validate_invoice, ValidationResult
from src.modules.schema_mapper import map_invoice_to_orm
from src.modules.db_writer import DatabaseWriter
from src.models.invoice import InvoiceData
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Result model
# ─────────────────────────────────────────────────────────────────────────────
class ProcessingStatus(str, Enum):
    SUCCESS  = "success"
    SKIPPED  = "skipped"   # Document was a duplicate
    FAILED   = "failed"    # Unrecoverable error at any stage


@dataclass
class ProcessingResult:
    file_path: str
    status: ProcessingStatus
    invoice_number: Optional[str] = None
    db_id: Optional[int] = None
    validation_warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def is_success(self) -> bool:
        return self.status in (ProcessingStatus.SUCCESS, ProcessingStatus.SKIPPED)

    def summary(self) -> str:
        parts = [f"[{self.status.value.upper()}] {Path(self.file_path).name}"]
        if self.invoice_number:
            parts.append(f"invoice={self.invoice_number}")
        if self.db_id:
            parts.append(f"db_id={self.db_id}")
        if self.error:
            parts.append(f"error={self.error}")
        if self.validation_warnings:
            parts.append(f"warnings={len(self.validation_warnings)}")
        return " | ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# The Agent
# ─────────────────────────────────────────────────────────────────────────────
class DocumentToDatabaseAgent:
    """
    Processes one or more documents through the full IDP pipeline.

    Examples:
        # Single document
        agent = DocumentToDatabaseAgent()
        result = await agent.process_file("invoices/inv_001.pdf")

        # Batch processing
        results = await agent.process_batch(["inv_001.pdf", "inv_002.pdf"])
    """

    def __init__(self, database_url: str | None = None) -> None:
        # LLMExtractor is stateless after init — safe to reuse across documents
        self._extractor = LLMExtractor()
        self._database_url = database_url  # None → uses settings default

    # ── Public: single document ───────────────────────────────────────────────
    async def process_file(self, file_path: str | Path) -> ProcessingResult:
        """
        Run the complete pipeline for one document.
        Never raises — all errors are captured in ProcessingResult.
        """
        path = str(file_path)
        logger.info("Processing document: %s", path)

        # ── Stage 1: Load ─────────────────────────────────────────────────────
        try:
            document_text = load_document(path)
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            return ProcessingResult(
                file_path=path, status=ProcessingStatus.FAILED,
                error=f"[LOAD] {exc}",
            )

        # ── Stage 2: Extract ──────────────────────────────────────────────────
        try:
            invoice: InvoiceData = self._extractor.extract(
                document_text, source_filename=Path(path).name
            )
        except RuntimeError as exc:
            return ProcessingResult(
                file_path=path, status=ProcessingStatus.FAILED,
                error=f"[EXTRACT] {exc}",
            )

        # ── Stage 3: Validate business rules ──────────────────────────────────
        validation: ValidationResult = validate_invoice(invoice)
        if not validation.is_valid:
            error_msgs = "; ".join(str(e) for e in validation.errors)
            return ProcessingResult(
                file_path=path, status=ProcessingStatus.FAILED,
                invoice_number=invoice.invoice_number,
                error=f"[VALIDATE] {error_msgs}",
                validation_warnings=[str(w) for w in validation.warnings],
            )

        # ── Stage 4: Map to ORM ───────────────────────────────────────────────
        orm_invoice = map_invoice_to_orm(invoice, source_filename=Path(path).name)

        # ── Stage 5: Persist ──────────────────────────────────────────────────
        try:
            async with DatabaseWriter(self._database_url) as writer:
                db_result = await writer.save_invoice(orm_invoice)
        except RuntimeError as exc:
            return ProcessingResult(
                file_path=path, status=ProcessingStatus.FAILED,
                invoice_number=invoice.invoice_number,
                error=f"[DB] {exc}",
            )

        # ── Done ──────────────────────────────────────────────────────────────
        status = (
            ProcessingStatus.SKIPPED
            if db_result["status"] == "skipped"
            else ProcessingStatus.SUCCESS
        )
        return ProcessingResult(
            file_path=path,
            status=status,
            invoice_number=invoice.invoice_number,
            db_id=db_result["id"],
            validation_warnings=[str(w) for w in validation.warnings],
        )

    # ── Public: batch ─────────────────────────────────────────────────────────
    async def process_batch(
        self,
        file_paths: list[str | Path],
        concurrency: int = 3,
    ) -> list[ProcessingResult]:
        """
        Process multiple documents with bounded concurrency.

        Args:
            file_paths  : list of file paths to process
            concurrency : max simultaneous documents (default 3 — rate-limit friendly)
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def _guarded(path: str | Path) -> ProcessingResult:
            async with semaphore:
                return await self.process_file(path)

        results = await asyncio.gather(*(_guarded(p) for p in file_paths))

        # ── Batch summary log ─────────────────────────────────────────────────
        total   = len(results)
        success = sum(1 for r in results if r.status == ProcessingStatus.SUCCESS)
        skipped = sum(1 for r in results if r.status == ProcessingStatus.SKIPPED)
        failed  = sum(1 for r in results if r.status == ProcessingStatus.FAILED)
        logger.info(
            "Batch complete: %d total | %d success | %d skipped | %d failed",
            total, success, skipped, failed,
        )
        return list(results)
