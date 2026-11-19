"""Native text extractor adapter for digital PDFs."""

from pathlib import Path
from typing import Any, Dict, List

from harness.adapters.base import BaseExtractor
from harness.config import PARSER_VERSIONS, REPO_ROOT
from harness.dependencies import require_python_module


class PdfNativeExtractor(BaseExtractor):
    """Adapter for digital PDFs with accessible text streams."""

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            name="pdf_native",
            version=PARSER_VERSIONS["pdf_native"],
            config=config or {"mode": "text_stream"},
        )

    def get_processing_units(self, source_record: Dict[str, Any]) -> List[str]:
        """Returns unit list for every page in the PDF."""
        pikepdf = require_python_module("pikepdf", pip_package="pikepdf", feature_description="PDF native extraction")
        file_path = REPO_ROOT / source_record["relative_path"]
        with pikepdf.open(file_path) as pdf:
            total_pages = len(pdf.pages)
        return [f"page_{p:04d}" for p in range(1, total_pages + 1)]

    def extract_unit(
        self,
        source_record: Dict[str, Any],
        output_dir: Path,
        unit_identifier: str,
    ) -> Dict[str, Any]:
        """Extracts text for a single page."""
        pikepdf = require_python_module("pikepdf", pip_package="pikepdf", feature_description="PDF native extraction")
        pdfminer_hl = require_python_module("pdfminer.high_level", pip_package="pdfminer.six", feature_description="PDF text extraction")
        extract_text = pdfminer_hl.extract_text

        file_path = REPO_ROOT / source_record["relative_path"]
        page_num = int(unit_identifier.replace("page_", ""))
        page_idx = page_num - 1

        with pikepdf.open(file_path) as pdf:
            total_pages = len(pdf.pages)

        # Extract text using pdfminer
        raw_text = extract_text(str(file_path), page_numbers=[page_idx]) or ""
        clean_text = raw_text.strip()

        provenance = self.build_provenance(
            source_record=source_record,
            processing_unit="page",
            unit_identifier=unit_identifier,
        )

        payload = {
            "provenance": provenance,
            "content": {
                "page_number": page_num,
                "total_pages": total_pages,
                "char_count": len(clean_text),
                "text": clean_text,
                "ocr_applied": False,
            },
        }

        target_file = output_dir / f"{unit_identifier}.json"
        out_sha256, out_size = self.atomic_write_json(target_file, payload)

        return {
            "processing_unit": "page",
            "unit_identifier": unit_identifier,
            "output_path": str(target_file),
            "output_sha256": out_sha256,
            "output_size": out_size,
            "status": "COMPLETED",
            "output_validity": "valid" if len(clean_text) > 0 else "empty",
        }
