"""
modules/schema_mapper.py
─────────────────────────
Maps validated Pydantic models → SQLAlchemy ORM instances.

This is the translation boundary between the extraction world (Pydantic)
and the persistence world (SQLAlchemy). Keeping it isolated means neither
side leaks into the other.
"""

from __future__ import annotations

import logging

from src.models.invoice import InvoiceData, LineItem
from src.models.db_schema import Invoice as InvoiceORM, InvoiceLineItem as LineItemORM

logger = logging.getLogger(__name__)


def map_invoice_to_orm(invoice: InvoiceData, source_filename: str = "") -> InvoiceORM:
    """
    Convert a validated InvoiceData Pydantic instance into a SQLAlchemy
    InvoiceORM row (with nested InvoiceLineItem children).

    The returned ORM object is detached (not yet added to any session).
    """
    # Map header fields
    orm_invoice = InvoiceORM(
        invoice_number   = invoice.invoice_number,
        po_number        = invoice.po_number,
        reference_number = invoice.reference_number,
        invoice_date     = invoice.invoice_date,
        due_date         = invoice.due_date,
        vendor_name      = invoice.vendor_name,
        vendor_tax_id    = invoice.vendor_tax_id,
        vendor_address   = invoice.vendor_address,
        buyer_name       = invoice.buyer_name,
        buyer_tax_id     = invoice.buyer_tax_id,
        buyer_address    = invoice.buyer_address,
        currency         = invoice.currency,
        subtotal         = invoice.subtotal,
        discount_amount  = invoice.discount_amount,
        tax_rate_pct     = invoice.tax_rate_pct,
        tax_amount       = invoice.tax_amount,
        total_amount     = invoice.total_amount,
        payment_terms    = invoice.payment_terms,
        notes            = invoice.notes,
        source_filename  = source_filename,
    )

    # Map line items — each gets the parent relationship set automatically
    orm_invoice.line_items = [
        _map_line_item(item) for item in invoice.line_items
    ]

    logger.debug(
        "Mapped invoice %s → ORM (%d line items)",
        invoice.invoice_number, len(orm_invoice.line_items),
    )
    return orm_invoice


def _map_line_item(item: LineItem) -> LineItemORM:
    """Map a single Pydantic LineItem to its ORM counterpart."""
    return LineItemORM(
        description  = item.description,
        quantity     = item.quantity,
        unit         = item.unit,
        unit_price   = item.unit_price,
        discount_pct = item.discount_pct,
        subtotal     = item.subtotal,
    )
