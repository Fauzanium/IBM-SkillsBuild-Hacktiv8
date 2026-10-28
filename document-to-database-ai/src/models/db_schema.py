"""
models/db_schema.py
────────────────────
SQLAlchemy ORM table definitions.
Mirrors the Pydantic models but is kept separate to respect the
single-responsibility principle (validation ≠ persistence).
"""

from datetime import date, datetime
from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime,
    ForeignKey, Text, func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Invoice(Base):
    __tablename__ = "invoices"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    invoice_number  = Column(String(64), unique=True, nullable=False, index=True)
    po_number       = Column(String(64), nullable=True)
    reference_number= Column(String(64), nullable=True)
    invoice_date    = Column(Date, nullable=False)
    due_date        = Column(Date, nullable=True)

    vendor_name     = Column(String(256), nullable=False)
    vendor_tax_id   = Column(String(32),  nullable=True)
    vendor_address  = Column(Text,        nullable=True)
    buyer_name      = Column(String(256), nullable=False)
    buyer_tax_id    = Column(String(32),  nullable=True)
    buyer_address   = Column(Text,        nullable=True)

    currency        = Column(String(3),   nullable=False, default="IDR")
    subtotal        = Column(Float,       nullable=False)
    discount_amount = Column(Float,       nullable=True)
    tax_rate_pct    = Column(Float,       nullable=True)
    tax_amount      = Column(Float,       nullable=True)
    total_amount    = Column(Float,       nullable=False)

    payment_terms   = Column(String(128), nullable=True)
    notes           = Column(Text,        nullable=True)

    # Audit columns — set automatically
    source_filename = Column(String(512), nullable=True)
    created_at      = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at      = Column(DateTime, onupdate=func.now(), nullable=True)

    line_items = relationship("InvoiceLineItem", back_populates="invoice", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Invoice #{self.invoice_number} | {self.vendor_name} → {self.buyer_name}>"


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id  = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(String(512), nullable=False)
    quantity    = Column(Float,       nullable=False)
    unit        = Column(String(32),  nullable=True)
    unit_price  = Column(Float,       nullable=False)
    discount_pct= Column(Float,       nullable=True)
    subtotal    = Column(Float,       nullable=False)

    invoice = relationship("Invoice", back_populates="line_items")

    def __repr__(self) -> str:
        return f"<LineItem '{self.description[:40]}' qty={self.quantity}>"
