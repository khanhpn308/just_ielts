# IELTS Data Harness V0.2 — Normalization Contract Specification
**Phase V0.2-A: Schema Design & Normalization Contract**  
**Status:** Architectural Blueprint (Design Only)  
**Author:** IELTS Learning Systems Engineer & Data Architecture Team  
**Date:** 2026-11-19  

---

## 1. Overview & Architectural Invariants

The Normalization Contract defines the formal processing guarantees, schema transitions, data integrity rules, and error handling protocols between staged raw extraction artifacts (`private/staging/raw_extracted/`) and canonical normalized entities (`data/normalized/`).

### 1.1 Invariant Principles
1. **Zero Guessing (No Hallucination or Imputation):**
   If an answer key is missing, an evidence quote is not found, or a question prompt is cut off, the normalizer **must not** synthesize or infer values. Missing fields must be recorded as `null`, accompanied by an explicit validation flag (e.g. `MISSING_ANSWER_KEY`, `UNRESOLVED_EVIDENCE_SPAN`).
2. **Deterministic Idempotency:**
   Running the normalization engine over identical raw JSON inputs with the same normalizer configuration must yield bit-identical normalized output JSON files and identical cryptographic hashes.
3. **Traceable Lineage:**
   Every normalized entity must carry a `_provenance` block containing the originating physical file ID (`source_file_id`), processing unit (`unit_identifier`), block index, and character/byte locator.
4. **Schema Versioning:**
   All normalized outputs must declare `schema_version: "v0.2.0-normalized"`. Breaking changes to entity structures necessitate incrementing the minor version (`v0.3.0-normalized`).

---

## 2. Stage-by-Stage Input/Output Contracts

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          NORMALIZATION STAGES & CONTRACTS                       │
│                                                                                 │
│  [Raw JSON Artifact]                                                            │
│          │                                                                      │
│          ▼ Stage 1: Content Block Sanitization Contract                         │
│  [ContentBlock Stream]                                                          │
│          │                                                                      │
│          ▼ Stage 2: Structural Demarcation Contract                             │
│  [PassageOrSection & TaskPrompt Entities]                                       │
│          │                                                                      │
│          ▼ Stage 3: Question Group & Item Parsing Contract                      │
│  [QuestionGroup & Question Entities]                                            │
│          │                                                                      │
│          ▼ Stage 4: Answer Key Reconciliation Contract                          │
│  [Answer Entities]                                                              │
│          │                                                                      │
│          ▼ Stage 5: Evidence Grounding & Span Resolution Contract               │
│  [Evidence Entities]                                                            │
│          │                                                                      │
│          ▼ Stage 6: Explanation & Principle Linkage Contract                    │
│  [Explanation Entities & Principle Associations]                                │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

### 2.1 Stage 1: Content Block Sanitization Contract

#### Input Contract
- **Source:** Validated V0.1 raw extraction JSON artifact (e.g., `SRC-138/raw_document.json`, `SRC-011/page_0008.json`, `SRC-077/raw_sheets.json`).
- **Pre-conditions:** Checksum matches SQLite `processing_checkpoints.output_sha256`; JSON conforms to V0.1 provenance and content structure.

#### Transformation Logic
1. Strip non-printable ASCII/control characters except standard newlines (`\n`) and tabs (`\t`).
2. Normalize Unicode representations (NFC normalization).
3. De-hyphenate soft linebreaks where a word was broken across lines during typesetting or OCR (e.g. `trans- \n port` $\to$ `transport`).
4. Reconstruct contiguous paragraph blocks from segmented line fragments.

#### Output Contract: `ContentBlock`
```json
{
  "block_id": "BLK-SRC138-000309",
  "unit_id": "SRC-138:raw_document",
  "block_type": "paragraph",
  "block_index": 309,
  "raw_text": " 1 Applicants to the department must have previously studied art history.2 Students can choose...",
  "sanitized_text": "1 Applicants to the department must have previously studied art history. 2 Students can choose...",
  "char_length": 512,
  "flags": ["joined_numbered_sentences"]
}
```

---

### 2.2 Stage 2: Structural Demarcation Contract

#### Input Contract
- Stream of sanitized `ContentBlock` objects.

#### Transformation Logic
1. Identify Test Boundaries: Header patterns matching `^TEST\s+(\d+)$`, `^VOL(?:UME)?\s+(\d+)$`.
2. Identify Passage/Section Boundaries: Header patterns matching `^READING\s+PASSAGE\s+(\d+)$`, `^SECTION\s+(\d+)$`, `^PART\s+(\d+)$`.
3. Extract Passage Metadata: Title (next prominent heading), subtitle/introductory prompt.
4. Segment Paragraphs: Map paragraph letter anchors (`A`, `B`, `C`...) to body paragraphs. Calculate absolute character offsets within `narrative_text`.

#### Output Contract: `PassageOrSection`
- **Required Fields:** `passage_id`, `test_id`, `skill`, `sequence_number`, `title`, `narrative_text`, `paragraphs`, `word_count`, `_provenance`.
- **Validation Rules:**
  - `sequence_number` must be $1, 2, \text{or } 3$ for Reading ($1, 2, 3, \text{or } 4$ for Listening).
  - `paragraphs` array must not be empty; paragraph character boundaries must be contiguous and non-overlapping.
  - Word count must fall within $300 \le W \le 1500$.

---

### 2.3 Stage 3: Question Group & Item Parsing Contract

#### Input Contract
- Demarcated `PassageOrSection` and associated trailing `ContentBlock` objects.

#### Transformation Logic
1. Instruction Boundary Detection: Patterns matching `^Questions\s+(\d+)\s*[-–—]\s*(\d+)`.
2. Instruction Parsing: Extract question type keywords (e.g. `TRUE/FALSE/NOT GIVEN`, `ONE WORD ONLY`, `Choose the correct letter`).
3. Individual Question Item Extraction:
   - Handle formatted items (individual paragraphs).
   - **Concatenated Sentence Run Recovery:** In real-world DOCX files (such as `SRC-138` paragraph 309), multiple questions are run together without linebreaks (e.g. `1 Applicants... 2 Students... 3 The course...`). The parser must execute a numbered sentence splitter:
     $$\text{Pattern: } (?:\s|^)(\d{1,2})\s+([A-Z][^\d\n]+?)(?=(?:\s+\d{1,2}\s+[A-Z])|$)`$$
4. MCQ Option Extraction: Isolate choice labels `A`, `B`, `C`, `D` and their option strings.

#### Output Contract: `QuestionGroup` & `Question`
- **Required Fields (`QuestionGroup`):** `group_id`, `passage_id`, `start_question_number`, `end_question_number`, `question_type`, `instruction_text`, `_provenance`.
- **Required Fields (`Question`):** `question_id`, `group_id`, `passage_id`, `question_number`, `question_type`, `prompt_text`, `_provenance`.
- **Validation Rules:**
  - Question numbers in a group must form a continuous arithmetic sequence ($end - start + 1 = \text{count}$).
  - `prompt_text` must not be empty and must not contain residual question numbers or next-question text.

---

### 2.4 Stage 4: Answer Key Reconciliation Contract

#### Input Contract
- Parsed `Question` entity + Answer source data (XLSX sheet row, PDF answer key page, or DOCX key block).

#### Transformation Logic
1. Locate Answer by Question Number: Extract string value corresponding to question $N$.
2. Canonical Value Normalization:
   - For `true-false-not-given`: Normalize `"T"`, `"True"`, `"TRUE"` $\to$ `"TRUE"`; `"F"`, `"False"`, `"FALSE"` $\to$ `"FALSE"`; `"NG"`, `"NGV"`, `"Not Given"`, `"NOT GIVEN"` $\to$ `"NOT GIVEN"`.
   - For `yes-no-not-given`: Normalize `"Y"` $\to$ `"YES"`; `"N"` $\to$ `"NO"`; `"NG"` $\to$ `"NOT GIVEN"`.
   - For MCQ: Upper-case letter `"A"`, `"B"`, `"C"`, `"D"`.
   - For completion: Lowercase text, strip extraneous terminal punctuation, record slash-separated alternatives as `acceptable_alternates` (e.g. `"in the autumn / in autumn"` $\to$ target: `"in the autumn"`, alternates: `["in autumn"]`).
3. Conflict Resolution: If an XLSX key and an OCR key disagree, prioritize the digital XLSX key, assign status `consensus_key`, and flag `KEY_SOURCE_DISCREPANCY` for human audit.

#### Output Contract: `Answer`
- **Required Fields:** `answer_id`, `question_id`, `target_value`, `acceptable_alternates`, `case_sensitive`, `verification_status`, `source_key_ref`, `_provenance`.
- **Validation Rules:**
  - `verification_status` must never be `verified` without explicit human or cryptographic validation.
  - If answer is unlocated in source key, record `target_value: null` and flag `MISSING_ANSWER_KEY`.

---

### 2.5 Stage 5: Evidence Grounding & Span Resolution Contract

#### Input Contract
- Normalized `Answer` + `PassageOrSection` narrative text + Source explanation/location text (if available).

#### Transformation Logic
1. Extraction of Source Quote: From explanation sources (e.g., `SRC-137` "Location: Paragraph C..."), parse the quoted proof sentence.
2. Exact Span Search: Search for verbatim quote within `PassageOrSection.narrative_text`.
   - If exact match found: Record `char_start`, `char_end`, `paragraph_label`, and set `exact_match_verified: true`.
3. Fuzzy Span Resolution (OCR Noise Recovery):
   - If OCR noise prevents exact string match (e.g., `senes xêu hẹ` vs `series of issues`), execute character-level Levenshtein substring search.
   - If similarity $\ge 0.85$: Record offsets, set `exact_match_verified: false`, and record `match_confidence`.
   - If similarity $< 0.85$: Record `char_start: null`, `char_end: null`, and flag `UNRESOLVED_EVIDENCE_SPAN`.

#### Output Contract: `Evidence`
- **Required Fields:** `evidence_id`, `answer_id`, `passage_id`, `verbatim_quote`, `exact_match_verified`, `_provenance`.
- **Validation Rules:**
  - If `exact_match_verified: true`, `narrative_text[char_start:char_end]` must exactly equal `verbatim_quote`.

---

### 2.6 Stage 6: Explanation & Principle Linkage Contract

#### Input Contract
- Normalized `Question`, `Answer`, `Evidence`, and available explanation text from source materials or learning repository principles.

#### Transformation Logic
1. Parse Source Explanation: Separate general rationale from distractor refutations.
2. Paraphrase Extraction: Identify matching pairs between question prompt keywords and passage evidence keywords (e.g., `"perceived" = "people's responses to it"`).
3. Map Observable Error Triggers to Principle IDs:
   - If question type is `true-false-not-given` $\to$ link `RD-TFNG-001`.
   - If question type is `matching-information` $\to$ link `RD-MI-001` through `RD-MI-005`.
   - If question requires direct textual proof $\to$ link `RD-CORE-001`.

#### Output Contract: `Explanation`
- **Required Fields:** `explanation_id`, `question_id`, `answer_id`, `author_type`, `verification_status`, `_provenance`.
- **Validation Rules:**
  - `author_type` must be strictly categorized:
    - `"source_published"`: Directly extracted from authentic publisher key/explanation book.
    - `"expert_teacher"`: Written or verified by human IELTS instructor.
    - `"machine_drafted"`: Generated or assisted by AI (requires explicit verification gate).

---

## 3. Comprehensive Error Handling & Rejection Taxonomy

When an entity fails contract validation, the normalizer must reject or downgrade the entity according to the following taxonomy:

| Error Code | Severity | Trigger Condition | Engine Action |
|---|---|---|---|
| `SCHEMA_VALIDATION_ERROR` | FATAL | JSON violates schema definitions | Abort entity emission; log validation failure |
| `ORPHAN_FOREIGN_KEY` | FATAL | Parent entity ID not found in database | Quarantine entity in `unresolved/` queue |
| `MISSING_ANSWER_KEY` | WARNING | Question exists without matching answer key | Emit question with `answer_id: null`; mark `review_required` |
| `ORPHAN_ANSWER_KEY` | WARNING | Answer exists without matching question item | Emit answer with `question_id: null`; mark `review_required` |
| `UNRESOLVED_EVIDENCE_SPAN`| WARNING | Quoted evidence cannot be located in passage | Emit evidence with `char_start: null`; mark `review_required` |
| `OCR_CORRUPTION_DETECTED` | WARNING | Character corruption rate exceeds 10% | Mark entity with `ocr_noisy`; flag for manual transcription |
| `WORD_LIMIT_VIOLATION` | ERROR | Key answer exceeds instruction limit | Flag `INVALID_KEY_WORD_LIMIT`; set status `review_required` |
| `CONCATENATED_QUESTION_RUN`| INFO | Multiple questions found in single block | Automatically apply regex segmenter; log recovery event |
