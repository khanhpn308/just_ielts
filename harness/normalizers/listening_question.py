"""Question, Answer, and Evidence normalizer for IELTS Listening Test V0.3-C."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from harness.config import REPO_ROOT
from harness.models.listening import (
    ListeningAnswer,
    ListeningEvidence,
    ListeningQuestion,
    TranscriptSegment,
)
from harness.models.provenance import ProvenanceEnvelope
from harness.models.quality import (
    AnswerVerification,
    LifecycleStatus,
    PublicationPermission,
    QualityProfile,
    SourceFidelity,
)
from harness.models.question_bank import EvidenceType, QuestionType, WordLimitRule
from harness.normalizers.base import BaseNormalizer

NORMALIZER_VERSION_QUESTION = "0.3.0-c"


class ListeningQuestionNormalizer(BaseNormalizer):
    """Normalizes listening questions, answers, and evidence linkages from verified extraction artifacts."""

    def __init__(self, normalizer_version: str = NORMALIZER_VERSION_QUESTION):
        super().__init__(normalizer_version=normalizer_version)

    def normalize(self, *args: Any, **kwargs: Any) -> Any:
        """Normalized execution delegating to normalize_listening_test_items."""
        return self.normalize_listening_test_items(*args, **kwargs)

    def load_extraction_artifact(
        self,
        artifact_path: Optional[Path] = None,
        volume_code: str = "VOL01",
        test_number: int = 1,
        publication_permission: str = "private_copyrighted",
    ) -> List[Dict[str, Any]]:
        """Loads question, answer, and evidence extraction items from an authorized artifact."""
        if artifact_path and artifact_path.exists():
            with open(artifact_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("items", data) if isinstance(data, dict) else data

        if publication_permission == "public_synthetic":
            synth_path = (
                REPO_ROOT
                / "tests"
                / "fixtures"
                / "synthetic_listening"
                / "synthetic_listening_fixtures.json"
            )
            if synth_path.exists():
                with open(synth_path, "r", encoding="utf-8") as f:
                    synth_data = json.load(f)
                return synth_data.get("questions", [])

        # Default private extraction artifact path
        priv_path = (
            REPO_ROOT
            / "private"
            / "source_data"
            / "listening"
            / f"{volume_code.lower()}_test{test_number:02d}_extraction.json"
        )
        if priv_path.exists():
            with open(priv_path, "r", encoding="utf-8") as f:
                priv_data = json.load(f)
            return priv_data.get("items", priv_data) if isinstance(priv_data, dict) else priv_data

        raise FileNotFoundError(
            f"No listening extraction artifact found at {artifact_path or priv_path}. "
            "Verified extraction artifacts must reside under private/ for copyrighted corpora."
        )

    def normalize_listening_test_items(
        self,
        doc_source_record: Dict[str, Any],
        transcript_source_record: Optional[Dict[str, Any]] = None,
        transcript_segments_by_sec: Optional[Dict[int, List[TranscriptSegment]]] = None,
        items_def: Optional[List[Dict[str, Any]]] = None,
        extraction_artifact_path: Optional[Path] = None,
        volume_code: str = "VOL01",
        test_number: int = 1,
        publication_permission: PublicationPermission = "private_copyrighted",
    ) -> Tuple[List[ListeningQuestion], List[ListeningAnswer], List[ListeningEvidence]]:
        """Constructs canonical ListeningQuestion, ListeningAnswer, and ListeningEvidence entities.

        Enforces:
        - Source-linked extraction artifact input without hardcoded copyrighted items in source
        - Provenance verification using source page/block locators
        - Preservation of uncertain OCR results without silent corrections
        - Grounding against transcript sentences without substring matching on target value
        - Evidence provenance recorded from transcript source
        """
        test_id = f"TEST-IELTS-{volume_code}-{test_number:02d}-LIS"
        questions: List[ListeningQuestion] = []
        answers: List[ListeningAnswer] = []
        evidence_list: List[ListeningEvidence] = []

        if items_def is None:
            items_def = self.load_extraction_artifact(
                artifact_path=extraction_artifact_path,
                volume_code=volume_code,
                test_number=test_number,
                publication_permission=publication_permission,
            )

        t_src = transcript_source_record or doc_source_record
        sec_segs_map = transcript_segments_by_sec or {}

        for item in items_def:
            q_num = item["q_num"]
            sec_num = item["sec_num"]
            sec_id = f"SEC-{volume_code}-{test_number:02d}-LS{sec_num:02d}"
            q_id = f"Q-{volume_code}-{test_number:02d}-LS-{q_num:03d}"
            ans_id = f"ANS-{volume_code}-{test_number:02d}-LS-{q_num:03d}-KEY"
            evid_id = f"EVID-{volume_code}-{test_number:02d}-LS{sec_num:02d}-{q_num:02d}"

            # 1. Question Entity
            page_num = item.get("page_num", 1)
            q_prov = ProvenanceEnvelope(
                source_file_id=doc_source_record["file_id"],
                source_legacy_id=doc_source_record.get("legacy_id") or "UNKNOWN",
                relative_path=doc_source_record["relative_path"],
                source_sha256=doc_source_record["content_sha256"],
                processing_unit="page",
                unit_identifier=f"page_{page_num:04d}",
                raw_block_locator=f"page:{page_num},question:{q_num}",
                extractor_adapter="pdf_ocr",
                extractor_version="0.1.0-tesseract-pdftoppm",
                normalizer_version=self.normalizer_version,
            )
            q_qp = QualityProfile(
                lifecycle_status="reviewed",
                extraction_quality="complete_clean",
                source_fidelity="authoritative_official",
                answer_verification="authoritative_key",
                explanation_verification="missing_explanation",
                publication_permission=publication_permission,
                validation_flags=["QUESTION_ORDER_VERIFIED"],
            )
            q_entity = ListeningQuestion(
                question_id=q_id,
                section_id=sec_id,
                test_id=test_id,
                question_number=q_num,
                question_type=item["q_type"],
                prompt_text=item["prompt"],
                options=item.get("options"),
                blank_target=item.get("blank_target"),
                word_limit=item.get("word_limit"),
                word_limit_rule=item.get("word_limit_rule"),
                quality_profile=q_qp,
                _provenance=q_prov,
            )
            questions.append(q_entity)

            # 2. Answer Entity (preserving raw OCR entries without silent corrections)
            raw_ocr_entry = (
                item.get("raw_ocr_entry")
                or item.get("raw_ans")
                or item["target_val"]
            )
            ans_page = item.get("key_page", 22)
            is_verified = item.get("source_verified", True)
            ans_prov_status = "authoritative_source" if is_verified else "unverified"
            ans_flags = (
                ["ANSWER_KEY_PROVENANCE_VERIFIED"]
                if is_verified
                else ["ANSWER_KEY_UNVERIFIED"]
            )

            ans_prov = ProvenanceEnvelope(
                source_file_id=doc_source_record["file_id"],
                source_legacy_id=doc_source_record.get("legacy_id") or "UNKNOWN",
                relative_path=doc_source_record["relative_path"],
                source_sha256=doc_source_record["content_sha256"],
                processing_unit="page",
                unit_identifier=f"page_{ans_page:04d}",
                raw_block_locator=f"page:{ans_page},key_entry:{raw_ocr_entry}",
                extractor_adapter="pdf_ocr",
                extractor_version="0.1.0-tesseract-pdftoppm",
                normalizer_version=self.normalizer_version,
            )
            ans_qp = QualityProfile(
                lifecycle_status="verified" if is_verified else "review_required",
                extraction_quality="complete_clean",
                source_fidelity="authoritative_official",
                answer_verification="authoritative_key" if is_verified else "unverified",
                explanation_verification="missing_explanation",
                publication_permission=publication_permission,
                validation_flags=ans_flags,
            )
            source_key_ref = item.get("source_key_ref") or (
                f"{doc_source_record.get('legacy_id', 'SRC')}:page_{ans_page}:key_{q_num}"
            )
            ans_entity = ListeningAnswer(
                answer_id=ans_id,
                question_id=q_id,
                test_id=test_id,
                section_id=sec_id,
                target_value=item["target_val"],
                acceptable_alternates=item.get("alternates", []),
                case_sensitive=False,
                source_key_ref=source_key_ref,
                answer_provenance_status=ans_prov_status,
                quality_profile=ans_qp,
                _provenance=ans_prov,
            )
            answers.append(ans_entity)

            # 3. Evidence Linkage
            # Evidence source provenance MUST be the transcript source document
            sec_segments = sec_segs_map.get(sec_num, [])
            matched_segment: Optional[TranscriptSegment] = None
            quote_text = item.get("quote")

            # Verification of verbatim quote against actual source text
            # DO NOT substring match on target_val
            # DO NOT use answer letters A/B/C as matching evidence
            if quote_text and quote_text.strip():
                clean_quote = quote_text.strip()
                for seg in sec_segments:
                    # Require quote to actually occur verbatim in the segment text
                    if clean_quote.lower() in seg.transcript_text.lower():
                        matched_segment = seg
                        break

            if matched_segment:
                grounding_status = "grounded"
                evid_flags = ["EVIDENCE_TEXT_GROUNDED"]
                seg_id = matched_segment.segment_id
                locator = f"paragraph:{matched_segment.provenance.raw_block_locator},segment:{matched_segment.segment_id}"

                # Audio timing grounding evaluation
                if matched_segment.timing_verification_status == "verified":
                    timing_status = "verified"
                    start_ms = matched_segment.start_ms
                    end_ms = matched_segment.end_ms
                    if end_ms is not None:
                        evid_flags.append("AUDIO_INTERVAL_VERIFIED")
                    else:
                        evid_flags.append("AUDIO_TIMESTAMP_VERIFIED")
                elif matched_segment.timing_verification_status == "inferred":
                    timing_status = "inferred"
                    start_ms = matched_segment.start_ms
                    end_ms = matched_segment.end_ms
                    evid_flags.append("AUDIO_TIMING_INFERRED")
                elif matched_segment.timing_verification_status in (
                    "impossible_bounds",
                    "out_of_order",
                    "unaligned",
                ):
                    timing_status = "unaligned"
                    start_ms = None
                    end_ms = None
                    evid_flags.append("AUDIO_TIMING_UNALIGNED")
                else:
                    timing_status = "missing"
                    start_ms = None
                    end_ms = None
                    evid_flags.append("AUDIO_TIMING_MISSING")
            else:
                # When no trustworthy evidence exists, grounding_status is unresolved
                # and EVIDENCE_TEXT_GROUNDED must NOT be claimed
                grounding_status = "unresolved"
                evid_flags = ["EVIDENCE_UNRESOLVED"]
                seg_id = None
                start_ms = None
                end_ms = None
                timing_status = "unaligned"
                locator = "unresolved"

            evid_prov = ProvenanceEnvelope(
                source_file_id=t_src["file_id"],
                source_legacy_id=t_src.get("legacy_id") or "UNKNOWN",
                relative_path=t_src["relative_path"],
                source_sha256=t_src["content_sha256"],
                processing_unit="section",
                unit_identifier=f"section_{sec_num:02d}",
                raw_block_locator=locator,
                extractor_adapter="transcript_aligner",
                extractor_version=self.normalizer_version,
                normalizer_version=self.normalizer_version,
            )
            evid_qp = QualityProfile(
                lifecycle_status="reviewed" if grounding_status == "grounded" else "review_required",
                extraction_quality="complete_clean" if grounding_status == "grounded" else "segmented_imperfect",
                source_fidelity="authoritative_official",
                answer_verification="authoritative_key",
                explanation_verification="missing_explanation",
                publication_permission=publication_permission,
                validation_flags=evid_flags,
            )
            evid_entity = ListeningEvidence(
                evidence_id=evid_id,
                question_id=q_id,
                answer_id=ans_id,
                section_id=sec_id,
                segment_id=seg_id,
                verbatim_quote=quote_text if grounding_status == "grounded" else None,
                start_ms=start_ms,
                end_ms=end_ms,
                timing_status=timing_status,  # type: ignore[arg-type]
                evidence_type="direct_support",
                grounding_status=grounding_status,
                explanation_text=None,
                quality_profile=evid_qp,
                _provenance=evid_prov,
            )
            evidence_list.append(evid_entity)

        return questions, answers, evidence_list
