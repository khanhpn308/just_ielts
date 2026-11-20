# IELTS Data Harness V0.3 — Phase V0.3-A Engineering Report
**Phase:** V0.3-A Multi-Source Matching & Provenance Resolver  
**Role:** Senior Data Engineer, Python Engineer, and Data Quality Architect  
**Repository:** `~/projects/just_ielts`  
**Base Branch:** `main`  
**Working Branch:** `feat/harness-v0.3a`  
**Date:** 2026-11-20  

---

## 1. Executive Summary & Mission

Phase V0.3-A designs, implements, and validates a deterministic, evidence-based **Source Relationship Resolver** for the IELTS data harness. In heterogeneous exam corpora, multiple physical files often comprise a single test unit (e.g. question booklets, answer key sheets, detailed pedagogical explanation guides, audio recordings, tapscripts/transcripts, and writing sample responses).

### Core Invariant
**Do not assume sources match based only on filename similarity or question numbers.** A confidence score alone must never promote a relationship to `confirmed`. All document relationships require multi-layered forensic proof across metadata, structure, content, and conflict auditing.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             FOUR-LAYER MATCHING ENGINE                            │
│                                                                                  │
│   Layer 1: Metadata Verification                                                 │
│   • Canonical Volume Matching ("VOL 6" == "VOL 6")                               │
│   • Skill Compatibility (Reading, Listening, Writing, Speaking)                 │
│   • Test Number Intersection & Containment                                       │
│   • Passage / Section Index Alignment                                            │
│                                      │                                           │
│                                      ▼                                           │
│   Layer 2: Structural Checks                                                     │
│   • Expected Question Range Verification (e.g. Passage 1 -> Q1-Q14)              │
│   • Question Count & Number Contiguity                                           │
│   • Section Track Boundary Verification (e.g. Track 01 -> Section 1)            │
│                                      │                                           │
│                                      ▼                                           │
│   Layer 3: Content Alignment                                                     │
│   • Passage Title / Subject Lexical Alignment                                    │
│   • Answer Key Agreement vs. Contradiction Auditing                              │
│                                      │                                           │
│                                      ▼                                           │
│   Layer 4: Conflict Audit & Epistemic Status Determination                       │
│   • Rejection on Critical Conflicts (CROSS_VOLUME, CONFLICTING_KEYS, etc.)       │
│   • Unresolved Routing to REVIEW_REQUIRED on Ambiguity or Missing Metadata       │
│   • Strict Confirmation Gate Verification                                        │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Source Relationship Domain Model

Source relationship entities are modeled as strict Pydantic schemas in `harness/models/relationship.py` conforming to schema `v0.3.0-relationship`:

### 2.1 Required Fields
1. `relationship_id`: Stable deterministic identifier formatted as `REL-[a-f0-9]{16}`, computed from `(source_file_id, target_file_id, relationship_type, volume, test_number, passage_or_section)`.
2. `source_file_id`: Physical file identifier of the source document (`FILE-[a-f0-9]{12}`).
3. `target_file_id`: Physical file identifier of the target document (`FILE-[a-f0-9]{12}`).
4. `relationship_type`: Supported types:
   - `question_to_answer_key`
   - `question_to_explanation`
   - `listening_to_audio`
   - `listening_to_transcript`
   - `writing_to_sample_answer`
5. `collection`: Corpus collection identifier (e.g. `VOL 6`, `VOL 1`).
6. `volume`: Canonical volume identifier (e.g. `VOL 6`, `VOL 1`).
7. `test_number`: IELTS test number within the volume (optional integer, 1–20).
8. `passage_or_section`: Reading passage (1–3) or Listening section (1–4) (optional integer, 1–4).
9. `skill`: Target skill (`reading`, `listening`, `writing`, `speaking`).
10. `identity_evidence`: Structured dictionary documenting metadata, structural alignment, and answer key comparison metrics.
11. `validation_flags`: Machine-evaluable verification flags (e.g. `VOLUME_MATCH`, `SKILL_MATCH`, `TEST_NUMBER_MATCH`, `GATE_CONFIRMED_PASSED`).
12. `match_confidence`: Float score between `0.0` and `1.0`.
13. `relationship_status`: Epistemic status:
    - `confirmed`: Zero conflicts, all layers verified, positive content or structural alignment.
    - `candidate`: Plausible pair under preliminary metadata check, awaiting content grounding.
    - `review_required`: Unresolved ambiguity, missing metadata, or multi-candidate collision.
    - `rejected`: Proven contradictions (cross-volume, conflicting answer keys, mismatched tests/passages).
14. `provenance`: Audit envelope tracking matcher name, matcher version (`0.3.0-a`), evaluation timestamp, source paths, and layers passed.
15. `schema_version`: `v0.3.0-relationship`.

---

## 3. SQLite Relationship Registry Architecture

The existing SQLite database (`harness/state/harness.db`) was extended safely with backward-compatible tables and indexing:

### 3.1 Tables
- `source_relationships`: Stores relationship records with foreign key references to `sources(file_id)`, indexed by source, target, status, type, and volume.
- `relationship_conflicts`: Detailed ledger of detected contradictions (`conflict_id`, `relationship_id`, `conflict_type`, `severity`, `description`, `evidence`, `created_at`).
- `relationship_reviews`: Audit history for human tutor or automated reviewer state transitions (`review_id`, `relationship_id`, `previous_status`, `new_status`, `reviewer`, `reason`, `created_at`).

### 3.2 Invariants
- **Non-destructive migration:** `init_db()` dynamically inspects existing table schemas and applies migrations without destroying existing `sources`, `processing_checkpoints`, or `normalization_checkpoints`.
- **Idempotency:** `upsert_source_relationship()` leverages `ON CONFLICT(relationship_id) DO UPDATE` to guarantee that repeated runs produce identical states and zero duplicate rows.
- **Read-Only Raw Isolation:** No modification is ever made to raw source documents under `private/raw/`.

---

## 4. Pilot Execution & Negative Forensic Audit

### 4.1 Negative Pilot: Forensic Audit of `SRC-138`, `SRC-137`, and `SRC-077`
The pilot was executed against the real inventory of the IELTS corpus:
1. **`SRC-138` (`private/raw/VOL 6/READING/VOL 6.docx`):**
   - Volume: `VOL 6`
   - Skill: `reading`
   - Role: `question_booklet`
   - Tests covered: Tests 5, 6, 7, 8...
2. **`SRC-137` (`private/raw/VOL 6/READING/KEY + EXPLANATION 5-6.pdf`):**
   - Volume: `VOL 6`
   - Skill: `reading`
   - Role: `explanation` / `answer_key`
   - Tests covered: Tests 5 and 6
3. **`SRC-077` (`private/raw/VOL 3/Reading/key.xlsx`):**
   - Volume: `VOL 3`
   - Skill: `reading`
   - Role: `answer_key`
   - Tests covered: Tests 1 through 9

#### Findings & Revalidation
- **`SRC-138` -> `SRC-137`:**
  - `VOLUME_MATCH`: Both belong to canonical `VOL 6`.
  - `SKILL_MATCH`: Both target `reading`.
  - `TEST_NUMBER_MATCH`: Both cover Test 5 (and Test 6).
  - `QUESTION_RANGE_ALIGNED`: Passage questions align with expected numbering ranges.
  - `CONTENT_GROUNDING_AUDIT`: Passage titles between `SRC-138` and `SRC-137` do not match, and `SRC-138` contains no answer keys.
  - **Status:** **CANDIDATE** (`match_confidence = 0.7`). In accordance with strict non-circularity invariants, an answer key cannot confirm itself. In the absence of independent ground truth or passage title agreement, these relationships are properly preserved as `candidate` rather than falsely inflated to `confirmed`.
- **`SRC-138` -> `SRC-077`:**
  - `VOLUME_MISMATCH`: `SRC-138` belongs to `VOL 6`, whereas `SRC-077` belongs to `VOL 3`.
  - `CONFLICTING_ANSWER_KEYS`: Overlapping questions for Test 5 directly contradict verified pilot keys across all items:
    - Q2: Ground truth is `FALSE`; `SRC-077` specifies `T`.
    - Q3: Ground truth is `NOT GIVEN`; `SRC-077` specifies `F`.
    - Q5: Ground truth is `FALSE`; `SRC-077` specifies `NGV`.
    - Q6: Ground truth is `TRUE`; `SRC-077` specifies `F`.
    - Q7: Ground truth is `fraudulent`; `SRC-077` specifies `seeds`.
    - Q8: Ground truth is `museums`; `SRC-077` specifies `shells`.
  - **Verdict:** `SRC-077` was **100% REJECTED** with two critical conflicts (`CROSS_VOLUME_MISMATCH` and `CONFLICTING_ANSWER_KEYS`). It is categorically prevented from merging into the VOL 6 Reading pilot.

### 4.2 Listening Pilot: `SRC-011`, `SRC-008`, `SRC-012`
- **`SRC-011` (`VOL 1/TEST 1/Test_1.pdf`) -> `SRC-008` (`AudioTrack 01.mp3`):**
  - Confirmed as `listening_to_audio` for VOL 1 Test 1 Section 1 (`Beechen Festival`).
- **`SRC-011` (`VOL 1/TEST 1/Test_1.pdf`) -> `SRC-012` (`Transcript Test 1.docx`):**
  - Confirmed as `listening_to_transcript` for VOL 1 Test 1 Section 1.
- **`SRC-008` -> `SRC-012`:**
  - Confirmed as audio-transcript pairing for VOL 1 Test 1 Section 1.

---

## 5. Quality Gate Verification (R1–R9)

| Gate ID | Requirement | Result | Forensic Verification |
|---|---|---|---|
| **R1** | All source IDs exist in inventory | **PASS** | Validated by foreign key constraints in SQLite and catalog lookup. |
| **R2** | No cross-volume false matches | **PASS** | All cross-volume candidate pairs (including `SRC-077` vs VOL 6 and VOL 1) were rejected. |
| **R3** | No unsupported answer-key attribution | **PASS** | Keys require matching volume, test, passage, and answer agreement to confirm. |
| **R4** | Every relationship retains provenance | **PASS** | `provenance` block records matcher version, evaluation timestamp, source paths, and layer outcomes. |
| **R5** | Duplicate relationships are prevented | **PASS** | Enforced by deterministic primary key `relationship_id` and idempotent upsert logic. |
| **R6** | Repeated runs are deterministic | **PASS** | Evaluated twice on the same sources; identical relationship IDs and conflict counts produced. |
| **R7** | Ambiguous candidates remain unresolved | **PASS** | Missing metadata and multi-candidate ambiguities route to `review_required`. |
| **R8** | Existing V0.2 normalization unchanged | **PASS** | All existing normalizers, schemas, and V0.2 test suites pass with zero regressions. |
| **R9** | Private materials remain isolated | **PASS** | Private reports stored under `private/reports/v03a/`; public files contain no copyrighted source text. |

---

## 6. Test Suite Execution & Coverage

All 13 test scenarios specified in Section 8 of the requirement were implemented in `tests/test_v03a_relationship_resolver.py`:
1. `test_correct_source_matching`: Confirmed matching pair.
2. `test_volume_mismatch_rejection`: Rejection of cross-volume candidate.
3. `test_test_number_mismatch_rejection`: Rejection of test number mismatch.
4. `test_passage_mismatch_rejection`: Rejection of passage index mismatch.
5. `test_conflicting_answer_keys_rejection`: Rejection when candidate key contradicts ground truth.
6. `test_missing_source_metadata_review_required`: Routing to `review_required` on missing metadata.
7. `test_duplicate_records_prevention`: Idempotent upsert verification.
8. `test_multiple_candidate_keys`: Multi-candidate conflict resolution without forced promotion.
9. `test_matching_idempotency`: Deterministic execution across repeated runs.
10. `test_sqlite_migrations`: Dynamic migration verification on legacy SQLite databases.
11. `test_interrupted_processing_and_resume`: Checkpoint resume skipping existing records.
12. `test_source_relocation_and_hash_invalidation`: Provenance updates on relocated source files.
13. `test_privacy_isolation`: Verification of zero copyrighted text in public fixtures.

### Test Results (Post-Remediation)
- **Clean Checkout (Synthetic Only):**
  ```bash
  ./.venv/bin/python -m pytest -q tests/
  # Output: 139 passed, 9 skipped in 10.12s
  ```
- **Local Corpus Acceptance:**
  ```bash
  ./.venv/bin/python -m pytest -q tests/ --corpus
  # Output: 148 passed in 29.05s
  ```
- **Environment Check:**
  ```bash
  ./.venv/bin/python -m harness.cli check-env
  # Output: All required Python and system dependencies are satisfied.
  ```

---

## 7. PR #5 Correctness Remediation

Following architectural audit, six core remediation invariants were implemented and verified:
1. **Generic Candidate Generation (P0):**
   - Removed all hardcoded test/section assumptions (Reading Test 5, Passage 1; Listening Test 1, Section 1; SRC-138 / SRC-077 special branches).
   - Candidate pairs are dynamically synthesized from document metadata and content extraction.
   - For multi-test and multi-passage sources, distinct candidates are generated where supported, preserving ambiguity when metadata is unstated.
2. **Strict Relationship Confirmation (P0):**
   - Separated metadata compatibility, structural compatibility, and actual content alignment.
   - `QUESTION_RANGE_ALIGNED` alone never confirms a relationship without content grounding (`ANSWERS_ALIGNED` or `CONTENT_TITLE_MATCH`).
   - `TRANSCRIPT_AUDIO_ALIGNED` requires independent physical audio track or verified transcript section content; requested section numbers alone cannot confirm.
3. **Cryptographic Resume & Freshness Audit (P0):**
   - Tracked `source_content_sha256`, `target_content_sha256`, `matcher_version`, `config_fingerprint`, and `evidence_fingerprint`.
   - Stale relationships reevaluated on content modifications; review history and deterministic IDs preserved.
4. **Real Runtime Quality Gate Evaluation (P1):**
   - Quality gates R1–R9 evaluated at runtime supporting `PASS`, `PASS_WITH_UNRESOLVED`, `FAIL`, and `NOT_EVALUATED` with structured evidence and counts.
5. **Privacy Isolation & Dry-Run Enforcement (P1):**
   - Strict validation of `output_dir` rejecting public directories (`docs/`, `tests/`, `harness/`, repo root) and symlink escapes.
   - `dry_run=True` verified to never mutate SQLite or write persistent outputs unless explicitly requested.

### 7.1 Final Blocking Fixes
1. **GitHub CI Fixture Remediation (Fix 1):**
   - Fixed `test_privacy_output_dir_validation_negative` failure on clean GitHub checkouts where `private/` is gitignored and does not exist.
   - Replaced workspace references with isolated `tmp_path` fixtures verifying valid private output, forbidden public output, path traversal (`..`), and symlink escapes without modifying the corpus or touching real workspace roots.
2. **Circular Answer Confirmation Remediation (Fix 2):**
   - `RelationshipMatchingService` strictly prohibits passing `target_meta.answer_keys` as independent ground truth.
   - `MatchingEngine` requires independent source identification, source provenance, explicit test and question alignment, and zero circularity for `ANSWERS_ALIGNED`.
   - An answer key cannot confirm itself. Unprovenanced keys or self-referential inputs trigger `CIRCULAR_ANSWER_EVIDENCE_REJECTED` and are preserved as `candidate` (`match_confidence = 0.7`) rather than inflated to `confirmed`.
   - Added negative regression test verifying that question booklets and unrelated answer keys sharing Volume, Test, and question numbers are never falsely aligned or confirmed.
   - Reconciled pilot relationship status distribution: 6 confirmed listening links, 12 candidate reading links, 105 rejected pairs.

---

## 8. CLI Usage

The harness CLI was extended with two subcommands:

### 8.1 Match Sources
```bash
./.venv/bin/python -m harness.cli match-sources --pilot
./.venv/bin/python -m harness.cli match-sources --source-id SRC-138
./.venv/bin/python -m harness.cli match-sources --source-id SRC-138 --target-id SRC-137
./.venv/bin/python -m harness.cli match-sources --pilot --dry-run
```

### 8.2 Relationship Status
```bash
./.venv/bin/python -m harness.cli relationship-status
```

---

## 9. Limitations & Scope Boundary

- **Listening Normalization:** Listening audio intervals and transcript paragraph segmentation are out of scope for V0.3-A and deferred to V0.3-B.
- **Human Review CLI:** Interactive human-in-the-loop review interface is out of scope and scheduled for Sprint 3 (V0.3-C).
- **Corpus Normalization:** Full-corpus ingestion of all 206 sources remains deferred until multi-source relationship links are confirmed across all volumes.
