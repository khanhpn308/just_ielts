"""Independent Synthetic Retrieval Test Suite for IELTS Data Harness Phase V0.2-C.

Verifies all seven required TutorRetriever capabilities using pure synthetic fixtures:
1. Valid direct-support retrieval (READY)
2. NOT GIVEN retrieval with strict null quote invariant (READY)
3. Missing answer key preservation and diagnostic gating (BLOCKED)
4. Unverified / machine-drafted explanation gating (not READY -> REVIEW_REQUIRED)
5. Stale / unmanifested entity rejection
6. Missing or corrupted manifest rejection (fails closed)
7. Missing referenced entity rejection (passage, group, evidence)

Runs independently on GitHub Actions without access to the private corpus.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from harness.config import REPO_ROOT
from harness.retrieval import TutorRetriever
from harness.normalizers.base import compute_canonical_content_hash

SYNTHETIC_DIR = REPO_ROOT / "tests" / "fixtures" / "synthetic_normalized"
PRINCIPLES_DIR = REPO_ROOT / "principles"


@pytest.fixture
def synthetic_retriever() -> TutorRetriever:
    """Provides TutorRetriever initialized on synthetic normalized fixtures."""
    return TutorRetriever(normalized_dir=SYNTHETIC_DIR, principles_dir=PRINCIPLES_DIR)


def test_synthetic_retrieval_direct_support(synthetic_retriever: TutorRetriever):
    """Test 1: Valid direct-support retrieval returns complete context and READY status."""
    res = synthetic_retriever.retrieve_question("Q-VOL99-01-RD-001")

    # 1. Question prompt and hierarchical context
    assert res["question_id"] == "Q-VOL99-01-RD-001"
    assert res["question_number"] == 1
    assert res["question_type"] == "true-false-not-given"
    assert "Submerged tidal turbines" in res["prompt_text"]

    # Passage context
    assert res["passage"] is not None
    assert res["passage"]["passage_id"] == "PASSAGE-VOL99-01-RD01"
    assert "Marine Energy Systems" in res["passage"]["title"]

    # Question group context
    assert res["group"] is not None
    assert res["group"]["group_id"] == "QG-VOL99-01-RD01-G01"
    assert "TRUE, FALSE, or NOT GIVEN" in res["group"]["instruction_text"]

    # 2. Answer key verification
    assert res["answer"] is not None
    assert res["answer"]["target_value"] == "TRUE"
    assert res["answer"]["verification_status"] == "authoritative_key"
    assert res["answer"]["lifecycle_status"] == "verified"
    assert res["answer"]["is_missing"] is False

    # 3. Direct support evidence verification
    assert res["evidence"] is not None
    assert res["evidence"]["evidence_type"] == "direct_support"
    assert res["evidence"]["exact_match_verified"] is True
    assert res["evidence"]["char_start"] == 0
    assert res["evidence"]["char_end"] == 86
    assert res["evidence"]["verbatim_quote"] == (
        "Submerged tidal turbines generate predictable electrical current from marine channels."
    )

    # 4. Pedagogical explanation verification
    assert res["explanation"] is not None
    assert res["explanation"]["author_type"] == "expert_teacher"
    assert res["explanation"]["explanation_verification"] == "expert_verified"
    assert res["explanation"]["lifecycle_status"] == "verified"
    assert len(res["explanation"]["rationale_en"]) > 0

    # 5. Linked principles
    assert any(p["id"] == "RD-TFNG-001" for p in res["linked_principles"])

    # 6. Readiness evaluation: Entire chain verified -> READY
    unc = res["uncertainty_disclosure"]
    assert unc["readiness"] == "READY"
    assert unc["is_answer_missing"] is False
    assert unc["is_key_unverified"] is False
    assert unc["is_human_verified"] is True
    assert "Complete authoritative chain verified" in unc["readiness_reason"]


def test_synthetic_retrieval_not_given(synthetic_retriever: TutorRetriever):
    """Test 2: NOT GIVEN retrieval verifies null quote invariant and READY status."""
    res = synthetic_retriever.retrieve_question("Q-VOL99-01-RD-002")

    assert res["question_number"] == 2
    assert res["answer"]["target_value"] == "NOT GIVEN"

    # Strict NOT GIVEN invariant: verbatim_quote and character offsets MUST be None
    assert res["evidence"]["evidence_type"] == "insufficient_information_not_given"
    assert res["evidence"]["verbatim_quote"] is None
    assert res["evidence"]["char_start"] is None
    assert res["evidence"]["char_end"] is None
    assert res["evidence"]["exact_match_verified"] is False
    assert "records were not published" in res["evidence"]["missing_information_rationale"]

    # Explanation is verified
    assert res["explanation"]["explanation_verification"] == "expert_verified"

    # Readiness evaluation
    unc = res["uncertainty_disclosure"]
    assert unc["readiness"] == "READY"
    assert "NOT_GIVEN_EVIDENCE_INVARIANT" in unc["flags"]
    assert "NOT GIVEN item" in unc["disclosure_text"]


def test_synthetic_retrieval_missing_answer_blocked(synthetic_retriever: TutorRetriever):
    """Test 3: Missing answer key results in explicit BLOCKED readiness and critical warning."""
    res = synthetic_retriever.retrieve_question("Q-VOL99-01-RD-003")

    assert res["question_number"] == 3
    assert res["answer"]["target_value"] is None
    assert res["answer"]["is_missing"] is True
    assert res["answer"]["verification_status"] == "missing_key"

    unc = res["uncertainty_disclosure"]
    assert unc["readiness"] == "BLOCKED"
    assert unc["is_answer_missing"] is True
    assert "MISSING_SOURCE_ANSWER_KEY" in unc["flags"]
    assert "CRITICAL WARNING" in unc["disclosure_text"]
    assert "Answer key is completely missing" in unc["readiness_reason"]


def test_synthetic_retrieval_unverified_explanation_not_ready(synthetic_retriever: TutorRetriever):
    """Test 4: Unverified explanation prevents READY rating even when answer is verified."""
    res = synthetic_retriever.retrieve_question("Q-VOL99-01-RD-004")

    # Answer is authoritative and verified
    assert res["answer"]["target_value"] == "TRUE"
    assert res["answer"]["verification_status"] == "authoritative_key"
    assert res["answer"]["lifecycle_status"] == "verified"

    # Evidence is verified direct support
    assert res["evidence"]["exact_match_verified"] is True
    assert res["evidence"]["lifecycle_status"] == "verified"

    # Explanation is machine-drafted and unverified
    assert res["explanation"]["author_type"] == "machine_drafted"
    assert res["explanation"]["explanation_verification"] == "machine_drafted_unverified"
    assert res["explanation"]["lifecycle_status"] == "review_required"

    # Readiness MUST NOT be READY; must be REVIEW_REQUIRED
    unc = res["uncertainty_disclosure"]
    assert unc["readiness"] != "READY"
    assert unc["readiness"] == "REVIEW_REQUIRED"
    assert unc["is_human_verified"] is False
    assert "MACHINE_DRAFTED_EXPLANATION" in unc["flags"]
    assert "Pedagogical explanation is unverified" in unc["readiness_reason"]


def test_synthetic_retrieval_stale_entity_rejected(synthetic_retriever: TutorRetriever):
    """Test 5: Stale entity present on disk but not in active manifest is rejected."""
    # Q-VOL99-01-RD-040 is written to disk in synthetic_normalized but declared in stale_entities
    assert (SYNTHETIC_DIR / "Q-VOL99-01-RD-040.json").exists()

    with pytest.raises(ValueError, match="stale, deprecated, or not declared in the authoritative manifest"):
        synthetic_retriever.retrieve_question("Q-VOL99-01-RD-040")


def test_synthetic_retrieval_corrupted_manifest_rejected(tmp_path: Path):
    """Test 6: Missing, corrupted, or structurally invalid manifests are rejected."""
    # Case A: Missing manifest fails closed with FileNotFoundError
    with pytest.raises(FileNotFoundError, match="Authoritative manifest missing"):
        TutorRetriever(normalized_dir=tmp_path / "empty_dir")

    # Case B: Corrupted JSON manifest fails closed with ValueError
    bad_json_dir = tmp_path / "bad_json"
    bad_json_dir.mkdir()
    (bad_json_dir / "manifest.json").write_text("{ malformed json", encoding="utf-8")
    with pytest.raises(ValueError, match="is corrupted"):
        TutorRetriever(normalized_dir=bad_json_dir)

    # Case C: Manifest missing required entities list
    no_entities_dir = tmp_path / "no_entities"
    no_entities_dir.mkdir()
    (no_entities_dir / "manifest.json").write_text(
        json.dumps({"schema_version": "v0.2.0-normalized"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required 'entities' list"):
        TutorRetriever(normalized_dir=no_entities_dir)

    # Case D: Manifest total_entities count mismatch
    mismatch_dir = tmp_path / "mismatch"
    mismatch_dir.mkdir()
    (mismatch_dir / "manifest.json").write_text(
        json.dumps({
            "schema_version": "v0.2.0-normalized",
            "total_entities": 99,
            "entities": [],
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Manifest total_entities mismatch"):
        TutorRetriever(normalized_dir=mismatch_dir)

    # Case E: Unsafe output_filename with path traversal
    unsafe_dir = tmp_path / "unsafe"
    unsafe_dir.mkdir()
    (unsafe_dir / "manifest.json").write_text(
        json.dumps({
            "schema_version": "v0.2.0-normalized",
            "total_entities": 1,
            "entities": [{
                "entity_id": "Q-VOL99-01-RD-001",
                "entity_type": "question",
                "output_filename": "../escape.json",
                "canonical_content_sha256": "0" * 64,
            }],
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsafe output_filename"):
        TutorRetriever(normalized_dir=unsafe_dir)


def test_synthetic_retrieval_missing_referenced_entity_rejected(tmp_path: Path):
    """Test 7: Missing referenced entities (passage, question group) are rejected."""
    # Create valid manifest but question references non-existent passage
    test_dir = tmp_path / "missing_ref"
    test_dir.mkdir()

    # Load authentic synthetic question data and modify passage_id
    src_q = json.loads((SYNTHETIC_DIR / "Q-VOL99-01-RD-001.json").read_text(encoding="utf-8"))
    src_q["passage_id"] = "PASSAGE-NONEXISTENT-01-RD01"
    q_hash = compute_canonical_content_hash(src_q)
    src_q["_provenance"]["canonical_content_sha256"] = q_hash

    (test_dir / "Q-VOL99-01-RD-001.json").write_text(json.dumps(src_q, indent=2), encoding="utf-8")

    m_payload = {
        "schema_version": "v0.2.0-normalized",
        "total_entities": 1,
        "entities": [{
            "entity_id": "Q-VOL99-01-RD-001",
            "entity_type": "question",
            "output_filename": "Q-VOL99-01-RD-001.json",
            "canonical_content_sha256": q_hash,
        }],
    }
    (test_dir / "manifest.json").write_text(json.dumps(m_payload, indent=2), encoding="utf-8")

    retriever = TutorRetriever(normalized_dir=test_dir, principles_dir=PRINCIPLES_DIR)
    with pytest.raises(ValueError, match="Referenced passage 'PASSAGE-NONEXISTENT-01-RD01'.*failed retrieval"):
        retriever.retrieve_question("Q-VOL99-01-RD-001")


def test_synthetic_retrieval_unsafe_question_id_rejected(synthetic_retriever: TutorRetriever):
    """Verifies that path traversal and malformed question IDs are rejected."""
    unsafe_ids = [
        "../../etc/passwd",
        "Q-VOL99/01-RD-001",
        "Q-VOL99\\01-RD-001",
        "Q-VOL99-01-RD-001\0",
        "Q-1",
        "not-a-question-id",
        "",
    ]
    for bad_id in unsafe_ids:
        with pytest.raises(ValueError):
            synthetic_retriever.retrieve_question(bad_id)
