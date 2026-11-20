"""Quality profile and verification state machine model for IELTS Data Harness V0.2."""

from __future__ import annotations

from typing import List, Literal
from pydantic import BaseModel, ConfigDict, Field


LifecycleStatus = Literal[
    "extracted",
    "review_required",
    "reviewed",
    "verified",
    "rejected",
]

ExtractionQuality = Literal[
    "complete_clean",
    "ocr_noisy",
    "segmented_imperfect",
    "truncated_missing_pages",
]

SourceFidelity = Literal[
    "authoritative_official",
    "secondary_reputable",
    "unverified_community",
]

AnswerVerification = Literal[
    "authoritative_key",
    "consensus_key",
    "unverified",
    "disputed",
    "missing_key",
]

ExplanationVerification = Literal[
    "source_provided",
    "expert_verified",
    "machine_drafted_unverified",
    "unsupported",
    "missing_explanation",
]

PublicationPermission = Literal[
    "public_synthetic",
    "private_copyrighted",
    "restricted_citation",
]


class QualityProfile(BaseModel):
    """Reusable multi-dimensional quality profile and verification state machine."""

    model_config = ConfigDict(extra="forbid")

    lifecycle_status: LifecycleStatus = Field(
        ...,
        description="Lifecycle state of the entity in the verification pipeline.",
    )
    extraction_quality: ExtractionQuality = Field(
        ...,
        description="Physical text extraction fidelity and completeness.",
    )
    source_fidelity: SourceFidelity = Field(
        ...,
        description="Authority and editorial rigor of the source publication.",
    )
    answer_verification: AnswerVerification = Field(
        ...,
        description="Epistemic certainty of the answer key value.",
    )
    explanation_verification: ExplanationVerification = Field(
        ...,
        description="Pedagogical validity and grounding of the rationale.",
    )
    publication_permission: PublicationPermission = Field(
        ...,
        description="Legal copyright and repository distribution classification.",
    )
    validation_flags: List[str] = Field(
        default_factory=list,
        description="Diagnostic warning or informational flags emitted by normalizer.",
    )
