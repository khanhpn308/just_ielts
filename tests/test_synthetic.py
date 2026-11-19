"""Unit and synthetic integration tests for IELTS Data Harness V0.1.

These tests run independently of the private corpus and can run on any clean checkout.
"""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Dict, List
import unittest.mock as mock
import zipfile
import pytest

from PIL import Image, ImageDraw
import pikepdf

from harness.adapters.docx import DocxExtractor
from harness.adapters.pdf_router import PdfRouterExtractor
from harness.adapters.xlsx import XlsxExtractor
from harness.classifier import classify_pdf
from harness.config import compute_config_hash
from harness.db import (
    check_checkpoint_validity,
    get_checkpoint,
    get_db_connection,
    init_db,
    list_sources,
    upsert_source,
)
from harness.engine import ExtractionEngine, get_adapter_for_source
from harness.inventory import scan_raw_sources, sync_inventory_to_db
from harness.validator import validate_all_staged, validate_json_file, validate_staged_source


# --- Synthetic File Helpers ---


def make_digital_pdf(output_path: Path, pages_text: List[str], pad: bool = True) -> Path:
    """Creates a synthetic digital PDF with valid text streams using pikepdf."""
    pdf = pikepdf.new()
    for text in pages_text:
        page = pdf.add_blank_page(page_size=(400, 300))
        # Ensure text is substantial enough (>= 50 chars) for digital classification when pad is True
        if pad and len(text) < 50:
            text = text + " " + ("Digital paragraph filler text to ensure valid density." * 2)
        # Escape parenthesis in text stream
        escaped_text = text.replace("(", r"\(").replace(")", r"\)")
        stream_content = f"BT /F1 18 Tf 50 250 Td ({escaped_text}) Tj ET".encode("utf-8")
        page.Contents = pdf.make_stream(stream_content)
        page.Resources = pikepdf.Dictionary(
            Font=pikepdf.Dictionary(
                F1=pikepdf.Dictionary(
                    Type=pikepdf.Name.Font,
                    Subtype=pikepdf.Name.Type1,
                    BaseFont=pikepdf.Name.Helvetica,
                )
            )
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(output_path)
    return output_path


def make_scanned_page_pdf(output_path: Path, text: str) -> Path:
    """Renders text as a raster bitmap image and saves as single-page PDF."""
    img = Image.new("RGB", (600, 200), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((40, 80), text, fill=(0, 0, 0))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PDF")
    return output_path


def make_mixed_pdf(output_path: Path, tmp_dir: Path) -> Path:
    """
    Creates a synthetic 4-page mixed PDF:
    - Page 1: Digital text (high density > 50 chars).
    - Page 2: Scanned bitmap text (0 native chars, recognized by OCR).
    - Page 3: Blank page (0 native chars, 0 OCR chars).
    - Page 4: Low density ambiguous text (5 chars).
    """
    p1_path = tmp_dir / "p1.pdf"
    make_digital_pdf(p1_path, ["This is page one with clear digital selectable text for native extraction."])

    p2_path = tmp_dir / "p2.pdf"
    make_scanned_page_pdf(p2_path, "SCANNED OCR TEXT HEADING")

    p4_path = tmp_dir / "p4.pdf"
    make_digital_pdf(p4_path, ["Test"], pad=False)

    mixed = pikepdf.open(p1_path)
    img_pdf = pikepdf.open(p2_path)
    mixed.pages.append(img_pdf.pages[0])
    # Page 3: Blank page
    mixed.add_blank_page(page_size=(400, 300))
    # Page 4: Low density
    p4_pdf = pikepdf.open(p4_path)
    mixed.pages.append(p4_pdf.pages[0])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    mixed.save(output_path)
    return output_path


def make_synthetic_docx(output_path: Path) -> Path:
    """Creates a synthetic DOCX with alternating paragraphs and tables."""
    doc_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>First Paragraph</w:t></w:r></w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Cell 1A</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Cell 1B</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
    <w:p><w:r><w:t>Second Paragraph</w:t></w:r></w:p>
  </w:body>
</w:document>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        z.writestr("word/document.xml", doc_xml)
    return output_path


def make_synthetic_xlsx(output_path: Path) -> Path:
    """Creates a synthetic XLSX with formulas, merged cells, and hidden sheets."""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
</Relationships>"""
    wb = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="VisibleSheet" sheetId="1" r:id="rId1"/>
    <sheet name="HiddenSheet" sheetId="2" state="hidden" r:id="rId2"/>
    <sheet name="UnresolvedSheet" sheetId="3" r:id="rIdUnresolved"/>
  </sheets>
</workbook>"""
    sh1 = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="n"><v>100</v></c>
      <c r="B1" t="n"><v>200</v></c>
      <c r="C1" t="n"><f>SUM(A1:B1)</f><v>300</v></c>
    </row>
  </sheetData>
  <mergeCells count="1">
    <mergeCell ref="A1:B1"/>
  </mergeCells>
</worksheet>"""
    sh2 = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>Secret Data</t></is></c></row>
  </sheetData>
</worksheet>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/worksheets/sheet1.xml", sh1)
        z.writestr("xl/worksheets/sheet2.xml", sh2)
    return output_path


def compute_hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# --- Test Cases ---


def test_checksum_corruption():
    """Verify that tampering with an extracted file is detected and forces re-extraction."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        pdf_path = tmp_dir / "sample.pdf"
        make_digital_pdf(pdf_path, ["Digital page one text for testing."])

        db_path = tmp_dir / "test.db"
        staging_dir = tmp_dir / "staging"
        init_db(db_path)

        src_record = {
            "file_id": "FILE-synth-01",
            "legacy_id": "SRC-SYNTH-01",
            "relative_path": str(pdf_path),
            "filename": pdf_path.name,
            "extension": ".pdf",
            "detected_type": "digital_pdf",
            "size_bytes": pdf_path.stat().st_size,
            "content_sha256": compute_hash(pdf_path),
            "collection": "test",
            "duplicate_group": "none",
            "accessibility_status": "accessible",
        }
        conn = get_db_connection(db_path)
        upsert_source(conn, src_record)
        conn.close()

        engine = ExtractionEngine(db_path=db_path, staging_dir=staging_dir)
        res = engine.process_source(src_record)
        assert res["completed"] == 1
        assert res["failed"] == 0

        # Output file exists and is valid
        out_file = staging_dir / "SRC-SYNTH-01" / "page_0001.json"
        assert out_file.exists()
        val_before = validate_staged_source("SRC-SYNTH-01", staging_dir=staging_dir, db_path=db_path)
        assert val_before["status"] == "PASS"

        # Corrupt the output file
        corrupted_content = out_file.read_text().replace("Digital page one", "TAMPERED CONTENT")
        out_file.write_text(corrupted_content)

        # 1. Checkpoint validity must fail due to checksum mismatch
        conn = get_db_connection(db_path)
        cp = get_checkpoint(
            conn,
            src_record["file_id"],
            "raw_extraction",
            "0.1.0-pdfminer",
            compute_config_hash({"mode": "text_stream"}),
            "v0.1.0-raw-block-schema",
            "page",
            "page_0001",
        )
        is_valid = check_checkpoint_validity(
            conn=conn,
            file_id=src_record["file_id"],
            stage="raw_extraction",
            parser_version="0.1.0-pdfminer",
            config_hash=cp["config_hash"],
            output_schema_version="v0.1.0-raw-block-schema",
            processing_unit="page",
            unit_identifier="page_0001",
            current_source_sha256=src_record["content_sha256"],
        )
        conn.close()
        assert is_valid is False, "Corrupted output file must not be validated as valid checkpoint"

        # 2. Validator must report FAIL
        val_after = validate_staged_source("SRC-SYNTH-01", staging_dir=staging_dir, db_path=db_path)
        assert val_after["status"] == "FAIL"

        # 3. Next extraction run without force must detect corruption and re-extract
        res_re = engine.process_source(src_record, force=False)
        assert res_re["completed"] == 1
        assert res_re["skipped"] == 0

        # Validator passes again
        val_restored = validate_staged_source("SRC-SYNTH-01", staging_dir=staging_dir, db_path=db_path)
        assert val_restored["status"] == "PASS"


def test_missing_output_page():
    """Verify that a missing page in a multi-page output is detected by validator."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        pdf_path = tmp_dir / "sample3.pdf"
        make_digital_pdf(pdf_path, ["Page 1 text content.", "Page 2 text content.", "Page 3 text content."])

        db_path = tmp_dir / "test.db"
        staging_dir = tmp_dir / "staging"
        init_db(db_path)

        src_record = {
            "file_id": "FILE-synth-02",
            "legacy_id": "SRC-SYNTH-02",
            "relative_path": str(pdf_path),
            "filename": pdf_path.name,
            "extension": ".pdf",
            "detected_type": "digital_pdf",
            "size_bytes": pdf_path.stat().st_size,
            "content_sha256": compute_hash(pdf_path),
            "collection": "test",
            "duplicate_group": "none",
            "accessibility_status": "accessible",
        }
        conn = get_db_connection(db_path)
        upsert_source(conn, src_record)
        conn.close()

        engine = ExtractionEngine(db_path=db_path, staging_dir=staging_dir)
        res = engine.process_source(src_record)
        assert res["total_units"] == 3
        assert res["completed"] == 3

        # Validate initially passes
        val1 = validate_staged_source("SRC-SYNTH-02", staging_dir=staging_dir, db_path=db_path)
        assert val1["status"] == "PASS"

        # Delete page 2
        p2 = staging_dir / "SRC-SYNTH-02" / "page_0002.json"
        assert p2.exists()
        p2.unlink()

        # Validator must detect missing page
        val2 = validate_staged_source("SRC-SYNTH-02", staging_dir=staging_dir, db_path=db_path)
        assert val2["status"] == "FAIL"
        assert any("Missing expected extraction unit" in err for err in val2["errors"])


def test_interrupted_processing_synthetic():
    """Verify that interrupted processing skips completed units upon resume."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        pdf_path = tmp_dir / "sample3.pdf"
        make_digital_pdf(pdf_path, ["Page 1 text content.", "Page 2 text content.", "Page 3 text content."])

        db_path = tmp_dir / "test.db"
        staging_dir = tmp_dir / "staging"
        init_db(db_path)

        src_record = {
            "file_id": "FILE-synth-03",
            "legacy_id": "SRC-SYNTH-03",
            "relative_path": str(pdf_path),
            "filename": pdf_path.name,
            "extension": ".pdf",
            "detected_type": "digital_pdf",
            "size_bytes": pdf_path.stat().st_size,
            "content_sha256": compute_hash(pdf_path),
            "collection": "test",
            "duplicate_group": "none",
            "accessibility_status": "accessible",
        }
        conn = get_db_connection(db_path)
        upsert_source(conn, src_record)
        conn.close()

        engine = ExtractionEngine(db_path=db_path, staging_dir=staging_dir)

        # Extract only unit page_0001
        res1 = engine.process_source(src_record, specific_unit="page_0001")
        assert res1["completed"] == 1

        # Resume full extraction: page 1 skipped, pages 2 and 3 completed
        res_resume = engine.process_source(src_record, force=False)
        assert res_resume["total_units"] == 3
        assert res_resume["completed"] == 2
        assert res_resume["skipped"] == 1
        assert res_resume["failed"] == 0

        val = validate_staged_source("SRC-SYNTH-03", staging_dir=staging_dir, db_path=db_path)
        assert val["status"] == "PASS"
        assert val["total_files"] == 3


def test_source_hash_changes():
    """Verify that modifying the source file invalidates checkpoint and triggers re-extraction."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        pdf_path = tmp_dir / "sample.pdf"
        make_digital_pdf(pdf_path, ["Original text content in document."])

        db_path = tmp_dir / "test.db"
        staging_dir = tmp_dir / "staging"
        init_db(db_path)

        orig_hash = compute_hash(pdf_path)
        src_record = {
            "file_id": "FILE-synth-04",
            "legacy_id": "SRC-SYNTH-04",
            "relative_path": str(pdf_path),
            "filename": pdf_path.name,
            "extension": ".pdf",
            "detected_type": "digital_pdf",
            "size_bytes": pdf_path.stat().st_size,
            "content_sha256": orig_hash,
            "collection": "test",
            "duplicate_group": "none",
            "accessibility_status": "accessible",
        }
        conn = get_db_connection(db_path)
        upsert_source(conn, src_record)
        conn.close()

        engine = ExtractionEngine(db_path=db_path, staging_dir=staging_dir)
        res1 = engine.process_source(src_record)
        assert res1["completed"] == 1

        # Modify source PDF with new content
        make_digital_pdf(pdf_path, ["Completely modified and new text content."])
        new_hash = compute_hash(pdf_path)
        assert new_hash != orig_hash

        # Checkpoint validity check with new source SHA must return False
        adapter = get_adapter_for_source(src_record)
        conn = get_db_connection(db_path)
        cp = get_checkpoint(
            conn,
            src_record["file_id"],
            "raw_extraction",
            adapter.version,
            adapter.config_hash,
            "v0.1.0-raw-block-schema",
            "page",
            "page_0001",
        )
        assert cp is not None
        is_valid = check_checkpoint_validity(
            conn=conn,
            file_id=src_record["file_id"],
            stage="raw_extraction",
            parser_version=adapter.version,
            config_hash=cp["config_hash"],
            output_schema_version="v0.1.0-raw-block-schema",
            processing_unit="page",
            unit_identifier="page_0001",
            current_source_sha256=new_hash,
        )
        conn.close()
        assert is_valid is False

        # Updating source record and extracting triggers re-extraction
        src_record["content_sha256"] = new_hash
        res2 = engine.process_source(src_record, force=False)
        assert res2["completed"] == 1
        assert res2["skipped"] == 0


def test_mixed_pdf_pages():
    """Verify page-aware extraction routing on a mixed PDF (digital, scanned, empty, ambiguous)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        pdf_path = tmp_dir / "mixed.pdf"
        make_mixed_pdf(pdf_path, tmp_dir)

        # Classification check: must identify as mixed_pdf and recommend pdf_router
        cls_info = classify_pdf(pdf_path)
        assert cls_info["subtype"] == "mixed_pdf"
        assert cls_info["recommended_adapter"] == "pdf_router"

        db_path = tmp_dir / "test.db"
        staging_dir = tmp_dir / "staging"
        init_db(db_path)

        src_record = {
            "file_id": "FILE-mixed-01",
            "legacy_id": "SRC-MIXED-01",
            "relative_path": str(pdf_path),
            "filename": pdf_path.name,
            "extension": ".pdf",
            "detected_type": "mixed_pdf",
            "size_bytes": pdf_path.stat().st_size,
            "content_sha256": compute_hash(pdf_path),
            "collection": "test",
            "duplicate_group": "none",
            "accessibility_status": "accessible",
        }
        conn = get_db_connection(db_path)
        upsert_source(conn, src_record)
        conn.close()

        engine = ExtractionEngine(db_path=db_path, staging_dir=staging_dir)
        res = engine.process_source(src_record)
        assert res["total_units"] == 4
        assert res["completed"] == 4
        assert res["failed"] == 0

        # Inspect page 1 (digital): native extraction used
        p1_data = json.loads((staging_dir / "SRC-MIXED-01" / "page_0001.json").read_text())
        assert p1_data["provenance"]["routing_decision"] == "native"
        assert p1_data["content"]["ocr_applied"] is False
        assert "digital selectable text" in p1_data["content"]["text"]

        # Inspect page 2 (scanned): OCR used
        p2_data = json.loads((staging_dir / "SRC-MIXED-01" / "page_0002.json").read_text())
        assert p2_data["provenance"]["routing_decision"] == "ocr"
        assert p2_data["content"]["ocr_applied"] is True
        assert "SCANNED" in p2_data["content"]["text"]

        # Inspect page 3 (blank): unexpectedly empty flagged
        p3_data = json.loads((staging_dir / "SRC-MIXED-01" / "page_0003.json").read_text())
        assert "unexpectedly_empty" in p3_data["content"]["flags"]

        # Inspect page 4 (low density): ambiguous text density flagged
        p4_data = json.loads((staging_dir / "SRC-MIXED-01" / "page_0004.json").read_text())
        assert "ambiguous_text_density" in p4_data["content"]["flags"]

        # Validate staged output: empty/ambiguous units trigger REVIEW_REQUIRED
        val = validate_staged_source("SRC-MIXED-01", staging_dir=staging_dir, db_path=db_path)
        assert val["status"] == "REVIEW_REQUIRED"
        assert val["empty"] > 0
        assert val["failed"] == 0


def test_duplicate_content_identities():
    """Verify that identical files receive distinct physical identities and shared duplicate group."""
    with tempfile.TemporaryDirectory() as tmp:
        raw_dir = Path(tmp) / "raw"
        f1 = raw_dir / "folder_a" / "item.txt"
        f2 = raw_dir / "folder_b" / "copy.txt"
        f1.parent.mkdir(parents=True, exist_ok=True)
        f2.parent.mkdir(parents=True, exist_ok=True)

        content = b"Exact identical payload across both copies."
        f1.write_bytes(content)
        f2.write_bytes(content)

        scanned = scan_raw_sources(raw_dir)
        assert len(scanned) == 2

        # Distinct file_ids
        assert scanned[0]["file_id"] != scanned[1]["file_id"]
        # Identical content hashes
        assert scanned[0]["content_sha256"] == scanned[1]["content_sha256"]
        # Shared duplicate group tag
        dup1 = scanned[0]["duplicate_group"]
        dup2 = scanned[1]["duplicate_group"]
        assert dup1 == dup2
        assert dup1 != "none"


def test_failed_extraction_exit_code():
    """Verify that any extraction failure causes CLI extract to exit with non-zero status."""
    import sys
    from harness.cli import main

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        db_path = tmp_dir / "test.db"
        init_db(db_path)

        # Create source pointing to corrupt file
        corrupt_file = tmp_dir / "corrupt.docx"
        corrupt_file.write_bytes(b"This is not a valid zip archive for docx")

        src_record = {
            "file_id": "FILE-corrupt",
            "legacy_id": "SRC-CORRUPT",
            "relative_path": str(corrupt_file),
            "filename": corrupt_file.name,
            "extension": ".docx",
            "detected_type": "openxml_word",
            "size_bytes": corrupt_file.stat().st_size,
            "content_sha256": compute_hash(corrupt_file),
            "collection": "test",
            "duplicate_group": "none",
            "accessibility_status": "accessible",
        }
        conn = get_db_connection(db_path)
        upsert_source(conn, src_record)
        conn.close()

        with mock.patch("harness.config.DB_PATH", db_path), \
             mock.patch("harness.db.DB_PATH", db_path), \
             mock.patch("harness.config.STAGING_DIR", tmp_dir / "staging"), \
             mock.patch("harness.engine.STAGING_DIR", tmp_dir / "staging"), \
             mock.patch.object(sys, "argv", ["harness", "extract", "--source-id", "SRC-CORRUPT"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code != 0


def test_resume_non_pilot_sources():
    """Verify that resume can target interrupted sources outside the pilot dataset."""
    import sys
    from harness.cli import main

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        pdf_path = tmp_dir / "nonpilot.pdf"
        make_digital_pdf(pdf_path, ["Page 1 text.", "Page 2 text."])

        db_path = tmp_dir / "test.db"
        staging_dir = tmp_dir / "staging"
        init_db(db_path)

        non_pilot_src = {
            "file_id": "FILE-nonpilot-01",
            "legacy_id": "SRC-999",
            "relative_path": str(pdf_path),
            "filename": pdf_path.name,
            "extension": ".pdf",
            "detected_type": "digital_pdf",
            "size_bytes": pdf_path.stat().st_size,
            "content_sha256": compute_hash(pdf_path),
            "collection": "test",
            "duplicate_group": "none",
            "accessibility_status": "accessible",
        }
        conn = get_db_connection(db_path)
        upsert_source(conn, non_pilot_src)
        conn.close()

        # Step 1: Partially extract unit page_0001
        engine = ExtractionEngine(db_path=db_path, staging_dir=staging_dir)
        engine.process_source(non_pilot_src, specific_unit="page_0001")

        # Step 2: Use CLI resume specifically on SRC-999 (non-pilot)
        with mock.patch("harness.config.DB_PATH", db_path), \
             mock.patch("harness.db.DB_PATH", db_path), \
             mock.patch("harness.config.STAGING_DIR", staging_dir), \
             mock.patch("harness.engine.STAGING_DIR", staging_dir), \
             mock.patch.object(sys, "argv", ["harness", "resume", "--source-id", "SRC-999"]):
            main()

        # Verify page 2 is now extracted and staged output is complete
        val = validate_staged_source("SRC-999", staging_dir=staging_dir, db_path=db_path)
        assert val["status"] == "PASS"
        assert val["total_files"] == 2


def test_docx_reading_order_and_deduplication():
    """Verify DOCX reading order preservation and table paragraph deduplication."""
    with tempfile.TemporaryDirectory() as tmp:
        docx_path = Path(tmp) / "doc.docx"
        make_synthetic_docx(docx_path)

        fake_source = {
            "file_id": "FILE-docx-synth",
            "legacy_id": "SRC-DOCX-01",
            "relative_path": str(docx_path),
            "content_sha256": compute_hash(docx_path),
        }
        ext = DocxExtractor()
        res = ext.extract_unit(fake_source, Path(tmp), "raw_document")

        out_data = json.loads(Path(res["output_path"]).read_text())
        content = out_data["content"]

        # 1. Blocks order must strictly preserve sequence: Paragraph, Table, Paragraph
        blocks = content["blocks"]
        assert len(blocks) == 3
        assert blocks[0]["type"] == "paragraph"
        assert blocks[0]["text"] == "First Paragraph"
        assert blocks[0]["index"] == 0

        assert blocks[1]["type"] == "table"
        assert blocks[1]["index"] == 1
        assert blocks[1]["rows"] == [["Cell 1A", "Cell 1B"]]

        assert blocks[2]["type"] == "paragraph"
        assert blocks[2]["text"] == "Second Paragraph"
        assert blocks[2]["index"] == 2

        # 2. Table paragraphs must NOT leak as independent top-level paragraphs
        paragraphs = content["paragraphs"]
        assert len(paragraphs) == 2
        p_texts = [p["text"] for p in paragraphs]
        assert "Cell 1A" not in p_texts
        assert "Cell 1B" not in p_texts


def test_xlsx_structural_fidelity():
    """Verify XLSX preserves formulas, merged cells, hidden sheet metadata, and unresolved relationships."""
    with tempfile.TemporaryDirectory() as tmp:
        xlsx_path = Path(tmp) / "workbook.xlsx"
        make_synthetic_xlsx(xlsx_path)

        fake_source = {
            "file_id": "FILE-xlsx-synth",
            "legacy_id": "SRC-XLSX-01",
            "relative_path": str(xlsx_path),
            "content_sha256": compute_hash(xlsx_path),
        }
        ext = XlsxExtractor()
        res = ext.extract_unit(fake_source, Path(tmp), "raw_sheets")

        out_data = json.loads(Path(res["output_path"]).read_text())
        content = out_data["content"]

        sheets = content["sheets"]
        assert len(sheets) == 3

        # 1. Sheet 1: Formulas and merged ranges
        sh1 = next(s for s in sheets if s["name"] == "VisibleSheet")
        assert sh1["resolved"] is True
        assert sh1["is_hidden"] is False
        assert sh1["merged_ranges"] == ["A1:B1"]

        formula_cell = sh1["rows"][0]["cells"][2]
        assert formula_cell["coord"] == "C1"
        assert formula_cell["formula"] == "SUM(A1:B1)"
        assert formula_cell["value"] == "300"

        # 2. Sheet 2: Hidden sheet metadata
        sh2 = next(s for s in sheets if s["name"] == "HiddenSheet")
        assert sh2["resolved"] is True
        assert sh2["is_hidden"] is True
        assert sh2["state"] == "hidden"

        # 3. Sheet 3: Unresolved relationship handled gracefully
        sh3 = next(s for s in sheets if s["name"] == "UnresolvedSheet")
        assert sh3["resolved"] is False
        assert "could not be resolved" in sh3["error"]


def test_inventory_reconciliation():
    """Verify that removed or relocated sources are reconciled without silently remaining active."""
    with tempfile.TemporaryDirectory() as tmp:
        raw_dir = Path(tmp) / "raw"
        f1 = raw_dir / "file1.txt"
        f2 = raw_dir / "file2.txt"
        f1.parent.mkdir(parents=True, exist_ok=True)
        f1.write_text("Content of file 1")
        f2.write_text("Content of file 2")

        db_path = Path(tmp) / "inventory.db"
        sync_inventory_to_db(db_path=db_path, raw_dir=raw_dir)

        conn = get_db_connection(db_path)
        sources_init = list_sources(conn)
        conn.close()
        assert len(sources_init) == 2
        for s in sources_init:
            assert s["accessibility_status"] == "accessible"

        # 1. Delete file1
        f1.unlink()

        # 2. Move file2 to a new location
        relocated_f2 = raw_dir / "relocated" / "file2.txt"
        relocated_f2.parent.mkdir(parents=True, exist_ok=True)
        f2.rename(relocated_f2)

        # Re-sync inventory
        sync_inventory_to_db(db_path=db_path, raw_dir=raw_dir)

        conn = get_db_connection(db_path)
        sources_after = list_sources(conn)
        conn.close()

        status_by_path = {s["relative_path"]: s["accessibility_status"] for s in sources_after}

        # The old f1 path must be marked as 'missing', not 'accessible'
        f1_rel = f1.relative_to(Path(tmp)).as_posix()
        assert any(
            s["accessibility_status"] == "missing"
            for s in sources_after
            if not (Path(tmp) / s["relative_path"]).exists()
        )

        # Neither missing nor old location remains marked as 'accessible'
        for s in sources_after:
            disk_exists = (Path(tmp) / s["relative_path"]).exists()
            if not disk_exists:
                assert s["accessibility_status"] in ["missing", "relocated"]


def test_empty_staging_validation():
    """Verify that an empty staging directory cannot report successful validation."""
    with tempfile.TemporaryDirectory() as tmp:
        empty_dir = Path(tmp) / "empty_staging"
        empty_dir.mkdir()

        res = validate_all_staged(staging_dir=empty_dir)
        assert res["status"] == "FAIL"
        assert res["total_sources"] == 0
        assert res["failed_sources"] == 0
        assert len(res["errors"]) > 0
