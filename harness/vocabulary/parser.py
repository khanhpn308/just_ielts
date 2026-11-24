"""Structural extraction parsers for Family A (In-Use), Family B (IELTS Vocab), and Family C (NgocBach)."""

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from harness.config import REPO_ROOT
from harness.vocabulary.inventory import VOCAB_RAW_DIR, VOCAB_KB_DIR

STAGING_OCR_CACHE = REPO_ROOT / "private" / "staging" / "raw_extracted" / "ocr_cache"
STAGING_UNITS_DIR = VOCAB_KB_DIR / "units"


def ensure_ocr_cache_dir() -> Path:
    STAGING_OCR_CACHE.mkdir(parents=True, exist_ok=True)
    return STAGING_OCR_CACHE


def get_page_text_with_cache(source_id: str, pdf_path: Path, page_num: int, is_scanned: bool = False) -> str:
    """Retrieves page text using pdftotext or cached tesseract OCR for scanned pages."""
    if not is_scanned:
        # Digital text layer
        res = subprocess.run(
            ["pdftotext", "-f", str(page_num), "-l", str(page_num), str(pdf_path), "-"],
            capture_output=True, text=True, check=True
        )
        return res.stdout

    # Scanned page - check disk cache first
    cache_dir = ensure_ocr_cache_dir()
    cache_file = cache_dir / f"{source_id}_p{page_num:03d}.txt"
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")

    # Render image with pdftoppm (150 DPI is fast and high quality)
    prefix = f"/tmp/ocr_{source_id}_p{page_num:03d}"
    subprocess.run(
        ["pdftoppm", "-png", "-f", str(page_num), "-l", str(page_num), "-r", "150", str(pdf_path), prefix],
        check=True
    )
    # Match created png
    candidates = list(Path("/tmp").glob(f"ocr_{source_id}_p{page_num:03d}*.png"))
    if not candidates:
        raise FileNotFoundError(f"pdftoppm did not generate expected image for page {page_num}")
    img_file = candidates[0]

    try:
        res = subprocess.run(
            ["tesseract", str(img_file), "stdout", "-l", "eng"],
            capture_output=True, text=True, check=True
        )
        text = res.stdout
        cache_file.write_text(text, encoding="utf-8")
        return text
    finally:
        img_file.unlink(missing_ok=True)


class FamilyAParser:
    """Parser for Cambridge In Use textbooks (EVU-B2, EVU-ADV, ECI-INT, ECI-ADV, AVU)."""

    def __init__(self, source_id: str):
        self.source_id = source_id
        self.pdf_path = VOCAB_RAW_DIR / f"{source_id}.pdf"
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"Source PDF not found: {self.pdf_path}")
        self._ak_cache: Dict[int, str] = {}

    def parse_unit(self, unit_info: Dict[str, Any]) -> Dict[str, Any]:
        """Parses a two-page unit into theory, exercises, vocabulary targets and answer key."""
        p_start = unit_info["physical_pages"][0]
        p_end = unit_info["physical_pages"][1]
        unit_num = unit_info["unit_number"]
        unit_key = unit_info["unit_key"]

        theory_text = get_page_text_with_cache(self.source_id, self.pdf_path, p_start, is_scanned=False)
        exercise_text = get_page_text_with_cache(self.source_id, self.pdf_path, p_end, is_scanned=False)

        sections = self._extract_theory_sections(theory_text)
        exercises = self._extract_exercises(exercise_text, unit_num)
        answer_key = self._extract_answer_key(unit_num, unit_info.get("answer_key_pdf_pages"))

        return {
            "unit_key": unit_key,
            "source_id": self.source_id,
            "unit_number": unit_num,
            "title": unit_info["title"],
            "physical_pages": [p_start, p_end],
            "topics": unit_info.get("topics", []),
            "language_functions": unit_info.get("language_functions", []),
            "theory": {
                "raw_text": theory_text,
                "sections": sections,
            },
            "exercises": exercises,
            "answer_key": answer_key,
            "audio_required": False,
        }

    def _extract_theory_sections(self, text: str) -> List[Dict[str, Any]]:
        """Splits left theory page into sections A, B, C, D..."""
        lines = [l.strip() for l in text.splitlines()]
        sections = []
        current_letter = None
        current_title = ""
        current_lines = []

        for l in lines:
            # Section header pattern: single letter 'A', 'B', 'C' on its own line or 'A Subtitle'
            m = re.match(r"^([A-E])\b(?:\s+(.*))?$", l)
            if m and len(l) < 50:
                if current_letter:
                    sections.append({
                        "section_id": current_letter,
                        "title": current_title,
                        "content": "\n".join(current_lines).strip(),
                    })
                current_letter = m.group(1)
                current_title = m.group(2) or ""
                current_lines = []
            elif current_letter:
                if not current_title and len(current_lines) == 0 and len(l) < 60:
                    current_title = l
                else:
                    current_lines.append(l)

        if current_letter:
            sections.append({
                "section_id": current_letter,
                "title": current_title,
                "content": "\n".join(current_lines).strip(),
            })

        if not sections:
            # Fallback for single section / unsectioned theory
            sections.append({
                "section_id": "A",
                "title": "General Presentation",
                "content": text.strip(),
            })

        return sections

    def _extract_exercises(self, text: str, unit_num: int) -> List[Dict[str, Any]]:
        """Extracts numbered exercises like 14.1, 14.2... from the exercise page."""
        pattern = re.compile(rf"^({unit_num}\.\d{{1,2}})\b\s*(.*)$")
        exercises = []
        curr_ex = None
        curr_lines = []

        for l in text.splitlines():
            l_str = l.strip()
            m = pattern.match(l_str)
            if m:
                if curr_ex:
                    exercises.append({
                        "exercise_id": f"{self.source_id}-EX-{curr_ex['num']}",
                        "exercise_number": curr_ex["num"],
                        "instructions": curr_ex["instruction"],
                        "content": "\n".join(curr_lines).strip(),
                    })
                curr_ex = {"num": m.group(1), "instruction": m.group(2)}
                curr_lines = []
            elif curr_ex:
                curr_lines.append(l_str)

        if curr_ex:
            exercises.append({
                "exercise_id": f"{self.source_id}-EX-{curr_ex['num']}",
                "exercise_number": curr_ex["num"],
                "instructions": curr_ex["instruction"],
                "content": "\n".join(curr_lines).strip(),
            })

        return exercises

    def _extract_answer_key(self, unit_num: int, ak_pages: Optional[List[int]]) -> Dict[str, Any]:
        """Extracts answers for unit_num from the answer key page range using layout-aware extraction and caching."""
        if not ak_pages or len(ak_pages) < 2:
            return {"status": "unverified", "answers": {}}

        def get_ak_page_text(p: int) -> str:
            if p not in self._ak_cache:
                res = subprocess.run(
                    ["pdftotext", "-layout", "-f", str(p), "-l", str(p), str(self.pdf_path), "-"],
                    capture_output=True, text=True, check=True
                )
                self._ak_cache[p] = res.stdout
            return self._ak_cache[p]

        # Prioritize searching near the estimated page to minimize search overhead
        total_p = ak_pages[1] - ak_pages[0] + 1
        est_p = ak_pages[0] + min(max(0, int((unit_num / 100.0) * total_p) - 1), total_p - 1)
        priority_pages = [p for p in [est_p, est_p - 1, est_p + 1, est_p - 2, est_p + 2] if ak_pages[0] <= p <= ak_pages[1]]
        remaining_pages = [p for p in range(ak_pages[0], ak_pages[1] + 1) if p not in priority_pages]
        search_pages = priority_pages + remaining_pages

        matched_answers = {}
        for p in search_pages:
            txt = get_ak_page_text(p)
            # Include next page if available, since exercises often span across two answer key pages
            if p + 1 <= ak_pages[1]:
                txt = txt + "\n" + get_ak_page_text(p + 1)
            pattern = re.compile(rf"(?:Unit\s+{unit_num}\b|Key\s+{unit_num}\b)(.*?)(?=Unit\s+\d+\b|Key\s+\d+\b|\Z)", re.DOTALL | re.IGNORECASE)
            m = pattern.search(txt)
            if m:
                u_text = m.group(1)
                ex_matches = re.finditer(rf"({unit_num}\.\d{{1,2}})(.*?)(?={unit_num}\.\d{{1,2}}|\Z)", u_text, re.DOTALL)
                for em in ex_matches:
                    ex_id = em.group(1).strip()
                    ans_str = em.group(2).strip()
                    matched_answers[ex_id] = ans_str
                if matched_answers:
                    break

        return {
            "status": "extracted_authoritative_key" if matched_answers else "not_located",
            "answers": matched_answers,
        }


class FamilyBParser:
    """Parser for Pauline Cullen IELTS Vocabulary (IVU-60, IVU-65)."""

    def __init__(self, source_id: str):
        self.source_id = source_id
        self.pdf_path = VOCAB_RAW_DIR / f"{source_id}.pdf"
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"Source PDF not found: {self.pdf_path}")

    def parse_unit(self, unit_info: Dict[str, Any]) -> Dict[str, Any]:
        """Parses multi-page unit from cached OCR."""
        p_pages = unit_info["physical_pages"]
        unit_num = unit_info["unit_number"]
        unit_key = unit_info["unit_key"]

        pages_text = {}
        full_text_list = []
        for p in p_pages:
            t = get_page_text_with_cache(self.source_id, self.pdf_path, p, is_scanned=True)
            pages_text[p] = t
            full_text_list.append(t)

        combined_text = "\n\n--- PAGE BREAK ---\n\n".join(full_text_list)

        # Extract features
        vocab_notes = self._extract_feature_boxes(combined_text, r"Vocabulary\s+note\b")
        error_warnings = self._extract_feature_boxes(combined_text, r"Error\s+warning\b")
        test_tips = self._extract_feature_boxes(combined_text, r"Test\s+tip\b")
        exercises = self._extract_exercises(combined_text, unit_num)
        answer_key = self._extract_answer_key(unit_num, unit_info.get("answer_key_pdf_pages"))

        return {
            "unit_key": unit_key,
            "source_id": self.source_id,
            "unit_number": unit_num,
            "title": unit_info["title"],
            "subtopics": unit_info.get("subtopics", ""),
            "test_practice": unit_info.get("test_practice", ""),
            "physical_pages": p_pages,
            "topics": unit_info.get("topics", []),
            "language_functions": unit_info.get("language_functions", []),
            "theory": {
                "raw_text": combined_text,
                "vocabulary_notes": vocab_notes,
                "error_warnings": error_warnings,
                "test_tips": test_tips,
            },
            "exercises": exercises,
            "answer_key": answer_key,
            "audio_required": True,
            "audio_available": False,
            "audio_dependency_note": "Audio files missing locally; audio transcripts preserved for practice.",
        }

    def _extract_feature_boxes(self, text: str, pattern_str: str) -> List[str]:
        """Finds sidebar boxes like Vocabulary note or Error warning."""
        pat = re.compile(pattern_str, re.IGNORECASE)
        matches = []
        for m in pat.finditer(text):
            start = m.start()
            # Capture following 300 chars or until next double newline
            snippet = text[start:start + 400].strip()
            matches.append(snippet)
        return matches

    def _extract_exercises(self, text: str, unit_num: int) -> List[Dict[str, Any]]:
        """Extracts exercises matching numbered prompts, activity blocks or test practice."""
        pattern = re.compile(
            r"(?:^|\n)\s*(?:(?:[£€@©e\d\(\)]+\s*)?(\b\d{1,2}(?:\.\d{1,2})?\b)|(Test practice\b)|(Complete the table\b)|(Listen to\b)|(COLLOCATION\b)|(All of the words in the box\b))\s*(.*?)(?=(?:^|\n)\s*(?:(?:[£€@©e\d\(\)]+\s*)?\b\d{1,2}(?:\.\d{1,2})?\b|Test practice\b|Complete the table\b|Listen to\b|COLLOCATION\b|\Z))",
            re.DOTALL | re.IGNORECASE
        )
        exercises = []
        matches = list(pattern.finditer(text))
        for i, m in enumerate(matches):
            ex_num = m.group(1) or m.group(2) or f"Ex-{i+1}"
            body = m.group(0).strip()
            # First line is instruction
            lines = body.splitlines()
            inst = lines[0] if lines else ""
            content = "\n".join(lines[1:]).strip() if len(lines) > 1 else body
            if len(body) > 30:
                exercises.append({
                    "exercise_id": f"{self.source_id}-EX-{ex_num}",
                    "exercise_number": ex_num,
                    "instructions": inst[:200],
                    "content": content[:1200],
                })
        return exercises

    def _extract_answer_key(self, unit_num: int, ak_pages: Optional[List[int]]) -> Dict[str, Any]:
        """Extracts answers for unit_num from cached OCR of answer key pages."""
        if not ak_pages or len(ak_pages) < 2:
            return {"status": "unverified", "answers": {}}

        matched_answers = {}
        # In Cullen books, Unit u typically appears around ak_pages[0] + (unit_num - 1)
        est_page = ak_pages[0] + min(unit_num - 1, ak_pages[1] - ak_pages[0])
        candidate_pages = sorted(list(set([
            max(ak_pages[0], est_page - 1),
            est_page,
            min(ak_pages[1], est_page + 1),
            ak_pages[0],
            ak_pages[0] + 1
        ])))

        for p in candidate_pages:
            txt = get_page_text_with_cache(self.source_id, self.pdf_path, p, is_scanned=True)
            # Check for Unit {unit_num} or check if sub-exercises 1.2, 1.4, 2 exist
            pattern = re.compile(rf"(?:Unit\s+{unit_num}\b|Wunit\s*{unit_num}\b)(.*?)(?=Unit\s+\d+\b|Wunit\s*\d+\b|\Z)", re.DOTALL | re.IGNORECASE)
            m = pattern.search(txt)
            if m:
                u_text = m.group(1)
                ex_matches = re.finditer(rf"(\d{{1,2}}(?:\.\d{{1,2}})?)(.*?)(?=\d{{1,2}}(?:\.\d{{1,2}})?|\Z)", u_text, re.DOTALL)
                for em in ex_matches:
                    ex_id = em.group(1).strip()
                    ans_str = em.group(2).strip()
                    matched_answers[ex_id] = ans_str
                if matched_answers:
                    break

            # If no explicit 'Unit {unit_num}' header (like IVU-65 p138-139 where headers were omitted)
            if not matched_answers and unit_num == 5 and p in [138, 139]:
                # Locate Unit 5 section on p. 138-139
                u5_match = re.search(r"Speaker 1: C.*?1\.4.*?prior knowledge", txt, re.DOTALL)
                if u5_match:
                    matched_answers["1.2-1.4"] = u5_match.group(0).strip()
                    break

        return {
            "status": "extracted_ocr_key" if matched_answers else "not_located",
            "answers": matched_answers,
        }


class FamilyCParser:
    """Parser for NgocBach Paraphrase (NB-PARA)."""

    def __init__(self):
        self.source_id = "NB-PARA"
        self.pdf_path = VOCAB_RAW_DIR / "NB-PARA.pdf"
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"Source PDF not found: {self.pdf_path}")

    def parse_section(self, section_info: Dict[str, Any]) -> Dict[str, Any]:
        """Parses a paraphrase section, cleaning advertising footers and extracting bilingual paraphrase entries."""
        pages = section_info["physical_pages"]
        raw_texts = []
        for p in pages:
            raw_texts.append(get_page_text_with_cache(self.source_id, self.pdf_path, p, is_scanned=False))

        cleaned_text = self._clean_advertising("\n".join(raw_texts))
        paraphrase_items = self._extract_paraphrase_groups(cleaned_text)

        return {
            "unit_key": section_info["unit_key"],
            "source_id": self.source_id,
            "title": section_info["title"],
            "physical_pages": pages,
            "topics": section_info.get("topics", []),
            "language_functions": section_info.get("language_functions", []),
            "raw_text": cleaned_text,
            "paraphrase_groups": paraphrase_items,
            "audio_required": False,
        }

    def _clean_advertising(self, text: str) -> str:
        """Removes commercial footers and promotional noise."""
        lines = text.splitlines()
        cleaned = []
        for l in lines:
            l_str = l.strip()
            if "ngocbach.com" in l_str or "0974657403" in l_str or "ieltsbach1707" in l_str:
                continue
            if "Khóa học" in l_str or "Hotline" in l_str:
                continue
            cleaned.append(l)
        return "\n".join(cleaned).strip()

    def _extract_paraphrase_groups(self, text: str) -> List[Dict[str, Any]]:
        """Extracts paraphrase transformation groups: Expression -> Variants -> Meaning/Gloss."""
        groups = []
        # Pattern often: 'English expression – Variant 1 / Variant 2: Nghĩa tiếng Việt'
        pattern = re.compile(r"^([A-Za-z0-9\s,\'\"\(\)\-\?]+?)\s*[–—\-]\s*(.*?):\s*(.*)$", re.MULTILINE)
        for m in pattern.finditer(text):
            orig = m.group(1).strip()
            variants = [v.strip() for v in m.group(2).split("/") if v.strip()]
            vi = m.group(3).strip()
            if orig and variants:
                groups.append({
                    "original_expression": orig,
                    "paraphrase_variants": variants,
                    "meaning_vi": vi,
                })
        return groups


def save_parsed_unit(unit_data: Dict[str, Any], output_base: Path = STAGING_UNITS_DIR) -> Path:
    """Saves parsed unit JSON to private/knowledge/vocabulary/units/<source_id>/<unit_key>.json."""
    source_id = unit_data["source_id"]
    unit_key = unit_data["unit_key"]
    unit_dir = output_base / source_id
    unit_dir.mkdir(parents=True, exist_ok=True)
    out_file = unit_dir / f"{unit_key}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(unit_data, f, indent=2, ensure_ascii=False)
    return out_file
