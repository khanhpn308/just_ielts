# IELTS Data Harness V0.2 — Entity Relationship Specification
**Phase V0.2-A: Schema Design & Normalization Contract (Remediated)**  
**Status:** Architectural Blueprint (Design Only)  
**Author:** IELTS Learning Systems Engineer & Data Architecture Team  
**Date:** 2026-11-19 (Remediated)  

---

## 1. Domain Entity Catalog

The V0.2 normalized architecture categorizes all system entities into three cohesive domains: **Source & Provenance**, **Question Bank**, and **Learning Knowledge**.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              IELTS DOMAIN ENTITY CATALOG                               │
├──────────────────────────┬─────────────────────────────┬───────────────────────────────┤
│   SOURCE & PROVENANCE    │        QUESTION BANK        │      LEARNING KNOWLEDGE       │
├──────────────────────────┼─────────────────────────────┼───────────────────────────────┤
│ • SourceDocument         │ • Test                      │ • Principle                   │
│ • SourceReference        │ • PassageOrSection          │ • Strategy                    │
│ • ExtractionUnit         │ • QuestionGroup             │ • Lesson                      │
│ • ContentBlock           │ • Question                  │ • Vocabulary                  │
│                          │ • Answer                    │ • Collocation                 │
│                          │ • Evidence                  │ • EssayPlan                   │
│                          │ • Explanation               │ • SampleAnswer                │
└──────────────────────────┴─────────────────────────────┴───────────────────────────────┘
```

---

## 2. Complete Entity-Relationship Model

```mermaid
erDiagram
    SourceDocument ||--o{ ExtractionUnit : "contains"
    SourceDocument ||--o{ SourceReference : "cites"
    ExtractionUnit ||--o{ ContentBlock : "produces"
    
    Test ||--|{ PassageOrSection : "comprises"
    SourceReference ||--o{ Test : "documents"
    
    PassageOrSection ||--|{ QuestionGroup : "contains"
    PassageOrSection ||--o{ ContentBlock : "anchored_to"
    
    QuestionGroup ||--|{ Question : "groups"
    Question ||--o{ Answer : "has_correct"
    Question ||--o{ Explanation : "clarified_by"
    Question }o--o{ Principle : "tests_skill_of"
    
    Answer ||--o{ Evidence : "grounded_in"
    Evidence }o--o| PassageOrSection : "located_in"
    Evidence }o--o{ ContentBlock : "extracts_from"
    
    Explanation }o--o{ Principle : "applies_rule"
    Explanation }o--o| Evidence : "references"
    
    Principle ||--o{ Strategy : "operationalized_by"
    Principle }o--o{ Lesson : "taught_in"
    Principle }o--o{ Vocabulary : "reinforces"
    Principle }o--o{ Collocation : "illustrates"
    
    Test ||--o{ WritingPrompt : "includes_task"
    WritingPrompt ||--o{ EssayPlan : "outlined_by"
    EssayPlan ||--o{ SampleAnswer : "expanded_into"
    SampleAnswer }o--o{ Principle : "demonstrates"
    SampleAnswer }o--o{ Collocation : "incorporates"
```

---

## 3. Entity Definitions & Domain Specifications

### 3.1 Source & Provenance Domain

#### 3.1.1 `SourceDocument`
- **Definition:** Physical or digital file asset tracked in V0.1 inventory (`private/raw/`).
- **Primary Key:** `file_id` (format: `FILE-[a-f0-9]{12}`, e.g. `FILE-3a7f8090a786`).
- **Legacy Reference:** `legacy_id` (format: `SRC-\d{3,4}`, e.g. `SRC-138`).
- **Key Attributes:** `file_path`, `content_sha256`, `size_bytes`, `extension`, `detected_type`, `collection`, `relocated_from`, `relocated_to`.
- **Role:** Immutable root of provenance. All downstream learning objects maintain backward traceability to `source_file_id` and `source_legacy_id`.

#### 3.1.2 `SourceReference`
- **Definition:** Bibliographic and contextual authority citation.
- **Primary Key:** `reference_id` (e.g., `REF-CAMB-VOL01`).
- **Key Attributes:** `title`, `author_or_publisher`, `edition`, `publication_year`, `isbn_or_url`, `is_authoritative`.

#### 3.1.3 `ExtractionUnit`
- **Definition:** Discrete partition processed by V0.1 adapters.
- **Primary Key:** `unit_id` (e.g., `FILE-7dbc16204945:page_0001`, `FILE-3a7f8090a786:raw_document`).
- **Key Attributes:** `source_file_id`, `unit_type` (`page`, `document`, `sheets`, `audio_metadata`), `unit_identifier` (`page_0001`), `adapter_name`, `adapter_version`.

#### 3.1.4 `ContentBlock`
- **Definition:** Atomic structural element of extracted text or media (paragraph, heading, table row, list item, dialogue segment).
- **Primary Key:** `block_id` (e.g., `BLK-FILE3a7f8090a786-000309`).
- **Key Attributes:** `unit_id`, `block_type`, `block_index`, `raw_text`, `sanitized_text`, `bounding_box`.

---

### 3.2 Question Bank Domain

#### 3.2.1 `Test`
- **Definition:** Complete IELTS examination paper.
- **Primary Key:** `test_id` (e.g., `TEST-IELTS-VOL06-05-ACAD`).
- **Key Attributes:** `volume`, `test_number`, `track` (`academic` or `general_training`), `title`, `sections_present`, `quality_profile`, `_provenance`.

#### 3.2.2 `PassageOrSection`
- **Definition:** Reading Passage (1–3) or Listening Section (1–4).
- **Primary Key:** `passage_id` (e.g., `PASSAGE-VOL06-05-RD01`, `SECTION-VOL01-01-LS02`).
- **Key Attributes:** `test_id`, `skill`, `sequence_number`, `title`, `subtitle`, `narrative_text`, `paragraphs`, `word_count`, `quality_profile`, `_provenance`.

#### 3.2.3 `QuestionGroup`
- **Definition:** Cluster of questions sharing instructions and rubrics.
- **Primary Key:** `group_id` (e.g., `QG-VOL06-05-RD01-G01`).
- **Key Attributes:** `passage_id` (nullable for standalone group), `start_question_number`, `end_question_number`, `question_type`, `instruction_text`, `word_limit_rule`, `shared_options`, `quality_profile`, `_provenance`.

#### 3.2.4 `Question`
- **Definition:** Individual test item presenting a specific task or proposition.
- **Primary Key:** `question_id` (e.g., `Q-VOL06-05-RD-001`).
- **Key Attributes:** `group_id`, `passage_id` (nullable for standalone question), `question_number`, `question_type`, `prompt_text`, `options`, `blank_target`, `linked_principle_ids`, `quality_profile`, `_provenance`.

#### 3.2.5 `Answer`
- **Definition:** Ground truth solution for a test question.
- **Primary Key:** `answer_id` (e.g., `ANS-VOL06-05-RD-001-KEY`).
- **Key Attributes:** `question_id` (**nullable** for orphan answer keys), `target_value` (**nullable** when answer key is unrecorded/missing), `acceptable_alternates`, `case_sensitive`, `source_key_ref`, `quality_profile`, `_provenance`.

#### 3.2.6 `Evidence`
- **Definition:** Textual proof, contradictory counter-claim, or insufficient-information rationale supporting an answer.
- **Primary Key:** `evidence_id` (e.g., `EVID-VOL06-05-RD-001-01`).
- **Key Attributes:**
  - `answer_id` (nullable for unlinked evidence), `passage_id` (nullable if unlinked).
  - `evidence_type`: `direct_support`, `contradictory_evidence`, or `insufficient_information_not_given`.
  - `verbatim_quote`: String for positive proof or contradiction; **null for NOT GIVEN**.
  - `char_start`, `char_end`: Offsets in passage text; **null for NOT GIVEN**.
  - `missing_information_rationale`: Explicit justification for NOT GIVEN items.
  - `quality_profile`, `_provenance`.

#### 3.2.7 `Explanation`
- **Definition:** Pedagogical rationale and distractor analysis.
- **Primary Key:** `explanation_id` (e.g., `EXPL-VOL06-05-RD-001`).
- **Key Attributes:** `question_id`, `answer_id` (nullable), `evidence_id` (nullable), `rationale_en`, `rationale_vi`, `paraphrase_map`, `distractor_notes`, `author_type`, `quality_profile`, `_provenance`.

---

### 3.3 Learning Knowledge Domain

#### 3.3.1 `Principle`
- **Definition:** Atomic reusable cognitive strategy or rule (stored as Markdown in `principles/`).
- **Primary Key:** `principle_id` (e.g., `RD-TFNG-001`, `RD-MI-001`, `RD-CORE-001`).
- **Key Attributes:** `id`, `title`, `type` (`principle`, `strategy`, `workflow`, `heuristic`), `skill` (`reading`, `listening`, `writing`, `speaking`, `general`), `question_types` (array, can be empty), `triggers` (array), `dependencies` (array), `status` (`draft`, `reviewed`, `verified`), `source_refs`.

#### 3.3.2 `Vocabulary` & `Collocation`
- **Primary Key:** `item_id` (e.g., `VOC-ACAD-00001`, `COL-ACAD-00001`).
- **Key Attributes:** `lemma_or_expression`, `pos`, `cambridge_us_ipa`, `meaning_vi`, `cefr_level`, `context_sentence_en`, `collocations`, `quality_profile`, `_provenance`.

---

## 4. Referential Integrity & Nullable Foreign Keys

| Entity | Field | Nullable? | Reason / Handling Rule |
|---|---|---|---|
| `Answer` | `question_id` | **YES** | Accommodates orphaned answer keys (e.g. VOL 7 Reading Key `SRC-151` where question booklet is missing). Flagged `ORPHAN_ANSWER_KEY_UNLINKED`. |
| `Answer` | `target_value` | **YES** | Accommodates questions where answer key is missing or cut off in source. Flagged `MISSING_SOURCE_ANSWER_KEY`. |
| `Question` | `passage_id` | **YES** | Accommodates standalone test prompts (e.g. Writing/Speaking prompts). |
| `Evidence` | `answer_id` | **YES** | Accommodates unlinked evidence excerpts extracted from reading lessons. |
| `Evidence` | `verbatim_quote` | **YES** | **Null for `insufficient_information_not_given`** to avoid fabricating quotes for NOT GIVEN items. |
| `Explanation` | `answer_id` | **YES** | Accommodates explanations where answer key is unlinked or pending verification. |
| `Explanation` | `evidence_id` | **YES** | Accommodates explanations pending textual anchoring. |
