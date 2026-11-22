"""Reading PDF normalizer for IELTS Data Harness V0.2 & V0.3."""

from __future__ import annotations

from dataclasses import dataclass
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
)


@dataclass
class PageLine:
    """Represents a text line associated with its source page metadata."""

    page_idx: int
    page_num: int
    is_ocr: bool
    line_idx: int
    text: str


def _find_test_in_line(text: str) -> Optional[int]:
    """Detects explicit Test boundary declaration in a line."""
    m = re.match(r"^\s*(?:READING\s+)?TEST\s+(\d+)\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(?:READING\s+)?TEST\s+(\d+)\b", text, re.IGNORECASE)
    if m and len(text.split()) <= 6:
        return int(m.group(1))
    return None


def _find_passage_in_line(text: str) -> Optional[int]:
    """Detects explicit Reading Passage boundary declaration in a line."""
    m = re.match(r"^\s*(?:READING\s+)?PASSAGE\s+(\d+)\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"\bREADING\s+PASSAGE\s+(\d+)\b", text, re.IGNORECASE)
    if m and len(text.split()) <= 6:
        return int(m.group(1))
    return None


class PdfReadingNormalizer(BaseNormalizer):
    """Normalizes raw PDF extractions (text streams or OCR pages) into canonical Reading entities."""

    def __init__(self, normalizer_version: str = NORMALIZER_VERSION):
        super().__init__(normalizer_version=normalizer_version)
        self.unresolved_questions: List[Dict[str, Any]] = []

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

        Returns dict containing 'test', 'passage', 'groups', 'questions', and 'unresolved_questions'.
        """
        if not pages:
            raise ValueError("No pages provided for PDF normalization.")

        self.unresolved_questions = []

        # 1. Structure lines with page tracking
        all_lines: List[PageLine] = []
        for p_idx, page in enumerate(pages):
            content = page.get("content", {})
            p_num = (
                content.get("page_number")
                or (page.get("provenance") or {}).get("page_number")
                or page.get("page_number")
                or (p_idx + 1)
            )
            is_ocr_page = bool(content.get("ocr_applied", False))
            raw_text = content.get("text", "")
            for l_idx, line in enumerate(raw_text.splitlines()):
                line_str = line.strip()
                if line_str:
                    all_lines.append(
                        PageLine(
                            page_idx=p_idx,
                            page_num=int(p_num),
                            is_ocr=is_ocr_page,
                            line_idx=l_idx,
                            text=line_str,
                        )
                    )

        if not all_lines:
            raise ValueError("No text lines available in PDF pages.")

        # 2. Validate Test identity and boundaries
        test_markers: List[Tuple[int, int, int]] = []  # (test_num, line_index, page_num)
        for idx, pl in enumerate(all_lines):
            t_val = _find_test_in_line(pl.text)
            if t_val is not None:
                test_markers.append((t_val, idx, pl.page_num))

        detected_tests: List[int] = []
        for t_val, _, _ in test_markers:
            if t_val not in detected_tests:
                detected_tests.append(t_val)

        if detected_tests:
            if test_number not in detected_tests:
                raise ValueError(
                    f"Requested Test {test_number} not found in PDF page boundaries. Detected tests: {detected_tests}"
                )
        else:
            # Check source metadata or page provenance
            meta_test: Optional[int] = None
            if source_record:
                if "test_number" in source_record and source_record["test_number"] is not None:
                    meta_test = int(source_record["test_number"])
                else:
                    fn = source_record.get("filename") or source_record.get("relative_path") or ""
                    m_fn = re.search(r"\bTEST[_\s]*(\d+)\b", fn, re.IGNORECASE)
                    if m_fn:
                        meta_test = int(m_fn.group(1))

            if meta_test is None:
                for p in pages:
                    prov_path = (p.get("provenance") or {}).get("relative_path", "")
                    m_p = re.search(r"\bTEST[_\s]*(\d+)\b", prov_path, re.IGNORECASE)
                    if m_p:
                        meta_test = int(m_p.group(1))
                        break

            if meta_test is not None:
                if meta_test != test_number:
                    raise ValueError(
                        f"Requested Test {test_number} does not match source metadata Test {meta_test}"
                    )
            elif (
                source_record
                and (
                    source_record.get("collection") == "synthetic"
                    or "synthetic" in str(source_record.get("relative_path", ""))
                    or "synthetic" in str(source_record.get("file_id", ""))
                )
                and test_number == 1
            ):
                # Standalone single-test synthetic fixture defaulting to Test 1
                pass
            else:
                raise ValueError(
                    f"Ambiguous or unverified Test identity for requested Test {test_number}: "
                    "PDF pages contain no identifiable test boundaries or trustworthy metadata."
                )

        # 3. Strictly isolate lines for requested Test
        if test_markers:
            test_start_idx = min(idx for (t_val, idx, _) in test_markers if t_val == test_number)
            subsequent_tests = [
                idx for (t_val, idx, _) in test_markers if idx > test_start_idx and t_val != test_number
            ]
            test_end_idx = min(subsequent_tests) if subsequent_tests else len(all_lines)
            test_lines = all_lines[test_start_idx:test_end_idx]
        else:
            test_lines = all_lines

        # 4. Strictly isolate lines for requested Passage within the Test
        passage_markers: List[Tuple[int, int, int]] = []  # (pass_num, line_index, page_num)
        for idx, pl in enumerate(test_lines):
            p_val = _find_passage_in_line(pl.text)
            if p_val is not None:
                passage_markers.append((p_val, idx, pl.page_num))

        detected_passages: List[int] = []
        for p_val, _, _ in passage_markers:
            if p_val not in detected_passages:
                detected_passages.append(p_val)

        if detected_passages:
            if passage_number not in detected_passages:
                raise ValueError(
                    f"Reading Passage {passage_number} not found for Test {test_number}. "
                    f"Detected passages: {detected_passages}"
                )
            pass_start_idx = min(idx for (p_val, idx, _) in passage_markers if p_val == passage_number)
            subsequent_passages = [
                idx for (p_val, idx, _) in passage_markers if idx > pass_start_idx and p_val != passage_number
            ]
            pass_end_idx = min(subsequent_passages) if subsequent_passages else len(test_lines)
            passage_lines = test_lines[pass_start_idx:pass_end_idx]
        else:
            if passage_number == 1:
                passage_lines = test_lines
            else:
                raise ValueError(
                    f"Reading Passage {passage_number} not found for Test {test_number}: "
                    "document contains no passage boundary markers."
                )

        # 5. Extract and validate passage narrative text without unsafe splitting or padding
        q_start: Optional[int] = None
        for i, pl in enumerate(passage_lines):
            if re.match(r"^\s*Questions?(?:\s+\d+|\s*$|\s*:)", pl.text, re.IGNORECASE):
                q_start = i
                break

        if q_start is None:
            raise ValueError(
                f"No question marker found in passage content for Test {test_number} Passage {passage_number}. "
                "Document splitting fallback is prohibited."
            )

        title_idx = 0
        for i in range(min(4, q_start)):
            t = passage_lines[i].text
            if (
                not _find_test_in_line(t)
                and not _find_passage_in_line(t)
                and not re.match(r"^\s*You\s+should\s+spend", t, re.IGNORECASE)
            ):
                title_idx = i
                break

        title = passage_lines[title_idx].text
        body_line_objs = passage_lines[title_idx + 1:q_start]
        body_lines = [pl.text for pl in body_line_objs if pl.text]

        narrative_text = "\n\n".join(body_lines).strip()
        if not narrative_text:
            raise ValueError("No reading passage narrative body text found in PDF pages.")

        if len(narrative_text) < 100 or len(narrative_text.split()) < 50:
            raise ValueError(
                f"Extracted passage narrative text is insufficient or truncated "
                f"({len(narrative_text)} chars, {len(narrative_text.split())} words; "
                f"minimum 100 chars and 50 words required). Text padding is prohibited."
            )

        para_items: List[ParagraphItem] = []
        curr_offset = 0
        for seq_i, line in enumerate(body_lines):
            if seq_i > 0:
                curr_offset += 2
            p_start = curr_offset
            p_end = p_start + len(line)
            curr_offset = p_end
            label_match = re.match(r"^([A-Z])\s+", line)
            label = label_match.group(1) if label_match else str(seq_i + 1)
            para_items.append(
                ParagraphItem(
                    label=label,
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

        # 6. Parse question group range without inventing fallback ranges
        group_header_line = passage_lines[q_start]
        group_header = group_header_line.text
        m_range = re.search(r"Questions?\s+(\d+)\s*(?:-|–|—|to)\s*(\d+)", group_header, re.IGNORECASE)
        if m_range:
            start_q = int(m_range.group(1))
            end_q = int(m_range.group(2))
        else:
            m_single = re.search(r"Question\s+(\d+)\b", group_header, re.IGNORECASE)
            if m_single:
                start_q = end_q = int(m_single.group(1))
            else:
                raise ValueError(
                    f"Could not determine question range from group header: {group_header!r}. "
                    "Invented question-group ranges are prohibited."
                )

        instruction_lines: List[str] = []
        item_lines_start = len(passage_lines)
        for idx in range(q_start + 1, len(passage_lines)):
            l_text = passage_lines[idx].text
            if re.match(r"^(?:Question\s+)?\d+[\.\s\:\)]", l_text, re.IGNORECASE):
                item_lines_start = idx
                break
            instruction_lines.append(l_text)

        has_source_instructions = len(instruction_lines) > 0
        if has_source_instructions:
            instruction_text = " ".join(instruction_lines).strip()
        else:
            # Never present fabricated default instructions as source!
            instruction_text = group_header

        detected_qtype = detect_question_type_from_instructions(instruction_text)
        q_type: QuestionType = detected_qtype or "true-false-not-given"
        word_limit = detect_word_limit_rule(instruction_text)

        test_id = f"TEST-IELTS-{volume_code}-{test_number:02d}-{'ACAD' if track == 'academic' else 'GT'}"
        passage_id = f"PASSAGE-{volume_code}-{test_number:02d}-RD{passage_number:02d}"
        group_id = f"QG-{volume_code}-{test_number:02d}-RD{passage_number:02d}-G01"

        # 7. Parse question items strictly from isolated candidate lines
        candidate_q_lines = passage_lines[item_lines_start:] if item_lines_start < len(passage_lines) else []
        questions: List[IELTSQuestion] = []

        for q_num in range(start_q, end_q + 1):
            q_id = f"Q-{volume_code}-{test_number:02d}-RD-{q_num:03d}"
            matched_prompt: Optional[str] = None
            matched_line_obj: Optional[PageLine] = None

            for cand_line in candidate_q_lines:
                m_item = re.match(rf"^(?:Question\s+)?{q_num}[\.\s\:\)](.*)", cand_line.text, re.IGNORECASE)
                if m_item:
                    extracted = m_item.group(1).strip()
                    if len(extracted) >= 3:
                        matched_prompt = extracted
                        matched_line_obj = cand_line
                        break

            if not matched_prompt or matched_line_obj is None:
                # Do NOT publish fabricated fallback prompts!
                self.unresolved_questions.append({
                    "question_id": q_id,
                    "group_id": group_id,
                    "passage_id": passage_id,
                    "question_number": q_num,
                    "question_type": q_type,
                    "error": "UNRESOLVED_QUESTION_PROMPT",
                    "note": f"Could not match question prompt text for question {q_num} in group {group_id}",
                    "lifecycle_status": "review_required",
                })
                continue

            q_prov = self._make_provenance(
                source_record=source_record,
                raw_block_locator=f"page:{matched_line_obj.page_num}:line:{matched_line_obj.line_idx}",
                unit_identifier=f"page_{matched_line_obj.page_num:04d}",
                is_ocr=matched_line_obj.is_ocr,
            )
            q_status = "review_required" if matched_line_obj.is_ocr else "extracted"
            q_qp = QualityProfile(
                lifecycle_status=q_status,  # type: ignore[arg-type]
                extraction_quality="ocr_noisy" if matched_line_obj.is_ocr else "complete_clean",
                source_fidelity="authoritative_official",
                answer_verification="unverified",
                explanation_verification="source_provided",
                publication_permission=publication_permission,  # type: ignore[arg-type]
                validation_flags=["OCR_EXTRACTION_SOURCE"] if matched_line_obj.is_ocr else [],
            )
            questions.append(
                IELTSQuestion(
                    question_id=q_id,
                    group_id=group_id,
                    passage_id=passage_id,
                    question_number=q_num,
                    question_type=q_type,
                    prompt_text=matched_prompt,
                    options=None,
                    blank_target=None,
                    linked_principle_ids=["RD-TFNG-001"] if q_type == "true-false-not-given" else [],
                    quality_profile=q_qp,
                    _provenance=q_prov,
                )
            )

        # 8. Build accurate page-isolated Provenance and truthful QualityProfiles
        test_page_nums = sorted(list(set(pl.page_num for pl in test_lines)))
        test_p_min, test_p_max = test_page_nums[0], test_page_nums[-1]
        test_locator = (
            f"page:{test_p_min}"
            if test_p_min == test_p_max
            else f"page_range:{test_p_min}-{test_p_max}"
        )

        passage_page_nums = sorted(list(set(pl.page_num for pl in passage_lines)))
        pass_p_min, pass_p_max = passage_page_nums[0], passage_page_nums[-1]
        pass_locator = (
            f"page:{pass_p_min}"
            if pass_p_min == pass_p_max
            else f"page_range:{pass_p_min}-{pass_p_max}"
        )

        is_ocr = any(pl.is_ocr for pl in passage_lines)
        extraction_q = "ocr_noisy" if is_ocr else "complete_clean"

        has_unresolved = len(self.unresolved_questions) > 0
        val_flags: List[str] = []
        if is_ocr:
            val_flags.append("OCR_EXTRACTION_SOURCE")
        if has_unresolved:
            val_flags.append("UNRESOLVED_QUESTIONS")
        if not has_source_instructions:
            val_flags.append("MISSING_INSTRUCTION_TEXT")

        needs_review = is_ocr or has_unresolved or not has_source_instructions
        overall_lifecycle = "review_required" if needs_review else "reviewed"
        passage_lifecycle = "review_required" if needs_review else "extracted"

        test_prov = self._make_provenance(
            source_record=source_record,
            raw_block_locator=test_locator,
            unit_identifier=f"page_{test_p_min:04d}",
            is_ocr=is_ocr,
        )
        test_qp = QualityProfile(
            lifecycle_status=overall_lifecycle,  # type: ignore[arg-type]
            extraction_quality=extraction_q,
            source_fidelity="authoritative_official",
            answer_verification="unverified",
            explanation_verification="source_provided",
            publication_permission=publication_permission,  # type: ignore[arg-type]
            validation_flags=list(val_flags),
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

        passage_prov = self._make_provenance(
            source_record=source_record,
            raw_block_locator=pass_locator,
            unit_identifier=f"page_{pass_p_min:04d}",
            is_ocr=is_ocr,
        )
        passage_qp = QualityProfile(
            lifecycle_status=passage_lifecycle,  # type: ignore[arg-type]
            extraction_quality=extraction_q,
            source_fidelity="authoritative_official",
            answer_verification="unverified",
            explanation_verification="source_provided",
            publication_permission=publication_permission,  # type: ignore[arg-type]
            validation_flags=list(val_flags),
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

        group_prov = self._make_provenance(
            source_record=source_record,
            raw_block_locator=f"page:{group_header_line.page_num}:line:{group_header_line.line_idx}",
            unit_identifier=f"page_{group_header_line.page_num:04d}",
            is_ocr=is_ocr,
        )
        group_qp = QualityProfile(
            lifecycle_status=overall_lifecycle,  # type: ignore[arg-type]
            extraction_quality=extraction_q,
            source_fidelity="authoritative_official",
            answer_verification="unverified",
            explanation_verification="source_provided",
            publication_permission=publication_permission,  # type: ignore[arg-type]
            validation_flags=list(val_flags),
        )
        q_group = QuestionGroup(
            group_id=group_id,
            passage_id=passage_id,
            start_question_number=start_q,
            end_question_number=end_q,
            question_type=q_type,
            instruction_text=instruction_text,
            word_limit_rule=word_limit,
            shared_options=None,
            quality_profile=group_qp,
            _provenance=group_prov,
        )

        return {
            "test": test_entity,
            "passage": passage_entity,
            "groups": [q_group],
            "questions": questions,
            "unresolved_questions": list(self.unresolved_questions),
        }

    def _make_provenance(
        self,
        source_record: Dict[str, Any],
        raw_block_locator: str,
        unit_identifier: str = "page_0001",
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
            unit_identifier=unit_identifier,
            raw_block_locator=raw_block_locator,
            extractor_adapter=adapter,
            extractor_version=version,
            normalizer_version=self.normalizer_version,
            canonical_content_sha256=None,
            normalized_at=None,
        )
