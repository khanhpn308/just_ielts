"""Source Inventory scanner and synchronization for Harness V0.1."""

import csv
from datetime import datetime, timezone
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from harness.config import INVENTORY_CSV, RAW_DIR, REPO_ROOT
from harness.db import get_db_connection, init_db, upsert_source


def compute_file_sha256(filepath: Path, chunk_size: int = 65536) -> str:
    """Computes streaming SHA-256 hash of a file in read-only binary mode."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def compute_file_id(relative_path: str) -> str:
    """
    Computes deterministic physical file ID based on relative path.
    Format: FILE-<sha256(relative_path)[:12]>
    """
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:12]
    return f"FILE-{digest}"


def load_legacy_inventory_mapping(csv_path: Path = INVENTORY_CSV) -> Dict[str, Dict[str, str]]:
    """Loads authoritative mapping of relative_path -> metadata from Phase 0 CSV."""
    mapping = {}
    if not csv_path.exists():
        return mapping
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rel = row["relative_path"].strip()
            mapping[rel] = {
                "legacy_id": row["source_id"].strip(),
                "duplicate_group": row.get("duplicate_group", "none").strip(),
                "collection": row.get("collection", "").strip(),
                "accessibility_status": row.get("accessibility_status", "accessible").strip(),
                "detected_type": row.get("detected_type", "").strip(),
            }
    return mapping


def scan_raw_sources(raw_dir: Path = RAW_DIR) -> List[Dict[str, Any]]:
    """
    Scans the raw source directory recursively in read-only mode.
    Returns list of scanned source dictionaries.
    """
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw directory not found: {raw_dir}")

    legacy_map = load_legacy_inventory_mapping()
    raw_files: List[Path] = [p for p in raw_dir.rglob("*") if p.is_file()]
    raw_files.sort(key=lambda p: str(p))

    # First pass: collect metadata and compute hashes
    scanned_items = []
    hash_counts = defaultdict(list)

    for p in raw_files:
        try:
            rel_path = p.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel_path = p.as_posix()
        size_bytes = p.stat().st_size
        content_sha256 = compute_file_sha256(p)
        file_id = compute_file_id(rel_path)
        ext = p.suffix.lower()
        filename = p.name

        # Determine collection
        try:
            rel_to_raw = p.relative_to(raw_dir)
            collection = rel_to_raw.parts[0] if len(rel_to_raw.parts) > 1 else "root"
        except ValueError:
            collection = "unknown"

        # Check legacy info if available
        legacy_info = legacy_map.get(rel_path, {})
        legacy_id = legacy_info.get("legacy_id")

        accessibility = "accessible"
        if filename.startswith("~$") or size_bytes == 0:
            accessibility = "unreadable"

        detected_type = legacy_info.get("detected_type") or ext.lstrip(".")

        item = {
            "file_id": file_id,
            "legacy_id": legacy_id,
            "relative_path": rel_path,
            "filename": filename,
            "extension": ext,
            "detected_type": detected_type,
            "size_bytes": size_bytes,
            "content_sha256": content_sha256,
            "collection": legacy_info.get("collection") or collection,
            "accessibility_status": legacy_info.get("accessibility_status") or accessibility,
            "duplicate_group": legacy_info.get("duplicate_group", "none"),
        }
        scanned_items.append(item)
        hash_counts[content_sha256].append(item)

    # Reconcile duplicate groups from content hash if not already assigned
    for sha, group in hash_counts.items():
        if len(group) > 1:
            # Check if an existing legacy duplicate_group is shared
            existing_dup = next((item["duplicate_group"] for item in group if item["duplicate_group"] != "none"), None)
            dup_id = existing_dup or f"DUP-{sha[:12]}"
            for item in group:
                item["duplicate_group"] = dup_id
        else:
            group[0]["duplicate_group"] = "none"

    return scanned_items


def sync_inventory_to_db(db_path: Path = None, raw_dir: Path = RAW_DIR) -> Tuple[int, int]:
    """
    Scans raw sources and synchronizes all records to SQLite `sources` table.
    Reconciles removed and relocated files:
    - Preserves legacy IDs for relocated files matching existing content hashes.
    - Updates removed or relocated sources to 'missing' or 'relocated' status.
    - Prevents missing sources from silently remaining marked as active.
    Returns (total_scanned_records, total_bytes).
    """
    init_db(db_path)
    conn = get_db_connection(db_path)

    # 1. Fetch existing database records to compare
    cur = conn.execute("SELECT * FROM sources")
    existing_rows = [dict(r) for r in cur.fetchall()]
    existing_by_file_id = {r["file_id"]: r for r in existing_rows}
    existing_by_sha = defaultdict(list)
    for r in existing_rows:
        existing_by_sha[r["content_sha256"]].append(r)

    # 2. Scan physical files on disk
    sources = scan_raw_sources(raw_dir)
    scanned_by_file_id = {s["file_id"]: s for s in sources}
    scanned_by_rel_path = {s["relative_path"]: s for s in sources}
    scanned_by_sha = defaultdict(list)
    for s in sources:
        scanned_by_sha[s["content_sha256"]].append(s)

    # 3. Preserve legacy source IDs for relocated files
    for s in sources:
        if not s.get("legacy_id"):
            candidates = existing_by_sha.get(s["content_sha256"], [])
            for cand in candidates:
                cand_legacy = cand.get("legacy_id")
                if cand_legacy and cand["relative_path"] not in scanned_by_rel_path:
                    s["legacy_id"] = cand_legacy
                    break

    # 4. Upsert scanned sources
    total_bytes = 0
    for src in sources:
        upsert_source(conn, src)
        total_bytes += src["size_bytes"]

    # 5. Reconcile removed / relocated sources from prior inventory
    now = datetime.now(timezone.utc).isoformat()
    for old_fid, old_rec in existing_by_file_id.items():
        if old_fid not in scanned_by_file_id:
            old_rel_path = old_rec["relative_path"]
            old_file_path = (
                Path(old_rel_path) if Path(old_rel_path).is_absolute() else REPO_ROOT / old_rel_path
            )
            if not old_file_path.exists():
                if old_rec["content_sha256"] in scanned_by_sha:
                    new_status = "relocated"
                else:
                    new_status = "missing"

                with conn:
                    conn.execute(
                        "UPDATE sources SET accessibility_status = ?, updated_at = ? WHERE file_id = ?",
                        (new_status, now, old_fid),
                    )

    conn.close()
    return len(sources), total_bytes
