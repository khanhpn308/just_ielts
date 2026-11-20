"""Question bank domain models for IELTS Data Harness V0.2."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from harness.models.provenance import ProvenanceEnvelope
from harness.models.quality import QualityProfile


QuestionType = Literal[
    "true-false-not-given",
    "yes-no-not-given",
    "multiple-choice-single",
    "multiple-choice-multi",
    "matching-information",
    "matching-headings",
    "matching-features",
    "matching-sentence-endings",
    "sentence-completion",
    "summary-completion",
    "note-completion",
    "table-completion",
    "flow-chart-completion",
    "diagram-label-completion",
    "short-answer",
]

WordLimitRule = Literal[
    "one_word_only",
    "no_more_than_two_words",
    "no_more_than_three_words",
    "one_word_and_or_a_number",
    "no_more_than_two_words_and_or_a_number",
    "no_more_than_three_words_and_or_a_number",
    "a_number",
    "letters_only",
]

EvidenceType = Literal[
    "direct_support",
    "contradictory_evidence",
    "insufficient_information_not_given",
]

AuthorType = Literal[
    "source_published",
    "expert_teacher",
    "machine_drafted",
]


class IELTSTest(BaseModel):
    """Normalized representation of an authentic or synthetic IELTS test paper."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    test_id: str = Field(
        ...,
        pattern=r"^TEST-IELTS-[A-Z0-9]+-\d{2}-(ACAD|GT)$",
        description="Deterministic test ID",
    )
    title: str = Field(..., min_length=5)
    volume: str = Field(...)
    test_number: int = Field(..., ge=1, le=20)
    track: Literal["academic", "general_training"] = Field(...)
    source_reference_id: Optional[str] = Field(default=None)
    sections_present: List[Literal["reading", "listening", "writing", "speaking"]] = Field(
        ..., min_length=1
    )
    quality_profile: QualityProfile = Field(...)
    provenance: ProvenanceEnvelope = Field(..., alias="_provenance")


class ParagraphItem(BaseModel):
    """Paragraph item within a Reading passage or Listening section."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(
        ...,
        description="Paragraph letter (A, B, C...) or numerical sequence label",
    )
    sequence_index: int = Field(..., ge=0)
    char_start: int = Field(..., ge=0)
    char_end: int = Field(..., ge=0)
    text: str = Field(...)


class PassageOrSection(BaseModel):
    """Normalized Reading passage or Listening section within an IELTS test."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    passage_id: str = Field(
        ...,
        pattern=r"^(PASSAGE|SECTION)-[A-Z0-9-]+-(RD|LS)\d{2}$",
    )
    test_id: str = Field(
        ...,
        pattern=r"^TEST-IELTS-[A-Z0-9]+-\d{2}-(ACAD|GT)$",
    )
    skill: Literal["reading", "listening"] = Field(...)
    sequence_number: int = Field(..., ge=1, le=4)
    title: str = Field(..., min_length=1)
    subtitle: Optional[str] = Field(default=None)
    narrative_text: str = Field(..., min_length=100)
    paragraphs: List[ParagraphItem] = Field(..., min_length=1)
    audio_track_ref: Optional[str] = Field(default=None)
    word_count: int = Field(..., ge=50, le=2000)
    quality_profile: QualityProfile = Field(...)
    provenance: ProvenanceEnvelope = Field(..., alias="_provenance")


class SharedOption(BaseModel):
    """Option choice within a question group."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(...)
    text: str = Field(...)


class QuestionGroup(BaseModel):
    """Normalized instruction block clustering related question items."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    group_id: str = Field(
        ...,
        pattern=r"^QG-[A-Z0-9-]+-G\d{2}$",
    )
    passage_id: Optional[str] = Field(
        default=None,
        pattern=r"^(PASSAGE|SECTION)-[A-Z0-9-]+-(RD|LS)\d{2}$",
        description="Parent passage/section ID. Nullable for standalone question groups.",
    )
    start_question_number: int = Field(..., ge=1, le=40)
    end_question_number: int = Field(..., ge=1, le=40)
    question_type: QuestionType = Field(...)
    instruction_text: str = Field(..., min_length=5)
    word_limit_rule: Optional[WordLimitRule] = Field(default=None)
    shared_options: Optional[List[SharedOption]] = Field(default=None)
    quality_profile: QualityProfile = Field(...)
    provenance: ProvenanceEnvelope = Field(..., alias="_provenance")


class IELTSQuestion(BaseModel):
    """Normalized atomic test question item."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    question_id: str = Field(
        ...,
        pattern=r"^Q-[A-Z0-9-]+-(RD|LS|WR|SP)-\d{3}$",
    )
    group_id: str = Field(
        ...,
        pattern=r"^QG-[A-Z0-9-]+-G\d{2}$",
    )
    passage_id: Optional[str] = Field(
        default=None,
        pattern=r"^(PASSAGE|SECTION)-[A-Z0-9-]+-(RD|LS)\d{2}$",
        description="Associated passage/section ID. Nullable for standalone prompts.",
    )
    question_number: int = Field(..., ge=1, le=40)
    question_type: QuestionType = Field(...)
    prompt_text: str = Field(..., min_length=3)
    options: Optional[Dict[str, str]] = Field(default=None)
    blank_target: Optional[str] = Field(default=None)
    linked_principle_ids: List[str] = Field(
        default_factory=list,
    )
    quality_profile: QualityProfile = Field(...)
    provenance: ProvenanceEnvelope = Field(..., alias="_provenance")


class IELTSAnswer(BaseModel):
    """Normalized ground truth answer key and verified variants."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    answer_id: str = Field(
        ...,
        pattern=r"^ANS-[A-Z0-9-]+-(KEY|ALT\d{2})$",
    )
    question_id: Optional[str] = Field(
        default=None,
        pattern=r"^Q-[A-Z0-9-]+-(RD|LS|WR|SP)-\d{3}$",
        description="Associated question ID. Null for orphaned answer keys.",
    )
    target_value: Optional[str] = Field(
        default=None,
        description="Primary authoritative answer string. Null if key is unrecorded or cut off.",
    )
    acceptable_alternates: List[str] = Field(default_factory=list)
    case_sensitive: bool = Field(default=False)
    source_key_ref: str = Field(
        ...,
        description="Document page, sheet name, or cell coordinate citing the answer key",
    )
    quality_profile: QualityProfile = Field(...)
    provenance: ProvenanceEnvelope = Field(..., alias="_provenance")


class AudioInterval(BaseModel):
    """Auditory grounding interval."""

    model_config = ConfigDict(extra="forbid")

    start_sec: float = Field(..., ge=0.0)
    end_sec: float = Field(..., ge=0.0)


class IELTSEvidence(BaseModel):
    """Normalized textual or auditory grounding proof supporting an answer."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    evidence_id: str = Field(
        ...,
        pattern=r"^EVID-[A-Z0-9-]+-\d{2}$",
    )
    answer_id: Optional[str] = Field(
        default=None,
        pattern=r"^ANS-[A-Z0-9-]+-(KEY|ALT\d{2})$",
        description="Associated answer ID. Nullable for unlinked or orphan evidence.",
    )
    passage_id: Optional[str] = Field(
        default=None,
        pattern=r"^(PASSAGE|SECTION)-[A-Z0-9-]+-(RD|LS)\d{2}$",
        description="Associated passage ID. Nullable if unlinked.",
    )
    evidence_type: EvidenceType = Field(
        ...,
        description="Epistemic nature of the evidence.",
    )
    paragraph_label: Optional[str] = Field(default=None)
    char_start: Optional[int] = Field(default=None, ge=0)
    char_end: Optional[int] = Field(default=None, ge=0)
    verbatim_quote: Optional[str] = Field(
        default=None,
        description="Exact quoted sentence from passage. Null for NOT GIVEN.",
    )
    exact_match_verified: bool = Field(
        default=False,
        description="True if verbatim_quote matches narrative_text[char_start:char_end] exactly.",
    )
    missing_information_rationale: Optional[str] = Field(
        default=None,
        description="Pedagogical justification for NOT GIVEN.",
    )
    audio_interval: Optional[AudioInterval] = Field(default=None)
    quality_profile: QualityProfile = Field(...)
    provenance: ProvenanceEnvelope = Field(..., alias="_provenance")


class ParaphrasePair(BaseModel):
    """Lexical paraphrase mapping pair."""

    model_config = ConfigDict(extra="forbid")

    prompt_term: str = Field(...)
    passage_term: str = Field(...)


class IELTSExplanation(BaseModel):
    """Normalized pedagogical rationale, distractor analysis, and lexical paraphrase mapping."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    explanation_id: str = Field(
        ...,
        pattern=r"^EXPL-[A-Z0-9-]+$",
    )
    question_id: str = Field(
        ...,
        pattern=r"^Q-[A-Z0-9-]+-(RD|LS|WR|SP)-\d{3}$",
    )
    answer_id: Optional[str] = Field(
        default=None,
        pattern=r"^ANS-[A-Z0-9-]+-(KEY|ALT\d{2})$",
        description="Associated answer ID. Null if answer key is unlinked or missing.",
    )
    evidence_id: Optional[str] = Field(
        default=None,
        pattern=r"^EVID-[A-Z0-9-]+-\d{2}$",
        description="Associated evidence ID. Null if rationale is ungrounded.",
    )
    rationale_en: Optional[str] = Field(default=None)
    rationale_vi: Optional[str] = Field(default=None)
    paraphrase_map: List[ParaphrasePair] = Field(default_factory=list)
    distractor_notes: Optional[str] = Field(default=None)
    author_type: AuthorType = Field(...)
    quality_profile: QualityProfile = Field(...)
    provenance: ProvenanceEnvelope = Field(..., alias="_provenance")
