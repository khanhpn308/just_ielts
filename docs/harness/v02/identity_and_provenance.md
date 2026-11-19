# IELTS Data Harness V0.2 — Identity Design & Provenance Architecture
**Phase V0.2-A: Schema Design & Normalization Contract (Remediated)**  
**Status:** Architectural Blueprint (Design Only)  
**Author:** IELTS Learning Systems Engineer & Data Architecture Team  
**Date:** 2026-11-19 (Remediated)  

---

## 1. The Multi-Tier Identity Problem

In an IELTS data engineering pipeline, random UUIDs or simple integer counters break provenance and relational integrity:
1. **Lack of Domain Semantics:** UUIDs obscure the volume, test number, skill, and question sequence.
2. **Fragility Under Re-runs:** Ephemeral IDs cause spurious diffs across normalization re-runs.
3. **Conflation of Physical vs. Logical Layers:** A physical file (e.g. `FILE-3a7f8090a786`, `VOL 6.docx`) contains multiple logical tests. Conversely, binary clones (same SHA-256) may exist across multiple folders.

Phase V0.2 establishes a **strictly deterministic, hierarchical, human-readable, and stable identification system** aligning 100% with Phase V0.1 source inventory.

---

## 2. Deterministic Identifier Hierarchy

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ TIER 1: PHYSICAL SOURCE FILE ID                                                │
│ Primary Key: sources.file_id = FILE-[a-f0-9]{12}                               │
│ Legacy Alias: sources.legacy_id = SRC-{NNN}                                    │
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
│ Scope: Global unique identifier for a specific test item (001 to 040)          │
└───────┬──────────────────────────────┼─────────────────────────────────┬───────┘
        │                              │                                 │
        ▼                              ▼                                 ▼
┌─────────────────────┐      ┌─────────────────────┐      ┌──────────────────────┐
│ TIER 7: ANSWER ID   │      │ TIER 8: EVIDENCE ID │      │ TIER 9: EXPLANATION  │
│ Format:             │      │ Format:             │      │ Format:              │
│ ANS-{Q_ID}-KEY      │      │ EVID-{Q_ID}-{NN}    │      │ EXPL-{Q_ID}          │
│ Example:            │      │ Example:            │      │ Example:             │
│ ANS-VOL06-05-RD-001 │      │ EVID-VOL06-05-RD-001│      │ EXPL-VOL06-05-RD-001 │
└─────────────────────┘      └─────────────────────┘      └──────────────────────┘
```

---

## 3. ID Minting Rules & Syntax Specifications

### 3.1 Tier 1: Physical File ID & Legacy Mapping
- **Physical File ID:** `^FILE-[a-f0-9]{12}$`
  - Minted in V0.1 via: `f"FILE-{hashlib.sha256(relative_path.encode()).hexdigest()[:12]}"`.
  - Immutable primary key in `sources` table.
- **Legacy Source ID:** `^SRC-\d{3,4}$` (or `"UNKNOWN"`).
  - Authoritative reference matching Phase 0 discovery reports and inventory tables.

### 3.2 Tier 2: Logical Document ID (`doc_id`)
- **Format:** `DOC-[A-Z0-9]+(-[A-Z0-9]+)*`
- **Example:** `private/raw/VOL 6/READING/VOL 6.docx` $\to$ `DOC-VOL06-READING-VOL6-DOCX`.

### 3.3 Tier 3: Test ID (`test_id`)
- **Format:** `^TEST-IELTS-(VOL\d{2}|CAMB\d{2}|OG)-(\d{2})-(ACAD|GT)$`
- **Example:** `TEST-IELTS-VOL06-05-ACAD`.

### 3.4 Tier 4: Passage / Section ID (`passage_id`)
- **Format:** `PASSAGE-(VOL\d{2})-(\d{2})-RD(\d{2})` for Reading.  
  `SECTION-(VOL\d{2})-(\d{2})-LS(\d{2})` for Listening.
- **Example:** `PASSAGE-VOL06-05-RD01`.

### 3.5 Tier 5: Question Group ID (`group_id`)
- **Format:** `QG-(VOL\d{2})-(\d{2})-RD(\d{2})-G(\d{2})`
- **Example:** `QG-VOL06-05-RD01-G01`.

### 3.6 Tier 6: Atomic Question ID (`question_id`)
- **Format:** `Q-(VOL\d{2})-(\d{2})-(RD|LS|WR|SP)-(\d{3})`
- **Example:** `Q-VOL06-05-RD-001`.

### 3.7 Tier 7: Answer ID (`answer_id`)
- **Format:** `ANS-(VOL\d{2})-(\d{2})-(RD|LS|WR|SP)-(\d{3})-(KEY|ALT\d{2})`
- **Example:** `ANS-VOL06-05-RD-001-KEY`.

### 3.8 Tier 8: Evidence ID (`evidence_id`)
- **Format:** `EVID-(VOL\d{2})-(\d{2})-(RD|LS|WR|SP)-(\d{3})-(\d{2})`
- **Example:** `EVID-VOL06-05-RD-001-01`.

### 3.9 Tier 9: Explanation ID (`explanation_id`)
- **Format:** `EXPL-(VOL\d{2})-(\d{2})-(RD|LS|WR|SP)-(\d{3})`
- **Example:** `EXPL-VOL06-05-RD-001`.

### 3.10 Tier 10: Principle ID (`principle_id`)
- **Format:** `^[A-Z]{2}-[A-Z0-9]+-\d{3}$`
- **Example:** `RD-TFNG-001`, `RD-MI-001`, `RD-CORE-001`.
- **Status:** Preserves 100% compatibility with existing principles in `principles/INDEX.md`.

---

## 4. The Standard Provenance Envelope Specification

```json
{
  "_provenance": {
    "schema_version": "v0.2.0-normalized",
    "source_file_id": "FILE-3a7f8090a786",
    "source_legacy_id": "SRC-138",
    "relative_path": "private/raw/VOL 6/READING/VOL 6.docx",
    "source_sha256": "3a7f8090a7864f1c95697241cfb26ad0ffcf56a7c36a6ec65cf1f3c3a9f061b1",
    "processing_unit": "document",
    "unit_identifier": "raw_document",
    "raw_block_locator": "para_index:309",
    "extractor_adapter": "docx",
    "extractor_version": "0.1.0-lxml-docx",
    "normalizer_version": "0.2.0-alpha",
    "canonical_content_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "normalized_at": null
  }
}
```
