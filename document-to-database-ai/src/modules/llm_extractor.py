"""
modules/llm_extractor.py
─────────────────────────
Calls the LLM using the layered prompt template and parses the JSON response
into a validated Pydantic model.

Key responsibilities:
  - Build the prompt with all four layers filled in
  - Invoke the LLM with retry / timeout
  - Parse the raw string response into InvoiceData
  - Trigger the correction prompt if parsing fails (one retry)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from src.config import settings
from src.models.invoice import InvoiceData, get_invoice_json_schema
from src.prompts.templates import EXTRACTION_PROMPT, CORRECTION_PROMPT

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Field definitions injected into the CONTEXT_LAYER of the prompt
# ─────────────────────────────────────────────────────────────────────────────
_INVOICE_FIELD_DEFINITIONS = """
MANDATORY fields (must be non-null in every valid invoice):
- invoice_number   : Unique invoice identifier — look for labels like "No. Faktur",
                     "Invoice No.", "Nomor Invoice", "INV-XXXX" (string)
- invoice_date     : Document issue date — label: "Tanggal", "Date", "Tgl. Faktur"
                     → normalise to YYYY-MM-DD (date string)
- vendor_name      : Full legal name of the seller/supplier — label: "Dari", "From",
                     "Nama Penjual", company header at the top of the document (string)
- buyer_name       : Full legal name of the buyer — label: "Kepada", "Bill To",
                     "Nama Pembeli", "Customer" (string)
- subtotal         : Sum of all line items BEFORE tax, AFTER any line discounts —
                     label: "Subtotal", "DPP", "Jumlah Sebelum Pajak"
                     → strip Rp/IDR symbols and thousand-separators → float
- total_amount     : Grand total payable including all taxes and discounts —
                     label: "Total", "Grand Total", "Jumlah yang Harus Dibayar"
                     → strip Rp/IDR symbols and thousand-separators → float

OPTIONAL fields (set to null if not present — do NOT fabricate):
- po_number        : Purchase order reference — label: "No. PO", "PO Number" (string | null)
- reference_number : Any other document reference number (string | null)
- due_date         : Payment due date — label: "Jatuh Tempo", "Due Date"
                     → normalise to YYYY-MM-DD (date string | null)
- vendor_tax_id    : Seller NPWP/tax ID — label: "NPWP Penjual" (string | null)
- vendor_address   : Seller postal address (string | null)
- buyer_tax_id     : Buyer NPWP/tax ID — label: "NPWP Pembeli" (string | null)
- buyer_address    : Buyer postal address (string | null)
- currency         : ISO-4217 currency code — default "IDR" if not stated (string)
- discount_amount  : Invoice-level discount in currency units → float | null
- tax_rate_pct     : VAT/PPN rate as a percentage — e.g. 11 for 11% (float | null)
- tax_amount       : Tax amount in currency units → strip symbols → float | null
- payment_terms    : e.g. "Net 30", "COD", "Tunai" (string | null)
- notes            : Any additional remarks, bank details, or free-text notes (string | null)

LINE ITEMS array (extract every row in the item table):
Each line item object must contain:
- description    : Product/service name — trim OCR artifacts (string)
- quantity       : Number of units → float (e.g. "5" → 5.0)
- unit           : Unit of measure — e.g. "Lic", "Hr", "Pkt", "pcs" (string | null)
- unit_price     : Price per unit → strip symbols → float
- discount_pct   : Line-level discount as a percentage (float | null)
- subtotal       : Line total → strip symbols → float
"""

_INVOICE_SCHEMA_DESCRIPTION = "Invoice (Faktur) extraction schema — financial document"


def _build_llm() -> ChatOpenAI:
    """Instantiate a ChatOpenAI client from centralised settings."""
    return ChatOpenAI(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        temperature=settings.openai_temperature,
        timeout=settings.extraction_timeout,
        max_retries=0,  # tenacity handles retries at the call level
    )


def _parse_json_from_response(raw: str) -> dict[str, Any]:
    """
    Robustly extract a JSON object from an LLM response string.

    Handles common LLM output artefacts:
      - Markdown code fences (```json ... ``` or ``` ... ```)
      - Leading prose before the first '{' (e.g. "Here is the JSON: {...")
      - Trailing commentary after the closing '}'
    """
    cleaned = raw.strip()

    # ── Strip markdown fences ─────────────────────────────────────────────────
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Drop the opening fence line (```json or ```) and the closing ``` if present
        inner_lines = lines[1:]
        if inner_lines and inner_lines[-1].strip() == "```":
            inner_lines = inner_lines[:-1]
        cleaned = "\n".join(inner_lines).strip()

    # ── Isolate the JSON object — find the outermost { ... } block ───────────
    brace_start = cleaned.find("{")
    brace_end   = cleaned.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        cleaned = cleaned[brace_start : brace_end + 1]

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM response is not valid JSON after cleanup. "
            f"Parser error: {exc}. "
            f"Raw response (first 500 chars): {raw[:500]!r}"
        ) from exc


class LLMExtractor:
    """
    Orchestrates a single document → InvoiceData extraction pass.

    Usage:
        extractor = LLMExtractor()
        invoice = extractor.extract(document_text, source_filename="inv_001.pdf")
    """

    def __init__(self) -> None:
        self._llm = _build_llm()
        self._json_schema = get_invoice_json_schema()

    # ── Public method ─────────────────────────────────────────────────────────
    def extract(self, document_text: str, source_filename: str = "unknown") -> InvoiceData:
        """
        Extract structured invoice data from raw document text.

        Returns a validated InvoiceData instance.
        Raises RuntimeError if extraction or validation cannot be recovered.
        """
        logger.info("Starting extraction for: %s", source_filename)

        raw_response = self._invoke_extraction(document_text, source_filename)

        try:
            data_dict = _parse_json_from_response(raw_response)
            invoice = InvoiceData.model_validate(data_dict)
            logger.info("Extraction successful for: %s", source_filename)
            return invoice

        except (ValueError, ValidationError) as exc:
            # ── Correction pass — one automatic retry ─────────────────────────
            logger.warning(
                "Initial extraction failed for %s: %s — attempting correction",
                source_filename, exc,
            )
            corrected_response = self._invoke_correction(
                previous_output=raw_response,
                validation_errors=str(exc),
            )
            try:
                data_dict = _parse_json_from_response(corrected_response)
                invoice = InvoiceData.model_validate(data_dict)
                logger.info("Correction pass succeeded for: %s", source_filename)
                return invoice
            except (ValueError, ValidationError) as final_exc:
                raise RuntimeError(
                    f"Extraction failed after correction for '{source_filename}': {final_exc}"
                ) from final_exc

    # ── Private helpers ───────────────────────────────────────────────────────
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _invoke_extraction(self, document_text: str, source_filename: str) -> str:
        """Call the LLM with the full four-layer extraction prompt."""
        chain = EXTRACTION_PROMPT | self._llm
        response = chain.invoke({
            "document_type": "Invoice / Faktur",
            "source_filename": source_filename,
            "target_schema_description": _INVOICE_SCHEMA_DESCRIPTION,
            "field_definitions": _INVOICE_FIELD_DEFINITIONS,
            "json_schema": json.dumps(self._json_schema, indent=2),
            "document_text": document_text,
        })
        return response.content

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _invoke_correction(self, previous_output: str, validation_errors: str) -> str:
        """Call the LLM correction prompt to fix a malformed extraction."""
        chain = CORRECTION_PROMPT | self._llm
        response = chain.invoke({
            "previous_output": previous_output,
            "validation_errors": validation_errors,
            "json_schema": json.dumps(self._json_schema, indent=2),
        })
        return response.content
