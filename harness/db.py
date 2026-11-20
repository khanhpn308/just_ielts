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
                relocated_from TEXT,
                relocated_to TEXT,
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

            CREATE TABLE IF NOT EXISTS normalization_checkpoints (
                checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                source_file_id TEXT NOT NULL REFERENCES sources(file_id),
                source_legacy_id TEXT NOT NULL,
                normalizer_version TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL,
                canonical_content_sha256 TEXT NOT NULL,
                output_path TEXT NOT NULL,
                output_sha256 TEXT NOT NULL,
                lifecycle_status TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(entity_id, normalizer_version, raw_sha256)
            );

            CREATE INDEX IF NOT EXISTS idx_norm_checkpoints_entity ON normalization_checkpoints(entity_id);
            CREATE INDEX IF NOT EXISTS idx_norm_checkpoints_status ON normalization_checkpoints(status);
            CREATE INDEX IF NOT EXISTS idx_norm_checkpoints_source ON normalization_checkpoints(source_file_id);
            CREATE INDEX IF NOT EXISTS idx_norm_checkpoints_lifecycle ON normalization_checkpoints(lifecycle_status);

            CREATE TABLE IF NOT EXISTS source_relationships (
                relationship_id TEXT PRIMARY KEY,
                source_file_id TEXT NOT NULL REFERENCES sources(file_id),
                target_file_id TEXT NOT NULL REFERENCES sources(file_id),
                relationship_type TEXT NOT NULL,
                collection TEXT NOT NULL,
                volume TEXT NOT NULL,
                test_number INTEGER,
                passage_or_section INTEGER,
                skill TEXT NOT NULL,
                identity_evidence TEXT NOT NULL,
                validation_flags TEXT NOT NULL,
                match_confidence REAL NOT NULL,
                relationship_status TEXT NOT NULL,
                provenance TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_rel_source ON source_relationships(source_file_id);
            CREATE INDEX IF NOT EXISTS idx_rel_target ON source_relationships(target_file_id);
            CREATE INDEX IF NOT EXISTS idx_rel_status ON source_relationships(relationship_status);
            CREATE INDEX IF NOT EXISTS idx_rel_type ON source_relationships(relationship_type);
            CREATE INDEX IF NOT EXISTS idx_rel_volume ON source_relationships(volume);

            CREATE TABLE IF NOT EXISTS relationship_conflicts (
                conflict_id TEXT PRIMARY KEY,
                relationship_id TEXT REFERENCES source_relationships(relationship_id),
                source_file_id TEXT NOT NULL REFERENCES sources(file_id),
                target_file_id TEXT NOT NULL REFERENCES sources(file_id),
                conflict_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                description TEXT NOT NULL,
                evidence TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_conflicts_rel ON relationship_conflicts(relationship_id);
            CREATE INDEX IF NOT EXISTS idx_conflicts_src ON relationship_conflicts(source_file_id);
            CREATE INDEX IF NOT EXISTS idx_conflicts_type ON relationship_conflicts(conflict_type);

            CREATE TABLE IF NOT EXISTS relationship_reviews (
                review_id TEXT PRIMARY KEY,
                relationship_id TEXT NOT NULL REFERENCES source_relationships(relationship_id),
                previous_status TEXT NOT NULL,
                new_status TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_reviews_rel ON relationship_reviews(relationship_id);
            """
        )
        # Migrate schema dynamically if table was created previously without relocation columns
        cur = conn.execute("PRAGMA table_info(sources)")
        existing_cols = {row["name"] for row in cur.fetchall()}
        if "relocated_from" not in existing_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN relocated_from TEXT")
        if "relocated_to" not in existing_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN relocated_to TEXT")
    conn.close()


def upsert_source(conn: sqlite3.Connection, source_data: Dict[str, Any]) -> None:
    """Inserts or updates a source record."""
    now = datetime.now(timezone.utc).isoformat()
    sql = """
        INSERT INTO sources (
            file_id, legacy_id, relative_path, filename, extension,
            detected_type, size_bytes, content_sha256, collection,
            duplicate_group, accessibility_status, relocated_from, relocated_to,
            created_at, updated_at
        ) VALUES (
            :file_id, :legacy_id, :relative_path, :filename, :extension,
            :detected_type, :size_bytes, :content_sha256, :collection,
            :duplicate_group, :accessibility_status, :relocated_from, :relocated_to,
            :created_at, :updated_at
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
            relocated_from = COALESCE(excluded.relocated_from, sources.relocated_from),
            relocated_to = COALESCE(excluded.relocated_to, sources.relocated_to),
            updated_at = excluded.updated_at
    """
    params = dict(source_data)
    params.setdefault("relocated_from", None)
    params.setdefault("relocated_to", None)
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

    valid_file_ids = {file_id}
    src_rec = get_source_by_file_id(conn, file_id)
    if src_rec and src_rec.get("relocated_from"):
        valid_file_ids.add(src_rec["relocated_from"])
    if prov.get("file_id") not in valid_file_ids:
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


def upsert_normalization_checkpoint(conn: sqlite3.Connection, cp_data: Dict[str, Any]) -> None:
    """Inserts or updates a normalization checkpoint record."""
    now = datetime.now(timezone.utc).isoformat()
    sql = """
        INSERT INTO normalization_checkpoints (
            entity_id, entity_type, source_file_id, source_legacy_id,
            normalizer_version, schema_version, config_hash, raw_sha256,
            canonical_content_sha256, output_path, output_sha256,
            lifecycle_status, status, created_at, updated_at
        ) VALUES (
            :entity_id, :entity_type, :source_file_id, :source_legacy_id,
            :normalizer_version, :schema_version, :config_hash, :raw_sha256,
            :canonical_content_sha256, :output_path, :output_sha256,
            :lifecycle_status, :status, :created_at, :updated_at
        )
        ON CONFLICT(entity_id, normalizer_version, raw_sha256) DO UPDATE SET
            schema_version = excluded.schema_version,
            config_hash = excluded.config_hash,
            canonical_content_sha256 = excluded.canonical_content_sha256,
            output_path = excluded.output_path,
            output_sha256 = excluded.output_sha256,
            lifecycle_status = excluded.lifecycle_status,
            status = excluded.status,
            updated_at = excluded.updated_at
    """
    params = dict(cp_data)
    params.setdefault("created_at", now)
    params["updated_at"] = now
    with conn:
        conn.execute(sql, params)


def get_normalization_checkpoint(
    conn: sqlite3.Connection,
    entity_id: str,
    normalizer_version: str,
    raw_sha256: str,
) -> Optional[Dict[str, Any]]:
    """Retrieves a normalization checkpoint by its unique key."""
    sql = """
        SELECT * FROM normalization_checkpoints
        WHERE entity_id = ? AND normalizer_version = ? AND raw_sha256 = ?
    """
    cur = conn.execute(sql, (entity_id, normalizer_version, raw_sha256))
    row = cur.fetchone()
    return dict(row) if row else None


def is_normalization_checkpoint_valid(
    conn: sqlite3.Connection,
    entity_id: str,
    normalizer_version: str,
    raw_sha256: str,
    config_hash: str,
    schema_version: str,
) -> bool:
    """Checks whether an existing normalization checkpoint is fresh and valid on disk."""
    cp = get_normalization_checkpoint(conn, entity_id, normalizer_version, raw_sha256)
    if not cp:
        return False
    if cp.get("status") != "COMPLETED":
        return False
    if cp.get("config_hash") != config_hash:
        return False
    if cp.get("schema_version") != schema_version:
        return False

    out_path = Path(cp["output_path"])
    if not out_path.exists():
        return False

    try:
        content_bytes = out_path.read_bytes()
    except OSError:
        return False

    actual_sha = hashlib.sha256(content_bytes).hexdigest()
    if actual_sha != cp["output_sha256"]:
        return False

    return True


def list_normalization_checkpoints(
    conn: sqlite3.Connection,
    entity_type: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lists normalization checkpoints with optional filtering."""
    clauses = []
    params = []
    if entity_type:
        clauses.append("entity_type = ?")
        params.append(entity_type)
    if status:
        clauses.append("status = ?")
        params.append(status)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM normalization_checkpoints {where_sql} ORDER BY checkpoint_id ASC"
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def count_normalization_by_lifecycle(conn: sqlite3.Connection) -> Dict[str, int]:
    """Returns counts of normalization checkpoints grouped by lifecycle_status."""
    cur = conn.execute(
        "SELECT lifecycle_status, COUNT(*) FROM normalization_checkpoints GROUP BY lifecycle_status"
    )
    return dict(cur.fetchall())


# --- V0.3-A Source Relationship Registry Operations ---


def upsert_source_relationship(conn: sqlite3.Connection, rel_data: Dict[str, Any]) -> None:
    """Inserts or updates a source relationship record."""
    now = datetime.now(timezone.utc).isoformat()
    params = dict(rel_data)
    params.setdefault("created_at", now)
    params["updated_at"] = now

    # Ensure JSON serializable fields are encoded
    for json_field in ("identity_evidence", "validation_flags", "provenance"):
        val = params.get(json_field)
        if isinstance(val, (dict, list)):
            params[json_field] = json.dumps(val, sort_keys=True)
        elif val is None:
            params[json_field] = "{}" if json_field != "validation_flags" else "[]"

    sql = """
        INSERT INTO source_relationships (
            relationship_id, source_file_id, target_file_id, relationship_type,
            collection, volume, test_number, passage_or_section, skill,
            identity_evidence, validation_flags, match_confidence,
            relationship_status, provenance, schema_version, created_at, updated_at
        ) VALUES (
            :relationship_id, :source_file_id, :target_file_id, :relationship_type,
            :collection, :volume, :test_number, :passage_or_section, :skill,
            :identity_evidence, :validation_flags, :match_confidence,
            :relationship_status, :provenance, :schema_version, :created_at, :updated_at
        )
        ON CONFLICT(relationship_id) DO UPDATE SET
            source_file_id = excluded.source_file_id,
            target_file_id = excluded.target_file_id,
            relationship_type = excluded.relationship_type,
            collection = excluded.collection,
            volume = excluded.volume,
            test_number = excluded.test_number,
            passage_or_section = excluded.passage_or_section,
            skill = excluded.skill,
            identity_evidence = excluded.identity_evidence,
            validation_flags = excluded.validation_flags,
            match_confidence = excluded.match_confidence,
            relationship_status = excluded.relationship_status,
            provenance = excluded.provenance,
            schema_version = excluded.schema_version,
            updated_at = excluded.updated_at
    """
    with conn:
        conn.execute(sql, params)


def _deserialize_rel_row(row: sqlite3.Row) -> Dict[str, Any]:
    """Helper to convert sqlite3.Row to dict and parse JSON fields."""
    d = dict(row)
    for k in ("identity_evidence", "validation_flags", "provenance"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
    return d


def get_source_relationship(conn: sqlite3.Connection, relationship_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a source relationship by its unique ID."""
    sql = "SELECT * FROM source_relationships WHERE relationship_id = ?"
    cur = conn.execute(sql, (relationship_id,))
    row = cur.fetchone()
    return _deserialize_rel_row(row) if row else None


def list_source_relationships(
    conn: sqlite3.Connection,
    status: Optional[str] = None,
    relationship_type: Optional[str] = None,
    source_file_id: Optional[str] = None,
    target_file_id: Optional[str] = None,
    volume: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lists source relationships with optional filtering."""
    clauses = []
    params = []
    if status:
        clauses.append("relationship_status = ?")
        params.append(status)
    if relationship_type:
        clauses.append("relationship_type = ?")
        params.append(relationship_type)
    if source_file_id:
        clauses.append("source_file_id = ?")
        params.append(source_file_id)
    if target_file_id:
        clauses.append("target_file_id = ?")
        params.append(target_file_id)
    if volume:
        clauses.append("volume = ?")
        params.append(volume)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM source_relationships {where_sql} ORDER BY created_at ASC"
    cur = conn.execute(sql, params)
    return [_deserialize_rel_row(r) for r in cur.fetchall()]


def count_relationships_by_status(conn: sqlite3.Connection) -> Dict[str, int]:
    """Returns relationship counts grouped by relationship_status."""
    cur = conn.execute(
        "SELECT relationship_status, COUNT(*) FROM source_relationships GROUP BY relationship_status"
    )
    return dict(cur.fetchall())


def count_relationships_by_type(conn: sqlite3.Connection) -> Dict[str, int]:
    """Returns relationship counts grouped by relationship_type."""
    cur = conn.execute(
        "SELECT relationship_type, COUNT(*) FROM source_relationships GROUP BY relationship_type"
    )
    return dict(cur.fetchall())


def record_relationship_conflict(conn: sqlite3.Connection, conflict_data: Dict[str, Any]) -> None:
    """Inserts a relationship conflict record."""
    params = dict(conflict_data)
    now = datetime.now(timezone.utc).isoformat()
    params.setdefault("created_at", now)

    evidence_val = params.get("evidence")
    if isinstance(evidence_val, (dict, list)):
        params["evidence"] = json.dumps(evidence_val, sort_keys=True)
    elif evidence_val is None:
        params["evidence"] = "{}"

    sql = """
        INSERT INTO relationship_conflicts (
            conflict_id, relationship_id, source_file_id, target_file_id,
            conflict_type, severity, description, evidence, created_at
        ) VALUES (
            :conflict_id, :relationship_id, :source_file_id, :target_file_id,
            :conflict_type, :severity, :description, :evidence, :created_at
        )
        ON CONFLICT(conflict_id) DO UPDATE SET
            relationship_id = excluded.relationship_id,
            conflict_type = excluded.conflict_type,
            severity = excluded.severity,
            description = excluded.description,
            evidence = excluded.evidence
    """
    with conn:
        conn.execute(sql, params)


def list_relationship_conflicts(
    conn: sqlite3.Connection,
    relationship_id: Optional[str] = None,
    conflict_type: Optional[str] = None,
    source_file_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lists conflict records with optional filtering."""
    clauses = []
    params = []
    if relationship_id:
        clauses.append("relationship_id = ?")
        params.append(relationship_id)
    if conflict_type:
        clauses.append("conflict_type = ?")
        params.append(conflict_type)
    if source_file_id:
        clauses.append("source_file_id = ?")
        params.append(source_file_id)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM relationship_conflicts {where_sql} ORDER BY created_at ASC"
    cur = conn.execute(sql, params)
    res = []
    for r in cur.fetchall():
        d = dict(r)
        if "evidence" in d and isinstance(d["evidence"], str):
            try:
                d["evidence"] = json.loads(d["evidence"])
            except Exception:
                pass
        res.append(d)
    return res


def record_relationship_review(conn: sqlite3.Connection, review_data: Dict[str, Any]) -> None:
    """Inserts a relationship review event."""
    params = dict(review_data)
    now = datetime.now(timezone.utc).isoformat()
    params.setdefault("created_at", now)

    sql = """
        INSERT INTO relationship_reviews (
            review_id, relationship_id, previous_status, new_status,
            reviewer, reason, created_at
        ) VALUES (
            :review_id, :relationship_id, :previous_status, :new_status,
            :reviewer, :reason, :created_at
        )
        ON CONFLICT(review_id) DO NOTHING
    """
    with conn:
        conn.execute(sql, params)


def list_relationship_reviews(
    conn: sqlite3.Connection, relationship_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Lists review events."""
    if relationship_id:
        cur = conn.execute(
            "SELECT * FROM relationship_reviews WHERE relationship_id = ? ORDER BY created_at ASC",
            (relationship_id,),
        )
    else:
        cur = conn.execute("SELECT * FROM relationship_reviews ORDER BY created_at ASC")
    return [dict(r) for r in cur.fetchall()]


