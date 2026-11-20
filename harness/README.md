# IELTS Data Harness V0.1 & V0.2-B — Technical Reference & Environment Guide

This directory contains the IELTS Data Harness engine for ingestion, classification, raw structured extraction (V0.1), and normalization into canonical, validated learning entities (V0.2-B).

---

## 1. Python Environment Policy

Per repository instructions in [AGENTS.md](file:///home/khanh/projects/just_ielts/AGENTS.md), this project relies on a repository-local Python virtual environment at `.venv/`.

- Never install packages into the global system Python.
- Always execute commands explicitly using `./.venv/bin/python`.
- Verify the environment health before running batch operations.

---

## 2. Environment Setup

### 2.1 Virtual Environment Creation
If `.venv/` does not exist:
```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
```

### 2.2 Python Dependencies Installation
Install direct dependencies from [requirements-harness.txt](file:///home/khanh/projects/just_ielts/requirements-harness.txt):
```bash
./.venv/bin/pip install -r requirements-harness.txt
```

### 2.3 System Prerequisites (Ubuntu / Debian / WSL2)
The harness utilizes standard Linux system utilities for media inspection and OCR:

```bash
sudo apt-get update && sudo apt-get install -y \
  file \
  poppler-utils \
  tesseract-ocr \
  tesseract-ocr-eng \
  tesseract-ocr-vie
```

| Utility | System Package | Used By |
|---|---|---|
| `file` | `file` | `AudioMetaExtractor` (detects codecs, bitrates, container formats) |
| `pdftoppm` | `poppler-utils` | `PdfOcrExtractor` (renders PDF pages to ephemeral PNGs at 200 DPI) |
| `tesseract` | `tesseract-ocr` | `PdfOcrExtractor` (OCR text extraction in `eng` and `vie`) |

---

## 3. Environment Diagnostics

Verify that all Python and system dependencies are properly installed:
```bash
./.venv/bin/python -m harness.cli check-env
```

Expected output when healthy:
```
>>> Diagnosing Python Environment: /path/to/.venv/bin/python

[Python Packages]
  [OK     ] pikepdf      (pip: pikepdf       ) — PDF parsing and inspection
  [OK     ] pdfminer     (pip: pdfminer.six  ) — PDF text stream extraction
  [OK     ] lxml         (pip: lxml          ) — OpenXML DOCX and XLSX processing
  [OK     ] pydantic     (pip: pydantic      ) — Schema validation
  [OK     ] yaml         (pip: PyYAML        ) — YAML configuration parsing
  [OK     ] pytest       (pip: pytest        ) — Automated test suite

[System Commands]
  [OK     ] file         — /usr/bin/file
  [OK     ] pdftoppm     — /usr/bin/pdftoppm
  [OK     ] tesseract    — /usr/bin/tesseract

All required Python and system dependencies are satisfied.
```

---

## 4. CLI Usage Reference

All commands run through `./.venv/bin/python -m harness.cli`:

### 4.1 Phase V0.1 — Ingestion & Raw Extraction Commands
```bash
# Display CLI help
./.venv/bin/python -m harness.cli --help

# 1. Scan private/raw/ and synchronize metadata to SQLite sources table
./.venv/bin/python -m harness.cli inventory

# 2. Inspect document types and recommended extractor adapters
./.venv/bin/python -m harness.cli classify --pilot
./.venv/bin/python -m harness.cli classify --source-id SRC-011

# 3. Execute raw extraction
./.venv/bin/python -m harness.cli extract --pilot                 # Extract all 7 pilot files
./.venv/bin/python -m harness.cli extract --source-id SRC-004      # Extract specific source
./.venv/bin/python -m harness.cli extract --source-id SRC-004 --unit page_0001 # Extract single page
./.venv/bin/python -m harness.cli extract --pilot --force          # Ignore checkpoints

# 4. Resume incomplete or interrupted extraction tasks
./.venv/bin/python -m harness.cli resume

# 5. Display processing status and checkpoint metrics
./.venv/bin/python -m harness.cli status

# 6. Validate integrity and checksums of staged JSON artifacts
./.venv/bin/python -m harness.cli validate
./.venv/bin/python -m harness.cli validate --source-id SRC-011
```

### 4.2 Phase V0.2-B — Normalization & Quality Verification Commands
```bash
# 1. Run Reading Pilot normalization (SRC-138 + SRC-137)
./.venv/bin/python -m harness.cli normalize --pilot

# Dry-run normalization without writing files to disk
./.venv/bin/python -m harness.cli normalize --pilot --dry-run

# Force re-normalization, bypassing existing normalization checkpoints
./.venv/bin/python -m harness.cli normalize --pilot --force

# Normalize a specific source and test
./.venv/bin/python -m harness.cli normalize --source-id SRC-138 --test-number 5 --passage-number 1

# 2. Run Quality Gates G1-G7 verification and output JSON quality report
./.venv/bin/python -m harness.cli verify --test-id TEST-IELTS-VOL06-05-ACAD --report

# 3. Check normalization status and lifecycle breakdown
./.venv/bin/python -m harness.cli normalization-status
```

---

## 5. Architectural Principles

1. **Lazy Loading & Fault Tolerance:**
   Top-level imports are restricted to standard library modules. Heavy modules (`pikepdf`, `pdfminer`, `lxml`) are imported only on demand. CLI help remains functional regardless of environment state.

2. **Deterministic Content Hashing & Storage:**
   All canonical normalized entities have execution timestamps (`normalized_at`) excluded from their `canonical_content_sha256` digest. Output files are serialized with 2-space indentation, sorted keys, and written atomically.

3. **Multi-Tier Quality Lifecycle:**
   Entities progress through strict lifecycle states: `extracted` $\to$ `review_required` / `reviewed` $\to$ `verified` / `rejected`. No machine-generated or automated script can promote records directly to `verified`; human tutor review is required.

4. **Zero Guessing Policy:**
   Missing answer keys, missing evidence quotes, and OCR ambiguities are recorded as `null` with explicit diagnostic flags (e.g. `MISSING_SOURCE_ANSWER_KEY`, `OCR_TYPO_CORRECTED`). Content is never hallucinated or invented.

5. **Copyright & Privacy Isolation:**
   Authentic examination papers, passages, question prompts, and answer booklets reside strictly under gitignored `private/` directories (`private/raw/`, `private/staging/raw_extracted/`, `private/staging/normalized/`). Zero proprietary content is committed to Git. Public test fixtures and examples are strictly synthetic.

---

## 6. Running Automated Tests

Run the complete test suite:
```bash
./.venv/bin/python -m pytest -v tests/
```
