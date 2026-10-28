"""
models/invoice.py
──────────────────
Pydantic v2 models that define the canonical data shape for an Invoice.

These models serve THREE roles:
  1. LLM output validation  — JSON from the LLM is parsed into these models.
  2. Schema documentation   — serialised to JSON Schema and injected into prompts.
  3. ORM bridge             — converted to SQLAlchemy rows before DB insert.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class LineItem(BaseModel):
    """A single line on an invoice."""

    description: str = Field(..., max_length=512)
    quantity: float = Field(..., gt=0)
    unit: Optional[str] = Field(None, max_length=32, description="UOM e.g. pcs, kg")
    unit_price: float = Field(..., ge=0)
    discount_pct: Optional[float] = Field(None, ge=0, le=100)
    subtotal: float = Field(..., ge=0)

    @model_validator(mode="after")
    def _check_subtotal_plausible(self) -> "LineItem":
        """Soft-check: subtotal should roughly equal qty × unit_price (±1% tolerance)."""
        discount = (self.discount_pct or 0) / 100
        expected = self.quantity * self.unit_price * (1 - discount)
        if abs(self.subtotal - expected) > (expected * 0.01 + 1):
            raise ValueError(
                f"subtotal {self.subtotal} is inconsistent with "
                f"qty={self.quantity} × price={self.unit_price}"
            )
        return self


class InvoiceData(BaseModel):
    """
    Top-level invoice extraction model.

    All Optional fields may legitimately be absent in a document.
    Required fields (no Optional) must be present for DB insertion.
    """

    # ── Identifiers ───────────────────────────────────────────────────────────
    invoice_number: str = Field(..., max_length=64, description="Invoice number / no. faktur")
    po_number: Optional[str] = Field(None, max_length=64)
    reference_number: Optional[str] = Field(None, max_length=64)

    # ── Dates ─────────────────────────────────────────────────────────────────
    invoice_date: date = Field(..., description="Issue date — ISO-8601 YYYY-MM-DD")
    due_date: Optional[date] = None

    # ── Parties ───────────────────────────────────────────────────────────────
    vendor_name: str = Field(..., max_length=256)
    vendor_tax_id: Optional[str] = Field(None, max_length=32)
    vendor_address: Optional[str] = Field(None, max_length=512)
    buyer_name: str = Field(..., max_length=256)
    buyer_tax_id: Optional[str] = Field(None, max_length=32)
    buyer_address: Optional[str] = Field(None, max_length=512)

    # ── Financials ────────────────────────────────────────────────────────────
    currency: str = Field("IDR", max_length=3, description="ISO-4217 currency code")
    subtotal: float = Field(..., ge=0)
    discount_amount: Optional[float] = Field(None, ge=0)
    tax_rate_pct: Optional[float] = Field(None, ge=0, le=100)
    tax_amount: Optional[float] = Field(None, ge=0)
    total_amount: float = Field(..., ge=0)

    # ── Line items ────────────────────────────────────────────────────────────
    line_items: list[LineItem] = Field(default_factory=list)

    # ── Metadata ──────────────────────────────────────────────────────────────
    payment_terms: Optional[str] = Field(None, max_length=128)
    notes: Optional[str] = Field(None, max_length=1024)

    @field_validator("currency")
    @classmethod
    def _uppercase_currency(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _check_total_consistency(self) -> "InvoiceData":
        """Verify that subtotal + tax ≈ total (within 1% or 1 unit tolerance)."""
        tax = self.tax_amount or 0
        discount = self.discount_amount or 0
        expected = self.subtotal - discount + tax
        if abs(self.total_amount - expected) > (expected * 0.01 + 1):
            raise ValueError(
                f"total_amount {self.total_amount} does not reconcile with "
                f"subtotal={self.subtotal}, discount={discount}, tax={tax}"
            )
        return self


# ── Helper: JSON Schema for prompt injection ──────────────────────────────────
def get_invoice_json_schema() -> dict:
    """Return the JSON Schema dict for InvoiceData (used in prompt OUTPUT_CONSTRAINT)."""
    return InvoiceData.model_json_schema()
