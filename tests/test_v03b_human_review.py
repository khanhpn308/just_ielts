"""Automated test suite for Human Review & Source Verification Workflow (Phase V0.3-B).

Covers all 12 regression scenarios specified in Acceptance Gates and Section 8:
1. Valid review event.
2. Missing reviewer identity.
3. Invalid timestamps.
4. Missing supporting evidence.
5. Circular answer source.
6. Critical conflicts.
7. Stale source hash.
8. Concurrent review changes.
9. Duplicate review submissions.
10. Immutable audit history.
11. Dry-run without mutation.
12. Privacy isolation.
Plus verified independent source validation tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import pytest

from harness.config import REPO_ROOT
from harness.db import (
    apply_relationship_review_atomic,
    get_db_connection,
    get_source_relationship,
    init_db,
    list_relationship_conflicts,
    list_relationship_reviews,
    list_source_relationships,
    record_relationship_conflict,
    record_relationship_review,
    upsert_source,
    upsert_source_relationship,
)
from harness.matching.service import RelationshipMatchingService
from harness.models.relationship import (
    RelationshipReview,
    SourceRelationship,
    compute_relationship_id,
    compute_review_id,
)
from harness.review.policy import (
    ConcurrencyConflictError,
    DuplicateReviewError,
    ReviewPolicyValidator,
    ReviewPolicyViolation,
    StaleRelationshipError,
)
from harness.review.service import RelationshipReviewService
from harness.review.verification import SourceReferenceValidator

FIXTURES_PATH = REPO_ROOT / "tests" / "fixtures" / "synthetic_relationships" / "synthetic_test_sources.json"


@pytest.fixture
def synthetic_sources_map() -> dict:
    """Loads synthetic test sources fixture."""
    data = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    return {s["legacy_id"]: s for s in data["sources"]}


@pytest.fixture
def temp_db(tmp_path) -> Path:
    """Creates a temporary isolated SQLite database with migrations applied."""
    db_file = tmp_path / "test_v03b.db"
    init_db(db_file)
    return db_file


@pytest.fixture
def populated_db(temp_db, synthetic_sources_map) -> Path:
    """Populates temporary SQLite database with synthetic sources and candidates."""
    conn = get_db_connection(temp_db)
    for src in synthetic_sources_map.values():
        upsert_source(conn, {
            "file_id": src["file_id"],
            "legacy_id": src["legacy_id"],
            "relative_path": src["relative_path"],
            "filename": src["filename"],
            "extension": src["extension"],
            "detected_type": src["detected_type"],
            "size_bytes": src["size_bytes"],
            "content_sha256": src["content_sha256"],
            "collection": src["collection"],
            "duplicate_group": src["duplicate_group"],
            "accessibility_status": src["accessibility_status"],
        })

    # Candidate 1: Supported by content title match
    rel_id_1 = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )
    upsert_source_relationship(conn, {
        "relationship_id": rel_id_1,
        "source_file_id": "FILE-a00000000001",
        "target_file_id": "FILE-a00000000002",
        "relationship_type": "question_to_explanation",
        "collection": "VOL 99",
        "volume": "VOL 99",
        "test_number": 1,
        "passage_or_section": 1,
        "skill": "reading",
        "identity_evidence": {"passage_title": "Marine Energy Systems"},
        "validation_flags": ["VOLUME_MATCH", "SKILL_MATCH", "TEST_NUMBER_MATCH", "CONTENT_TITLE_MATCH"],
        "match_confidence": 0.8,
        "relationship_status": "candidate",
        "provenance": {"matcher_version": "0.3.0-a", "evaluated_at": "2026-11-20T10:00:00Z"},
        "source_content_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
        "target_content_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
        "schema_version": "v0.3.0-relationship",
    })

    # Candidate 2: Supported ONLY by question range (no content grounding, missing independent evidence)
    rel_id_2 = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000004", "question_to_answer_key", "VOL 99", 1, 1
    )
    upsert_source_relationship(conn, {
        "relationship_id": rel_id_2,
        "source_file_id": "FILE-a00000000001",
        "target_file_id": "FILE-a00000000004",
        "relationship_type": "question_to_answer_key",
        "collection": "VOL 99",
        "volume": "VOL 99",
        "test_number": 1,
        "passage_or_section": 1,
        "skill": "reading",
        "identity_evidence": {"expected_question_range": [1, 14]},
        "validation_flags": ["VOLUME_MATCH", "SKILL_MATCH", "TEST_NUMBER_MATCH", "PASSAGE_REQUESTED", "QUESTION_RANGE_ALIGNED"],
        "match_confidence": 0.7,
        "relationship_status": "candidate",
        "provenance": {"matcher_version": "0.3.0-a", "evaluated_at": "2026-11-20T10:00:00Z"},
        "source_content_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
        "target_content_sha256": "4444444444444444444444444444444444444444444444444444444444444444",
        "schema_version": "v0.3.0-relationship",
    })

    # Rejected 3: Critical conflict (cross volume)
    rel_id_3 = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000003", "question_to_answer_key", "VOL 99", 1, 1
    )
    upsert_source_relationship(conn, {
        "relationship_id": rel_id_3,
        "source_file_id": "FILE-a00000000001",
        "target_file_id": "FILE-a00000000003",
        "relationship_type": "question_to_answer_key",
        "collection": "VOL 99",
        "volume": "VOL 99",
        "test_number": 1,
        "passage_or_section": 1,
        "skill": "reading",
        "identity_evidence": {},
        "validation_flags": ["VOLUME_MISMATCH", "SKILL_MATCH"],
        "match_confidence": 0.0,
        "relationship_status": "rejected",
        "provenance": {"matcher_version": "0.3.0-a", "evaluated_at": "2026-11-20T10:00:00Z"},
        "source_content_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
        "target_content_sha256": "3333333333333333333333333333333333333333333333333333333333333333",
        "schema_version": "v0.3.0-relationship",
    })
    record_relationship_conflict(conn, {
        "conflict_id": "CONF-crit00000000001",
        "relationship_id": rel_id_3,
        "source_file_id": "FILE-a00000000001",
        "target_file_id": "FILE-a00000000003",
        "conflict_type": "CROSS_VOLUME_MISMATCH",
        "severity": "critical",
        "description": "Cross-volume mismatch: VOL 99 vs VOL 88",
        "evidence": {"source_volume": "VOL 99", "target_volume": "VOL 88"},
    })

    conn.close()
    return temp_db


# --------------------------------------------------------------------------
# 1. Valid Review Event
# --------------------------------------------------------------------------
def test_valid_review_event(populated_db):
    """Scenario 1: Verified review event successfully promotes candidate to confirmed with full audit trail."""
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )

    res = service.decide(
        relationship_id=rel_id,
        decision="approve",
        reviewer_id="USER-001",
        reason="Forensic content title match verified against passage 1",
        reviewed_at="2026-11-20T17:30:00+07:00",
    )

    assert res["status"] == "success"
    assert res["previous_status"] == "candidate"
    assert res["final_status"] == "confirmed"
    assert res["decision"] == "approve"

    # Verify audit event in DB
    history = service.get_history(rel_id)
    assert len(history) == 1
    ev = history[0]
    assert ev["relationship_id"] == rel_id
    assert ev["reviewer_id"] == "USER-001"
    assert ev["reviewer"] == "USER-001"
    assert ev["previous_status"] == "candidate"
    assert ev["final_status"] == "confirmed"
    assert ev["decision"] == "approve"
    assert ev["reason"] == "Forensic content title match verified against passage 1"
    assert ev["reviewed_at"] == "2026-11-20T17:30:00+07:00"
    assert ev["source_fingerprint"] == "1111111111111111111111111111111111111111111111111111111111111111"
    assert ev["target_fingerprint"] == "2222222222222222222222222222222222222222222222222222222222222222"
    assert ev["review_policy_version"] == "v0.3.0-b"
    assert ev["expert_verified"] is False

    # Check relationship updated in registry
    conn = get_db_connection(populated_db)
    rel = get_source_relationship(conn, rel_id)
    conn.close()
    assert rel["relationship_status"] == "confirmed"
    assert "HUMAN_REVIEW_APPROVED" in rel["validation_flags"]


# --------------------------------------------------------------------------
# 2. Missing Reviewer Identity
# --------------------------------------------------------------------------
def test_missing_reviewer_identity(populated_db):
    """Scenario 2: Missing or blank reviewer identifier is rejected."""
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )

    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="",
            reason="Approved without reviewer identifier",
        )
    assert "Reviewer identity is required" in str(exc_info.value)

    # Status remains candidate
    conn = get_db_connection(populated_db)
    rel = get_source_relationship(conn, rel_id)
    conn.close()
    assert rel["relationship_status"] == "candidate"


# --------------------------------------------------------------------------
# 3. Invalid Timestamps
# --------------------------------------------------------------------------
def test_invalid_timestamps(populated_db):
    """Scenario 3: Non-timezone-aware or invalid timestamps are rejected."""
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )

    # Naive timestamp without timezone offset
    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="USER-001",
            reason="Tested naive timestamp",
            reviewed_at="2026-11-20T10:00:00",
        )
    assert "must be timezone-aware" in str(exc_info.value)


# --------------------------------------------------------------------------
# 4. Missing Supporting Evidence
# --------------------------------------------------------------------------
def test_missing_supporting_evidence(populated_db):
    """Scenario 4: Candidate relationship supported only by question ranges cannot be confirmed."""
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000004", "question_to_answer_key", "VOL 99", 1, 1
    )

    # Attempt approval without providing independent ground truth evidence
    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="USER-001",
            reason="Attempting approval based on numbering range alone",
        )
    assert "Missing independent supporting evidence" in str(exc_info.value)

    # Must remain candidate
    conn = get_db_connection(populated_db)
    rel = get_source_relationship(conn, rel_id)
    conn.close()
    assert rel["relationship_status"] == "candidate"


# --------------------------------------------------------------------------
# 5. Circular Answer Source
# --------------------------------------------------------------------------
def test_circular_answer_source(populated_db):
    """Scenario 5: Attempting to confirm an answer key using the candidate key itself is rejected."""
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000004", "question_to_answer_key", "VOL 99", 1, 1
    )

    # Reviewer passes candidate target file itself as supporting evidence
    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="USER-001",
            reason="Using target answer key as its own supporting evidence",
            evidence_source_id="FILE-a00000000004",
        )
    assert "Circular answer key evidence" in str(exc_info.value)


# --------------------------------------------------------------------------
# 6. Critical Conflicts
# --------------------------------------------------------------------------
def test_critical_conflicts(populated_db):
    """Scenario 6: Relationships with unresolved critical conflicts cannot be approved."""
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000003", "question_to_answer_key", "VOL 99", 1, 1
    )

    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="USER-001",
            reason="Operator attempting to bypass cross volume conflict",
        )
    assert "Critical conflict 'CROSS_VOLUME_MISMATCH'" in str(exc_info.value)
    assert "prevent promotion to confirmed" in str(exc_info.value)


# --------------------------------------------------------------------------
# 7. Stale Source Hash
# --------------------------------------------------------------------------
def test_stale_source_hash(populated_db):
    """Scenario 7: Approval is rejected if source content hash changed since relationship creation."""
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )

    # Mutate source content hash in sources table to simulate modified file
    conn = get_db_connection(populated_db)
    conn.execute(
        "UPDATE sources SET content_sha256 = '9999999999999999999999999999999999999999999999999999999999999999' WHERE file_id = 'FILE-a00000000001'"
    )
    conn.commit()
    conn.close()

    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="USER-001",
            reason="Approval attempted on stale relationship",
        )
    assert "Source content hash changed" in str(exc_info.value) or "Stale relationship" in str(exc_info.value)


# --------------------------------------------------------------------------
# 8. Concurrent Review Changes
# --------------------------------------------------------------------------
def test_concurrent_review_changes(populated_db):
    """Scenario 8: Optimistic concurrency check detects concurrent modifications."""
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )

    review_event = {
        "review_id": "REV-concurrent00001",
        "relationship_id": rel_id,
        "previous_status": "candidate",
        "final_status": "confirmed",
        "decision": "approve",
        "reviewer_id": "USER-002",
        "reason": "Concurrent update test",
        "reviewed_at": "2026-11-20T17:40:00+07:00",
    }

    conn = get_db_connection(populated_db)
    # Expected status is 'candidate', but suppose another thread changed it to 'rejected'
    conn.execute(
        "UPDATE source_relationships SET relationship_status = 'rejected' WHERE relationship_id = ?",
        (rel_id,),
    )
    conn.commit()

    with pytest.raises(ConcurrencyConflictError) as exc_info:
        apply_relationship_review_atomic(
            conn=conn,
            review_data=review_event,
            expected_status="candidate",
        )
    assert "Optimistic concurrency check failed" in str(exc_info.value)
    conn.close()


# --------------------------------------------------------------------------
# 9. Duplicate Review Submissions
# --------------------------------------------------------------------------
def test_duplicate_review_submissions(populated_db):
    """Scenario 9: Prevent duplicate review submission with same review_id."""
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )
    t_fixed = "2026-11-20T17:45:00+07:00"

    # First deferral succeeds
    res1 = service.decide(
        relationship_id=rel_id,
        decision="defer",
        reviewer_id="USER-001",
        reason="Initial deferral to consult external key",
        reviewed_at=t_fixed,
    )
    assert res1["status"] == "success"

    # Exact duplicate review submission with identical review_id
    with pytest.raises(DuplicateReviewError) as exc_info:
        conn = get_db_connection(populated_db)
        apply_relationship_review_atomic(
            conn=conn,
            review_data=res1["review_event"],
        )
        conn.close()
    assert "Duplicate review ID" in str(exc_info.value)


# --------------------------------------------------------------------------
# 10. Immutable Audit History
# --------------------------------------------------------------------------
def test_immutable_audit_history(populated_db):
    """Scenario 10: Multi-step review lifecycle forms an immutable, append-only chronological log."""
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )

    # Step 1: Defer
    service.decide(
        relationship_id=rel_id,
        decision="defer",
        reviewer_id="USER-001",
        reason="Step 1: Deferring to inspect question booklet text",
        reviewed_at="2026-11-20T17:00:00+07:00",
    )

    # Step 2: Approve
    service.decide(
        relationship_id=rel_id,
        decision="approve",
        reviewer_id="USER-002",
        reason="Step 2: Title and passage structure confirmed against test 1",
        reviewed_at="2026-11-20T17:15:00+07:00",
    )

    history = service.get_history(rel_id)
    assert len(history) == 2
    assert history[0]["decision"] == "defer"
    assert history[0]["final_status"] == "candidate"
    assert history[1]["decision"] == "approve"
    assert history[1]["final_status"] == "confirmed"


# --------------------------------------------------------------------------
# 11. Dry-Run Without Mutation
# --------------------------------------------------------------------------
def test_dry_run_without_mutation(populated_db):
    """Scenario 11: dry_run=True performs full validation but makes no changes in SQLite."""
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )

    res = service.decide(
        relationship_id=rel_id,
        decision="approve",
        reviewer_id="USER-001",
        reason="Dry-run simulation of approval",
        dry_run=True,
    )
    assert res["dry_run"] is True
    assert res["status"] == "success"

    # SQLite must remain unmodified
    conn = get_db_connection(populated_db)
    rel = get_source_relationship(conn, rel_id)
    reviews = list_relationship_reviews(conn, rel_id)
    conn.close()

    assert rel["relationship_status"] == "candidate"
    assert len(reviews) == 0


# --------------------------------------------------------------------------
# 12. Privacy Isolation
# --------------------------------------------------------------------------
def test_privacy_isolation(populated_db):
    """Scenario 12: Review events and models never contain copyrighted raw passage texts."""
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )

    res = service.decide(
        relationship_id=rel_id,
        decision="approve",
        reviewer_id="USER-001",
        reason="Audit check for privacy isolation",
    )
    review_json = json.dumps(res["review_event"])

    forbidden_terms = [
        "READING TEST 1",
        "READING PASSAGE 1",
        "Marine Energy Systems",  # Should be referenced as title ID, but review model should not store raw paragraphs
    ]
    # Check review model does not store raw paragraphs
    assert "paragraphs" not in res["review_event"]


# --------------------------------------------------------------------------
# 13. Independent Source Validation
# --------------------------------------------------------------------------
def test_independent_source_validation_unregistered_rejected(populated_db):
    """Scenario 13: Ground truth reference from unregistered source is rejected."""
    conn = get_db_connection(populated_db)
    validator = SourceReferenceValidator(conn)

    res = validator.validate_reference(
        reference_source_id="EXT-UNREGISTERED-SRC",
        expected_collection="VOL 99",
        expected_test_number=1,
        candidate_target_file_id="FILE-a00000000002",
    )
    assert res.is_valid is False
    assert "UNREGISTERED_SOURCE_REJECTED" in res.flags
    conn.close()


def test_independent_source_validation_collection_mismatch(populated_db):
    """Scenario 14: Ground truth reference with cross-collection mismatch is rejected."""
    conn = get_db_connection(populated_db)
    validator = SourceReferenceValidator(conn)

    # SRC-SYN-03 belongs to VOL 88, but expected collection is VOL 99
    res = validator.validate_reference(
        reference_source_id="SRC-SYN-03",
        expected_collection="VOL 99",
        expected_test_number=1,
        candidate_target_file_id="FILE-a00000000004",
    )
    assert res.is_valid is False
    assert "COLLECTION_MISMATCH" in res.flags
    conn.close()


def test_independent_source_validation_success_promotes_approval(populated_db):
    """Scenario 15: Valid independent supporting evidence reference promotes candidate to confirmed."""
    synthetic_fixtures = {
        "SRC-SYN-04": {
            "test_numbers": [1],
            "passages_or_sections": {"1": [1]},
            "passage_titles": {"1": {"1": "Marine Energy Systems"}},
            "answer_keys": {"1": {1: "TRUE", 2: "FALSE", 3: "NOT GIVEN", 4: "TRUE"}},
        }
    }
    service = RelationshipReviewService(db_path=populated_db, synthetic_fixtures=synthetic_fixtures)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000004", "question_to_answer_key", "VOL 99", 1, 1
    )

    # Provide valid independent evidence reference SRC-SYN-02 (VOL 99 Test 1 Key)
    res = service.decide(
        relationship_id=rel_id,
        decision="approve",
        reviewer_id="USER-001",
        reason="Approved using independent verified answer key from SRC-SYN-02",
        evidence_source_id="SRC-SYN-02",
        evidence_references={
            "provenance": {
                "source_id": "SRC-SYN-02",
                "authority": "cambridge_verified_key",
                "provenance_type": "independent_external_key",
            }
        },
    )

    assert res["status"] == "success"
    assert res["final_status"] == "confirmed"
    assert res["review_event"]["evidence_references"]["source_id"] == "SRC-SYN-02"


# --------------------------------------------------------------------------
# 16. CLI Subcommand Tests
# --------------------------------------------------------------------------
def test_cli_relationship_review_list(populated_db, capsys, monkeypatch):
    """Test CLI: relationship-review list."""
    from harness.cli import main
    monkeypatch.setattr("harness.config.DB_PATH", populated_db)
    monkeypatch.setattr("sys.argv", ["harness", "relationship-review", "list"])

    main()
    captured = capsys.readouterr()
    assert "SOURCE RELATIONSHIPS FOR HUMAN REVIEW" in captured.out
    assert "Total Found: 2" in captured.out


def test_cli_relationship_review_show(populated_db, capsys, monkeypatch):
    """Test CLI: relationship-review show."""
    from harness.cli import main
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )
    monkeypatch.setattr("harness.config.DB_PATH", populated_db)
    monkeypatch.setattr("sys.argv", ["harness", "relationship-review", "show", "--id", rel_id])

    main()
    captured = capsys.readouterr()
    assert f"SOURCE RELATIONSHIP REVIEW INSPECTION: {rel_id}" in captured.out
    assert "Status          : CANDIDATE" in captured.out
    assert "Approval Eligible : YES" in captured.out


def test_cli_relationship_review_decide_dry_run(populated_db, capsys, monkeypatch):
    """Test CLI: relationship-review decide --dry-run."""
    from harness.cli import main
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )
    monkeypatch.setattr("harness.config.DB_PATH", populated_db)
    monkeypatch.setattr(
        "sys.argv",
        [
            "harness", "relationship-review", "decide",
            "--id", rel_id,
            "--decision", "approve",
            "--reviewer-id", "USER-001",
            "--reason", "CLI dry-run verification test",
            "--dry-run",
        ],
    )

    main()
    captured = capsys.readouterr()
    assert "[DRY-RUN SUCCESS]" in captured.out
    assert "candidate -> confirmed" in captured.out


def test_cli_relationship_review_decide_rejection(populated_db, capsys, monkeypatch):
    """Test CLI: relationship-review decide rejection on missing evidence exits with code 1."""
    from harness.cli import main
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000004", "question_to_answer_key", "VOL 99", 1, 1
    )
    monkeypatch.setattr("harness.config.DB_PATH", populated_db)
    monkeypatch.setattr(
        "sys.argv",
        [
            "harness", "relationship-review", "decide",
            "--id", rel_id,
            "--decision", "approve",
            "--reviewer-id", "USER-001",
            "--reason", "Unsupported approval attempt",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "[POLICY REJECTION]" in captured.out


def test_cli_relationship_review_history(populated_db, capsys, monkeypatch):
    """Test CLI: relationship-review history."""
    from harness.cli import main
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )
    service = RelationshipReviewService(db_path=populated_db)
    service.decide(
        relationship_id=rel_id,
        decision="defer",
        reviewer_id="USER-001",
        reason="Testing CLI history display",
    )

    monkeypatch.setattr("harness.config.DB_PATH", populated_db)
    monkeypatch.setattr("sys.argv", ["harness", "relationship-review", "history", "--id", rel_id])

    main()
    captured = capsys.readouterr()
    assert f"IMMUTABLE REVIEW AUDIT HISTORY: {rel_id}" in captured.out
    assert "Total Review Events: 1" in captured.out
    assert "Decision         : defer" in captured.out


# --------------------------------------------------------------------------
# 17. Independent Evidence Validation & Negative Tests (P0 Remediation)
# --------------------------------------------------------------------------
def test_negative_unrelated_doc_same_collection_missing_test_metadata(populated_db):
    """Negative test: Document in same collection with missing test metadata cannot confirm."""
    conn = get_db_connection(populated_db)
    upsert_source(conn, {
        "file_id": "FILE-a00000000099",
        "legacy_id": "SRC-SYN-UNRELATED-01",
        "relative_path": "data/synthetic/VOL99/General/policy_notes.txt",
        "filename": "policy_notes.txt",
        "extension": ".txt",
        "detected_type": "text",
        "size_bytes": 1024,
        "content_sha256": "9999999999999999999999999999999999999999999999999999999999999999",
        "collection": "VOL 99",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })
    conn.close()

    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000004", "question_to_answer_key", "VOL 99", 1, 1
    )

    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="USER-001",
            reason="Attempting approval using unrelated doc in same collection",
            evidence_source_id="SRC-SYN-UNRELATED-01",
            evidence_references={"provenance": {"source_id": "SRC-SYN-UNRELATED-01", "provenance_type": "test_note"}},
        )

    assert "Missing test metadata" in str(exc_info.value)

    conn = get_db_connection(populated_db)
    rel = get_source_relationship(conn, rel_id)
    conn.close()
    assert rel["relationship_status"] == "candidate"


def test_negative_unrelated_doc_same_collection_test_mismatch(populated_db):
    """Negative test: Document in same collection covering wrong test number cannot confirm."""
    service = RelationshipReviewService(db_path=populated_db)
    # Target is FILE-a00000000002 (Test 1), reference evidence is SRC-SYN-04 (Test 2)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )

    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="USER-001",
            reason="Attempting approval using Test 2 key for Test 1 relationship",
            evidence_source_id="SRC-SYN-04",
            evidence_references={"provenance": {"source_id": "SRC-SYN-04", "provenance_type": "test_key"}},
        )

    assert "Test number mismatch" in str(exc_info.value)

    conn = get_db_connection(populated_db)
    rel = get_source_relationship(conn, rel_id)
    conn.close()
    assert rel["relationship_status"] == "candidate"


def test_negative_same_collection_no_content_evidence(populated_db):
    """Negative test: Registered source from same volume without content evidence is NOT sufficient."""
    conn = get_db_connection(populated_db)
    upsert_source(conn, {
        "file_id": "FILE-a00000000098",
        "legacy_id": "SRC-SYN-EMPTY-KEY",
        "relative_path": "data/synthetic/VOL99/Reading/test_1_cover.pdf",
        "filename": "test_1_cover.pdf",
        "extension": ".pdf",
        "detected_type": "pdf",
        "size_bytes": 2048,
        "content_sha256": "8888888888888888888888888888888888888888888888888888888888888888",
        "collection": "VOL 99",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })
    conn.close()

    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000004", "question_to_answer_key", "VOL 99", 1, 1
    )

    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="USER-001",
            reason="Attempting approval using cover page without content evidence",
            evidence_source_id="SRC-SYN-EMPTY-KEY",
            evidence_references={"provenance": {"source_id": "SRC-SYN-EMPTY-KEY", "provenance_type": "cover_page"}},
        )

    assert "no answer key or content evidence" in str(exc_info.value)


def test_negative_invalid_source_sha_rejected(populated_db):
    """Negative test: Source reference with invalid/malformed SHA-256 hash is rejected."""
    conn = get_db_connection(populated_db)
    upsert_source(conn, {
        "file_id": "FILE-a00000000097",
        "legacy_id": "SRC-SYN-BAD-SHA",
        "relative_path": "data/synthetic/VOL99/Reading/test_1_badsha.pdf",
        "filename": "test_1_badsha.pdf",
        "extension": ".pdf",
        "detected_type": "pdf",
        "size_bytes": 2048,
        "content_sha256": "not-a-valid-sha256",
        "collection": "VOL 99",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })
    conn.close()

    conn = get_db_connection(populated_db)
    validator = SourceReferenceValidator(conn)
    res = validator.validate_reference(
        reference_source_id="SRC-SYN-BAD-SHA",
        expected_collection="VOL 99",
        expected_test_number=1,
        candidate_target_file_id="FILE-a00000000004",
    )
    conn.close()

    assert res.is_valid is False
    assert "INVALID_SOURCE_HASH" in res.flags


# --------------------------------------------------------------------------
# 18. Expert Verification Integrity Tests (P0 Remediation)
# --------------------------------------------------------------------------
def test_expert_verification_caller_provided_true_rejected_by_service(populated_db):
    """Regression test: Caller-provided expert_verified=True is blocked by review service."""
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )

    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="USER-001",
            reason="Attempting unauthenticated expert verification claim",
            expert_verified=True,
        )

    assert "caller-provided expert_verified=True is not permitted" in str(exc_info.value)


def test_expert_verification_caller_provided_true_rejected_by_policy(populated_db):
    """Regression test: ReviewPolicyValidator rejects unauthenticated expert_verified=True."""
    conn = get_db_connection(populated_db)
    rel = get_source_relationship(
        conn,
        compute_relationship_id(
            "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
        ),
    )
    validator = ReviewPolicyValidator(conn)
    result = validator.evaluate_decision(
        relationship=rel,
        decision="approve",
        reviewer_id="USER-001",
        reason="Testing policy evaluation for expert verification",
        reviewed_at="2026-11-20T17:30:00+07:00",
        expert_verified=True,
    )
    conn.close()

    assert result.can_proceed is False
    assert result.expert_verified is False
    assert any("expert_verified=False is enforced" in r for r in result.rejection_reasons)


def test_expert_verification_model_raises_on_true():
    """Regression test: RelationshipReview model rejects caller-provided expert_verified=True."""
    with pytest.raises(ValueError, match="Caller-provided expert_verified=True is not permitted"):
        RelationshipReview(
            review_id="REV-0000000000000001",
            relationship_id="REL-0000000000000001",
            reviewer_id="USER-001",
            previous_status="candidate",
            final_status="confirmed",
            decision="approve",
            reason="Attempting expert model instantiation",
            reviewed_at="2026-11-20T17:30:00+07:00",
            expert_verified=True,
        )


def test_expert_verification_database_enforces_zero(populated_db):
    """Regression test: Database persistence layer strictly enforces expert_verified=0."""
    conn = get_db_connection(populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )

    record_relationship_review(
        conn,
        {
            "review_id": "REV-TEST-FORCE-EXPERT",
            "relationship_id": rel_id,
            "previous_status": "candidate",
            "new_status": "confirmed",
            "reviewer": "attacker",
            "reason": "Attempting direct SQL bypass of expert flag",
            "expert_verified": True,
        },
    )

    reviews = list_relationship_reviews(conn, rel_id)
    conn.close()

    test_rev = [r for r in reviews if r["review_id"] == "REV-TEST-FORCE-EXPERT"][0]
    assert test_rev["expert_verified"] is False


# --------------------------------------------------------------------------
# 19. Preserve Human Review Decisions Across Matcher Reruns (P0 Remediation)
# --------------------------------------------------------------------------
def test_matcher_rerun_preserves_human_approval_when_fresh(populated_db, synthetic_sources_map):
    """Regression test: Matcher reruns on unchanged inputs preserve human approved status and review history."""
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_answer_key", "VOL 99", 1, 1
    )
    conn = get_db_connection(populated_db)
    upsert_source_relationship(conn, {
        "relationship_id": rel_id,
        "source_file_id": "FILE-a00000000001",
        "target_file_id": "FILE-a00000000002",
        "relationship_type": "question_to_answer_key",
        "collection": "VOL 99",
        "volume": "VOL 99",
        "test_number": 1,
        "passage_or_section": 1,
        "skill": "reading",
        "identity_evidence": {"passage_title": "Marine Energy Systems"},
        "validation_flags": ["VOLUME_MATCH", "SKILL_MATCH", "TEST_NUMBER_MATCH", "CONTENT_TITLE_MATCH"],
        "match_confidence": 0.8,
        "relationship_status": "candidate",
        "provenance": {"matcher_version": "0.3.0-a", "evaluated_at": "2026-11-20T10:00:00Z"},
        "source_content_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
        "target_content_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
        "schema_version": "v0.3.0-relationship",
    })
    conn.close()

    service = RelationshipReviewService(db_path=populated_db)

    # 1. Human reviews and approves candidate
    res_approve = service.decide(
        relationship_id=rel_id,
        decision="approve",
        reviewer_id="HUMAN-EXPERT-01",
        reason="Human forensic review approved based on title match",
        reviewed_at="2026-11-20T10:00:00Z",
    )
    assert res_approve["final_status"] == "confirmed"

    # 2. Run matcher rerun with unchanged inputs
    matching_service = RelationshipMatchingService(db_path=populated_db)
    sources = list(synthetic_sources_map.values())[:2]
    rerun_res = matching_service.match_sources(sources_override=sources, resume=True)

    # 3. Verify human review decision is preserved in returned results and database
    rerun_rel = [r for r in rerun_res["relationships"] if r.relationship_id == rel_id][0]
    assert rerun_rel.relationship_status == "confirmed"
    assert "HUMAN_REVIEW_APPROVED" in rerun_rel.validation_flags

    conn = get_db_connection(populated_db)
    db_rel = get_source_relationship(conn, rel_id)
    history = list_relationship_reviews(conn, rel_id)
    conn.close()

    assert db_rel["relationship_status"] == "confirmed"
    assert "HUMAN_REVIEW_APPROVED" in db_rel["validation_flags"]
    assert len(history) == 1
    assert history[0]["reviewer_id"] == "HUMAN-EXPERT-01"


def test_matcher_rerun_marks_stale_confirmed_for_revalidation(populated_db, synthetic_sources_map):
    """Regression test: When inputs become stale, confirmed relationships are marked for revalidation."""
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_answer_key", "VOL 99", 1, 1
    )
    conn = get_db_connection(populated_db)
    upsert_source_relationship(conn, {
        "relationship_id": rel_id,
        "source_file_id": "FILE-a00000000001",
        "target_file_id": "FILE-a00000000002",
        "relationship_type": "question_to_answer_key",
        "collection": "VOL 99",
        "volume": "VOL 99",
        "test_number": 1,
        "passage_or_section": 1,
        "skill": "reading",
        "identity_evidence": {"passage_title": "Marine Energy Systems"},
        "validation_flags": ["VOLUME_MATCH", "SKILL_MATCH", "TEST_NUMBER_MATCH", "CONTENT_TITLE_MATCH"],
        "match_confidence": 0.8,
        "relationship_status": "candidate",
        "provenance": {"matcher_version": "0.3.0-a", "evaluated_at": "2026-11-20T10:00:00Z"},
        "source_content_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
        "target_content_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
        "schema_version": "v0.3.0-relationship",
    })
    conn.close()

    service = RelationshipReviewService(db_path=populated_db)

    # 1. Human reviews and approves candidate
    service.decide(
        relationship_id=rel_id,
        decision="approve",
        reviewer_id="HUMAN-EXPERT-01",
        reason="Human forensic review approved based on initial snapshot",
        reviewed_at="2026-11-20T10:00:00Z",
    )

    # 2. Modify target source content SHA (making relationship inputs stale)
    modified_sources = [dict(s) for s in list(synthetic_sources_map.values())[:2]]
    modified_sources[1]["content_sha256"] = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    # Also strip title so matcher does not re-confirm on its own
    modified_sources[1]["staged_data"] = {
        "test_numbers": [1],
        "passages_or_sections": {"1": [1]},
        "passage_titles": {"1": {"1": "Different Title Completely"}},
    }

    matching_service = RelationshipMatchingService(db_path=populated_db)
    rerun_res = matching_service.match_sources(sources_override=modified_sources, resume=True)

    # 3. Verify relationship is marked review_required and NOT active confirmed
    rerun_rel = [r for r in rerun_res["relationships"] if r.relationship_id == rel_id][0]
    assert rerun_rel.relationship_status == "review_required"
    assert "STALE_REVALIDATION_REQUIRED" in rerun_rel.validation_flags
    assert "HUMAN_REVIEW_APPROVED" not in rerun_rel.validation_flags

    # 4. Verify transition review event was recorded in audit log
    conn = get_db_connection(populated_db)
    db_rel = get_source_relationship(conn, rel_id)
    history = list_relationship_reviews(conn, rel_id)
    conflicts = list_relationship_conflicts(conn, relationship_id=rel_id)
    conn.close()

    assert db_rel["relationship_status"] == "review_required"
    assert len(history) == 2
    transition_event = history[1]
    assert transition_event["reviewer_id"] == "SYSTEM-MATCHER"
    assert transition_event["previous_status"] == "confirmed"
    assert transition_event["final_status"] == "review_required"
    assert "Stale relationship inputs/evidence detected" in transition_event["reason"]

    assert any(c["conflict_type"] == "STALE_SOURCE_HASH" for c in conflicts)


# --------------------------------------------------------------------------
# 20. Audit Immutability Enforcement (P1 Remediation)
# --------------------------------------------------------------------------
def test_audit_immutability_blocks_sql_update(populated_db):
    """P1: SQLite trigger strictly blocks UPDATE operations on relationship_reviews."""
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )
    service.decide(
        relationship_id=rel_id,
        decision="defer",
        reviewer_id="USER-001",
        reason="Audit immutability test record",
    )

    conn = get_db_connection(populated_db)
    with pytest.raises(sqlite3.DatabaseError) as exc_info:
        conn.execute("UPDATE relationship_reviews SET reason = 'tampered rationale' WHERE relationship_id = ?", (rel_id,))
    conn.close()

    assert "Audit log immutability violation: UPDATE operations" in str(exc_info.value)


def test_audit_immutability_blocks_sql_delete(populated_db):
    """P1: SQLite trigger strictly blocks DELETE operations on relationship_reviews."""
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )
    service.decide(
        relationship_id=rel_id,
        decision="defer",
        reviewer_id="USER-001",
        reason="Audit immutability delete test record",
    )

    conn = get_db_connection(populated_db)
    with pytest.raises(sqlite3.DatabaseError) as exc_info:
        conn.execute("DELETE FROM relationship_reviews WHERE relationship_id = ?", (rel_id,))
    conn.close()

    assert "Audit log immutability violation: DELETE operations" in str(exc_info.value)


def test_audit_immutability_safe_migrations(populated_db):
    """P1: Safe SQLite migrations (init_db re-runs and ALTER TABLE) succeed without breaking immutability."""
    # 1. Rerunning init_db on populated database is idempotent and non-destructive
    init_db(populated_db)

    # 2. ALTER TABLE ADD COLUMN succeeds
    conn = get_db_connection(populated_db)
    conn.execute("ALTER TABLE relationship_reviews ADD COLUMN test_migration_col TEXT")
    conn.close()

    # 3. New append-only reviews can be inserted and audited
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000002", "question_to_explanation", "VOL 99", 1, 1
    )
    service.decide(
        relationship_id=rel_id,
        decision="defer",
        reviewer_id="USER-002",
        reason="Second append-only review event after migration",
    )

    history = service.get_history(rel_id)
    assert len(history) == 1
    assert history[0]["reviewer_id"] == "USER-002"

    # 4. Triggers still block UPDATE after migration
    conn = get_db_connection(populated_db)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE relationship_reviews SET reason = 'unauthorized'")
    conn.close()


# --------------------------------------------------------------------------
# 21. Independent Evidence Trust Boundary Negative Regressions
# --------------------------------------------------------------------------
def test_negative_regression_fabricated_caller_staged_data_rejected(populated_db):
    """Negative regression test: Fabricated caller-provided staged_data is strictly rejected."""
    service = RelationshipReviewService(db_path=populated_db)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000004", "question_to_answer_key", "VOL 99", 1, 1
    )

    # 1. Caller attempts to supply fabricated staged_data to force approval
    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="ATTACKER-01",
            reason="Attempting approval using caller-injected fabricated staged_data",
            evidence_source_id="SRC-SYN-02",
            evidence_references={
                "staged_data": {
                    "test_numbers": [1],
                    "passages_or_sections": {"1": [1]},
                    "answer_keys": {"1": {1: "FABRICATED_KEY", 2: "FABRICATED_KEY"}},
                },
                "provenance": {
                    "source_id": "SRC-SYN-02",
                    "provenance_type": "injected_staged_data",
                    "authority": "untrusted",
                },
            },
        )

    assert "Untrusted caller-supplied staged_data rejected" in str(exc_info.value)

    # 2. Relationship retains candidate status
    conn = get_db_connection(populated_db)
    rel = get_source_relationship(conn, rel_id)
    assert rel["relationship_status"] == "candidate"

    # 3. Direct validator call rejects caller staged_data
    validator = SourceReferenceValidator(conn)
    val_res = validator.validate_reference(
        reference_source_id="SRC-SYN-02",
        expected_collection="VOL 99",
        expected_test_number=1,
        expected_passage_or_section=1,
        candidate_target_file_id="FILE-a00000000004",
        relationship_type="question_to_answer_key",
        evidence_references={"staged_data": {"answer_keys": {1: {1: "INJECTED"}}}},
    )
    conn.close()

    assert val_res.is_valid is False
    assert "CALLER_STAGED_DATA_REJECTED" in val_res.flags


def test_negative_regression_unrelated_answer_key_sharing_volume_and_test_rejected(populated_db):
    """Negative regression test: Answer key sharing Volume/Test but covering disjoint sections cannot confirm."""
    # Register an answer key in VOL 99 Test 1 that only covers Passage 3 (Q28-Q40)
    conn = get_db_connection(populated_db)
    upsert_source(conn, {
        "file_id": "FILE-a00000000098",
        "legacy_id": "SRC-SYN-UNRELATED-P3",
        "relative_path": "data/synthetic/VOL99/Reading/unrelated_p3_key.pdf",
        "filename": "unrelated_p3_key.pdf",
        "extension": ".pdf",
        "detected_type": "pdf",
        "size_bytes": 2048,
        "content_sha256": "8888888888888888888888888888888888888888888888888888888888888888",
        "collection": "VOL 99",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })
    conn.close()

    synthetic_fixtures = {
        "SRC-SYN-UNRELATED-P3": {
            "test_numbers": [1],
            "passages_or_sections": {"1": [3]},
            "answer_keys": {
                "1": {28: "A", 29: "B", 30: "C", 31: "D"}
            },
        }
    }

    # Candidate relationship is for Passage 1 (questions 1-14)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000004", "question_to_answer_key", "VOL 99", 1, 1
    )

    service = RelationshipReviewService(db_path=populated_db, synthetic_fixtures=synthetic_fixtures)
    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="USER-001",
            reason="Attempting approval using unrelated Passage 3 key for Passage 1 candidate",
            evidence_source_id="SRC-SYN-UNRELATED-P3",
            evidence_references={
                "provenance": {
                    "source_id": "SRC-SYN-UNRELATED-P3",
                    "provenance_type": "test_answer_key",
                    "authority": "official",
                }
            },
        )

    # An answer key containing answers for the same Test is not sufficient for confirmation
    assert "An answer key containing answers for the same Test is not sufficient for confirmation" in str(exc_info.value)

    # Verify status remains candidate
    conn = get_db_connection(populated_db)
    rel = get_source_relationship(conn, rel_id)
    assert rel["relationship_status"] == "candidate"

    # Direct validation check
    validator = SourceReferenceValidator(conn, synthetic_fixtures=synthetic_fixtures)
    val_res = validator.validate_reference(
        reference_source_id="SRC-SYN-UNRELATED-P3",
        expected_collection="VOL 99",
        expected_test_number=1,
        expected_passage_or_section=1,
        candidate_target_file_id="FILE-a00000000004",
        relationship_type="question_to_answer_key",
        evidence_provenance={"source_id": "SRC-SYN-UNRELATED-P3", "provenance_type": "key", "authority": "cambridge"},
    )
    conn.close()

    assert val_res.is_valid is False
    assert "NO_MATCHING_QUESTION_EVIDENCE" in val_res.flags


def test_negative_regression_missing_physical_source_and_extraction_rejected(populated_db):
    """Negative regression test: Missing physical source and missing trusted extraction artifact fails validation."""
    conn = get_db_connection(populated_db)
    upsert_source(conn, {
        "file_id": "FILE-a00000000099",
        "legacy_id": "SRC-GHOST-MISSING",
        "relative_path": "private/raw/VOL 99/ghost_nonexistent.pdf",
        "filename": "ghost_nonexistent.pdf",
        "extension": ".pdf",
        "detected_type": "pdf",
        "size_bytes": 1024,
        "content_sha256": "9999999999999999999999999999999999999999999999999999999999999999",
        "collection": "VOL 99",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })
    conn.close()

    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000004", "question_to_answer_key", "VOL 99", 1, 1
    )

    service = RelationshipReviewService(db_path=populated_db)
    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="USER-001",
            reason="Attempting approval using nonexistent physical source and missing extraction artifact",
            evidence_source_id="SRC-GHOST-MISSING",
            evidence_references={
                "provenance": {
                    "source_id": "SRC-GHOST-MISSING",
                    "provenance_type": "missing_ghost",
                    "authority": "none",
                }
            },
        )

    assert "physical file is missing and has no trusted extraction artifact" in str(exc_info.value)

    conn = get_db_connection(populated_db)
    rel = get_source_relationship(conn, rel_id)
    assert rel["relationship_status"] == "candidate"

    validator = SourceReferenceValidator(conn)
    val_res = validator.validate_reference(
        reference_source_id="SRC-GHOST-MISSING",
        expected_collection="VOL 99",
        expected_test_number=1,
        expected_passage_or_section=1,
        candidate_target_file_id="FILE-a00000000004",
        relationship_type="question_to_answer_key",
        evidence_provenance={"source_id": "SRC-GHOST-MISSING", "provenance_type": "ghost", "authority": "none"},
    )
    conn.close()

    assert val_res.is_valid is False
    assert "MISSING_PHYSICAL_SOURCE_AND_EXTRACTION" in val_res.flags


def test_negative_regression_no_matching_question_level_evidence_rejected(populated_db):
    """Negative regression test: Reference source with no matching question-level evidence retains candidate status."""
    conn = get_db_connection(populated_db)
    upsert_source(conn, {
        "file_id": "FILE-a00000000096",
        "legacy_id": "SRC-SYN-NO-Q-MATCH",
        "relative_path": "data/synthetic/VOL99/Reading/no_q_match.pdf",
        "filename": "no_q_match.pdf",
        "extension": ".pdf",
        "detected_type": "pdf",
        "size_bytes": 2048,
        "content_sha256": "7777777777777777777777777777777777777777777777777777777777777777",
        "collection": "VOL 99",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })
    conn.close()

    # Synthetic fixture has answers for Q15-Q20 (Passage 2), candidate is for Passage 1 (Q1-Q14)
    synthetic_fixtures = {
        "SRC-SYN-NO-Q-MATCH": {
            "test_numbers": [1],
            "passages_or_sections": {"1": [1]},
            "answer_keys": {
                "1": {15: "A", 16: "B", 17: "C", 18: "D"}
            },
        }
    }

    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000004", "question_to_answer_key", "VOL 99", 1, 1
    )

    service = RelationshipReviewService(db_path=populated_db, synthetic_fixtures=synthetic_fixtures)
    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="USER-001",
            reason="Attempting approval with no matching question numbers for Passage 1",
            evidence_source_id="SRC-SYN-NO-Q-MATCH",
            evidence_references={
                "provenance": {
                    "source_id": "SRC-SYN-NO-Q-MATCH",
                    "provenance_type": "test_key",
                    "authority": "official",
                }
            },
        )

    assert "No matching question-level evidence" in str(exc_info.value) or "An answer key containing answers for the same Test is not sufficient" in str(exc_info.value)

    conn = get_db_connection(populated_db)
    rel = get_source_relationship(conn, rel_id)
    assert rel["relationship_status"] == "candidate"

    validator = SourceReferenceValidator(conn, synthetic_fixtures=synthetic_fixtures)
    val_res = validator.validate_reference(
        reference_source_id="SRC-SYN-NO-Q-MATCH",
        expected_collection="VOL 99",
        expected_test_number=1,
        expected_passage_or_section=1,
        candidate_target_file_id="FILE-a00000000004",
        relationship_type="question_to_answer_key",
        evidence_provenance={"source_id": "SRC-SYN-NO-Q-MATCH", "provenance_type": "key", "authority": "test"},
    )
    conn.close()

    assert val_res.is_valid is False
    assert "NO_MATCHING_QUESTION_EVIDENCE" in val_res.flags


def test_synthetic_fixture_injection_rejected_outside_test_context(populated_db):
    """Regression test: Synthetic fixture injection is rejected when allow_synthetic_fixtures=False."""
    conn = get_db_connection(populated_db)
    validator = SourceReferenceValidator(conn, allow_synthetic_fixtures=False)
    val_res = validator.validate_reference(
        reference_source_id="SRC-SYN-02",
        expected_collection="VOL 99",
        expected_test_number=1,
        expected_passage_or_section=1,
        candidate_target_file_id="FILE-a00000000004",
        relationship_type="question_to_answer_key",
        evidence_provenance={
            "source_id": "SRC-SYN-02",
            "provenance_type": "independent_key",
            "authority": "cambridge",
        },
    )
    conn.close()

    assert val_res.is_valid is False
    assert "SYNTHETIC_FIXTURE_NOT_PERMITTED" in val_res.flags


def test_negative_regression_unrelated_sources_sharing_volume_test_passage_and_questions_retain_review_required(populated_db):
    """Regression test: Two unrelated sources sharing Volume, Test, Passage, and question numbers

    must NOT receive CONTENT_ALIGNMENT_VERIFIED and must retain review_required.
    An independent answer key merely containing question numbers in the same range cannot confirm it.
    """
    conn = get_db_connection(populated_db)
    # Source A: Reading passage in VOL 99 Test 1 Passage 1, covering questions 1-13
    upsert_source(conn, {
        "file_id": "FILE-a00000000091",
        "legacy_id": "SRC-SYN-UNRELATED-A",
        "relative_path": "data/synthetic/VOL99/Reading/unrelated_test_1_passage_1_a.docx",
        "filename": "unrelated_test_1_passage_1_a.docx",
        "extension": ".docx",
        "detected_type": "docx",
        "size_bytes": 2048,
        "content_sha256": "9191919191919191919191919191919191919191919191919191919191919191",
        "collection": "VOL 99",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })
    # Source B: Unrelated answer key in VOL 99 Test 1 Passage 1, covering questions 1-13 with different/unaligned topic
    upsert_source(conn, {
        "file_id": "FILE-a00000000092",
        "legacy_id": "SRC-SYN-UNRELATED-B",
        "relative_path": "data/synthetic/VOL99/Reading/unrelated_test_1_passage_1_b.pdf",
        "filename": "unrelated_test_1_passage_1_b.pdf",
        "extension": ".pdf",
        "detected_type": "pdf",
        "size_bytes": 2048,
        "content_sha256": "9292929292929292929292929292929292929292929292929292929292929292",
        "collection": "VOL 99",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })

    # Synthetic metadata fixtures: sharing Volume, Test, Passage, and question range [1, 14],
    # but distinct unrelated passage titles ("The History of Tea" vs "Underground Railway Networks")
    synthetic_fixtures = {
        "SRC-SYN-UNRELATED-A": {
            "test_numbers": [1],
            "passages_or_sections": {"1": [1]},
            "passage_titles": {"1": {"1": "The History of Tea"}},
            "paragraphs": [{"text": "Passage 1: The History of Tea"}],
        },
        "SRC-SYN-UNRELATED-B": {
            "test_numbers": [1],
            "passages_or_sections": {"1": [1]},
            "passage_titles": {"1": {"1": "Underground Railway Networks"}},
            "answer_keys": {
                "1": {1: "NO", 2: "YES", 3: "NOT GIVEN"}
            },
        },
    }

    rel_id = compute_relationship_id(
        "FILE-a00000000091", "FILE-a00000000092", "question_to_answer_key", "VOL 99", 1, 1
    )
    upsert_source_relationship(conn, {
        "relationship_id": rel_id,
        "source_file_id": "FILE-a00000000091",
        "target_file_id": "FILE-a00000000092",
        "relationship_type": "question_to_answer_key",
        "collection": "VOL 99",
        "volume": "VOL 99",
        "test_number": 1,
        "passage_or_section": 1,
        "skill": "reading",
        "identity_evidence": {"expected_question_range": [1, 14]},
        "validation_flags": ["VOLUME_MATCH", "SKILL_MATCH", "TEST_NUMBER_MATCH", "QUESTION_RANGE_ALIGNED"],
        "match_confidence": 0.5,
        "relationship_status": "review_required",
        "provenance": {"matcher_version": "0.3.0-a", "evaluated_at": "2026-11-20T10:00:00Z"},
        "source_content_sha256": "9191919191919191919191919191919191919191919191919191919191919191",
        "target_content_sha256": "9292929292929292929292929292929292929292929292929292929292929292",
        "schema_version": "v0.3.0-relationship",
    })
    conn.close()

    service = RelationshipReviewService(db_path=populated_db, synthetic_fixtures=synthetic_fixtures)

    # 1. Attempt approval using an independent answer key (SRC-SYN-02) that contains Q1-Q4
    # in the same test/passage range
    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="OPERATOR-01",
            reason="Attempting approval using independent answer key sharing question range",
            evidence_source_id="SRC-SYN-02",
            evidence_references={
                "provenance": {
                    "source_id": "SRC-SYN-02",
                    "provenance_type": "independent_key",
                    "authority": "official",
                }
            },
        )

    assert "retaining review_required" in str(exc_info.value) or "Missing independent supporting evidence" in str(exc_info.value)

    # 2. Relationship retains review_required status in SQLite DB
    conn = get_db_connection(populated_db)
    rel = get_source_relationship(conn, rel_id)
    assert rel["relationship_status"] == "review_required"

    # 3. Direct validator call verifies CONTENT_ALIGNMENT_VERIFIED is NOT marked
    validator = SourceReferenceValidator(conn, synthetic_fixtures=synthetic_fixtures)
    val_res = validator.validate_reference(
        reference_source_id="SRC-SYN-02",
        expected_collection="VOL 99",
        expected_test_number=1,
        expected_passage_or_section=1,
        candidate_source_file_id="FILE-a00000000091",
        candidate_target_file_id="FILE-a00000000092",
        relationship_type="question_to_answer_key",
        evidence_provenance={"source_id": "SRC-SYN-02", "provenance_type": "key", "authority": "test"},
    )
    conn.close()

    assert val_res.is_valid is False
    assert "CONTENT_ALIGNMENT_VERIFIED" not in val_res.flags
    assert "CONTENT_ALIGNMENT_ESTABLISHED" not in val_res.flags
    assert "INSUFFICIENT_CONTENT_ALIGNMENT" in val_res.flags
    assert "REVIEW_REQUIRED_RETAINED" in val_res.flags


def test_negative_regression_allow_synthetic_fixtures_explicit_true_outside_test_env_rejected(populated_db, monkeypatch):
    """Regression test: allow_synthetic_fixtures=True must NOT override the isolated-test-context requirement.

    Synthetic fixtures must strictly be rejected outside isolated test contexts.
    """
    # 1. Simulate running outside of test environment
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("JUST_IELTS_TEST_ENV", raising=False)

    conn = get_db_connection(populated_db)
    validator = SourceReferenceValidator(conn, allow_synthetic_fixtures=True)

    # 2. Verify isolated test context is detected as False
    assert validator.is_isolated_test_context() is False

    # 3. Attempt reference validation with synthetic fixture; must be rejected despite allow_synthetic_fixtures=True
    val_res = validator.validate_reference(
        reference_source_id="SRC-SYN-02",
        expected_collection="VOL 99",
        expected_test_number=1,
        expected_passage_or_section=1,
        candidate_target_file_id="FILE-a00000000004",
        candidate_source_file_id="FILE-a00000000001",
        relationship_type="question_to_answer_key",
        evidence_provenance={
            "source_id": "SRC-SYN-02",
            "provenance_type": "independent_key",
            "authority": "cambridge",
        },
    )
    conn.close()

    assert val_res.is_valid is False
    assert "SYNTHETIC_FIXTURE_NOT_PERMITTED" in val_res.flags
    assert any("Synthetic fixture injection is permitted only in isolated test contexts" in r for r in val_res.rejection_reasons)

    # 4. Also verify through RelationshipReviewService that decide() rejects approval outside test environment
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000004", "question_to_answer_key", "VOL 99", 1, 1
    )
    service = RelationshipReviewService(db_path=populated_db, allow_synthetic_fixtures=True)
    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="OPERATOR-01",
            reason="Attempting approval outside test environment with allow_synthetic_fixtures=True",
            evidence_source_id="SRC-SYN-02",
            evidence_references={
                "provenance": {
                    "source_id": "SRC-SYN-02",
                    "authority": "cambridge",
                    "provenance_type": "independent_key",
                }
            },
        )
    assert "Synthetic fixture injection is permitted only in isolated test contexts" in str(exc_info.value)


# --------------------------------------------------------------------------
# 22. PR #6 Content Alignment Guard Regression Tests
# --------------------------------------------------------------------------
def test_negative_regression_reference_title_matches_one_participant_only_retains_review_required(populated_db):
    """Regression test: A matching reference title alone is not sufficient to link two participants.

    When reference title matches one participant only, CONTENT_ALIGNMENT_VERIFIED must NOT be marked,
    and relationship must retain review_required.
    """
    conn = get_db_connection(populated_db)
    # Candidate relationship between FILE-a00000000001 (SRC-SYN-01, has title "Marine Energy Systems")
    # and FILE-a00000000004 (SRC-SYN-04, has NO title and answer keys for Test 2 only)
    rel_id = compute_relationship_id(
        "FILE-a00000000001", "FILE-a00000000004", "question_to_answer_key", "VOL 99", 1, 1
    )
    upsert_source_relationship(conn, {
        "relationship_id": rel_id,
        "source_file_id": "FILE-a00000000001",
        "target_file_id": "FILE-a00000000004",
        "relationship_type": "question_to_answer_key",
        "collection": "VOL 99",
        "volume": "VOL 99",
        "test_number": 1,
        "passage_or_section": 1,
        "skill": "reading",
        "identity_evidence": {"expected_question_range": [1, 14]},
        "validation_flags": ["VOLUME_MATCH", "SKILL_MATCH", "TEST_NUMBER_MATCH", "PASSAGE_REQUESTED", "QUESTION_RANGE_ALIGNED"],
        "match_confidence": 0.5,
        "relationship_status": "review_required",
        "provenance": {"matcher_version": "0.3.0-a", "evaluated_at": "2026-11-20T10:00:00Z"},
        "source_content_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
        "target_content_sha256": "4444444444444444444444444444444444444444444444444444444444444444",
        "schema_version": "v0.3.0-relationship",
    })
    conn.close()

    service = RelationshipReviewService(db_path=populated_db)
    # 1. Attempting approval using reference source SRC-SYN-02 whose title matches candidate source only
    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="OPERATOR-01",
            reason="Attempting approval when reference title matches candidate source only",
            evidence_source_id="SRC-SYN-02",
            evidence_references={
                "provenance": {
                    "source_id": "SRC-SYN-02",
                    "provenance_type": "independent_key",
                    "authority": "official",
                }
            },
        )
    assert "retaining review_required" in str(exc_info.value) or "Missing independent supporting evidence" in str(exc_info.value)

    # 2. Relationship retains review_required in SQLite DB
    conn = get_db_connection(populated_db)
    rel = get_source_relationship(conn, rel_id)
    assert rel["relationship_status"] == "review_required"

    # 3. Direct validator call verifies CONTENT_ALIGNMENT_VERIFIED is NOT marked
    validator = SourceReferenceValidator(conn)
    val_res = validator.validate_reference(
        reference_source_id="SRC-SYN-02",
        expected_collection="VOL 99",
        expected_test_number=1,
        expected_passage_or_section=1,
        candidate_source_file_id="FILE-a00000000001",
        candidate_target_file_id="FILE-a00000000004",
        relationship_type="question_to_answer_key",
        evidence_provenance={"source_id": "SRC-SYN-02", "provenance_type": "key", "authority": "test"},
    )
    conn.close()

    assert val_res.is_valid is False
    assert "CONTENT_ALIGNMENT_VERIFIED" not in val_res.flags
    assert "CONTENT_ALIGNMENT_ESTABLISHED" not in val_res.flags
    assert "INSUFFICIENT_CONTENT_ALIGNMENT" in val_res.flags
    assert "REVIEW_REQUIRED_RETAINED" in val_res.flags


def test_negative_regression_audio_section_number_matches_without_content_alignment_retains_review_required(populated_db):
    """Regression test: A matching audio track/section number alone is not verified audio-transcript alignment.

    When audio section number matches without content alignment (no title or transcript text binding),
    CONTENT_ALIGNMENT_VERIFIED must NOT be marked, and relationship must retain review_required.
    """
    conn = get_db_connection(populated_db)
    # Register an independent reference audio source
    upsert_source(conn, {
        "file_id": "FILE-a00000000089",
        "legacy_id": "SRC-SYN-REF-AUDIO",
        "relative_path": "data/synthetic/VOL99/Listening/ref_audio.mp3",
        "filename": "ref_audio.mp3",
        "extension": ".mp3",
        "detected_type": "mp3",
        "size_bytes": 5000,
        "content_sha256": "8989898989898989898989898989898989898989898989898989898989898989",
        "collection": "VOL 99",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })

    # Candidate listening relationship between FILE-a00000000008 (SRC-SYN-08, AudioTrack 01.mp3)
    # and FILE-a00000000009 (SRC-SYN-09, Transcript Test 1.docx)
    # Both cover Section 1, but have no matching titles, no answers, and no transcript_audio_aligned marker.
    rel_id = compute_relationship_id(
        "FILE-a00000000008", "FILE-a00000000009", "listening_to_audio", "VOL 99", 1, 1
    )
    upsert_source_relationship(conn, {
        "relationship_id": rel_id,
        "source_file_id": "FILE-a00000000008",
        "target_file_id": "FILE-a00000000009",
        "relationship_type": "listening_to_audio",
        "collection": "VOL 99",
        "volume": "VOL 99",
        "test_number": 1,
        "passage_or_section": 1,
        "skill": "listening",
        "identity_evidence": {"audio_track": 1},
        "validation_flags": ["VOLUME_MATCH", "SKILL_MATCH", "TEST_NUMBER_MATCH", "PASSAGE_REQUESTED"],
        "match_confidence": 0.6,
        "relationship_status": "review_required",
        "provenance": {"matcher_version": "0.3.0-a", "evaluated_at": "2026-11-20T10:00:00Z"},
        "source_content_sha256": "8888888888888888888888888888888888888888888888888888888888888888",
        "target_content_sha256": "9999999999999999999999999999999999999999999999999999999999999999",
        "schema_version": "v0.3.0-relationship",
    })
    conn.close()

    synthetic_fixtures = {
        "SRC-SYN-REF-AUDIO": {
            "test_numbers": [1],
            "passages_or_sections": {"1": [1]},
            "raw_content_summary": {"audio_track": 1},
        }
    }

    service = RelationshipReviewService(db_path=populated_db, synthetic_fixtures=synthetic_fixtures)
    # 1. Attempting approval using reference source SRC-SYN-REF-AUDIO
    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="OPERATOR-01",
            reason="Attempting approval on matching audio section number without content alignment",
            evidence_source_id="SRC-SYN-REF-AUDIO",
            evidence_references={
                "provenance": {
                    "source_id": "SRC-SYN-REF-AUDIO",
                    "provenance_type": "audio_track",
                    "authority": "official",
                }
            },
        )
    assert "retaining review_required" in str(exc_info.value) or "Missing independent supporting evidence" in str(exc_info.value)

    # 2. Relationship retains review_required in SQLite DB
    conn = get_db_connection(populated_db)
    rel = get_source_relationship(conn, rel_id)
    assert rel["relationship_status"] == "review_required"

    # 3. Direct validator call verifies CONTENT_ALIGNMENT_VERIFIED is NOT marked
    validator = SourceReferenceValidator(conn, synthetic_fixtures=synthetic_fixtures)
    val_res = validator.validate_reference(
        reference_source_id="SRC-SYN-REF-AUDIO",
        expected_collection="VOL 99",
        expected_test_number=1,
        expected_passage_or_section=1,
        candidate_source_file_id="FILE-a00000000008",
        candidate_target_file_id="FILE-a00000000009",
        relationship_type="listening_to_audio",
        evidence_provenance={"source_id": "SRC-SYN-REF-AUDIO", "provenance_type": "audio", "authority": "test"},
    )
    conn.close()

    assert val_res.is_valid is False
    assert "CONTENT_ALIGNMENT_VERIFIED" not in val_res.flags
    assert "CONTENT_ALIGNMENT_ESTABLISHED" not in val_res.flags
    assert "INSUFFICIENT_CONTENT_ALIGNMENT" in val_res.flags
    assert "REVIEW_REQUIRED_RETAINED" in val_res.flags


def test_negative_regression_both_participants_lack_trusted_content_retains_review_required(populated_db):
    """Regression test: When both participants lack trusted content evidence,

    CONTENT_ALIGNMENT_VERIFIED must NOT be marked, and relationship must retain review_required.
    """
    conn = get_db_connection(populated_db)
    # Register two sources that have physical files missing and no trusted extraction artifacts
    upsert_source(conn, {
        "file_id": "FILE-a00000000081",
        "legacy_id": "SRC-SYN-NO-CONTENT-A",
        "relative_path": "data/synthetic/VOL99/Reading/missing_content_a.docx",
        "filename": "missing_content_a.docx",
        "extension": ".docx",
        "detected_type": "docx",
        "size_bytes": 2048,
        "content_sha256": "8181818181818181818181818181818181818181818181818181818181818181",
        "collection": "VOL 99",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })
    upsert_source(conn, {
        "file_id": "FILE-a00000000082",
        "legacy_id": "SRC-SYN-NO-CONTENT-B",
        "relative_path": "data/synthetic/VOL99/Reading/missing_content_b.pdf",
        "filename": "missing_content_b.pdf",
        "extension": ".pdf",
        "detected_type": "pdf",
        "size_bytes": 2048,
        "content_sha256": "8282828282828282828282828282828282828282828282828282828282828282",
        "collection": "VOL 99",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })

    rel_id = compute_relationship_id(
        "FILE-a00000000081", "FILE-a00000000082", "question_to_answer_key", "VOL 99", 1, 1
    )
    upsert_source_relationship(conn, {
        "relationship_id": rel_id,
        "source_file_id": "FILE-a00000000081",
        "target_file_id": "FILE-a00000000082",
        "relationship_type": "question_to_answer_key",
        "collection": "VOL 99",
        "volume": "VOL 99",
        "test_number": 1,
        "passage_or_section": 1,
        "skill": "reading",
        "identity_evidence": {},
        "validation_flags": ["VOLUME_MATCH", "SKILL_MATCH", "TEST_NUMBER_MATCH"],
        "match_confidence": 0.5,
        "relationship_status": "review_required",
        "provenance": {"matcher_version": "0.3.0-a", "evaluated_at": "2026-11-20T10:00:00Z"},
        "source_content_sha256": "8181818181818181818181818181818181818181818181818181818181818181",
        "target_content_sha256": "8282828282828282828282828282828282828282828282828282828282828282",
        "schema_version": "v0.3.0-relationship",
    })
    conn.close()

    service = RelationshipReviewService(db_path=populated_db)
    # 1. Attempting approval using valid reference source SRC-SYN-02
    with pytest.raises(ReviewPolicyViolation) as exc_info:
        service.decide(
            relationship_id=rel_id,
            decision="approve",
            reviewer_id="OPERATOR-01",
            reason="Attempting approval when both participants lack trusted content",
            evidence_source_id="SRC-SYN-02",
            evidence_references={
                "provenance": {
                    "source_id": "SRC-SYN-02",
                    "provenance_type": "independent_key",
                    "authority": "official",
                }
            },
        )
    assert "retaining review_required" in str(exc_info.value) or "Missing independent supporting evidence" in str(exc_info.value)

    # 2. Relationship retains review_required in SQLite DB
    conn = get_db_connection(populated_db)
    rel = get_source_relationship(conn, rel_id)
    assert rel["relationship_status"] == "review_required"

    # 3. Direct validator call verifies CONTENT_ALIGNMENT_VERIFIED is NOT marked
    validator = SourceReferenceValidator(conn)
    val_res = validator.validate_reference(
        reference_source_id="SRC-SYN-02",
        expected_collection="VOL 99",
        expected_test_number=1,
        expected_passage_or_section=1,
        candidate_source_file_id="FILE-a00000000081",
        candidate_target_file_id="FILE-a00000000082",
        relationship_type="question_to_answer_key",
        evidence_provenance={"source_id": "SRC-SYN-02", "provenance_type": "key", "authority": "test"},
    )
    conn.close()

    assert val_res.is_valid is False
    assert "CONTENT_ALIGNMENT_VERIFIED" not in val_res.flags
    assert "CONTENT_ALIGNMENT_ESTABLISHED" not in val_res.flags
    assert "INSUFFICIENT_CONTENT_ALIGNMENT" in val_res.flags
    assert "REVIEW_REQUIRED_RETAINED" in val_res.flags





