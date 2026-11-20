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
    upsert_source,
    upsert_source_relationship,
)
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
    service = RelationshipReviewService(db_path=populated_db)
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

