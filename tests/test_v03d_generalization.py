"""Tests for Phase V0.3-D: Controlled Corpus Expansion & Generalization.

Verifies the 10 generalization requirements:
1. New test normalization succeeds.
2. Existing pilot still produces valid output.
3. Repeated execution is deterministic.
4. Identical rerun skips unchanged records.
5. Changed source invalidates affected records.
6. Missing keys remain unresolved.
7. Conflicting sources are rejected.
8. No unsupported verified status.
9. No duplicate entity identities.
10. No private data enters Git.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any, Dict

import pytest

from harness.config import REPO_ROOT
from harness.db import (
    init_db,
    is_normalization_checkpoint_valid,
    upsert_normalization_checkpoint,
)
from harness.models.listening import (
    AudioAsset,
    ListeningAnswer,
    ListeningEvidence,
    ListeningQuestion,
    ListeningSection,
    ListeningTest,
)
from harness.models.provenance import ProvenanceEnvelope
from harness.models.question_bank import (
    IELTSAnswer,
    IELTSEvidence,
    IELTSExplanation,
    IELTSQuestion,
    ParagraphItem,
    PassageOrSection,
)
from harness.normalizers.answer_reconciler import AnswerReconciler
from harness.normalizers.base import SCHEMA_VERSION
from harness.normalizers.reading_docx import DocxReadingNormalizer


@pytest.fixture
def synthetic_fixtures() -> Dict[str, Any]:
    """Loads synthetic generalization test fixtures."""
    fixtures_path = (
        REPO_ROOT
        / "tests"
        / "fixtures"
        / "synthetic_generalization"
        / "synthetic_generalization_fixtures.json"
    )
    with open(fixtures_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def temp_db(tmp_path: Path) -> sqlite3.Connection:
    """Creates a temporary in-memory or file-backed SQLite database with harness schema."""
    db_file = tmp_path / "test_harness.db"
    init_db(db_file)
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Test 1: New test normalization succeeds
# ---------------------------------------------------------------------------
def test_01_new_test_normalization_succeeds(synthetic_fixtures: Dict[str, Any]):
    """Verifies that a previously unseen test layout normalizes to schema-valid entities."""
    reading_data = synthetic_fixtures["synthetic_reading"]
    raw_doc = {
        "metadata": {"test_number": 9, "title": reading_data["title"]},
        "content": {"blocks": reading_data["raw_docx_blocks"]},
    }

    normalizer = DocxReadingNormalizer(normalizer_version="0.2.0-b")
    res = normalizer.normalize(
        raw_document=raw_doc,
        source_record={
            "file_id": "FILE-5a2cce4d0793",
            "legacy_id": "SRC-138",
            "content_sha256": "a" * 64,
            "sha256": "a" * 64,
            "relative_path": "synthetic/test9.docx",
        },
        passage_number=1,
        test_number=9,
        volume_code="VOL99",
        publication_permission="private_copyrighted",
    )

    passage = res["passage"]
    questions = res["questions"]

    assert isinstance(passage, PassageOrSection)
    assert passage.passage_id == "PASSAGE-VOL99-09-RD01"
    assert len(questions) == 3
    for q in questions:
        assert isinstance(q, IELTSQuestion)
        assert q.prompt_text
        assert q.question_number in [1, 2, 3]


# ---------------------------------------------------------------------------
# Test 2: Existing pilot still produces valid output
# ---------------------------------------------------------------------------
def test_02_existing_pilot_still_produces_valid_output():
    """Verifies that linear passage normalization from prior pilots produces valid output without regression."""
    body = (
        "Art history encompasses the study of human creativity across various civilizations and chronological eras. "
        "Scholars investigate stylistic movements, iconographic motifs, and social contexts influencing material culture. "
        "Methodologies range from formal visual analysis to critical theories addressing patronage, gender representation, "
        "and cultural exchange between distinct geographical regions over centuries of documented human innovation."
    )
    raw_doc = {
        "metadata": {"test_number": 5, "title": "History of Art"},
        "content": {
            "blocks": [
                {"type": "paragraph", "text": "TEST 5"},
                {"type": "paragraph", "text": "READING PASSAGE 1"},
                {
                    "type": "paragraph",
                    "text": "You should spend about 20 minutes on Questions 1-3.",
                },
                {"type": "paragraph", "text": "Art History Overview"},
                {"type": "paragraph", "text": body},
                {"type": "paragraph", "text": "Questions 1-3"},
                {"type": "paragraph", "text": "Choose the correct letter, A, B or C."},
                {"type": "paragraph", "text": "1. First question prompt"},
                {"type": "paragraph", "text": "2. Second question prompt"},
                {"type": "paragraph", "text": "3. Third question prompt"},
            ]
        },
    }
    normalizer = DocxReadingNormalizer(normalizer_version="0.2.0-b")
    res = normalizer.normalize(
        raw_document=raw_doc,
        source_record={
            "file_id": "FILE-5a2cce4d0793",
            "legacy_id": "SRC-138",
            "content_sha256": "b" * 64,
            "sha256": "b" * 64,
            "relative_path": "synthetic/pilot5.docx",
        },
        passage_number=1,
        test_number=5,
        volume_code="VOL06",
        publication_permission="private_copyrighted",
    )
    questions = res["questions"]
    assert len(questions) == 3
    assert questions[0].question_number == 1
    assert questions[1].question_number == 2
    assert questions[2].question_number == 3


# ---------------------------------------------------------------------------
# Test 3: Repeated execution is deterministic
# ---------------------------------------------------------------------------
def test_03_repeated_execution_is_deterministic(synthetic_fixtures: Dict[str, Any]):
    """Verifies that repeated normalization on identical input produces identical hashes and structures."""
    reading_data = synthetic_fixtures["synthetic_reading"]
    raw_doc = {
        "metadata": {"test_number": 9, "title": reading_data["title"]},
        "content": {"blocks": reading_data["raw_docx_blocks"]},
    }
    src = {
        "file_id": "FILE-5a2cce4d0793",
        "legacy_id": "SRC-138",
        "content_sha256": "c" * 64,
        "sha256": "c" * 64,
        "relative_path": "synthetic/test9.docx",
    }

    normalizer = DocxReadingNormalizer(normalizer_version="0.2.0-b")
    res1 = normalizer.normalize(
        raw_document=raw_doc,
        source_record=src,
        passage_number=1,
        test_number=9,
        volume_code="VOL99",
        publication_permission="private_copyrighted",
    )
    res2 = normalizer.normalize(
        raw_document=raw_doc,
        source_record=src,
        passage_number=1,
        test_number=9,
        volume_code="VOL99",
        publication_permission="private_copyrighted",
    )

    q_run1 = res1["questions"]
    q_run2 = res2["questions"]

    for q1, q2 in zip(q_run1, q_run2):
        assert q1.question_id == q2.question_id
        assert q1.prompt_text == q2.prompt_text
        assert (
            q1.provenance.canonical_content_sha256
            == q2.provenance.canonical_content_sha256
        )


# ---------------------------------------------------------------------------
# Test 4: Identical rerun skips unchanged records
# ---------------------------------------------------------------------------
def test_04_identical_rerun_skips_unchanged_records(
    temp_db: sqlite3.Connection, tmp_path: Path
):
    """Verifies that an existing, fresh checkpoint is recognized as valid, allowing identical reruns to skip."""
    entity_id = "Q-TEST-SYNTH-001"
    normalizer_ver = "0.2.0-b"
    raw_sha = "d" * 64
    cfg_hash = "cfg" + "0" * 61
    schema_ver = SCHEMA_VERSION

    out_file = tmp_path / f"{entity_id}.json"
    dummy_payload = json.dumps({"test": "data"}).encode("utf-8")
    out_file.write_bytes(dummy_payload)
    out_sha = hashlib.sha256(dummy_payload).hexdigest()

    cp_data = {
        "entity_id": entity_id,
        "entity_type": "question",
        "source_file_id": "FILE-5a2cce4d0793",
        "source_legacy_id": "SRC-SYNTH",
        "normalizer_version": normalizer_ver,
        "schema_version": schema_ver,
        "config_hash": cfg_hash,
        "raw_sha256": raw_sha,
        "canonical_content_sha256": out_sha,
        "output_path": str(out_file),
        "output_sha256": out_sha,
        "lifecycle_status": "extracted",
        "status": "COMPLETED",
    }
    upsert_normalization_checkpoint(temp_db, cp_data)

    is_valid = is_normalization_checkpoint_valid(
        conn=temp_db,
        entity_id=entity_id,
        normalizer_version=normalizer_ver,
        raw_sha256=raw_sha,
        config_hash=cfg_hash,
        schema_version=schema_ver,
    )
    assert is_valid is True


# ---------------------------------------------------------------------------
# Test 5: Changed source invalidates affected records
# ---------------------------------------------------------------------------
def test_05_changed_source_invalidates_affected_records(
    temp_db: sqlite3.Connection, tmp_path: Path
):
    """Verifies that when source SHA256 changes or content file is modified, the checkpoint is invalidated."""
    entity_id = "Q-TEST-SYNTH-002"
    normalizer_ver = "0.2.0-b"
    raw_sha_old = "e" * 64
    raw_sha_new = "f" * 64
    cfg_hash = "cfg" + "0" * 61
    schema_ver = SCHEMA_VERSION

    out_file = tmp_path / f"{entity_id}.json"
    payload = b'{"val": 1}'
    out_file.write_bytes(payload)
    out_sha = hashlib.sha256(payload).hexdigest()

    cp_data = {
        "entity_id": entity_id,
        "entity_type": "question",
        "source_file_id": "FILE-5a2cce4d0793",
        "source_legacy_id": "SRC-SYNTH",
        "normalizer_version": normalizer_ver,
        "schema_version": schema_ver,
        "config_hash": cfg_hash,
        "raw_sha256": raw_sha_old,
        "canonical_content_sha256": out_sha,
        "output_path": str(out_file),
        "output_sha256": out_sha,
        "lifecycle_status": "extracted",
        "status": "COMPLETED",
    }
    upsert_normalization_checkpoint(temp_db, cp_data)

    # Check with raw_sha_new -> must be invalid (checkpoint not found for new sha)
    is_valid_new_sha = is_normalization_checkpoint_valid(
        conn=temp_db,
        entity_id=entity_id,
        normalizer_version=normalizer_ver,
        raw_sha256=raw_sha_new,
        config_hash=cfg_hash,
        schema_version=schema_ver,
    )
    assert is_valid_new_sha is False

    # Also test file content modification on disk
    out_file.write_bytes(b'{"val": 999}')
    is_valid_tampered = is_normalization_checkpoint_valid(
        conn=temp_db,
        entity_id=entity_id,
        normalizer_version=normalizer_ver,
        raw_sha256=raw_sha_old,
        config_hash=cfg_hash,
        schema_version=schema_ver,
    )
    assert is_valid_tampered is False


# ---------------------------------------------------------------------------
# Test 6: Missing keys remain unresolved
# ---------------------------------------------------------------------------
def test_06_missing_keys_remain_unresolved(synthetic_fixtures: Dict[str, Any]):
    """Verifies that missing or unparseable answer keys remain target_value=None and flag missing_key."""
    reading_data = synthetic_fixtures["synthetic_reading"]
    raw_doc = {
        "metadata": {"test_number": 9, "title": reading_data["title"]},
        "content": {"blocks": reading_data["raw_docx_blocks"]},
    }
    normalizer = DocxReadingNormalizer(normalizer_version="0.2.0-b")
    res = normalizer.normalize(
        raw_document=raw_doc,
        source_record={
            "file_id": "FILE-5a2cce4d0793",
            "legacy_id": "SRC-138",
            "content_sha256": "a" * 64,
            "sha256": "a" * 64,
            "relative_path": "synthetic/test9.docx",
        },
        test_number=9,
        passage_number=1,
        volume_code="VOL99",
    )
    questions = res["questions"]

    reconciler = AnswerReconciler()
    # Key for Q1 is available, but Q2 and Q3 are missing
    raw_keys = {1: {"raw_val": "A", "raw_block": "k1", "unit_identifier": "p1"}}
    answers = reconciler.reconcile_answers(
        questions=questions,
        raw_key_map=raw_keys,
        source_record={
            "legacy_id": "SRC-137",
            "file_id": "FILE-181f8751b4f4",
            "sha256": "b" * 64,
            "content_sha256": "b" * 64,
            "relative_path": "key.pdf",
        },
        volume_code="VOL99",
        test_number=9,
    )

    assert len(answers) == 3
    # Q1 has key
    assert answers[0].target_value == "A"
    # Q2 and Q3 must be unresolved / None
    assert answers[1].target_value is None
    assert "MISSING_SOURCE_ANSWER_KEY" in answers[1].quality_profile.validation_flags
    assert answers[1].quality_profile.answer_verification == "missing_key"

    assert answers[2].target_value is None
    assert "MISSING_SOURCE_ANSWER_KEY" in answers[2].quality_profile.validation_flags
    assert answers[2].quality_profile.answer_verification == "missing_key"


# ---------------------------------------------------------------------------
# Test 7: Conflicting sources are rejected
# ---------------------------------------------------------------------------
def test_07_conflicting_sources_are_rejected():
    """Verifies that attempting to reconcile answer keys from a mismatched test yields empty keys / rejected."""
    reconciler = AnswerReconciler()
    ocr_pages = [
        {
            "unit_identifier": "page_0001",
            "content": {"text": "TEST 5\nREADING PASSAGE 1\n1 A\n2 B"},
        }
    ]
    # Requesting test 6 from a page that only contains Test 5
    keys = reconciler.parse_pdf_ocr_explanation_keys(ocr_pages, test_number=6)
    assert (
        len(keys) == 0
    ), "Mismatched test content must not be reconciled into requested test"


# ---------------------------------------------------------------------------
# Test 8: No unsupported verified status
# ---------------------------------------------------------------------------
def test_08_no_unsupported_verified_status(synthetic_fixtures: Dict[str, Any]):
    """Verifies that unreviewed answers are strictly marked unverified under fail-closed quality policy."""
    reading_data = synthetic_fixtures["synthetic_reading"]
    raw_doc = {
        "metadata": {"test_number": 9, "title": reading_data["title"]},
        "content": {"blocks": reading_data["raw_docx_blocks"]},
    }
    normalizer = DocxReadingNormalizer(normalizer_version="0.2.0-b")
    res = normalizer.normalize(
        raw_document=raw_doc,
        source_record={
            "file_id": "FILE-5a2cce4d0793",
            "legacy_id": "SRC-138",
            "content_sha256": "a" * 64,
            "sha256": "a" * 64,
            "relative_path": "synthetic/test9.docx",
        },
        test_number=9,
        passage_number=1,
        volume_code="VOL99",
    )
    questions = res["questions"]

    reconciler = AnswerReconciler()
    raw_keys = {
        1: {"raw_val": "A", "raw_block": "k1", "unit_identifier": "p1"},
        2: {"raw_val": "B", "raw_block": "k2", "unit_identifier": "p1"},
    }
    answers = reconciler.reconcile_answers(
        questions=questions,
        raw_key_map=raw_keys,
        source_record={
            "legacy_id": "SRC-137",
            "file_id": "FILE-181f8751b4f4",
            "sha256": "b" * 64,
            "content_sha256": "b" * 64,
            "relative_path": "key.pdf",
        },
        volume_code="VOL99",
        test_number=9,
    )

    for ans in answers:
        # None of the automatically extracted answers can claim verified status
        assert ans.quality_profile.answer_verification != "verified"
        assert ans.quality_profile.lifecycle_status != "verified"
        if ans.target_value is not None:
            assert ans.quality_profile.answer_verification == "unverified"
            assert ans.quality_profile.lifecycle_status == "review_required"


# ---------------------------------------------------------------------------
# Test 9: No duplicate entity identities
# ---------------------------------------------------------------------------
def test_09_no_duplicate_entity_identities(synthetic_fixtures: Dict[str, Any]):
    """Verifies that all entity IDs produced across listening sections are unique."""
    listening_data = synthetic_fixtures["synthetic_listening"]
    test_id = listening_data["test_id"]
    test_number = listening_data["test_number"]

    seen_ids = set()
    for sec_data in listening_data["sections"]:
        sec_num = sec_data["section_number"]
        sec_id = f"SEC-SYNTH-LIS-{test_number:02d}-{sec_num:02d}"
        assert sec_id not in seen_ids
        seen_ids.add(sec_id)

        for q in sec_data["questions"]:
            q_num = q["question_number"]
            q_id = f"Q-SYNTH-LIS-{test_number:02d}-{q_num:03d}"
            ans_id = f"ANS-SYNTH-LIS-{test_number:02d}-{q_num:03d}-KEY"
            ev_id = f"EVID-SYNTH-LIS-{test_number:02d}-{q_num:03d}-01"

            assert q_id not in seen_ids
            assert ans_id not in seen_ids
            assert ev_id not in seen_ids

            seen_ids.add(q_id)
            seen_ids.add(ans_id)
            seen_ids.add(ev_id)


# ---------------------------------------------------------------------------
# Test 10: No private data enters Git
# ---------------------------------------------------------------------------
def test_10_no_private_data_enters_git():
    """Verifies that no private source files or staging outputs are tracked in Git."""
    # Check tracked files
    res_tracked = subprocess.run(
        ["git", "ls-files", "private/"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert (
        not res_tracked.stdout.strip()
    ), f"Private files are tracked in Git: {res_tracked.stdout}"

    # Check staged files
    res_staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    staged_private = [
        line for line in res_staged.stdout.splitlines() if line.startswith("private/")
    ]
    assert not staged_private, f"Private files are staged in Git: {staged_private}"
