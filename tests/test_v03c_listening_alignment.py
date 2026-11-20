"""Fully synthetic regression tests for IELTS Listening Normalization & Audio Alignment (V0.3-C).

Tests run entirely against synthetic fixtures and SQLite memory/temp databases without
requiring private raw files or network access.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import sqlite3
import tempfile

from harness.config import REPO_ROOT
from harness.db import (
    get_db_connection,
    init_db,
    is_normalization_checkpoint_valid,
    upsert_normalization_checkpoint,
    upsert_source,
)
from harness.models.listening import (
    SCHEMA_VERSION_LISTENING,
    AudioAsset,
    ListeningAnswer,
    ListeningEvidence,
    ListeningQuestion,
    ListeningSection,
    ListeningTest,
    SpeakerTurn,
    TranscriptSegment,
)
from harness.models.provenance import ProvenanceEnvelope
from harness.models.quality import QualityProfile
from harness.normalizers.audio_aligner import AudioAligner
from harness.normalizers.base import BaseNormalizer, validate_output_privacy
from harness.normalizers.listening_orchestrator import (
    NORMALIZER_VERSION_LISTENING,
    ListeningNormalizationOrchestrator,
)
from harness.normalizers.listening_question import (
    RAW_LISTENING_QUESTIONS_DEF,
    ListeningQuestionNormalizer,
)
from harness.normalizers.transcript import (
    TranscriptNormalizer,
    parse_timestamp_to_ms,
)

FIXTURES_PATH = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "synthetic_listening"
    / "synthetic_listening_fixtures.json"
)


@pytest.fixture
def synthetic_data() -> dict:
    """Loads synthetic listening test fixtures."""
    with open(FIXTURES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def temp_db() -> sqlite3.Connection:
    """Creates an isolated temporary SQLite database for test checkpoints."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = Path(tf.name)
    init_db(db_path)
    conn = get_db_connection(db_path)
    yield conn
    conn.close()
    if db_path.exists():
        db_path.unlink(missing_ok=True)


# ==============================================================================
# TEST 1: Correct Transcript Segmentation
# ==============================================================================
def test_transcript_segmentation(synthetic_data):
    """Verifies that transcript paragraphs are accurately partitioned across 4 sections."""
    norm = TranscriptNormalizer()
    src = synthetic_data["sources"]["transcript_doc"]
    paras = synthetic_data["transcript_paragraphs"]

    sections = norm.segment_transcript(
        paragraphs=paras,
        source_record=src,
        volume_code="VOL99",
        test_number=1,
    )

    assert len(sections) == 4
    assert len(sections[1]["segments"]) > 0
    assert len(sections[2]["segments"]) > 0
    assert len(sections[3]["segments"]) > 0
    assert len(sections[4]["segments"]) > 0

    # Section IDs must be distinct and sequential
    for sec_num in range(1, 5):
        sec_id = f"SEC-VOL99-01-LS{sec_num:02d}"
        for seg in sections[sec_num]["segments"]:
            assert seg.section_id == sec_id
            assert seg.test_id == "TEST-IELTS-VOL99-01-LIS"


# ==============================================================================
# TEST 2: Speaker-Turn Preservation
# ==============================================================================
def test_speaker_turn_preservation(synthetic_data):
    """Verifies that speaker labels and consecutive speaker turns are preserved without loss."""
    norm = TranscriptNormalizer()
    src = synthetic_data["sources"]["transcript_doc"]
    paras = synthetic_data["transcript_paragraphs"]

    sections = norm.segment_transcript(
        paragraphs=paras,
        source_record=src,
        volume_code="VOL99",
        test_number=1,
    )

    sec1_turns = sections[1]["speaker_turns"]
    assert len(sec1_turns) >= 3

    # Check speakers in section 1
    speakers = [t.speaker_id for t in sec1_turns]
    assert "Speaker 1" in speakers
    assert "Speaker 2" in speakers

    # Verbatim text check
    turn1_text = sec1_turns[0].text
    assert "Welcome to the synthetic festival" in turn1_text


# ==============================================================================
# TEST 3: Valid Timestamps Alignment
# ==============================================================================
def test_valid_timestamps(synthetic_data):
    """Verifies that valid intervals within audio duration are marked verified with 0 <= start < end <= duration."""
    norm = TranscriptNormalizer()
    aligner = AudioAligner()
    src_t = synthetic_data["sources"]["transcript_doc"]
    paras = synthetic_data["transcript_paragraphs"]

    sections = norm.segment_transcript(paragraphs=paras, source_record=src_t)
    sec1_segs = sections[1]["segments"]

    # Construct synthetic audio asset with duration 10 minutes (600,000 ms)
    prov = ProvenanceEnvelope(
        source_file_id="FILE-a00000000003",
        source_legacy_id="SRC-9903",
        relative_path="data/synthetic/VOL99/AudioTrack_01.mp3",
        source_sha256="c" * 64,
        processing_unit="audio",
        unit_identifier="audio_metadata",
        raw_block_locator="header",
        extractor_adapter="audio_meta",
        extractor_version="0.1.0",
        normalizer_version="0.3.0-c",
    )
    qp = QualityProfile(
        lifecycle_status="verified",
        extraction_quality="complete_clean",
        source_fidelity="authoritative_official",
        answer_verification="unverified",
        explanation_verification="missing_explanation",
        publication_permission="public_synthetic",
        validation_flags=["AUDIO_SOURCE_VERIFIED"],
    )
    audio = AudioAsset(
        audio_id="AUDIO-VOL99-01-SEC01",
        test_id="TEST-IELTS-VOL99-01-LIS",
        section_number=1,
        file_path="data/synthetic/VOL99/AudioTrack_01.mp3",
        source_file_id="FILE-a00000000003",
        source_sha256="c" * 64,
        format="mp3",
        duration_ms=600000,
        duration_sec=600.0,
        audio_verification_status="verified",
        quality_profile=qp,
        _provenance=prov,
    )

    aligned, audit = aligner.align_section_audio(1, sec1_segs, audio)

    assert audit["verified_count"] > 0
    assert audit["impossible_bounds_count"] == 0
    assert audit["out_of_order_count"] == 0

    for seg in aligned:
        if seg.start_ms is not None:
            assert seg.timing_verification_status == "verified"
            assert 0 <= seg.start_ms
            if seg.end_ms is not None:
                assert seg.start_ms < seg.end_ms <= audio.duration_ms


# ==============================================================================
# TEST 4: Impossible Timestamps
# ==============================================================================
def test_impossible_timestamps(synthetic_data):
    """Verifies that timestamps exceeding audio duration or with start >= end are flagged impossible_bounds."""
    norm = TranscriptNormalizer()
    aligner = AudioAligner()
    src_t = synthetic_data["sources"]["transcript_doc"]
    impos_paras = synthetic_data["anomaly_paragraphs"]["impossible_timestamps"]

    sections = norm.segment_transcript(paragraphs=impos_paras, source_record=src_t)
    segs = sections[1]["segments"]

    # Audio track of only 60 seconds (60,000 ms)
    prov = ProvenanceEnvelope(
        source_file_id="FILE-a00000000003",
        source_legacy_id="SRC-9903",
        relative_path="data/synthetic/VOL99/AudioTrack_01.mp3",
        source_sha256="c" * 64,
        processing_unit="audio",
        unit_identifier="audio_metadata",
        raw_block_locator="header",
        extractor_adapter="audio_meta",
        extractor_version="0.1.0",
        normalizer_version="0.3.0-c",
    )
    qp = QualityProfile(
        lifecycle_status="verified",
        extraction_quality="complete_clean",
        source_fidelity="authoritative_official",
        answer_verification="unverified",
        explanation_verification="missing_explanation",
        publication_permission="public_synthetic",
        validation_flags=[],
    )
    short_audio = AudioAsset(
        audio_id="AUDIO-VOL99-01-SEC01",
        test_id="TEST-IELTS-VOL99-01-LIS",
        section_number=1,
        file_path="data/synthetic/VOL99/AudioTrack_01.mp3",
        source_file_id="FILE-a00000000003",
        source_sha256="c" * 64,
        format="mp3",
        duration_ms=60000,
        duration_sec=60.0,
        audio_verification_status="verified",
        quality_profile=qp,
        _provenance=prov,
    )

    aligned, audit = aligner.align_section_audio(1, segs, short_audio)

    assert audit["impossible_bounds_count"] == len(segs)
    assert audit["verified_count"] == 0
    for seg in aligned:
        assert seg.timing_verification_status == "impossible_bounds"


# ==============================================================================
# TEST 5: Out-of-Order Intervals
# ==============================================================================
def test_out_of_order_intervals(synthetic_data):
    """Verifies that non-chronological intervals (start_ms < prev_start_ms) are flagged out_of_order."""
    norm = TranscriptNormalizer()
    aligner = AudioAligner()
    src_t = synthetic_data["sources"]["transcript_doc"]
    ooo_paras = synthetic_data["anomaly_paragraphs"]["out_of_order_timestamps"]

    sections = norm.segment_transcript(paragraphs=ooo_paras, source_record=src_t)
    segs = sections[1]["segments"]

    prov = ProvenanceEnvelope(
        source_file_id="FILE-a00000000003",
        source_legacy_id="SRC-9903",
        relative_path="data/synthetic/VOL99/AudioTrack_01.mp3",
        source_sha256="c" * 64,
        processing_unit="audio",
        unit_identifier="audio_metadata",
        raw_block_locator="header",
        extractor_adapter="audio_meta",
        extractor_version="0.1.0",
        normalizer_version="0.3.0-c",
    )
    qp = QualityProfile(
        lifecycle_status="verified",
        extraction_quality="complete_clean",
        source_fidelity="authoritative_official",
        answer_verification="unverified",
        explanation_verification="missing_explanation",
        publication_permission="public_synthetic",
        validation_flags=[],
    )
    audio = AudioAsset(
        audio_id="AUDIO-VOL99-01-SEC01",
        test_id="TEST-IELTS-VOL99-01-LIS",
        section_number=1,
        file_path="data/synthetic/VOL99/AudioTrack_01.mp3",
        source_file_id="FILE-a00000000003",
        source_sha256="c" * 64,
        format="mp3",
        duration_ms=600000,
        duration_sec=600.0,
        audio_verification_status="verified",
        quality_profile=qp,
        _provenance=prov,
    )

    aligned, audit = aligner.align_section_audio(1, segs, audio)

    assert audit["out_of_order_count"] >= 1
    # Second segment was 00:01:30 after 00:03:00 -> out_of_order
    assert aligned[1].timing_verification_status == "out_of_order"


# ==============================================================================
# TEST 6: Missing Timestamp Handling
# ==============================================================================
def test_missing_timestamp_handling(synthetic_data):
    """Verifies that lines without timestamps preserve order, set unaligned, and never invent timestamps."""
    norm = TranscriptNormalizer()
    aligner = AudioAligner()
    src_t = synthetic_data["sources"]["transcript_doc"]
    missing_paras = synthetic_data["anomaly_paragraphs"]["missing_timestamps"]

    sections = norm.segment_transcript(paragraphs=missing_paras, source_record=src_t)
    segs = sections[1]["segments"]

    prov = ProvenanceEnvelope(
        source_file_id="FILE-a00000000003",
        source_legacy_id="SRC-9903",
        relative_path="data/synthetic/VOL99/AudioTrack_01.mp3",
        source_sha256="c" * 64,
        processing_unit="audio",
        unit_identifier="audio_metadata",
        raw_block_locator="header",
        extractor_adapter="audio_meta",
        extractor_version="0.1.0",
        normalizer_version="0.3.0-c",
    )
    qp = QualityProfile(
        lifecycle_status="verified",
        extraction_quality="complete_clean",
        source_fidelity="authoritative_official",
        answer_verification="unverified",
        explanation_verification="missing_explanation",
        publication_permission="public_synthetic",
        validation_flags=[],
    )
    audio = AudioAsset(
        audio_id="AUDIO-VOL99-01-SEC01",
        test_id="TEST-IELTS-VOL99-01-LIS",
        section_number=1,
        file_path="data/synthetic/VOL99/AudioTrack_01.mp3",
        source_file_id="FILE-a00000000003",
        source_sha256="c" * 64,
        format="mp3",
        duration_ms=600000,
        duration_sec=600.0,
        audio_verification_status="verified",
        quality_profile=qp,
        _provenance=prov,
    )

    aligned, audit = aligner.align_section_audio(1, segs, audio)

    assert audit["unaligned_count"] == len(segs)
    for seg in aligned:
        assert seg.start_ms is None
        assert seg.timing_verification_status == "unaligned"
        assert seg.timing_source == "unaligned"


# ==============================================================================
# TEST 7: Question-to-Section Mapping
# ==============================================================================
def test_question_to_section_mapping(synthetic_data):
    """Verifies that all 40 questions are properly partitioned into 4 distinct sections."""
    q_norm = ListeningQuestionNormalizer()
    src_doc = synthetic_data["sources"]["question_doc"]

    questions, answers, evidence = q_norm.normalize_listening_test_items(
        doc_source_record=src_doc,
        transcript_segments_by_sec={s: [] for s in range(1, 5)},
        volume_code="VOL99",
        test_number=1,
        publication_permission="public_synthetic",
    )

    assert len(questions) == 40
    assert len(answers) == 40
    assert len(evidence) == 40

    sec_q_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for q in questions:
        # Determine section number from section_id
        sec_num = int(q.section_id[-2:])
        sec_q_counts[sec_num] += 1

    assert sec_q_counts[1] == 10
    assert sec_q_counts[2] == 10
    assert sec_q_counts[3] == 10
    assert sec_q_counts[4] == 10


# ==============================================================================
# TEST 8: Answer Provenance
# ==============================================================================
def test_answer_provenance(synthetic_data):
    """Verifies that every answer entity has authoritative provenance, source key reference, and valid format."""
    q_norm = ListeningQuestionNormalizer()
    src_doc = synthetic_data["sources"]["question_doc"]

    questions, answers, evidence = q_norm.normalize_listening_test_items(
        doc_source_record=src_doc,
        transcript_segments_by_sec={s: [] for s in range(1, 5)},
        volume_code="VOL99",
        test_number=1,
        publication_permission="public_synthetic",
    )

    for ans in answers:
        assert ans.answer_provenance_status == "authoritative_source"
        assert ans.source_key_ref.startswith("SRC-011")
        assert ans.target_value is not None and len(ans.target_value) > 0
        assert ans.provenance.source_file_id == src_doc["file_id"]
        assert ans.provenance.source_sha256 == src_doc["content_sha256"]


# ==============================================================================
# TEST 9: Cross-Test Mismatch
# ==============================================================================
def test_cross_test_mismatch(synthetic_data):
    """Verifies that an answer cannot be linked to a question from a different test ID."""
    q_norm = ListeningQuestionNormalizer()
    src_doc = synthetic_data["sources"]["question_doc"]

    _, answers, _ = q_norm.normalize_listening_test_items(
        doc_source_record=src_doc,
        transcript_segments_by_sec={s: [] for s in range(1, 5)},
        volume_code="VOL99",
        test_number=1,
        publication_permission="public_synthetic",
    )

    ans = answers[0]

    # Attempting to assign a mismatched test_id violates regex or relationship invariant
    with pytest.raises(Exception):
        ListeningAnswer(
            answer_id=ans.answer_id,
            question_id="Q-VOL88-02-LS-001",  # Cross-test mismatch
            test_id="INVALID-TEST-ID-FORMAT",
            section_id=ans.section_id,
            target_value="test",
            acceptable_alternates=[],
            case_sensitive=False,
            source_key_ref="key",
            answer_provenance_status="authoritative_source",
            quality_profile=ans.quality_profile,
            _provenance=ans.provenance,
        )


# ==============================================================================
# TEST 10: Stale Source Detection
# ==============================================================================
def test_stale_source_detection(temp_db, synthetic_data):
    """Verifies that changing a source file's SHA-256 digest invalidates normalization checkpoints."""
    conn = temp_db
    src = synthetic_data["sources"]["question_doc"]
    upsert_source(conn, src)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        target_file = Path(f.name)

    content = {"entity_id": "TEST-IELTS-VOL99-01-LIS", "data": "original"}
    target_file.write_text(json.dumps(content))
    out_sha = hashlib.sha256(target_file.read_bytes()).hexdigest()

    cp_data = {
        "entity_id": "TEST-IELTS-VOL99-01-LIS",
        "entity_type": "listening_test",
        "source_file_id": src["file_id"],
        "source_legacy_id": src["legacy_id"],
        "normalizer_version": "0.3.0-c",
        "schema_version": SCHEMA_VERSION_LISTENING,
        "config_hash": "default",
        "raw_sha256": src["content_sha256"],
        "canonical_content_sha256": out_sha,
        "output_path": str(target_file),
        "output_sha256": out_sha,
        "lifecycle_status": "verified",
        "status": "COMPLETED",
    }
    upsert_normalization_checkpoint(conn, cp_data)

    # Valid with original raw_sha
    assert is_normalization_checkpoint_valid(
        conn=conn,
        entity_id="TEST-IELTS-VOL99-01-LIS",
        normalizer_version="0.3.0-c",
        raw_sha256=src["content_sha256"],
        config_hash="default",
        schema_version=SCHEMA_VERSION_LISTENING,
    )

    # Invalid with altered/stale raw_sha
    tampered_sha = "f" * 64
    assert not is_normalization_checkpoint_valid(
        conn=conn,
        entity_id="TEST-IELTS-VOL99-01-LIS",
        normalizer_version="0.3.0-c",
        raw_sha256=tampered_sha,
        config_hash="default",
        schema_version=SCHEMA_VERSION_LISTENING,
    )

    target_file.unlink(missing_ok=True)


# ==============================================================================
# TEST 11: Checkpoint Resume
# ==============================================================================
def test_checkpoint_resume(temp_db, synthetic_data):
    """Verifies that repeated runs with identical sources skip already-normalized entities."""
    conn = temp_db
    src = synthetic_data["sources"]["question_doc"]
    upsert_source(conn, src)

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        target_file = out_dir / "test.json"
        content = {"entity_id": "SEC-VOL99-01-LS01"}
        target_file.write_text(json.dumps(content))
        file_sha = hashlib.sha256(target_file.read_bytes()).hexdigest()

        cp_data = {
            "entity_id": "SEC-VOL99-01-LS01",
            "entity_type": "listening_section",
            "source_file_id": src["file_id"],
            "source_legacy_id": src["legacy_id"],
            "normalizer_version": "0.3.0-c",
            "schema_version": SCHEMA_VERSION_LISTENING,
            "config_hash": "default",
            "raw_sha256": src["content_sha256"],
            "canonical_content_sha256": file_sha,
            "output_path": str(target_file),
            "output_sha256": file_sha,
            "lifecycle_status": "reviewed",
            "status": "COMPLETED",
        }
        upsert_normalization_checkpoint(conn, cp_data)

        # Check validity
        is_valid = is_normalization_checkpoint_valid(
            conn=conn,
            entity_id="SEC-VOL99-01-LS01",
            normalizer_version="0.3.0-c",
            raw_sha256=src["content_sha256"],
            config_hash="default",
            schema_version=SCHEMA_VERSION_LISTENING,
        )
        assert is_valid is True


# ==============================================================================
# TEST 12: Privacy Isolation
# ==============================================================================
def test_privacy_isolation():
    """Verifies that private_copyrighted entities cannot be written to unauthorized public paths."""
    with tempfile.TemporaryDirectory() as td:
        private_root = Path(td) / "private"
        public_root = Path(td) / "public"
        private_root.mkdir()
        public_root.mkdir()

        payload = {
            "entity_id": "TEST-PRIV-01",
            "quality_profile": {"publication_permission": "private_copyrighted"},
        }

        # Writing to unauthorized public directory must fail
        with pytest.raises(PermissionError):
            validate_output_privacy(
                target_path=public_root / "test.json",
                payload=payload,
                authorized_private_roots=[private_root],
            )

        # Writing to authorized private directory must succeed
        valid_path = validate_output_privacy(
            target_path=private_root / "test.json",
            payload=payload,
            authorized_private_roots=[private_root],
        )
        assert valid_path.resolve() == (private_root / "test.json").resolve()


# ==============================================================================
# TEST 13: Missing Audio Asset Handling
# ==============================================================================
def test_missing_audio_asset_handling():
    """Verifies that when audio is missing, asset status is missing and timing is marked missing/unaligned."""
    aligner = AudioAligner()
    asset = aligner.build_audio_asset(
        source_record=None,
        test_id="TEST-IELTS-VOL99-01-LIS",
        section_number=4,
        volume_code="VOL99",
        test_number=1,
        fallback_source_file_id="FILE-a00000000001",
        publication_permission="public_synthetic",
    )

    assert asset.audio_verification_status == "missing"
    assert asset.duration_ms is None

    # Align dummy segment against missing asset
    prov = ProvenanceEnvelope(
        source_file_id="FILE-a00000000002",
        source_legacy_id="SRC-9902",
        relative_path="data/synthetic/VOL99/Transcript_1.docx",
        source_sha256="b" * 64,
        processing_unit="transcript",
        unit_identifier="transcript_docx",
        raw_block_locator="para_index:0",
        extractor_adapter="docx",
        extractor_version="0.1.0",
        normalizer_version="0.3.0-c",
    )
    qp = QualityProfile(
        lifecycle_status="extracted",
        extraction_quality="complete_clean",
        source_fidelity="authoritative_official",
        answer_verification="unverified",
        explanation_verification="missing_explanation",
        publication_permission="public_synthetic",
        validation_flags=[],
    )
    seg = TranscriptSegment(
        segment_id="TRANS-VOL99-01-LS04-SEG001",
        section_id="SEC-VOL99-01-LS04",
        test_id="TEST-IELTS-VOL99-01-LIS",
        sequence_index=0,
        speaker_id="Speaker 3",
        transcript_text="Dummy lecture line.",
        start_ms=10000,
        end_ms=20000,
        timing_source="source_timestamp",
        timing_verification_status="unverified",
        quality_profile=qp,
        _provenance=prov,
    )

    aligned, audit = aligner.align_section_audio(4, [seg], asset)
    assert audit["missing_audio_count"] == 1
    assert aligned[0].timing_verification_status == "missing"
