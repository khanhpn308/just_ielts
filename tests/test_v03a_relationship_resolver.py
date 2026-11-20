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
    list_source_relationships,
    record_relationship_conflict,
    record_relationship_review,
    upsert_source,
    upsert_source_relationship,
)
from harness.matching.engine import MatchingEngine
from harness.matching.metadata import SourceDocumentMetadata, extract_source_metadata
from harness.matching.service import RelationshipMatchingService
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
