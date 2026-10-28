# Document to Database AI

> Intelligent Document Processing (IDP) system that reads unstructured documents (PDF, DOCX, TXT), extracts structured data via LLM, validates it, and persists it to a relational database — fully automated.

---

## Architecture

```
Document File (PDF/DOCX/TXT)
        │
        ▼
┌─────────────────────┐
│   DocumentLoader    │  Converts any file format → plain text
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│    LLMExtractor     │  4-layer Prompt → GPT-4o → JSON → Pydantic model
│  (Prompt Layering)  │
│  1. System Persona  │
│  2. Context Layer   │
│  3. Task Layer      │
│  4. Output Constraint│
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  BusinessValidator  │  Domain rules (date logic, total reconciliation…)
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   SchemaMapper      │  Pydantic → SQLAlchemy ORM objects
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   DatabaseWriter    │  Async upsert to SQLite / PostgreSQL
└─────────────────────┘
```

---

## Project Structure

```
document-to-database-ai/
├── main.py                         # CLI entry point
├── requirements.txt
├── .env.example                    # Copy to .env and fill in secrets
├── sample_docs/
│   └── sample_invoice.txt
├── logs/
└── src/
    ├── config.py                   # Pydantic-settings (reads .env)
    ├── agent.py                    # DocumentToDatabaseAgent orchestrator
    ├── prompts/
    │   └── templates.py            # 4-layer prompt templates
    ├── models/
    │   ├── invoice.py              # Pydantic extraction models
    │   └── db_schema.py            # SQLAlchemy ORM tables
    ├── modules/
    │   ├── document_loader.py      # File → plain text
    │   ├── llm_extractor.py        # LLM call + JSON parsing
    │   ├── validator.py            # Business-rule validation
    │   ├── schema_mapper.py        # Pydantic → ORM mapping
    │   └── db_writer.py            # Async database persistence
    └── utils/
        └── logger.py               # Structured logging (structlog)
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and set OPENAI_API_KEY
```

### 3. Run

```bash
# Single file
python main.py sample_docs/sample_invoice.txt

# Entire folder
python main.py sample_docs/

# Multiple explicit files
python main.py inv1.pdf inv2.docx inv3.txt
```

---

## Prompt Layering Design

| Layer | Role | Location |
|---|---|---|
| **System Persona** | Defines the model's identity and absolute constraints | `SYSTEM_PERSONA` in `prompts/templates.py` |
| **Context Layer** | Injects document type, schema description, field definitions | `CONTEXT_LAYER` |
| **Task Layer** | Precise extraction instructions + document text | `TASK_LAYER` |
| **Output Constraint** | Hard JSON Schema the model must conform to | `OUTPUT_CONSTRAINT` |

A **Correction Prompt** fires automatically if the initial response fails Pydantic validation.

---

## Data Flow & Error Handling

| Stage | Error Type | Behaviour |
|---|---|---|
| Load | File not found, unsupported format | `FAILED` result returned |
| Extract | LLM timeout, invalid JSON | Retry 3× (tenacity), then correction prompt |
| Validate | Business rule violation | `FAILED` if ERROR severity, warnings logged |
| Persist | DB integrity error, duplicate | `SKIPPED` for duplicates, `FAILED` for errors |

---

## Extending the System

- **New document type** → add a loader class + one entry in `_LOADER_REGISTRY` in `document_loader.py`
- **New document schema** → duplicate `models/invoice.py`, create a new ORM table, and write a new extractor subclass
- **New business rule** → add a function to `validator.py` and append it to `_RULES`
- **Switch to PostgreSQL** → set `DATABASE_URL=postgresql+asyncpg://...` in `.env`

---

## Tech Stack

| Component | Library |
|---|---|
| LLM Framework | LangChain + langchain-openai |
| Data Validation | Pydantic v2 |
| Database ORM | SQLAlchemy 2 (async) |
| PDF Parsing | pypdf |
| Retry Logic | tenacity |
| Logging | structlog |
| CLI Output | rich |
