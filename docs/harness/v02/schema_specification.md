# IELTS Data Harness V0.2 — Schema Specification & Data Dictionaries
**Phase V0.2-A: Schema Design & Normalization Contract (Remediated)**  
**Status:** Architectural Blueprint (Design Only)  
**Author:** IELTS Learning Systems Engineer & Data Architecture Team  
**Date:** 2026-11-19 (Remediated)  

---

## 1. Global Standards & Envelopes

Every normalized JSON record produced in Phase V0.2 adheres to JSON Schema Draft 2020-12 and must encapsulate standardized **Provenance Envelope** and **Quality Profile** components.

### 1.1 The Standard Provenance Envelope (`_provenance`)
Aligned with Phase V0.1 inventory and extraction outputs:

| Field Name | Type | Constraint | Description | Example |
|---|---|---|---|---|
| `schema_version` | `string` | Const: `"v0.2.0-normalized"` | Normalized schema version | `"v0.2.0-normalized"` |
| `source_file_id` | `string` | Required, Pattern: `^FILE-[a-f0-9]{12}$` | Physical file ID from V0.1 `sources.file_id` | `"FILE-3a7f8090a786"` |
| `source_legacy_id` | `string` | Required, Pattern: `^(SRC-\d{3,4}\|UNKNOWN)$` | Authoritative legacy ID from V0.1 `sources.legacy_id` | `"SRC-138"` |
| `relative_path` | `string` | Required | Relative path under `private/raw/` | `"private/raw/VOL 6/READING/VOL 6.docx"` |
| `source_sha256` | `string` | Required, 64-char Hex | Cryptographic SHA-256 of raw file bytes | `"3a7f8...b1"` |
| `processing_unit` | `string` | Required, Enum | Partition type (`document`, `page`, `sheets`, `audio_metadata`) | `"document"` |
| `unit_identifier` | `string` | Required | Partition identifier (`raw_document`, `page_0001`, `raw_sheets`) | `"raw_document"` |
| `raw_block_locator` | `string` | Required | Locator within raw block (`para_index:309`, `cell:B3`, `line:12`) | `"para_index:309"` |
| `extractor_adapter` | `string` | Required | Adapter name from V0.1 | `"docx"` |
| `extractor_version` | `string` | Required | Adapter version tag | `"0.1.0-lxml-docx"` |
| `normalizer_version`| `string` | Required | Normalizer version tag | `"0.2.0-alpha"` |
| `canonical_content_sha256`| `string` / `null` | Optional, 64-char Hex | Hash of canonical fields (excluding timestamps) | `"e3b0c44...b855"` |
| `normalized_at` | `string` / `null` | Optional, ISO 8601 UTC | Execution timestamp (excluded from canonical hash) | `"2026-11-19T12:00:00Z"` |

---

### 1.2 The Unified Quality Profile (`quality_profile`)
Referenced by all core entities via `$ref: "quality_profile.schema.json"`:

| Field Name | Type | Enum Values / Format | Description |
|---|---|---|---|
| `lifecycle_status` | `string` | `["extracted", "review_required", "reviewed", "verified", "rejected"]` | Pipeline state machine status |
| `extraction_quality` | `string` | `["complete_clean", "ocr_noisy", "segmented_imperfect", "truncated_missing_pages"]` | Text capture fidelity |
| `source_fidelity` | `string` | `["authoritative_official", "secondary_reputable", "unverified_community"]` | Document authority |
| `answer_verification` | `string` | `["authoritative_key", "consensus_key", "unverified", "disputed", "missing_key"]` | Ground truth certainty |
| `explanation_verification`| `string` | `["source_provided", "expert_verified", "machine_drafted_unverified", "unsupported", "missing_explanation"]` | Pedagogical grounding |
| `publication_permission` | `string` | `["public_synthetic", "private_copyrighted", "restricted_citation"]` | Copyright boundary |
| `validation_flags` | `array[string]`| List of string warning/diagnostic flags | Diagnostic pipeline flags |

---

## 2. Core Question Bank Data Dictionaries

### 2.1 Entity: `Test`
- **File:** `schemas/v02/test.schema.json`
- **Primary Key:** `test_id` (`TEST-IELTS-[A-Z0-9]+-\d{2}-(ACAD|GT)`)
- **Key Fields:** `title`, `volume`, `test_number`, `track`, `sections_present`, `quality_profile`, `_provenance`.

### 2.2 Entity: `PassageOrSection`
- **File:** `schemas/v02/passage_section.schema.json`
- **Primary Key:** `passage_id` (`(PASSAGE|SECTION)-[A-Z0-9-]+-(RD|LS)\d{2}`)
- **Key Fields:** `test_id`, `skill`, `sequence_number`, `title`, `subtitle`, `narrative_text`, `paragraphs`, `word_count`, `quality_profile`, `_provenance`.

### 2.3 Entity: `QuestionGroup`
- **File:** `schemas/v02/question_group.schema.json`
- **Primary Key:** `group_id` (`QG-[A-Z0-9-]+-G\d{2}`)
- **Key Fields:** `passage_id` (nullable for standalone group), `start_question_number`, `end_question_number`, `question_type`, `instruction_text`, `word_limit_rule`, `shared_options`, `quality_profile`, `_provenance`.

### 2.4 Entity: `Question`
- **File:** `schemas/v02/question.schema.json`
- **Primary Key:** `question_id` (`Q-[A-Z0-9-]+-(RD|LS|WR|SP)-\d{3}`)
- **Key Fields:** `group_id`, `passage_id` (nullable), `question_number`, `question_type`, `prompt_text`, `options`, `blank_target`, `linked_principle_ids`, `quality_profile`, `_provenance`.

### 2.5 Entity: `Answer`
- **File:** `schemas/v02/answer.schema.json`
- **Primary Key:** `answer_id` (`ANS-[A-Z0-9-]+-(KEY|ALT\d{2})`)
- **Key Fields:**
  - `question_id` (**nullable** for orphan answer keys).
  - `target_value` (**nullable** if answer key is unrecorded/missing in source).
  - `acceptable_alternates`, `case_sensitive`, `source_key_ref`, `quality_profile`, `_provenance`.

### 2.6 Entity: `Evidence`
- **File:** `schemas/v02/evidence.schema.json`
- **Primary Key:** `evidence_id` (`EVID-[A-Z0-9-]+-\d{2}`)
- **Key Fields:**
  - `answer_id` (nullable), `passage_id` (nullable).
  - `evidence_type`: `direct_support`, `contradictory_evidence`, or `insufficient_information_not_given`.
  - `verbatim_quote`: String for positive/contradictory evidence; **null for NOT GIVEN**.
  - `char_start`, `char_end`: Offsets in narrative text; **null for NOT GIVEN**.
  - `missing_information_rationale`: Explicit justification for NOT GIVEN items.
  - `exact_match_verified`, `quality_profile`, `_provenance`.

### 2.7 Entity: `Explanation`
- **File:** `schemas/v02/explanation.schema.json`
- **Primary Key:** `explanation_id` (`EXPL-[A-Z0-9-]+`)
- **Key Fields:** `question_id`, `answer_id` (nullable), `evidence_id` (nullable), `rationale_en`, `rationale_vi`, `paraphrase_map`, `distractor_notes`, `author_type`, `quality_profile`, `_provenance`.

---

## 3. Learning Knowledge Data Dictionaries

### 3.1 Entity: `PrincipleMetadata`
- **File:** `schemas/v02/principle_metadata.schema.json`
- **Key Fields:**
  - `id`: Pattern `^[A-Z]{2}-[A-Z0-9]+-\d{3}$` (e.g. `RD-TFNG-001`, `RD-CORE-001`).
  - `title`: String.
  - `type`: Enum `["principle", "strategy", "workflow", "heuristic"]`.
  - `skill`: Enum `["reading", "listening", "writing", "speaking", "general"]`.
  - `question_types`: Array of strings (can be empty for general/core principles).
  - `triggers`: Array of strings (error codes).
  - `dependencies`: Array of principle IDs (can be empty).
  - `status`: Enum `["draft", "reviewed", "verified"]`.
  - `source_refs`: Array of strings.
