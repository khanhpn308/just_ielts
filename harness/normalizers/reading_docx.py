"""Reading DOCX normalizer for IELTS Data Harness V0.2."""

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


def segment_joined_questions(
    text: str, start_num: int, end_num: int
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Deterministic segmentation algorithm for concatenated DOCX question runs.

    Handles:
    - sentence.2 Next question (no space after period)
    - word5 Next question (no punctuation between word and digit)
    - Numbers within prompt text (e.g. 1980, 2 distinct branches, 25 percent)

    Guarantees:
    - Exact question count and strictly contiguous numbering
    - Zero text loss (period attached to preceding sentence)
    - Unresolvable sequences routed to review
    Returns (parsed_questions, diagnostic_flags).
    """
    flags = []
    expected_numbers = list(range(start_num, end_num + 1))
    positions = []
    curr = 0

    for num in expected_numbers:
        # Pattern: prefix boundary (start, punctuation, letter, space), exact number, optional period/space, lookahead uppercase
        pattern = rf"(?:^|[\.\?!a-zA-Z\s])({num})(?:[\.\s]*)(?=[A-Z])"
        match = re.search(pattern, text[curr:])
        if not match:
            flags.append("SEGMENTATION_SEQUENCE_GAP")
            return [], flags

        digit_start = curr + match.start(1)
        prompt_start = curr + match.end()
        positions.append((num, digit_start, prompt_start))
        curr = prompt_start

    res = []
    for i in range(len(positions)):
        num, _, prompt_start = positions[i]
        prompt_end = positions[i + 1][1] if i + 1 < len(positions) else len(text)
        prompt = text[prompt_start:prompt_end].strip()
        res.append({
            "number": num,
            "prompt": prompt,
            "char_start": prompt_start,
            "char_end": prompt_end,
        })

    if len(res) != (end_num - start_num + 1):
        flags.append("SEGMENTATION_COUNT_MISMATCH")

    return res, flags


def detect_question_type_from_instructions(text: str) -> QuestionType:
    """Detects IELTS question type from instruction text heuristics."""
    upper = text.upper()
    if "TRUE" in upper and "FALSE" in upper and "NOT GIVEN" in upper:
        return "true-false-not-given"
    if "YES" in upper and "NO" in upper and "NOT GIVEN" in upper:
        return "yes-no-not-given"
    if "COMPLETE THE NOTES" in upper or "NOTES BELOW" in upper:
        return "note-completion"
    if "COMPLETE THE SUMMARY" in upper or "SUMMARY BELOW" in upper:
        return "summary-completion"
    if "COMPLETE THE SENTENCES" in upper:
        return "sentence-completion"
    if "COMPLETE THE TABLE" in upper or "TABLE BELOW" in upper:
        return "table-completion"
    if "FLOW-CHART" in upper or "FLOW CHART" in upper:
        return "flow-chart-completion"
    if "DIAGRAM" in upper:
        return "diagram-label-completion"
    if "HEADING" in upper:
        return "matching-headings"
    if "WHICH PARAGRAPH CONTAINS" in upper or "MATCHING INFORMATION" in upper:
        return "matching-information"
    if "CHOOSE TWO" in upper or "CHOOSE THREE" in upper:
        return "multiple-choice-multi"
    if "CHOOSE THE CORRECT LETTER" in upper or "MULTIPLE CHOICE" in upper:
        return "multiple-choice-single"
    if "SHORT-ANSWER" in upper or "SHORT ANSWER" in upper:
        return "short-answer"
    return "note-completion"


def detect_word_limit_rule(text: str) -> Optional[WordLimitRule]:
    """Extracts word limit rule enum from instruction text."""
    upper = text.upper()
    if "ONE WORD ONLY" in upper:
        return "one_word_only"
    if "NO MORE THAN TWO WORDS AND/OR A NUMBER" in upper:
        return "no_more_than_two_words_and_or_a_number"
    if "NO MORE THAN TWO WORDS" in upper:
        return "no_more_than_two_words"
    if "NO MORE THAN THREE WORDS AND/OR A NUMBER" in upper:
        return "no_more_than_three_words_and_or_a_number"
    if "NO MORE THAN THREE WORDS" in upper:
        return "no_more_than_three_words"
    if "ONE WORD AND/OR A NUMBER" in upper:
        return "one_word_and_or_a_number"
    if "A NUMBER" in upper:
        return "a_number"
    if "LETTERS ONLY" in upper:
        return "letters_only"
    return None


class DocxReadingNormalizer(BaseNormalizer):
    """Normalizes raw DOCX extractions into canonical Reading entities."""

    def __init__(self, normalizer_version: str = NORMALIZER_VERSION):
        super().__init__(normalizer_version=normalizer_version)

    def normalize(
        self,
        raw_document: Dict[str, Any],
        source_record: Dict[str, Any],
        test_number: int = 5,
        passage_number: int = 1,
        volume_code: str = "VOL06",
        track: str = "academic",
        publication_permission: str = "private_copyrighted",
    ) -> Dict[str, Any]:
        """Normalizes Reading Passage and Question items from raw DOCX extraction.

        Returns dict containing:
        - 'test': IELTSTest
        - 'passage': PassageOrSection
        - 'groups': List[QuestionGroup]
        - 'questions': List[IELTSQuestion]
        """
        paragraphs = raw_document.get("content", {}).get("paragraphs", [])
        if not paragraphs:
            raise ValueError("No paragraphs found in raw_document content.")

        # Extract text list
        p_texts = [
            (p.get("text", "") if isinstance(p, dict) else str(p)).strip()
            for p in paragraphs
        ]

        # Locate target Test and Reading Passage boundaries
        start_idx, end_idx = self._find_passage_bounds(
            p_texts, test_number=test_number, passage_number=passage_number
        )

        passage_paras = p_texts[start_idx:end_idx]

        # Structure Test entity
        test_id = f"TEST-IELTS-{volume_code}-{test_number:02d}-{'ACAD' if track == 'academic' else 'GT'}"
        test_prov = self._make_provenance(
            source_record=source_record,
            raw_block_locator=f"para_index:{start_idx}",
            unit_id="raw_document",
        )
        test_qp = QualityProfile(
            lifecycle_status="reviewed",
            extraction_quality="complete_clean",
            source_fidelity="authoritative_official",
            answer_verification="authoritative_key",
            explanation_verification="source_provided",
            publication_permission=publication_permission,  # type: ignore[arg-type]
            validation_flags=[],
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

        # Structure Passage entity
        passage_id = f"PASSAGE-{volume_code}-{test_number:02d}-RD{passage_number:02d}"
        passage_title, passage_body_paras, p_body_indices, question_area_paras = self._split_passage_and_questions(
            passage_paras, start_idx
        )

        # Build paragraph items and full narrative text
        para_items: List[ParagraphItem] = []
        curr_offset = 0
        narrative_parts: List[str] = []

        for seq_i, (p_text, orig_idx) in enumerate(zip(passage_body_paras, p_body_indices)):
            if seq_i > 0:
                curr_offset += 2  # for "\n\n" separator
            p_start = curr_offset
            p_end = p_start + len(p_text)
            curr_offset = p_end
            narrative_parts.append(p_text)

            # Determine paragraph label (e.g. letter A, B, C or number 1, 2, 3...)
            label_match = re.match(r"^([A-Z])\s+", p_text)
            label = label_match.group(1) if label_match else str(seq_i + 1)

            para_items.append(
                ParagraphItem(
                    label=label,
                    sequence_index=seq_i,
                    char_start=p_start,
                    char_end=p_end,
                    text=p_text,
                )
            )

        narrative_text = "\n\n".join(narrative_parts)
        word_count = len(narrative_text.split())

        passage_prov = self._make_provenance(
            source_record=source_record,
            raw_block_locator=f"para_index:{p_body_indices[0]}",
            unit_id="raw_document",
        )
        passage_qp = QualityProfile(
            lifecycle_status="extracted",
            extraction_quality="complete_clean",
            source_fidelity="authoritative_official",
            answer_verification="authoritative_key",
            explanation_verification="source_provided",
            publication_permission=publication_permission,  # type: ignore[arg-type]
            validation_flags=[],
        )
        passage_entity = PassageOrSection(
            passage_id=passage_id,
            test_id=test_id,
            skill="reading",
            sequence_number=passage_number,
            title=passage_title,
            subtitle=None,
            narrative_text=narrative_text,
            paragraphs=para_items,
            audio_track_ref=None,
            word_count=word_count,
            quality_profile=passage_qp,
            _provenance=passage_prov,
        )

        # Parse Question Groups & Items
        groups, questions = self._parse_questions(
            question_area_paras=question_area_paras,
            test_id=test_id,
            passage_id=passage_id,
            volume_code=volume_code,
            test_number=test_number,
            source_record=source_record,
            publication_permission=publication_permission,
        )

        return {
            "test": test_entity,
            "passage": passage_entity,
            "groups": groups,
            "questions": questions,
        }

    def _find_passage_bounds(
        self, p_texts: List[str], test_number: int, passage_number: int
    ) -> Tuple[int, int]:
        """Finds slice indices [start_idx, end_idx) for target Reading Passage."""
        # Locate target Test
        test_regex = rf"^TEST\s+{test_number}\b"
        test_start = None
        for i, t in enumerate(p_texts):
            if re.match(test_regex, t, re.I):
                test_start = i
                break

        if test_start is None:
            # Fallback: search for passage directly
            test_start = 0

        # Locate target Reading Passage
        passage_regex = rf"^READING\s+PASSAGE\s+{passage_number}\b"
        pass_start = None
        for i in range(test_start, len(p_texts)):
            if re.match(passage_regex, p_texts[i], re.I):
                pass_start = i
                break

        if pass_start is None:
            raise ValueError(f"Reading Passage {passage_number} not found for Test {test_number}")

        # Locate next Reading Passage or next Test or end of document
        next_boundary_regex = r"^(READING\s+PASSAGE\s+\d+|TEST\s+\d+)\b"
        pass_end = len(p_texts)
        for i in range(pass_start + 1, len(p_texts)):
            if re.match(next_boundary_regex, p_texts[i], re.I):
                pass_end = i
                break

        return pass_start, pass_end

    def _split_passage_and_questions(
        self, passage_paras: List[str], base_idx: int
    ) -> Tuple[str, List[str], List[int], List[Tuple[int, str]]]:
        """Splits the passage paragraph block into Title, Passage Narrative, and Question Area."""
        # Find where Questions begin (e.g. "Questions 1-6" or "Questions 1–13")
        q_start = None
        for i, t in enumerate(passage_paras):
            if re.match(r"^Questions\s+\d+", t, re.I):
                q_start = i
                break

        if q_start is None:
            raise ValueError("No 'Questions X-Y' marker found in passage block.")

        # Passage text is between heading (para 0 is 'READING PASSAGE X', para 1 is rubric 'You should spend...')
        # Para 2 is typically the title
        title_idx = 1
        for i in range(1, min(4, q_start)):
            t = passage_paras[i]
            if not re.match(r"^You\s+should\s+spend", t, re.I) and len(t) < 150:
                title_idx = i
                break

        title = passage_paras[title_idx]

        body_paras = []
        body_indices = []
        for i in range(title_idx + 1, q_start):
            text = passage_paras[i]
            if text:
                body_paras.append(text)
                body_indices.append(base_idx + i)

        question_area = [
            (base_idx + i, passage_paras[i])
            for i in range(q_start, len(passage_paras))
            if passage_paras[i]
        ]

        return title, body_paras, body_indices, question_area

    def _parse_questions(
        self,
        question_area_paras: List[Tuple[int, str]],
        test_id: str,
        passage_id: str,
        volume_code: str,
        test_number: int,
        source_record: Dict[str, Any],
        publication_permission: str,
    ) -> Tuple[List[QuestionGroup], List[IELTSQuestion]]:
        """Parses question groups and items from the question section."""
        # Partition question area by "Questions X-Y"
        group_slices: List[List[Tuple[int, str]]] = []
        current_slice: List[Tuple[int, str]] = []

        for p_idx, text in question_area_paras:
            if re.match(r"^Questions\s+\d+", text, re.I) and current_slice:
                group_slices.append(current_slice)
                current_slice = [(p_idx, text)]
            else:
                current_slice.append((p_idx, text))
        if current_slice:
            group_slices.append(current_slice)

        groups: List[QuestionGroup] = []
        questions: List[IELTSQuestion] = []

        for g_num, g_slice in enumerate(group_slices, start=1):
            header_idx, header_text = g_slice[0]
            header_match = re.search(r"Questions\s+(\d+)[-–](\d+)", header_text, re.I)
            if not header_match:
                continue

            start_q = int(header_match.group(1))
            end_q = int(header_match.group(2))

            # Next paragraph(s) are instructions until questions start
            instr_parts = []
            q_paras = []
            for p_idx, t in g_slice[1:]:
                # If it looks like questions or notes, start collecting items
                if re.match(rf"^{start_q}\b", t) or re.search(r"\d+[\.…\_]", t) or len(instr_parts) >= 2:
                    q_paras.append((p_idx, t))
                else:
                    instr_parts.append(t)

            instruction_text = "\n".join(instr_parts).strip()
            if not instruction_text:
                instruction_text = header_text

            q_type = detect_question_type_from_instructions(instruction_text)
            word_limit = detect_word_limit_rule(instruction_text)

            group_id = f"QG-{volume_code}-{test_number:02d}-RD01-G{g_num:02d}"
            group_prov = self._make_provenance(
                source_record=source_record,
                raw_block_locator=f"para_index:{header_idx}",
                unit_id="raw_document",
            )
            group_qp = QualityProfile(
                lifecycle_status="reviewed",
                extraction_quality="complete_clean",
                source_fidelity="authoritative_official",
                answer_verification="authoritative_key",
                explanation_verification="source_provided",
                publication_permission=publication_permission,  # type: ignore[arg-type]
                validation_flags=[],
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
            groups.append(q_group)

            # Now parse individual questions for this group
            group_questions = self._parse_items_in_group(
                q_paras=q_paras,
                start_q=start_q,
                end_q=end_q,
                group_id=group_id,
                passage_id=passage_id,
                q_type=q_type,
                volume_code=volume_code,
                test_number=test_number,
                source_record=source_record,
                publication_permission=publication_permission,
            )
            questions.extend(group_questions)

        return groups, questions

    def _parse_items_in_group(
        self,
        q_paras: List[Tuple[int, str]],
        start_q: int,
        end_q: int,
        group_id: str,
        passage_id: str,
        q_type: QuestionType,
        volume_code: str,
        test_number: int,
        source_record: Dict[str, Any],
        publication_permission: str,
    ) -> List[IELTSQuestion]:
        """Parses individual IELTSQuestion items within a group."""
        items: List[IELTSQuestion] = []

        # Check if first paragraph contains concatenated questions (e.g. 1 ... 2 ... 3 ...)
        if q_paras and re.match(rf"^{start_q}\b", q_paras[0][1]):
            first_idx, first_text = q_paras[0]
            # Try segmentation
            segmented, seg_flags = segment_joined_questions(first_text, start_q, end_q)
            if segmented and not seg_flags:
                for s in segmented:
                    q_num = s["number"]
                    q_id = f"Q-{volume_code}-{test_number:02d}-RD-{q_num:03d}"
                    q_prov = self._make_provenance(
                        source_record=source_record,
                        raw_block_locator=f"para_index:{first_idx}",
                        unit_id="raw_document",
                    )
                    q_qp = QualityProfile(
                        lifecycle_status="extracted",
                        extraction_quality="complete_clean",
                        source_fidelity="authoritative_official",
                        answer_verification="authoritative_key",
                        explanation_verification="source_provided",
                        publication_permission=publication_permission,  # type: ignore[arg-type]
                        validation_flags=[],
                    )
                    items.append(
                        IELTSQuestion(
                            question_id=q_id,
                            group_id=group_id,
                            passage_id=passage_id,
                            question_number=q_num,
                            question_type=q_type,
                            prompt_text=s["prompt"],
                            options=None,
                            blank_target=None,
                            linked_principle_ids=["RD-TFNG-001"] if q_type == "true-false-not-given" else [],
                            quality_profile=q_qp,
                            _provenance=q_prov,
                        )
                    )
                return items

        # Fallback / Note completion / Multi-paragraph questions
        for q_num in range(start_q, end_q + 1):
            matched_para = None
            matched_idx = None
            blank_str = None

            for p_idx, text in q_paras:
                # Pattern: q_num followed by dots, underscores or blank
                m = re.search(rf"(?:^|\s)({q_num})([…\.\_]+)", text)
                if m:
                    matched_para = text.strip()
                    matched_idx = p_idx
                    blank_str = m.group(0).strip()
                    break
                # Or standard numbered prompt: "7. Prompt..."
                m2 = re.match(rf"^{q_num}[\.\s\:\)](.*)", text)
                if m2:
                    matched_para = m2.group(1).strip()
                    matched_idx = p_idx
                    break

            q_id = f"Q-{volume_code}-{test_number:02d}-RD-{q_num:03d}"
            prompt = matched_para if matched_para else f"[Question {q_num} text unresolved]"
            flags = [] if matched_para else ["UNRESOLVED_QUESTION_PROMPT"]
            status = "extracted" if matched_para else "review_required"

            q_prov = self._make_provenance(
                source_record=source_record,
                raw_block_locator=f"para_index:{matched_idx if matched_idx is not None else 0}",
                unit_id="raw_document",
            )
            q_qp = QualityProfile(
                lifecycle_status=status,  # type: ignore[arg-type]
                extraction_quality="complete_clean" if matched_para else "segmented_imperfect",
                source_fidelity="authoritative_official",
                answer_verification="authoritative_key",
                explanation_verification="source_provided",
                publication_permission=publication_permission,  # type: ignore[arg-type]
                validation_flags=flags,
            )
            items.append(
                IELTSQuestion(
                    question_id=q_id,
                    group_id=group_id,
                    passage_id=passage_id,
                    question_number=q_num,
                    question_type=q_type,
                    prompt_text=prompt,
                    options=None,
                    blank_target=blank_str,
                    linked_principle_ids=[],
                    quality_profile=q_qp,
                    _provenance=q_prov,
                )
            )

        return items

    def _make_provenance(
        self,
        source_record: Dict[str, Any],
        raw_block_locator: str,
        unit_id: str = "raw_document",
    ) -> ProvenanceEnvelope:
        """Constructs backward-traceable ProvenanceEnvelope for DOCX extraction."""
        return ProvenanceEnvelope(
            schema_version=SCHEMA_VERSION,
            source_file_id=source_record["file_id"],
            source_legacy_id=source_record["legacy_id"],
            relative_path=source_record["relative_path"],
            source_sha256=source_record["content_sha256"],
            processing_unit="document",
            unit_identifier=unit_id,
            raw_block_locator=raw_block_locator,
            extractor_adapter="docx",
            extractor_version="0.1.0-lxml-docx",
            normalizer_version=self.normalizer_version,
            canonical_content_sha256=None,
            normalized_at=None,
        )
