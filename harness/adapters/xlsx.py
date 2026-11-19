"""OpenXML XLSX spreadsheet extractor adapter using lxml and zipfile."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import zipfile

from harness.adapters.base import BaseExtractor
from harness.config import PARSER_VERSIONS, REPO_ROOT
from harness.dependencies import require_python_module


class XlsxExtractor(BaseExtractor):
    """Adapter for Microsoft Excel XLSX workbooks."""

    MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(
            name="xlsx",
            version=PARSER_VERSIONS["xlsx"],
            config=config or {"skip_empty_rows": True},
        )

    def get_processing_units(self, source_record: Dict[str, Any]) -> List[str]:
        """XLSX workbooks are processed as a single sheets unit in V0.1."""
        return ["raw_sheets"]

    def extract_unit(
        self,
        source_record: Dict[str, Any],
        output_dir: Path,
        unit_identifier: str = "raw_sheets",
    ) -> Dict[str, Any]:
        """Extracts all worksheets, coordinates, types, and cell values from XLSX."""
        lxml_etree = require_python_module("lxml.etree", pip_package="lxml", feature_description="XLSX parsing")
        etree = lxml_etree

        file_path = REPO_ROOT / source_record["relative_path"]

        ns_m = {"m": self.MAIN_NS}
        ns_rel = {"pr": self.REL_NS}

        sheets_data = []
        relationships = {}

        with zipfile.ZipFile(file_path, "r") as z:
            # 1. Read shared strings
            shared_strings: List[str] = []
            if "xl/sharedStrings.xml" in z.namelist():
                sst_xml = z.read("xl/sharedStrings.xml")
                sst_tree = etree.fromstring(sst_xml)
                for si in sst_tree.xpath("//m:si", namespaces=ns_m):
                    shared_strings.append("".join(si.xpath(".//m:t/text()", namespaces=ns_m)))

            # 2. Read relationship targets
            rel_map = {}
            if "xl/_rels/workbook.xml.rels" in z.namelist():
                rels_xml = z.read("xl/_rels/workbook.xml.rels")
                rels_tree = etree.fromstring(rels_xml)
                for r in rels_tree.xpath("//pr:Relationship", namespaces=ns_rel):
                    rel_id = r.attrib.get("Id")
                    rel_type = r.attrib.get("Type", "")
                    raw_target = r.attrib.get("Target", "")
                    target = raw_target.lstrip("/")
                    if target and not target.startswith("xl/"):
                        target = f"xl/{target}"
                    rel_map[rel_id] = target
                    relationships[rel_id] = {"type": rel_type, "target": target}

            # 3. Read workbook definition
            wb_xml = z.read("xl/workbook.xml")
            wb_tree = etree.fromstring(wb_xml)

            for s in wb_tree.xpath("//m:sheet", namespaces=ns_m):
                sheet_name = s.attrib.get("name", "UnknownSheet")
                sheet_id = s.attrib.get("sheetId", "")
                state = s.attrib.get("state", "visible")
                is_hidden = state in ["hidden", "veryHidden"]
                r_id = s.attrib.get(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
                ) or s.attrib.get("r:id")

                target_file = rel_map.get(r_id)
                # Attempt fallback if not in rel_map
                if not target_file:
                    fallback = f"xl/worksheets/sheet{sheet_id}.xml"
                    if fallback in z.namelist():
                        target_file = fallback

                # Do not silently skip when unresolvable
                if not target_file or target_file not in z.namelist():
                    sheets_data.append(
                        {
                            "name": sheet_name,
                            "sheet_id": sheet_id,
                            "state": state,
                            "is_hidden": is_hidden,
                            "relationship_id": r_id,
                            "target_file": target_file,
                            "resolved": False,
                            "error": f"Worksheet target '{target_file}' could not be resolved in package",
                            "row_count": 0,
                            "rows": [],
                            "merged_ranges": [],
                        }
                    )
                    continue

                sheet_xml = z.read(target_file)
                sheet_tree = etree.fromstring(sheet_xml)

                # Extract merged cell ranges
                merged_ranges = []
                for mc in sheet_tree.xpath("//m:mergeCells/m:mergeCell", namespaces=ns_m):
                    ref = mc.attrib.get("ref")
                    if ref:
                        merged_ranges.append(ref)

                rows_data = []
                for row_node in sheet_tree.xpath("//m:row", namespaces=ns_m):
                    r_num = row_node.attrib.get("r", "")
                    cells_data = []
                    has_content = False

                    for c in row_node.xpath(".//m:c", namespaces=ns_m):
                        coord = c.attrib.get("r", "")
                        cell_type = c.attrib.get("t", "n")
                        val = "".join(c.xpath(".//m:v/text()", namespaces=ns_m)).strip()
                        formula = "".join(c.xpath(".//m:f/text()", namespaces=ns_m)).strip()

                        if cell_type == "s" and val.isdigit():
                            idx = int(val)
                            val = shared_strings[idx] if idx < len(shared_strings) else val
                        elif cell_type == "inlineStr":
                            val = "".join(c.xpath(".//m:t/text()", namespaces=ns_m)).strip()

                        if val or formula:
                            has_content = True

                        cell_entry = {"coord": coord, "type": cell_type, "value": val}
                        if formula:
                            cell_entry["formula"] = formula
                        cells_data.append(cell_entry)

                    if has_content or not self.config.get("skip_empty_rows", True):
                        rows_data.append({"row": r_num, "cells": cells_data})

                sheets_data.append(
                    {
                        "name": sheet_name,
                        "sheet_id": sheet_id,
                        "state": state,
                        "is_hidden": is_hidden,
                        "relationship_id": r_id,
                        "target_file": target_file,
                        "resolved": True,
                        "merged_ranges": merged_ranges,
                        "row_count": len(rows_data),
                        "rows": rows_data,
                    }
                )

        provenance = self.build_provenance(
            source_record=source_record,
            processing_unit="sheets",
            unit_identifier=unit_identifier,
        )

        payload = {
            "provenance": provenance,
            "content": {
                "sheet_count": len(sheets_data),
                "relationships": relationships,
                "sheets": sheets_data,
            },
        }

        target_file = output_dir / f"{unit_identifier}.json"
        out_sha256, out_size = self.atomic_write_json(target_file, payload)

        return {
            "processing_unit": "sheets",
            "unit_identifier": unit_identifier,
            "output_path": str(target_file),
            "output_sha256": out_sha256,
            "output_size": out_size,
            "status": "COMPLETED",
            "output_validity": "valid" if sheets_data else "empty",
        }
