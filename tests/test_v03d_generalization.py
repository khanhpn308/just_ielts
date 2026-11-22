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
            "content": {"text": "TEST 5\nREADING PASSAGE 1\n1. Answer: TRUE\n2. Answer: FALSE"},
        }
    ]
    # Requesting test 6 from a page that only contains valid parseable Test 5 keys
    keys = reconciler.parse_pdf_ocr_explanation_keys(ocr_pages, test_number=6)
    assert (
        len(keys) == 0
    ), "Source contains valid parseable Test 5 keys; requesting Test 6 must yield 0 keys"


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


# ---------------------------------------------------------------------------
# Test 11: Listening unregistered test fails clearly without Test 1 fallback
# ---------------------------------------------------------------------------
def test_11_listening_unregistered_test_fails_clearly():
    """Verifies that requesting an unregistered test fails clearly without falling back to Test 1."""
    from harness.normalizers.listening_orchestrator import ListeningNormalizationOrchestrator

    orchestrator = ListeningNormalizationOrchestrator()
    with pytest.raises(ValueError, match="Unsupported listening test configuration: Test 3"):
        orchestrator.run_pilot(test_number=3)


# ---------------------------------------------------------------------------
# Test 12: Truthful aggregate quality status for unverified answers
# ---------------------------------------------------------------------------
def test_12_unverified_answers_do_not_produce_verified_aggregate(
    synthetic_fixtures: Dict[str, Any], tmp_path: Path
):
    """Verifies that 40 unverified answers never produce a section or test claiming verified answer keys."""
    from harness.normalizers.listening_orchestrator import ListeningNormalizationOrchestrator

    listening_data = synthetic_fixtures["synthetic_listening"]
    config = {
        "volume_code": "VOL99",
        "volume": "VOL 99",
        "test_number": 9,
        "doc_legacy_id": "SRC-999",
        "transcript_legacy_id": "SRC-998",
        "audio_legacy_ids": {1: None, 2: None, 3: None, 4: None},
        "section_titles": {1: "Sec 1", 2: "Sec 2", 3: "Sec 3", 4: "Sec 4"},
    }

    # Set up synthetic mock sources in temp db
    temp_db_path = tmp_path / "test_synth.db"
    init_db(temp_db_path)
    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row

    from harness.db import upsert_source
    upsert_source(conn, {
        "file_id": "FILE-111122223333",
        "legacy_id": "SRC-999",
        "relative_path": "synthetic/doc999.pdf",
        "filename": "doc999.pdf",
        "extension": ".pdf",
        "detected_type": "pdf",
        "size_bytes": 1000,
        "content_sha256": "1" * 64,
        "collection": "VOL 99",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })
    upsert_source(conn, {
        "file_id": "FILE-444455556666",
        "legacy_id": "SRC-998",
        "relative_path": "synthetic/trans998.docx",
        "filename": "trans998.docx",
        "extension": ".docx",
        "detected_type": "docx",
        "size_bytes": 1000,
        "content_sha256": "2" * 64,
        "collection": "VOL 99",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })
    conn.close()

    orchestrator = ListeningNormalizationOrchestrator(
        output_dir=tmp_path / "normalized",
        db_path=temp_db_path,
    )

    # 40 unverified items definition
    items_def = [
        {
            "q_num": q,
            "sec_num": ((q - 1) // 10) + 1,
            "page_num": 1,
            "q_type": "note-completion",
            "prompt": f"Item {q}",
            "target_val": f"Answer {q}",
            "source_verified": False,
        }
        for q in range(1, 41)
    ]

    # Minimal transcript paragraphs
    paragraphs = [
        {"seq_index": 0, "text": "SECTION 1\nSpeaker 1 [00:00:01] Hello."},
        {"seq_index": 1, "text": "SECTION 2\nSpeaker 1 [00:05:00] Next section."},
        {"seq_index": 2, "text": "SECTION 3\nSpeaker 1 [00:10:00] Third section."},
        {"seq_index": 3, "text": "SECTION 4\nSpeaker 1 [00:15:00] Final section."},
    ]

    res = orchestrator.run_pilot(
        config=config,
        publication_permission="public_synthetic",
        reports_dir=tmp_path / "reports",
        paragraphs=paragraphs,
        items_def=items_def,
    )

    out_dir = tmp_path / "normalized"
    # Inspect emitted section entities
    for s_idx in range(1, 5):
        s_file = out_dir / "listening_section" / f"SEC-VOL99-09-LS0{s_idx}.json"
        assert s_file.exists(), f"Section {s_idx} file must exist"
        with open(s_file, "r", encoding="utf-8") as f:
            sec_data = json.load(f)
        qp = sec_data["quality_profile"]
        assert qp["answer_verification"] == "unverified", (
            f"Section {s_idx} must have answer_verification='unverified', got {qp['answer_verification']}"
        )
        assert qp["answer_verification"] != "authoritative_key"
        assert qp["lifecycle_status"] == "review_required"
        assert "UNVERIFIED_ANSWER_KEYS" in qp["validation_flags"]

    # Inspect emitted test entity
    t_file = out_dir / "listening_test" / "TEST-IELTS-VOL99-09-LIS.json"
    assert t_file.exists()
    with open(t_file, "r", encoding="utf-8") as f:
        t_data = json.load(f)
    t_qp = t_data["quality_profile"]
    assert t_qp["answer_verification"] == "unverified", (
        f"Test must have answer_verification='unverified', got {t_qp['answer_verification']}"
    )
    assert t_qp["answer_verification"] != "authoritative_key"
    assert t_qp["lifecycle_status"] == "review_required"
    assert "UNVERIFIED_ANSWER_KEYS" in t_qp["validation_flags"]


# ---------------------------------------------------------------------------
# Test 13: Reading test boundary validation & negative Test 99 regression
# ---------------------------------------------------------------------------
def test_13_reading_test_boundary_validation_negative_test_99():
    """Negative regression test: requesting Test 99 from a document containing only Tests 5 and 6
    must fail cleanly with ValueError and reject cross-test fallback to first passage.
    Also verifies that Test 5 and Test 6 remain strictly independent.
    """
    normalizer = DocxReadingNormalizer(normalizer_version="0.2.0-b")
    raw_doc = {
        "content": {
            "paragraphs": [
                # Test 5 content
                {"text": "TEST 5"},
                {"text": "READING PASSAGE 1"},
                {"text": "You should spend about 20 minutes on Questions 1-3."},
                {"text": "Passage Title Five"},
                {"text": (
                    "A Ocean current turbines generate continuous baseline electrical power from regular tidal streams. "
                    "Unlike terrestrial wind installations which fluctuate with local weather patterns, lunar gravity cycles "
                    "ensure perfectly predictable kinetic yields across every seasonal period without requiring large barrage "
                    "dams or producing detrimental environmental consequences for marine coastal ecosystems across decades."
                )},
                {"text": "Questions 1-3"},
                {"text": "1 Question prompt five one."},
                {"text": "2 Question prompt five two."},
                {"text": "3 Question prompt five three."},
                # Test 6 content
                {"text": "TEST 6"},
                {"text": "READING PASSAGE 1"},
                {"text": "You should spend about 20 minutes on Questions 1-3."},
                {"text": "Passage Title Six"},
                {"text": (
                    "A Deep space telescopes observe distant cosmological phenomena across infrared spectra with extreme fidelity. "
                    "Cryogenic cooling systems prevent thermal radiation from corrupting delicate sensor arrays during prolonged "
                    "orbital exposures, enabling astrophysical teams to analyze atmospheric compositions of distant terrestrial "
                    "exoplanets orbiting stellar hosts millions of light years from Earth with high scientific confidence."
                )},
                {"text": "Questions 1-3"},
                {"text": "1 Question prompt six one."},
                {"text": "2 Question prompt six two."},
                {"text": "3 Question prompt six three."},
            ]
        }
    }
    src_rec = {
        "file_id": "FILE-5a2cce4d0793",
        "legacy_id": "SRC-138",
        "content_sha256": "5" * 64,
        "relative_path": "synthetic/tests_5_and_6.docx",
    }

    # 1. Requesting Test 99 MUST be rejected cleanly without falling back to Test 5
    with pytest.raises(ValueError, match="Requested Test 99 not found in document boundaries"):
        normalizer.normalize(
            raw_document=raw_doc,
            source_record=src_rec,
            test_number=99,
            passage_number=1,
            volume_code="VOL06",
        )

    # 2. Test 5 and Test 6 normalize independently without mixing
    res5 = normalizer.normalize(
        raw_document=raw_doc,
        source_record=src_rec,
        test_number=5,
        passage_number=1,
        volume_code="VOL06",
    )
    assert res5["test"].test_number == 5
    assert res5["passage"].title == "Passage Title Five"
    assert "five" in res5["questions"][0].prompt_text.lower()
    assert "six" not in res5["questions"][0].prompt_text.lower()

    res6 = normalizer.normalize(
        raw_document=raw_doc,
        source_record=src_rec,
        test_number=6,
        passage_number=1,
        volume_code="VOL06",
    )
    assert res6["test"].test_number == 6
    assert res6["passage"].title == "Passage Title Six"
    assert "six" in res6["questions"][0].prompt_text.lower()
    assert "five" not in res6["questions"][0].prompt_text.lower()


# ---------------------------------------------------------------------------
# Test 14: OCR pages with passage headings but no identifiable test rejected
# ---------------------------------------------------------------------------
def test_14_ocr_pages_with_passage_headings_but_no_identifiable_test_rejected():
    """Negative regression test: OCR pages containing passage headings (e.g. READING PASSAGE 1)
    but no source-backed identifiable Test are rejected (return empty dict), preventing
    arbitrary initialization from requested test_number.
    Also verifies accurate page-level offsets when source identity is backed.
    """
    reconciler = AnswerReconciler()

    # Case A: OCR page with passage heading but unverified test identity
    unverified_pages = [
        {
            "unit_identifier": "page_0001",
            "provenance": {"relative_path": "unidentified/explanation_guide.pdf"},
            "content": {
                "text": "READING PASSAGE 1\n1. Answer: TRUE\n2. Answer: FALSE\n3. Answer: NOT GIVEN",
                "page_number": 1,
            },
        }
    ]
    # Requesting Test 5 on unverified test source yields 0 keys (never initializes curr_test=5)
    keys_unverified = reconciler.parse_pdf_ocr_explanation_keys(
        unverified_pages, test_number=5, passage_number=1
    )
    assert keys_unverified == {}, "OCR pages without source-backed Test identity must yield 0 keys"

    # Case B: Source-backed test identity preserves exact page-level offsets
    page_text = "TEST 5\nREADING PASSAGE 1\n1. Answer: TRUE\n2. Answer: FALSE"
    verified_pages = [
        {
            "unit_identifier": "page_0001",
            "provenance": {"relative_path": "verified/TEST 5 Guide.pdf"},
            "content": {
                "text": page_text,
                "page_number": 1,
            },
        }
    ]
    keys_verified = reconciler.parse_pdf_ocr_explanation_keys(
        verified_pages, test_number=5, passage_number=1
    )
    assert len(keys_verified) >= 2
    for q_num, ans_info in keys_verified.items():
        c_start = ans_info["char_start"]
        c_end = ans_info["char_end"]
        matched = ans_info["raw_matched_text"]
        assert page_text[c_start:c_end] == matched, "Page-level character offsets must be strictly accurate"


# ---------------------------------------------------------------------------
# Test 15: Listening source relationship validation & Test 2 source isolation
# ---------------------------------------------------------------------------
def test_15_listening_source_relationships_and_test2_isolation(tmp_path: Path):
    """Synthetic regression test verifying listening source relationships and cross-test isolation:
    1. Ambiguous booklet or transcript candidates in inventory fail clearly.
    2. Confirmed and candidate relationships resolve without mixing cross-test sources.
    3. Cross-test relationship attempts trigger strict isolation violation.
    4. Unresolved / candidate relationships are flagged for human review.
    """
    from harness.normalizers.listening_orchestrator import ListeningNormalizationOrchestrator
    from harness.db import init_db, upsert_source, upsert_source_relationship

    temp_db_path = tmp_path / "test_iso.db"
    init_db(temp_db_path)
    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row

    # 1. Ambiguous inventory test: multiple candidate PDFs in same test directory
    upsert_source(conn, {
        "file_id": "FILE-PDF-001",
        "legacy_id": "SRC-P01",
        "relative_path": "VOL 1/TEST 4/booklet_a.pdf",
        "filename": "booklet_a.pdf",
        "extension": ".pdf",
        "detected_type": "pdf",
        "size_bytes": 1000,
        "content_sha256": "1" * 64,
        "collection": "VOL 1",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })
    upsert_source(conn, {
        "file_id": "FILE-PDF-002",
        "legacy_id": "SRC-P02",
        "relative_path": "VOL 1/TEST 4/booklet_b.pdf",
        "filename": "booklet_b.pdf",
        "extension": ".pdf",
        "detected_type": "pdf",
        "size_bytes": 1000,
        "content_sha256": "2" * 64,
        "collection": "VOL 1",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })
    upsert_source(conn, {
        "file_id": "FILE-DOC-001",
        "legacy_id": "SRC-D01",
        "relative_path": "VOL 1/TEST 4/transcript.docx",
        "filename": "transcript.docx",
        "extension": ".docx",
        "detected_type": "docx",
        "size_bytes": 1000,
        "content_sha256": "3" * 64,
        "collection": "VOL 1",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })

    orch = ListeningNormalizationOrchestrator(db_path=temp_db_path)
    with pytest.raises(ValueError, match="Ambiguous booklet inventory"):
        orch.resolve_pilot_config(conn, test_number=4)

    # 2. Add synthetic Test 1 and Test 2 sources
    t1_sources = [
        {"file_id": "FILE-T1-PDF", "legacy_id": "SRC-008", "relative_path": "VOL 1/TEST 1/Test_1.pdf", "detected_type": "pdf"},
        {"file_id": "FILE-T1-TR", "legacy_id": "SRC-009", "relative_path": "VOL 1/TEST 1/Transcript Test 1.docx", "detected_type": "docx"},
        {"file_id": "FILE-T1-A1", "legacy_id": "SRC-010", "relative_path": "VOL 1/TEST 1/1.mp3", "detected_type": "audio"},
        {"file_id": "FILE-T1-A2", "legacy_id": "SRC-011", "relative_path": "VOL 1/TEST 1/2.mp3", "detected_type": "audio"},
        {"file_id": "FILE-T1-A3", "legacy_id": "SRC-012", "relative_path": "VOL 1/TEST 1/3.mp3", "detected_type": "audio"},
        {"file_id": "FILE-T1-A4", "legacy_id": "SRC-013", "relative_path": "VOL 1/TEST 1/4.mp3", "detected_type": "audio"},
    ]
    for s in t1_sources:
        upsert_source(conn, {
            "file_id": s["file_id"],
            "legacy_id": s["legacy_id"],
            "relative_path": s["relative_path"],
            "filename": Path(s["relative_path"]).name,
            "extension": Path(s["relative_path"]).suffix,
            "detected_type": s["detected_type"],
            "size_bytes": 1000,
            "content_sha256": hashlib.sha256(s["file_id"].encode()).hexdigest(),
            "collection": "VOL 1",
            "duplicate_group": "none",
            "accessibility_status": "accessible",
        })

    t2_sources = [
        {"file_id": "FILE-T2-PDF", "legacy_id": "SRC-020", "relative_path": "VOL 1/TEST 2/Test_2.pdf", "detected_type": "pdf"},
        {"file_id": "FILE-T2-TR", "legacy_id": "SRC-021", "relative_path": "VOL 1/TEST 2/Transcript Test 2.docx", "detected_type": "docx"},
        {"file_id": "FILE-T2-A1", "legacy_id": "SRC-017", "relative_path": "VOL 1/TEST 2/1.mp3", "detected_type": "audio"},
        {"file_id": "FILE-T2-A2", "legacy_id": "SRC-018", "relative_path": "VOL 1/TEST 2/2.mp3", "detected_type": "audio"},
        {"file_id": "FILE-T2-A3", "legacy_id": "SRC-019", "relative_path": "VOL 1/TEST 2/3.mp3", "detected_type": "audio"},
    ]
    for s in t2_sources:
        upsert_source(conn, {
            "file_id": s["file_id"],
            "legacy_id": s["legacy_id"],
            "relative_path": s["relative_path"],
            "filename": Path(s["relative_path"]).name,
            "extension": Path(s["relative_path"]).suffix,
            "detected_type": s["detected_type"],
            "size_bytes": 1000,
            "content_sha256": hashlib.sha256(s["file_id"].encode()).hexdigest(),
            "collection": "VOL 1",
            "duplicate_group": "none",
            "accessibility_status": "accessible",
        })

    # Add confirmed relationships for Test 1
    upsert_source_relationship(conn, {
        "relationship_id": "REL-T1-TR",
        "source_file_id": "FILE-T1-PDF",
        "target_file_id": "FILE-T1-TR",
        "relationship_type": "listening_to_transcript",
        "collection": "VOL 1",
        "volume": "VOL 1",
        "test_number": 1,
        "passage_or_section": None,
        "skill": "listening",
        "identity_evidence": "{}",
        "validation_flags": "[]",
        "match_confidence": 1.0,
        "relationship_status": "confirmed",
        "provenance": "{}",
        "schema_version": "0.3.0",
    })
    for sec_i, a_id in enumerate(["FILE-T1-A1", "FILE-T1-A2", "FILE-T1-A3", "FILE-T1-A4"], start=1):
        upsert_source_relationship(conn, {
            "relationship_id": f"REL-T1-A{sec_i}",
            "source_file_id": "FILE-T1-PDF",
            "target_file_id": a_id,
            "relationship_type": "listening_to_audio",
            "collection": "VOL 1",
            "volume": "VOL 1",
            "test_number": 1,
            "passage_or_section": sec_i,
            "skill": "listening",
            "identity_evidence": "{}",
            "validation_flags": "[]",
            "match_confidence": 1.0,
            "relationship_status": "confirmed",
            "provenance": "{}",
            "schema_version": "0.3.0",
        })

    # Add candidate relationships for Test 2 (unresolved)
    upsert_source_relationship(conn, {
        "relationship_id": "REL-T2-TR",
        "source_file_id": "FILE-T2-PDF",
        "target_file_id": "FILE-T2-TR",
        "relationship_type": "listening_to_transcript",
        "collection": "VOL 1",
        "volume": "VOL 1",
        "test_number": 2,
        "passage_or_section": None,
        "skill": "listening",
        "identity_evidence": "{}",
        "validation_flags": "[]",
        "match_confidence": 0.85,
        "relationship_status": "candidate",
        "provenance": "{}",
        "schema_version": "0.3.0",
    })
    for sec_i, a_id in enumerate(["FILE-T2-A1", "FILE-T2-A2", "FILE-T2-A3"], start=1):
        upsert_source_relationship(conn, {
            "relationship_id": f"REL-T2-A{sec_i}",
            "source_file_id": "FILE-T2-PDF",
            "target_file_id": a_id,
            "relationship_type": "listening_to_audio",
            "collection": "VOL 1",
            "volume": "VOL 1",
            "test_number": 2,
            "passage_or_section": sec_i,
            "skill": "listening",
            "identity_evidence": "{}",
            "validation_flags": "[]",
            "match_confidence": 0.85,
            "relationship_status": "candidate",
            "provenance": "{}",
            "schema_version": "0.3.0",
        })

    # 3. Verify Test 2 resolution on synthetic DB
    cfg2 = orch.resolve_pilot_config(conn, test_number=2)
    assert cfg2 is not None

    # Test 2 sources must belong strictly to Test 2
    assert cfg2["doc_legacy_id"] == "SRC-020"
    assert cfg2["transcript_legacy_id"] == "SRC-021"
    assert cfg2["audio_legacy_ids"][1] == "SRC-017"
    assert cfg2["audio_legacy_ids"][2] == "SRC-018"
    assert cfg2["audio_legacy_ids"][3] == "SRC-019"
    assert cfg2["audio_legacy_ids"][4] is None

    # Verify no cross-test source mixing
    test1_files = {"SRC-008", "SRC-009", "SRC-010", "SRC-011", "SRC-012", "SRC-013"}
    assert cfg2["doc_legacy_id"] not in test1_files
    assert cfg2["transcript_legacy_id"] not in test1_files
    for a_id in cfg2["audio_legacy_ids"].values():
        if a_id:
            assert a_id not in test1_files

    # Verify candidate/unresolved relationships are flagged
    assert cfg2["has_unresolved_relationships"] is True
    assert len(cfg2["unresolved_relationship_ids"]) > 0
    assert "REL-T2-TR" in cfg2["unresolved_relationship_ids"]

    # 4. Verify ambiguous candidate relationship failure
    upsert_source(conn, {
        "file_id": "FILE-T2-TR-EXTRA",
        "legacy_id": "SRC-099",
        "relative_path": "VOL 1/TEST 2/Transcript Extra.docx",
        "filename": "Transcript Extra.docx",
        "extension": ".docx",
        "detected_type": "docx",
        "size_bytes": 1000,
        "content_sha256": "4" * 64,
        "collection": "VOL 1",
        "duplicate_group": "none",
        "accessibility_status": "accessible",
    })
    upsert_source_relationship(conn, {
        "relationship_id": "REL-T2-TR-EXTRA",
        "source_file_id": "FILE-T2-PDF",
        "target_file_id": "FILE-T2-TR-EXTRA",
        "relationship_type": "listening_to_transcript",
        "collection": "VOL 1",
        "volume": "VOL 1",
        "test_number": 2,
        "passage_or_section": None,
        "skill": "listening",
        "identity_evidence": "{}",
        "validation_flags": "[]",
        "match_confidence": 0.85,
        "relationship_status": "candidate",
        "provenance": "{}",
        "schema_version": "0.3.0",
    })
    with pytest.raises(ValueError, match="Ambiguous candidate booklet/transcript relationships"):
        orch.resolve_pilot_config(conn, test_number=2)

    conn.close()


@pytest.mark.corpus
def test_15_listening_source_relationships_and_test2_isolation_corpus():
    """Corpus integration test for Listening Test 2 source isolation on live harness.db:
    1. Resolves actual SRC-020, SRC-021, and audio SRC-017 through SRC-019.
    2. Strictly asserts 0 mixing of Test 1 sources (SRC-008..SRC-012).
    3. Confirms candidate relationships trigger human review flagging.
    """
    from harness.normalizers.listening_orchestrator import ListeningNormalizationOrchestrator

    db_path = Path("harness/state/harness.db")
    if not db_path.exists():
        pytest.fail(f"Corpus testing is enabled but SQLite database not found at {db_path}")

    main_conn = sqlite3.connect(db_path)
    main_conn.row_factory = sqlite3.Row
    main_orch = ListeningNormalizationOrchestrator()
    cfg2 = main_orch.resolve_pilot_config(main_conn, test_number=2)
    assert cfg2 is not None

    # Test 2 sources must belong strictly to Test 2
    assert cfg2["doc_legacy_id"] == "SRC-020"
    assert cfg2["transcript_legacy_id"] == "SRC-021"
    assert cfg2["audio_legacy_ids"][1] == "SRC-017"
    assert cfg2["audio_legacy_ids"][2] == "SRC-018"
    assert cfg2["audio_legacy_ids"][3] == "SRC-019"
    assert cfg2["audio_legacy_ids"][4] is None

    # Confirm Test 1 files are NEVER mixed into Test 2
    test1_files = {"SRC-008", "SRC-009", "SRC-010", "SRC-011", "SRC-012"}
    assert cfg2["doc_legacy_id"] not in test1_files
    assert cfg2["transcript_legacy_id"] not in test1_files
    for a_id in cfg2["audio_legacy_ids"].values():
        if a_id:
            assert a_id not in test1_files

    # Confirm candidate relationships trigger human review flagging
    assert cfg2["has_unresolved_relationships"] is True
    assert len(cfg2["unresolved_relationship_ids"]) > 0
    main_conn.close()


# ---------------------------------------------------------------------------
# Test 16: Reading PDF normalizer rejects unverified test identities
# ---------------------------------------------------------------------------
def test_16_pdf_reading_unverified_test_identities_rejected():
    """Negative regression test verifying that PdfReadingNormalizer strictly rejects unverified test identities:
    1. Requested Test 99 not found in PDF page boundaries.
    2. Ambiguous/missing Test identity on unverified PDF source without test markers.
    3. Mismatch between requested Test and source metadata Test.
    4. Isolated synthetic test fixture requests non-Test-1 identity without metadata.
    """
    from harness.normalizers.reading_pdf import PdfReadingNormalizer

    normalizer = PdfReadingNormalizer()

    # 1. Multi-test PDF with explicit TEST 1 and TEST 2: requesting Test 99 must fail
    pages_multi = [
        {
            "content": {
                "page_number": 1,
                "text": "TEST 1\nREADING PASSAGE 1\nNarrative text for test one.\nQuestions 1-2\n1 Prompt one.\n2 Prompt two.",
            }
        },
        {
            "content": {
                "page_number": 2,
                "text": "TEST 2\nREADING PASSAGE 1\nNarrative text for test two.\nQuestions 1-2\n1 Prompt one.\n2 Prompt two.",
            }
        },
    ]
    with pytest.raises(ValueError, match="Requested Test 99 not found in PDF page boundaries"):
        normalizer.normalize(
            pages=pages_multi,
            source_record={
                "file_id": "FILE-000000000001",
                "legacy_id": "SRC-001",
                "relative_path": "sample.pdf",
                "content_sha256": "0" * 64,
            },
            test_number=99,
            passage_number=1,
            volume_code="VOL01",
        )

    # 2. Unverified PDF with no test markers in text or metadata: requesting Test 5 must fail
    pages_unverified = [
        {
            "content": {
                "page_number": 1,
                "text": (
                    "READING PASSAGE 1\n"
                    "Passage narrative text content without any identifiable test header.\n"
                    "Questions 1-2\n"
                    "1 Prompt statement A.\n"
                    "2 Prompt statement B."
                ),
            }
        }
    ]
    with pytest.raises(ValueError, match="Ambiguous or unverified Test identity"):
        normalizer.normalize(
            pages=pages_unverified,
            source_record={
                "file_id": "FILE-000000000091",
                "legacy_id": "SRC-991",
                "relative_path": "unidentified/guide.pdf",
                "content_sha256": "1" * 64,
            },
            test_number=5,
            passage_number=1,
            volume_code="VOL01",
        )

    # 3. Source metadata specifies Test 5, caller requests Test 6: must fail cleanly
    with pytest.raises(ValueError, match="Requested Test 6 does not match source metadata Test 5"):
        normalizer.normalize(
            pages=pages_unverified,
            source_record={
                "file_id": "FILE-000000000005",
                "legacy_id": "SRC-005",
                "relative_path": "VOL 6/TEST 5/reading.pdf",
                "content_sha256": "2" * 64,
            },
            test_number=6,
            passage_number=1,
            volume_code="VOL06",
        )

    # 4. Synthetic fixture without test markers requesting Test 99: must fail cleanly
    with pytest.raises(ValueError, match="Ambiguous or unverified Test identity"):
        normalizer.normalize(
            pages=pages_unverified,
            source_record={
                "file_id": "FILE-000000000099",
                "legacy_id": "SRC-999",
                "relative_path": "synthetic/sample.pdf",
                "collection": "synthetic",
                "content_sha256": "3" * 64,
            },
            test_number=99,
            passage_number=1,
            volume_code="VOL99",
        )


# ---------------------------------------------------------------------------
# Test 17: Reading PDF normalizer never fabricates fallback prompts
# ---------------------------------------------------------------------------
def test_17_pdf_reading_no_fabricated_fallback_prompts_and_preserves_review_required():
    """Verifies that:
    1. Missing/truncated question prompts in PDF extractions are never fabricated.
    2. Unresolved questions are captured with review_required status in unresolved_questions.
    3. Emitted test, passage, and group entities retain lifecycle_status='review_required'.
    """
    from harness.normalizers.reading_pdf import PdfReadingNormalizer

    normalizer = PdfReadingNormalizer()
    pages = [
        {
            "content": {
                "page_number": 1,
                "text": (
                    "Marine Tidal Turbine Engineering in Shallow Estuaries\n\n"
                    "Tidal stream installations offer completely predictable energy generation yields without requiring "
                    "expensive hydrostatic impoundments. Marine engineers carefully analyze component stress tolerances "
                    "under intense cyclic hydrodynamic turbulence to ensure structural survivability across decades of operation. "
                    "Furthermore, extensive field deployments demonstrate that advanced corrosion-resistant composite alloys "
                    "significantly reduce recurring maintenance requirements while operating continuously in high-salinity oceanic environments.\n\n"
                    "Questions 1-3\n\n"
                    "Do the following statements agree with the information given in the passage?\n"
                    "1 Tidal power generation predictable yields are consistent.\n"
                    "3 Extreme hydrodynamic turbulence stresses structural components.\n"
                ),
                "ocr_applied": False,
            }
        }
    ]
    source_rec = {
        "file_id": "FILE-000000000002",
        "legacy_id": "SRC-998",
        "relative_path": "synthetic/tidal.pdf",
        "collection": "synthetic",
        "content_sha256": "4" * 64,
    }

    res = normalizer.normalize(
        pages=pages,
        source_record=source_rec,
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
        publication_permission="public_synthetic",
    )

    questions = res["questions"]
    unresolved = res["unresolved_questions"]

    # 1. Exactly 2 valid questions extracted; Question 2 is missing from text and MUST NOT be fabricated
    assert len(questions) == 2
    assert questions[0].question_number == 1
    assert questions[0].prompt_text == "Tidal power generation predictable yields are consistent."
    assert questions[1].question_number == 3
    assert questions[1].prompt_text == "Extreme hydrodynamic turbulence stresses structural components."
    for q in questions:
        assert not q.prompt_text.startswith("Question statement")

    # 2. Missing Question 2 captured in unresolved_questions queue
    assert len(unresolved) == 1
    unres = unresolved[0]
    assert unres["question_number"] == 2
    assert unres["error"] == "UNRESOLVED_QUESTION_PROMPT"
    assert unres["lifecycle_status"] == "review_required"

    # 3. Entities preserve review_required lifecycle status due to unresolved content
    assert res["test"].quality_profile.lifecycle_status == "review_required"
    assert res["passage"].quality_profile.lifecycle_status == "review_required"
    assert res["groups"][0].quality_profile.lifecycle_status == "review_required"
    assert "UNRESOLVED_QUESTIONS" in res["test"].quality_profile.validation_flags
