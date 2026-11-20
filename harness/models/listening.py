"""Listening domain models for IELTS Data Harness V0.3-C."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from harness.models.provenance import ProvenanceEnvelope
from harness.models.quality import QualityProfile
from harness.models.question_bank import EvidenceType, QuestionType, WordLimitRule

SCHEMA_VERSION_LISTENING = "v0.3.0-listening"


class AudioAsset(BaseModel):
    """Normalized audio recording asset linked to an IELTS Listening section or test."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    audio_id: str = Field(
        ...,
        pattern=r"^AUDIO-[A-Z0-9-]+$",
        description="Deterministic audio asset ID (e.g. AUDIO-VOL01-01-SEC01)",
    )
    test_id: str = Field(
        ...,
        pattern=r"^TEST-IELTS-[A-Z0-9]+-\d{2}-LIS$",
        description="Parent listening test ID",
    )
    section_number: Optional[int] = Field(
        default=None,
        ge=1,
        le=4,
        description="Listening section number (1-4) or null for full test recording",
    )
    file_path: str = Field(
        ...,
        description="Relative or normalized path of the audio file",
    )
    source_file_id: str = Field(
        ...,
        pattern=r"^FILE-[a-f0-9]{12}$",
        description="Physical file ID from inventory",
    )
    source_legacy_id: Optional[str] = Field(
        default=None,
        description="Legacy source identifier (e.g. SRC-008)",
    )
    source_sha256: str = Field(
        ...,
        pattern=r"^[a-f0-9]{64}$",
        description="Cryptographic SHA-256 of the audio file bytes",
    )
    format: str = Field(
        ...,
        description="Audio container format (e.g. mp3, mp4, wav)",
    )
    codec: Optional[str] = Field(
        default=None,
        description="Audio compression codec if detected",
    )
    duration_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Audio duration in milliseconds",
    )
    duration_sec: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Audio duration in seconds",
    )
    sample_rate_hz: Optional[int] = Field(
        default=None,
        ge=0,
        description="Audio sample rate in Hertz",
    )
    channels: Optional[str] = Field(
        default=None,
        description="Channel layout (Mono, Stereo)",
    )
    bitrate_kbps: Optional[int] = Field(
        default=None,
        ge=0,
        description="Bitrate in kilobits per second",
    )
    raw_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Raw extractor metadata (ID3 tags, container info)",
    )
    audio_verification_status: Literal["verified", "missing", "corrupt", "unverified"] = Field(
        ...,
        description="Physical and cryptographic integrity status of audio asset",
    )
    quality_profile: QualityProfile = Field(...)
    provenance: ProvenanceEnvelope = Field(..., alias="_provenance")


class TranscriptSegment(BaseModel):
    """Normalized atomic segment within a listening transcript with verified or unaligned timing."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    segment_id: str = Field(
        ...,
        pattern=r"^TRANS-[A-Z0-9-]+-SEG\d{3,}$",
        description="Deterministic transcript segment ID",
    )
    section_id: str = Field(
        ...,
        pattern=r"^SEC-[A-Z0-9-]+-LS\d{2}$",
        description="Parent listening section ID",
    )
    test_id: str = Field(
        ...,
        pattern=r"^TEST-IELTS-[A-Z0-9]+-\d{2}-LIS$",
        description="Parent listening test ID",
    )
    sequence_index: int = Field(
        ...,
        ge=0,
        description="0-based sequence index within the section transcript",
    )
    speaker_id: Optional[str] = Field(
        default=None,
        description="Speaker identity string if present in source (e.g. Speaker 1, Sally)",
    )
    transcript_text: str = Field(
        ...,
        min_length=1,
        description="Verbatim transcript content text without silent edits",
    )
    start_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Start time offset in milliseconds from audio beginning",
    )
    end_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="End time offset in milliseconds from audio beginning",
    )
    timing_source: Literal["source_timestamp", "audio_alignment", "unaligned", "missing"] = Field(
        ...,
        description="Provenance origin of timing boundaries",
    )
    timing_verification_status: Literal[
        "verified", "unverified", "impossible_bounds", "out_of_order", "unaligned", "missing"
    ] = Field(
        ...,
        description="Forensic verification state of segment timing bounds",
    )
    raw_timestamp_str: Optional[str] = Field(
        default=None,
        description="Original source timestamp string (e.g. [00:01:49])",
    )
    quality_profile: QualityProfile = Field(...)
    provenance: ProvenanceEnvelope = Field(..., alias="_provenance")


class SpeakerTurn(BaseModel):
    """Cohesive conversational turn attributed to a single speaker."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    turn_id: str = Field(
        ...,
        pattern=r"^TURN-[A-Z0-9-]+-\d{3,}$",
        description="Deterministic speaker turn ID",
    )
    section_id: str = Field(
        ...,
        pattern=r"^SEC-[A-Z0-9-]+-LS\d{2}$",
        description="Parent listening section ID",
    )
    speaker_id: str = Field(
        ...,
        min_length=1,
        description="Speaker label (e.g. Speaker 1, Steve, Gary Payne)",
    )
    turn_index: int = Field(
        ...,
        ge=0,
        description="0-based index of this speaker turn within section",
    )
    text: str = Field(
        ...,
        min_length=1,
        description="Complete turn text aggregated across continuous segments",
    )
    start_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Turn start offset in milliseconds",
    )
    end_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Turn end offset in milliseconds",
    )
    segment_ids: List[str] = Field(
        default_factory=list,
        description="List of constituent transcript segment IDs",
    )
    quality_profile: QualityProfile = Field(...)
    provenance: ProvenanceEnvelope = Field(..., alias="_provenance")


class ListeningSection(BaseModel):
    """Normalized Listening Section (1-4) within an authentic IELTS Listening test."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    section_id: str = Field(
        ...,
        pattern=r"^SEC-[A-Z0-9-]+-LS\d{2}$",
        description="Deterministic section ID (e.g. SEC-VOL01-01-LS01)",
    )
    test_id: str = Field(
        ...,
        pattern=r"^TEST-IELTS-[A-Z0-9]+-\d{2}-LIS$",
        description="Parent test ID",
    )
    section_number: int = Field(
        ...,
        ge=1,
        le=4,
        description="Section sequence number (1, 2, 3, or 4)",
    )
    title: str = Field(
        ...,
        min_length=1,
        description="Section title or topic name (e.g. Beechen Festival)",
    )
    audio_asset_id: Optional[str] = Field(
        default=None,
        description="Linked audio asset ID",
    )
    audio_status: Literal["available", "missing", "unverified"] = Field(
        ...,
        description="Availability status of the section audio file",
    )
    transcript_status: Literal["verified_source", "extracted", "ai_generated", "missing"] = Field(
        ...,
        description="Provenance classification of the transcript content",
    )
    start_question_number: int = Field(
        ...,
        ge=1,
        le=40,
        description="First question number in section (e.g. 1, 11, 21, 31)",
    )
    end_question_number: int = Field(
        ...,
        ge=1,
        le=40,
        description="Last question number in section (e.g. 10, 20, 30, 40)",
    )
    segments: List[TranscriptSegment] = Field(
        default_factory=list,
        description="Ordered transcript segments belonging to this section",
    )
    speaker_turns: List[SpeakerTurn] = Field(
        default_factory=list,
        description="Ordered speaker turns belonging to this section",
    )
    quality_profile: QualityProfile = Field(...)
    provenance: ProvenanceEnvelope = Field(..., alias="_provenance")


class ListeningQuestion(BaseModel):
    """Normalized atomic IELTS Listening question item."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    question_id: str = Field(
        ...,
        pattern=r"^Q-[A-Z0-9-]+-LS-\d{3}$",
        description="Deterministic question ID (e.g. Q-VOL01-01-LS-001)",
    )
    section_id: str = Field(
        ...,
        pattern=r"^SEC-[A-Z0-9-]+-LS\d{2}$",
        description="Parent section ID",
    )
    test_id: str = Field(
        ...,
        pattern=r"^TEST-IELTS-[A-Z0-9]+-\d{2}-LIS$",
        description="Parent test ID",
    )
    question_number: int = Field(
        ...,
        ge=1,
        le=40,
        description="Question number (1-40)",
    )
    question_type: QuestionType = Field(
        ...,
        description="Categorical IELTS question type",
    )
    prompt_text: str = Field(
        ...,
        min_length=2,
        description="Exact question stem or context line",
    )
    options: Optional[Dict[str, str]] = Field(
        default=None,
        description="Key-value mapping of multiple choice / matching options (A, B, C...)",
    )
    blank_target: Optional[str] = Field(
        default=None,
        description="Target marker indicating completion blank position",
    )
    word_limit: Optional[str] = Field(
        default=None,
        description="Human-readable word limit constraint string from instructions",
    )
    word_limit_rule: Optional[WordLimitRule] = Field(
        default=None,
        description="Canonical word limit enumeration",
    )
    quality_profile: QualityProfile = Field(...)
    provenance: ProvenanceEnvelope = Field(..., alias="_provenance")


class ListeningAnswer(BaseModel):
    """Normalized answer key item linked to a listening question with verified provenance."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    answer_id: str = Field(
        ...,
        pattern=r"^ANS-[A-Z0-9-]+-(KEY|ALT\d{2})$",
        description="Deterministic answer key ID",
    )
    question_id: str = Field(
        ...,
        pattern=r"^Q-[A-Z0-9-]+-LS-\d{3}$",
        description="Target question ID",
    )
    test_id: str = Field(
        ...,
        pattern=r"^TEST-IELTS-[A-Z0-9]+-\d{2}-LIS$",
        description="Parent test ID",
    )
    section_id: str = Field(
        ...,
        pattern=r"^SEC-[A-Z0-9-]+-LS\d{2}$",
        description="Parent section ID",
    )
    target_value: Optional[str] = Field(
        default=None,
        description="Authoritative answer string from official key sheet",
    )
    acceptable_alternates: List[str] = Field(
        default_factory=list,
        description="List of valid alternative answers/spellings",
    )
    case_sensitive: bool = Field(
        default=False,
        description="Whether case sensitivity is strictly enforced",
    )
    source_key_ref: str = Field(
        ...,
        description="Exact source document page or coordinate citing this answer key",
    )
    answer_provenance_status: Literal["authoritative_source", "consensus", "unverified", "missing"] = Field(
        ...,
        description="Epistemic validation status of answer provenance",
    )
    quality_profile: QualityProfile = Field(...)
    provenance: ProvenanceEnvelope = Field(..., alias="_provenance")


class ListeningEvidence(BaseModel):
    """Grounding proof linking an answer to transcript segments and optional audio intervals."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    evidence_id: str = Field(
        ...,
        pattern=r"^EVID-[A-Z0-9-]+-LS\d{2}-\d{2}$",
        description="Deterministic evidence item ID",
    )
    question_id: str = Field(
        ...,
        pattern=r"^Q-[A-Z0-9-]+-LS-\d{3}$",
        description="Associated question ID",
    )
    answer_id: Optional[str] = Field(
        default=None,
        pattern=r"^ANS-[A-Z0-9-]+-(KEY|ALT\d{2})$",
        description="Associated answer ID",
    )
    section_id: str = Field(
        ...,
        pattern=r"^SEC-[A-Z0-9-]+-LS\d{2}$",
        description="Associated section ID",
    )
    segment_id: Optional[str] = Field(
        default=None,
        description="Linked transcript segment ID containing the proof",
    )
    verbatim_quote: Optional[str] = Field(
        default=None,
        description="Verbatim sentence from transcript directly supporting or deciding answer",
    )
    start_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Audio start offset in milliseconds if verifiable",
    )
    end_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Audio end offset in milliseconds if verifiable",
    )
    timing_status: Literal["verified", "unaligned", "missing"] = Field(
        ...,
        description="Audio grounding verification status",
    )
    evidence_type: EvidenceType = Field(
        ...,
        description="Direct support, contradictory evidence, or not given",
    )
    grounding_status: Literal["grounded", "unresolved", "missing_evidence"] = Field(
        ...,
        description="Grounding integrity status",
    )
    explanation_text: Optional[str] = Field(
        default=None,
        description="Optional pedagogical rationale or missing explanation note",
    )
    quality_profile: QualityProfile = Field(...)
    provenance: ProvenanceEnvelope = Field(..., alias="_provenance")


class ListeningTest(BaseModel):
    """Top-level normalized IELTS Listening Test paper."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    test_id: str = Field(
        ...,
        pattern=r"^TEST-IELTS-[A-Z0-9]+-\d{2}-LIS$",
        description="Deterministic test identifier",
    )
    volume: str = Field(
        ...,
        description="Corpus volume identifier (e.g. VOL 1)",
    )
    test_number: int = Field(
        ...,
        ge=1,
        le=20,
        description="Test index within the volume",
    )
    track: Literal["academic", "general_training"] = Field(
        default="academic",
        description="Test track",
    )
    title: str = Field(
        ...,
        min_length=5,
        description="Full title of test",
    )
    source_reference_id: Optional[str] = Field(
        default=None,
        description="Physical source file ID of the question booklet",
    )
    sections: List[ListeningSection] = Field(
        default_factory=list,
        description="List of normalized listening sections",
    )
    audio_assets: List[AudioAsset] = Field(
        default_factory=list,
        description="List of linked audio assets",
    )
    questions: List[ListeningQuestion] = Field(
        default_factory=list,
        description="List of all questions in test (1-40)",
    )
    answers: List[ListeningAnswer] = Field(
        default_factory=list,
        description="List of all answer keys in test (1-40)",
    )
    evidence: List[ListeningEvidence] = Field(
        default_factory=list,
        description="List of evidence proof items linking answers to transcripts",
    )
    quality_profile: QualityProfile = Field(...)
    provenance: ProvenanceEnvelope = Field(..., alias="_provenance")
