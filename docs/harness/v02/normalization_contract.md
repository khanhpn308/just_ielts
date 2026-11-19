# IELTS Data Harness V0.2 — Normalization Contract Specification
**Phase V0.2-A: Schema Design & Normalization Contract (Remediated)**  
**Status:** Architectural Blueprint (Design Only)  
**Author:** IELTS Learning Systems Engineer & Data Architecture Team  
**Date:** 2026-11-19 (Remediated)  

---

## 1. Overview & Architectural Invariants

The Normalization Contract defines the formal processing guarantees, schema transitions, data integrity rules, and error handling protocols between staged raw extraction artifacts (`private/staging/raw_extracted/`) and canonical normalized entities (`private/staging/normalized/` for copyrighted data, and `data/normalized/synthetic/` for public test fixtures).

### 1.1 Invariant Principles
1. **Zero Guessing (No Hallucination or Imputation):**
   If an answer key is missing, an evidence quote is not found, or a question prompt is cut off, the normalizer **must not** synthesize or infer values. Missing fields must be recorded as `null`, accompanied by an explicit validation flag (e.g. `MISSING_SOURCE_ANSWER_KEY`, `UNRESOLVED_EVIDENCE_SPAN`).
2. **Deterministic Idempotency & Canonical Hashing:**
   Running the normalizer over identical raw JSON inputs with the same configuration must yield bit-identical normalized output JSON files and identical cryptographic hashes. Execution timestamps (`normalized_at`) are excluded from canonical content hashes (`canonical_content_sha256`).
3. **Traceable Lineage to V0.1:**
   Every normalized entity carries a `_provenance` block containing the physical `source_file_id` (`FILE-[a-f0-9]{12}`), authoritative `source_legacy_id` (`SRC-XXX`), unit identifier, and raw block locator.
4. **Schema Versioning:**
   All normalized outputs declare `schema_version: "v0.2.0-normalized"`.

---

## 2. Question Segmentation Contract for Joined DOCX Runs

### 2.1 The Problem Statement
In authentic IELTS Word documents (such as `SRC-138`, paragraph 309), multiple numbered questions frequently collapse into a single text block without paragraph breaks. Real-world boundary cases include:
- `...studied art history.2 Students can choose...` (No space after period).
- `...made and perceived5 Students will be able...` (Word immediately followed by digit, no punctuation).
- `...In 1980 the committee established 2 distinct research branches.2 Approximately 25 percent...` (Internal numerical distractors: `1980`, `2`, `25` inside prompt text).

### 2.2 Formal Segmentation Protocol
Given a concatenated text run $T$ and an expected sequential range $[S, E]$ where $N = E - S + 1$:
1. **Strict Monotonic Sequence Search:**
   The algorithm searches for question numbers $k \in [S, E]$ sequentially from the current text offset.
2. **Delimiter Pattern Specification:**
   A candidate number $k$ is recognized if and only if:
   $$\text{Pattern: } (?:^|[\.\?!a-zA-Z\s])(k)(?:[\.\s]*)(?=[A-Z])$$
   - **Prefix Boundary:** Preceded by start of string, sentence-ending punctuation (`.`, `?`, `!`), whitespace, or lowercase character.
   - **Target Group:** Captures exact sequential integer $k$.
   - **Suffix Boundary:** Followed by optional period or whitespace, and **strictly followed by an Uppercase Letter `[A-Z]`** (the first letter of the subsequent question sentence).
   - This prevents false splits on internal numerical expressions such as `"established 2 distinct"` (where `distinct` is lowercase).
3. **Boundary Splitting & Text Coverage:**
   - Prompt text for item $k$ spans from the end of delimiter $k$ to the digit start of delimiter $k+1$.
   - Any period preceding delimiter $k+1$ remains attached to the preceding prompt text, ensuring **zero text loss**.
4. **Integrity Guarantees:**
   - **Count Conservation:** Extracted items must equal exactly $E - S + 1$.
   - **Strict Numbering:** Items must form a continuous sequence $S, S+1, \dots, E$.
   - **No Text Loss:** Concatenation of reconstructed prompt texts and delimiters covers 100% of the input text characters.
   - **No Content Invention:** Prompt characters are copied verbatim from the raw string without lexical rewriting.
   - **Failure Routing:** If any number in the sequence cannot be matched, or if duplicate delimiters appear, the parser aborts automatic splitting, sets `lifecycle_status: "review_required"`, and records `validation_flags: ["SEGMENTATION_SEQUENCE_GAP"]`.

---

## 3. Evidence Grounding Contract

### 3.1 Grounding Typology
Evidence entities must explicitly distinguish between three epistemic conditions:
1. `direct_support`:
   - Positive proof proving a statement is `TRUE` or justifying a specific completion answer.
   - Requires `verbatim_quote`, `char_start`, `char_end`, and `exact_match_verified: true`.
2. `contradictory_evidence`:
   - Counter-claim in the passage proving a statement is `FALSE` by direct contradiction.
   - Requires `verbatim_quote` containing the contradictory passage clause and verified character offsets.
3. `insufficient_information_not_given`:
   - Justification for a `NOT GIVEN` classification.
   - **`verbatim_quote` MUST BE `null`** (prevents fabricated quotes for information that does not exist in the passage).
   - Requires `missing_information_rationale` describing what topic is mentioned and what specific fact is absent.

---

## 4. Deterministic Output & Serialization Contract

To prevent spurious Git diffs and ensure rigorous verifiable data engineering across environments, Phase V0.2 strictly separates content identity, physical serialization, and runtime execution metadata.

### 4.1 Tri-Layer Determinism Framework

1. **Canonical Content Hash Stability (`canonical_content_sha256`):**
   - Represents the mathematical identity of the pedagogical content.
   - Calculated strictly over semantic payload fields (identifiers, text, options, target answers, coordinates, relationships).
   - Volatile execution timestamps (`normalized_at`) and the hash self-reference (`canonical_content_sha256`) are filtered out prior to serialization.
   - Computed as:
     $$\text{canonical\_content\_sha256} = \text{SHA-256}\Big(\text{JSON\_DUMP}\big(\text{Filter}(\text{entity}, \text{exclude}=\{\text{"normalized\_at"}, \text{"canonical\_content\_sha256"}\}), \text{sort\_keys}=\text{True}, \text{indent}=2\big)\Big)$$
   - Invariant: Re-running normalization at timestamp $T_2 > T_1$ over identical input guaranteed:
     $$\text{canonical\_content\_sha256}(D, T_1) \equiv \text{canonical\_content\_sha256}(D, T_2)$$

2. **Byte-Identical Serialized Output:**
   - Disk artifacts written to `private/staging/normalized/` or public repositories must be byte-for-byte identical across runs.
   - Enforced serialization parameters:
     - Encoding: UTF-8 without Byte Order Mark (BOM).
     - Indentation: Exactly 2 spaces (`indent=2`).
     - Key Sorting: Lexicographical order (`sort_keys=True`).
     - Line Endings: Unix standard line feed (`\n`).
     - Trailing Newline: Single trailing `\n` at end of file.
   - When canonical entity records are written to persistent storage, `normalized_at` is set to `null` (or omitted), guaranteeing bit-identical files on disk and zero spurious Git diffs.

3. **Volatile Execution Timestamps (`normalized_at`):**
   - Reflects the physical execution time (ISO 8601 UTC string, e.g. `"2026-11-19T12:00:00Z"`).
   - In production runtimes, execution timestamps and performance metrics belong to:
     - SQLite checkpoint ledger (`harness/state/harness.db` table `processing_checkpoints.created_at`).
     - Execution run manifests (`private/staging/normalized/manifest.json`).
   - If populated within an entity instance during ad-hoc debugging, the field is explicitly excluded from canonical hashing so integrity verification remains uncompromised.
