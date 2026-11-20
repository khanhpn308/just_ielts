"""Source relationship domain models for IELTS Data Harness V0.3-A."""

from __future__ import annotations

from datetime import datetime
import hashlib
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

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

ReviewDecision = Literal[
    "approve",
    "reject",
    "defer",
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
SCHEMA_VERSION_REVIEW = "v0.3.0-review"


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


def compute_review_id(
    relationship_id: str,
    reviewer_id: str,
    decision: str,
    reviewed_at: str,
) -> str:
    """Computes stable, deterministic review identifier."""
    key = f"{relationship_id}:{reviewer_id}:{decision}:{reviewed_at}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"REV-{digest}"


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
    """Audit record of a human or automated review lifecycle event for a source relationship."""

    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(
        ...,
        pattern=r"^REV-[a-f0-9]{16}$",
    )
    relationship_id: str = Field(
        ...,
        pattern=r"^REL-[a-f0-9]{16}$",
    )
    reviewer_id: str = Field(
        default="",
        min_length=1,
        description="Operator identifier (operator declaration, not authenticated expert).",
    )
    reviewer: str = Field(
        default="",
        min_length=1,
        description="Legacy alias for reviewer_id.",
    )
    previous_status: RelationshipStatus = Field(
        ...,
        description="Status prior to this review action.",
    )
    requested_status: Optional[str] = Field(
        default=None,
        description="Requested target status by reviewer.",
    )
    final_status: Optional[RelationshipStatus] = Field(
        default=None,
        description="Resulting status after policy evaluation.",
    )
    new_status: Optional[RelationshipStatus] = Field(
        default=None,
        description="Legacy alias for final_status.",
    )
    decision: Optional[ReviewDecision] = Field(
        default=None,
        description="Human review decision (approve, reject, defer).",
    )
    reason: str = Field(
        ...,
        min_length=5,
        description="Mandatory documented rationale for the decision.",
    )
    reviewed_at: Optional[str] = Field(
        default=None,
        description="Timezone-aware ISO 8601 timestamp of review decision.",
    )
    created_at: Optional[str] = Field(
        default=None,
        description="Legacy timestamp field (synced with reviewed_at).",
    )
    source_fingerprint: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of source content at review time.",
    )
    target_fingerprint: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of target content at review time.",
    )
    evidence_references: Dict[str, Any] = Field(
        default_factory=dict,
        description="References to verified independent supporting evidence.",
    )
    review_policy_version: str = Field(
        default="v0.3.0-b",
        description="Policy ruleset version applied during evaluation.",
    )
    expert_verified: bool = Field(
        default=False,
        description="Whether decision is backed by authenticated expert qualification.",
    )

    @model_validator(mode="before")
    @classmethod
    def _sync_and_validate(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        d = dict(data)

        # 1. Sync reviewer_id and reviewer
        rev_id = d.get("reviewer_id") or d.get("reviewer") or ""
        if rev_id:
            d.setdefault("reviewer_id", rev_id)
            d.setdefault("reviewer", rev_id)

        # 2. Sync final_status and new_status
        f_stat = d.get("final_status") or d.get("new_status")
        if f_stat:
            d.setdefault("final_status", f_stat)
            d.setdefault("new_status", f_stat)

        # 3. Requested status fallback
        if not d.get("requested_status") and d.get("final_status"):
            d["requested_status"] = d["final_status"]

        # 4. Sync reviewed_at and created_at
        t_stamp = d.get("reviewed_at") or d.get("created_at")
        if t_stamp:
            d.setdefault("reviewed_at", t_stamp)
            d.setdefault("created_at", t_stamp)

            # Validate timezone awareness if reviewed_at was passed or explicitly requested
            # Note: ISO format strings can be checked for timezone
            try:
                dt = datetime.fromisoformat(t_stamp.replace("Z", "+00:00"))
                if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                    raise ValueError(f"Timestamp '{t_stamp}' must be timezone-aware.")
            except Exception as e:
                if "timezone-aware" in str(e):
                    raise
                raise ValueError(f"Invalid ISO 8601 timestamp '{t_stamp}': {e}")

        return d
