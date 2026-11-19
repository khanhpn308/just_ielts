"""Document format classifier and parser router for Harness V0.1."""

from pathlib import Path
from typing import Any, Dict, Optional

from harness.config import REPO_ROOT
from harness.dependencies import require_python_module


def classify_pdf(file_path: Path) -> Dict[str, Any]:
    """
    Inspects a PDF document to determine page count, text density,
    and whether it is digital, scanned, or mixed.
    Lazily imports pikepdf and pdfminer.
    """
    pikepdf = require_python_module("pikepdf", pip_package="pikepdf", feature_description="PDF inspection")
    pdfminer_hl = require_python_module("pdfminer.high_level", pip_package="pdfminer.six", feature_description="PDF text density profiling")
    extract_text = pdfminer_hl.extract_text

    try:
        with pikepdf.open(file_path) as pdf:
            total_pages = len(pdf.pages)
    except Exception as e:
        return {
            "category": "pdf",
            "subtype": "corrupt_pdf",
            "page_count": 0,
            "recommended_adapter": None,
            "accessibility": "unreadable",
            "error": str(e),
        }

    if total_pages == 0:
        return {
            "category": "pdf",
            "subtype": "empty_pdf",
            "page_count": 0,
            "recommended_adapter": None,
            "accessibility": "unreadable",
        }

    # Sample up to 5 representative pages for text density check
    sample_indices = [0]
    if total_pages > 1:
        sample_indices.append(total_pages - 1)
    if total_pages > 2:
        sample_indices.append(total_pages // 2)
    if total_pages > 5:
        sample_indices.extend([total_pages // 4, (3 * total_pages) // 4])
    sample_indices = sorted(list(set(sample_indices)))

    total_chars = 0
    sampled_pages = 0

    for idx in sample_indices:
        try:
            txt = extract_text(str(file_path), page_numbers=[idx]) or ""
            total_chars += len(txt.strip())
            sampled_pages += 1
        except Exception:
            pass

    avg_chars = total_chars / max(1, sampled_pages)

    if avg_chars > 100:
        subtype = "digital_pdf"
        adapter = "pdf_native"
    elif avg_chars < 20:
        subtype = "scanned_pdf"
        adapter = "pdf_ocr"
    else:
        subtype = "mixed_pdf"
        adapter = "pdf_ocr"  # Default mixed to OCR to ensure text capture

    return {
        "category": "pdf",
        "subtype": subtype,
        "page_count": total_pages,
        "avg_sample_chars": avg_chars,
        "recommended_adapter": adapter,
        "accessibility": "accessible",
    }


def classify_source(source_record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Classifies a source record based on extension, accessibility, and content inspection.
    """
    rel_path = source_record["relative_path"]
    file_path = REPO_ROOT / rel_path
    ext = source_record.get("extension", "").lower()
    filename = source_record.get("filename", "")

    # Check unreadable lock files
    if filename.startswith("~$") or source_record.get("accessibility_status") == "unreadable":
        return {
            "category": "lock_file",
            "subtype": "unreadable",
            "page_count": 0,
            "recommended_adapter": None,
            "accessibility": "unreadable",
        }

    if not file_path.exists():
        return {
            "category": "missing",
            "subtype": "file_not_found",
            "page_count": 0,
            "recommended_adapter": None,
            "accessibility": "unreadable",
        }

    if ext == ".pdf":
        return classify_pdf(file_path)

    if ext == ".docx":
        return {
            "category": "docx",
            "subtype": "openxml_word",
            "page_count": 0,
            "recommended_adapter": "docx",
            "accessibility": "accessible",
        }

    if ext == ".xlsx":
        return {
            "category": "xlsx",
            "subtype": "openxml_sheet",
            "page_count": 0,
            "recommended_adapter": "xlsx",
            "accessibility": "accessible",
        }

    if ext in [".mp3", ".wav", ".m4a"]:
        return {
            "category": "audio",
            "subtype": ext.lstrip("."),
            "page_count": 0,
            "recommended_adapter": "audio_meta",
            "accessibility": "accessible",
        }

    if ext == ".mp4":
        return {
            "category": "video_media",
            "subtype": "mp4",
            "page_count": 0,
            "recommended_adapter": "audio_meta",
            "accessibility": "accessible",
        }

    return {
        "category": "other",
        "subtype": ext.lstrip("."),
        "page_count": 0,
        "recommended_adapter": None,
        "accessibility": "metadata_only",
    }
