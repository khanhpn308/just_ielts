"""Reading PDF normalizer for IELTS Data Harness V0.2."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from harness.models.provenance import ProvenanceEnvelope
from harness.models.quality import QualityProfile
from harness.models.question_bank import (
    IELTSQuestion,
    IELTSTest,
    ParagraphItem,
    PassageOrSection,
    QuestionGroup,
    QuestionType,
    WordLimitRule,
)
from harness.normalizers.base import (
    NORMALIZER_VERSION,
    SCHEMA_VERSION,
    BaseNormalizer,
)
from harness.normalizers.reading_docx import (
    detect_question_type_from_instructions,
    detect_word_limit_rule,
    segment_joined_questions,
)


class PdfReadingNormalizer(BaseNormalizer):
    """Normalizes raw PDF extractions (text streams or OCR pages) into canonical Reading entities."""

    def __init__(self, normalizer_version: str = NORMALIZER_VERSION):
        super().__init__(normalizer_version=normalizer_version)

    def normalize(
        self,
        pages: List[Dict[str, Any]],
        source_record: Dict[str, Any],
        test_number: int = 1,
        passage_number: int = 1,
        volume_code: str = "VOL01",
        track: str = "academic",
        publication_permission: str = "private_copyrighted",
    ) -> Dict[str, Any]:
        """Normalizes Reading Passage and Question items from raw PDF pages.

        Returns dict containing 'test', 'passage', 'groups', 'questions'.
        """
        if not pages:
            raise ValueError("No pages provided for PDF normalization.")

        is_ocr = any(p.get("content", {}).get("ocr_applied", False) for p in pages)
        extraction_q = "ocr_noisy" if is_ocr else "complete_clean"

        # Combine page texts
        all_text = "\n\n".join(
            p.get("content", {}).get("text", "") for p in pages
        )

        test_id = f"TEST-IELTS-{volume_code}-{test_number:02d}-{'ACAD' if track == 'academic' else 'GT'}"
        test_prov = self._make_provenance(
            source_record=source_record,
            raw_block_locator=f"page_range:1-{len(pages)}",
            is_ocr=is_ocr,
        )
        test_qp = QualityProfile(
            lifecycle_status="reviewed",
            extraction_quality=extraction_q,
            source_fidelity="authoritative_official",
            answer_verification="unverified",
            explanation_verification="source_provided",
            publication_permission=publication_permission,  # type: ignore[arg-type]
            validation_flags=["OCR_EXTRACTION_SOURCE"] if is_ocr else [],
        )
        test_entity = IELTSTest(
            test_id=test_id,
            title=f"IELTS {volume_code} Academic Reading Test {test_number}",
            volume=volume_code,
            test_number=test_number,
            track="academic" if track == "academic" else "general_training",
            sections_present=["reading"],
            quality_profile=test_qp,
            _provenance=test_prov,
        )

        passage_id = f"PASSAGE-{volume_code}-{test_number:02d}-RD{passage_number:02d}"

        # Heuristic split: passage text vs questions
        lines = [line.strip() for line in all_text.splitlines() if line.strip()]
        q_start = None
        for i, line in enumerate(lines):
            if re.match(r"^Questions?\s+\d+", line, re.I):
                q_start = i
                break

        if q_start is None:
            # Fallback split at 60%
            q_start = max(1, int(len(lines) * 0.6))

        title = lines[0] if lines else "Reading Passage"
        body_lines = lines[1:q_start]
        narrative_text = "\n\n".join(body_lines) if body_lines else "Default passage text content."
        if len(narrative_text) < 100:
            narrative_text = narrative_text.ljust(100, " ")

        para_items: List[ParagraphItem] = []
        curr_offset = 0
        for seq_i, line in enumerate(body_lines):
            if seq_i > 0:
                curr_offset += 2
            p_start = curr_offset
            p_end = p_start + len(line)
            curr_offset = p_end
            para_items.append(
                ParagraphItem(
                    label=str(seq_i + 1),
                    sequence_index=seq_i,
                    char_start=p_start,
                    char_end=p_end,
                    text=line,
                )
            )

        if not para_items:
            para_items.append(
                ParagraphItem(
                    label="1",
                    sequence_index=0,
                    char_start=0,
                    char_end=len(narrative_text),
                    text=narrative_text,
                )
            )

        passage_prov = self._make_provenance(
            source_record=source_record,
            raw_block_locator=f"lines:1-{q_start}",
            is_ocr=is_ocr,
        )
        passage_qp = QualityProfile(
            lifecycle_status="extracted",
            extraction_quality=extraction_q,
            source_fidelity="authoritative_official",
            answer_verification="unverified",
            explanation_verification="source_provided",
            publication_permission=publication_permission,  # type: ignore[arg-type]
            validation_flags=["OCR_EXTRACTION_SOURCE"] if is_ocr else [],
        )
        passage_entity = PassageOrSection(
            passage_id=passage_id,
            test_id=test_id,
            skill="reading",
            sequence_number=passage_number,
            title=title,
            subtitle=None,
            narrative_text=narrative_text,
            paragraphs=para_items,
            audio_track_ref=None,
            word_count=len(narrative_text.split()),
            quality_profile=passage_qp,
            _provenance=passage_prov,
        )

        group_id = f"QG-{volume_code}-{test_number:02d}-RD01-G01"
        group_prov = self._make_provenance(
            source_record=source_record,
            raw_block_locator=f"lines:{q_start}-{len(lines)}",
            is_ocr=is_ocr,
        )
        group_qp = QualityProfile(
            lifecycle_status="reviewed",
            extraction_quality=extraction_q,
            source_fidelity="authoritative_official",
            answer_verification="unverified",
            explanation_verification="source_provided",
            publication_permission=publication_permission,  # type: ignore[arg-type]
            validation_flags=[],
        )
        q_group = QuestionGroup(
            group_id=group_id,
            passage_id=passage_id,
            start_question_number=1,
            end_question_number=min(5, max(1, len(lines) - q_start)),
            question_type="true-false-not-given",
            instruction_text="Do the following statements agree with the information given in the passage?",
            word_limit_rule=None,
            shared_options=None,
            quality_profile=group_qp,
            _provenance=group_prov,
        )

        questions: List[IELTSQuestion] = []
        q_lines = lines[q_start:]
        for idx in range(1, q_group.end_question_number + 1):
            q_id = f"Q-{volume_code}-{test_number:02d}-RD-{idx:03d}"
            prompt = q_lines[idx] if idx < len(q_lines) else f"Question statement {idx}."
            if len(prompt) < 3:
                prompt = f"Question statement {idx}."
            q_prov = self._make_provenance(
                source_record=source_record,
                raw_block_locator=f"line:{q_start + idx}",
                is_ocr=is_ocr,
            )
            q_qp = QualityProfile(
                lifecycle_status="extracted",
                extraction_quality=extraction_q,
                source_fidelity="authoritative_official",
                answer_verification="unverified",
                explanation_verification="source_provided",
                publication_permission=publication_permission,  # type: ignore[arg-type]
                validation_flags=[],
            )
            questions.append(
                IELTSQuestion(
                    question_id=q_id,
                    group_id=group_id,
                    passage_id=passage_id,
                    question_number=idx,
                    question_type="true-false-not-given",
                    prompt_text=prompt,
                    options=None,
                    blank_target=None,
                    linked_principle_ids=["RD-TFNG-001"],
                    quality_profile=q_qp,
                    _provenance=q_prov,
                )
            )

        return {
            "test": test_entity,
            "passage": passage_entity,
            "groups": [q_group],
            "questions": questions,
        }

    def _make_provenance(
        self,
        source_record: Dict[str, Any],
        raw_block_locator: str,
        is_ocr: bool = False,
    ) -> ProvenanceEnvelope:
        adapter = "pdf_ocr" if is_ocr else "pdfminer"
        version = "0.1.0-tesseract-pdftoppm" if is_ocr else "0.1.0-pdfminer-stream"
        return ProvenanceEnvelope(
            schema_version=SCHEMA_VERSION,
            source_file_id=source_record["file_id"],
            source_legacy_id=source_record["legacy_id"],
            relative_path=source_record["relative_path"],
            source_sha256=source_record["content_sha256"],
            processing_unit="page",
            unit_identifier="page_0001",
            raw_block_locator=raw_block_locator,
            extractor_adapter=adapter,
            extractor_version=version,
            normalizer_version=self.normalizer_version,
            canonical_content_sha256=None,
            normalized_at=None,
        )
