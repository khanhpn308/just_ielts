"""Answer key reconciler and normalizer for IELTS Data Harness V0.2."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from harness.models.provenance import ProvenanceEnvelope
from harness.models.quality import AnswerVerification, LifecycleStatus, QualityProfile
from harness.models.question_bank import IELTSAnswer, IELTSQuestion
from harness.normalizers.base import (
    NORMALIZER_VERSION,
    SCHEMA_VERSION,
    BaseNormalizer,
)

# Known OCR typo mappings to canonical corrections
OCR_CORRECTIONS: Dict[str, str] = {
    "fraudulant": "fraudulent",
    "fals": "FALSE",
    "tru": "TRUE",
}


def normalize_answer_value(raw_val: str) -> Tuple[Optional[str], List[str], List[str]]:
    """Normalizes raw answer text into canonical target value, acceptable alternates, and flags.

    Enforces strict distinction between FALSE and NOT GIVEN.
    Does not guess missing values.
    """
    if raw_val is None:
        return None, [], ["MISSING_SOURCE_ANSWER_KEY"]

    val = raw_val.strip()
    if not val:
        return None, [], ["MISSING_SOURCE_ANSWER_KEY"]

    flags = []
    upper = val.upper()

    # Boolean True / False / Not Given
    if upper in {"TRUE", "T"}:
        return "TRUE", ["T"], []
    if upper in {"FALSE", "F"}:
        return "FALSE", ["F"], []
    if upper in {"NOT GIVEN", "NOTGIVEN", "NOT-GIVEN", "NG", "NGV"}:
        return "NOT GIVEN", ["NG"], []
    if upper in {"YES", "Y"}:
        return "YES", ["Y"], []
    if upper in {"NO", "N"}:
        return "NO", ["N"], []

    # OCR Typo remediation
    lower = val.lower()
    if lower in OCR_CORRECTIONS:
        corrected = OCR_CORRECTIONS[lower]
        flags.append("OCR_TYPO_CORRECTED")
        return corrected, [val], flags

    # General completion / text answers
    return val, [], flags


class AnswerReconciler(BaseNormalizer):
    """Reconciles raw heterogeneous answer keys against question entities."""

    def __init__(self, normalizer_version: str = NORMALIZER_VERSION):
        super().__init__(normalizer_version=normalizer_version)

    def parse_pdf_ocr_explanation_keys(
        self, pages: List[Dict[str, Any]]
    ) -> Dict[int, Dict[str, Any]]:
        """Parses answer keys from PDF explanation guides (e.g. SRC-137 pages)."""
        combined_text = "\n\n".join(
            p.get("content", {}).get("text", "") for p in pages
        )
        answers: Dict[int, Dict[str, Any]] = {}

        # 1. Look for 'Methods course.\n\nAnswer: False' (Question 2 on page 1)
        m2 = re.search(r"Methods\s+course\.\s*\n+Answer:\s*([^\n\r]+)", combined_text)
        if m2:
            answers[2] = {
                "raw_val": m2.group(1).strip().split()[0],
                "source_ref": "Page 95, Top Item (Methods course)",
                "raw_block": "line:Answer_Q2",
            }

        # 2. Look for Question 3: '3. ... Answer: Not Given'
        m3 = re.search(r"3[\.\s][\s\S]*?Answer:\s*([^\n\r]+)", combined_text)
        if m3:
            raw = m3.group(1).strip()
            # If line has words like 'Not Given', capture it
            if "Not Given" in raw or "NOT GIVEN" in raw:
                raw = "Not Given"
            answers[3] = {
                "raw_val": raw,
                "source_ref": "Page 95, Question 3",
                "raw_block": "line:Answer_Q3",
            }

        # 3. Look for Question 4: '4, ... Answer: True'
        m4 = re.search(r"4[\,\.\s][\s\S]*?Answer:\s*([^\n\r]+)", combined_text)
        if m4:
            answers[4] = {
                "raw_val": m4.group(1).strip().split()[0],
                "source_ref": "Page 95, Question 4",
                "raw_block": "line:Answer_Q4",
            }

        # 4. Look for Question 5: '5. ... Answer: False'
        m5 = re.search(r"5[\.\s\-—]+[\s\S]*?Answer:\s*([^\n\r]+)", combined_text)
        if m5:
            answers[5] = {
                "raw_val": m5.group(1).strip().split()[0],
                "source_ref": "Page 96, Question 5",
                "raw_block": "line:Answer_Q5",
            }

        # 5. Look for Question 6: 'Answer: True\n\nLocation: Students wishing to take a course'
        m6 = re.search(
            r"Answer:\s*([^\n\r]+)\s*\n+Location:\s*Students\s+wishing\s+to\s+take\s+a\s+course",
            combined_text,
        )
        if m6:
            answers[6] = {
                "raw_val": m6.group(1).strip().split()[0],
                "source_ref": "Page 96, Question 6",
                "raw_block": "line:Answer_Q6",
            }

        # 6. Look for note completion items (Questions 7-10)
        # e.g. 'considered 7 Fraudulant', 'in 8 museums', 'when 9 Cubism started', 'as 10 cinema'
        for q_num in [7, 8, 9, 10]:
            m_note = re.search(rf"\b{q_num}\s+([A-Za-z]+)", combined_text)
            if m_note:
                answers[q_num] = {
                    "raw_val": m_note.group(1).strip(),
                    "source_ref": f"Page 96, Note item {q_num}",
                    "raw_block": f"line:Note_Q{q_num}",
                }

        return answers

    def reconcile_answers(
        self,
        questions: List[IELTSQuestion],
        raw_key_map: Dict[int, Dict[str, Any]],
        source_record: Dict[str, Any],
        volume_code: str = "VOL06",
        test_number: int = 5,
        publication_permission: str = "private_copyrighted",
    ) -> List[IELTSAnswer]:
        """Reconciles answer keys for a list of questions, generating IELTSAnswer entities."""
        answers: List[IELTSAnswer] = []

        for q in questions:
            q_num = q.question_number
            ans_id = f"ANS-{volume_code}-{test_number:02d}-RD-{q_num:03d}-KEY"

            if q_num in raw_key_map:
                key_info = raw_key_map[q_num]
                target_val, alternates, flags = normalize_answer_value(key_info["raw_val"])
                source_ref = key_info.get("source_ref", f"Question {q_num} Answer Key")
                raw_block = key_info.get("raw_block", f"key_index:{q_num}")

                qp = QualityProfile(
                    lifecycle_status="reviewed" if not flags else "review_required",
                    extraction_quality="complete_clean" if "OCR_TYPO_CORRECTED" not in flags else "ocr_noisy",
                    source_fidelity="secondary_reputable" if "SRC-137" in source_record.get("legacy_id", "") else "authoritative_official",
                    answer_verification="authoritative_key",
                    explanation_verification="source_provided",
                    publication_permission=publication_permission,  # type: ignore[arg-type]
                    validation_flags=flags,
                )
            else:
                # Key is missing in source
                target_val = None
                alternates = []
                flags = ["MISSING_SOURCE_ANSWER_KEY"]
                source_ref = "Missing in source answer key document"
                raw_block = f"missing_key:{q_num}"

                qp = QualityProfile(
                    lifecycle_status="review_required",
                    extraction_quality="truncated_missing_pages",
                    source_fidelity="secondary_reputable" if "SRC-137" in source_record.get("legacy_id", "") else "authoritative_official",
                    answer_verification="missing_key",
                    explanation_verification="missing_explanation",
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
                unit_identifier="page_0001",
                raw_block_locator=raw_block,
                extractor_adapter="pdf_ocr",
                extractor_version="0.1.0-tesseract-pdftoppm",
                normalizer_version=self.normalizer_version,
                canonical_content_sha256=None,
                normalized_at=None,
            )

            ans_entity = IELTSAnswer(
                answer_id=ans_id,
                question_id=q.question_id,
                target_value=target_val,
                acceptable_alternates=alternates,
                case_sensitive=False,
                source_key_ref=source_ref,
                quality_profile=qp,
                _provenance=prov,
            )
            answers.append(ans_entity)

        # Handle orphaned answer keys (keys present in raw_key_map with no corresponding question)
        matched_q_nums = {q.question_number for q in questions}
        for k_num, key_info in raw_key_map.items():
            if k_num not in matched_q_nums:
                ans_id = f"ANS-{volume_code}-{test_number:02d}-RD-{k_num:03d}-KEY"
                target_val, alternates, flags = normalize_answer_value(key_info["raw_val"])
                flags.append("ORPHAN_ANSWER_KEY_UNLINKED")

                qp = QualityProfile(
                    lifecycle_status="review_required",
                    extraction_quality="complete_clean",
                    source_fidelity="authoritative_official",
                    answer_verification="unverified",
                    explanation_verification="missing_explanation",
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
                    unit_identifier="page_0001",
                    raw_block_locator=key_info.get("raw_block", f"orphan_key:{k_num}"),
                    extractor_adapter="pdf_ocr",
                    extractor_version="0.1.0-tesseract-pdftoppm",
                    normalizer_version=self.normalizer_version,
                    canonical_content_sha256=None,
                    normalized_at=None,
                )
                ans_entity = IELTSAnswer(
                    answer_id=ans_id,
                    question_id=None,
                    target_value=target_val,
                    acceptable_alternates=alternates,
                    case_sensitive=False,
                    source_key_ref=key_info.get("source_ref", f"Orphan Key {k_num}"),
                    quality_profile=qp,
                    _provenance=prov,
                )
                answers.append(ans_entity)

        return answers

    def normalize(self, *args: Any, **kwargs: Any) -> Any:
        return self.reconcile_answers(*args, **kwargs)
