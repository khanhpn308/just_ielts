# IELTS Data Harness V0.2 — System Architecture Specification
**Phase V0.2-A: Schema Design & Normalization Contract**  
**Status:** Architectural Blueprint (Design Only)  
**Author:** IELTS Learning Systems Engineer & Data Architecture Team  
**Date:** 2026-11-19  

---

## 1. Executive Summary & Evolutionary Context

### 1.1 The V0.1 Baseline
In Phase V0.1, the IELTS Data Harness solved the physical extraction challenge across heterogeneous source materials (scanned PDF, digital PDF, OpenXML DOCX, OpenXML XLSX, and MP3 audio). V0.1 implemented:
- Read-only scanning and deterministic SHA-256 source inventory (`private/raw/`).
- Format detection and classifier routing.
- Granular per-page, per-sheet, and per-document extraction adapters (`PdfNativeExtractor`, `PdfOcrExtractor`, `DocxExtractor`, `XlsxExtractor`, `AudioMetaExtractor`).
- SQLite transactional checkpoint/resume engine (`harness/state/harness.db`).
- Checksummed raw extraction staging (`private/staging/raw_extracted/`) preserving 100% extraction provenance.

### 1.2 The V0.2 Mandate
Physical extraction is not learning data. Raw JSON dumps contain noise, OCR artifacts, unstructured text runs, fragmented tables, and disconnected answer keys. Phase V0.2 bridges the gap between raw data dumps and an atomic, verifiable IELTS Knowledge Base and Question Bank.

Phase V0.2-A establishes the **data architecture, normalized schema specifications, identity rules, quality gates, and normalization contracts** required to transform raw blocks into validated, interconnected learning entities.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           V0.1 PHYSICAL EXTRACTION                              │
│  Raw Files (PDF/DOCX/XLSX/MP3) ──► Extraction Adapters ──► Staged Raw JSON Blocks│
└────────────────────────────────────────┬────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           V0.2 NORMALIZATION PIPELINE                           │
│                                                                                 │
│  ┌─────────────────────────┐      ┌─────────────────────────┐                   │
│  │  Content Segmentation   │ ───► │  Structure Demarcation  │                   │
│  │ (Blocks, Tables, Audio) │      │  (Passage/Section/Task) │                   │
│  └─────────────────────────┘      └────────────┬────────────┘                   │
│                                                │                                │
│                                                ▼                                │
│  ┌─────────────────────────┐      ┌─────────────────────────┐                   │
│  │ Answer Key Reconciler   │ ◄─── │ Question Bank Parser    │                   │
│  │ (Ground Truth & Alts)   │      │ (Groups & Atomic Items) │                   │
│  └────────────┬────────────┘      └─────────────────────────┘                   │
│               │                                                                 │
│               ▼                                                                 │
│  ┌─────────────────────────┐      ┌─────────────────────────┐                   │
│  │ Evidence Span Anchor    │ ───► │ Principle & Explanation │                   │
│  │ (Character/Time Offsets)│      │ Mapper (Pedagogy Link)  │                   │
│  └─────────────────────────┘      └────────────┬────────────┘                   │
└────────────────────────────────────────────────┼────────────────────────────────┘
                                                 │
                                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      VERIFICATION GATES & STORAGE TIERS                         │
│   [Tier 1: Markdown]          [Tier 2: Normalized JSONL]     [Tier 3: SQLite]   │
│  Authoritative Principles      Canonical Learning Entities    Relational Graph  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Three-Tier Storage Architecture

To maintain high data integrity, auditable version control, and low operational complexity, V0.2 establishes a strict three-tier storage model.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ TIER 1: AUTHORITATIVE PEDAGOGICAL CONTENT (Human-Authored Markdown)             │
│ • Location: principles/**/*.md, lessons/**/*.md                                 │
│ • Role: Ground-truth pedagogical strategies, procedures, and learning rules     │
│ • Format: GitHub-flavored Markdown with structured YAML frontmatter             │
│ • Versioning: Tracked natively in Git repository                                │
└─────────────────────────────────────────────────────────────────────────────────┘
                                      ▲
                                      │ Foreign Key (principle_id)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ TIER 2: CANONICAL NORMALIZED DATA (Immutable Structured JSON / JSONL)           │
│ • Location: data/normalized/{tests,passages,questions,answers,evidence}/        │
│ • Role: Source-of-truth machine-readable entity bank                            │
│ • Format: Deterministic JSON Schema-validated files with provenance envelopes   │
│ • Mutability: Append-only or deterministic rebuild via idempotent normalizer    │
└─────────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ ETL Sync / Ingestion
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ TIER 3: DERIVED QUERY & RELATIONSHIP ENGINE (Relational SQLite)                 │
│ • Location: harness/state/harness.db (or data/derived/ielts_knowledge.db)       │
│ • Role: High-speed relational joins, cross-filtering, and integrity validation │
│ • Nature: Strictly derived — reproducible at any time from Tier 1 + Tier 2      │
│ • Features: Foreign Key enforcement (PRAGMA foreign_keys = ON), WAL mode       │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Explicit Rationale: Why Vector Databases Are Excluded in V0.2
Vector databases (e.g., Chroma, Qdrant, Pinecone) are deliberately excluded from the IELTS Data Harness V0.2 architecture for the following structural reasons:
1. **Deterministic Grounding vs. Probabilistic Hallucination:**
   In IELTS Academic tutoring, determining whether an answer is `FALSE` or `NOT GIVEN` depends on precise logical contradiction versus absence of evidence. Vector similarity conflates topical proximity with logical truth. A paragraph discussing the exact keywords with high cosine similarity is often a classic IELTS distractor.
2. **Exact Textual Span & Byte Offset Anchoring:**
   Learning verification requires character-level coordinates (`char_start`, `char_end`) or paragraph-letter coordinates (`Paragraph C, Lines 4–6`). Vector embeddings discard precise boundaries and token positions.
3. **Auditability & Traceability:**
   Every fact, answer key, and explanation must point to an immutable source file (`file_id`), processing unit (`page_0001`), and block index. A vector search result provides no audit trail of ground-truth validity.
4. **Zero Heavy Infrastructure Dependency:**
   In accordance with the repository's lean architecture, SQLite provides $O(1)$ and $O(\log N)$ exact relational and full-text retrieval (via FTS5) with zero cloud services, zero external daemon processes, and negligible storage footprint.

---

## 3. Four-Skill Architectural Support

The V0.2 entity architecture abstracts the core examination domain into universal constructs while accommodating skill-specific modalities:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   CORE TEST ENTITY                                     │
│                                    (test_id)                                           │
└───────┬──────────────────────┬──────────────────────────┬───────────────────────┬──────┘
        │                      │                          │                       │
        ▼                      ▼                          ▼                       ▼
┌───────────────┐      ┌───────────────┐          ┌───────────────┐       ┌───────────────┐
│    READING    │      │   LISTENING   │          │    WRITING    │       │   SPEAKING    │
└───────┬───────┘      └───────┬───────┘          └───────┬───────┘       └───────┬───────┘
        ▼                      ▼                          ▼                       ▼
┌───────────────┐      ┌───────────────┐          ┌───────────────┐       ┌───────────────┐
│ Reading       │      │ Listening     │          │ Writing Task  │       │ Speaking Part │
│ Passage (1-3) │      │ Section (1-4) │          │ Prompt (1-2)  │       │ Topic (1-3)   │
└───────┬───────┘      └───────┬───────┘          └───────┬───────┘       └───────┬───────┘
        │                      │                          │                       │
        │ Text                 │ Audio Stream             │ Prompt Analysis       │ Cue Card
        │ Blocks               │ + Transcript             │ + Data Graphics       │ + Prompt Ideas
        ▼                      ▼                          ▼                       ▼
┌───────────────┐      ┌───────────────┐          ┌───────────────┐       ┌───────────────┐
│ Question      │      │ Question      │          │ Essay Plan /  │       │ Model Speech  │
│ Group (Q1-13) │      │ Group (Q1-10) │          │ Outline       │       │ Script        │
└───────┬───────┘      └───────┬───────┘          └───────┬───────┘       └───────┬───────┘
        ▼                      ▼                          ▼                       ▼
┌───────────────┐      ┌───────────────┐          ┌───────────────┐       ┌───────────────┐
│ Atomic        │      │ Atomic        │          │ Model Essay   │       │ Audio Cue /   │
│ Question Item │      │ Question Item │          │ (Band 7.5+)   │       │ Sample Audio  │
└───────┬───────┘      └───────┬───────┘          └───────┬───────┘       └───────┬───────┘
        ▼                      ▼                          ▼                       ▼
┌───────────────┐      ┌───────────────┐          ┌───────────────┐       ┌───────────────┐
│ Answer Key    │      │ Answer Key    │          │ Criterion     │       │ Criterion     │
│ & Alternates  │      │ & Alternates  │          │ Assessment    │       │ Assessment    │
└───────┬───────┘      └───────┬───────┘          │ (TR/CC/LR/GRA)│       │ (FC/PR/LR/GRA)│
        ▼                      ▼                  └───────┬───────┘       └───────┬───────┘
┌───────────────┐      ┌───────────────┐                  │                       │
│ Textual       │      │ Audio Bounding│                  │                       │
│ Evidence Span │      │ & Timed Script│                  │                       │
└───────┬───────┘      └───────┬───────┘                  │                       │
        └───────────────┬──────┘                          │                       │
                        ▼                                 ▼                       ▼
        ┌─────────────────────────────────────────────────────────────────────────────────┐
        │                          LEARNING KNOWLEDGE BASE                                │
        │ • Principles & Strategies (principles/**/*.md)                                 │
        │ • Vocabulary & Collocations (data/vocabulary/, data/collocations/)              │
        │ • Systematic Error Triggers (e.g., confuse_false_not_given)                     │
        └─────────────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Academic Reading (Primary Pilot Focus)
- **Granularity:** 3 Passages per test, 40 questions total.
- **Evidence Anchor:** Character start/end offsets, paragraph labels (A–H), verbatim text quotes.
- **Verification Rule:** Every answer must have verbatim textual grounding in the passage.

### 3.2 Listening
- **Granularity:** 4 Sections/Parts per test, 40 questions total.
- **Evidence Anchor:** Timestamp intervals (`start_time_sec`, `end_time_sec`), audio track reference, transcript paragraph/speaker label.
- **Verification Rule:** Answer words must conform to exact word limits stated in the instructions.

### 3.3 Writing
- **Granularity:** Task 1 (Academic report/process) & Task 2 (Discursive essay).
- **Core Entities:** Prompt $\to$ Prompt Deconstruction $\to$ Essay Plan $\to$ Sample Answer $\to$ Criterion Breakdown (TR/TA, CC, LR, GRA) $\to$ Lexical Bank.
- **Verification Rule:** Band scores for model answers are advisory/unofficial and must include criterion-level justifications.

### 3.4 Speaking
- **Granularity:** Part 1 (Introduction & Interview), Part 2 (Long Turn / Cue Card), Part 3 (Two-way Discussion).
- **Core Entities:** Topic / Cue Card Prompt $\to$ Mindmap / Structural Strategy $\to$ Sample Response Transcript $\to$ Lexical Resource & Pronunciation Targets.
- **Verification Rule:** Differentiate between exam forecast questions and official test material.

---

## 4. Pipeline Execution Architecture

Normalization proceeds through seven sequential, fault-isolated pipeline stages:

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ Stage 1: Ingestion & Provenance Binding                                        │
│ Read staged raw JSON artifact, verify SHA-256 against checkpoint database.     │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ Stage 2: Content Block Sanitization & Structural Segmentation                  │
│ Clean raw text, de-hyphenate linebreaks, repair encoding, segment paragraphs,   │
│ isolate tables and metadata blocks.                                            │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ Stage 3: Test & Passage / Section Demarcation                                  │
│ Detect test boundaries, volume metadata, passage titles, narrative text runs,   │
│ and section division labels.                                                   │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ Stage 4: Question Group & Item Parsing                                         │
│ Extract instruction headers, word constraints, question numbers, prompts, and   │
│ options (A/B/C/D). Handle joined/concatenated runs with boundary regexes.      │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ Stage 5: Answer Key Normalization & Multi-Source Reconciliation                │
│ Parse answer tables/lists, normalize enums (TRUE/FALSE/NOT GIVEN), register    │
│ acceptable spelling variants, resolve conflicting answer sources.              │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ Stage 6: Evidence Grounding & Offset Resolution                                │
│ Align quoted evidence against normalized passage text. Verify exact character  │
│ offsets. Compute similarity confidence if OCR noise is present.                │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ Stage 7: Quality Gate Evaluation & Atomic Output Generation                    │
│ Evaluate multi-dimensional quality flags, assign lifecycle status, and write   │
│ atomic normalized JSON records + derived SQLite entries.                       │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Architectural Quality Guarantees

1. **Non-Destructive Processing:**
   Raw staged JSON outputs from V0.1 are immutable inputs. The normalizer never modifies V0.1 artifacts or `private/raw/` files.
2. **Determinism & Idempotency:**
   Given identical raw input artifacts and the same normalization configuration, the normalizer produces identical JSON outputs with identical cryptographic hashes.
3. **No Guessing Policy:**
   Missing answers, missing question texts, or cut-off pages are explicitly recorded as `null` with a `missing_input` validation flag. Missing fields are never synthesized or imputed by machine models during normalization.
4. **Air-Gapped Copyright Protection:**
   All normalized records extracted from copyrighted test materials are stored strictly in `private/staging/normalized/` (gitignored). Public schema directories contain strictly synthetic illustrative records.
