"""Base extractor adapter class and atomic writing utilities."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from harness.config import OUTPUT_SCHEMA_VERSION, compute_config_hash


class BaseExtractor(ABC):
    """Abstract base class for all Harness V0.1 extraction adapters."""

    def __init__(self, name: str, version: str, config: Optional[Dict[str, Any]] = None):
        self.name = name
        self.version = version
        self.config = config or {}
        self.config_hash = compute_config_hash(self.config)
        self.output_schema_version = OUTPUT_SCHEMA_VERSION

    def build_provenance(
        self,
        source_record: Dict[str, Any],
        processing_unit: str,
        unit_identifier: str,
    ) -> Dict[str, Any]:
        """Constructs standardized provenance metadata for extracted artifacts."""
        return {
            "file_id": source_record["file_id"],
            "legacy_id": source_record.get("legacy_id") or "UNKNOWN",
            "relative_path": source_record["relative_path"],
            "source_sha256": source_record["content_sha256"],
            "parser_name": self.name,
            "parser_version": self.version,
            "config_hash": self.config_hash,
            "output_schema_version": self.output_schema_version,
            "processing_unit": processing_unit,
            "unit_identifier": unit_identifier,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def atomic_write_json(target_path: Path, payload: Dict[str, Any]) -> Tuple[str, int]:
        """
        Atomically writes dictionary payload as JSON to target_path.
        Uses a temporary file in the same directory and atomic rename (os.replace).
        Returns (sha256_hash, file_size_bytes).
        """
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target_path.with_name(f"{target_path.name}.tmp")

        serialized_data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        h = hashlib.sha256(serialized_data)
        file_sha256 = h.hexdigest()
        file_size = len(serialized_data)

        with open(tmp_path, "wb") as f:
            f.write(serialized_data)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, target_path)
        return file_sha256, file_size

    @abstractmethod
    def extract_unit(
        self,
        source_record: Dict[str, Any],
        output_dir: Path,
        unit_identifier: str,
    ) -> Dict[str, Any]:
        """Extracts a specific processing unit."""
        pass

    @abstractmethod
    def get_processing_units(self, source_record: Dict[str, Any]) -> List[str]:
        """Returns list of unit identifiers (e.g. ['page_0001', ...] or ['document'])."""
        pass
