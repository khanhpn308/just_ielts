"""Structural parsing and source inventory for the 8 vocabulary textbooks."""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import pikepdf

from harness.config import REPO_ROOT

VOCAB_RAW_DIR = REPO_ROOT / "private" / "raw" / "vocabulary_books"
VOCAB_KB_DIR = REPO_ROOT / "private" / "knowledge" / "vocabulary"
PROCESSING_VERSION = "1.1.0"

# Canonical metadata for the eight locked textbooks
SOURCE_METADATA_CONFIG = {
    "EVU-B2": {
        "title": "English Vocabulary in Use Upper-intermediate",
        "edition": "4th Edition",
        "authors": ["Michael McCarthy", "Felicity O'Dell"],
        "publisher": "Cambridge University Press",
        "filename": "EVU-B2.pdf",
        "family": "in_use",
        "printed_page_offset": 4,  # printed p.1 = pdf p.5; units start printed p.5/6 -> pdf p.9
        "unit_count": 101,
        "unit_page_length": 2,
        "first_unit_pdf_page": 9,
        "last_unit_pdf_page": 210,
        "theory_page_rule": "left_page",
        "exercise_page_rule": "right_page",
        "answer_key_pdf_pages": [211, 257],
        "phonemic_symbols_pdf_page": 258,
        "index_pdf_pages": [259, 279],
        "wordlist_available": False,
        "recording_scripts_available": False,
        "audio_references": False,
        "audio_files_available": False,
        "text_layer": True,
        "scanned": False,
        "extraction_limitations": [],
    },
    "EVU-ADV": {
        "title": "English Vocabulary in Use Advanced",
        "edition": "3rd Edition",
        "authors": ["Michael McCarthy", "Felicity O'Dell"],
        "publisher": "Cambridge University Press",
        "filename": "EVU-ADV.pdf",
        "family": "in_use",
        "printed_page_offset": 2,  # printed p.8 = pdf p.10
        "unit_count": 101,
        "unit_page_length": 2,
        "first_unit_pdf_page": 10,
        "last_unit_pdf_page": 211,
        "theory_page_rule": "left_page",
        "exercise_page_rule": "right_page",
        "answer_key_pdf_pages": [212, 277],
        "phonemic_symbols_pdf_page": 278,
        "index_pdf_pages": [279, 300],
        "wordlist_available": False,
        "recording_scripts_available": False,
        "audio_references": False,
        "audio_files_available": False,
        "text_layer": True,
        "scanned": False,
        "extraction_limitations": [],
    },
    "ECI-INT": {
        "title": "English Collocations in Use Intermediate",
        "edition": "2nd Edition",
        "authors": ["Michael McCarthy", "Felicity O'Dell"],
        "publisher": "Cambridge University Press",
        "filename": "ECI-INT.pdf",
        "family": "in_use",
        "printed_page_offset": 4,  # printed p.6 = pdf p.10
        "unit_count": 60,
        "unit_page_length": 2,
        "first_unit_pdf_page": 10,
        "last_unit_pdf_page": 129,
        "theory_page_rule": "left_page",
        "exercise_page_rule": "right_page",
        "answer_key_pdf_pages": [130, 161],
        "index_pdf_pages": [162, 193],
        "wordlist_available": False,
        "recording_scripts_available": False,
        "audio_references": False,
        "audio_files_available": False,
        "text_layer": True,
        "scanned": False,
        "extraction_limitations": ["No native PDF bookmarks; table of contents reconstructed from text layer"],
    },
    "ECI-ADV": {
        "title": "English Collocations in Use Advanced",
        "edition": "2nd Edition",
        "authors": ["Felicity O'Dell", "Michael McCarthy"],
        "publisher": "Cambridge University Press",
        "filename": "ECI-ADV.pdf",
        "family": "in_use",
        "printed_page_offset": 4,  # printed p.6 = pdf p.10
        "unit_count": 60,
        "unit_page_length": 2,
        "first_unit_pdf_page": 10,
        "last_unit_pdf_page": 129,
        "theory_page_rule": "left_page",
        "exercise_page_rule": "right_page",
        "answer_key_pdf_pages": [128, 163],
        "index_pdf_pages": [164, 192],
        "wordlist_available": False,
        "recording_scripts_available": False,
        "audio_references": False,
        "audio_files_available": False,
        "text_layer": True,
        "scanned": False,
        "extraction_limitations": [],
    },
    "AVU": {
        "title": "Academic Vocabulary in Use",
        "edition": "Second Edition",
        "authors": ["Michael McCarthy", "Felicity O'Dell"],
        "publisher": "Cambridge University Press",
        "filename": "AVU.pdf",
        "family": "in_use",
        "printed_page_offset": 2,  # printed p.8 = pdf p.10 (Unit 0); printed p.10 = pdf p.12 (Unit 1)
        "unit_count": 51,  # Unit 0 + Units 1-50
        "unit_page_length": 2,
        "unit_zero_pdf_pages": [10, 11],
        "first_unit_pdf_page": 12,
        "last_unit_pdf_page": 111,
        "theory_page_rule": "left_page",
        "exercise_page_rule": "right_page",
        "reading_disciplines_pdf_pages": [112, 117],
        "reference_sections_pdf_pages": [118, 133],
        "answer_key_pdf_pages": [134, 163],
        "phonemic_symbols_pdf_page": 164,
        "index_pdf_pages": [165, 176],
        "wordlist_available": False,
        "recording_scripts_available": False,
        "audio_references": False,
        "audio_files_available": False,
        "text_layer": True,
        "scanned": False,
        "extraction_limitations": [],
    },
    "IVU-60": {
        "title": "Cambridge Vocabulary for IELTS with answers (Band 6.0)",
        "edition": "Self-study vocabulary practice",
        "authors": ["Pauline Cullen"],
        "publisher": "Cambridge University Press",
        "filename": "IVU-60.pdf",
        "family": "ielts_vocab",
        "printed_page_offset": 2,  # printed p.8 = pdf p.10
        "unit_count": 25,
        "review_test_count": 5,
        "first_unit_pdf_page": 10,
        "last_unit_pdf_page": 133,  # Unit 25 ends p. 129, Test 5 is p. 132-133
        "theory_page_rule": "multi_page_contextual",
        "exercise_page_rule": "integrated_exercises_and_test_practice",
        "answer_key_pdf_pages": [134, 158],
        "recording_scripts_pdf_pages": [159, 168],
        "wordlist_pdf_pages": [169, 175],
        "tracklist_pdf_page": 177,
        "wordlist_available": True,
        "recording_scripts_available": True,
        "audio_references": True,
        "audio_files_available": False,
        "text_layer": False,
        "scanned": True,
        "extraction_limitations": [
            "Scanned PDF with zero text layer requiring OCR",
            "Very large file size (~442 MB) requiring bounded page-by-page / unit-by-unit processing",
            "Referenced audio tracks (1a - 38b) missing locally; transcripts preserved for study",
        ],
    },
    "IVU-65": {
        "title": "Cambridge Vocabulary for IELTS Advanced with answers (Band 6.5 and above)",
        "edition": "Self-study vocabulary practice",
        "authors": ["Pauline Cullen"],
        "publisher": "Cambridge University Press",
        "filename": "IVU-65.pdf",
        "family": "ielts_vocab",
        "printed_page_offset": 3,  # printed p.8 = pdf p.11
        "unit_count": 25,
        "first_unit_pdf_page": 11,
        "last_unit_pdf_page": 134,  # Unit 25 ends p. 134 (printed 131)
        "theory_page_rule": "multi_page_contextual",
        "exercise_page_rule": "integrated_exercises_and_test_practice",
        "answer_key_pdf_pages": [135, 158],
        "recording_scripts_pdf_pages": [159, 170],
        "wordlist_pdf_pages": [171, 175],
        "wordlist_available": True,
        "recording_scripts_available": True,
        "audio_references": True,
        "audio_files_available": False,
        "text_layer": False,
        "scanned": True,
        "extraction_limitations": [
            "Scanned PDF with zero text layer requiring OCR",
            "Referenced audio tracks (1 - 26) missing locally; transcripts preserved for study",
        ],
    },
    "NB-PARA": {
        "title": "How to Paraphrase in the IELTS Test (Sách Hướng Dẫn Paraphrase Trong IELTS Test)",
        "edition": "2021 Edition (note: 2026 edition also available in TÀI LIỆU THẦY NGOCBACH 2026/)",
        "authors": ["Nguyen Ngoc Bach"],
        "publisher": "ngocbach.com",
        "filename": "NB-PARA.pdf",
        "family": "ngocbach_paraphrase",
        "printed_page_offset": 0,  # printed page = physical page
        "unit_count": 7,  # Task 1 General, Task 1 Particular, Task 2 General, Task 2 Particular, Task 2 Topics, Practice Sections (Education, Work, Crime, Environment, Transport)
        "first_unit_pdf_page": 3,
        "last_unit_pdf_page": 51,
        "theory_page_rule": "heading_based_strategies",
        "exercise_page_rule": "practice_paraphrase_lists",
        "practice_topics_pdf_pages": {
            "Education": [30, 34],
            "Work": [35, 38],
            "Crime": [39, 42],
            "Environment": [43, 46],
            "Transport": [47, 51],
        },
        "answer_key_pdf_pages": None,  # Bilingual examples and paraphrase groups are self-contained
        "wordlist_available": True,
        "recording_scripts_available": False,
        "audio_references": False,
        "audio_files_available": False,
        "text_layer": True,
        "scanned": False,
        "extraction_limitations": [
            "Contains repetitive commercial furniture (hotline, website course promos) needing normalization",
            "Not all expressions in paraphrase groups are interchangeable synonyms; requires distinction in register, degree and grammar",
        ],
    },
}


def compute_sha256(path: Path) -> str:
    """Computes SHA-256 hash using streaming chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_source_sha256(
    source_id: str,
    sources_file: Optional[Path] = None,
    pdf_path: Optional[Path] = None,
) -> Optional[str]:
    """Resolves expected SHA-256 for a source from sources.json or by hashing pdf_path."""
    s_file = sources_file or (VOCAB_KB_DIR / "sources.json")
    if s_file.exists():
        try:
            with open(s_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            sha = data.get("sources", {}).get(source_id, {}).get("sha256")
            if sha:
                return sha
        except Exception:
            pass

    target_pdf = pdf_path
    if target_pdf is None and source_id in SOURCE_METADATA_CONFIG:
        candidate = VOCAB_RAW_DIR / SOURCE_METADATA_CONFIG[source_id]["filename"]
        if candidate.exists():
            target_pdf = candidate

    if target_pdf is not None and target_pdf.exists():
        return compute_sha256(target_pdf)
    return None


def extract_outline_titles(pdf: pikepdf.Pdf) -> List[str]:
    """Extracts top-level bookmark titles from outline if present."""
    titles = []
    try:
        outline = pdf.open_outline()
        for item in outline.root:
            titles.append(str(item.title))
    except Exception:
        pass
    return titles


def build_source_inventory() -> Dict[str, Any]:
    """Builds comprehensive inventory of the 8 vocabulary books."""
    inventory = {
        "version": "1.0.0",
        "sources": {},
        "summary": {
            "total_sources": 8,
            "text_layer_sources": 6,
            "scanned_sources": 2,
            "total_pages": 0,
            "total_size_bytes": 0,
        },
    }

    total_pages = 0
    total_size = 0

    for source_id, meta in SOURCE_METADATA_CONFIG.items():
        pdf_path = VOCAB_RAW_DIR / meta["filename"]
        if not pdf_path.exists():
            raise FileNotFoundError(f"Required vocabulary textbook not found: {pdf_path}")

        file_size = pdf_path.stat().st_size
        sha256_hash = compute_sha256(pdf_path)

        with pikepdf.open(pdf_path) as pdf:
            pdf_page_count = len(pdf.pages)
            docinfo = {}
            if pdf.docinfo:
                docinfo = {str(k): str(v) for k, v in pdf.docinfo.items()}
            outline_titles = extract_outline_titles(pdf)

        total_pages += pdf_page_count
        total_size += file_size

        inventory["sources"][source_id] = {
            "source_id": source_id,
            "filename": meta["filename"],
            "relative_path": str(pdf_path.relative_to(REPO_ROOT)),
            "sha256": sha256_hash,
            "file_size_bytes": file_size,
            "file_size_mb": round(file_size / (1024 * 1024), 2),
            "pdf_page_count": pdf_page_count,
            "title": meta["title"],
            "edition": meta["edition"],
            "authors": meta["authors"],
            "publisher": meta["publisher"],
            "family": meta["family"],
            "printed_page_offset": meta["printed_page_offset"],
            "unit_count": meta["unit_count"],
            "first_unit_pdf_page": meta["first_unit_pdf_page"],
            "last_unit_pdf_page": meta["last_unit_pdf_page"],
            "theory_page_rule": meta["theory_page_rule"],
            "exercise_page_rule": meta["exercise_page_rule"],
            "answer_key_pdf_pages": meta["answer_key_pdf_pages"],
            "index_pdf_pages": meta.get("index_pdf_pages"),
            "wordlist_available": meta["wordlist_available"],
            "recording_scripts_available": meta["recording_scripts_available"],
            "audio_references": meta["audio_references"],
            "audio_files_available": meta["audio_files_available"],
            "text_layer": meta["text_layer"],
            "scanned": meta["scanned"],
            "bookmarks_count": len(outline_titles),
            "top_bookmarks": outline_titles[:10],
            "docinfo": docinfo,
            "extraction_limitations": meta["extraction_limitations"],
        }

    inventory["summary"]["total_pages"] = total_pages
    inventory["summary"]["total_size_bytes"] = total_size
    inventory["summary"]["total_size_mb"] = round(total_size / (1024 * 1024), 2)

    return inventory


def save_source_inventory(output_dir: Path = VOCAB_KB_DIR) -> Path:
    """Saves inventory to private/knowledge/vocabulary/sources.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    inv = build_source_inventory()
    out_file = output_dir / "sources.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(inv, f, indent=2, ensure_ascii=False)
    return out_file


if __name__ == "__main__":
    out = save_source_inventory()
    print(f"Source inventory generated successfully: {out}")
