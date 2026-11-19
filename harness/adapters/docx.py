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

    @staticmethod
    def _parse_paragraph(p_elem: Any, ns: Dict[str, str], seq_idx: int) -> Dict[str, Any]:
        """Parses a paragraph element into text and formatting runs."""
        p_text = "".join(p_elem.xpath(".//w:t/text()", namespaces=ns)).strip()
        runs = []
        for r in p_elem.xpath(".//w:r", namespaces=ns):
            r_text = "".join(r.xpath(".//w:t/text()", namespaces=ns))
            if not r_text:
                continue
            is_bold = bool(r.xpath(".//w:rPr/w:b", namespaces=ns))
            is_italic = bool(r.xpath(".//w:rPr/w:i", namespaces=ns))
            runs.append({"text": r_text, "bold": is_bold, "italic": is_italic})
        return {
            "index": seq_idx,
            "text": p_text,
            "runs": runs,
        }

    @staticmethod
    def _parse_table(tbl_elem: Any, ns: Dict[str, str], seq_idx: int) -> Dict[str, Any]:
        """Parses a table element into structured rows and cells without leaking top-level paragraphs."""
        rows_data = []
        for tr in tbl_elem.xpath("./w:tr", namespaces=ns):
            row_cells = []
            for tc in tr.xpath("./w:tc", namespaces=ns):
                cell_text = " ".join(
                    "".join(p.xpath(".//w:t/text()", namespaces=ns)).strip()
                    for p in tc.xpath("./w:p", namespaces=ns)
                ).strip()
                row_cells.append(cell_text)
            rows_data.append(row_cells)
        return {"index": seq_idx, "rows": rows_data}

    def extract_unit(
        self,
        source_record: Dict[str, Any],
        output_dir: Path,
        unit_identifier: str = "raw_document",
    ) -> Dict[str, Any]:
        """Extracts structured paragraphs, formatting runs, and tables preserving block reading order."""
        lxml_etree = require_python_module("lxml.etree", pip_package="lxml", feature_description="DOCX parsing")
        etree = lxml_etree

        file_path = REPO_ROOT / source_record["relative_path"]
        ns = {"w": self.W_NS}

        with zipfile.ZipFile(file_path, "r") as z:
            if "word/document.xml" not in z.namelist():
                raise ValueError("word/document.xml not found in DOCX package")
            xml_bytes = z.read("word/document.xml")
            tree = etree.fromstring(xml_bytes)

            body_nodes = tree.xpath("//w:body", namespaces=ns)
            if not body_nodes:
                raise ValueError("w:body not found in word/document.xml")
            body = body_nodes[0]

            def _walk_container(container: Any, current_seq: int):
                container_blocks = []
                container_paragraphs = []
                container_tables = []

                for child in container.iterchildren():
                    qname = etree.QName(child)
                    if qname.namespace != self.W_NS:
                        continue
                    tag = qname.localname

                    if tag == "p":
                        p_data = self._parse_paragraph(child, ns, current_seq)
                        if p_data["text"] or p_data["runs"]:
                            block_item = {"type": "paragraph", **p_data}
                            container_blocks.append(block_item)
                            container_paragraphs.append(p_data)
                            current_seq += 1
                    elif tag == "tbl":
                        t_data = self._parse_table(child, ns, current_seq)
                        block_item = {"type": "table", **t_data}
                        container_blocks.append(block_item)
                        container_tables.append(t_data)
                        current_seq += 1
                    elif tag == "sdt":
                        sdt_contents = child.xpath("./w:sdtContent", namespaces=ns)
                        if sdt_contents:
                            s_blocks, s_p, s_t, current_seq = _walk_container(sdt_contents[0], current_seq)
                            container_blocks.extend(s_blocks)
                            container_paragraphs.extend(s_p)
                            container_tables.extend(s_t)

                return container_blocks, container_paragraphs, container_tables, current_seq

            blocks_data, paragraphs_data, tables_data, _ = _walk_container(body, 0)

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
                "block_count": len(blocks_data),
                "blocks": blocks_data,
                "paragraphs": paragraphs_data,
                "tables": tables_data,
            },
        }

        target_file = output_dir / f"{unit_identifier}.json"
        out_sha256, out_size = self.atomic_write_json(target_file, payload)

        validity = "valid" if (paragraphs_data or tables_data or blocks_data) else "empty"

        return {
            "processing_unit": "document",
            "unit_identifier": unit_identifier,
            "output_path": str(target_file),
            "output_sha256": out_sha256,
            "output_size": out_size,
            "status": "COMPLETED",
            "output_validity": validity,
        }
