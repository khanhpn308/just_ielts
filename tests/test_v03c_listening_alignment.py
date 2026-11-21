"""Fully synthetic regression tests for IELTS Listening Normalization & Audio Alignment (V0.3-C).

Tests run entirely against synthetic fixtures and SQLite memory/temp databases without
requiring private raw files or network access.
"""

from __future__ import annotations

import copy
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
    compute_listening_entity_dependency_hash,
)
from harness.normalizers.listening_question import (
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

    speakers = [t.speaker_id for t in sec1_turns]
    assert "Speaker 1" in speakers
    assert "Speaker 2" in speakers

    turn1_text = sec1_turns[0].text
    assert "Welcome to the synthetic festival" in turn1_text


# ==============================================================================
# TEST 3: Valid Timestamps Alignment & Zero Fabricated Intervals
# ==============================================================================
def test_valid_timestamps(synthetic_data):
    """Verifies that valid timestamps are marked verified, unavailable end_ms is preserved as null,
    and single timestamps do NOT claim AUDIO_INTERVAL_VERIFIED."""
    norm = TranscriptNormalizer()
    aligner = AudioAligner()
    src_t = synthetic_data["sources"]["transcript_doc"]
    paras = synthetic_data["transcript_paragraphs"]

    sections = norm.segment_transcript(paragraphs=paras, source_record=src_t)
    sec1_segs = sections[1]["segments"]

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
    assert audit["verified_timestamps_count"] > 0
    # Zero fabricated intervals
    assert audit["verified_intervals_count"] == 0
    assert audit["impossible_bounds_count"] == 0
    assert audit["out_of_order_count"] == 0

    for seg in aligned:
        if seg.start_ms is not None:
            assert seg.timing_verification_status == "verified"
            assert 0 <= seg.start_ms <= audio.duration_ms
            # Preserved unavailable end_ms as null
            assert seg.end_ms is None
            # Must NOT claim AUDIO_INTERVAL_VERIFIED because end_ms is null
            assert "AUDIO_INTERVAL_VERIFIED" not in seg.quality_profile.validation_flags
            assert "AUDIO_TIMESTAMP_VERIFIED" in seg.quality_profile.validation_flags


# ==============================================================================
# TEST 4: Never Generate 30-Second Endpoint (Negative Regression)
# ==============================================================================
def test_no_fabricated_30s_endpoint():
    """Negative regression test: Trailing segment with start_ms must never receive a 30s endpoint."""
    aligner = AudioAligner()
    prov = ProvenanceEnvelope(
        source_file_id="FILE-a00000000003",
        source_legacy_id="SRC-9903",
        relative_path="audio.mp3",
        source_sha256="c" * 64,
        processing_unit="audio",
        unit_identifier="header",
        raw_block_locator="hdr",
        extractor_adapter="test",
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
        file_path="audio.mp3",
        source_file_id="FILE-a00000000003",
        source_sha256="c" * 64,
        format="mp3",
        duration_ms=600000,
        audio_verification_status="verified",
        quality_profile=qp,
        _provenance=prov,
    )
    trailing_seg = TranscriptSegment(
        segment_id="TRANS-VOL99-01-LS01-SEG999",
        section_id="SEC-VOL99-01-LS01",
        test_id="TEST-IELTS-VOL99-01-LIS",
        sequence_index=10,
        speaker_id="Speaker 1",
        transcript_text="Trailing segment line.",
        start_ms=450000,
        end_ms=None,
        timing_source="source_timestamp",
        timing_verification_status="unverified",
        quality_profile=qp,
        _provenance=prov,
    )

    aligned, audit = aligner.align_section_audio(1, [trailing_seg], audio)
    res_seg = aligned[0]

    assert res_seg.start_ms == 450000
    # Must remain null, NOT min(start + 30000, duration) = 480000
    assert res_seg.end_ms is None
    assert "AUDIO_INTERVAL_VERIFIED" not in res_seg.quality_profile.validation_flags
    assert "AUDIO_TIMESTAMP_VERIFIED" in res_seg.quality_profile.validation_flags


# ==============================================================================
# TEST 5: Derived Bounds Distinction (Negative Regression)
# ==============================================================================
def test_derived_bounds_distinction():
    """Negative regression test: Inferred/derived bounds must never be marked audio-verified."""
    aligner = AudioAligner()
    prov = ProvenanceEnvelope(
        source_file_id="FILE-a00000000003",
        source_legacy_id="SRC-9903",
        relative_path="audio.mp3",
        source_sha256="c" * 64,
        processing_unit="audio",
        unit_identifier="header",
        raw_block_locator="hdr",
        extractor_adapter="test",
        extractor_version="0.1.0",
        normalizer_version="0.3.0-c",
    )
    qp = QualityProfile(
        lifecycle_status="extracted",
        extraction_quality="complete_clean",
        source_fidelity="unverified_community",
        answer_verification="unverified",
        explanation_verification="missing_explanation",
        publication_permission="public_synthetic",
        validation_flags=[],
    )
    audio = AudioAsset(
        audio_id="AUDIO-VOL99-01-SEC01",
        test_id="TEST-IELTS-VOL99-01-LIS",
        section_number=1,
        file_path="audio.mp3",
        source_file_id="FILE-a00000000003",
        source_sha256="c" * 64,
        format="mp3",
        duration_ms=600000,
        audio_verification_status="verified",
        quality_profile=qp,
        _provenance=prov,
    )
    derived_seg = TranscriptSegment(
        segment_id="TRANS-VOL99-01-LS01-SEG998",
        section_id="SEC-VOL99-01-LS01",
        test_id="TEST-IELTS-VOL99-01-LIS",
        sequence_index=0,
        speaker_id="Speaker 1",
        transcript_text="Derived bound line.",
        start_ms=10000,
        end_ms=25000,
        timing_source="derived_bound",
        timing_verification_status="unverified",
        quality_profile=qp,
        _provenance=prov,
    )

    aligned, audit = aligner.align_section_audio(1, [derived_seg], audio)
    res = aligned[0]

    assert res.timing_verification_status == "inferred"
    assert "AUDIO_INTERVAL_VERIFIED" not in res.quality_profile.validation_flags
    assert "AUDIO_TIMING_INFERRED" in res.quality_profile.validation_flags
    assert audit["inferred_count"] == 1
    assert audit["verified_count"] == 0


# ==============================================================================
# TEST 6: Impossible Timestamps & Timebase Mismatch
# ==============================================================================
def test_impossible_timestamps(synthetic_data):
    """Verifies that timestamps exceeding audio duration or with start >= end are flagged impossible_bounds."""
    norm = TranscriptNormalizer()
    aligner = AudioAligner()
    src_t = synthetic_data["sources"]["transcript_doc"]
    impos_paras = synthetic_data["anomaly_paragraphs"]["impossible_timestamps"]

    secs = norm.segment_transcript(paragraphs=impos_paras, source_record=src_t)
    segs = secs[1]["segments"]

    short_prov = ProvenanceEnvelope(
        source_file_id="FILE-a00000000003",
        source_legacy_id="SRC-9903",
        relative_path="audio.mp3",
        source_sha256="c" * 64,
        processing_unit="audio",
        unit_identifier="hdr",
        raw_block_locator="hdr",
        extractor_adapter="test",
        extractor_version="0.1.0",
        normalizer_version="0.3.0-c",
    )
    short_qp = QualityProfile(
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
        file_path="audio.mp3",
        source_file_id="FILE-a00000000003",
        source_sha256="c" * 64,
        format="mp3",
        duration_ms=300000,  # 5 minutes
        duration_sec=300.0,
        audio_verification_status="verified",
        quality_profile=short_qp,
        _provenance=short_prov,
    )

    aligned, audit = aligner.align_section_audio(1, segs, short_audio)

    assert audit["impossible_bounds_count"] == len(segs)
    assert audit["verified_count"] == 0
    for seg in aligned:
        assert seg.timing_verification_status == "impossible_bounds"


# ==============================================================================
# TEST 7: Out-of-Order Intervals
# ==============================================================================
def test_out_of_order_intervals(synthetic_data):
    """Verifies that non-chronological timestamps are flagged as out_of_order."""
    norm = TranscriptNormalizer()
    aligner = AudioAligner()
    src_t = synthetic_data["sources"]["transcript_doc"]
    ooo_paras = synthetic_data["anomaly_paragraphs"]["out_of_order_timestamps"]

    secs = norm.segment_transcript(paragraphs=ooo_paras, source_record=src_t)
    segs = secs[1]["segments"]

    prov = ProvenanceEnvelope(
        source_file_id="FILE-a00000000003",
        source_legacy_id="SRC-9903",
        relative_path="audio.mp3",
        source_sha256="c" * 64,
        processing_unit="audio",
        unit_identifier="hdr",
        raw_block_locator="hdr",
        extractor_adapter="test",
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
        file_path="audio.mp3",
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
    assert aligned[1].timing_verification_status == "out_of_order"


# ==============================================================================
# TEST 8: Missing Timestamp Handling
# ==============================================================================
def test_missing_timestamp_handling(synthetic_data):
    """Verifies that dialogue lines without timestamps are preserved as unaligned without fabrication."""
    norm = TranscriptNormalizer()
    aligner = AudioAligner()
    src_t = synthetic_data["sources"]["transcript_doc"]
    missing_paras = synthetic_data["anomaly_paragraphs"]["missing_timestamps"]

    secs = norm.segment_transcript(paragraphs=missing_paras, source_record=src_t)
    segs = secs[1]["segments"]

    prov = ProvenanceEnvelope(
        source_file_id="FILE-a00000000003",
        source_legacy_id="SRC-9903",
        relative_path="audio.mp3",
        source_sha256="c" * 64,
        processing_unit="audio",
        unit_identifier="hdr",
        raw_block_locator="hdr",
        extractor_adapter="test",
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
        file_path="audio.mp3",
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
# TEST 9: Question-to-Section Mapping
# ==============================================================================
def test_question_to_section_mapping(synthetic_data):
    """Verifies that all 40 questions are properly partitioned into 4 distinct sections."""
    q_norm = ListeningQuestionNormalizer()
    src_doc = synthetic_data["sources"]["question_doc"]
    src_t = synthetic_data["sources"]["transcript_doc"]

    questions, answers, evidence = q_norm.normalize_listening_test_items(
        doc_source_record=src_doc,
        transcript_source_record=src_t,
        transcript_segments_by_sec={s: [] for s in range(1, 5)},
        items_def=synthetic_data["questions"],
        volume_code="VOL99",
        test_number=1,
        publication_permission="public_synthetic",
    )

    assert len(questions) == 40
    assert len(answers) == 40
    assert len(evidence) == 40

    sec_q_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for q in questions:
        sec_num = int(q.section_id[-2:])
        sec_q_counts[sec_num] += 1

    assert sec_q_counts[1] == 10
    assert sec_q_counts[2] == 10
    assert sec_q_counts[3] == 10
    assert sec_q_counts[4] == 10


# ==============================================================================
# TEST 10: Answer Provenance & Unverified Answer Flag
# ==============================================================================
def test_answer_provenance(synthetic_data):
    """Verifies authoritative source key references and flagging of unverified answers."""
    q_norm = ListeningQuestionNormalizer()
    src_doc = synthetic_data["sources"]["question_doc"]
    src_t = synthetic_data["sources"]["transcript_doc"]

    items = copy.deepcopy(synthetic_data["questions"])
    # Set one answer as unverified
    items[0]["source_verified"] = False

    questions, answers, evidence = q_norm.normalize_listening_test_items(
        doc_source_record=src_doc,
        transcript_source_record=src_t,
        transcript_segments_by_sec={s: [] for s in range(1, 5)},
        items_def=items,
        volume_code="VOL99",
        test_number=1,
        publication_permission="public_synthetic",
    )

    # First answer must be flagged unverified
    assert answers[0].answer_provenance_status == "unverified"
    assert "ANSWER_KEY_UNVERIFIED" in answers[0].quality_profile.validation_flags

    # Other answers are authoritative
    for ans in answers[1:]:
        assert ans.answer_provenance_status == "authoritative_source"
        assert ans.target_value is not None and len(ans.target_value) > 0
        assert ans.provenance.source_file_id == src_doc["file_id"]
        assert ans.provenance.source_sha256 == src_doc["content_sha256"]


# ==============================================================================
# TEST 11: Cross-Test Mismatch
# ==============================================================================
def test_cross_test_mismatch(synthetic_data):
    """Verifies that an answer cannot be linked to a question from a different test ID."""
    q_norm = ListeningQuestionNormalizer()
    src_doc = synthetic_data["sources"]["question_doc"]
    src_t = synthetic_data["sources"]["transcript_doc"]

    _, answers, _ = q_norm.normalize_listening_test_items(
        doc_source_record=src_doc,
        transcript_source_record=src_t,
        transcript_segments_by_sec={s: [] for s in range(1, 5)},
        items_def=synthetic_data["questions"],
        volume_code="VOL99",
        test_number=1,
        publication_permission="public_synthetic",
    )

    ans = answers[0]

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
# TEST 12: Evidence Linkage — No Substring Matching on target_value (Negative Regression)
# ==============================================================================
def test_no_substring_matching_on_target_val(synthetic_data):
    """Negative regression test: Substring match of target_value without verbatim quote must NOT ground evidence."""
    q_norm = ListeningQuestionNormalizer()
    t_norm = TranscriptNormalizer()
    src_doc = synthetic_data["sources"]["question_doc"]
    src_t = synthetic_data["sources"]["transcript_doc"]
    paras = synthetic_data["transcript_paragraphs"]

    sections = t_norm.segment_transcript(paras, src_t)
    sec_segs = {s: sections[s]["segments"] for s in range(1, 5)}

    # Item where target_val 'library' is in segment text, but quote does NOT match segment text
    bogus_item = {
        "q_num": 1,
        "sec_num": 1,
        "page_num": 1,
        "q_type": "table-completion",
        "prompt": "Test prompt",
        "raw_ocr_entry": "library",
        "target_val": "library",
        "quote": "This fabricated quote does not exist in any transcript segment.",
        "source_verified": True,
    }

    _, _, evidence = q_norm.normalize_listening_test_items(
        doc_source_record=src_doc,
        transcript_source_record=src_t,
        transcript_segments_by_sec=sec_segs,
        items_def=[bogus_item],
        volume_code="VOL99",
        test_number=1,
        publication_permission="public_synthetic",
    )

    ev = evidence[0]
    # Grounding must be unresolved despite 'library' appearing in the transcript!
    assert ev.grounding_status == "unresolved"
    assert ev.verbatim_quote is None
    assert ev.segment_id is None
    assert "EVIDENCE_TEXT_GROUNDED" not in ev.quality_profile.validation_flags
    assert "EVIDENCE_UNRESOLVED" in ev.quality_profile.validation_flags


# ==============================================================================
# TEST 13: Evidence Linkage — No MCQ Option Letters Matching (Negative Regression)
# ==============================================================================
def test_no_mcq_letter_matching(synthetic_data):
    """Negative regression test: Answer letter A/B/C must never be used as text search evidence."""
    q_norm = ListeningQuestionNormalizer()
    t_norm = TranscriptNormalizer()
    src_doc = synthetic_data["sources"]["question_doc"]
    src_t = synthetic_data["sources"]["transcript_doc"]
    paras = synthetic_data["transcript_paragraphs"]

    sections = t_norm.segment_transcript(paras, src_t)
    sec_segs = {s: sections[s]["segments"] for s in range(1, 5)}

    mcq_item = {
        "q_num": 11,
        "sec_num": 2,
        "page_num": 2,
        "q_type": "multiple-choice-single",
        "prompt": "MCQ Question",
        "options": {"A": "First option", "B": "Second option", "C": "Third option"},
        "raw_ocr_entry": "A",
        "target_val": "A",
        "quote": None,  # No verbatim quote
        "source_verified": True,
    }

    _, _, evidence = q_norm.normalize_listening_test_items(
        doc_source_record=src_doc,
        transcript_source_record=src_t,
        transcript_segments_by_sec=sec_segs,
        items_def=[mcq_item],
        volume_code="VOL99",
        test_number=1,
        publication_permission="public_synthetic",
    )

    ev = evidence[0]
    # Must remain unresolved even though English text contains thousands of 'a' letters!
    assert ev.grounding_status == "unresolved"
    assert ev.segment_id is None
    assert "EVIDENCE_TEXT_GROUNDED" not in ev.quality_profile.validation_flags


# ==============================================================================
# TEST 14: Evidence Linkage — Wrong Section Rejection (Negative Regression)
# ==============================================================================
def test_wrong_section_evidence_rejection(synthetic_data):
    """Negative regression test: Quote present in Section 2 cannot ground a question in Section 1."""
    q_norm = ListeningQuestionNormalizer()
    t_norm = TranscriptNormalizer()
    src_doc = synthetic_data["sources"]["question_doc"]
    src_t = synthetic_data["sources"]["transcript_doc"]
    paras = synthetic_data["transcript_paragraphs"]

    sections = t_norm.segment_transcript(paras, src_t)
    sec_segs = {s: sections[s]["segments"] for s in range(1, 5)}

    wrong_sec_item = {
        "q_num": 1,
        "sec_num": 1,  # Question is in Section 1
        "page_num": 1,
        "q_type": "table-completion",
        "prompt": "Test prompt",
        "raw_ocr_entry": "hiking boots",
        "target_val": "hiking boots",
        # Quote is from Section 2!
        "quote": "Please ensure you carry extra water and wear sturdy hiking boots.",
        "source_verified": True,
    }

    _, _, evidence = q_norm.normalize_listening_test_items(
        doc_source_record=src_doc,
        transcript_source_record=src_t,
        transcript_segments_by_sec=sec_segs,
        items_def=[wrong_sec_item],
        volume_code="VOL99",
        test_number=1,
        publication_permission="public_synthetic",
    )

    ev = evidence[0]
    assert ev.grounding_status == "unresolved"
    assert ev.segment_id is None
    assert "EVIDENCE_TEXT_GROUNDED" not in ev.quality_profile.validation_flags


# ==============================================================================
# TEST 15: Evidence Provenance Recorded from Transcript Source
# ==============================================================================
def test_evidence_provenance_transcript_source(synthetic_data):
    """Verifies that evidence provenance is linked to the transcript source document, NOT the question doc."""
    q_norm = ListeningQuestionNormalizer()
    t_norm = TranscriptNormalizer()
    src_doc = synthetic_data["sources"]["question_doc"]
    src_t = synthetic_data["sources"]["transcript_doc"]
    paras = synthetic_data["transcript_paragraphs"]

    sections = t_norm.segment_transcript(paras, src_t)
    sec_segs = {s: sections[s]["segments"] for s in range(1, 5)}

    valid_item = {
        "q_num": 1,
        "sec_num": 1,
        "page_num": 1,
        "q_type": "table-completion",
        "prompt": "Opening ceremony location",
        "raw_ocr_entry": "library",
        "target_val": "library",
        "quote": "Certainly, it takes place at the community library.",
        "source_verified": True,
    }

    _, _, evidence = q_norm.normalize_listening_test_items(
        doc_source_record=src_doc,
        transcript_source_record=src_t,
        transcript_segments_by_sec=sec_segs,
        items_def=[valid_item],
        volume_code="VOL99",
        test_number=1,
        publication_permission="public_synthetic",
    )

    ev = evidence[0]
    assert ev.grounding_status == "grounded"
    assert ev.provenance.source_file_id == src_t["file_id"]
    assert ev.provenance.source_sha256 == src_t["content_sha256"]
    assert ev.provenance.source_legacy_id == src_t["legacy_id"]
    assert ev.provenance.relative_path == src_t["relative_path"]


# ==============================================================================
# TEST 16: Source Data Isolation — No Copyrighted Data in Public Code
# ==============================================================================
def test_no_copyrighted_data_in_public_code():
    """Verifies that public python normalizer code contains zero copyrighted IELTS items."""
    code_path = REPO_ROOT / "harness" / "normalizers" / "listening_question.py"
    text = code_path.read_text(encoding="utf-8")

    assert "RAW_LISTENING_QUESTIONS_DEF" not in text
    assert "Beechen" not in text
    assert "Bislama" not in text
    assert "La Vega" not in text
    assert "theather" not in text


# ==============================================================================
# TEST 17: Uncertain OCR Preservation
# ==============================================================================
def test_ocr_preservation_uncertain_results(synthetic_data):
    """Verifies that noisy OCR entries are preserved in locators without silent corrections."""
    q_norm = ListeningQuestionNormalizer()
    src_doc = synthetic_data["sources"]["question_doc"]
    src_t = synthetic_data["sources"]["transcript_doc"]

    item = {
        "q_num": 9,
        "sec_num": 1,
        "page_num": 1,
        "key_page": 22,
        "q_type": "note-completion",
        "prompt": "Web address",
        "raw_ocr_entry": "g events",  # Noisy OCR: 9 -> g
        "target_val": "events",
        "quote": "you can look at w w w dot events dot com",
        "source_verified": True,
    }

    _, answers, _ = q_norm.normalize_listening_test_items(
        doc_source_record=src_doc,
        transcript_source_record=src_t,
        transcript_segments_by_sec={1: []},
        items_def=[item],
        volume_code="VOL99",
        test_number=1,
        publication_permission="public_synthetic",
    )

    ans = answers[0]
    assert ans.target_value == "events"
    assert "key_entry:g events" in ans.provenance.raw_block_locator


# ==============================================================================
# TEST 18: Privacy Isolation
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

        with pytest.raises(PermissionError):
            validate_output_privacy(
                target_path=public_root / "test.json",
                payload=payload,
                authorized_private_roots=[private_root],
            )

        valid_path = validate_output_privacy(
            target_path=private_root / "test.json",
            payload=payload,
            authorized_private_roots=[private_root],
        )
        assert valid_path.resolve() == (private_root / "test.json").resolve()


# ==============================================================================
# TEST 19: Missing Audio Asset Handling
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


# ==============================================================================
# TEST 20: Dependency-Aware Checkpoints Invalidation
# ==============================================================================
def test_dependency_aware_checkpoints(temp_db, synthetic_data):
    """Verifies the 6 dependency tracking scenarios:
    1. Initial normalization
    2. Identical rerun
    3. Transcript-only change (invalidates transcript & evidence; skips audio & questions)
    4. Audio-only change (invalidates audio asset; skips questions, answers, transcript)
    5. Answer-key / question doc change (invalidates questions & answers; skips audio & transcript)
    6. Interrupted processing and resume
    """
    conn = temp_db
    src_doc = synthetic_data["sources"]["question_doc"]
    src_t = synthetic_data["sources"]["transcript_doc"]
    src_a = synthetic_data["sources"]["audio_track_1"]
    upsert_source(conn, src_doc)
    upsert_source(conn, src_t)
    upsert_source(conn, src_a)

    audio_shas = {1: src_a["content_sha256"], 2: None, 3: None, 4: None}
    doc_sha = src_doc["content_sha256"]
    t_sha = src_t["content_sha256"]

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)

        # Entity 1: Question
        q_file = out_dir / "listening_question" / "Q-001.json"
        q_file.parent.mkdir(parents=True, exist_ok=True)
        q_file.write_text(json.dumps({"q": 1}))
        q_sha = hashlib.sha256(q_file.read_bytes()).hexdigest()
        q_dep = compute_listening_entity_dependency_hash("listening_question", doc_sha, t_sha, audio_shas, 1)
        upsert_normalization_checkpoint(conn, {
            "entity_id": "Q-001", "entity_type": "listening_question",
            "source_file_id": src_doc["file_id"], "source_legacy_id": src_doc["legacy_id"],
            "normalizer_version": "0.3.0-c", "schema_version": SCHEMA_VERSION_LISTENING,
            "config_hash": "default", "raw_sha256": q_dep, "canonical_content_sha256": q_sha,
            "output_path": str(q_file), "output_sha256": q_sha,
            "lifecycle_status": "reviewed", "status": "COMPLETED",
        })

        # Entity 2: Audio Asset
        a_file = out_dir / "audio_asset" / "AUDIO-01.json"
        a_file.parent.mkdir(parents=True, exist_ok=True)
        a_file.write_text(json.dumps({"a": 1}))
        a_sha = hashlib.sha256(a_file.read_bytes()).hexdigest()
        a_dep = compute_listening_entity_dependency_hash("audio_asset", doc_sha, t_sha, audio_shas, 1)
        upsert_normalization_checkpoint(conn, {
            "entity_id": "AUDIO-01", "entity_type": "audio_asset",
            "source_file_id": src_a["file_id"], "source_legacy_id": src_a["legacy_id"],
            "normalizer_version": "0.3.0-c", "schema_version": SCHEMA_VERSION_LISTENING,
            "config_hash": "default", "raw_sha256": a_dep, "canonical_content_sha256": a_sha,
            "output_path": str(a_file), "output_sha256": a_sha,
            "lifecycle_status": "verified", "status": "COMPLETED",
        })

        # Entity 3: Transcript Segment
        seg_file = out_dir / "transcript_segment" / "SEG-001.json"
        seg_file.parent.mkdir(parents=True, exist_ok=True)
        seg_file.write_text(json.dumps({"s": 1}))
        seg_sha = hashlib.sha256(seg_file.read_bytes()).hexdigest()
        seg_dep = compute_listening_entity_dependency_hash("transcript_segment", doc_sha, t_sha, audio_shas, 1)
        upsert_normalization_checkpoint(conn, {
            "entity_id": "SEG-001", "entity_type": "transcript_segment",
            "source_file_id": src_t["file_id"], "source_legacy_id": src_t["legacy_id"],
            "normalizer_version": "0.3.0-c", "schema_version": SCHEMA_VERSION_LISTENING,
            "config_hash": "default", "raw_sha256": seg_dep, "canonical_content_sha256": seg_sha,
            "output_path": str(seg_file), "output_sha256": seg_sha,
            "lifecycle_status": "extracted", "status": "COMPLETED",
        })

        # Entity 4: Evidence
        ev_file = out_dir / "listening_evidence" / "EVID-01.json"
        ev_file.parent.mkdir(parents=True, exist_ok=True)
        ev_file.write_text(json.dumps({"ev": 1}))
        ev_sha = hashlib.sha256(ev_file.read_bytes()).hexdigest()
        ev_dep = compute_listening_entity_dependency_hash("listening_evidence", doc_sha, t_sha, audio_shas, 1)
        upsert_normalization_checkpoint(conn, {
            "entity_id": "EVID-01", "entity_type": "listening_evidence",
            "source_file_id": src_t["file_id"], "source_legacy_id": src_t["legacy_id"],
            "normalizer_version": "0.3.0-c", "schema_version": SCHEMA_VERSION_LISTENING,
            "config_hash": "default", "raw_sha256": ev_dep, "canonical_content_sha256": ev_sha,
            "output_path": str(ev_file), "output_sha256": ev_sha,
            "lifecycle_status": "reviewed", "status": "COMPLETED",
        })

        # Scenario 1 & 2: Identical rerun -> All checkpoints valid
        assert is_normalization_checkpoint_valid(conn, "Q-001", "0.3.0-c", q_dep, "default", SCHEMA_VERSION_LISTENING)
        assert is_normalization_checkpoint_valid(conn, "AUDIO-01", "0.3.0-c", a_dep, "default", SCHEMA_VERSION_LISTENING)
        assert is_normalization_checkpoint_valid(conn, "SEG-001", "0.3.0-c", seg_dep, "default", SCHEMA_VERSION_LISTENING)
        assert is_normalization_checkpoint_valid(conn, "EVID-01", "0.3.0-c", ev_dep, "default", SCHEMA_VERSION_LISTENING)

        # Scenario 3: Transcript-only change -> Invalidates segment & evidence; skips audio & question
        new_t_sha = "9" * 64
        new_seg_dep = compute_listening_entity_dependency_hash("transcript_segment", doc_sha, new_t_sha, audio_shas, 1)
        new_ev_dep = compute_listening_entity_dependency_hash("listening_evidence", doc_sha, new_t_sha, audio_shas, 1)
        assert not is_normalization_checkpoint_valid(conn, "SEG-001", "0.3.0-c", new_seg_dep, "default", SCHEMA_VERSION_LISTENING)
        assert not is_normalization_checkpoint_valid(conn, "EVID-01", "0.3.0-c", new_ev_dep, "default", SCHEMA_VERSION_LISTENING)
        # Unrelated entities: Question and Audio are STILL VALID
        assert is_normalization_checkpoint_valid(conn, "Q-001", "0.3.0-c", q_dep, "default", SCHEMA_VERSION_LISTENING)
        assert is_normalization_checkpoint_valid(conn, "AUDIO-01", "0.3.0-c", a_dep, "default", SCHEMA_VERSION_LISTENING)

        # Scenario 4: Audio-only change -> Invalidates audio asset, timing-dependent segments & evidence; skips question, answer, other sections
        new_audio_shas = {1: "8" * 64, 2: None, 3: None, 4: None}
        new_a_dep = compute_listening_entity_dependency_hash("audio_asset", doc_sha, t_sha, new_audio_shas, 1)
        new_seg_dep = compute_listening_entity_dependency_hash("transcript_segment", doc_sha, t_sha, new_audio_shas, 1, timing_depends_on_audio=True)
        new_ev_dep = compute_listening_entity_dependency_hash("listening_evidence", doc_sha, t_sha, new_audio_shas, 1, timing_depends_on_audio=True)
        assert not is_normalization_checkpoint_valid(conn, "AUDIO-01", "0.3.0-c", new_a_dep, "default", SCHEMA_VERSION_LISTENING)
        assert not is_normalization_checkpoint_valid(conn, "SEG-001", "0.3.0-c", new_seg_dep, "default", SCHEMA_VERSION_LISTENING)
        assert not is_normalization_checkpoint_valid(conn, "EVID-01", "0.3.0-c", new_ev_dep, "default", SCHEMA_VERSION_LISTENING)
        # Unrelated entities: Question is STILL VALID
        assert is_normalization_checkpoint_valid(conn, "Q-001", "0.3.0-c", q_dep, "default", SCHEMA_VERSION_LISTENING)
        # Unrelated section segment (Section 2) is STILL VALID
        seg2_old = compute_listening_entity_dependency_hash("transcript_segment", doc_sha, t_sha, audio_shas, 2, timing_depends_on_audio=True)
        seg2_new = compute_listening_entity_dependency_hash("transcript_segment", doc_sha, t_sha, new_audio_shas, 2, timing_depends_on_audio=True)
        assert seg2_old == seg2_new
        assert is_normalization_checkpoint_valid(conn, "SEG-001", "0.3.0-c", seg_dep, "default", SCHEMA_VERSION_LISTENING)

        # Scenario 5: Question doc / Answer key change -> Invalidates question & evidence; skips audio & segment
        new_doc_sha = "7" * 64
        new_q_dep = compute_listening_entity_dependency_hash("listening_question", new_doc_sha, t_sha, audio_shas, 1)
        assert not is_normalization_checkpoint_valid(conn, "Q-001", "0.3.0-c", new_q_dep, "default", SCHEMA_VERSION_LISTENING)
        # Unrelated entities: Audio and Segment are STILL VALID
        assert is_normalization_checkpoint_valid(conn, "AUDIO-01", "0.3.0-c", a_dep, "default", SCHEMA_VERSION_LISTENING)
        assert is_normalization_checkpoint_valid(conn, "SEG-001", "0.3.0-c", seg_dep, "default", SCHEMA_VERSION_LISTENING)

        # Scenario 6: Interrupted processing and resume
        # An entity not yet written or interrupted
        assert not is_normalization_checkpoint_valid(conn, "UNWRITTEN-01", "0.3.0-c", "any", "default", SCHEMA_VERSION_LISTENING)


# ==============================================================================
# TEST 21: Fail-Closed Source Verification (Regression Test)
# ==============================================================================
def test_source_verification_fail_closed(synthetic_data):
    """Verifies fail-closed source verification:
    - source_verified missing -> unverified
    - fabricated source_verified=True without valid provenance -> not verified
    - valid source-linked review -> accepted
    - mismatched source hash -> rejected/unverified
    """
    q_norm = ListeningQuestionNormalizer()
    src_doc = synthetic_data["sources"]["question_doc"]
    src_t = synthetic_data["sources"]["transcript_doc"]

    valid_review = {
        "reviewer_id": "REV-TEST-01",
        "reviewed_at": "2026-11-21T00:00:00+00:00",
        "review_decision": "accepted",
        "verification_method": "manual_source_check",
    }

    # Case 1: source_verified missing -> unverified
    item_missing_verified = {
        "q_num": 1,
        "sec_num": 1,
        "page_num": 1,
        "q_type": "table-completion",
        "prompt": "Test prompt",
        "raw_ocr_entry": "library",
        "target_val": "library",
        "source_key_ref": "SRC-9901:page_1:key_1",
        "source_sha256": src_doc["content_sha256"],
        "review_evidence": valid_review,
        # 'source_verified' is omitted!
    }

    # Case 2: fabricated source_verified=True without valid provenance -> not verified
    item_fabricated = {
        "q_num": 2,
        "sec_num": 1,
        "page_num": 1,
        "q_type": "table-completion",
        "prompt": "Test prompt 2",
        "raw_ocr_entry": "4.30",
        "target_val": "4.30",
        "source_verified": True,  # Fabricated! Missing review evidence & source hash
    }

    # Case 3: valid source-linked review -> accepted
    item_valid = {
        "q_num": 3,
        "sec_num": 1,
        "page_num": 1,
        "q_type": "table-completion",
        "prompt": "Test prompt 3",
        "raw_ocr_entry": "station",
        "target_val": "station",
        "source_key_ref": "SRC-9901:page_1:key_3",
        "source_sha256": src_doc["content_sha256"],
        "source_file_id": src_doc["file_id"],
        "source_verified": True,
        "review_evidence": valid_review,
    }

    # Case 4: mismatched source hash -> rejected/unverified
    item_mismatched_hash = {
        "q_num": 4,
        "sec_num": 1,
        "page_num": 1,
        "q_type": "table-completion",
        "prompt": "Test prompt 4",
        "raw_ocr_entry": "cooking",
        "target_val": "cooking",
        "source_key_ref": "SRC-9901:page_1:key_4",
        "source_sha256": "deadbeef" * 8,  # Mismatched hash!
        "source_file_id": src_doc["file_id"],
        "source_verified": True,
        "review_evidence": valid_review,
    }

    _, answers, _ = q_norm.normalize_listening_test_items(
        doc_source_record=src_doc,
        transcript_source_record=src_t,
        transcript_segments_by_sec={1: []},
        items_def=[item_missing_verified, item_fabricated, item_valid, item_mismatched_hash],
        volume_code="VOL99",
        test_number=1,
        publication_permission="public_synthetic",
    )

    ans_missing, ans_fab, ans_ok, ans_mismatch = answers

    # Case 1: unverified
    assert ans_missing.answer_provenance_status == "unverified"
    assert "ANSWER_KEY_UNVERIFIED" in ans_missing.quality_profile.validation_flags
    assert ans_missing.quality_profile.lifecycle_status == "review_required"
    assert ans_missing.quality_profile.answer_verification == "unverified"

    # Case 2: not verified
    assert ans_fab.answer_provenance_status == "unverified"
    assert "ANSWER_KEY_UNVERIFIED" in ans_fab.quality_profile.validation_flags
    assert "MISSING_VERIFICATION_EVIDENCE" in ans_fab.quality_profile.validation_flags
    assert ans_fab.quality_profile.lifecycle_status == "review_required"

    # Case 3: accepted
    assert ans_ok.answer_provenance_status == "authoritative_source"
    assert "ANSWER_KEY_PROVENANCE_VERIFIED" in ans_ok.quality_profile.validation_flags
    assert ans_ok.quality_profile.lifecycle_status == "verified"
    assert ans_ok.quality_profile.answer_verification == "authoritative_key"

    # Case 4: rejected/unverified
    assert ans_mismatch.answer_provenance_status == "unverified"
    assert "ANSWER_KEY_UNVERIFIED" in ans_mismatch.quality_profile.validation_flags
    assert "SOURCE_HASH_MISMATCH" in ans_mismatch.quality_profile.validation_flags
    assert ans_mismatch.quality_profile.lifecycle_status == "review_required"


# ==============================================================================
# TEST 22: Orchestrator-Level Audio Dependency Invalidation
# ==============================================================================
def test_orchestrator_audio_dependency_invalidation(synthetic_data):
    """Orchestrator-level regression test:
    - Initial run
    - Identical rerun -> skipped
    - Modify Section 1 audio only
    - Rerun without force
    - Section 1 timing-dependent records updated
    - Other sections unchanged
    - Question and answer records unchanged
    - Checkpoint hashes consistent with outputs
    """
    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        db_path = tmp_path / "test_harness.db"
        out_dir = tmp_path / "normalized"
        rep_dir = tmp_path / "reports"

        init_db(db_path)
        conn = get_db_connection(db_path)

        src_doc = copy.deepcopy(synthetic_data["sources"]["question_doc"])
        src_t = copy.deepcopy(synthetic_data["sources"]["transcript_doc"])
        src_a1 = copy.deepcopy(synthetic_data["sources"]["audio_track_1"])
        src_a2 = copy.deepcopy(synthetic_data["sources"]["audio_track_1"])
        src_a2["file_id"] = "FILE-a00000000004"
        src_a2["legacy_id"] = "SRC-9904"
        src_a2["relative_path"] = "data/synthetic/VOL99/AudioTrack_02.mp3"
        src_a2["filename"] = "AudioTrack_02.mp3"
        src_a2["content_sha256"] = "dddd4444" * 8
        src_a3 = copy.deepcopy(synthetic_data["sources"]["audio_track_1"])
        src_a3["file_id"] = "FILE-a00000000005"
        src_a3["legacy_id"] = "SRC-9905"
        src_a3["relative_path"] = "data/synthetic/VOL99/AudioTrack_03.mp3"
        src_a3["filename"] = "AudioTrack_03.mp3"
        src_a3["content_sha256"] = "eeee5555" * 8

        upsert_source(conn, src_doc)
        upsert_source(conn, src_t)
        upsert_source(conn, src_a1)
        upsert_source(conn, src_a2)
        upsert_source(conn, src_a3)
        conn.close()

        cfg = {
            "volume_code": "VOL99",
            "volume": "VOL 99",
            "test_number": 1,
            "doc_legacy_id": src_doc["legacy_id"],
            "transcript_legacy_id": src_t["legacy_id"],
            "audio_legacy_ids": {
                1: src_a1["legacy_id"],
                2: src_a2["legacy_id"],
                3: src_a3["legacy_id"],
                4: None,
            },
            "section_titles": {
                1: "Sec 1",
                2: "Sec 2",
                3: "Sec 3",
                4: "Sec 4",
            },
        }

        # Mock audio aligner to produce verified timing bounds from synthetic source records
        class MockAudioAligner(AudioAligner):
            def build_audio_asset(self, source_record, test_id, section_number=None, **kwargs):
                if not source_record:
                    return super().build_audio_asset(source_record, test_id, section_number, **kwargs)
                sec_suffix = f"-SEC{section_number:02d}" if section_number else "-FULL"
                audio_id = f"AUDIO-VOL99-01{sec_suffix}"
                prov = ProvenanceEnvelope(
                    source_file_id=source_record["file_id"],
                    source_legacy_id=source_record.get("legacy_id") or "UNKNOWN",
                    relative_path=source_record["relative_path"],
                    source_sha256=source_record["content_sha256"],
                    processing_unit="audio",
                    unit_identifier="audio_metadata",
                    raw_block_locator="file_header",
                    extractor_adapter="audio_meta",
                    extractor_version="0.1.0-file-id3",
                    normalizer_version=self.normalizer_version,
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
                return AudioAsset(
                    audio_id=audio_id,
                    test_id=test_id,
                    section_number=section_number,
                    file_path=source_record["relative_path"],
                    source_file_id=source_record["file_id"],
                    source_legacy_id=source_record.get("legacy_id"),
                    source_sha256=source_record["content_sha256"],
                    format="mp3",
                    duration_ms=600000,
                    duration_sec=600.0,
                    sample_rate_hz=44100,
                    channels="stereo",
                    bitrate_kbps=128,
                    audio_verification_status="verified",
                    quality_profile=qp,
                    _provenance=prov,
                )

        orchestrator = ListeningNormalizationOrchestrator(
            output_dir=out_dir,
            db_path=db_path,
            audio_aligner=MockAudioAligner(),
        )

        paragraphs = synthetic_data["transcript_paragraphs"]
        questions = synthetic_data["questions"]

        # 1. Initial Run
        res1 = orchestrator.run_pilot(
            config=cfg,
            paragraphs=paragraphs,
            items_def=questions,
            reports_dir=rep_dir,
            publication_permission="public_synthetic",
        )
        assert res1["written_count"] == res1["total_entities"]
        assert res1["skipped_count"] == 0

        # 2. Identical Rerun -> 100% skipped
        res2 = orchestrator.run_pilot(
            config=cfg,
            paragraphs=paragraphs,
            items_def=questions,
            reports_dir=rep_dir,
            publication_permission="public_synthetic",
        )
        assert res2["written_count"] == 0
        assert res2["skipped_count"] == res1["total_entities"]

        # 3. Modify Section 1 audio only
        conn = get_db_connection(db_path)
        new_sec1_audio_sha = "ffff1111" * 8
        conn.execute(
            "UPDATE sources SET content_sha256 = ? WHERE legacy_id = ?",
            (new_sec1_audio_sha, src_a1["legacy_id"]),
        )
        conn.commit()
        conn.close()

        # 4. Rerun without force
        res3 = orchestrator.run_pilot(
            config=cfg,
            paragraphs=paragraphs,
            items_def=questions,
            reports_dir=rep_dir,
            publication_permission="public_synthetic",
        )

        # 5. Assertions
        assert res3["written_count"] > 0
        assert res3["skipped_count"] > 0
        assert res3["written_count"] + res3["skipped_count"] == res3["total_entities"]

        # Check checkpoints in DB
        conn = get_db_connection(db_path)
        cur = conn.execute("SELECT entity_id, entity_type, raw_sha256, canonical_content_sha256, output_path, output_sha256 FROM normalization_checkpoints")
        checkpoints = {row[0]: row for row in cur.fetchall()}
        conn.close()

        # Section 1 audio asset: updated
        sec1_audio_id = "AUDIO-VOL99-01-SEC01"
        assert sec1_audio_id in checkpoints
        assert checkpoints[sec1_audio_id][2] == new_sec1_audio_sha

        # Section 2 & 3 audio assets: unchanged
        assert checkpoints["AUDIO-VOL99-01-SEC02"][2] == src_a2["content_sha256"]
        assert checkpoints["AUDIO-VOL99-01-SEC03"][2] == src_a3["content_sha256"]

        # Section 1 segments: updated
        # Questions & Answers: unchanged
        for q in questions:
            q_id = f"Q-VOL99-01-LS-{q['q_num']:03d}"
            ans_id = f"ANS-VOL99-01-LS-{q['q_num']:03d}-KEY"
            # Dependency hash of questions and answers depends strictly on doc_sha256!
            assert checkpoints[q_id][2] == src_doc["content_sha256"]
            assert checkpoints[ans_id][2] == src_doc["content_sha256"]

        # Checkpoint hashes consistent with outputs on disk
        for ent_id, row in checkpoints.items():
            out_p = Path(row[4])
            assert out_p.exists()
            content_bytes = out_p.read_bytes()
            assert hashlib.sha256(content_bytes).hexdigest() == row[5]

