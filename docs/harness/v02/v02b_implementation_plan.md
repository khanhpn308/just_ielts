# IELTS Data Harness V0.2 — Phase V0.2-B Implementation Plan
**Phase V0.2-A: Schema Design & Normalization Contract**  
**Status:** Actionable Engineering Roadmap  
**Author:** IELTS Learning Systems Engineer & Data Architecture Team  
**Date:** 2026-11-19  

---

## 1. Roadmap Overview & Execution Boundaries

Phase V0.2-B represents the implementation phase that translates the specifications, schemas, and contracts established in Phase V0.2-A into executable Python modules within the repository's local environment (`.venv/`).

### Execution Constraints & Boundaries
- **Strict Stop Condition:** This document outlines the roadmap only. Execution of Phase V0.2-B is strictly deferred until Phase V0.2-A design review is approved by the user.
- **Environment Integrity:** All code runs via `./.venv/bin/python`. Zero new packages will be added without explicit approval; standard library and existing V0.1 dependencies (`pydantic`, `lxml`, `pytest`) are prioritized.
- **Immutability of V0.1:** Existing V0.1 extractors, inventory tables, and checkpoint states will remain untouched. V0.2 normalizers consume staged outputs as read-only inputs.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    PHASE V0.2-B SPRINT EXECUTION ROADMAP                        │
├──────────┬─────────────────────────────────────────────────┬────────────────────┤
│ Sprint 1 │ Pydantic Data Models & Base Normalizer Engine   │ Core abstractions  │
│ Sprint 2 │ Question Paper & Passage Parsers (DOCX & PDF)   │ Item segmentation  │
│ Sprint 3 │ Answer Key Reconciler & Normalizer              │ Ground truth bank  │
│ Sprint 4 │ Evidence Span Resolver & Quoted Proof Matcher   │ Grounding engine   │
│ Sprint 5 │ CLI Commands, Validation Gates & Checkpointing  │ Orchestration      │
│ Sprint 6 │ Pilot End-to-End Pipeline & Golden Benchmark    │ Acceptance test    │
└──────────┴─────────────────────────────────────────────────┴────────────────────┘
```

---

## 2. Sprint Breakdown & Technical Deliverables

### Sprint 1: Pydantic Data Models & Base Normalizer Engine
- **Goal:** Implement type-safe Python data structures implementing the V0.2-A JSON schemas.
- **Key Modules to Create:**
  - `harness/normalizers/base.py`: Abstract `BaseNormalizer` with atomic output writing and provenance tracking.
  - `harness/models/provenance.py`: `ProvenanceEnvelope` model.
  - `harness/models/question_bank.py`: `Test`, `PassageOrSection`, `QuestionGroup`, `Question`, `Answer`, `Evidence`, `Explanation` models.
  - `harness/models/quality.py`: `QualityProfile` model and state machine validator.
- **Automated Tests:** `tests/test_v02_models.py` (Validates Pydantic serialization, enum enforcement, and boundary validation).

---

### Sprint 2: Question Paper & Passage Parsers (DOCX & PDF)
- **Goal:** Transform raw paragraph arrays from `DocxExtractor` and raw OCR pages from `PdfOcrExtractor` into structured passages and questions.
- **Key Modules to Create:**
  - `harness/normalizers/reading_docx.py`: Parser for `SRC-138` (VOL 6) and other digital Word documents.
    - Implements numbered sentence recovery for concatenated runs (e.g. paragraph 309).
    - Detects passage headings, subtitles, and paragraph letter tags (`A`–`H`).
  - `harness/normalizers/reading_pdf.py`: Structural parser for scanned PDF tests (`SRC-011`).
- **Automated Tests:** `tests/test_v02_reading_parser.py` (Tests segmentation on raw paragraph runs and passage boundaries).

---

### Sprint 3: Answer Key Reconciler & Normalizer
- **Goal:** Parse heterogeneous answer key formats into canonical `Answer` entities.
- **Key Modules to Create:**
  - `harness/normalizers/answer_reconciler.py`:
    - Tabular XLSX parser: Ingests `SRC-077` sheet grids, maps coordinate cells to question numbers 1–40.
    - Scanned PDF Key parser: Ingests `SRC-011` p. 23 and `SRC-137` answer lines.
    - Enum canonicalizer: Converts `"T"`, `"True"`, `"TRUE"` $\to$ `"TRUE"`, `"NGV"` $\to$ `"NOT GIVEN"`.
    - OCR typo remediation: Replaces `"Fraudulant"` with `"fraudulent"`.
- **Automated Tests:** `tests/test_v02_answer_reconciler.py` (Tests multi-format answer extraction and normalization).

---

### Sprint 4: Evidence Span Resolver & Quoted Proof Matcher
- **Goal:** Ground answers against passage text by finding exact or high-confidence character offsets.
- **Key Modules to Create:**
  - `harness/normalizers/evidence_resolver.py`:
    - Verbatim substring finder (`char_start`, `char_end`).
    - Fuzzy fallback for OCR variations using standard library `difflib.SequenceMatcher`.
    - Automated detection of paragraph letter location (`Paragraph C`).
- **Automated Tests:** `tests/test_v02_evidence_resolver.py` (Validates span calculation and exact match verification).

---

### Sprint 5: CLI Commands, Validation Gates & Checkpointing
- **Goal:** Integrate normalization into `./.venv/bin/python -m harness.cli` with granular SQLite checkpointing.
- **Key Modules to Create / Extend:**
  - `harness/db.py`: Add `normalization_checkpoints` table with unique constraint on `(entity_id, normalizer_version, raw_sha256)`.
  - `harness/cli.py`:
    - Add `normalize --source-id SRC-XXX` command.
    - Add `verify --test-id TEST-XXX` quality gate runner.
    - Add `export-knowledge` to build derived SQLite views.
- **Automated Tests:** `tests/test_v02_cli.py` (Tests command-line flags, idempotency, and status reporting).

---

### Sprint 6: Pilot End-to-End Pipeline & Golden Benchmark
- **Goal:** Execute full normalization on the approved Reading pilot (PILOT-05 and PILOT-02) and build the golden benchmark dataset.
- **Tasks:**
  1. Run normalizer on `SRC-138` (Test 5 Passage 1).
  2. Run reconciler on `SRC-137` (Test 5 Explanations & Keys).
  3. Emit normalized entities into `private/staging/normalized/`.
  4. Run validation gates; generate audit report verifying that Questions 2–6 achieve `reviewed` status and Questions 1, 11–13 are correctly flagged `review_required`.
  5. Commit synthetic validation fixtures into `tests/fixtures/v02/`.

---

## 3. Sprint Acceptance Criteria Matrix

| Sprint | Deliverable Files | Success Criteria |
|---|---|---|
| **Sprint 1** | `harness/models/*.py`, `harness/normalizers/base.py` | 100% schema compliance, zero external dependencies beyond `pydantic`. |
| **Sprint 2** | `harness/normalizers/reading_docx.py` | Perfectly separates concatenated Q1–6 in paragraph 309 of `SRC-138`. |
| **Sprint 3** | `harness/normalizers/answer_reconciler.py` | Successfully extracts 360 answers from `SRC-077` and 9 answers from `SRC-137`. |
| **Sprint 4** | `harness/normalizers/evidence_resolver.py` | Correctly resolves exact character offsets for Q3, Q4, Q5, Q6 in `SRC-138`. |
| **Sprint 5** | `harness/cli.py` extensions, SQLite tables | `harness.cli normalize` runs idempotently with O(1) checkpoint skipping. |
| **Sprint 6** | End-to-end pilot output & audit log | Produces zero unhandled exceptions; correctly flags missing inputs; outputs 100% verifiable learning records. |
