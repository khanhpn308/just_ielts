"""Page-aware hybrid extraction router adapter for mixed and standard PDFs."""

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


class PdfRouterExtractor(BaseExtractor):
    """
    Adapter providing page-aware extraction routing for PDFs:
    - Uses native text extraction when reliable (>= threshold characters).
    - Routes to OCR (pdftoppm + Tesseract) for scanned/image-only pages.
    - Flags ambiguous (very low text density) or unexpectedly empty pages.
    - Preserves page-level routing provenance.
    """

    _ocr_semaphore = threading.Semaphore(MAX_OCR_WORKERS)

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        default_config = {
            "min_native_chars": cfg.get("min_native_chars", 50),
            "ambiguous_threshold": cfg.get("ambiguous_threshold", 20),
            "dpi": cfg.get("dpi", OCR_DPI),
            "lang": cfg.get("lang", OCR_LANG),
            "psm": cfg.get("psm", OCR_PSM),
            "max_workers": cfg.get("max_workers", MAX_OCR_WORKERS),
        }
        super().__init__(
            name="pdf_router",
            version=PARSER_VERSIONS["pdf_router"],
            config=default_config,
        )
        self.min_native_chars = self.config["min_native_chars"]
        self.ambiguous_threshold = self.config["ambiguous_threshold"]
        self.dpi = self.config["dpi"]
        self.lang = self.config["lang"]
        self.psm = self.config["psm"]

    def get_processing_units(self, source_record: Dict[str, Any]) -> List[str]:
        """Returns unit list for every page in the PDF."""
        pikepdf = require_python_module("pikepdf", pip_package="pikepdf", feature_description="PDF router processing")
        file_path = REPO_ROOT / source_record["relative_path"]
        with pikepdf.open(file_path) as pdf:
            total_pages = len(pdf.pages)
        return [f"page_{p:04d}" for p in range(1, total_pages + 1)]

    def _ocr_page(self, file_path: Path, page_num: int) -> str:
        """Executes OCR on a single PDF page and returns recognized text."""
        cmd_pdftoppm = require_system_tool(
            "pdftoppm", system_package="poppler-utils", feature_description="PDF rendering for OCR"
        )
        cmd_tesseract = require_system_tool(
            "tesseract", system_package="tesseract-ocr", feature_description="Optical character recognition"
        )

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

                return res_ocr.stdout.strip()

    def extract_unit(
        self,
        source_record: Dict[str, Any],
        output_dir: Path,
        unit_identifier: str,
    ) -> Dict[str, Any]:
        """Extracts a single page using page-aware routing."""
        pikepdf = require_python_module("pikepdf", pip_package="pikepdf", feature_description="PDF router processing")
        pdfminer_hl = require_python_module(
            "pdfminer.high_level", pip_package="pdfminer.six", feature_description="PDF text extraction"
        )
        extract_text = pdfminer_hl.extract_text

        file_path = REPO_ROOT / source_record["relative_path"]
        page_num = int(unit_identifier.replace("page_", ""))
        page_idx = page_num - 1

        with pikepdf.open(file_path) as pdf:
            total_pages = len(pdf.pages)

        if page_num < 1 or page_num > total_pages:
            raise ValueError(f"Requested page {page_num} out of bounds (1..{total_pages})")

        # 1. Attempt native text extraction
        native_text = ""
        try:
            raw_text = extract_text(str(file_path), page_numbers=[page_idx]) or ""
            native_text = raw_text.strip()
        except Exception:
            native_text = ""

        native_char_count = len(native_text)
        flags: List[str] = []

        # 2. Page routing decision
        if native_char_count >= self.min_native_chars:
            # Native text extraction is reliable
            chosen_method = "native"
            final_text = native_text
            ocr_applied = False
            ocr_char_count = 0
            validity = "valid"
        else:
            # Low or zero native text: perform OCR inspection
            ocr_text = self._ocr_page(file_path, page_num)
            ocr_char_count = len(ocr_text)

            if ocr_char_count >= self.min_native_chars or (
                ocr_char_count > native_char_count and ocr_char_count >= self.ambiguous_threshold
            ):
                chosen_method = "ocr"
                final_text = ocr_text
                ocr_applied = True
                validity = "valid"
            elif native_char_count == 0 and ocr_char_count == 0:
                # Unexpectedly empty page
                chosen_method = "none"
                final_text = ""
                ocr_applied = False
                flags.append("unexpectedly_empty")
                validity = "empty"
            else:
                # Ambiguous low text density (between 1 and threshold chars)
                if ocr_char_count > native_char_count:
                    chosen_method = "ocr"
                    final_text = ocr_text
                    ocr_applied = True
                else:
                    chosen_method = "native"
                    final_text = native_text
                    ocr_applied = False
                flags.append("ambiguous_text_density")
                validity = "ambiguous"

        # 3. Assemble provenance with page routing metadata
        provenance = self.build_provenance(
            source_record=source_record,
            processing_unit="page",
            unit_identifier=unit_identifier,
        )
        provenance["routing_decision"] = chosen_method

        payload = {
            "provenance": provenance,
            "content": {
                "page_number": page_num,
                "total_pages": total_pages,
                "char_count": len(final_text),
                "text": final_text,
                "ocr_applied": ocr_applied,
                "routing_decision": chosen_method,
                "native_char_count": native_char_count,
                "ocr_char_count": ocr_char_count,
                "flags": flags,
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
            "output_validity": validity,
        }
