"""Extraction integrity and output validation for Harness V0.1."""

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from harness.config import DB_PATH, STAGING_DIR
from harness.db import get_db_connection


REQUIRED_PROVENANCE_KEYS = [
    "file_id",
    "legacy_id",
    "relative_path",
    "source_sha256",
    "parser_name",
    "parser_version",
    "config_hash",
    "output_schema_version",
    "processing_unit",
    "unit_identifier",
    "extracted_at",
]


def compute_bytes_sha256(data: bytes) -> str:
    """Computes SHA-256 hash of bytes."""
    return hashlib.sha256(data).hexdigest()


def validate_json_file(
    file_path: Path,
    expected_sha256: Optional[str] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Validates a single JSON extraction file.
    Checks:
    1. Existence and non-zero size.
    2. Checksum match if provided.
    3. Valid JSON syntax.
    4. Required 'provenance' and 'content' blocks.
    5. Completeness of provenance keys.
    """
    if not file_path.is_file():
        return False, f"File does not exist: {file_path}", None

    size = file_path.stat().st_size
    if size == 0:
        return False, f"File is empty (0 bytes): {file_path}", None

    try:
        raw_bytes = file_path.read_bytes()
    except OSError as e:
        return False, f"Cannot read file {file_path.name}: {e}", None

    if expected_sha256:
        calc_sha = compute_bytes_sha256(raw_bytes)
        if calc_sha != expected_sha256:
            return False, f"Checksum mismatch for {file_path.name}: expected {expected_sha256}, got {calc_sha}", None

    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except Exception as e:
        return False, f"Invalid JSON in {file_path.name}: {e}", None

    if not isinstance(data, dict):
        return False, f"Root JSON is not an object in {file_path.name}", None

    if "provenance" not in data:
        return False, f"Missing 'provenance' block in {file_path.name}", None

    if "content" not in data:
        return False, f"Missing 'content' block in {file_path.name}", None

    prov = data["provenance"]
    if not isinstance(prov, dict):
        return False, f"Provenance is not a dictionary in {file_path.name}", None

    missing_keys = [k for k in REQUIRED_PROVENANCE_KEYS if k not in prov or not prov[k]]
    if missing_keys:
        return False, f"Missing provenance fields in {file_path.name}: {missing_keys}", data

    return True, "Valid", data


def classify_content_emptiness(content: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Classifies if extracted content is empty or ambiguous.
    Returns (is_empty, classification_label).
    """
    if not isinstance(content, dict):
        return True, "empty_non_dict"

    flags = content.get("flags", [])
    if "unexpectedly_empty" in flags:
        return True, "unexpectedly_empty"
    if "ambiguous_text_density" in flags:
        return True, "ambiguous_text_density"

    # Text check (PDF)
    if "text" in content:
        txt = content.get("text", "")
        if not txt or len(str(txt).strip()) == 0:
            return True, "empty_text"

    # Paragraphs / tables check (DOCX)
    if "paragraphs" in content and "tables" in content:
        p_cnt = len(content.get("paragraphs", []))
        t_cnt = len(content.get("tables", []))
        if p_cnt == 0 and t_cnt == 0:
            return True, "empty_docx"

    # Sheets check (XLSX)
    if "sheets" in content:
        sheets = content.get("sheets", [])
        if not sheets:
            return True, "empty_xlsx_no_sheets"
        total_rows = sum(s.get("row_count", 0) for s in sheets)
        if total_rows == 0:
            return True, "empty_xlsx_no_rows"

    return False, "populated"


def validate_staged_source(
    legacy_id: str,
    staging_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Validates all staged output artifacts and manifest for a given source ID.
    Performs comprehensive completeness and integrity checks:
    - Expected units match extracted units (no missing pages, no gaps).
    - Failed units prevent source-level PASS.
    - Output checksums match checkpoint records and manifest.
    - Source and unit provenance match.
    - Empty outputs are explicitly classified (yields REVIEW_REQUIRED).
    """
    root_dir = staging_dir or STAGING_DIR
    source_dir = root_dir / legacy_id

    if not source_dir.is_dir():
        return {
            "source_id": legacy_id,
            "status": "FAIL",
            "total_files": 0,
            "passed": 0,
            "failed": 1,
            "empty": 0,
            "manifest_present": False,
            "empty_units": [],
            "errors": [f"Source directory not found: {source_dir}"],
        }

    manifest_file = source_dir / "manifest.json"
    manifest_data = None
    errors: List[str] = []

    if manifest_file.exists():
        try:
            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"Invalid manifest.json: {e}")
    else:
        errors.append("manifest.json missing")

    if not manifest_data:
        return {
            "source_id": legacy_id,
            "status": "FAIL",
            "total_files": 0,
            "passed": 0,
            "failed": 1,
            "empty": 0,
            "manifest_present": False,
            "empty_units": [],
            "errors": errors,
        }

    # 1. Check for failed units recorded in manifest
    manifest_failed = manifest_data.get("failed_units", 0)
    if manifest_failed > 0:
        errors.append(f"Manifest records {manifest_failed} failed extraction unit(s)")

    # 2. Check expected units from manifest against disk files
    manifest_units = manifest_data.get("units", [])
    expected_unit_ids = [u["unit_identifier"] for u in manifest_units]
    total_expected = manifest_data.get("total_units", len(expected_unit_ids))

    if total_expected == 0:
        errors.append("Manifest specifies 0 total units")

    if len(expected_unit_ids) != total_expected:
        errors.append(
            f"Manifest unit count mismatch: total_units={total_expected}, but units array has {len(expected_unit_ids)}"
        )

    # Unit lookup map from manifest
    manifest_unit_map = {u["unit_identifier"]: u for u in manifest_units}

    # Verify if any unit is marked FAILED inside manifest units
    for u in manifest_units:
        if u.get("status") == "FAILED":
            errors.append(f"Extraction unit '{u.get('unit_identifier')}' failed: {u.get('error')}")

    # Inspect files on disk
    disk_unit_files = {p.stem: p for p in source_dir.glob("*.json") if p.name != "manifest.json"}

    # Missing page / unit detection
    missing_units = set(expected_unit_ids) - set(disk_unit_files.keys())
    if missing_units:
        errors.append(f"Missing expected extraction unit file(s): {sorted(list(missing_units))}")

    # Extraneous files detection
    extra_units = set(disk_unit_files.keys()) - set(expected_unit_ids)
    if extra_units:
        errors.append(f"Extraneous unit file(s) found on disk: {sorted(list(extra_units))}")

    # Page continuity check for multi-page documents
    if expected_unit_ids and all(u.startswith("page_") for u in expected_unit_ids):
        page_nums = sorted([int(u.replace("page_", "")) for u in expected_unit_ids])
        if page_nums:
            expected_pages = list(range(1, max(page_nums) + 1))
            if page_nums != expected_pages:
                missing_pgs = set(expected_pages) - set(page_nums)
                errors.append(f"Missing page numbers in sequence: {sorted(list(missing_pgs))}")

    # 3. Query DB checkpoints if accessible
    db_checkpoints: Dict[str, Dict[str, Any]] = {}
    target_db = db_path if db_path is not None else (DB_PATH if root_dir == STAGING_DIR else None)
    if target_db and target_db.exists():
        try:
            conn = get_db_connection(target_db)
            cur = conn.execute(
                "SELECT * FROM processing_checkpoints WHERE legacy_id = ?",
                (legacy_id,),
            )
            for row in cur.fetchall():
                db_checkpoints[row["unit_identifier"]] = dict(row)
            conn.close()
        except sqlite3.Error:
            pass

    passed = 0
    failed = 0
    empty_units: List[str] = []

    # Validate each unit on disk
    for unit_id in sorted(disk_unit_files.keys()):
        jf = disk_unit_files[unit_id]
        m_unit = manifest_unit_map.get(unit_id, {})
        expected_sha = m_unit.get("output_sha256")

        # Validate basic JSON structure and manifest checksum
        ok, msg, data = validate_json_file(jf, expected_sha256=expected_sha)
        if not ok:
            failed += 1
            errors.append(msg)
            continue

        assert data is not None
        prov = data["provenance"]
        content = data["content"]

        # Check DB checkpoint matching if present
        if unit_id in db_checkpoints:
            cp = db_checkpoints[unit_id]
            if cp.get("status") == "FAILED":
                failed += 1
                errors.append(f"Database checkpoint for {unit_id} status is FAILED")
                continue
            cp_sha = cp.get("output_sha256")
            if cp_sha:
                actual_sha = compute_bytes_sha256(jf.read_bytes())
                if actual_sha != cp_sha:
                    failed += 1
                    errors.append(
                        f"Output checksum mismatch with DB checkpoint for {unit_id}: expected {cp_sha}, got {actual_sha}"
                    )
                    continue

        # Check provenance matching
        if prov.get("legacy_id") != legacy_id:
            failed += 1
            errors.append(f"Provenance legacy_id mismatch in {jf.name}: expected {legacy_id}, got {prov.get('legacy_id')}")
            continue

        if prov.get("unit_identifier") != unit_id:
            failed += 1
            errors.append(
                f"Provenance unit_identifier mismatch in {jf.name}: expected {unit_id}, got {prov.get('unit_identifier')}"
            )
            continue

        manifest_source_sha = manifest_data.get("source_sha256")
        if manifest_source_sha and prov.get("source_sha256") != manifest_source_sha:
            failed += 1
            errors.append(f"Provenance source_sha256 mismatch in {jf.name}")
            continue

        # Empty output classification
        is_empty, empty_label = classify_content_emptiness(content)
        if is_empty:
            empty_units.append(unit_id)
        else:
            passed += 1

    # Determine status
    if failed > 0 or errors or missing_units or manifest_failed > 0:
        status = "FAIL"
    elif empty_units:
        status = "REVIEW_REQUIRED"
    elif passed > 0:
        status = "PASS"
    else:
        status = "FAIL"

    return {
        "source_id": legacy_id,
        "status": status,
        "total_files": len(disk_unit_files),
        "passed": passed,
        "failed": failed,
        "empty": len(empty_units),
        "manifest_present": bool(manifest_data),
        "empty_units": empty_units,
        "errors": errors,
    }


def validate_all_staged(
    staging_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Validates all staged sources in the staging directory.
    An empty staging directory reports failure (cannot report successful validation).
    """
    root_dir = staging_dir or STAGING_DIR

    if not root_dir.exists():
        return {
            "status": "FAIL",
            "total_sources": 0,
            "passed_sources": 0,
            "failed_sources": 0,
            "review_required_sources": 0,
            "sources": [],
            "errors": [f"Staging directory does not exist: {root_dir}"],
        }

    source_dirs = [d for d in root_dir.iterdir() if d.is_dir()]
    source_dirs.sort(key=lambda d: d.name)

    if not source_dirs:
        return {
            "status": "FAIL",
            "total_sources": 0,
            "passed_sources": 0,
            "failed_sources": 0,
            "review_required_sources": 0,
            "sources": [],
            "errors": [f"Staging directory contains zero staged sources: {root_dir}"],
        }

    sources_summary = []
    passed_sources = 0
    failed_sources = 0
    review_required_sources = 0

    for sd in source_dirs:
        res = validate_staged_source(sd.name, staging_dir=root_dir, db_path=db_path)
        sources_summary.append(res)
        if res["status"] == "PASS":
            passed_sources += 1
        elif res["status"] == "REVIEW_REQUIRED":
            review_required_sources += 1
        else:
            failed_sources += 1

    overall_status = "FAIL" if failed_sources > 0 else ("REVIEW_REQUIRED" if review_required_sources > 0 else "PASS")

    return {
        "status": overall_status,
        "total_sources": len(source_dirs),
        "passed_sources": passed_sources,
        "failed_sources": failed_sources,
        "review_required_sources": review_required_sources,
        "sources": sources_summary,
        "errors": [],
    }
