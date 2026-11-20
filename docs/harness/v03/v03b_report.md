# IELTS Data Harness V0.3 — Phase V0.3-B Engineering Report
**Phase:** V0.3-B Human Review & Source Verification Workflow  
**Role:** Senior Python Engineer, Data Quality Engineer, and IELTS Knowledge Base Architect  
**Repository:** `~/projects/just_ielts`  
**Base Branch:** `main`  
**Working Branch:** `feat/harness-v0.3b`  
**Date:** 2026-11-20  

---

## 1. Executive Summary & Mission

Phase V0.3-B implements a rigorous, lightweight human-review workflow for the IELTS Multi-Source Relationship Resolver. In heterogeneous exam corpora, heuristic and metadata-driven resolvers often produce plausible relationship pairings (e.g. question booklets to answer keys or explanation guides) that lack independent content grounding or retain epistemic ambiguity.

Phase V0.3-B provides human operators with the tools to inspect, approve, reject, or defer source relationships while enforcing strict evidentiary invariants, atomic state transitions, and immutable audit logs.

### Core Invariants
1. **Never Automatic Approval:** A relationship never transitions to `confirmed` without meeting all epistemic gates and receiving explicit human operator approval.
2. **Operator Declaration vs. Expert Qualification:** Reviewer identities submitted via CLI are operator declarations, not authenticated proof of expert qualification. Systems must never claim `expert_verified` without independently authenticated credentials.
3. **No Promotion Over Critical Conflicts:** Critical contradictions (e.g. cross-volume mismatches, conflicting answer keys, skill contradictions) categorically prohibit promotion to `confirmed`.
4. **Stale Source Evidence Invalidation:** Any change to source content hashes invalidates existing snapshots and blocks approval until re-evaluated.
5. **No Blind Ground-Truth Trust:** External or caller-provided ground truth references must be validated against the source inventory, content hashes, collection/test scope, and non-circularity invariants.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                          HUMAN REVIEW DECISION PIPELINE                          │
│                                                                                  │
│   Operator Input (CLI / API):                                                    │
│   • Target Relationship ID (REL-...)                                             │
│   • Decision: [approve | reject | defer]                                         │
│   • Reviewer ID (Operator Declaration)                                           │
│   • Mandatory Documented Rationale (min 5 chars)                                 │
│   • Timezone-Aware Timestamp (ISO 8601)                                          │
│   • Optional Supporting Evidence References                                      │
│                                      │                                           │
│                                      ▼                                           │
│   Epistemic Review Policy Gates (Rules A–E):                                     │
│   [Rule A] Source Existence & Accessibility in Inventory                         │
│   [Rule A] Test / Volume / Section Alignment (Zero Mismatches)                   │
│   [Rule A] Independent Supporting Evidence (Content Title, Verified Key/Audio)   │
│   [Rule B] No Unresolved Critical Conflicts (e.g. Cross-Volume)                  │
│   [Rule C] Source Freshness (Recorded SHA-256 == Current DB & Disk SHA-256)      │
│   [Rule D] Missing Evidence Retains candidate or review_required                 │
│                                      │                                           │
│                                      ▼                                           │
│   Atomic Transaction & Concurrency Enforcement:                                  │
│   • Optimistic Concurrency Check (status, updated_at)                            │
│   • Duplicate Review Check (unique deterministic review_id)                      │
│   • Atomic SQLite Transaction: Update Status + Append Review Event               │
│   • Immutable Audit History Persistence (relationship_reviews)                   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Human Review Domain Model

The relationship review domain model is formalized in `harness/models/relationship.py` conforming to schema `v0.3.0-review`:

### 2.1 Model Specifications
```python
class RelationshipReview(BaseModel):
    review_id: str                      # Deterministic REV-[a-f0-9]{16}
    relationship_id: str                # Target REL-[a-f0-9]{16}
    reviewer_id: str                    # Declared operator identifier
    reviewer: str                       # Backward-compatible alias
    previous_status: RelationshipStatus # candidate, review_required, confirmed, rejected
    requested_status: Optional[str]     # confirmed, rejected, deferred
    final_status: RelationshipStatus    # Resulting status after policy evaluation
    new_status: RelationshipStatus      # Backward-compatible alias
    decision: ReviewDecision            # approve, reject, defer
    reason: str                         # Documented rationale (min 5 chars)
    reviewed_at: str                    # Timezone-aware ISO 8601 timestamp
    created_at: str                     # Synced ISO timestamp
    source_fingerprint: Optional[str]   # Snapshot source SHA-256
    target_fingerprint: Optional[str]   # Snapshot target SHA-256
    evidence_references: Dict[str, Any] # References to verified external evidence
    review_policy_version: str          # Policy ruleset version ("v0.3.0-b")
    expert_verified: bool               # False (CLI operator declaration)
```

### 2.2 Deterministic Identifier Generation
Review events receive a stable, deterministic primary key:
$$\text{review\_id} = \text{"REV-"} + \text{SHA256}(\text{relationship\_id} : \text{reviewer\_id} : \text{decision} : \text{reviewed\_at})[:16]$$

---

## 3. Review Policy Engine (Rules A–E)

The review policy engine (`harness/review/policy.py`) enforces strict epistemic criteria:

### 3.1 Rule A: Candidate or Review Required Promotion
A relationship in `candidate` or `review_required` may transition to `confirmed` only if **all** of the following conditions are satisfied:
1. **Source Identity Validity:** Both primary and target sources exist in inventory and are marked accessible.
2. **Scope Alignment:** No `VOLUME_MISMATCH`, `SKILL_MISMATCH`, `TEST_NUMBER_MISMATCH`, or `PASSAGE_MISMATCH` flags are present.
3. **Independent Supporting Evidence:** At least one independent content grounding factor exists:
   - `CONTENT_TITLE_MATCH` in validation flags.
   - `ANSWERS_ALIGNED` in validation flags (without circularity).
   - `AUDIO_TRACK_VERIFIED` in validation flags (without audio track mismatch).
   - `TRANSCRIPT_SECTION_VERIFIED` in validation flags.
   - `TRANSCRIPT_AUDIO_ALIGNED` in validation flags.
   - Or reviewer-provided evidence verified via `SourceReferenceValidator`.
4. **Zero Critical Conflicts:** No unresolved critical conflict exists in `relationship_conflicts`.
5. **Fresh Fingerprints:** Recorded source and target SHA-256 match current database inventory and physical files on disk.
6. **Explicit Approval:** Reviewer explicitly submits `approve`.

### 3.2 Rule B: Rejected Relationship Promotion Restriction
A relationship in `rejected` status cannot be promoted to `confirmed` while critical conflicts remain active. An operator must first resolve the conflict (e.g. catalog update or re-extraction) and rerun matching.

### 3.3 Rule C: Stale Relationship Invalidation
Approval is categorically rejected if source hashes have changed since the relationship snapshot was computed.

### 3.4 Rule D: Missing Evidence Retention
If a candidate relationship only possesses structural numbering compatibility (e.g. `QUESTION_RANGE_ALIGNED`), attempting to approve it without external verified evidence fails validation. The relationship remains in `candidate` or `review_required`.

### 3.5 Rule E: Invalidation of Stale Confirmed Relationships
If source files of a previously confirmed relationship are modified on disk or re-extracted, the relationship is flagged as stale and must not be served as an active confirmation until re-validated.

---

## 4. Independent Source Verification & Non-Circularity

Phase V0.3-B resolves the V0.3-A limitation where `known_ground_truth_map` accepted caller-provided source identifiers without independent verification.

The `SourceReferenceValidator` (`harness/review/verification.py`) provides cryptographic and metadata verification:
1. **Inventory Existence Check:** The referenced source must exist in SQLite `sources` table.
2. **Cryptographic Check:** The recorded content SHA-256 and physical on-disk file SHA-256 must match.
3. **Identity & Test Scope:** The reference document must belong to the matching collection and cover the required test number.
4. **Strict Non-Circularity:** The reference source cannot share `file_id`, `legacy_id`, `relative_path`, or content SHA-256 with the candidate target file. An answer key cannot confirm itself.
5. **Provenance Completeness:** Reviewer-provided references must supply non-empty audit provenance (`source_id`, `provenance_type`, or `authority`).

Fabricated or uncataloged source identifiers are rejected with `UNREGISTERED_SOURCE_REJECTED`, preventing spurious confirmations.

---

## 5. Review CLI Reference

The CLI was extended with the `relationship-review` subcommand suite in `harness/cli.py`:

### 5.1 Listing Relationships
```bash
./.venv/bin/python -m harness.cli relationship-review list
./.venv/bin/python -m harness.cli relationship-review list --status unresolved
./.venv/bin/python -m harness.cli relationship-review list --volume "VOL 6"
./.venv/bin/python -m harness.cli relationship-review list --format json
```

### 5.2 Inspecting Forensic Details & Gate Preview
```bash
./.venv/bin/python -m harness.cli relationship-review show --id REL-de2d61aad4fbe19b
./.venv/bin/python -m harness.cli relationship-review show --id REL-60baca75b5f63f07 --format json
```

### 5.3 Recording Review Decisions
```bash
# Approve with documented reason
./.venv/bin/python -m harness.cli relationship-review decide \
  --id REL-a000000000000001 \
  --decision approve \
  --reviewer-id USER-001 \
  --reason "Verified title alignment and passage structure against Test 1"

# Dry-run evaluation (no SQLite mutation)
./.venv/bin/python -m harness.cli relationship-review decide \
  --id REL-de2d61aad4fbe19b \
  --decision defer \
  --reviewer-id USER-001 \
  --reason "Deferring to locate independent Cambridge answer key" \
  --dry-run

# Reject relationship
./.venv/bin/python -m harness.cli relationship-review decide \
  --id REL-de2d61aad4fbe19b \
  --decision reject \
  --reviewer-id USER-001 \
  --reason "Contradictory content detected during human inspection"
```

### 5.4 Audit History Retrieval
```bash
./.venv/bin/python -m harness.cli relationship-review history --id REL-de2d61aad4fbe19b
```

---

## 6. Database Integrity & SQLite Migrations

Dynamic, non-destructive migrations were implemented in `harness/db.py`:

### 6.1 Extended `relationship_reviews` Schema
```sql
CREATE TABLE IF NOT EXISTS relationship_reviews (
    review_id TEXT PRIMARY KEY,
    relationship_id TEXT NOT NULL REFERENCES source_relationships(relationship_id),
    previous_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    reviewer_id TEXT,
    requested_status TEXT,
    final_status TEXT,
    decision TEXT,
    reason TEXT NOT NULL,
    source_fingerprint TEXT,
    target_fingerprint TEXT,
    evidence_references TEXT,
    review_policy_version TEXT,
    reviewed_at TIMESTAMP,
    expert_verified INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reviews_rel ON relationship_reviews(relationship_id);
CREATE INDEX IF NOT EXISTS idx_reviews_decision ON relationship_reviews(decision);
```

### 6.2 Transactional Guarantees
- **Atomic Operations:** Updating `source_relationships.relationship_status` and appending to `relationship_reviews` occurs within a single SQLite transaction block (`with conn:`).
- **Optimistic Concurrency:** Expected status and updated_at timestamps are verified before applying mutations; concurrent modifications trigger `ConcurrencyConflictError`.
- **Duplicate Prevention:** Existing review IDs trigger `DuplicateReviewError`.
- **Append-Only Immutability:** Review events cannot be altered or deleted.

---

## 7. Pilot Execution & Forensic Demonstration

Current status distribution recalculated from SQLite (`harness/state/harness.db`):
- **Confirmed:** 6 (4.9%)
- **Review Required:** 0 (0.0%)
- **Candidate:** 12 (9.8%)
- **Rejected:** 105 (85.4%)
- **Total Registered:** 123
- **Active Conflicts Recorded:** 76

### 7.1 Pilot Source Inspection
1. **Candidate Pair: `SRC-138` (`VOL 6.docx`) / `SRC-137` (`KEY + EXPLANATION 5-6.pdf`):**
   - 12 candidates exist covering Reading Tests 5 and 6, Passages 1–3 for explanation and answer key pairings.
   - Status: `candidate` (`match_confidence = 0.70`).
   - Flags: `VOLUME_MATCH`, `SKILL_MATCH`, `TEST_NUMBER_MATCH`, `PASSAGE_REQUESTED`, `QUESTION_RANGE_ALIGNED`.
   - Gate Assessment: Blocked from approval by Rule D (`Missing independent supporting evidence`).
2. **Rejected Pair: `SRC-138` (`VOL 6.docx`) / `SRC-077` (`VOL 3 key.xlsx`):**
   - Status: `rejected` (`match_confidence = 0.00`).
   - Flags: `VOLUME_MISMATCH`.
   - Conflicts: `CROSS_VOLUME_MISMATCH`, `CONFLICTING_ANSWER_KEYS`.
   - Gate Assessment: Blocked from approval by Rule B (`Critical conflicts`).
3. **Confirmed Listening Pair: `SRC-011` (`VOL 1 Test_1.pdf`) / `SRC-008` (`AudioTrack 01.mp3`):**
   - Relationship: `REL-60baca75b5f63f07` (`listening_to_audio`, VOL 1 Test 1 Section 1).
   - Flags: `VOLUME_MATCH`, `SKILL_MATCH`, `TEST_NUMBER_MATCH`, `PASSAGE_REQUESTED`, `AUDIO_TRACK_VERIFIED`, `TRANSCRIPT_AUDIO_ALIGNED`, `GATE_CONFIRMED_PASSED`.
   - Gate Assessment: Approval Eligible (`Meets all Rule A epistemic confirmation gates`).

### 7.2 Demonstration Verification
| Demonstration | Scenario | Result | Verification Evidence |
|---|---|---|---|
| **Demo 1** | Listing candidate relationships | **PASS** | `relationship-review list` correctly reported all 12 unresolved candidates. |
| **Demo 2** | Inspecting forensic evidence & conflicts | **PASS** | `relationship-review show` detailed source paths, SHA-256, flags, and gate previews. |
| **Demo 3** | Rejecting unsupported approval | **PASS** | Attempting to approve `REL-de2d61aad4fbe19b` failed with Rule D policy violation; status unmodified. |
| **Demo 4** | Recording synthetic approval | **PASS** | Synthetic candidate with title match approved as `REV-fd001bc32329a933` with operator declaration. |
| **Demo 5** | Detecting stale source evidence | **PASS** | Modified source SHA-256 triggered `Stale relationship` rejection. |
| **Demo 6** | Retrieving immutable review history | **PASS** | Chronological audit trail retrieved with decision, reviewer, and timestamps. |

---

## 8. Quality & Acceptance Gates Verification (H1–H9)

| Gate ID | Requirement | Result | Forensic Verification |
|---|---|---|---|
| **H1** | Every decision has valid audit provenance | **PASS** | Every review event stores review_id, reviewer_id, timestamps, fingerprints, decision, reason, policy version. |
| **H2** | No unsupported relationship gets confirmed | **PASS** | Approval requires independent content grounding; question-range-only candidates remain candidate. |
| **H3** | Critical conflicts prevent approval | **PASS** | Cross-volume and contradictory answer key relationships strictly blocked from promotion. |
| **H4** | Stale source evidence invalidates approval | **PASS** | Modifying source content SHA-256 immediately invalidates approval eligibility. |
| **H5** | Review history remains immutable | **PASS** | Table is append-only; duplicate review IDs rejected; history lists events chronologically. |
| **H6** | Dry-run causes no persistent changes | **PASS** | `--dry-run` performs full policy evaluation but performs zero database writes. |
| **H7** | Existing normalization remains compatible | **PASS** | All 149 baseline tests from V0.1, V0.2, and V0.3-A pass without regressions. |
| **H8** | Clean-checkout CI passes | **PASS** | Synthetic test suite executes cleanly on fresh checkout (160 passed, 9 skipped). |
| **H9** | Private data stays isolated | **PASS** | No copyrighted passages or private paths committed to public tracking. |

---

## 9. Test Suite Execution & Coverage

All 20 test scenarios are implemented in `tests/test_v03b_human_review.py`:
1. `test_valid_review_event`: Successful approval with complete audit trail.
2. `test_missing_reviewer_identity`: Empty reviewer identifier rejected.
3. `test_invalid_timestamps`: Naive/non-timezone-aware timestamps rejected.
4. `test_missing_supporting_evidence`: Range-only candidate approval rejected.
5. `test_circular_answer_source`: Self-referencing candidate key rejected.
6. `test_critical_conflicts`: Cross-volume conflict approval rejected.
7. `test_stale_source_hash`: Hash mutation invalidates approval.
8. `test_concurrent_review_changes`: Optimistic concurrency violation caught.
9. `test_duplicate_review_submissions`: Duplicate review ID rejected.
10. `test_immutable_audit_history`: Append-only chronological logging verified.
11. `test_dry_run_without_mutation`: Zero SQLite mutations under dry-run verified.
12. `test_privacy_isolation`: Zero copyrighted passage texts in review events.
13. `test_independent_source_validation_unregistered_rejected`: Uncataloged ground truth rejected.
14. `test_independent_source_validation_collection_mismatch`: Cross-collection reference rejected.
15. `test_independent_source_validation_success_promotes_approval`: Verified external evidence confirms candidate.
16. `test_cli_relationship_review_list`: CLI list subcommand verified.
17. `test_cli_relationship_review_show`: CLI show subcommand verified.
18. `test_cli_relationship_review_decide_dry_run`: CLI decide dry-run verified.
19. `test_cli_relationship_review_decide_rejection`: CLI policy rejection exits with code 1.
20. `test_cli_relationship_review_history`: CLI history subcommand verified.

### Execution Metrics
- **Clean Checkout (Synthetic Only):**
  ```bash
  ./.venv/bin/python -m pytest -q tests/
  # Output: 160 passed, 9 skipped in 6.96s
  ```
- **Local Corpus Acceptance:**
  ```bash
  ./.venv/bin/python -m pytest -q tests/ --corpus
  # Output: 169 passed in 28.44s
  ```
- **Environment Diagnostics:**
  ```bash
  ./.venv/bin/python -m harness.cli check-env
  # Output: All required Python and system dependencies are satisfied.
  ```

---

## 10. Limitations & Scope Boundary

- **Listening Audio Interval Extraction:** Detailed audio interval segmentation and tapscript alignment remain deferred to Phase V0.3-C.
- **Web Interface:** Web/UI dashboard is explicitly out of scope; human reviews are conducted exclusively via the CLI and programmatic service.
- **Bulk Corpus Normalization:** Full ingestion of all 206 raw documents remains deferred until all volume relationships are reviewed and confirmed.

---

## 11. Review-Integrity Remediation Addendum (PR #6 Final Invariants)

Following PR review integrity analysis, the following critical defects were resolved:

1. **Independent Evidence Validation (P0):**
   - Explicitly separated source identity verification (`validate_source_identity`) from relationship evidence verification (`validate_relationship_evidence`).
   - Enforced non-empty, valid 64-hex SHA-256 and fresh source fingerprint on disk.
   - Mandated positive evidence of required test identity: missing test metadata strictly fails and never matches.
   - Enforced relevant question/section alignment and verified content evidence (answers, titles, audio/transcript).
   - Proven: A registered source from the same volume is strictly insufficient proof of a relationship; unverifiable references remain unresolved.
   - Added negative tests for unrelated documents with matching collection metadata.

2. **Expert Verification Integrity (P0):**
   - Caller-provided `expert_verified=True` is categorically rejected across API, policy, and domain model layers.
   - Enforced `expert_verified=False` across `RelationshipReviewService`, `ReviewPolicyValidator`, `RelationshipReview`, and SQLite write persistence boundaries.

3. **Preserve Human Review Decisions (P0):**
   - Protected human review decisions from silent overwrites during matcher reruns.
   - When inputs remain unchanged, approved status, review history, and flags are preserved.
   - When inputs or evidence become stale, previously confirmed relationships are transitioned to `review_required` with `STALE_REVALIDATION_REQUIRED` flags and prevented from active confirmation consumption.
   - System transition event and rationale are permanently recorded in `relationship_reviews`.

4. **Audit Immutability (P1):**
   - Enforced append-only immutability at SQLite persistence boundary via `BEFORE UPDATE` and `BEFORE DELETE` triggers.
   - Direct UPDATE and DELETE attempts raise `sqlite3.DatabaseError` abort exceptions while preserving safe schema migrations (`init_db` idempotency and `ALTER TABLE ADD COLUMN`).
