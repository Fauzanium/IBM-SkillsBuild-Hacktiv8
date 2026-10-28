"""
modules/validator.py
─────────────────────
Business-rule validation layer — runs AFTER Pydantic structural validation.

Pydantic ensures type correctness.
This module enforces domain-specific business rules that are too nuanced
for schema constraints alone (e.g. date logic, cross-field constraints).

Returns a list of ValidationIssue objects so callers can decide whether
to reject or log-and-continue.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from datetime import date

from src.models.invoice import InvoiceData

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    ERROR   = "ERROR"    # Blocks DB insertion
    WARNING = "WARNING"  # Logged; insertion proceeds


@dataclass
class ValidationIssue:
    severity: Severity
    field: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.value}] {self.field}: {self.message}"


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True only if there are no ERROR-level issues."""
        return not any(i.severity == Severity.ERROR for i in self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    def add(self, severity: Severity, field_name: str, message: str) -> None:
        self.issues.append(ValidationIssue(severity, field_name, message))


# ─────────────────────────────────────────────────────────────────────────────
# Individual rule functions — each accepts InvoiceData and mutates the result
# ─────────────────────────────────────────────────────────────────────────────

def _rule_invoice_date_not_future(invoice: InvoiceData, result: ValidationResult) -> None:
    """Invoice date should not be in the future."""
    if invoice.invoice_date > date.today():
        result.add(Severity.WARNING, "invoice_date",
                   f"Invoice date {invoice.invoice_date} is in the future.")


def _rule_due_date_after_invoice_date(invoice: InvoiceData, result: ValidationResult) -> None:
    """Due date, if present, must be >= invoice date."""
    if invoice.due_date and invoice.due_date < invoice.invoice_date:
        result.add(Severity.ERROR, "due_date",
                   f"due_date {invoice.due_date} is before invoice_date {invoice.invoice_date}.")


def _rule_line_items_present(invoice: InvoiceData, result: ValidationResult) -> None:
    """An invoice with no line items is suspicious."""
    if not invoice.line_items:
        result.add(Severity.WARNING, "line_items",
                   "Invoice has no line items — extraction may have missed them.")


def _rule_line_items_sum_matches_subtotal(invoice: InvoiceData, result: ValidationResult) -> None:
    """Sum of line-item subtotals should reconcile with invoice subtotal (±2%)."""
    if not invoice.line_items:
        return
    computed = sum(item.subtotal for item in invoice.line_items)
    tolerance = max(invoice.subtotal * 0.02, 1.0)
    if abs(computed - invoice.subtotal) > tolerance:
        result.add(Severity.ERROR, "subtotal",
                   f"Line items sum ({computed:.2f}) differs from subtotal "
                   f"({invoice.subtotal:.2f}) by more than 2%.")


def _rule_currency_known(invoice: InvoiceData, result: ValidationResult) -> None:
    """Warn on uncommon currency codes that might indicate extraction errors."""
    KNOWN = {"IDR", "USD", "EUR", "SGD", "MYR", "GBP", "JPY", "CNY", "AUD"}
    if invoice.currency not in KNOWN:
        result.add(Severity.WARNING, "currency",
                   f"Currency '{invoice.currency}' is not in the known-code list.")


def _rule_total_amount_positive(invoice: InvoiceData, result: ValidationResult) -> None:
    if invoice.total_amount <= 0:
        result.add(Severity.ERROR, "total_amount",
                   "total_amount must be greater than zero.")


# ─────────────────────────────────────────────────────────────────────────────
# Rule registry — add new rules here, no other code needs changing
# ─────────────────────────────────────────────────────────────────────────────
_RULES = [
    _rule_invoice_date_not_future,
    _rule_due_date_after_invoice_date,
    _rule_line_items_present,
    _rule_line_items_sum_matches_subtotal,
    _rule_currency_known,
    _rule_total_amount_positive,
]


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def validate_invoice(invoice: InvoiceData) -> ValidationResult:
    """
    Run all registered business rules against *invoice*.

    Returns a ValidationResult with zero or more issues.
    Callers should check result.is_valid before proceeding to DB insertion.
    """
    result = ValidationResult()

    for rule in _RULES:
        try:
            rule(invoice, result)
        except Exception as exc:
            # Rule execution must never crash the pipeline
            logger.error("Validation rule %s raised unexpectedly: %s", rule.__name__, exc)
            result.add(Severity.WARNING, "validator",
                       f"Rule {rule.__name__} failed unexpectedly: {exc}")

    if result.errors:
        logger.warning("Validation FAILED for invoice %s: %d error(s)",
                       invoice.invoice_number, len(result.errors))
    else:
        logger.info("Validation passed for invoice %s (%d warning(s))",
                    invoice.invoice_number, len(result.warnings))

    return result
