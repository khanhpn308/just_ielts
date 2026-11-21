# IELTS Data Harness V0.3 — Phase V0.3-D Engineering Report
**Phase:** V0.3-D Controlled Corpus Expansion & Quality Assurance  
**Role:** Senior Data Engineer, Python Engineer, and IELTS Assessment Data Quality Specialist  
**Repository:** `~/projects/just_ielts`  
**Base Branch:** `main`  
**Working Branch:** `feat/harness-v0.3d`  
**Date:** 2026-11-22  

---

## 1. Executive Summary & Mission Scope

Phase V0.3-D proves that the existing IELTS Data Harness generalizes reliably to previously unprocessed examinations across both Reading and Listening modalities without architectural rewrites or source-specific hardcoded overrides.

The mission operated under strict constraints:
- Process at most **ONE** new Reading test and **ONE** new Listening test.
- Do not redesign the architecture; do not normalize all 206 raw files in the repository.
- Zero chatbot or web UI construction.
- Strict copyright and privacy isolation: 0 copyrighted exam strings or private raw text committed to Git.
- Epistemic conservatism: fail-closed verification policy (no unverified answer promoted to verified status without authenticated human review, no fabricated timestamps, no guessing missing keys).

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   V0.3-D CONTROLLED CORPUS EXPANSION TOPOLOGY                    │
│                                                                                  │
│   Reading Pilot (VOL 6 Test 6 Passage 1):                                        │
│   • Source Document:     SRC-138 (private/raw/VOL 6/READING/VOL 6.docx)          │
│   • Key/Explanation:     SRC-137 (KEY + EXPLANATION 5-6.pdf)                     │
│   • Layout Challenges:   Word table grids, flowchart, lowercase prompt labels   │
│   • Emitted Entities:    57 entities (13 Questions, 13 Answers, 13 Evidence,     │
│                          13 Explanations, 1 Test, 1 Passage, 3 Groups)           │
│                                                                                  │
│   Listening Pilot (VOL 1 Test 2 Sections 1–4):                                   │
│   • Question Booklet:    SRC-020 (private/raw/VOL 1/TEST 2/Test_2.pdf)           │
│   • Transcript Document: SRC-021 (Transcript Test 2.docx)                        │
│   • Audio Assets:        SRC-017 (Sec 1), SRC-018 (Sec 2), SRC-019 (Sec 3)      │
│                          (Section 4 audio explicitly identified as MISSING)      │
│   • Layout Challenges:   Note completion, Single MCQ, Multi MCQ, Table, Matching│
│   • Emitted Entities:    214 entities (40 Questions, 40 Answers, 40 Evidence,    │
│                          4 Sections, 4 Audio Assets, 1 Test, Segments, Turns)    │
│                                                                                  │
│   SQLite Checkpoint & Manifest Gateway:                                          │
│   • Deterministic Rerun: 100% checkpoint reuse (271 / 271 skipped on rerun)      │
│   • Multi-Test Manifest: Merges active entities across tests without collision   │
│   • Fail-Closed Policy:  0 answers marked verified without authenticated review  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Selected Pilots & Provenance Verification

Pilot discovery inspected `source_inventory.csv`, `document_classification.csv`, and the SQLite relationship registry (`harness/state/harness.db`).

### 2.1 Reading Pilot
- **Test ID:** `TEST-IELTS-VOL06-06-ACAD`
- **Passage ID:** `PASSAGE-VOL06-06-RD01` (*Ambergris*, Questions 1–13)
- **Source Text:** `SRC-138` (`FILE-5a2cce4d0793`, `private/raw/VOL 6/READING/VOL 6.docx`)
  - Format: Microsoft Word DOCX
  - SHA-256: `d99ca101fdbd8329b359f47053e18a8043444fb9a53fe597c588523c03163353`
- **Key & Explanation Source:** `SRC-137` (`FILE-181f8751b4f4`, `private/raw/VOL 6/READING/KEY + EXPLANATION 5-6.pdf`)
  - Format: PDF OCR (Tesseract / pdftoppm)
  - SHA-256: `d316c8ac3d29bc42427d4290d9be27830b4b8eff114ee45d45ebf3afb8793933`
- **Source Relationships:**
  - `REL-098354d0e576d854` (`answer_key_for`, `candidate`)
  - `REL-a334af7819c00055` (`explanation_for`, `candidate`)

### 2.2 Listening Pilot
- **Test ID:** `TEST-IELTS-VOL01-02-LIS` (Sections 1–4, Questions 1–40)
- **Question Booklet:** `SRC-020` (`FILE-128ced80a86e`, `private/raw/VOL 1/TEST 2/Test_2.pdf`)
  - Format: PDF OCR (23 scanned pages)
  - SHA-256: `e26c9974a8f87f8f2dbfa0211ad525361ee5c2957e77a61fd50fe1c36bb3233f`
- **Transcript Document:** `SRC-021` (`FILE-447270cfb5ea`, `private/raw/VOL 1/TEST 2/Transcript Test 2.docx`)
  - Format: Microsoft Word DOCX with speaker labels and paragraph structure
  - SHA-256: `02e7a5c47a80b061859dd52628e1f20e72a4474efb77f24c1033b43ea8fd076f`
- **Audio Assets:**
  - Section 1: `SRC-017` (`FILE-c0870d7cc4e9`, `1.mp3`, `fcbf812bf706059b56dd7d29eb0cf588d9282d8c3fbe6520f340be561a066487`) — Status: Available
  - Section 2: `SRC-018` (`FILE-fffc909d3616`, `2.mp3`, `80798e49d6ae5f00e57cecebcf6ef31cbb5b5ea1c54b2fc5d89ea343a4ea8442`) — Status: Available
  - Section 3: `SRC-019` (`FILE-acf4d5506963`, `3.mp3`, `1f5a54db12613faeb486f0aa6725287ec2d76f8ebaa8c057ccfcf1a7ae221f7e`) — Status: Available
  - Section 4: Missing from physical archive storage — Status: Explicitly marked `missing` (no fabricated audio asset or timestamps).

---

## 3. Generalization Architecture & Corpus Adaptations

To support real-world formatting variations across the broader IELTS corpus without breaking architectural invariants or hardcoding test-specific values, minimal generic enhancements were made:

### 3.1 DOCX Block Stream Interleaving
*Observation:* In IELTS DOCX files, classification summaries and flowcharts frequently reside in embedded table structures (`w:tbl`) rather than top-level paragraphs (`w:p`).  
*Enhancement:* `DocxReadingNormalizer` was extended to consume sequential `content.blocks` (which interleaves table rows and text paragraphs in document order), ensuring prompt positions and flowchart connections are faithfully preserved.

### 3.2 Generic Case-Insensitive Prompt Segmentation
*Observation:* Classification prompts in Test 6 began with lowercase letters (e.g., `1 very expensive`, `2 a food flavouring`). The previous lookahead `(?=[A-Z])` caused a `SEGMENTATION_SEQUENCE_GAP`.  
*Enhancement:* The question delimiter regex was refined to:
```regex
(?:^\s*|(?<=[\.\?!a-zA-Z])|(?<=\s)(?={num}[\.\s]*[A-Z\"\'\(\[]))({num})(?:[\.\s]*)(?=[A-Za-z0-9\"\'\(\[])
```
This cleanly matches prompts starting with lowercase characters, quotation marks, or numerals, while rejecting internal numerical tokens (e.g., "$400" or "in 1980").

### 3.3 Dynamic Multi-Test Page Transition Slicing
*Observation:* In scanned secondary explanation books (`SRC-137`), multiple tests and passages share physical pages (e.g. Page 11 contains both the conclusion of Passage 1 and the start of Passage 2).  
*Enhancement:* `AnswerReconciler.parse_pdf_ocr_explanation_keys` detects `start_test` dynamically from volume filenames and splits page text across `READING PASSAGE (\d+)` boundaries, completely preventing cross-passage answer leakage.

### 3.4 Multi-Test Authoritative Manifest Persistence
*Observation:* Running normalization on a new test initially overwrote `manifest.json`, dropping existing pilot records and causing subsequent retrieval lookups to reject valid pilot entities.  
*Enhancement:* `ReadingOrchestrator` was updated to partition manifest records by `test_slug`, preserving active records from prior tests and atomically merging new test entities into `manifest.json`.

---

## 4. Quality Metrics Matrix

The quality evaluation adheres to strict metric separation, never inflating verified coverage or conflating structural extraction with human verification:

| Metric Category | Reading Pilot (`VOL06-06`) | Listening Pilot (`VOL01-02`) | Combined Total | Policy Standard |
| :--- | :---: | :---: | :---: | :--- |
| **Questions Parsed** | 13 | 40 | **53** | 100% of selected pilot items |
| **Questions Structurally Valid** | 13 (100%) | 40 (100%) | **53 (100%)** | Conforms to Pydantic v2 schemas |
| **Answers Extracted** | 8 (61.5%) | 39 (97.5%) | **47 (88.7%)** | Raw keys extracted from source OCR |
| **Answers Source-Verified** | 0 (0.0%) | 0 (0.0%) | **0 (0.0%)** | Fail-closed: Requires expert review record |
| **Evidence Records Linked** | 13 (100%) | 40 (100%) | **53 (100%)** | Provenance tracked to source document |
| **Evidence Text Grounded** | 10 (76.9%) | 34 (85.0%) | **44 (83.0%)** | Exact verbatim quotes grounded in text |
| **Explanations Available** | 13 (100%) | 0 (0.0%) | **13 (24.5%)** | Official rationale provided |
| **Unresolved Records** | 13 | 41 | **54** | Documented in human review queue |
| **Relationship Conflicts** | 0 | 0 | **0** | Zero unresolvable source conflicts |
| **Checkpoint Reuse Rate (Rerun)** | 57 / 57 (100%) | 214 / 214 (100%) | **271 / 271 (100%)** | Zero re-writes on identical execution |

### Question Readiness Classification

```
┌────────────────────────────────────────────────────────────────────────┐
│                   QUESTION READINESS CLASSIFICATION                    │
├───────────────────┬──────────────┬─────────────────────────────────────┤
│ Category          │ Count (Pct)  │ Qualification Criteria              │
├───────────────────┼──────────────┼─────────────────────────────────────┤
│ READY             │   0 ( 0.0%)  │ Requires verified answer key,       │
│                   │              │ grounded evidence, and sign-off.    │
│ REVIEW_REQUIRED   │  47 (88.7%)  │ Structurally valid question & key   │
│                   │              │ pending authenticated review record.│
│ BLOCKED           │   6 (11.3%)  │ Missing answer key / truncated OCR  │
│                   │              │ (Reading Q5, 10..13; Listening Q37).│
└───────────────────┴──────────────┴─────────────────────────────────────┘
```

---

## 5. Prioritized Human Review Queue

A total of 54 review items were generated across priority tiers and saved to `private/reports/v03d/human_review_queue.json`:

### Priority 1: Missing Answer Keys & Discrepancies (Blockers)
1. **`Q-VOL06-06-RD-005`** (`SRC-137`): OCR artifact `5S` prevented automatic key extraction.
2. **`Q-VOL06-06-RD-010`** (`SRC-137`): OCR artifact `49` prevented automatic key extraction.
3. **`Q-VOL06-06-RD-011`** (`SRC-137`): OCR artifact `41.` prevented automatic key extraction.
4. **`Q-VOL06-06-RD-012`** (`SRC-137`): OCR artifact `42` prevented automatic key extraction.
5. **`Q-VOL06-06-RD-013`** (`SRC-137`): OCR artifact `43` prevented automatic key extraction.
6. **`Q-VOL01-02-LS-037`** (`SRC-020`): Booklet OCR page 22 truncated letter next to question 37 (`28C 37 `).
7. **`Q-VOL01-02-LS-001`** (`SRC-020` vs `SRC-021`): Audio speaker utters 7-digit number `61438197` while booklet page 22 OCR key prints 8-digit number `614381997`.
8. **`SEC-VOL01-02-LS04`** (`TEST-IELTS-VOL01-02-LIS`): Section 4 audio file missing from physical archive disk.

### Priority 2: Grounding & Alignment Uncertainties
- **`Q-VOL06-06-RD-003`**: Multiple candidate keys detected in secondary explanation block.
- **`Q-VOL01-02-LS-011..014`**, **`Q-VOL01-02-LS-022, 025`**: Transcript dialogue spans require granular sentence-level alignment.

### Priority 3: Unverified Answer Keys Pending Expert Sign-off
- 7 Reading questions (`Q1, Q2, Q4, Q6..Q9`) and 33 Listening questions pending authenticated human examiner review in `harness/state/harness.db`.

---

## 6. Acceptance Gates Evaluation (D1–D10)

| Gate | Requirement | Status | Verification Evidence |
| :--- | :--- | :---: | :--- |
| **D1** | Both selected pilots assessed | **PASS** | 1 Reading passage (13 Qs) and 1 Listening test (40 Qs) processed through normalization. |
| **D2** | Source identities documented | **PASS** | All entities reference SHA-256 verified source records (`SRC-138`, `SRC-137`, `SRC-020`, `SRC-021`, `SRC-017`..`019`). |
| **D3** | Emitted entities schema-valid | **PASS** | All 271 normalized JSON entities strictly validate against Pydantic v2 models. |
| **D4** | No fabricated answer or evidence | **PASS** | Zero synthetic answers, letters, or timestamps created. Gaps preserved as `null`. |
| **D5** | Verification status is truthful | **PASS** | Exactly 0 unverified answers claim verified status (`verified_answers_count = 0`). |
| **D6** | Provenance is traceable | **PASS** | Every entity carries full `ProvenanceEnvelope` with source file ID, SHA-256, and block offsets. |
| **D7** | Deterministic reruns | **PASS** | 100% checkpoint reuse on rerun (0 written, 271 skipped). |
| **D8** | Existing tests pass | **PASS** | 222 public tests and 231 corpus tests pass with 0 regressions. |
| **D9** | Private source isolation | **PASS** | 0 private files or copyrighted exam content tracked or staged in Git. |
| **D10** | Generalization assessed explicitly | **PASS** | Formats, error modes, and edge cases evaluated across both modalities. |

---

## 7. Automated Test Suite Results

The automated test suite was executed using the project-local virtual environment (`./.venv/bin/python`):

```bash
# Public Test Suite (including 10 new generalization tests)
./.venv/bin/python -m pytest -q tests/
# Result: 222 passed, 9 skipped in 17.43s

# Corpus Integration Suite
./.venv/bin/python -m pytest -q tests/ --corpus
# Result: 231 passed in 39.34s

# Diagnostic Environment Check
./.venv/bin/python -m harness.cli check-env
# Result: All required Python and system dependencies are satisfied.

# Principles Index Validation
./.venv/bin/python scripts/build_principles_index.py --check
# Result: Validated 7 atomic principles; index up to date.
```

---

## 8. Scaling Assessment & GO / NO-GO Recommendation

### Verdict: **CONDITIONAL GO FOR CONTROLLED BATCH SCALING (UP TO 5 TESTS)**

The Harness demonstrated strong architectural generalization across previously unseen test structures (Word tables, flowcharts, lowercase prompts, missing audio). However, unconstrained batch scaling to all 206 files is **NOT RECOMMENDED** until the following safeguards are implemented:

1. **OCR Pre-Processing / Digital Keys:** Low-quality scans of secondary answer keys (`SRC-137`) generate excessive OCR noise (`5S`, `49`, `41.`), blocking automated scoring. High-resolution OCR preprocessing or publisher digital keys should be prioritized.
2. **Audio Inventory Audit:** Physical archive gaps (such as missing Section 4 audio in VOL 1 Test 2) must be flagged upstream during inventory ingestion so the pipeline knows whether audio alignment is feasible.
3. **Interactive Reviewer Interface:** Human review records cannot be scaled via manual SQLite inserts. An efficient CLI or lightweight review tool is required to process the 54 review queue items efficiently.
