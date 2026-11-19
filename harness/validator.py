"""Extraction integrity and output validation for Harness V0.1."""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from harness.config import STAGING_DIR
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

    raw_bytes = file_path.read_bytes()

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
    missing_keys = [k for k in REQUIRED_PROVENANCE_KEYS if k not in prov or not prov[k]]
    if missing_keys:
        return False, f"Missing provenance fields in {file_path.name}: {missing_keys}", data

    return True, "Valid", data


def validate_staged_source(
    legacy_id: str,
    staging_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Validates all staged output artifacts and manifest for a given source ID."""
    root_dir = staging_dir or STAGING_DIR
    source_dir = root_dir / legacy_id

    if not source_dir.is_dir():
        return {
            "source_id": legacy_id,
            "status": "MISSING_DIRECTORY",
            "total_files": 0,
            "passed": 0,
            "failed": 0,
            "errors": [f"Source directory not found: {source_dir}"],
        }

    manifest_file = source_dir / "manifest.json"
    manifest_data = None
    errors = []

    if manifest_file.exists():
        try:
            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"Invalid manifest.json: {e}")
    else:
        errors.append("manifest.json missing")

    json_files = [p for p in source_dir.glob("*.json") if p.name != "manifest.json"]
    json_files.sort(key=lambda p: p.name)

    passed = 0
    failed = 0

    for jf in json_files:
        ok, msg, _ = validate_json_file(jf)
        if ok:
            passed += 1
        else:
            failed += 1
            errors.append(msg)

    status = "PASS" if (failed == 0 and not errors and passed > 0) else "FAIL"

    return {
        "source_id": legacy_id,
        "status": status,
        "total_files": len(json_files),
        "passed": passed,
        "failed": failed,
        "manifest_present": bool(manifest_data),
        "errors": errors,
    }


def validate_all_staged(staging_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Validates all staged sources in the staging directory."""
    root_dir = staging_dir or STAGING_DIR
    if not root_dir.exists():
        return {
            "total_sources": 0,
            "passed_sources": 0,
            "failed_sources": 0,
            "sources": [],
        }

    source_dirs = [d for d in root_dir.iterdir() if d.is_dir()]
    source_dirs.sort(key=lambda d: d.name)

    sources_summary = []
    passed_sources = 0
    failed_sources = 0

    for sd in source_dirs:
        res = validate_staged_source(sd.name, staging_dir=root_dir)
        sources_summary.append(res)
        if res["status"] == "PASS":
            passed_sources += 1
        else:
            failed_sources += 1

    return {
        "total_sources": len(source_dirs),
        "passed_sources": passed_sources,
        "failed_sources": failed_sources,
        "sources": sources_summary,
    }
