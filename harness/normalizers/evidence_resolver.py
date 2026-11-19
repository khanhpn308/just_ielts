"""Evidence span resolver and explanation normalizer for IELTS Data Harness V0.2."""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional, Tuple

from harness.models.provenance import ProvenanceEnvelope
from harness.models.quality import ExplanationVerification, LifecycleStatus, QualityProfile
from harness.models.question_bank import (
    AuthorType,
    EvidenceType,
    IELTSAnswer,
    IELTSEvidence,
    IELTSExplanation,
    IELTSQuestion,
    ParaphrasePair,
    PassageOrSection,
)
from harness.normalizers.base import (
    NORMALIZER_VERSION,
    SCHEMA_VERSION,
    BaseNormalizer,
)


def find_exact_quote(quote: str, narrative_text: str) -> Optional[Tuple[int, int]]:
    """Locates exact substring quote in narrative_text and returns (char_start, char_end)."""
    if not quote or not narrative_text:
        return None
    idx = narrative_text.find(quote)
    if idx != -1:
        return idx, idx + len(quote)
    return None


def find_fuzzy_quote(
    quote: str, narrative_text: str, min_ratio: float = 0.85
) -> Optional[Tuple[int, int, float, str]]:
    """Finds best matching sentence/window in narrative_text via difflib.SequenceMatcher.

    Returns (char_start, char_end, similarity_ratio, matched_text) or None.
    """
    if not quote or not narrative_text:
        return None

    q_clean = " ".join(quote.split())
    q_len = len(q_clean)

    # Split narrative text into sentences / candidate chunks
    sentences = re.split(r"(?<=[.?!])\s+", narrative_text)
    best_match = None
    best_ratio = 0.0

    curr_pos = 0
    for sent in sentences:
        s_start = narrative_text.find(sent, curr_pos)
        if s_start == -1:
            s_start = curr_pos
        s_end = s_start + len(sent)
        curr_pos = s_end

        ratio = difflib.SequenceMatcher(None, q_clean, sent.strip()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = (s_start, s_end, ratio, sent.strip())

    if best_match and best_ratio >= min_ratio:
        return best_match

    return None


class EvidenceResolver(BaseNormalizer):
    """Grounds answers against passage text and normalizes pedagogical explanations."""

    def __init__(self, normalizer_version: str = NORMALIZER_VERSION):
        super().__init__(normalizer_version=normalizer_version)

    def resolve_evidence(
        self,
        evidence_id: str,
        answer: Optional[IELTSAnswer],
        passage: PassageOrSection,
        evidence_type: EvidenceType,
        candidate_quote: Optional[str] = None,
        paragraph_label: Optional[str] = None,
        missing_information_rationale: Optional[str] = None,
        source_record: Optional[Dict[str, Any]] = None,
        publication_permission: str = "private_copyrighted",
        unit_identifier: Optional[str] = None,
        raw_block_locator: Optional[str] = None,
    ) -> IELTSEvidence:
        """Grounds evidence candidate into validated IELTSEvidence entity."""
        if source_record is None:
            source_record = {
                "file_id": "FILE-000000000000",
                "legacy_id": "UNKNOWN",
                "relative_path": "unknown",
                "content_sha256": "0" * 64,
            }

        flags: List[str] = []
        char_start: Optional[int] = None
        char_end: Optional[int] = None
        verbatim_quote: Optional[str] = None
        exact_match_verified = False

        if evidence_type == "insufficient_information_not_given":
            # Invariant: For NOT GIVEN, verbatim_quote MUST be null
            verbatim_quote = None
            char_start = None
            char_end = None
            exact_match_verified = False
            if not missing_information_rationale:
                flags.append("MISSING_NOT_GIVEN_RATIONALE")
                lifecycle_status = "review_required"
            else:
                lifecycle_status = "reviewed"
        else:
            if not candidate_quote:
                flags.append("MISSING_EVIDENCE_QUOTE")
                lifecycle_status = "review_required"
            else:
                # 1. Try exact match
                exact_span = find_exact_quote(candidate_quote, passage.narrative_text)
                if exact_span:
                    char_start, char_end = exact_span
                    verbatim_quote = candidate_quote
                    exact_match_verified = True
                    lifecycle_status = "reviewed"
                else:
                    # 2. Try fuzzy match fallback
                    fuzzy_span = find_fuzzy_quote(candidate_quote, passage.narrative_text, min_ratio=0.85)
                    if fuzzy_span:
                        char_start, char_end, ratio, matched_text = fuzzy_span
                        verbatim_quote = matched_text
                        exact_match_verified = False
                        flags.append(f"FUZZY_EVIDENCE_MATCH:{ratio:.2f}")
                        lifecycle_status = "review_required"
                    else:
                        verbatim_quote = candidate_quote
                        char_start = None
                        char_end = None
                        exact_match_verified = False
                        flags.append("UNRESOLVED_EVIDENCE_SPAN")
                        lifecycle_status = "review_required"

        is_official = (
            source_record.get("collection") == "official_cambridge"
            or (
                source_record.get("source_fidelity") == "authoritative_official"
                and "SRC-137" not in source_record.get("legacy_id", "")
            )
        )
        source_fidelity: SourceFidelity = "authoritative_official" if is_official else "secondary_reputable"
        if answer and hasattr(answer, "quality_profile"):
            ans_verif: AnswerVerification = answer.quality_profile.answer_verification
        else:
            ans_verif = "authoritative_key" if is_official else "unverified"

        qp = QualityProfile(
            lifecycle_status=lifecycle_status,  # type: ignore[arg-type]
            extraction_quality="complete_clean" if exact_match_verified or evidence_type == "insufficient_information_not_given" else "ocr_noisy",
            source_fidelity=source_fidelity,
            answer_verification=ans_verif,
            explanation_verification="source_provided",
            publication_permission=publication_permission,  # type: ignore[arg-type]
            validation_flags=flags,
        )

        prov = ProvenanceEnvelope(
            schema_version=SCHEMA_VERSION,
            source_file_id=source_record["file_id"],
            source_legacy_id=source_record["legacy_id"],
            relative_path=source_record["relative_path"],
            source_sha256=source_record["content_sha256"],
            processing_unit="page",
            unit_identifier=unit_identifier or "page_0001",
            raw_block_locator=raw_block_locator or f"evidence:{evidence_id}",
            extractor_adapter="pdf_ocr",
            extractor_version="0.1.0-tesseract-pdftoppm",
            normalizer_version=self.normalizer_version,
            canonical_content_sha256=None,
            normalized_at=None,
        )

        return IELTSEvidence(
            evidence_id=evidence_id,
            answer_id=answer.answer_id if answer else None,
            passage_id=passage.passage_id,
            evidence_type=evidence_type,
            paragraph_label=paragraph_label,
            char_start=char_start,
            char_end=char_end,
            verbatim_quote=verbatim_quote,
            exact_match_verified=exact_match_verified,
            missing_information_rationale=missing_information_rationale,
            audio_interval=None,
            quality_profile=qp,
            _provenance=prov,
        )

    def resolve_explanation(
        self,
        explanation_id: str,
        question: IELTSQuestion,
        answer: Optional[IELTSAnswer],
        evidence: Optional[IELTSEvidence],
        rationale_en: Optional[str],
        rationale_vi: Optional[str] = None,
        paraphrase_map: Optional[List[Dict[str, str]]] = None,
        distractor_notes: Optional[str] = None,
        author_type: AuthorType = "source_published",
        source_record: Optional[Dict[str, Any]] = None,
        publication_permission: str = "private_copyrighted",
        unit_identifier: Optional[str] = None,
        raw_block_locator: Optional[str] = None,
        explanation_verification: Optional[ExplanationVerification] = None,
    ) -> IELTSExplanation:
        """Constructs and validates IELTSExplanation entity."""
        if source_record is None:
            source_record = {
                "file_id": "FILE-000000000000",
                "legacy_id": "UNKNOWN",
                "relative_path": "unknown",
                "content_sha256": "0" * 64,
            }

        pairs = [
            ParaphrasePair(prompt_term=p["prompt_term"], passage_term=p["passage_term"])
            for p in (paraphrase_map or [])
        ]

        flags: List[str] = []
        if explanation_verification:
            expl_verif = explanation_verification
            lifecycle_status = "review_required" if "unverified" in expl_verif else "reviewed"
        elif author_type == "machine_drafted":
            expl_verif = "machine_drafted_unverified"
            lifecycle_status = "review_required"
            flags.append("MACHINE_DRAFTED_UNVERIFIED")
        elif not rationale_en and not rationale_vi:
            expl_verif = "missing_explanation"
            lifecycle_status = "review_required"
            flags.append("MISSING_EXPLANATION_RATIONALE")
        elif author_type == "source_published":
            expl_verif = "source_provided"
            lifecycle_status = "reviewed"
        elif author_type == "expert_teacher":
            expl_verif = "expert_verified"
            lifecycle_status = "reviewed"
        else:
            expl_verif = "machine_drafted_unverified"
            lifecycle_status = "review_required"
            flags.append("MACHINE_DRAFTED_UNVERIFIED")

        is_official = (
            source_record.get("collection") == "official_cambridge"
            or (
                source_record.get("source_fidelity") == "authoritative_official"
                and "SRC-137" not in source_record.get("legacy_id", "")
            )
        )
        source_fidelity: SourceFidelity = "authoritative_official" if is_official else "secondary_reputable"
        if answer and hasattr(answer, "quality_profile"):
            ans_verif: AnswerVerification = answer.quality_profile.answer_verification
        else:
            ans_verif = "authoritative_key" if is_official else "unverified"

        # If answer itself is unverified, human review of the explanation is mandatory
        if ans_verif == "unverified" and lifecycle_status == "reviewed":
            lifecycle_status = "review_required"
            flags.append("UNVERIFIED_KEY_REQUIRES_REVIEW")

        qp = QualityProfile(
            lifecycle_status=lifecycle_status,
            extraction_quality="complete_clean",
            source_fidelity=source_fidelity,
            answer_verification=ans_verif,
            explanation_verification=expl_verif,
            publication_permission=publication_permission,  # type: ignore[arg-type]
            validation_flags=flags,
        )

        prov = ProvenanceEnvelope(
            schema_version=SCHEMA_VERSION,
            source_file_id=source_record["file_id"],
            source_legacy_id=source_record["legacy_id"],
            relative_path=source_record["relative_path"],
            source_sha256=source_record["content_sha256"],
            processing_unit="page",
            unit_identifier=unit_identifier or "page_0001",
            raw_block_locator=raw_block_locator or f"explanation:{explanation_id}",
            extractor_adapter="pdf_ocr",
            extractor_version="0.1.0-tesseract-pdftoppm",
            normalizer_version=self.normalizer_version,
            canonical_content_sha256=None,
            normalized_at=None,
        )

        return IELTSExplanation(
            explanation_id=explanation_id,
            question_id=question.question_id,
            answer_id=answer.answer_id if answer else None,
            evidence_id=evidence.evidence_id if evidence else None,
            rationale_en=rationale_en,
            rationale_vi=rationale_vi,
            paraphrase_map=pairs,
            distractor_notes=distractor_notes,
            author_type=author_type,
            quality_profile=qp,
            _provenance=prov,
        )

    def normalize(self, *args: Any, **kwargs: Any) -> Any:
        pass
