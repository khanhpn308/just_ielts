# IELTS Data Harness V0.2 — Phase V0.3 Readiness Assessment
**Phase:** V0.2-C Deliverable (Transition Planning & Strategic Readiness)  
**Target:** Evaluation of Architecture, Corpus Scaling, and AI Tutor Retrieval Readiness  
**Author:** Senior Data Quality Engineer, IELTS Assessment Specialist & Python Engineer  
**Date:** 2026-11-20  

---

## 1. Executive Assessment & Recommendation

Following the completion of Phase V0.2-C data acceptance and pilot reconciliation, this document evaluates whether the normalized dataset and data harness are ready to scale to Phase V0.3 (Full Corpus Ingestion across 206 sources).

### Strategic Verdict: **CONDITIONAL GO FOR V0.3**

1. **Architecture & Normalization Engine: UNCONDITIONAL GO**  
   The Normalization Engine, Pydantic domain models, Draft 2020-12 schemas, SQLite checkpointing, and Quality Gate verification (G1–G7) have demonstrated operational stability, deterministic execution, and zero data loss on messy real-world examination documents.
2. **AI Tutor Retrieval Pipeline: GO WITH MANDATORY DISCLOSURE & MANIFEST INTEGRITY**  
   The dataset and retrieval engine are fully hardened for AI Tutor retrieval. The `TutorRetriever` engine strictly enforces authoritative manifest validation, verifies entity identity and canonical SHA-256 checksums, prevents path traversal, and enforces chain-wide verification (Answer-Evidence-Explanation) before assigning `READY`. All unverified secondary keys and machine-drafted explanations trigger mandatory `REVIEW_REQUIRED` uncertainty disclosures.
3. **High-Stakes Autonomous Quizzing: NO-GO (HUMAN VERIFICATION GATE REQUIRED)**  
   The pilot data cannot be used for high-stakes, unassisted diagnostic scoring because 4 answers are physically missing from the source scans and 9 answers stem from a single secondary guide without publisher confirmation or human expert certification.

---

## 2. Readiness Evaluation Across Core Dimensions

### 2.1 Structural & Syntactic Readiness: **100% (READY)**
- All 38 normalized entities validate against Draft 2020-12 JSON Schemas via referencing registry with zero errors.
- Monotonic question segmentation reliably splits joined DOCX question runs with 100% count conservation.
- Deterministic canonical hashing excludes volatile run timestamps, allowing $O(1)$ resume skips across batch operations.

### 2.2 Source-Grounded Correctness: **PARTIAL / GO WITH UNRESOLVED STATUS**
- Direct support and contradiction evidence spans match narrative text with exact character-level offsets.
- The NOT GIVEN invariant (`verbatim_quote: null`, `char_start: null`) is strictly maintained.
- Truncated physical scans in secondary guides (e.g. `SRC-137` missing book page 94 and cutting off at page 96) are safely represented as `target_value: null` with `MISSING_SOURCE_ANSWER_KEY` flags, preventing hallucination.
- Cross-volume reconciliation candidate `SRC-077` was correctly detected as belonging to Volume 3 and rejected, proving the engine's epistemic defenses against false-positive answer matching.

### 2.3 Epistemic Integrity & Human Verification: **PENDING REVIEW**
- 0 of 38 entities currently hold `verified` status (zero false claims).
- Current entities are strictly partitioned: `review_required` (17), `reviewed` (7), `extracted` (14).
- The dataset strictly prohibits unreviewed secondary keys from being labeled `authoritative_key` or `consensus_key`.

---

## 3. Transition Gates to Phase V0.3

To scale safely from the single-passage Reading Pilot to the complete 206-source corpus in Phase V0.3, the following gates must be satisfied:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ GATE V3-1: Multi-Source Provenance Resolver                                     │
│ • Prerequisite: Automated matching of tabular answer banks (e.g. SRC-077)       │
│   strictly to their matching source volumes (e.g. VOL 3 -> VOL 3, not VOL 6).   │
│ • Invariant: Volume, test, passage, and prompt alignment must be mathematically │
│   verified before any key reconciliation occurs.                                │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ GATE V3-2: Ingestion of Official Cambridge Answer Keys                           │
│ • Prerequisite: Scan and extract official publisher answer key booklets         │
│   to heal truncated secondary guides (e.g. resolving Q1, Q11-Q13 in VOL 6).     │
│ • Target: Achieve 100% answer coverage across all ingested tests.               │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ GATE V3-3: Human Tutor Annotation CLI                                           │
│ • Prerequisite: Implement an authenticated review CLI for IELTS tutors          │
│   to verify answers, ground evidence, and promote entities to 'verified'.       │
│ • Requirement: Require reviewer_id, timezone-aware timestamp, and decision.     │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Phase V0.3 Risk Register & Mitigation Strategy

| Risk ID | Description | Impact | Likelihood | Mitigation Strategy in V0.3 |
|---|---|---|---|---|
| **R-01** | Cross-volume answer poisoning | Critical | Medium | Enforce strict collection and volume metadata matching in `AnswerReconciler` before merging XLSX sheets. |
| **R-02** | Hallucinated quotes for NOT GIVEN items | High | High | Quality Gate G5 automatically halts pipelines if `verbatim_quote` is non-null for `insufficient_information_not_given`. |
| **R-03** | Premature elevation to expert_verified | Critical | Low | Hardcode validator requirement that `lifecycle_status = 'verified'` requires a signed review event in annotations. |
| **R-04** | Copyright leakage in public repo | Critical | Low | Strict pre-write path resolution enforcing storage under `private/` and automated git diff checks before commits. |
| **R-05** | Batch processing performance bottlenecks | Medium | Medium | Leverage SQLite checkpointing to ensure linear scaling across 206 sources with resumption on interruption. |

---

## 5. Roadmap for Phase V0.3 Execution

1. **Sprint 1: Corpus Batch Pipeline Orchestration**
   - Extend `NormalizationOrchestrator` to iterate through all cataloged reading and listening sources.
   - Implement volume-aware multi-source mapping between question booklets and answer sheets.
2. **Sprint 2: Listening Module Normalization**
   - Implement `AudioMetaNormalizer` and transcript alignment engine for Section 1–4 items.
   - Ground listening evidence spans against timestamped audio intervals and transcript paragraph offsets.
3. **Sprint 3: Tutor Review Interface**
   - Build a lightweight terminal review tool for human IELTS assessment specialists.
   - Enable single-command promotion of `reviewed` entities to `verified` with cryptographic attribution.
4. **Sprint 4: Full Corpus Ingestion & Quality Audit**
   - Execute normalization across Volumes 1–19.
   - Output global corpus quality reports and index for AI Tutor retrieval.
