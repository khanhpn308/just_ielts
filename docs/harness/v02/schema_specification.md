# IELTS Data Harness V0.2 — Schema Specification & Data Dictionaries
**Phase V0.2-A: Schema Design & Normalization Contract**  
**Status:** Architectural Blueprint (Design Only)  
**Author:** IELTS Learning Systems Engineer & Data Architecture Team  
**Date:** 2026-11-19  

---

## 1. Global Standards & Envelopes

Every normalized JSON record produced in Phase V0.2 adheres to standard JSON Schema (Draft 2020-12 / Draft 7 compatible) and must include a standardized **Provenance Envelope** and **Quality Metadata** block.

### 1.1 The Standard Provenance Envelope (`_provenance`)
All normalized learning records must encapsulate their extraction roots:

| Field Name | Type | Constraint | Description | Example |
|---|---|---|---|---|
| `schema_version` | `string` | Required | Semantic version of the normalized schema | `"v0.2.0-normalized"` |
| `source_file_id` | `string` | Required, Pattern: `^SRC-\d{3}$` | Primary key of physical file from V0.1 inventory | `"SRC-138"` |
| `source_sha256` | `string` | Required, 64-char Hex | Cryptographic SHA-256 of the raw file at ingestion | `"3a7f8...b1"` |
| `processing_unit` | `string` | Required, Enum | Partition type processed in V0.1 | `"document"`, `"page"`, `"sheets"` |
| `unit_identifier` | `string` | Required | Specific partition unit identifier | `"raw_document"`, `"page_0001"` |
| `raw_block_locator` | `string` | Required | Locator within the raw unit (e.g. paragraph index, sheet cell, line number) | `"para_index:309"`, `"cell:B3"` |
| `extractor_name` | `string` | Required | Adapter name from V0.1 | `"docx"`, `"pdf_ocr"`, `"xlsx"` |
| `extractor_version` | `string` | Required | Version tag of extraction adapter | `"0.1.0-lxml-docx"` |
| `normalizer_version`| `string` | Required | Version tag of normalization logic | `"0.2.0-alpha"` |
| `normalized_at` | `string` | Required, ISO 8601 UTC | Timestamp of normalization run | `"2026-11-19T14:30:00Z"` |

---

## 2. Controlled Vocabularies & Enumerations

### 2.1 IELTS Skill Enumeration
```json
["reading", "listening", "writing", "speaking"]
```

### 2.2 Question Types Enumeration (`question_type`)
```json
[
  "true-false-not-given",
  "yes-no-not-given",
  "multiple-choice-single",
  "multiple-choice-multi",
  "matching-information",
  "matching-headings",
  "matching-features",
  "matching-sentence-endings",
  "sentence-completion",
  "summary-completion",
  "note-completion",
  "table-completion",
  "flow-chart-completion",
  "diagram-label-completion",
  "short-answer"
]
```

### 2.3 Word Limit Constraints (`word_limit_rule`)
```json
[
  "one_word_only",
  "no_more_than_two_words",
  "no_more_than_three_words",
  "one_word_and_or_a_number",
  "no_more_than_two_words_and_or_a_number",
  "no_more_than_three_words_and_or_a_number",
  "a_number",
  "letters_only"
]
```

### 2.4 Writing Task Types (`task_type`)
```json
[
  "task1_line_graph",
  "task1_bar_chart",
  "task1_pie_chart",
  "task1_table",
  "task1_process_diagram",
  "task1_map_comparison",
  "task1_multiple_charts",
  "task2_agree_disagree",
  "task2_discuss_both_views",
  "task2_advantages_disadvantages",
  "task2_problem_solution",
  "task2_two_part_question"
]
```

### 2.5 Speaking Part Types (`speaking_part`)
```json
[
  "part1_interview",
  "part2_long_turn",
  "part3_discussion"
]
```

---

## 3. Data Dictionaries: Question Bank Entities

### 3.1 Entity: `Test`
Represents an authentic examination booklet or past paper.

| Field Name | Type | Nullable | Constraints | Description |
|---|---|---|---|---|
| `test_id` | `string` | No | Primary Key, Pattern: `^TEST-IELTS-[A-Z0-9]+-\d{2}-[A-Z]+$` | Unique deterministic test ID (e.g. `TEST-IELTS-VOL01-01-ACAD`) |
| `title` | `string` | No | Min 5 chars | Human-readable test title (e.g. `"IELTS Practice Test 1 (Academic)"`) |
| `volume` | `string` | No | Identifier | Volume reference (e.g. `"VOL_01"`, `"CAMBRIDGE_18"`) |
| `test_number` | `integer` | No | $1 \le N \le 20$ | Sequential test number within volume |
| `track` | `string` | No | Enum: `["academic", "general_training"]` | IELTS candidate track |
| `source_reference_id` | `string` | Yes | Foreign Key | Link to `SourceReference` |
| `sections_present` | `array[string]`| No | Subset of skills | Array of available components: `["reading", "listening", "writing"]` |
| `verification_status`| `string` | No | Quality Status Enum | Overall test integrity status |
| `_provenance` | `object` | No | Standard Envelope | Originating document metadata |

---

### 3.2 Entity: `PassageOrSection`
Represents Reading Passages 1–3 or Listening Sections 1–4.

| Field Name | Type | Nullable | Constraints | Description |
|---|---|---|---|---|
| `passage_id` | `string` | No | Primary Key, Pattern: `^PASSAGE-[A-Z0-9-]+-RD\d{2}$` | Unique identifier (e.g. `PASSAGE-VOL01-01-RD01`) |
| `test_id` | `string` | No | Foreign Key $\to$ `Test.test_id` | Associated test |
| `skill` | `string` | No | Enum: `["reading", "listening"]` | Examination skill |
| `sequence_number`| `integer` | No | $1 \le N \le 4$ | Passage 1, 2, 3 or Section 1, 2, 3, 4 |
| `title` | `string` | No | Min 1 char | Passage title (e.g. `"The development of the silk industry"`) |
| `subtitle` | `string` | Yes | Optional | Accompanying teaser or context sentence |
| `narrative_text`| `string` | No | Min 100 chars | Full normalized body text |
| `paragraphs` | `array[object]`| No | Min 1 element | Ordered list of paragraph objects (see schema below) |
| `audio_track_ref`| `string` | Yes | Null for Reading | Physical audio track identifier for Listening |
| `word_count` | `integer` | No | $300 \le N \le 1500$ | Total body word count |
| `_provenance` | `object` | No | Standard Envelope | Raw extraction block reference |

#### Sub-Schema: `Paragraph` Object
```json
{
  "label": "A",
  "sequence_index": 0,
  "char_start": 0,
  "char_end": 742,
  "text": "Silk is a fine, smooth material produced from the cocoons of silkworms..."
}
```

---

### 3.3 Entity: `QuestionGroup`
Represents an instruction block covering a sequence of questions.

| Field Name | Type | Nullable | Constraints | Description |
|---|---|---|---|---|
| `group_id` | `string` | No | Primary Key, Pattern: `^QG-[A-Z0-9-]+-G\d{2}$` | Unique identifier (e.g. `QG-VOL01-01-RD01-G01`) |
| `passage_id` | `string` | No | Foreign Key $\to$ `PassageOrSection.passage_id` | Parent passage/section |
| `start_question_number`| `integer` | No | $1 \le N \le 40$ | First question number in group (e.g. 1) |
| `end_question_number` | `integer` | No | $1 \le N \le 40, N \ge start$ | Last question number in group (e.g. 6) |
| `question_type` | `string` | No | Question Type Enum | Normalized question type |
| `instruction_text` | `string` | No | Min 5 chars | Verbatim instruction header (e.g. `"Do the following statements agree..."`) |
| `word_limit_rule` | `string` | Yes | Word Limit Enum | Normalized limit rule (null for T/F/NG and MCQ) |
| `shared_options` | `array[object]`| Yes | Array of `{"label": "A", "text": "..."}` | Options bank for Matching Headings/Features |
| `_provenance` | `object` | No | Standard Envelope | Originating extraction block |

---

### 3.4 Entity: `Question`
Represents a single atomic question item.

| Field Name | Type | Nullable | Constraints | Description |
|---|---|---|---|---|
| `question_id` | `string` | No | Primary Key, Pattern: `^Q-[A-Z0-9-]+-RD-\d{3}$` | Unique identifier (e.g. `Q-VOL01-01-RD-001`) |
| `group_id` | `string` | No | Foreign Key $\to$ `QuestionGroup.group_id` | Parent instruction group |
| `passage_id` | `string` | No | Foreign Key $\to$ `PassageOrSection.passage_id` | Parent passage |
| `question_number`| `integer`| No | $1 \le N \le 40$ | Official question sequence number |
| `question_type` | `string` | No | Question Type Enum | Inherited or specialized question type |
| `prompt_text` | `string` | No | Min 3 chars | Proposition or sentence with blank |
| `options` | `object` | Yes | Keys `["A", "B", ...]` | Distractor options for MCQ |
| `blank_target` | `string` | Yes | e.g. `"{{BLANK_1}}"` | Placeholder token inside `prompt_text` for completion questions |
| `linked_principle_ids`| `array[string]`| No | List of principle IDs | Associated pedagogical strategies (e.g. `["RD-TFNG-001"]`) |
| `_provenance` | `object` | No | Standard Envelope | Block locator where question was parsed |

---

### 3.5 Entity: `Answer`
Represents ground-truth solution(s) for a question.

| Field Name | Type | Nullable | Constraints | Description |
|---|---|---|---|---|
| `answer_id` | `string` | No | Primary Key, Pattern: `^ANS-[A-Z0-9-]+-KEY$` | Unique answer record identifier |
| `question_id` | `string` | No | Foreign Key $\to$ `Question.question_id` | Associated test question |
| `target_value` | `string` | No | Min 1 char | Authoritative primary answer string (e.g. `"TRUE"`, `"white"`) |
| `acceptable_alternates`| `array[string]`| No | Default `[]` | Valid variations (e.g. `["FALSE", "F"]` or `["centre", "center"]`) |
| `case_sensitive` | `boolean`| No | Default `false` | Case distinction rule |
| `verification_status`| `string` | No | Enum: `["authoritative_key", "consensus_key", "unverified", "disputed"]` | Truth classification |
| `source_key_ref` | `string` | No | Document locator | Physical page or cell where key was published |
| `_provenance` | `object` | No | Standard Envelope | Provenance linking to key source |

---

### 3.6 Entity: `Evidence`
Represents the exact grounding proof for an answer.

| Field Name | Type | Nullable | Constraints | Description |
|---|---|---|---|---|
| `evidence_id` | `string` | No | Primary Key, Pattern: `^EVID-[A-Z0-9-]+-\d{2}$` | Unique evidence identifier |
| `answer_id` | `string` | No | Foreign Key $\to$ `Answer.answer_id` | Associated answer |
| `passage_id` | `string` | No | Foreign Key $\to$ `PassageOrSection.passage_id` | Passage containing evidence |
| `paragraph_label`| `string`| Yes | e.g. `"A"`, `"B"`, `"Paragraph 3"` | Paragraph identifier |
| `char_start` | `integer`| Yes | $0 \le N$ | Character offset in passage narrative |
| `char_end` | `integer`| Yes | $N \ge char\_start$ | Character offset end |
| `verbatim_quote` | `string` | No | Min 3 chars | Quoted sentence or clause from text |
| `exact_match_verified`| `boolean`| No | Default `false` | True if quote exists verbatim in passage text |
| `audio_interval` | `object` | Yes | Keys: `start_sec`, `end_sec` | Timestamp bounds for Listening items |
| `_provenance` | `object` | No | Standard Envelope | Originating source locator |

---

### 3.7 Entity: `Explanation`
Represents the pedagogical rationale and distractor analysis.

| Field Name | Type | Nullable | Constraints | Description |
|---|---|---|---|---|
| `explanation_id`| `string` | No | Primary Key, Pattern: `^EXPL-[A-Z0-9-]+$` | Unique explanation identifier |
| `question_id` | `string` | No | Foreign Key $\to$ `Question.question_id` | Associated question |
| `answer_id` | `string` | No | Foreign Key $\to$ `Answer.answer_id` | Associated answer |
| `evidence_id` | `string` | Yes | Foreign Key $\to$ `Evidence.evidence_id` | Associated evidence anchor |
| `rationale_en` | `string` | Yes | English explanation | Technical explanation in English |
| `rationale_vi` | `string` | Yes | Vietnamese explanation | Teaching explanation in Vietnamese |
| `paraphrase_map`| `array[object]`| No | List of `{"prompt_term": "...", "passage_term": "..."}` | Explicit lexical connections |
| `distractor_notes`| `string`| Yes | Optional | Explanation of why alternative choices fail |
| `author_type` | `string` | No | Enum: `["source_published", "expert_teacher", "machine_drafted"]` | Origin of explanation |
| `verification_status`| `string`| No | Quality Status Enum | Pedagogical review status |
| `_provenance` | `object` | No | Standard Envelope | Document/Page citation |

---

## 4. Data Dictionaries: Learning Knowledge Entities

### 4.1 Principle Frontmatter Schema (`PrincipleMetadata`)
Governs the YAML frontmatter of Markdown files in `principles/`:

| Field Name | Type | Nullable | Constraints | Description |
|---|---|---|---|---|
| `id` | `string` | No | Pattern: `^[A-Z]{2}-[A-Z]{2,4}-\d{3}$` | Permanent principle ID (e.g. `RD-TFNG-001`) |
| `title` | `string` | No | Min 5 chars | Concise principle title |
| `type` | `string` | No | Enum: `["principle", "strategy", "heuristic"]` | Classification |
| `skill` | `string` | No | Skill Enum | Applicable skill |
| `question_types`| `array[string]`| No | Min 1 Question Type Enum | Applicable question types |
| `triggers` | `array[string]`| No | Min 1 Error Code | Observable learner error codes |
| `dependencies` | `array[string]`| No | List of Principle IDs | Prerequisite principles |
| `status` | `string` | No | Enum: `["draft", "reviewed", "verified"]` | Authority status |
| `source_refs` | `array[string]`| No | List of Source IDs or citations | Source citations |

---

### 4.2 Entity: `VocabularyItem` & `CollocationItem`

| Field Name | Type | Nullable | Constraints | Description |
|---|---|---|---|---|
| `vocab_id` | `string` | No | Pattern: `^VOC-[A-Z]+-\d{5}$` | Permanent vocabulary ID |
| `lemma` | `string` | No | Dictionary base form | Headword in English |
| `pos` | `string` | No | Enum: `["n", "v", "adj", "adv", "phrase"]` | Part of speech |
| `cambridge_us_ipa`| `string`| No | Cambridge dictionary format | Pronunciation key (US English) |
| `meaning_vi` | `string` | No | Vietnamese explanation | Clear Vietnamese translation & explanation |
| `cefr_level` | `string` | No | Enum: `["B1", "B2", "C1", "C2"]` | Target proficiency band |
| `context_sentence_en`| `string`| No | Authentic example | Sentence extracted from IELTS source |
| `collocations` | `array[string]`| No | List of word combinations | High-frequency collocations |
| `source_passage_id` | `string`| Yes | Foreign Key | Grounding passage |
