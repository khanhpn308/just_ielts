"""OpenXML DOCX document extractor adapter using lxml and zipfile."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import zipfile

from harness.adapters.base import BaseExtractor
from harness.config import PARSER_VERSIONS, REPO_ROOT
from harness.dependencies import require_python_module


class DocxExtractor(BaseExtractor):
    """Adapter for Microsoft Word DOCX files."""

    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(
            name="docx",
            version=PARSER_VERSIONS["docx"],
            config=config or {"extract_runs": True, "extract_tables": True},
        )

    def get_processing_units(self, source_record: Dict[str, Any]) -> List[str]:
        """DOCX files are processed as a single document unit in V0.1."""
        return ["raw_document"]

    def extract_unit(
        self,
        source_record: Dict[str, Any],
        output_dir: Path,
        unit_identifier: str = "raw_document",
    ) -> Dict[str, Any]:
        """Extracts structured paragraphs, formatting runs, and tables from DOCX."""
        lxml_etree = require_python_module("lxml.etree", pip_package="lxml", feature_description="DOCX parsing")
        etree = lxml_etree

        file_path = REPO_ROOT / source_record["relative_path"]

        ns = {"w": self.W_NS}
        paragraphs_data = []
        tables_data = []

        with zipfile.ZipFile(file_path, "r") as z:
            if "word/document.xml" not in z.namelist():
                raise ValueError("word/document.xml not found in DOCX package")
            xml_bytes = z.read("word/document.xml")
            tree = etree.fromstring(xml_bytes)

            # Extract paragraphs
            p_nodes = tree.xpath("//w:p", namespaces=ns)
            for idx, p in enumerate(p_nodes):
                p_text = "".join(p.xpath(".//w:t/text()", namespaces=ns)).strip()
                runs = []
                for r in p.xpath(".//w:r", namespaces=ns):
                    r_text = "".join(r.xpath(".//w:t/text()", namespaces=ns))
                    if not r_text:
                        continue
                    is_bold = bool(r.xpath(".//w:rPr/w:b", namespaces=ns))
                    is_italic = bool(r.xpath(".//w:rPr/w:i", namespaces=ns))
                    runs.append({"text": r_text, "bold": is_bold, "italic": is_italic})

                if p_text or runs:
                    paragraphs_data.append(
                        {
                            "index": idx,
                            "text": p_text,
                            "runs": runs,
                        }
                    )

            # Extract tables
            tbl_nodes = tree.xpath("//w:tbl", namespaces=ns)
            for tbl_idx, tbl in enumerate(tbl_nodes):
                rows_data = []
                for tr in tbl.xpath(".//w:tr", namespaces=ns):
                    row_cells = []
                    for tc in tr.xpath(".//w:tc", namespaces=ns):
                        cell_text = " ".join(
                            "".join(p.xpath(".//w:t/text()", namespaces=ns)).strip()
                            for p in tc.xpath(".//w:p", namespaces=ns)
                        ).strip()
                        row_cells.append(cell_text)
                    rows_data.append(row_cells)
                tables_data.append({"index": tbl_idx, "rows": rows_data})

        provenance = self.build_provenance(
            source_record=source_record,
            processing_unit="document",
            unit_identifier=unit_identifier,
        )

        payload = {
            "provenance": provenance,
            "content": {
                "paragraph_count": len(paragraphs_data),
                "table_count": len(tables_data),
                "paragraphs": paragraphs_data,
                "tables": tables_data,
            },
        }

        target_file = output_dir / f"{unit_identifier}.json"
        out_sha256, out_size = self.atomic_write_json(target_file, payload)

        validity = "valid" if (paragraphs_data or tables_data) else "empty"

        return {
            "processing_unit": "document",
            "unit_identifier": unit_identifier,
            "output_path": str(target_file),
            "output_sha256": out_sha256,
            "output_size": out_size,
            "status": "COMPLETED",
            "output_validity": validity,
        }
