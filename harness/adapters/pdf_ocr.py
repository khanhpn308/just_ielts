"""Optical Character Recognition (OCR) extractor adapter for scanned PDFs."""

import glob
from pathlib import Path
import subprocess
import tempfile
import threading
from typing import Any, Dict, List, Optional

from harness.adapters.base import BaseExtractor
from harness.config import (
    MAX_OCR_WORKERS,
    OCR_DPI,
    OCR_LANG,
    OCR_PSM,
    PARSER_VERSIONS,
    REPO_ROOT,
)
from harness.dependencies import require_python_module, require_system_tool


class PdfOcrExtractor(BaseExtractor):
    """Adapter for scanned or image-based PDFs using pdftoppm and Tesseract OCR."""

    _ocr_semaphore = threading.Semaphore(MAX_OCR_WORKERS)

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        default_config = {
            "dpi": cfg.get("dpi", OCR_DPI),
            "lang": cfg.get("lang", OCR_LANG),
            "psm": cfg.get("psm", OCR_PSM),
            "max_workers": cfg.get("max_workers", MAX_OCR_WORKERS),
        }
        super().__init__(
            name="pdf_ocr",
            version=PARSER_VERSIONS["pdf_ocr"],
            config=default_config,
        )
        self.dpi = self.config["dpi"]
        self.lang = self.config["lang"]
        self.psm = self.config["psm"]

    def get_processing_units(self, source_record: Dict[str, Any]) -> List[str]:
        """Returns unit list for every page in the PDF."""
        pikepdf = require_python_module("pikepdf", pip_package="pikepdf", feature_description="PDF OCR processing")
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
        """Renders a single page to PNG, executes Tesseract OCR, and immediately cleans up raster files."""
        # Verify required system dependencies
        cmd_pdftoppm = require_system_tool("pdftoppm", system_package="poppler-utils", feature_description="PDF rendering for OCR")
        cmd_tesseract = require_system_tool("tesseract", system_package="tesseract-ocr", feature_description="Optical character recognition")
        pikepdf = require_python_module("pikepdf", pip_package="pikepdf", feature_description="PDF OCR processing")

        file_path = REPO_ROOT / source_record["relative_path"]
        page_num = int(unit_identifier.replace("page_", ""))

        with pikepdf.open(file_path) as pdf:
            total_pages = len(pdf.pages)

        if page_num < 1 or page_num > total_pages:
            raise ValueError(f"Requested page {page_num} out of bounds (1..{total_pages})")

        ocr_text = ""
        # Acquire semaphore to bound concurrent OCR execution and memory usage
        with self._ocr_semaphore:
            with tempfile.TemporaryDirectory() as tmpdir:
                prefix = Path(tmpdir) / "render"
                cmd_render = [
                    cmd_pdftoppm,
                    "-png",
                    "-r",
                    str(self.dpi),
                    "-f",
                    str(page_num),
                    "-l",
                    str(page_num),
                    str(file_path),
                    str(prefix),
                ]
                res_render = subprocess.run(
                    cmd_render,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res_render.returncode != 0:
                    raise RuntimeError(f"pdftoppm failed on page {page_num}: {res_render.stderr}")

                png_matches = glob.glob(f"{prefix}*.png")
                if not png_matches:
                    raise FileNotFoundError(f"pdftoppm produced no image for page {page_num}")

                rendered_png = png_matches[0]

                cmd_ocr = [
                    cmd_tesseract,
                    rendered_png,
                    "stdout",
                    "-l",
                    self.lang,
                    "--psm",
                    str(self.psm),
                ]
                res_ocr = subprocess.run(
                    cmd_ocr,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res_ocr.returncode != 0:
                    raise RuntimeError(f"tesseract failed on page {page_num}: {res_ocr.stderr}")

                ocr_text = res_ocr.stdout.strip()
                # TemporaryDirectory automatically cleans up rendered PNG on context exit

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
                "char_count": len(ocr_text),
                "text": ocr_text,
                "ocr_applied": True,
                "ocr_engine": "tesseract",
                "ocr_lang": self.lang,
                "render_dpi": self.dpi,
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
            "output_validity": "valid" if len(ocr_text) > 0 else "empty",
        }
