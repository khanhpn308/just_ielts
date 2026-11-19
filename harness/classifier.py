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

    # Sample representative pages for page-level text density profiling
    if total_pages <= 20:
        sample_indices = list(range(total_pages))
    else:
        # Check first, last, middle, and distributed samples
        sample_indices = sorted(list(set([
            0, 1, total_pages - 1, total_pages - 2,
            total_pages // 4, total_pages // 2, (3 * total_pages) // 4,
            total_pages // 6, (5 * total_pages) // 6, total_pages // 3
        ])))

    digital_count = 0
    empty_or_image_count = 0
    low_density_count = 0
    total_inspected = 0
    total_chars = 0

    for idx in sample_indices:
        try:
            txt = extract_text(str(file_path), page_numbers=[idx]) or ""
            chars = len(txt.strip())
            total_chars += chars
            total_inspected += 1

            if chars >= 50:
                digital_count += 1
            elif chars == 0:
                empty_or_image_count += 1
            else:
                low_density_count += 1
        except Exception:
            pass

    avg_chars = total_chars / max(1, total_inspected)

    # Page-aware classification routing
    if digital_count > 0 and (empty_or_image_count > 0 or low_density_count > 0):
        # Definite mixed PDF with both digital text and scanned/empty pages
        subtype = "mixed_pdf"
        adapter = "pdf_router"
    elif empty_or_image_count == total_inspected:
        # Purely scanned / image-based PDF
        subtype = "scanned_pdf"
        adapter = "pdf_ocr"
    elif digital_count == total_inspected:
        # Purely digital text PDF
        subtype = "digital_pdf"
        adapter = "pdf_native"
    else:
        # Ambiguous or partially recognized text -> route with hybrid page-aware router
        subtype = "mixed_pdf"
        adapter = "pdf_router"

    return {
        "category": "pdf",
        "subtype": subtype,
        "page_count": total_pages,
        "avg_sample_chars": avg_chars,
        "digital_pages_sampled": digital_count,
        "empty_or_image_pages_sampled": empty_or_image_count,
        "low_density_pages_sampled": low_density_count,
        "total_pages_sampled": total_inspected,
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
