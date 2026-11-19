"""SQLite database schema and state management for Harness V0.1."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness.config import DB_PATH, STATE_DIR


def get_db_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Creates a connection to SQLite with WAL mode and foreign keys enabled."""
    target_path = db_path or DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    """Initializes the database schema and required indexes."""
    conn = get_db_connection(db_path)
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                file_id TEXT PRIMARY KEY,
                legacy_id TEXT UNIQUE,
                relative_path TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                extension TEXT NOT NULL,
                detected_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                content_sha256 TEXT NOT NULL,
                collection TEXT NOT NULL,
                duplicate_group TEXT DEFAULT 'none',
                accessibility_status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_sources_legacy_id ON sources(legacy_id);
            CREATE INDEX IF NOT EXISTS idx_sources_content_sha256 ON sources(content_sha256);
            CREATE INDEX IF NOT EXISTS idx_sources_duplicate_group ON sources(duplicate_group);

            CREATE TABLE IF NOT EXISTS processing_checkpoints (
                checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL REFERENCES sources(file_id),
                legacy_id TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                stage TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                output_schema_version TEXT NOT NULL,
                processing_unit TEXT NOT NULL,
                unit_identifier TEXT NOT NULL,
                output_path TEXT,
                output_sha256 TEXT,
                output_validity TEXT NOT NULL DEFAULT 'unverified',
                status TEXT NOT NULL,
                retry_count INTEGER DEFAULT 0,
                error_message TEXT,
                error_history TEXT DEFAULT '[]',
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                UNIQUE(file_id, stage, parser_version, config_hash, output_schema_version, processing_unit, unit_identifier)
            );

            CREATE INDEX IF NOT EXISTS idx_checkpoints_lookup ON processing_checkpoints(file_id, stage, unit_identifier);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_status ON processing_checkpoints(status);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_legacy_id ON processing_checkpoints(legacy_id);
            """
        )
    conn.close()


def upsert_source(conn: sqlite3.Connection, source_data: Dict[str, Any]) -> None:
    """Inserts or updates a source record."""
    now = datetime.now(timezone.utc).isoformat()
    sql = """
        INSERT INTO sources (
            file_id, legacy_id, relative_path, filename, extension,
            detected_type, size_bytes, content_sha256, collection,
            duplicate_group, accessibility_status, created_at, updated_at
        ) VALUES (
            :file_id, :legacy_id, :relative_path, :filename, :extension,
            :detected_type, :size_bytes, :content_sha256, :collection,
            :duplicate_group, :accessibility_status, :created_at, :updated_at
        )
        ON CONFLICT(file_id) DO UPDATE SET
            legacy_id = excluded.legacy_id,
            relative_path = excluded.relative_path,
            filename = excluded.filename,
            extension = excluded.extension,
            detected_type = excluded.detected_type,
            size_bytes = excluded.size_bytes,
            content_sha256 = excluded.content_sha256,
            collection = excluded.collection,
            duplicate_group = excluded.duplicate_group,
            accessibility_status = excluded.accessibility_status,
            updated_at = excluded.updated_at
    """
    params = dict(source_data)
    params.setdefault("created_at", now)
    params["updated_at"] = now
    with conn:
        conn.execute(sql, params)


def get_source_by_file_id(conn: sqlite3.Connection, file_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a source record by file_id."""
    cur = conn.execute("SELECT * FROM sources WHERE file_id = ?", (file_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def get_source_by_legacy_id(conn: sqlite3.Connection, legacy_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a source record by legacy_id."""
    cur = conn.execute("SELECT * FROM sources WHERE legacy_id = ?", (legacy_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def list_sources(
    conn: sqlite3.Connection,
    pilot_only: bool = False,
    pilot_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Lists source records, optionally filtering to pilot sources."""
    if pilot_only and pilot_ids:
        placeholders = ",".join("?" for _ in pilot_ids)
        cur = conn.execute(
            f"SELECT * FROM sources WHERE legacy_id IN ({placeholders}) ORDER BY legacy_id",
            pilot_ids,
        )
    else:
        cur = conn.execute("SELECT * FROM sources ORDER BY legacy_id")
    return [dict(r) for r in cur.fetchall()]


def get_checkpoint(
    conn: sqlite3.Connection,
    file_id: str,
    stage: str,
    parser_version: str,
    config_hash: str,
    output_schema_version: str,
    processing_unit: str,
    unit_identifier: str,
) -> Optional[Dict[str, Any]]:
    """Retrieves an exact checkpoint record."""
    sql = """
        SELECT * FROM processing_checkpoints
        WHERE file_id = ? AND stage = ? AND parser_version = ?
          AND config_hash = ? AND output_schema_version = ?
          AND processing_unit = ? AND unit_identifier = ?
    """
    cur = conn.execute(
        sql,
        (
            file_id,
            stage,
            parser_version,
            config_hash,
            output_schema_version,
            processing_unit,
            unit_identifier,
        ),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def record_checkpoint_start(
    conn: sqlite3.Connection,
    file_id: str,
    legacy_id: str,
    source_sha256: str,
    stage: str,
    parser_version: str,
    config_hash: str,
    output_schema_version: str,
    processing_unit: str,
    unit_identifier: str,
    output_path: Optional[str] = None,
) -> None:
    """Marks a processing checkpoint as IN_PROGRESS."""
    now = datetime.now(timezone.utc).isoformat()
    sql = """
        INSERT INTO processing_checkpoints (
            file_id, legacy_id, source_sha256, stage, parser_version,
            config_hash, output_schema_version, processing_unit,
            unit_identifier, output_path, status, started_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'IN_PROGRESS', ?
        )
        ON CONFLICT(file_id, stage, parser_version, config_hash, output_schema_version, processing_unit, unit_identifier)
        DO UPDATE SET
            status = 'IN_PROGRESS',
            source_sha256 = excluded.source_sha256,
            output_path = excluded.output_path,
            started_at = excluded.started_at
    """
    with conn:
        conn.execute(
            sql,
            (
                file_id,
                legacy_id,
                source_sha256,
                stage,
                parser_version,
                config_hash,
                output_schema_version,
                processing_unit,
                unit_identifier,
                output_path,
                now,
            ),
        )


def record_checkpoint_completion(
    conn: sqlite3.Connection,
    file_id: str,
    stage: str,
    parser_version: str,
    config_hash: str,
    output_schema_version: str,
    processing_unit: str,
    unit_identifier: str,
    output_path: str,
    output_sha256: str,
    output_validity: str = "valid",
) -> None:
    """Marks a processing checkpoint as COMPLETED."""
    now = datetime.now(timezone.utc).isoformat()
    sql = """
        UPDATE processing_checkpoints SET
            status = 'COMPLETED',
            output_path = ?,
            output_sha256 = ?,
            output_validity = ?,
            error_message = NULL,
            completed_at = ?
        WHERE file_id = ? AND stage = ? AND parser_version = ?
          AND config_hash = ? AND output_schema_version = ?
          AND processing_unit = ? AND unit_identifier = ?
    """
    with conn:
        conn.execute(
            sql,
            (
                output_path,
                output_sha256,
                output_validity,
                now,
                file_id,
                stage,
                parser_version,
                config_hash,
                output_schema_version,
                processing_unit,
                unit_identifier,
            ),
        )


def record_checkpoint_failure(
    conn: sqlite3.Connection,
    file_id: str,
    legacy_id: str,
    source_sha256: str,
    stage: str,
    parser_version: str,
    config_hash: str,
    output_schema_version: str,
    processing_unit: str,
    unit_identifier: str,
    error_message: str,
) -> None:
    """Marks a processing checkpoint as FAILED, incrementing retry count and updating error history."""
    now = datetime.now(timezone.utc).isoformat()
    existing = get_checkpoint(
        conn,
        file_id,
        stage,
        parser_version,
        config_hash,
        output_schema_version,
        processing_unit,
        unit_identifier,
    )

    retry_count = 1
    error_history = []
    if existing:
        retry_count = (existing.get("retry_count") or 0) + 1
        raw_history = existing.get("error_history") or "[]"
        try:
            error_history = json.loads(raw_history)
        except Exception:
            error_history = []

    error_history.append({"timestamp": now, "error": error_message, "attempt": retry_count})

    sql = """
        INSERT INTO processing_checkpoints (
            file_id, legacy_id, source_sha256, stage, parser_version,
            config_hash, output_schema_version, processing_unit,
            unit_identifier, status, retry_count, error_message,
            error_history, output_validity, completed_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, 'FAILED', ?, ?, ?, 'invalid', ?
        )
        ON CONFLICT(file_id, stage, parser_version, config_hash, output_schema_version, processing_unit, unit_identifier)
        DO UPDATE SET
            status = 'FAILED',
            retry_count = excluded.retry_count,
            error_message = excluded.error_message,
            error_history = excluded.error_history,
            output_validity = 'invalid',
            completed_at = excluded.completed_at
    """
    with conn:
        conn.execute(
            sql,
            (
                file_id,
                legacy_id,
                source_sha256,
                stage,
                parser_version,
                config_hash,
                output_schema_version,
                processing_unit,
                unit_identifier,
                retry_count,
                error_message,
                json.dumps(error_history),
                now,
            ),
        )


def get_interrupted_sources(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Retrieves all sources that have IN_PROGRESS or FAILED checkpoints."""
    sql = """
        SELECT DISTINCT s.* FROM sources s
        JOIN processing_checkpoints cp ON s.file_id = cp.file_id
        WHERE cp.status IN ('FAILED', 'IN_PROGRESS')
        ORDER BY s.legacy_id
    """
    cur = conn.execute(sql)
    return [dict(r) for r in cur.fetchall()]


def check_checkpoint_validity(
    conn: sqlite3.Connection,
    file_id: str,
    stage: str,
    parser_version: str,
    config_hash: str,
    output_schema_version: str,
    processing_unit: str,
    unit_identifier: str,
    current_source_sha256: str,
) -> bool:
    """
    Verifies if an existing checkpoint is fully valid and can be safely skipped.
    Returns True ONLY IF:
    1. Checkpoint exists and status == 'COMPLETED'.
    2. Input source SHA-256 matches current_source_sha256.
    3. Parser version, config hash, and schema version match.
    4. Output file exists on disk and size > 0.
    5. Output SHA-256 matches recorded checksum.
    6. Output JSON structure is valid (contains 'provenance' and 'content' blocks).
    7. Output provenance matches expected source (file_id, source_sha256) and unit.
    """
    cp = get_checkpoint(
        conn,
        file_id,
        stage,
        parser_version,
        config_hash,
        output_schema_version,
        processing_unit,
        unit_identifier,
    )
    if not cp:
        return False
    if cp.get("status") != "COMPLETED":
        return False
    if cp.get("source_sha256") != current_source_sha256:
        return False
    if cp.get("parser_version") != parser_version:
        return False
    if cp.get("config_hash") != config_hash:
        return False
    if cp.get("output_schema_version") != output_schema_version:
        return False

    output_path = cp.get("output_path")
    if not output_path:
        return False
    p = Path(output_path)
    if not p.is_file() or p.stat().st_size == 0:
        return False

    recorded_sha = cp.get("output_sha256")
    if not recorded_sha:
        return False

    try:
        raw_bytes = p.read_bytes()
    except OSError:
        return False

    actual_sha = hashlib.sha256(raw_bytes).hexdigest()
    if actual_sha != recorded_sha:
        return False

    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except Exception:
        return False

    if not isinstance(data, dict):
        return False
    if "provenance" not in data or "content" not in data:
        return False

    prov = data["provenance"]
    if not isinstance(prov, dict):
        return False

    required_keys = [
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
    for k in required_keys:
        if not prov.get(k):
            return False

    if prov.get("file_id") != file_id:
        return False
    if prov.get("source_sha256") != current_source_sha256:
        return False
    if prov.get("processing_unit") != processing_unit:
        return False
    if prov.get("unit_identifier") != unit_identifier:
        return False
    if prov.get("parser_version") != parser_version:
        return False
    if prov.get("config_hash") != config_hash:
        return False
    if prov.get("output_schema_version") != output_schema_version:
        return False

    return True
