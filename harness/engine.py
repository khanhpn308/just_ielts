"""Extraction orchestration and checkpoint/resume engine for Harness V0.1."""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import traceback
from typing import Any, Dict, List, Optional

from harness.adapters import (
    AudioMetaExtractor,
    BaseExtractor,
    DocxExtractor,
    PdfNativeExtractor,
    PdfOcrExtractor,
    XlsxExtractor,
)
from harness.classifier import classify_source
from harness.config import (
    OUTPUT_SCHEMA_VERSION,
    PILOT_SOURCE_IDS,
    RAW_DIR,
    REPO_ROOT,
    STAGING_DIR,
)
from harness.db import (
    check_checkpoint_validity,
    get_checkpoint,
    get_db_connection,
    get_source_by_file_id,
    get_source_by_legacy_id,
    list_sources,
    record_checkpoint_completion,
    record_checkpoint_failure,
    record_checkpoint_start,
)

logger = logging.getLogger("harness.engine")


def get_adapter_for_source(source_record: Dict[str, Any], adapter_override: Optional[str] = None) -> BaseExtractor:
    """Selects and instantiates the appropriate extraction adapter."""
    adapter_name = adapter_override
    if not adapter_name:
        cls_info = classify_source(source_record)
        adapter_name = cls_info.get("recommended_adapter")

    if adapter_name == "pdf_native":
        return PdfNativeExtractor()
    elif adapter_name == "pdf_ocr":
        return PdfOcrExtractor()
    elif adapter_name == "docx":
        return DocxExtractor()
    elif adapter_name == "xlsx":
        return XlsxExtractor()
    elif adapter_name == "audio_meta":
        return AudioMetaExtractor()
    else:
        raise ValueError(f"No suitable extraction adapter found for source {source_record.get('legacy_id')}")


class ExtractionEngine:
    """Orchestrates source extraction with granular checkpointing, resume, and retry."""

    def __init__(self, db_path: Optional[Path] = None, staging_dir: Optional[Path] = None):
        self.db_path = db_path
        self.staging_dir = staging_dir or STAGING_DIR
        self.stage = "raw_extraction"
        self.schema_version = OUTPUT_SCHEMA_VERSION

    def process_unit(
        self,
        conn,
        source_record: Dict[str, Any],
        adapter: BaseExtractor,
        output_dir: Path,
        unit_id: str,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Processes a single extraction unit with checkpoint verification."""
        file_id = source_record["file_id"]
        legacy_id = source_record.get("legacy_id") or "UNKNOWN"
        source_sha256 = source_record["content_sha256"]
        processing_unit = "page" if unit_id.startswith("page_") else "document"

        # Check existing checkpoint
        if not force:
            is_valid = check_checkpoint_validity(
                conn=conn,
                file_id=file_id,
                stage=self.stage,
                parser_version=adapter.version,
                config_hash=adapter.config_hash,
                output_schema_version=self.schema_version,
                processing_unit=processing_unit,
                unit_identifier=unit_id,
                current_source_sha256=source_sha256,
            )
            if is_valid:
                cp = get_checkpoint(
                    conn,
                    file_id,
                    self.stage,
                    adapter.version,
                    adapter.config_hash,
                    self.schema_version,
                    processing_unit,
                    unit_id,
                )
                return {
                    "unit_identifier": unit_id,
                    "status": "SKIPPED",
                    "output_path": cp.get("output_path"),
                    "output_sha256": cp.get("output_sha256"),
                    "error": None,
                }

        # Record start of execution
        expected_output = str(output_dir / f"{unit_id}.json")
        record_checkpoint_start(
            conn=conn,
            file_id=file_id,
            legacy_id=legacy_id,
            source_sha256=source_sha256,
            stage=self.stage,
            parser_version=adapter.version,
            config_hash=adapter.config_hash,
            output_schema_version=self.schema_version,
            processing_unit=processing_unit,
            unit_identifier=unit_id,
            output_path=expected_output,
        )

        try:
            res = adapter.extract_unit(source_record, output_dir, unit_id)
            record_checkpoint_completion(
                conn=conn,
                file_id=file_id,
                stage=self.stage,
                parser_version=adapter.version,
                config_hash=adapter.config_hash,
                output_schema_version=self.schema_version,
                processing_unit=processing_unit,
                unit_identifier=unit_id,
                output_path=res["output_path"],
                output_sha256=res["output_sha256"],
                output_validity=res.get("output_validity", "valid"),
            )
            return {
                "unit_identifier": unit_id,
                "status": "COMPLETED",
                "output_path": res["output_path"],
                "output_sha256": res["output_sha256"],
                "error": None,
            }
        except Exception as e:
            err_msg = f"{type(e).__name__}: {str(e)}"
            record_checkpoint_failure(
                conn=conn,
                file_id=file_id,
                legacy_id=legacy_id,
                source_sha256=source_sha256,
                stage=self.stage,
                parser_version=adapter.version,
                config_hash=adapter.config_hash,
                output_schema_version=self.schema_version,
                processing_unit=processing_unit,
                unit_identifier=unit_id,
                error_message=err_msg,
            )
            # Remove any lingering .tmp file
            tmp_candidate = Path(expected_output).with_name(f"{Path(expected_output).name}.tmp")
            if tmp_candidate.exists():
                tmp_candidate.unlink()
            return {
                "unit_identifier": unit_id,
                "status": "FAILED",
                "output_path": None,
                "output_sha256": None,
                "error": err_msg,
            }

    def process_source(
        self,
        source_record: Dict[str, Any],
        force: bool = False,
        specific_unit: Optional[str] = None,
        adapter_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Processes all units of a single source record and writes a manifest."""
        conn = get_db_connection(self.db_path)
        legacy_id = source_record.get("legacy_id") or source_record["file_id"]
        output_dir = self.staging_dir / legacy_id
        output_dir.mkdir(parents=True, exist_ok=True)

        adapter = get_adapter_for_source(source_record, adapter_override)
        units = adapter.get_processing_units(source_record)

        if specific_unit:
            if specific_unit not in units:
                conn.close()
                raise ValueError(f"Requested unit '{specific_unit}' not in valid units {units}")
            units = [specific_unit]

        results = []
        completed_count = 0
        skipped_count = 0
        failed_count = 0

        for unit_id in units:
            unit_res = self.process_unit(
                conn=conn,
                source_record=source_record,
                adapter=adapter,
                output_dir=output_dir,
                unit_id=unit_id,
                force=force,
            )
            results.append(unit_res)
            st = unit_res["status"]
            if st == "COMPLETED":
                completed_count += 1
            elif st == "SKIPPED":
                skipped_count += 1
            elif st == "FAILED":
                failed_count += 1

        # Write summary manifest for multi-unit or completed sources
        manifest_path = output_dir / "manifest.json"
        manifest_payload = {
            "file_id": source_record["file_id"],
            "legacy_id": legacy_id,
            "relative_path": source_record["relative_path"],
            "source_sha256": source_record["content_sha256"],
            "parser_name": adapter.name,
            "parser_version": adapter.version,
            "config_hash": adapter.config_hash,
            "output_schema_version": self.schema_version,
            "total_units": len(units),
            "completed_units": completed_count,
            "skipped_units": skipped_count,
            "failed_units": failed_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "units": results,
        }
        adapter.atomic_write_json(manifest_path, manifest_payload)

        conn.close()
        return {
            "source_id": legacy_id,
            "file_id": source_record["file_id"],
            "total_units": len(units),
            "completed": completed_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "manifest_path": str(manifest_path),
            "results": results,
        }

    def process_all_pilots(self, force: bool = False) -> List[Dict[str, Any]]:
        """Processes the 7 unique pilot sources."""
        conn = get_db_connection(self.db_path)
        sources = list_sources(conn, pilot_only=True, pilot_ids=PILOT_SOURCE_IDS)
        conn.close()

        source_map = {s["legacy_id"]: s for s in sources}
        results = []
        for pid in PILOT_SOURCE_IDS:
            if pid not in source_map:
                logger.warning(f"Pilot source {pid} not found in database inventory.")
                continue
            src = source_map[pid]
            res = self.process_source(src, force=force)
            results.append(res)
        return results
