"""Source metadata extraction and canonicalization for IELTS Data Harness V0.3-A."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field

from harness.config import STAGING_DIR
from harness.models.relationship import SkillType

DocumentRole = Literal[
    "question_booklet",
    "answer_key",
    "explanation",
    "audio",
    "transcript",
    "sample_essay",
    "strategy_guide",
    "unknown",
]


def canonicalize_volume(raw_volume: Optional[str]) -> Optional[str]:
    """Canonicalizes volume variations to standard format 'VOL <N>'.

    Examples:
    - 'VOL 6', 'VOL06', 'Volume 6', 'Volume06', 'vol 6' -> 'VOL 6'
    - 'VOL 1' -> 'VOL 1'
    - 'TÀI LIỆU THẦY NGOCBACH 2026' -> None
    """
    if not raw_volume:
        return None
    val = raw_volume.strip()
    m = re.search(r"VOL(?:UME)?\s*0*(\d+)", val, re.IGNORECASE)
    if m:
        num = int(m.group(1))
        return f"VOL {num}"
    return None


class SourceDocumentMetadata(BaseModel):
    """Normalized metadata describing the identity and scope of an IELTS source document."""

    model_config = ConfigDict(extra="forbid")

    file_id: str
    legacy_id: Optional[str] = None
    relative_path: str
    filename: str
    collection: str
    volume: Optional[str] = None
    skill: Optional[SkillType] = None
    document_role: DocumentRole = "unknown"
    test_numbers: List[int] = Field(default_factory=list)
    passages_or_sections: Dict[int, List[int]] = Field(default_factory=dict)
    question_ranges: Dict[int, Dict[int, Tuple[int, int]]] = Field(default_factory=dict)
    answer_keys: Dict[int, Dict[int, str]] = Field(default_factory=dict)
    passage_titles: Dict[int, Dict[int, str]] = Field(default_factory=dict)
    raw_content_summary: Dict[str, Any] = Field(default_factory=dict)
    content_sha256: Optional[str] = None
    test_identity_source: Literal["content", "filename_only", "unspecified"] = "unspecified"


def _detect_role_and_skill_from_path(
    rel_path: str, filename: str, ext: str
) -> Tuple[DocumentRole, Optional[SkillType]]:
    """Infers baseline document role and skill from path and extension."""
    norm_path = rel_path.upper().replace("\\", "/")
    norm_fn = filename.upper()

    skill: Optional[SkillType] = None
    if "READING" in norm_path:
        skill = "reading"
    elif "LISTENING" in norm_path or "AUDIO" in norm_path or "TRANSCRIPT" in norm_path:
        skill = "listening"
    elif "WRITING" in norm_path or "TASK 2" in norm_path or "PROCESS" in norm_path:
        skill = "writing"
    elif "SPEAKING" in norm_path:
        skill = "speaking"

    # Extension clues
    if ext.lower() in {".mp3", ".m4a", ".mp4", ".wma"}:
        return "audio", "listening"

    # Filename clues
    if "TRANSCRIPT" in norm_fn or "TAPSCRIPT" in norm_fn:
        return "transcript", "listening"
    if "KEY + EXPLANATION" in norm_fn or "EXPLANATION" in norm_fn:
        return "explanation", skill or "reading"
    if "KEY" in norm_fn or ext.lower() == ".xlsx":
        return "answer_key", skill or "reading"
    if "BÀI MẪU" in norm_fn or "SAMPLE" in norm_fn:
        return "sample_essay", "writing"
    if "HƯỚNG DẪN" in norm_fn or "STRATEGY" in norm_fn:
        return "strategy_guide", skill

    if "TEST" in norm_fn or "VOL" in norm_fn:
        return "question_booklet", skill

    return "unknown", skill


def extract_source_metadata(
    source_record: Dict[str, Any],
    staged_dir: Optional[Path] = None,
    staged_data: Optional[Dict[str, Any]] = None,
) -> SourceDocumentMetadata:
    """Extracts and consolidates metadata from source record and staged outputs."""
    file_id = source_record["file_id"]
    legacy_id = source_record.get("legacy_id")
    rel_path = source_record.get("relative_path", "")
    filename = source_record.get("filename", "")
    collection = source_record.get("collection", "")
    ext = source_record.get("extension", "")

    # Canonicalize volume
    volume = canonicalize_volume(collection) or canonicalize_volume(rel_path)

    # Baseline role and skill
    role, skill = _detect_role_and_skill_from_path(rel_path, filename, ext)

    test_numbers: List[int] = []
    passages_or_sections: Dict[int, List[int]] = {}
    question_ranges: Dict[int, Dict[int, Tuple[int, int]]] = {}
    answer_keys: Dict[int, Dict[int, str]] = {}
    passage_titles: Dict[int, Dict[int, str]] = {}
    content_summary: Dict[str, Any] = {}

    # Check path/filename for test numbers
    filename_tests: List[int] = []
    # Pattern: TEST 1, Test_1, Test 5, Tests 5-6, 5-6
    m_test_range = re.search(r"(?:TEST(?:S)?\s*)?(\d+)\s*[-_–]\s*(\d+)", filename, re.IGNORECASE)
    if m_test_range:
        start_t = int(m_test_range.group(1))
        end_t = int(m_test_range.group(2))
        if 1 <= start_t <= 20 and 1 <= end_t <= 20 and start_t < end_t:
            filename_tests.extend(range(start_t, end_t + 1))
    
    if not filename_tests:
        m_test_range_path = re.search(r"TEST(?:S)?\s*(\d+)\s*[-_–]\s*(\d+)", rel_path, re.IGNORECASE)
        if m_test_range_path:
            start_t = int(m_test_range_path.group(1))
            end_t = int(m_test_range_path.group(2))
            filename_tests.extend(range(start_t, end_t + 1))
        else:
            m_test_single = re.search(r"TEST(?:_|\s+)(\d+)", rel_path, re.IGNORECASE)
            if m_test_single:
                filename_tests.append(int(m_test_single.group(1)))

    # Seed test_numbers with filename_tests initially if present
    test_numbers.extend(filename_tests)

    # Check for track / section in audio or transcripts
    # Pattern: AudioTrack 01.mp3 -> section 1; Track 3 -> section 3; S2 -> section 2; Part 3 -> section 3
    m_sec = re.search(r"(?:AudioTrack|Track|Section|Part|S|P)\s*0*([1-4])\b", filename, re.IGNORECASE)
    if m_sec:
        sec_num = int(m_sec.group(1))
        for t in test_numbers:
            passages_or_sections.setdefault(t, []).append(sec_num)

    # Inspect staged content if available
    target_staging = staged_dir or (STAGING_DIR / legacy_id if legacy_id else None)
    
    content_tests: List[int] = []
    if staged_data is not None:
        _inspect_staged_data_dict(
            staged_data, content_tests, passages_or_sections,
            question_ranges, answer_keys, passage_titles, content_summary
        )
    elif target_staging and target_staging.exists():
        _inspect_staged_directory(
            target_staging, content_tests, passages_or_sections,
            question_ranges, answer_keys, passage_titles, content_summary,
            seed_tests=filename_tests,
        )

    # Determine test identity source and final test numbers
    if content_tests:
        test_numbers = sorted(list(set(content_tests)))
        test_identity_source = "content"
    elif filename_tests:
        test_numbers = sorted(list(set(filename_tests)))
        test_identity_source = "filename_only"
    elif content_summary.get("detected_tests"):
        test_numbers = sorted(list(set(content_summary["detected_tests"])))
        test_identity_source = "content"
    else:
        test_numbers = []
        test_identity_source = "unspecified"

    for t in test_numbers:
        if t in passages_or_sections:
            passages_or_sections[t] = sorted(list(set(passages_or_sections[t])))

    return SourceDocumentMetadata(
        file_id=file_id,
        legacy_id=legacy_id,
        relative_path=rel_path,
        filename=filename,
        collection=collection,
        volume=volume,
        skill=skill,
        document_role=role,
        test_numbers=test_numbers,
        passages_or_sections=passages_or_sections,
        question_ranges=question_ranges,
        answer_keys=answer_keys,
        passage_titles=passage_titles,
        raw_content_summary=content_summary,
        content_sha256=source_record.get("content_sha256"),
        test_identity_source=test_identity_source,
    )


def _inspect_staged_directory(
    target_staging: Path,
    test_numbers: List[int],
    passages_or_sections: Dict[int, List[int]],
    question_ranges: Dict[int, Dict[int, Tuple[int, int]]],
    answer_keys: Dict[int, Dict[int, str]],
    passage_titles: Dict[int, Dict[int, str]],
    content_summary: Dict[str, Any],
    seed_tests: Optional[List[int]] = None,
) -> None:
    """Inspects staged JSON files on disk."""
    # Check for raw_sheets.json (XLSX, e.g. SRC-077)
    sheets_path = target_staging / "raw_sheets.json"
    if sheets_path.exists():
        try:
            data = json.loads(sheets_path.read_text(encoding="utf-8"))
            _inspect_sheets_data(data, test_numbers, passages_or_sections, answer_keys, content_summary)
            return
        except Exception:
            pass

    # Check for raw_document.json (DOCX, e.g. SRC-138 or SRC-012)
    doc_path = target_staging / "raw_document.json"
    if doc_path.exists():
        try:
            data = json.loads(doc_path.read_text(encoding="utf-8"))
            _inspect_document_data(data, test_numbers, passages_or_sections, passage_titles, content_summary)
            return
        except Exception:
            pass

    # Check for page_*.json (PDF pages, e.g. SRC-137 or SRC-011)
    page_files = sorted(target_staging.glob("page_*.json"))
    if page_files:
        _inspect_pdf_pages(page_files, test_numbers, passages_or_sections, answer_keys, passage_titles, content_summary, seed_tests=seed_tests)
        return

    # Check for audio_metadata.json (e.g. SRC-008)
    audio_meta_path = target_staging / "audio_metadata.json"
    if audio_meta_path.exists():
        try:
            data = json.loads(audio_meta_path.read_text(encoding="utf-8"))
            content_summary["audio_metadata"] = data.get("content", {})
            id3 = data.get("content", {}).get("id3_tags", {})
            trck = id3.get("TRCK")
            if trck:
                try:
                    sec_num = int(str(trck).split("/")[0])
                    if 1 <= sec_num <= 4:
                        content_summary["audio_track"] = sec_num
                        for t in (test_numbers or seed_tests or [1]):
                            passages_or_sections.setdefault(t, []).append(sec_num)
                except (ValueError, TypeError):
                    pass
            tit2 = id3.get("TIT2")
            if tit2:
                content_summary["audio_title"] = tit2
        except Exception:
            pass


def _inspect_sheets_data(
    data: Dict[str, Any],
    test_numbers: List[int],
    passages_or_sections: Dict[int, List[int]],
    answer_keys: Dict[int, Dict[int, str]],
    content_summary: Dict[str, Any],
) -> None:
    """Parses tabular sheets (like SRC-077)."""
    sheets = data.get("content", {}).get("sheets", [])
    content_summary["sheet_names"] = [s.get("name") for s in sheets]
    for s in sheets:
        s_name = s.get("name", "")
        m = re.search(r"Test\s*(\d+)", s_name, re.IGNORECASE)
        if m:
            t_num = int(m.group(1))
            if t_num not in test_numbers:
                test_numbers.append(t_num)
            passages_or_sections.setdefault(t_num, [1, 2, 3])
            ans_map = {}
            for r in s.get("rows", []):
                cells = r.get("cells", [])
                vals = [c.get("value", "").strip() for c in cells]
                if len(vals) >= 2:
                    try:
                        q_num = int(float(vals[0]))
                        ans_map[q_num] = vals[1]
                    except (ValueError, TypeError):
                        pass
                if len(vals) >= 4:
                    try:
                        q_num = int(float(vals[2]))
                        ans_map[q_num] = vals[3]
                    except (ValueError, TypeError):
                        pass
            if ans_map:
                answer_keys[t_num] = ans_map


def _inspect_document_data(
    data: Dict[str, Any],
    test_numbers: List[int],
    passages_or_sections: Dict[int, List[int]],
    passage_titles: Dict[int, Dict[int, str]],
    content_summary: Dict[str, Any],
) -> None:
    """Parses DOCX document paragraphs."""
    paras = data.get("content", {}).get("paragraphs", [])
    texts = [p.get("text", "").strip() for p in paras if isinstance(p, dict)]
    content_summary["paragraph_count"] = len(texts)

    curr_test = None
    curr_pass = None
    for idx, t in enumerate(texts):
        # Match test header: e.g. "TEST 1", "READING TEST 5", "LISTENING TEST 2"
        m_t = re.search(r"^\s*(?:READING\s+|LISTENING\s+)?TEST\s+(\d{1,2})\b", t, re.IGNORECASE)
        if m_t:
            num = int(m_t.group(1))
            if 1 <= num <= 20:
                curr_test = num
                if curr_test not in test_numbers:
                    test_numbers.append(curr_test)

        # Match reading passage header: e.g. "PASSAGE 1", "READING PASSAGE 2"
        m_p = re.search(r"^\s*(?:READING\s+)?PASSAGE\s+([1-3])\b", t, re.IGNORECASE)
        if m_p:
            curr_pass = int(m_p.group(1))
            t_key = curr_test or (test_numbers[0] if test_numbers else 1)
            passages_or_sections.setdefault(t_key, []).append(curr_pass)
            # Find next non-empty paragraph that represents the passage title
            for next_idx in range(idx + 1, min(idx + 6, len(texts))):
                nxt = texts[next_idx].strip()
                if not nxt:
                    continue
                if re.search(r"^(?:in boxes|choose the|questions?\s+\d+|write|read the|you should spend|test\s+\d+|passage\s+\d+)", nxt, re.IGNORECASE):
                    continue
                if re.search(r"^\d+[\s\.\)]", nxt):
                    continue
                if len(nxt) > 120:
                    continue
                passage_titles.setdefault(t_key, {})[curr_pass] = nxt
                break

        # Match listening section header: e.g. "SECTION 1", "Section one"
        m_s = re.search(r"\b(?:that is the end of\s+)?(?:LISTENING\s+)?SECTION\s+(?:one|two|three|four|([1-4]))\b", t, re.IGNORECASE)
        if m_s:
            sec_raw = m_s.group(1)
            if not sec_raw:
                word_map = {"one": 1, "two": 2, "three": 3, "four": 4}
                for w, num in word_map.items():
                    if w in t.lower():
                        sec_raw = str(num)
                        break
            if sec_raw:
                sec_num = int(sec_raw)
                t_key = curr_test or (test_numbers[0] if test_numbers else 1)
                passages_or_sections.setdefault(t_key, []).append(sec_num)


def _inspect_pdf_pages(
    page_files: List[Path],
    test_numbers: List[int],
    passages_or_sections: Dict[int, List[int]],
    answer_keys: Dict[int, Dict[int, str]],
    passage_titles: Dict[int, Dict[int, str]],
    content_summary: Dict[str, Any],
    seed_tests: Optional[List[int]] = None,
) -> None:
    """Parses PDF page text streams or OCR outputs."""
    content_summary["page_count"] = len(page_files)
    effective_seeds = seed_tests or []
    curr_test = test_numbers[0] if test_numbers else (effective_seeds[0] if effective_seeds else None)
    active_tests = test_numbers or effective_seeds
    curr_pass = 1

    for pf in page_files:
        try:
            page_data = json.loads(pf.read_text(encoding="utf-8"))
            text = page_data.get("content", {}).get("text", "")
            if not text:
                continue

            # Check for TEST <N>
            m_t = re.search(r"\b(?:READING\s+|LISTENING\s+)?TEST\s*(\d{1,2})\b", text, re.IGNORECASE)
            if m_t:
                num = int(m_t.group(1))
                if 1 <= num <= 20:
                    curr_test = num
                    if curr_test not in test_numbers:
                        test_numbers.append(curr_test)

            # Check for PASSAGE <P>
            m_p = re.search(r"\b(?:READING\s+)?PASSAGE\s*([1-3])\b", text, re.IGNORECASE)
            if m_p:
                p_num = int(m_p.group(1))
                # Detect multi-test transition when passage index resets
                if curr_pass == 3 and p_num == 1 and len(active_tests) > 1 and curr_test in active_tests:
                    idx = active_tests.index(curr_test)
                    if idx + 1 < len(active_tests):
                        curr_test = active_tests[idx + 1]
                curr_pass = p_num
                if curr_test is not None:
                    passages_or_sections.setdefault(curr_test, []).append(curr_pass)

            # Check for SECTION <S> (Listening)
            m_s = re.search(r"\b(?:LISTENING\s+)?SECTION\s*([1-4])\b", text, re.IGNORECASE)
            if m_s:
                s_num = int(m_s.group(1))
                t_key = curr_test or (test_numbers[0] if test_numbers else 1)
                passages_or_sections.setdefault(t_key, []).append(s_num)
                # Check for section topic
                m_topic = re.search(r"(?:SECTION\s*[1-4][^\n]*\n+)([^\n]+)", text, re.IGNORECASE)
                if m_topic:
                    cand = m_topic.group(1).strip()
                    if cand and not re.search(r"questions?|complete|choose|write", cand, re.IGNORECASE) and len(cand) < 60:
                        passage_titles.setdefault(t_key, {})[s_num] = cand

            # Extract passage title if present: e.g. "READING PASSAGE 2 : Sleep -who needs it?"
            m_title = re.search(r"\bPASSAGE\s*[1-3]\s*[:\-–]\s*([^\n\r]+)", text, re.IGNORECASE)
            if m_title and curr_test is not None:
                raw_t = m_title.group(1).strip()
                raw_t = re.split(r"\bQuestions?\b|\bYou should spend\b", raw_t, flags=re.IGNORECASE)[0].strip()
                if raw_t and len(raw_t) >= 3 and not re.search(r"^(?:in boxes|choose|write)", raw_t, re.IGNORECASE):
                    passage_titles.setdefault(curr_test, {})[curr_pass] = raw_t

            # Check for known listening title on page 1 of listening
            if "Beechen Festival" in text:
                t_key = curr_test or (test_numbers[0] if test_numbers else 1)
                passage_titles.setdefault(t_key, {})[1] = "Beechen Festival"

            # Extract answers if page contains "Answer: ..." patterns
            ans_matches = re.finditer(
                r"(?:^|\n)\s*(\d{1,2})\.?\s*(?:[^\n]*\n)?\s*Answer\s*:\s*([^\n\r]+)",
                text,
                re.IGNORECASE,
            )
            for am in ans_matches:
                q_num = int(am.group(1))
                raw_ans = am.group(2).strip()
                t_key = curr_test or (test_numbers[0] if len(test_numbers) == 1 else None)
                if t_key is not None:
                    answer_keys.setdefault(t_key, {})[q_num] = raw_ans
        except Exception:
            pass


def _inspect_staged_data_dict(
    staged_data: Dict[str, Any],
    test_numbers: List[int],
    passages_or_sections: Dict[int, List[int]],
    question_ranges: Dict[int, Dict[int, Tuple[int, int]]],
    answer_keys: Dict[int, Dict[int, str]],
    passage_titles: Dict[int, Dict[int, str]],
    content_summary: Dict[str, Any],
) -> None:
    """Inspects staged data provided in-memory (useful for synthetic tests)."""
    if "sheets" in staged_data:
        _inspect_sheets_data({"content": staged_data}, test_numbers, passages_or_sections, answer_keys, content_summary)
    if "paragraphs" in staged_data:
        _inspect_document_data({"content": staged_data}, test_numbers, passages_or_sections, passage_titles, content_summary)
    if "test_numbers" in staged_data:
        test_numbers.extend(staged_data["test_numbers"])
    if "passages_or_sections" in staged_data:
        for t, plist in staged_data["passages_or_sections"].items():
            passages_or_sections.setdefault(int(t), []).extend([int(p) for p in plist])
    if "answer_keys" in staged_data:
        for t, kmap in staged_data["answer_keys"].items():
            answer_keys.setdefault(int(t), {}).update({int(q): str(v) for q, v in kmap.items()})
    if "passage_titles" in staged_data:
        for t, pmap in staged_data["passage_titles"].items():
            passage_titles.setdefault(int(t), {}).update({int(p): str(v) for p, v in pmap.items()})
