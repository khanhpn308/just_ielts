"""Source relationship domain models for IELTS Data Harness V0.3-A."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

RelationshipType = Literal[
    "question_to_answer_key",
    "question_to_explanation",
    "listening_to_audio",
    "listening_to_transcript",
    "writing_to_sample_answer",
]

RelationshipStatus = Literal[
    "candidate",
    "review_required",
    "confirmed",
    "rejected",
]

SkillType = Literal[
    "reading",
    "listening",
    "writing",
    "speaking",
]

ConflictType = Literal[
    "CROSS_VOLUME_MISMATCH",
    "CONFLICTING_ANSWER_KEYS",
    "TEST_NUMBER_MISMATCH",
    "PASSAGE_MISMATCH",
    "SKILL_MISMATCH",
    "DUPLICATE_CANDIDATE",
    "MISSING_METADATA",
    "AMBIGUOUS_TEST_IDENTITY",
    "UNSUPPORTED_RELATIONSHIP",
    "UNGROUNDED_IDENTITY",
    "STALE_SOURCE_HASH",
]

ConflictSeverity = Literal[
    "critical",
    "high",
    "medium",
    "low",
]

SCHEMA_VERSION_RELATIONSHIP = "v0.3.0-relationship"


def compute_relationship_id(
    source_file_id: str,
    target_file_id: str,
    relationship_type: str,
    volume: str,
    test_number: Optional[int] = None,
    passage_or_section: Optional[int] = None,
) -> str:
    """Computes stable, deterministic relationship identifier."""
    key = f"{source_file_id}:{target_file_id}:{relationship_type}:{volume}:{test_number}:{passage_or_section}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"REL-{digest}"


class SourceRelationship(BaseModel):
    """Deterministic, evidence-grounded relationship linking multiple IELTS sources."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    relationship_id: str = Field(
        ...,
        pattern=r"^REL-[a-f0-9]{16}$",
        description="Deterministic relationship ID derived from core invariant tuple.",
    )
    source_file_id: str = Field(
        ...,
        pattern=r"^FILE-[a-f0-9]{12}$",
        description="Primary source file identifier (e.g. question booklet).",
    )
    target_file_id: str = Field(
        ...,
        pattern=r"^FILE-[a-f0-9]{12}$",
        description="Target linked file identifier (e.g. answer key, explanation, audio, transcript).",
    )
    relationship_type: RelationshipType = Field(
        ...,
        description="Supported relationship type.",
    )
    collection: str = Field(
        ...,
        min_length=1,
        description="Corpus collection name (e.g. 'VOL 6', 'VOL 1').",
    )
    volume: str = Field(
        ...,
        min_length=1,
        description="Canonical volume identifier (e.g. 'VOL 6', 'VOL 1').",
    )
    test_number: Optional[int] = Field(
        default=None,
        ge=1,
        le=20,
        description="IELTS test number within the volume.",
    )
    passage_or_section: Optional[int] = Field(
        default=None,
        ge=1,
        le=4,
        description="Reading passage (1-3) or Listening section (1-4).",
    )
    skill: SkillType = Field(
        ...,
        description="Primary language skill targeted by the test components.",
    )
    identity_evidence: Dict[str, Any] = Field(
        default_factory=dict,
        description="Detailed evidence records supporting or refuting the match.",
    )
    validation_flags: List[str] = Field(
        default_factory=list,
        description="Machine-evaluable diagnostic and gate verification flags.",
    )
    match_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0-1.0). Confidence alone NEVER promotes to confirmed.",
    )
    relationship_status: RelationshipStatus = Field(
        ...,
        description="Epistemic status of the relationship.",
    )
    provenance: Dict[str, Any] = Field(
        ...,
        description="Audit provenance tracking generator versions, config, and source hashes.",
    )
    source_content_sha256: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of primary source content.",
    )
    target_content_sha256: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of target source content.",
    )
    config_fingerprint: Optional[str] = Field(
        default=None,
        description="Configuration and rule version fingerprint.",
    )
    evidence_fingerprint: Optional[str] = Field(
        default=None,
        description="Deterministic SHA-256 digest of identity evidence.",
    )
    schema_version: str = Field(
        default=SCHEMA_VERSION_RELATIONSHIP,
        description="Schema specification version.",
    )


class RelationshipConflict(BaseModel):
    """Explicit record of conflicting evidence preventing or rejecting a relationship."""

    model_config = ConfigDict(extra="forbid")

    conflict_id: str = Field(
        ...,
        pattern=r"^CONF-[a-f0-9]{16}$",
        description="Deterministic conflict ID.",
    )
    relationship_id: Optional[str] = Field(
        default=None,
        pattern=r"^REL-[a-f0-9]{16}$",
        description="Associated relationship ID if generated.",
    )
    source_file_id: str = Field(
        ...,
        pattern=r"^FILE-[a-f0-9]{12}$",
    )
    target_file_id: str = Field(
        ...,
        pattern=r"^FILE-[a-f0-9]{12}$",
    )
    conflict_type: ConflictType = Field(
        ...,
        description="Classification of the conflict.",
    )
    severity: ConflictSeverity = Field(
        ...,
        description="Impact severity on relationship validity.",
    )
    description: str = Field(
        ...,
        min_length=5,
        description="Human-readable forensic explanation of the mismatch.",
    )
    evidence: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured data proving the contradiction.",
    )
    detected_at: str = Field(
        ...,
        description="ISO 8601 UTC timestamp of conflict detection.",
    )


class RelationshipReview(BaseModel):
    """Audit record of a lifecycle review state transition for a relationship."""

    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(
        ...,
        pattern=r"^REV-[a-f0-9]{16}$",
    )
    relationship_id: str = Field(
        ...,
        pattern=r"^REL-[a-f0-9]{16}$",
    )
    previous_status: RelationshipStatus = Field(...)
    new_status: RelationshipStatus = Field(...)
    reviewer: str = Field(..., min_length=2)
    reason: str = Field(..., min_length=5)
    created_at: str = Field(
        ...,
        description="ISO 8601 UTC timestamp of review decision.",
    )
