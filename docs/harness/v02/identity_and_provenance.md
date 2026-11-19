# IELTS Data Harness V0.2 — Identity Design & Provenance Architecture
**Phase V0.2-A: Schema Design & Normalization Contract**  
**Status:** Architectural Blueprint (Design Only)  
**Author:** IELTS Learning Systems Engineer & Data Architecture Team  
**Date:** 2026-11-19  

---

## 1. The Multi-Tier Identity Problem

In an IELTS data engineering pipeline, a simplistic auto-incrementing ID (`1`, `2`, `3`) or random UUID (`a7e2b...`) is completely inadequate:
1. **Lack of Semantic Meaning:** UUIDs obscure the volume, test number, skill, and question sequence.
2. **Fragility Under Re-runs:** Random UUIDs break relational foreign keys and git diffs every time normalization is re-executed.
3. **Confusion Between Physical & Logical Entities:** A single physical file (e.g. `SRC-138`, `VOL 6.docx`) contains 6 distinct logical tests. Conversely, two identical audio tracks (`AudioTrack 01.mp3` in VOL 1 vs. an unzipped backup) share the same SHA-256 but may serve different test contexts.

Phase V0.2-A establishes a **strictly deterministic, hierarchical, human-readable, and stable identification system** that preserves full backward compatibility with Phase V0.1 while ensuring reproducible re-normalization.

---

## 2. Deterministic Identifier Hierarchy

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ TIER 1: PHYSICAL SOURCE FILE ID                                                │
│ Format: SRC-{NNN}                                                              │
│ Example: SRC-011, SRC-138, SRC-077                                             │
│ Scope: Stable primary key in sources table; identifies an immutable file on disk│
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       │
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ TIER 2: LOGICAL DOCUMENT ID                                                    │
│ Format: DOC-{COLLECTION_SLUG}-{FILENAME_SLUG}                                  │
│ Example: DOC-VOL06-READING-VOL6-DOCX                                           │
│ Scope: Represents the document entity within its pedagogical collection        │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       │
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ TIER 3: LOGICAL TEST ID                                                        │
│ Format: TEST-IELTS-{VOLUME}-{TEST_NUM}-{TRACK}                                 │
│ Example: TEST-IELTS-VOL06-05-ACAD                                              │
│ Scope: Represents a complete 4-skill or single-skill IELTS examination paper   │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       │
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ TIER 4: PASSAGE OR SECTION ID                                                  │
│ Format: PASSAGE-{TEST_SLUG}-{SKILL_PREFIX}{NN}                                 │
│ Example: PASSAGE-VOL06-05-RD01, SECTION-VOL01-01-LS02                          │
│ Scope: Reading Passage (1, 2, 3) or Listening Section (1, 2, 3, 4)             │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       │
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ TIER 5: QUESTION GROUP ID                                                      │
│ Format: QG-{PASSAGE_SLUG}-G{NN}                                                │
│ Example: QG-VOL06-05-RD01-G01                                                  │
│ Scope: Sequence of questions sharing rubrics/instructions (e.g. Q1-6 T/F/NG)   │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       │
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ TIER 6: ATOMIC QUESTION ID                                                     │
│ Format: Q-{TEST_SLUG}-{SKILL_PREFIX}-{NNN}                                     │
│ Example: Q-VOL06-05-RD-001, Q-VOL01-01-LS-014                                  │
│ Scope: Global unique identifier for a specific test item (1 to 40)             │
└───────┬──────────────────────────────┼─────────────────────────────────┬───────┘
        │                              │                                 │
        ▼                              ▼                                 ▼
┌─────────────────────┐      ┌─────────────────────┐      ┌──────────────────────┐
│ TIER 7: ANSWER ID   │      │ TIER 8: EVIDENCE ID │      │ TIER 9: EXPLANATION  │
│ Format:             │      │ Format:             │      │ Format:              │
│ ANS-{Q_ID}-KEY      │      │ EVID-{Q_ID}-{NN}    │      │ EXPL-{Q_ID}-{SOURCE} │
│ Example:            │      │ Example:            │      │ Example:             │
│ ANS-VOL06-05-RD-001 │      │ EVID-VOL06-05-RD-001│      │ EXPL-VOL06-05-RD-001 │
└─────────────────────┘      └─────────────────────┘      └──────────────────────┘
```

---

## 3. ID Minting Rules & Syntax Specifications

### 3.1 Tier 1: Physical File ID (`source_file_id`)
- **Format:** `^SRC-\d{3,4}$`
- **Origin:** Retained directly from V0.1 SQLite `sources.file_id` and `source_inventory.csv`.
- **Invariance:** Never renumbered. If a file is relocated on disk, `file_id` remains unchanged.

### 3.2 Tier 2: Logical Document ID (`doc_id`)
- **Format:** `DOC-[A-Z0-9]+(-[A-Z0-9]+)*`
- **Minting Rule:** Uppercase sanitization of parent collection + filename slug.
- **Example:** `private/raw/VOL 6/READING/VOL 6.docx` $\to$ `DOC-VOL06-READING-VOL6-DOCX`.

### 3.3 Tier 3: Test ID (`test_id`)
- **Format:** `TEST-IELTS-(VOL\d{2}|CAMB\d{2}|OG)-(\d{2})-(ACAD|GT)`
- **Minting Rule:**
  - `VOL\d{2}`: Two-digit volume number from collection directory.
  - `\d{2}`: Two-digit test number parsed from section headers (e.g. `TEST 5` $\to$ `05`).
  - `ACAD|GT`: Academic or General Training.
- **Example:** `TEST-IELTS-VOL06-05-ACAD`.

### 3.4 Tier 4: Passage / Section ID (`passage_id`)
- **Format:** `PASSAGE-(VOL\d{2})-(\d{2})-RD(\d{2})` for Reading.  
  `SECTION-(VOL\d{2})-(\d{2})-LS(\d{2})` for Listening.
- **Minting Rule:** Combines volume, test number, and zero-padded sequence (01, 02, 03).
- **Example:** `PASSAGE-VOL06-05-RD01` (Volume 6, Test 5, Reading Passage 1).

### 3.5 Tier 5: Question Group ID (`group_id`)
- **Format:** `QG-(VOL\d{2})-(\d{2})-RD(\d{2})-G(\d{2})`
- **Minting Rule:** Appends zero-padded group sequence number within the passage.
- **Example:** `QG-VOL06-05-RD01-G01` (Questions 1–6 in Passage 1).

### 3.6 Tier 6: Atomic Question ID (`question_id`)
- **Format:** `Q-(VOL\d{2})-(\d{2})-(RD|LS|WR|SP)-(\d{3})`
- **Minting Rule:** Skill abbreviation + three-digit zero-padded question number (001 to 040).
- **Example:** `Q-VOL06-05-RD-001` (Question 1 in Test 5 Reading).

### 3.7 Tier 7: Answer ID (`answer_id`)
- **Format:** `ANS-{question_id}-KEY` (for official key), `ANS-{question_id}-ALT{NN}` (for alternates).
- **Example:** `ANS-Q-VOL06-05-RD-001-KEY`.

### 3.8 Tier 8: Evidence ID (`evidence_id`)
- **Format:** `EVID-{question_id}-{NN}`
- **Minting Rule:** Sequential zero-padded counter for evidence snippets supporting the answer.
- **Example:** `EVID-Q-VOL06-05-RD-001-01`.

### 3.9 Tier 9: Principle ID (`principle_id`)
- **Format:** `^{SKILL_CODE}-{TYPE_CODE}-\d{3}$`
- **Skill Codes:** `RD` (Reading), `LS` (Listening), `WR` (Writing), `SP` (Speaking), `GEN` (General).
- **Type Codes:** `CORE`, `TFNG`, `MI`, `MH`, `PLAN`, `VOC`.
- **Status:** Inherits existing stable IDs from `principles/INDEX.md` (e.g. `RD-TFNG-001`, `RD-MI-001`).
- **Rule:** Never renumber or deprecate an existing principle ID.

---

## 4. Disambiguation Rules: Physical Clones vs. Logical Context

A fundamental data engineering pitfall discovered during V0.1 discovery is that identical physical files (exact SHA-256 match) can appear in multiple locations:

| Scenario | Physical Reality | Logical Identity Resolution Rule |
|---|---|---|
| **Exact Audio Clones** | `AudioTrack 01.mp3` appears in both `VOL 1/TEST 1/` and a nested backup folder. | Inspect source directory. If both point to the same test, assign one canonical `file_id` and map duplicates in SQLite `sources.duplicate_group`. Do not create duplicate logical tests. |
| **Omnibus Question Books vs. Split Tests** | `FULL reading vol 2.pdf` (`SRC-064`) contains Tests 1–10 in a single 140-page file. | One physical `file_id` produces 10 logical `test_id`s (`TEST-IELTS-VOL02-01-ACAD` through `10`). The `_provenance` retains `SRC-064` with page ranges (`page_0001` to `page_0014` for Test 1). |
| **Separated Question Paper and Key Files** | Questions reside in `SRC-138` (DOCX), while keys reside in `SRC-137` (scanned PDF). | Entities preserve dual provenance. `Question` points to `SRC-138`; `Answer` points to `SRC-137`. They join on logical `question_id`. |

---

## 5. The Standard Provenance Envelope Specification

To satisfy the non-negotiable requirement of backward traceability to V0.1, every normalized JSON entity must serialize an identical `_provenance` block:

```json
{
  "_provenance": {
    "schema_version": "v0.2.0-normalized",
    "source_file_id": "SRC-138",
    "source_legacy_id": "SRC-138",
    "relative_path": "private/raw/VOL 6/READING/VOL 6.docx",
    "source_sha256": "3a7f8090a7864f1c95697241cfb26ad0ffcf56a7c36a6ec65cf1f3c3a9f061b1",
    "processing_unit": "document",
    "unit_identifier": "raw_document",
    "raw_block_locator": "para_index:309",
    "extractor_adapter": "docx",
    "extractor_version": "0.1.0-lxml-docx",
    "normalizer_version": "0.2.0-alpha",
    "normalized_at": "2026-11-19T14:30:00Z"
  }
}
```

This guarantees that any tutoring explanation, quiz question, or band estimate presented to the user can be immediately audited against the exact physical bytes and paragraph in the original file.
