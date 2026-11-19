# IELTS Data Harness V0.1 — Technical Reference & Environment Guide

This directory contains the IELTS Data Harness V0.1 engine for ingestion, classification, and raw structured extraction of learning materials.

---

## 1. Python Environment Policy

Per repository instructions in [AGENTS.md](file:///home/khanh/projects/just_ielts/AGENTS.md), this project relies on a repository-local Python virtual environment at `.venv/`.

- Never install packages into the global system Python.
- Always execute commands explicitly using `./.venv/bin/python`.
- Verify the environment health before running batch extractions.

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

A complete reproducible lockfile is archived under `private/requirements-harness.lock`.

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

```bash
# Display CLI help (works with zero third-party packages installed via lazy imports)
./.venv/bin/python -m harness.cli --help

# 1. Scan private/raw/ and synchronize metadata to SQLite sources table
./.venv/bin/python -m harness.cli inventory

# 2. Inspect document types and recommended extractor adapters
./.venv/bin/python -m harness.cli classify --pilot
./.venv/bin/python -m harness.cli classify --source-id SRC-011

# 3. Execute extraction
./.venv/bin/python -m harness.cli extract --pilot                 # Extract all 7 pilot files
./.venv/bin/python -m harness.cli extract --source-id SRC-004      # Extract specific source
./.venv/bin/python -m harness.cli extract --source-id SRC-004 --unit page_0001 # Extract single page
./.venv/bin/python -m harness.cli extract --pilot --force          # Ignore checkpoints

# 4. Resume incomplete or interrupted tasks
./.venv/bin/python -m harness.cli resume

# 5. Display processing status and checkpoint metrics
./.venv/bin/python -m harness.cli status

# 6. Validate integrity and checksums of staged JSON artifacts
./.venv/bin/python -m harness.cli validate
./.venv/bin/python -m harness.cli validate --source-id SRC-011
```

---

## 5. Architectural Principles

1. **Lazy Loading & Fault Tolerance:**
   Top-level imports are restricted to standard library modules. Extraction adapters and classifiers import external packages (`pikepdf`, `pdfminer`, `lxml`) only when executing tasks for that specific format. If an optional dependency is missing, CLI `--help` and unrelated extractors remain fully functional.

2. **Actionable Diagnostics:**
   When an adapter encounters a missing Python package or system binary, it raises `MissingPythonDependencyError` or `MissingSystemDependencyError` with the exact pip or apt command to install it.

3. **Per-Page Checkpoints & Idempotency:**
   Each PDF page, DOCX document, XLSX sheet, or audio metadata block is checkpointed individually in SQLite (`harness/state/harness.db`). Already completed units are skipped in O(1) time.

4. **Source & Repository Protection:**
   - Raw files under `private/raw/` are opened exclusively in read-only mode (`rb`).
   - Staged outputs reside in `private/staging/raw_extracted/` (gitignored).
   - Checkpoint state resides in `harness/state/` (gitignored).
   - Zero private data is tracked or committed to Git.

---

## 6. Running Automated Tests

Run the complete test suite:
```bash
./.venv/bin/python -m pytest -v tests/
```
