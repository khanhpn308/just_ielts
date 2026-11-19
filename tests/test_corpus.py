"""Automated test suite for IELTS Data Harness V0.1."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import pytest

from harness.config import (
    DB_PATH,
    OUTPUT_SCHEMA_VERSION,
    PARSER_VERSIONS,
    PILOT_SOURCE_IDS,
    RAW_DIR,
    REPO_ROOT,
    STAGING_DIR,
)
from harness.db import (
    get_db_connection,
    get_source_by_legacy_id,
    init_db,
    list_sources,
)
from harness.engine import ExtractionEngine
from harness.inventory import compute_file_sha256, scan_raw_sources, sync_inventory_to_db
from harness.validator import validate_all_staged, validate_json_file, validate_staged_source

# Mark all tests in this file as corpus tests (requiring private/raw/)
pytestmark = pytest.mark.corpus


@pytest.fixture(scope="session")
def synced_db():
    """Initializes and synchronizes inventory to database once for test session."""
    sync_inventory_to_db()
    return DB_PATH


def test_source_records_distinguishable(synced_db):
    """Requirement 1: All 206 source records remain distinguishable."""
    conn = get_db_connection(synced_db)
    sources = list_sources(conn)
    conn.close()

    assert len(sources) == 206, f"Expected exactly 206 source records, got {len(sources)}"

    file_ids = [s["file_id"] for s in sources]
    rel_paths = [s["relative_path"] for s in sources]
    legacy_ids = [s["legacy_id"] for s in sources if s["legacy_id"]]

    assert len(set(file_ids)) == 206, "All file_ids must be strictly unique"
    assert len(set(rel_paths)) == 206, "All relative_paths must be strictly unique"
    assert len(set(legacy_ids)) == len(legacy_ids), "All present legacy_ids must be strictly unique"


def test_duplicate_content_representation(synced_db):
    """Requirement 2: Duplicate content is represented correctly with distinct physical identity."""
    conn = get_db_connection(synced_db)
    cur = conn.execute("SELECT content_sha256, COUNT(*) FROM sources GROUP BY content_sha256 HAVING COUNT(*) > 1")
    dup_hashes = cur.fetchall()

    assert len(dup_hashes) == 4, f"Expected exactly 4 duplicate content groups, found {len(dup_hashes)}"

    for sha, count in dup_hashes:
        cur2 = conn.execute("SELECT * FROM sources WHERE content_sha256 = ?", (sha,))
        records = [dict(r) for r in cur2.fetchall()]
        assert len(records) == count

        # Physical identities must be unique despite identical content
        fids = [r["file_id"] for r in records]
        paths = [r["relative_path"] for r in records]
        assert len(set(fids)) == count
        assert len(set(paths)) == count

        # Duplicate group tag must be shared and not 'none'
        dup_groups = set(r["duplicate_group"] for r in records)
        assert len(dup_groups) == 1
        assert "none" not in dup_groups

    # Singletons must have duplicate_group == 'none'
    cur3 = conn.execute("SELECT COUNT(*) FROM sources WHERE duplicate_group = 'none'")
    singleton_count = cur3.fetchone()[0]
    total_dups = sum(c for _, c in dup_hashes)
    assert singleton_count == 206 - total_dups
    conn.close()


def test_no_raw_source_modification():
    """Requirement 3: Verify read-only access and zero modification of private/raw/."""
    # Capture snapshot of raw files before any test action
    raw_files = list(RAW_DIR.rglob("*"))
    file_snapshots = {
        p: (p.stat().st_size, p.stat().st_mtime)
        for p in raw_files
        if p.is_file()
    }

    assert len(file_snapshots) == 206, f"Expected 206 raw files, got {len(file_snapshots)}"

    # Perform inventory scan and hash calculations
    scanned = scan_raw_sources()
    assert len(scanned) == 206

    # Verify that sizes and mtimes in raw_files are strictly untouched
    for p, (orig_size, orig_mtime) in file_snapshots.items():
        assert p.exists(), f"File disappeared: {p}"
        assert p.stat().st_size == orig_size, f"File size changed: {p}"
        assert p.stat().st_mtime == orig_mtime, f"File mtime changed: {p}"


def test_pilot_extraction(synced_db):
    """Requirement 4: Extraction of the 7 approved pilot sources."""
    engine = ExtractionEngine()
    results = engine.process_all_pilots(force=False)

    assert len(results) == 7, f"Expected 7 pilot extraction results, got {len(results)}"

    # Pilot 1: SRC-004 (Digital PDF, 42 pages)
    p1 = next(r for r in results if r["source_id"] == "SRC-004")
    assert p1["total_units"] == 42
    assert p1["failed"] == 0

    # Pilot 2: SRC-011 (Scanned PDF, 23 pages)
    p2 = next(r for r in results if r["source_id"] == "SRC-011")
    assert p2["total_units"] == 23
    assert p2["failed"] == 0

    # Pilot 3: SRC-138 (DOCX, 1 document unit)
    p3 = next(r for r in results if r["source_id"] == "SRC-138")
    assert p3["total_units"] == 1
    assert p3["failed"] == 0

    # Pilot 4: SRC-077 (XLSX, 1 sheet unit)
    p4 = next(r for r in results if r["source_id"] == "SRC-077")
    assert p4["total_units"] == 1
    assert p4["failed"] == 0

    # Pilot 5: SRC-137 (Scanned PDF, 16 pages)
    p5 = next(r for r in results if r["source_id"] == "SRC-137")
    assert p5["total_units"] == 16
    assert p5["failed"] == 0

    # Pilot 6: SRC-008 (Audio MP3, 1 metadata unit)
    p6 = next(r for r in results if r["source_id"] == "SRC-008")
    assert p6["total_units"] == 1
    assert p6["failed"] == 0

    # Pilot 6b: SRC-012 (DOCX Transcript, 1 document unit)
    p6b = next(r for r in results if r["source_id"] == "SRC-012")
    assert p6b["total_units"] == 1
    assert p6b["failed"] == 0

    # Validate staged files integrity
    for pid in PILOT_SOURCE_IDS:
        val_res = validate_staged_source(pid)
        assert val_res["status"] == "PASS", f"Validation failed for pilot {pid}: {val_res['errors']}"
        assert val_res["failed"] == 0
        assert val_res["manifest_present"] is True


def test_interrupted_processing_recovery():
    """Requirement 5: Recovery after interrupted processing without redundant work."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_db = Path(tmpdir) / "test_harness.db"
        tmp_staging = Path(tmpdir) / "staging"
        init_db(tmp_db)

        # Sync inventory to temp db
        sync_inventory_to_db(db_path=tmp_db)

        conn = get_db_connection(tmp_db)
        src = get_source_by_legacy_id(conn, "SRC-004")
        conn.close()

        engine = ExtractionEngine(db_path=tmp_db, staging_dir=tmp_staging)

        # Step 1: Simulate extracting only pages 1 and 2
        res1 = engine.process_source(src, specific_unit="page_0001")
        assert res1["completed"] == 1
        res2 = engine.process_source(src, specific_unit="page_0002")
        assert res2["completed"] == 1

        # Step 2: Resume full extraction for SRC-004 (42 pages total)
        res_full = engine.process_source(src, force=False)
        assert res_full["total_units"] == 42
        # Pages 1 and 2 must have been SKIPPED
        assert res_full["skipped"] >= 2, f"Expected at least 2 skipped units, got {res_full['skipped']}"
        assert res_full["completed"] == 40
        assert res_full["failed"] == 0

        # Step 3: Validate output directory
        val_res = validate_staged_source("SRC-004", staging_dir=tmp_staging, db_path=tmp_db)
        assert val_res["status"] == "PASS"
        assert val_res["total_files"] == 42


def test_idempotency_no_reprocessing(synced_db):
    """Requirement 6: Idempotent repeated execution performs zero extra work."""
    engine = ExtractionEngine()
    conn = get_db_connection(synced_db)
    src = get_source_by_legacy_id(conn, "SRC-138")
    conn.close()

    # Second run without --force must skip all units
    res = engine.process_source(src, force=False)
    assert res["total_units"] == 1
    assert res["completed"] == 0
    assert res["skipped"] == 1
    assert res["failed"] == 0
    assert res["results"][0]["status"] == "SKIPPED"


def test_provenance_lineage(synced_db):
    """Requirement 7: Correct source-to-output lineage in provenance metadata."""
    conn = get_db_connection(synced_db)
    src_077 = get_source_by_legacy_id(conn, "SRC-077")
    conn.close()

    output_file = STAGING_DIR / "SRC-077" / "raw_sheets.json"
    assert output_file.exists(), f"Output file does not exist: {output_file}"

    ok, msg, data = validate_json_file(output_file)
    assert ok, f"Output validation failed: {msg}"

    prov = data["provenance"]
    assert prov["legacy_id"] == "SRC-077"
    assert prov["file_id"] == src_077["file_id"]
    assert prov["source_sha256"] == src_077["content_sha256"]
    assert prov["relative_path"] == src_077["relative_path"]
    assert prov["output_schema_version"] == OUTPUT_SCHEMA_VERSION
    assert prov["parser_version"] == PARSER_VERSIONS["xlsx"]


def test_no_public_data_leakage():
    """Requirement 8: Zero unintended public data publication or untracked repository changes."""
    # Check git status for uncommitted files outside private/ or gitignored directories
    cmd = ["git", "status", "--porcelain"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    raw_lines = [line for line in res.stdout.splitlines() if line.strip()]

    allowed_root_files = {".gitignore", "AGENTS.md", "requirements-harness.txt"}

    for line in raw_lines:
        parts = line.strip().split(maxsplit=1)
        if len(parts) < 2:
            continue
        filepath = parts[1]
        assert (
            filepath in allowed_root_files
            or filepath.startswith("harness/")
            or filepath.startswith("tests/")
            or filepath.startswith(".github/")
            or filepath.startswith("docs/")
            or filepath.startswith("schemas/")
        ), f"Unexpected untracked or modified file in repository: {filepath}"
        assert not filepath.startswith("private/staging/"), f"Staging output leaked to git: {filepath}"
        assert not filepath.startswith("private/raw/"), f"Raw file modified in git: {filepath}"
        assert not filepath.startswith("harness/state/"), f"Harness state leaked to git: {filepath}"
