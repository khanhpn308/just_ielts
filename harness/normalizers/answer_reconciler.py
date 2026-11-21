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
        self,
        pages: List[Dict[str, Any]],
        test_number: Optional[int] = None,
        passage_number: Optional[int] = None,
    ) -> Dict[int, Dict[str, Any]]:
        """Parses answer keys from PDF explanation guides (e.g. SRC-137 pages).

        Preserves accurate page-level provenance, exact character offsets,
        raw matched text, and confidence indicators.
        """
        # Filter pages by test and passage if multi-passage headings are detected
        filtered_pages = pages
        has_headers = any(
            re.search(r"READING\s+PASSAGE\s+\d+", p.get("content", {}).get("text", ""), re.IGNORECASE)
            for p in pages
        )
        if has_headers and (test_number is not None or passage_number is not None):
            # Detect starting test from pages or fallback
            start_test = 1
            sample_text = pages[0].get("content", {}).get("text", "") if pages else ""
            m_test_hdr = re.search(r"TEST\s+(\d+)", sample_text, re.IGNORECASE)
            if m_test_hdr:
                start_test = int(m_test_hdr.group(1))
            else:
                prov_path = pages[0].get("provenance", {}).get("relative_path", "") if pages else ""
                m_range = re.search(r"(\d+)\s*[-–]\s*(\d+)", prov_path)
                if m_range:
                    start_test = int(m_range.group(1))
                elif test_number is not None:
                    if test_number in (5, 6):
                        start_test = 5
                    else:
                        start_test = test_number

            curr_test = start_test
            curr_pass = 1
            selected = []
            for idx, p in enumerate(pages):
                text = p.get("content", {}).get("text", "")
                m = re.search(r"READING\s+PASSAGE\s+(\d+)", text, re.IGNORECASE)
                prev_pass = curr_pass
                if m:
                    p_num = int(m.group(1))
                    if p_num == 1 and idx > 0:
                        curr_test += 1
                    curr_pass = p_num
                passages_on_page = {prev_pass, curr_pass}
                test_match = (test_number is None or curr_test == test_number)
                pass_match = (passage_number is None or passage_number in passages_on_page)
                if test_match and pass_match:
                    selected.append(p)
            if selected:
                filtered_pages = selected

        answers: Dict[int, Dict[str, Any]] = {}

        for idx, page in enumerate(filtered_pages):
            content = page.get("content", {})
            prov = page.get("provenance", {})
            page_num = content.get("page_number", idx + 1)
            unit_id = prov.get("unit_identifier") or f"page_{page_num:04d}"
            text = content.get("text", "")
            if not text:
                continue

            # If page contains a transition to another passage, restrict text to target passage
            if passage_number is not None:
                m_pass = re.search(r"READING\s+PASSAGE\s+(\d+)", text, re.IGNORECASE)
                if m_pass:
                    p_trans = int(m_pass.group(1))
                    if passage_number < p_trans:
                        text = text[:m_pass.start()]
                    elif passage_number == p_trans:
                        text = text[m_pass.start():]

            def record_answer(
                q_num: int,
                raw_val: str,
                match_obj: Any,
                confidence: float = 1.0,
            ) -> None:
                c_start, c_end = match_obj.start(), match_obj.end()
                matched_text = match_obj.group(0)
                ambiguity_flags: List[str] = []
                if q_num in answers:
                    ambiguity_flags.append("MULTIPLE_KEY_CANDIDATES")
                    answers[q_num].setdefault("ambiguity_flags", []).append("MULTIPLE_KEY_CANDIDATES")
                    # Do not overwrite existing answer if existing has higher or equal confidence
                    if answers[q_num].get("confidence", 0) >= confidence:
                        return

                answers[q_num] = {
                    "raw_val": raw_val,
                    "original_val": raw_val,
                    "unit_identifier": unit_id,
                    "page_number": page_num,
                    "char_start": c_start,
                    "char_end": c_end,
                    "raw_matched_text": matched_text,
                    "source_ref": f"{unit_id} (page {page_num}), chars {c_start}-{c_end}",
                    "raw_block": f"offset:{c_start}-{c_end}",
                    "confidence": confidence,
                    "ambiguity_flags": ambiguity_flags,
                }

            # 1. Question 2: preceding question 3
            m2 = re.search(r"(?:^|\n)[^\n]*?\n+Answer:\s*([^\n\r]+)\s*\n+(?=3[\.\s])", text)
            if m2:
                record_answer(2, m2.group(1).strip().split()[0], m2, confidence=1.0)

            # 2. Question 3: '3. ... Answer: Not Given'
            m3 = re.search(r"3[\.\s][\s\S]*?Answer:\s*([^\n\r]+)", text)
            if m3:
                raw3 = m3.group(1).strip()
                if "Not Given" in raw3 or "NOT GIVEN" in raw3:
                    raw3 = "Not Given"
                else:
                    raw3 = raw3.split()[0]
                record_answer(3, raw3, m3, confidence=1.0)

            # 3. Question 4: '4, ... Answer: True'
            m4 = re.search(r"4[\,\.\s][\s\S]*?Answer:\s*([^\n\r]+)", text)
            if m4:
                record_answer(4, m4.group(1).strip().split()[0], m4, confidence=1.0)

            # 4. Question 5: '5. ... Answer: False'
            m5 = re.search(r"5[\.\s\-—]+[\s\S]*?Answer:\s*([^\n\r]+)", text)
            if m5:
                record_answer(5, m5.group(1).strip().split()[0], m5, confidence=1.0)
                # Question 6 follows question 5 block
                m6 = re.search(r"\nAnswer:\s*([^\n\r]+)\s*\n+Location:", text[m5.end():])
                if m6:
                    c_start = m5.end() + m6.start()
                    c_end = m5.end() + m6.end()
                    ambiguity_flags: List[str] = []
                    if 6 in answers:
                        ambiguity_flags.append("MULTIPLE_KEY_CANDIDATES")
                        answers[6].setdefault("ambiguity_flags", []).append("MULTIPLE_KEY_CANDIDATES")
                    if 6 not in answers or answers[6].get("confidence", 0) < 1.0:
                        answers[6] = {
                            "raw_val": m6.group(1).strip().split()[0],
                            "original_val": m6.group(1).strip().split()[0],
                            "unit_identifier": unit_id,
                            "page_number": page_num,
                            "char_start": c_start,
                            "char_end": c_end,
                            "raw_matched_text": m6.group(0),
                            "source_ref": f"{unit_id} (page {page_num}), chars {c_start}-{c_end}",
                            "raw_block": f"offset:{c_start}-{c_end}",
                            "confidence": 1.0,
                            "ambiguity_flags": ambiguity_flags,
                        }

            # 5. Note completion items (Questions 7-10)
            note_stopwords = {"answer", "questions", "question", "most", "the", "of", "in", "and", "or", "to", "for", "with", "a", "an"}
            for q_num in [7, 8, 9, 10]:
                m_note = re.search(rf"\b{q_num}\s+([A-Za-z]+)", text)
                if m_note:
                    cand_word = m_note.group(1).strip()
                    if cand_word.lower() not in note_stopwords:
                        record_answer(q_num, cand_word, m_note, confidence=0.95)

            # 7. General fallback for standard numbered answer lines: e.g. "1. Answer: TRUE" or "1 Answer: B"
            for q_cand in range(1, 41):
                if q_cand in answers:
                    continue
                m_gen = re.search(
                    rf"(?:^|\n)\s*(?:Question\s+)?{q_cand}[\.\s\:\)]*Answer\s*[:\-]\s*([^\n\r]+)",
                    text,
                    re.IGNORECASE,
                )
                if m_gen:
                    val = m_gen.group(1).strip().split()[0]
                    record_answer(q_cand, val, m_gen, confidence=0.90)

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

            # Epistemic source authority:
            # Do not label unverified secondary keys (like SRC-137) as authoritative official keys.
            is_official = (
                source_record.get("collection") == "official_cambridge"
                or (
                    source_record.get("source_fidelity") == "authoritative_official"
                    and "SRC-137" not in source_record.get("legacy_id", "")
                )
            )
            source_fidelity: SourceFidelity = "authoritative_official" if is_official else "secondary_reputable"

            if q_num in raw_key_map:
                key_info = raw_key_map[q_num]
                target_val, alternates, norm_flags = normalize_answer_value(key_info["raw_val"])
                flags = list(norm_flags) + list(key_info.get("ambiguity_flags", []))
                source_ref = key_info.get("source_ref", f"Question {q_num} Answer Key")
                raw_block = key_info.get("raw_block", f"key_index:{q_num}")
                unit_id = key_info.get("unit_identifier", "page_0001")

                # Check for independent corroboration
                has_corroboration = bool(
                    key_info.get("corroborated")
                    or source_record.get("corroborating_sources")
                    or key_info.get("consensus_sources")
                )

                if is_official:
                    answer_verification: AnswerVerification = "authoritative_key"
                    ans_lifecycle: LifecycleStatus = "reviewed" if not flags else "review_required"
                elif has_corroboration:
                    answer_verification = "consensus_key"
                    ans_lifecycle = "reviewed" if not flags else "review_required"
                else:
                    # Single-source secondary keys cannot be labeled consensus_key without independent corroboration
                    answer_verification = "unverified"
                    ans_lifecycle = "review_required"
                    flags.append("SINGLE_SOURCE_UNVERIFIED_KEY")

                qp = QualityProfile(
                    lifecycle_status=ans_lifecycle,
                    extraction_quality="complete_clean" if "OCR_TYPO_CORRECTED" not in flags else "ocr_noisy",
                    source_fidelity=source_fidelity,
                    answer_verification=answer_verification,
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
                unit_id = "page_0001"

                qp = QualityProfile(
                    lifecycle_status="review_required",
                    extraction_quality="truncated_missing_pages",
                    source_fidelity=source_fidelity,
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
                unit_identifier=unit_id,
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
                target_val, alternates, norm_flags = normalize_answer_value(key_info["raw_val"])
                flags = list(norm_flags) + list(key_info.get("ambiguity_flags", []))
                flags.append("ORPHAN_ANSWER_KEY_UNLINKED")
                unit_id = key_info.get("unit_identifier", "page_0001")
                raw_block = key_info.get("raw_block", f"orphan_key:{k_num}")

                is_official = (
                    source_record.get("collection") == "official_cambridge"
                    or (
                        source_record.get("source_fidelity") == "authoritative_official"
                        and "SRC-137" not in source_record.get("legacy_id", "")
                    )
                )
                source_fidelity = "authoritative_official" if is_official else "secondary_reputable"

                qp = QualityProfile(
                    lifecycle_status="review_required",
                    extraction_quality="complete_clean",
                    source_fidelity=source_fidelity,
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
                    unit_identifier=unit_id,
                    raw_block_locator=raw_block,
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
