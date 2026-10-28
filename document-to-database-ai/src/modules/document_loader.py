"""
modules/document_loader.py
───────────────────────────
Responsible for reading raw files and returning a clean plain-text string.

Supported formats (easily extensible via the registry pattern):
  - PDF  (.pdf)   — via pypdf
  - Word (.docx)  — via python-docx
  - Text (.txt)   — built-in

Design principle: this module knows NOTHING about extraction or databases.
It only converts bytes → str.
"""

from __future__ import annotations

import abc
import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Abstract base — all loaders implement this interface
# ─────────────────────────────────────────────────────────────────────────────
class BaseDocumentLoader(abc.ABC):
    @abc.abstractmethod
    def load(self, file_path: Path) -> str:
        """Read *file_path* and return its full text content."""


# ─────────────────────────────────────────────────────────────────────────────
# Concrete loaders
# ─────────────────────────────────────────────────────────────────────────────
class PDFLoader(BaseDocumentLoader):
    """Extract text from all pages of a PDF using pypdf."""

    def load(self, file_path: Path) -> str:
        from pypdf import PdfReader  # lazy import — not all deployments need PDF

        reader = PdfReader(str(file_path))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages).strip()
        logger.debug("PDFLoader: extracted %d chars from %s", len(text), file_path.name)
        return text


class DocxLoader(BaseDocumentLoader):
    """Extract text from a .docx file preserving paragraph order."""

    def load(self, file_path: Path) -> str:
        from docx import Document  # lazy import

        doc = Document(str(file_path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n".join(paragraphs).strip()
        logger.debug("DocxLoader: extracted %d chars from %s", len(text), file_path.name)
        return text


class PlainTextLoader(BaseDocumentLoader):
    """Read a plain-text file with UTF-8 encoding (fallback: latin-1)."""

    def load(self, file_path: Path) -> str:
        try:
            text = file_path.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError:
            text = file_path.read_text(encoding="latin-1").strip()
        logger.debug("PlainTextLoader: extracted %d chars from %s", len(text), file_path.name)
        return text


# ─────────────────────────────────────────────────────────────────────────────
# Registry — maps file extensions to loader classes
# To support a new format, just add one entry here.
# ─────────────────────────────────────────────────────────────────────────────
_LOADER_REGISTRY: dict[str, type[BaseDocumentLoader]] = {
    ".pdf":  PDFLoader,
    ".docx": DocxLoader,
    ".txt":  PlainTextLoader,
    ".text": PlainTextLoader,
}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def load_document(file_path: str | Path) -> str:
    """
    Load a document from *file_path* and return its plain-text content.

    Raises:
        FileNotFoundError  — if the file does not exist
        ValueError         — if the file extension is unsupported
        RuntimeError       — if the loader fails to extract any text
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")

    suffix = path.suffix.lower()
    loader_class = _LOADER_REGISTRY.get(suffix)

    if loader_class is None:
        supported = ", ".join(_LOADER_REGISTRY.keys())
        raise ValueError(
            f"Unsupported file type '{suffix}'. Supported: {supported}"
        )

    loader = loader_class()
    text = loader.load(path)

    if not text:
        raise RuntimeError(f"Loader returned empty text for {path.name}")

    return text
