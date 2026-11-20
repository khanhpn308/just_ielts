"""Comprehensive automated test suite for IELTS Multi-Source Matching & Provenance Resolver (Phase V0.3-A).

Tests all 13 required verification scenarios:
1. Correct source matching.
2. Volume mismatch.
3. Test number mismatch.
4. Passage mismatch.
5. Conflicting answer keys.
6. Missing source metadata.
7. Duplicate records.
8. Multiple candidate keys.
9. Idempotency.
10. SQLite migrations.
11. Interrupted processing and resume.
12. Source relocation and changed hashes.
13. Privacy isolation.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Dict, List

import pytest

from harness.config import REPO_ROOT
from harness.db import (
    count_relationships_by_status,
    count_relationships_by_type,
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
from harness.matching.engine import MatchingEngine
from harness.matching.metadata import SourceDocumentMetadata, extract_source_metadata
from harness.matching.service import RelationshipMatchingService, validate_output_directory
from harness.models.relationship import (
    RelationshipConflict,
    RelationshipReview,
    SourceRelationship,
    compute_relationship_id,
)

FIXTURES_PATH = REPO_ROOT / "tests" / "fixtures" / "synthetic_relationships" / "synthetic_test_sources.json"


@pytest.fixture
def synthetic_sources_map() -> Dict[str, Dict[str, Any]]:
    """Loads synthetic sources fixture from JSON."""
    raw = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    return {s["legacy_id"]: s for s in raw["sources"]}


@pytest.fixture
def temp_db_path(tmp_path) -> Path:
    """Creates a temporary isolated SQLite database for clean-checkout testing."""
    db_file = tmp_path / "test_harness.db"
    init_db(db_file)
    return db_file


@pytest.fixture
def populated_temp_db(temp_db_path, synthetic_sources_map) -> Path:
    """Populates temporary SQLite database with synthetic sources."""
    conn = get_db_connection(temp_db_path)
    for src in synthetic_sources_map.values():
        rec = {
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
        }
        upsert_source(conn, rec)
    conn.close()
    return temp_db_path


def _make_meta(src_dict: Dict[str, Any]) -> SourceDocumentMetadata:
    """Builds SourceDocumentMetadata directly from fixture dict."""
    return extract_source_metadata(
        source_record=src_dict,
        staged_data=src_dict.get("staged_data"),
    )


# --------------------------------------------------------------------------
# 1. Correct Source Matching
# --------------------------------------------------------------------------
def test_correct_source_matching(synthetic_sources_map):
    """Scenario 1: Verified matching pair (VOL 99 Test 1 Passage 1) is confirmed."""
    engine = MatchingEngine()
    meta_q = _make_meta(synthetic_sources_map["SRC-SYN-01"])
    meta_k = _make_meta(synthetic_sources_map["SRC-SYN-02"])

    rel, confs = engine.evaluate_relationship(
        source_meta=meta_q,
        target_meta=meta_k,
        relationship_type="question_to_explanation",
        test_number=1,
        passage_or_section=1,
    )

    assert rel.relationship_status == "confirmed"
    assert rel.match_confidence == 1.0
    assert len(confs) == 0
    assert "VOLUME_MATCH" in rel.validation_flags
    assert "SKILL_MATCH" in rel.validation_flags
    assert "TEST_NUMBER_MATCH" in rel.validation_flags
    assert "GATE_CONFIRMED_PASSED" in rel.validation_flags
    assert rel.volume == "VOL 99"
    assert rel.test_number == 1
    assert rel.passage_or_section == 1


# --------------------------------------------------------------------------
# 2. Volume Mismatch
# --------------------------------------------------------------------------
def test_volume_mismatch_rejection(synthetic_sources_map):
    """Scenario 2: Cross-volume candidate (VOL 99 vs VOL 88) is strictly rejected."""
    engine = MatchingEngine()
    meta_q = _make_meta(synthetic_sources_map["SRC-SYN-01"])  # VOL 99
    meta_k = _make_meta(synthetic_sources_map["SRC-SYN-03"])  # VOL 88

    rel, confs = engine.evaluate_relationship(
        source_meta=meta_q,
        target_meta=meta_k,
        relationship_type="question_to_answer_key",
        test_number=1,
        passage_or_section=1,
    )

    assert rel.relationship_status == "rejected"
    assert rel.match_confidence == 0.0
    assert any(c.conflict_type == "CROSS_VOLUME_MISMATCH" for c in confs)
    assert any(c.severity == "critical" for c in confs)
    assert "VOLUME_MISMATCH" in rel.validation_flags


# --------------------------------------------------------------------------
# 3. Test Number Mismatch
# --------------------------------------------------------------------------
def test_test_number_mismatch_rejection(synthetic_sources_map):
    """Scenario 3: Candidate covering Test 2 cannot link to Test 1."""
    engine = MatchingEngine()
    meta_q = _make_meta(synthetic_sources_map["SRC-SYN-01"])  # Test 1
    meta_k = _make_meta(synthetic_sources_map["SRC-SYN-04"])  # Test 2

    rel, confs = engine.evaluate_relationship(
        source_meta=meta_q,
        target_meta=meta_k,
        relationship_type="question_to_answer_key",
        test_number=1,
        passage_or_section=1,
    )

    assert rel.relationship_status == "rejected"
    assert any(c.conflict_type == "TEST_NUMBER_MISMATCH" for c in confs)
    assert "TEST_NUMBER_MISMATCH" in rel.validation_flags


# --------------------------------------------------------------------------
# 4. Passage Mismatch
# --------------------------------------------------------------------------
def test_passage_mismatch_rejection(synthetic_sources_map):
    """Scenario 4: Key for Passage 3 cannot link to Passage 1."""
    engine = MatchingEngine()
    meta_q = _make_meta(synthetic_sources_map["SRC-SYN-01"])  # Passage 1
    meta_k = _make_meta(synthetic_sources_map["SRC-SYN-05"])  # Passage 3

    rel, confs = engine.evaluate_relationship(
        source_meta=meta_q,
        target_meta=meta_k,
        relationship_type="question_to_answer_key",
        test_number=1,
        passage_or_section=None,  # let engine detect passage mismatch
    )

    assert rel.relationship_status == "rejected"
    assert any(c.conflict_type == "PASSAGE_MISMATCH" for c in confs)
    assert "PASSAGE_MISMATCH" in rel.validation_flags


# --------------------------------------------------------------------------
# 5. Conflicting Answer Keys
# --------------------------------------------------------------------------
def test_conflicting_answer_keys_rejection(synthetic_sources_map):
    """Scenario 5: Candidate key contradicting ground truth answers is rejected."""
    engine = MatchingEngine()
    meta_q = _make_meta(synthetic_sources_map["SRC-SYN-01"])
    meta_corrupt = _make_meta(synthetic_sources_map["SRC-SYN-06"])
    gt_answers = {1: "TRUE", 2: "FALSE", 3: "NOT GIVEN", 4: "TRUE"}

    rel, confs = engine.evaluate_relationship(
        source_meta=meta_q,
        target_meta=meta_corrupt,
        relationship_type="question_to_answer_key",
        test_number=1,
        passage_or_section=1,
        known_ground_truth_answers=gt_answers,
    )

    assert rel.relationship_status == "rejected"
    assert any(c.conflict_type == "CONFLICTING_ANSWER_KEYS" for c in confs)
    assert "CONFLICTING_ANSWER_KEYS" in rel.validation_flags

    key_conf = next(c for c in confs if c.conflict_type == "CONFLICTING_ANSWER_KEYS")
    assert key_conf.severity == "critical"
    assert 1 in key_conf.evidence["contradictory_questions"]


# --------------------------------------------------------------------------
# 6. Missing Source Metadata
# --------------------------------------------------------------------------
def test_missing_source_metadata_review_required(synthetic_sources_map):
    """Scenario 6: Sources lacking volume or test metadata route to review_required."""
    engine = MatchingEngine()
    meta_q = _make_meta(synthetic_sources_map["SRC-SYN-01"])
    meta_unlabeled = _make_meta(synthetic_sources_map["SRC-SYN-07"])

    rel, confs = engine.evaluate_relationship(
        source_meta=meta_q,
        target_meta=meta_unlabeled,
        relationship_type="question_to_answer_key",
    )

    assert rel.relationship_status == "review_required"
    assert rel.match_confidence <= 0.5
    assert any(c.conflict_type == "MISSING_METADATA" for c in confs)


# --------------------------------------------------------------------------
# 7. Duplicate Records Prevention
# --------------------------------------------------------------------------
def test_duplicate_records_prevention(populated_temp_db, synthetic_sources_map):
    """Scenario 7: Repeated insertions of the same relationship ID update in-place."""
    conn = get_db_connection(populated_temp_db)
    engine = MatchingEngine()
    meta_q = _make_meta(synthetic_sources_map["SRC-SYN-01"])
    meta_k = _make_meta(synthetic_sources_map["SRC-SYN-02"])

    rel, _ = engine.evaluate_relationship(meta_q, meta_k, "question_to_explanation", 1, 1)

    # Upsert first time
    upsert_source_relationship(conn, rel.model_dump())
    assert len(list_source_relationships(conn)) == 1

    # Upsert second time with modified confidence
    rel_modified = rel.model_copy(update={"match_confidence": 0.99})
    upsert_source_relationship(conn, rel_modified.model_dump())

    # Total record count must still be 1 (zero duplicates)
    all_rels = list_source_relationships(conn)
    assert len(all_rels) == 1
    assert all_rels[0]["match_confidence"] == 0.99
    conn.close()


# --------------------------------------------------------------------------
# 8. Multiple Candidate Keys
# --------------------------------------------------------------------------
def test_multiple_candidate_keys(synthetic_sources_map):
    """Scenario 8: Ambiguous or unverified keys cannot be promoted by confidence alone."""
    engine = MatchingEngine()
    meta_q = _make_meta(synthetic_sources_map["SRC-SYN-01"])
    meta_k_valid = _make_meta(synthetic_sources_map["SRC-SYN-02"])
    meta_k_corrupt = _make_meta(synthetic_sources_map["SRC-SYN-06"])

    rel_valid, confs_valid = engine.evaluate_relationship(meta_q, meta_k_valid, "question_to_answer_key", 1, 1)
    rel_corrupt, confs_corrupt = engine.evaluate_relationship(
        meta_q, meta_k_corrupt, "question_to_answer_key", 1, 1,
        known_ground_truth_answers=meta_k_valid.answer_keys.get(1)
    )

    assert rel_valid.relationship_status == "confirmed"
    assert rel_corrupt.relationship_status == "rejected"


# --------------------------------------------------------------------------
# 9. Idempotency
# --------------------------------------------------------------------------
def test_matching_idempotency(populated_temp_db, synthetic_sources_map, tmp_path):
    """Scenario 9: Repeated service runs yield identical deterministic IDs and results."""
    service = RelationshipMatchingService(db_path=populated_temp_db)
    sources_list = list(synthetic_sources_map.values())
    out_dir = tmp_path / "reports_run1"

    res1 = service.match_sources(sources_override=sources_list, output_dir=out_dir, force=True)
    res2 = service.match_sources(sources_override=sources_list, output_dir=out_dir, force=True)

    assert res1["total_evaluated"] == res2["total_evaluated"]
    assert res1["confirmed"] == res2["confirmed"]
    assert res1["rejected"] == res2["rejected"]

    ids1 = [r.relationship_id for r in res1["relationships"]]
    ids2 = [r.relationship_id for r in res2["relationships"]]
    assert ids1 == ids2


# --------------------------------------------------------------------------
# 10. SQLite Migrations
# --------------------------------------------------------------------------
def test_sqlite_migrations(tmp_path):
    """Scenario 10: Dynamic migration safely creates V0.3-A tables on a legacy V0.1/V0.2 DB."""
    db_file = tmp_path / "legacy_v02_test.db"
    conn = sqlite3.connect(db_file)
    # Simulate legacy database with sources and normalization_checkpoints only
    conn.executescript("""
        CREATE TABLE sources (
            file_id TEXT PRIMARY KEY,
            legacy_id TEXT UNIQUE,
            relative_path TEXT NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            extension TEXT NOT NULL,
            detected_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL,
            collection TEXT NOT NULL,
            duplicate_group TEXT DEFAULT 'none',
            accessibility_status TEXT NOT NULL,
            relocated_from TEXT,
            relocated_to TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO sources (file_id, legacy_id, relative_path, filename, extension, detected_type, size_bytes, content_sha256, collection, accessibility_status)
        VALUES ('FILE-legacy00001', 'SRC-LEGACY', 'path/legacy.pdf', 'legacy.pdf', '.pdf', 'pdf', 100, 'hash', 'VOL 1', 'accessible');
    """)
    conn.commit()
    conn.close()

    # Run init_db to migrate to V0.3-A
    init_db(db_file)

    conn2 = get_db_connection(db_file)
    cur = conn2.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    assert "source_relationships" in tables
    assert "relationship_conflicts" in tables
    assert "relationship_reviews" in tables

    # Verify existing legacy record is completely preserved
    cur2 = conn2.execute("SELECT file_id, legacy_id FROM sources WHERE file_id = 'FILE-legacy00001'")
    row = cur2.fetchone()
    assert row is not None
    assert row["legacy_id"] == "SRC-LEGACY"
    conn2.close()


# --------------------------------------------------------------------------
# 11. Interrupted Processing and Resume
# --------------------------------------------------------------------------
def test_interrupted_processing_and_resume(populated_temp_db, synthetic_sources_map, tmp_path):
    """Scenario 11: Service safely skips already evaluated relationships on resume."""
    service = RelationshipMatchingService(db_path=populated_temp_db)
    sources_list = list(synthetic_sources_map.values())[:3]
    out_dir = tmp_path / "resume_test"

    # Run 1: process and populate DB
    res1 = service.match_sources(sources_override=sources_list, output_dir=out_dir, force=True)

    # Run 2: resume should skip existing valid relationships
    res2 = service.match_sources(sources_override=sources_list, output_dir=out_dir, resume=True, force=False)

    assert res2["skipped_resumed"] > 0
    assert res2["total_evaluated"] == res1["total_evaluated"]


# --------------------------------------------------------------------------
# 12. Source Relocation and Changed Hashes
# --------------------------------------------------------------------------
def test_source_relocation_and_hash_invalidation(synthetic_sources_map):
    """Scenario 12: Changed source hashes and paths update provenance metadata."""
    engine = MatchingEngine()
    meta_orig = _make_meta(synthetic_sources_map["SRC-SYN-01"])
    meta_k = _make_meta(synthetic_sources_map["SRC-SYN-02"])

    rel1, _ = engine.evaluate_relationship(meta_orig, meta_k, "question_to_explanation", 1, 1)

    # Simulate relocated source
    relocated_dict = dict(synthetic_sources_map["SRC-SYN-01"])
    relocated_dict["relative_path"] = "data/synthetic/RELOCATED/Reading/test_1.docx"
    meta_relocated = _make_meta(relocated_dict)

    rel2, _ = engine.evaluate_relationship(meta_relocated, meta_k, "question_to_explanation", 1, 1)

    assert rel1.relationship_id == rel2.relationship_id  # Stable identity
    assert rel2.provenance["source_path"] == "data/synthetic/RELOCATED/Reading/test_1.docx"


# --------------------------------------------------------------------------
# 13. Privacy Isolation
# --------------------------------------------------------------------------
def test_privacy_isolation():
    """Scenario 13: Clean checkout test fixtures contain no copyrighted text."""
    fixture_text = FIXTURES_PATH.read_text(encoding="utf-8")
    # Verify no real Cambridge exam paragraphs or real author identities exist in synthetic test files
    assert "Ngoc Bach" not in fixture_text
    assert "Cam 16" not in fixture_text
    assert "Beechen Festival" not in fixture_text


# --------------------------------------------------------------------------
# Regression Tests for V0.3-A Correctness Remediation
# --------------------------------------------------------------------------

def test_generic_candidate_generation_multitest_multipassage():
    """P0: Candidates generated across multiple tests and passages without hardcoding 5, 1."""
    service = RelationshipMatchingService()
    s1 = {
        "file_id": "FILE-dyn000000001",
        "legacy_id": "SRC-REG-01",
        "relative_path": "data/synthetic/VOL2/Reading/test_booklet.docx",
        "filename": "test_booklet.docx",
        "extension": ".docx",
        "collection": "VOL 2",
        "staged_data": {
            "test_numbers": [3, 4],
            "passages_or_sections": {"3": [1, 2], "4": [1, 2, 3]},
            "paragraphs": [{"text": "READING TEST 3\nREADING PASSAGE 1\nTitle A"}],
        },
    }
    s2 = {
        "file_id": "FILE-dyn000000002",
        "legacy_id": "SRC-REG-02",
        "relative_path": "data/synthetic/VOL2/Reading/key.pdf",
        "filename": "key.pdf",
        "extension": ".pdf",
        "collection": "VOL 2",
        "staged_data": {
            "test_numbers": [3, 4],
            "passages_or_sections": {"3": [2], "4": [1]},
            "answer_keys": {"3": {"15": "A"}, "4": {"1": "TRUE"}},
        },
    }

    pairs = service.generate_candidate_pairs([s1, s2])
    # Expect candidates for (T3, P2), (T4, P1) because those are the intersection
    # Zero hardcoded 5, 1
    assert not any(p[3] == 5 for p in pairs)
    t3_candidates = [p for p in pairs if p[3] == 3]
    t4_candidates = [p for p in pairs if p[3] == 4]
    assert len(t3_candidates) > 0
    assert any(p[4] == 2 for p in t3_candidates)
    assert len(t4_candidates) > 0
    assert any(p[4] == 1 for p in t4_candidates)


def test_candidate_generation_preserves_ambiguity():
    """P0: Ambiguous test or passage identities are preserved as None rather than guessed."""
    service = RelationshipMatchingService()
    s1 = {
        "file_id": "FILE-dyn000000003",
        "legacy_id": "SRC-AMB-01",
        "relative_path": "data/synthetic/VOL5/Reading/general_reading.docx",
        "filename": "general_reading.docx",
        "extension": ".docx",
        "collection": "VOL 5",
        "staged_data": {"paragraphs": [{"text": "Some general notes without test markers"}]},
    }
    s2 = {
        "file_id": "FILE-dyn000000004",
        "legacy_id": "SRC-AMB-02",
        "relative_path": "data/synthetic/VOL5/Reading/key.pdf",
        "filename": "key.pdf",
        "extension": ".pdf",
        "collection": "VOL 5",
        "staged_data": {"answer_keys": {}},
    }

    pairs = service.generate_candidate_pairs([s1, s2])
    assert len(pairs) > 0
    # Both test_number and passage_or_section must be None (preserved ambiguity)
    for p in pairs:
        assert p[3] is None
        assert p[4] is None


def test_question_range_aligned_alone_does_not_confirm():
    """P0: Structural compatibility (QUESTION_RANGE_ALIGNED) alone must stay candidate."""
    engine = MatchingEngine()
    # Source question booklet with range Q1-14 but no titles or answers
    meta_q = SourceDocumentMetadata(
        file_id="FILE-a00000000031",
        relative_path="data/VOL10/Reading/test_1.docx",
        filename="test_1.docx",
        collection="VOL 10",
        volume="VOL 10",
        skill="reading",
        document_role="question_booklet",
        test_numbers=[1],
        passages_or_sections={1: [1]},
        passage_titles={},  # No title!
    )
    # Target answer key with Q1-Q14, but no overlapping answers or titles to verify content
    meta_k = SourceDocumentMetadata(
        file_id="FILE-a00000000032",
        relative_path="data/VOL10/Reading/key_1.pdf",
        filename="key_1.pdf",
        collection="VOL 10",
        volume="VOL 10",
        skill="reading",
        document_role="answer_key",
        test_numbers=[1],
        passages_or_sections={1: [1]},
        answer_keys={1: {1: "TRUE", 2: "FALSE", 3: "NOT GIVEN"}},
        passage_titles={},  # No title!
    )

    rel, confs = engine.evaluate_relationship(
        source_meta=meta_q,
        target_meta=meta_k,
        relationship_type="question_to_answer_key",
        test_number=1,
        passage_or_section=1,
    )

    # Must NOT be confirmed because QUESTION_RANGE_ALIGNED alone does not provide content proof
    assert "QUESTION_RANGE_ALIGNED" in rel.validation_flags
    assert "GATE_CONFIRMED_PASSED" not in rel.validation_flags
    assert rel.relationship_status == "candidate"
    assert rel.match_confidence < 1.0


def test_transcript_audio_aligned_requires_independent_evidence():
    """P0: TRANSCRIPT_AUDIO_ALIGNED requires audio track verification, not just requested section."""
    engine = MatchingEngine()
    meta_audio_unverified = SourceDocumentMetadata(
        file_id="FILE-a00000000041",
        relative_path="data/VOL1/audio.mp3",
        filename="audio.mp3",
        collection="VOL 1",
        volume="VOL 1",
        skill="listening",
        document_role="audio",
        test_numbers=[1],
        raw_content_summary={},  # No audio_track extracted!
    )
    meta_transcript = SourceDocumentMetadata(
        file_id="FILE-a00000000042",
        relative_path="data/VOL1/transcript.docx",
        filename="transcript.docx",
        collection="VOL 1",
        volume="VOL 1",
        skill="listening",
        document_role="transcript",
        test_numbers=[1],
        passages_or_sections={1: [1]},
    )

    rel, _ = engine.evaluate_relationship(
        source_meta=meta_transcript,
        target_meta=meta_audio_unverified,
        relationship_type="listening_to_audio",
        test_number=1,
        passage_or_section=1,  # Requested section number only!
    )

    # Must NOT have TRANSCRIPT_AUDIO_ALIGNED, and must NOT be confirmed
    assert "TRANSCRIPT_AUDIO_ALIGNED" not in rel.validation_flags
    assert "SECTION_REQUESTED_UNVERIFIED" in rel.validation_flags
    assert rel.relationship_status in {"candidate", "review_required"}
    assert rel.relationship_status != "confirmed"


def test_source_freshness_and_reevaluation(populated_temp_db, synthetic_sources_map, tmp_path):
    """P0: Stale relationships are reevaluated on content SHA change while fresh ones are skipped."""
    service = RelationshipMatchingService(db_path=populated_temp_db)
    sources = list(synthetic_sources_map.values())[:2]
    out_dir = tmp_path / "freshness_test"

    # Initial run
    res1 = service.match_sources(sources_override=sources, output_dir=out_dir, force=True)
    assert res1["confirmed"] > 0
    rel1 = res1["relationships"][0]

    # Run again without changes -> fresh, skipped_resumed > 0
    res2 = service.match_sources(sources_override=sources, output_dir=out_dir, resume=True)
    assert res2["skipped_resumed"] > 0

    # Modify source content SHA in memory to simulate upstream content edit
    modified_sources = [dict(s) for s in sources]
    modified_sources[0]["content_sha256"] = "9999999999999999999999999999999999999999999999999999999999999999"

    # Run again: should detect staleness and reevaluate rather than skip
    res3 = service.match_sources(sources_override=modified_sources, output_dir=out_dir, resume=True)
    assert res3["skipped_resumed"] == 0
    rel3 = [r for r in res3["relationships"] if r.relationship_id == rel1.relationship_id][0]
    assert rel3.source_content_sha256 == "9999999999999999999999999999999999999999999999999999999999999999"


def test_source_changes_status_unchanged_preserves_id_and_reviews(populated_temp_db, synthetic_sources_map, tmp_path):
    """P0: Content changes that still confirm preserve relationship_id and review history."""
    conn = get_db_connection(populated_temp_db)
    service = RelationshipMatchingService(db_path=populated_temp_db)
    sources = list(synthetic_sources_map.values())[:2]
    out_dir = tmp_path / "review_preservation"

    res1 = service.match_sources(sources_override=sources, output_dir=out_dir, force=True)
    rel1 = res1["relationships"][0]

    # Record a human review transition for this relationship
    record_relationship_review(
        conn,
        {
            "review_id": "REV-0000000000000001",
            "relationship_id": rel1.relationship_id,
            "previous_status": "candidate",
            "new_status": "confirmed",
            "reviewer": "expert_tutor",
            "reason": "Forensically validated pilot pair",
        },
    )
    conn.close()

    # Change source hash while preserving valid content
    modified_sources = [dict(s) for s in sources]
    modified_sources[0]["content_sha256"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    res2 = service.match_sources(sources_override=modified_sources, output_dir=out_dir, resume=True)
    rel2 = [r for r in res2["relationships"] if r.relationship_id == rel1.relationship_id][0]

    # Deterministic ID preserved
    assert rel2.relationship_id == rel1.relationship_id
    assert rel2.relationship_status == "confirmed"

    # Review history preserved
    conn2 = get_db_connection(populated_temp_db)
    reviews = list_relationship_reviews(conn2, rel1.relationship_id)
    conn2.close()
    assert len(reviews) == 1
    assert reviews[0]["reviewer"] == "expert_tutor"


def test_quality_gates_runtime_evaluation(populated_temp_db, synthetic_sources_map, tmp_path):
    """P1: Quality gates return real runtime PASS/PASS_WITH_UNRESOLVED/FAIL with counts."""
    service = RelationshipMatchingService(db_path=populated_temp_db)
    sources = list(synthetic_sources_map.values())
    out_dir = tmp_path / "gates_test"

    res = service.match_sources(sources_override=sources, output_dir=out_dir, force=True)
    assert "quality_gates" in res
    gates = res["quality_gates"]

    for gid in ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"]:
        assert gid in gates
        assert gates[gid]["status"] in {"PASS", "PASS_WITH_UNRESOLVED", "FAIL", "NOT_EVALUATED"}
        assert "counts" in gates[gid]
        assert "note" in gates[gid]

    # R2 must pass (zero cross-volume confirmed)
    assert gates["R2"]["status"] == "PASS"
    assert gates["R2"]["counts"]["cross_volume_confirmed"] == 0

    # R7 should reflect unresolved items if review_required exists
    if res["review_required"] > 0:
        assert gates["R7"]["status"] == "PASS_WITH_UNRESOLVED"


def test_privacy_output_dir_validation_negative(tmp_path):
    """P1: validate_output_directory strictly blocks public directories, path traversal, and symlink escapes."""
    fake_repo = tmp_path / "mock_repo"
    fake_repo.mkdir()
    fake_private = fake_repo / "private"
    fake_private.mkdir()
    fake_docs = fake_repo / "docs"
    fake_docs.mkdir()
    fake_tests = fake_repo / "tests"
    fake_tests.mkdir()

    # 1. Valid private output (both within mock repo private/ and external temp path)
    valid_private = fake_private / "reports" / "v03a"
    res_priv = validate_output_directory(valid_private, repo_root=fake_repo)
    assert res_priv == valid_private.resolve()

    valid_external_temp = tmp_path / "isolated_external_reports"
    res_ext = validate_output_directory(valid_external_temp, repo_root=fake_repo)
    assert res_ext == valid_external_temp.resolve()

    # 2. Forbidden public output
    with pytest.raises(ValueError, match="Security violation"):
        validate_output_directory(fake_docs / "leaked_reports", repo_root=fake_repo)

    with pytest.raises(ValueError, match="Security violation"):
        validate_output_directory(fake_tests / "leaked_reports", repo_root=fake_repo)

    with pytest.raises(ValueError, match="Security violation"):
        validate_output_directory(fake_repo / "escaped_reports", repo_root=fake_repo)

    # 3. Path traversal
    with pytest.raises(ValueError, match="Security violation"):
        validate_output_directory(fake_private / ".." / "docs", repo_root=fake_repo)

    with pytest.raises(ValueError, match="Security violation"):
        validate_output_directory(fake_private / ".." / "escaped_reports", repo_root=fake_repo)

    with pytest.raises(ValueError, match="Security violation"):
        validate_output_directory(fake_private / "nested" / ".." / ".." / "tests", repo_root=fake_repo)

    # 4. Symlink escape
    symlink_path = fake_private / "test_symlink_escape"
    symlink_path.symlink_to(fake_docs)
    with pytest.raises(ValueError, match="Security violation"):
        validate_output_directory(symlink_path, repo_root=fake_repo)


def test_negative_circular_answer_confirmation_and_unrelated_key(synthetic_sources_map, tmp_path):
    """Fix 2 Negative Regression Test: Question booklet and unrelated answer key.

    A question booklet and unrelated answer key share the same Volume, Test, and question numbers.
    Must verify:
    - No false ANSWERS_ALIGNED
    - No false CONFIRMED
    - No confidence inflation
    - Preserve candidate or review_required when independent evidence is unavailable
    - Rejection of circular self-confirmation
    - Preservation of legitimate confirmed relationships when independent evidence actually exists
    """
    engine = MatchingEngine()

    # 1. Question booklet: VOL 99, Test 1, Questions 1-14, Title: "Marine Energy Systems"
    # Question booklet has NO answer keys.
    meta_booklet = _make_meta(synthetic_sources_map["SRC-SYN-01"])

    # 2. Unrelated answer key sharing same Volume (VOL 99), Test (1), and Questions (1-14),
    # but with an unrelated passage title and unrelated answers.
    unrelated_key_dict = {
        "file_id": "FILE-a00000000099",
        "legacy_id": "SRC-SYN-UNRELATED-KEY",
        "relative_path": "data/synthetic/VOL99/Reading/unrelated_key.pdf",
        "filename": "unrelated_key.pdf",
        "extension": ".pdf",
        "detected_type": "pdf",
        "size_bytes": 10240,
        "content_sha256": "9999999999999999999999999999999999999999999999999999999999999999",
        "collection": "VOL 99",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
        "staged_data": {
            "test_numbers": [1],
            "passages_or_sections": {"1": [1]},
            "passage_titles": {"1": {"1": "Completely Unrelated Roman Architecture"}},
            "question_ranges": {"1": {"1": [1, 14]}},
            "answer_keys": {
                "1": {
                    "1": "TRUE",
                    "2": "FALSE",
                    "3": "NOT GIVEN",
                    "4": "TRUE",
                }
            },
        },
    }
    meta_unrelated_key = _make_meta(unrelated_key_dict)

    # 3. Direct evaluation with MatchingEngine:
    rel, confs = engine.evaluate_relationship(
        source_meta=meta_booklet,
        target_meta=meta_unrelated_key,
        relationship_type="question_to_answer_key",
        test_number=1,
        passage_or_section=1,
    )

    # Expected:
    # - No false ANSWERS_ALIGNED
    assert "ANSWERS_ALIGNED" not in rel.validation_flags
    # - No false CONFIRMED
    assert rel.relationship_status != "confirmed"
    assert rel.relationship_status == "candidate"
    assert "GATE_CONFIRMED_PASSED" not in rel.validation_flags
    # - No confidence inflation: match_confidence must be 0.7 (candidate), not 1.0
    assert rel.match_confidence == 0.7
    assert rel.match_confidence < 1.0

    # 4. Circular confirmation attempt (passing target key's own answers as ground truth):
    rel_circ, _ = engine.evaluate_relationship(
        source_meta=meta_booklet,
        target_meta=meta_unrelated_key,
        relationship_type="question_to_answer_key",
        test_number=1,
        passage_or_section=1,
        known_ground_truth_answers=meta_unrelated_key.answer_keys.get(1),
    )
    # An answer key cannot confirm itself
    assert "ANSWERS_ALIGNED" not in rel_circ.validation_flags
    assert "CIRCULAR_ANSWER_EVIDENCE_REJECTED" in rel_circ.validation_flags
    assert rel_circ.relationship_status == "candidate"
    assert rel_circ.match_confidence == 0.7

    # 5. Pipeline evaluation via RelationshipMatchingService.match_sources:
    db_path = tmp_path / "test_unrelated.db"
    init_db(db_path)
    conn = get_db_connection(db_path)
    upsert_source(conn, {
        "file_id": meta_booklet.file_id,
        "legacy_id": meta_booklet.legacy_id,
        "relative_path": meta_booklet.relative_path,
        "filename": meta_booklet.filename,
        "extension": ".docx",
        "detected_type": "docx",
        "size_bytes": 1024,
        "content_sha256": meta_booklet.content_sha256 or "1111",
        "collection": meta_booklet.collection,
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })
    upsert_source(conn, {
        "file_id": meta_unrelated_key.file_id,
        "legacy_id": meta_unrelated_key.legacy_id,
        "relative_path": meta_unrelated_key.relative_path,
        "filename": meta_unrelated_key.filename,
        "extension": ".pdf",
        "detected_type": "pdf",
        "size_bytes": 1024,
        "content_sha256": meta_unrelated_key.content_sha256 or "9999",
        "collection": meta_unrelated_key.collection,
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })
    conn.close()

    service = RelationshipMatchingService(db_path=db_path)
    res = service.match_sources(
        sources_override=[synthetic_sources_map["SRC-SYN-01"], unrelated_key_dict],
        output_dir=tmp_path / "service_out",
        force=True,
    )
    assert res["confirmed"] == 0
    assert res["candidate"] > 0
    assert res["rejected"] == 0

    # 6. Preserve legitimate confirmed relationships when independent evidence actually exists:
    # Case A: Content title alignment
    meta_key_valid = _make_meta(synthetic_sources_map["SRC-SYN-02"])
    rel_legit_title, _ = engine.evaluate_relationship(
        source_meta=meta_booklet,
        target_meta=meta_key_valid,
        relationship_type="question_to_answer_key",
        test_number=1,
        passage_or_section=1,
    )
    assert rel_legit_title.relationship_status == "confirmed"
    assert rel_legit_title.match_confidence == 1.0
    assert "CONTENT_TITLE_MATCH" in rel_legit_title.validation_flags
    assert "GATE_CONFIRMED_PASSED" in rel_legit_title.validation_flags

    # Case B: Genuinely independent external ground truth authority
    rel_legit_gt, _ = engine.evaluate_relationship(
        source_meta=meta_booklet,
        target_meta=meta_unrelated_key,
        relationship_type="question_to_answer_key",
        test_number=1,
        passage_or_section=1,
        known_ground_truth_answers={1: "TRUE", 2: "FALSE", 3: "NOT GIVEN", 4: "TRUE"},
        ground_truth_source_id="EXT-INDEPENDENT-AUTHORITY",
        ground_truth_provenance={"authority": "cambridge_esol_verified"},
    )
    assert rel_legit_gt.relationship_status == "confirmed"
    assert rel_legit_gt.match_confidence == 1.0
    assert "ANSWERS_ALIGNED" in rel_legit_gt.validation_flags
    assert "GATE_CONFIRMED_PASSED" in rel_legit_gt.validation_flags


def test_dry_run_does_not_mutate_db_or_persistent_outputs(temp_db_path, synthetic_sources_map):
    """P1: dry_run=True must not write to SQLite or default reports dir."""
    service = RelationshipMatchingService(db_path=temp_db_path)
    sources = list(synthetic_sources_map.values())[:2]

    # Dry run without explicit output_dir
    res = service.match_sources(sources_override=sources, dry_run=True, output_dir=None)

    # SQLite must have 0 rows
    conn = get_db_connection(temp_db_path)
    rels = list_source_relationships(conn)
    confs = list_relationship_conflicts(conn)
    conn.close()

    assert len(rels) == 0
    assert len(confs) == 0
    assert res["total_evaluated"] > 0

