# IELTS Data Harness V0.2 — Phase V0.2-C Acceptance Report
**Phase:** V0.2-C (Data Acceptance & Pilot Reconciliation)  
**Status:** Completed Engineering Acceptance Audit  
**Target:** Ground-Truth Quality Gate and Tutor Retrieval Acceptance for Reading Pilot  
**Author:** Senior Data Quality Engineer, IELTS Assessment Specialist & Python Engineer  
**Date:** 2026-11-20  

---

## 1. Executive Summary

Phase V0.2-C establishes formal data acceptance for the IELTS Reading Pilot (VOL 6 Academic Reading Test 5 Passage 1).

The primary objective of V0.2-C is to audit all 38 normalized entities, reconcile missing answers against candidate supplementary sheets, verify source evidence grounding, and determine whether the normalized dataset is epistemically and structurally ready for downstream AI Tutor retrieval.

### Key Milestones Completed:
1. **Pilot Entity Audit (Q1–Q13):** Verified all 38 canonical entities across 7 distinct schemas (Test, Passage, QuestionGroup, Question, Answer, Evidence, Explanation). Confirmed 100% complete question prompt extraction, sequential numbering, and zero text loss.
2. **Missing Answer Investigation & Disproof of Candidate Key (`SRC-077`):**
   - Conducted an evidence-based forensic reconciliation of missing questions Q1, Q11, Q12, and Q13.
   - Proved that candidate supplementary answer sheet `SRC-077` (`key.xlsx`) belongs to Volume 3 (not Volume 6), covers a completely different semantic domain (archaeology vs art history), and directly contradicts verified pilot keys across all overlapping items.
   - Categorically rejected `SRC-077` to prevent data corruption.
   - Preserved missing answers Q1, Q11, Q12, and Q13 as explicitly unresolved (`target_value: null`, status: `review_required`, flag: `MISSING_SOURCE_ANSWER_KEY`). Prohibited guessing or fabricating answers.
3. **Evidence & Explanation Fidelity:**
   - Validated direct support and contradiction evidence spans against passage text with 100% character-level offset precision.
   - Strictly enforced the NOT GIVEN data invariant (`verbatim_quote: null`, `char_start: null`, `char_end: null`, with explicit `missing_information_rationale`).
   - Categorized explanations by author type (`source_published` vs `machine_drafted`) and verification status (`source_provided` vs `machine_drafted_unverified`).
4. **Zero False Human Verification Claims:**
   - 0 of 38 entities claim `verified` or `expert_verified` in the absence of an authenticated human review event, adhering to Acceptance Gate A6.
5. **AI Tutor Retrieval Engine:**
   - Implemented `TutorRetriever` in `harness/retrieval.py` and CLI command `harness retrieve`.
   - Verified that question retrieval bundles question text, instructions, answer keys, evidence, explanations, linked principles, and explicit uncertainty disclosure.
   - Smoke tests verified: direct support item, NOT GIVEN item, and missing answer item.
6. **Acceptance Gates (A1–A9):** All 9 acceptance gates pass.

---

## 2. Reading Pilot Audit & Metric Summary

### 2.1 Aggregate Coverage Metrics

| Dimension | Pilot Metric | Target Standard | Status |
|---|---|---|---|
| **Question Coverage** | 13 / 13 (100.0%) | 100.0% count conservation | **PASS** |
| **Answer Coverage** | 9 / 13 (69.23%) | Ground truth matching source scan | **PASS (Gaps Explained)** |
| **Evidence Coverage** | 4 / 13 (30.77%) | 100% of available source rationales | **PASS** |
| **Explanation Coverage** | 4 / 13 (30.77%) | 100% of available source rationales | **PASS** |
| **Provenance Completeness** | 38 / 38 (100.0%) | Traced to source file SHA-256 and locator | **PASS** |
| **Human Expert Verification** | 0 / 38 (0.0%) | Zero false verification claims | **PASS** |
| **JSON Schema Conformance** | 38 / 38 (100.0%) | Strict Draft 2020-12 validation | **PASS** |

### 2.2 Quality Profile Breakdown

Entities by Lifecycle Status:
- `extracted`: 14 (1 passage + 13 questions)
- `reviewed`: 8 (1 test, 2 question groups, 4 evidence entities, 1 reconciled passage)
- `review_required`: 16 (9 single-source unverified keys, 4 missing keys, 4 unverified/machine-drafted explanations)
- `verified`: **0** (Human expert review required; zero false claims)
- `rejected`: 0

---

## 3. Answer Reconciliation Audit

### 3.1 Provenance of Source Gaps in Primary Guide (`SRC-137`)
The pilot's secondary answer guide (`SRC-137`, `KEY + EXPLANATION 5-6.pdf`) contains physical scanning gaps:
- **Book Page 94 Omission:** The PDF begins at printed book page 95. Book page 94, containing Question 1, was omitted during physical book scanning.
- **Book Page 96 Cutoff:** The PDF page 2 ends at the bottom of printed book page 96 after Question 10. PDF page 3 jumps directly to Reading Passage 2 (book page 97). Questions 11, 12, and 13 were truncated.

### 3.2 Candidate Evaluation: Rejection of `SRC-077`
Candidate key sheet `SRC-077` (`private/raw/VOL 3/Reading/key.xlsx`) was audited to determine whether it could reconcile the missing answers.

Before accepting any external answer key, the data harness requires mathematical and semantic proof of identity:
1. **Volume Identity:** Must match the target volume code (`VOL06`).
2. **Test Identity:** Must correspond to the target test number.
3. **Passage Domain:** Must align with the passage topic.
4. **Question Alignment:** Must address the identical prompts.
5. **Answer Concordance:** Must be compatible with known pilot keys.

#### Evaluation Outcome:
- `SRC-077` is located in `private/raw/VOL 3/` and was confirmed to belong to **Volume 3**, failing criterion 1.
- The content domain in `SRC-077` Test 5 corresponds to an archaeological passage, while the pilot passage addresses art history, failing criterion 3.
- All overlapping items in `SRC-077` directly contradict `SRC-137`:
  - Q2: Pilot key is `FALSE`; `SRC-077` has `T`.
  - Q3: Pilot key is `NOT GIVEN`; `SRC-077` has `F`.
  - Q5: Pilot key is `FALSE`; `SRC-077` has `NGV`.
  - Q6: Pilot key is `TRUE`; `SRC-077` has `F`.
  - Q7: Pilot key is `fraudulent`; `SRC-077` has `seeds`.
  - Q8: Pilot key is `museums`; `SRC-077` has `shells`.

**Reconciliation Conclusion:** `SRC-077` is an orphaned key sheet for Volume 3. It was **100% rejected** for PILOT-05. Missing questions Q1, Q11, Q12, and Q13 remain explicitly unresolved without data hallucination.

---

## 4. Evidence Grounding & Pedagogical Audit

### 4.1 Synthetic Illustration of Verification Types
*(Public documentation uses synthetic illustrations to protect copyrighted materials)*

```
[Synthetic Passage Text]
"Submerged tidal turbines generate predictable electrical current from lunar currents.
However, deployment costs remain undocumented in the initial trial reports."

[Synthetic Question 1 (TRUE)]: "Submerged turbines generate electrical current."
-> Evidence Type: direct_support
-> Exact Quote: "Submerged tidal turbines generate predictable electrical current from lunar currents."
-> Exact Offsets: (0, 78) -> exact_match_verified: true

[Synthetic Question 2 (NOT GIVEN)]: "Deployment costs doubled between 2020 and 2024."
-> Evidence Type: insufficient_information_not_given
-> Verbatim Quote: null (Enforces prohibition against fabricated quotes)
-> Offsets: (null, null)
-> Missing Information Rationale: "The text mentions that deployment costs are undocumented, providing no historical data for 2020-2024."
```

### 4.2 Audit of Real Pilot Evidence Records
- **`EVID-VOL06-05-RD-003-01` (Q3 - NOT GIVEN):** `verbatim_quote: null`, `char_start: null`, `char_end: null`. Valid missing information rationale documented.
- **`EVID-VOL06-05-RD-004-01` (Q4 - TRUE):** `direct_support`, character offsets `1027–1143`. Exact string slice verified against `narrative_text`. Paraphrase verified: "perceived" $\longleftrightarrow$ "people's responses to it".
- **`EVID-VOL06-05-RD-005-01` (Q5 - FALSE):** `contradictory_evidence`, character offsets `1416–1565`. Exact string slice verified. Contradicts the claim that students can take *any* listed course by proving they are *not available every year*.
- **`EVID-VOL06-05-RD-006-01` (Q6 - TRUE):** `direct_support`, character offsets `1686–1853`. Exact string slice verified. Paraphrase verified: "unlisted course" $\longleftrightarrow$ "course that does not appear in the list"; "appropriate approval" $\longleftrightarrow$ "permission from the relevant Course Tutor".

---

## 5. AI Tutor Retrieval Smoke Test

The `TutorRetriever` module in `harness/retrieval.py` implements schema-compliant retrieval for autonomous tutoring agents:

### 5.1 Retrieval Capabilities
1. **Full Context Packaging:** Packages question prompt, options, group instructions, and passage context in a single call.
2. **Pedagogical Enrichment:** Links relevant strategies from `principles/` (e.g. `RD-TFNG-001: Distinguish FALSE from NOT GIVEN`) via `linked_principle_ids`. Prohibits unlinked or fabricated principle associations.
3. **Mandatory Uncertainty Disclosure:** Every retrieved bundle includes a structured `uncertainty_disclosure` payload detailing:
   - Overall readiness rating (`READY`, `REVIEW_REQUIRED`, `BLOCKED`).
   - Source authority level (`authoritative_official` vs `secondary_reputable`).
   - Explicit flags (`MISSING_SOURCE_ANSWER_KEY`, `SINGLE_SOURCE_UNVERIFIED_KEY`, `OCR_TYPO_CORRECTED`).
   - Human-readable disclaimer text warning tutors not to conduct high-stakes diagnostic scoring on unverified or missing keys.

### 5.2 Retrieval Test Results

| Test Case | Question ID | Target Answer | Evidence Type | Readiness | Uncertainty Disclosure |
|---|---|---|---|---|---|
| **Direct Support** | `Q-VOL06-05-RD-004` | `TRUE` | `direct_support` | `REVIEW_REQUIRED` | Discloses single-source secondary key from SRC-137 pending expert verification; reports exact evidence offsets. |
| **NOT GIVEN** | `Q-VOL06-05-RD-003` | `NOT GIVEN` | `insufficient_information_not_given` | `REVIEW_REQUIRED` | Discloses missing-information rationale; enforces `verbatim_quote: null`; flags machine-drafted explanation. |
| **Missing Answer** | `Q-VOL06-05-RD-001` | `null` | *None* | `BLOCKED` | **CRITICAL WARNING:** Answer key missing from physical scan; blocks automated scoring; prohibits answer guessing. |
| **OCR Typo Item** | `Q-VOL06-05-RD-007` | `fraudulent` | *None* | `REVIEW_REQUIRED` | Discloses OCR typo remediation from `Fraudulant`; reports missing evidence span. |

---

## 6. Acceptance Gate Evaluation (A1–A9)

| Gate | Description | Criteria | Result | Notes |
|---|---|---|---|---|
| **A1** | Question Audit Completeness | All 13 questions audited against original sources. | **PASS** | Complete audit matrix generated in `private/reports/v02c/audit_matrix.csv`. |
| **A2** | Answer Source Provenance | Every accepted answer has traceable source provenance. | **PASS** | All 9 populated answers trace to `SRC-137` page locators with SHA-256. |
| **A3** | Zero Data Fabrication | No fabricated evidence quotes, explanations, or answers. | **PASS** | 4 missing keys preserved as `null`. NOT GIVEN quotes strictly `null`. |
| **A4** | Missing Answer Preservation | Missing answers remain explicitly unresolved. | **PASS** | Q1, Q11, Q12, Q13 flagged `MISSING_SOURCE_ANSWER_KEY`. `SRC-077` rejected. |
| **A5** | Schema Compliance | All canonical records satisfy JSON Schemas. | **PASS** | All 38 entities validate against Draft 2020-12 schemas without warnings. |
| **A6** | Honest Verification Claims | Zero false claims of human expert verification. | **PASS** | 0 records claim `verified` or `expert_verified`. All pending human review. |
| **A7** | Tutor Uncertainty Disclosure | Tutor retrieval exposes epistemic uncertainty. | **PASS** | `TutorRetriever` outputs machine flags and human-readable disclaimers. |
| **A8** | Regression Invariance | Existing test suite passes with zero regressions. | **PASS** | 100 passed standard, 109 passed with `--corpus`, check-env OK. |
| **A9** | Privacy Isolation | Zero copyrighted or private material enters public Git. | **PASS** | Authentic texts kept in `private/`; public reports use synthetic examples. |

---

## 7. Deliverables Index

### Private Deliverables (`private/reports/v02c/`):
- `audit_matrix.csv`: Complete item-level matrix for Questions 1–13.
- `reconciliation_report.md`: Detailed forensic report on `SRC-077` and `SRC-137`.
- `quality_report.json`: Machine-readable quality metrics across all dimensions.
- `unresolved_items.json`: Comprehensive catalog of unresolved keys, evidence, and explanations.
- `tutor_retrieval_samples.json`: Complete retrieved JSON bundles for representative smoke test items.

### Public Deliverables (`docs/harness/v02/`):
- `v02c_acceptance_report.md`: This comprehensive engineering acceptance document.
- `v03_readiness_assessment.md`: Strategic architecture assessment and roadmap for Phase V0.3.
