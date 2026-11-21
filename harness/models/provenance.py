"""Provenance envelope model for IELTS Data Harness V0.2."""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class ProvenanceEnvelope(BaseModel):
    """Standard backward-traceable provenance envelope aligning with V0.1 sources."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["v0.2.0-normalized", "v0.3.0-listening", "v0.3.0-normalized"] = "v0.2.0-normalized"
    source_file_id: str = Field(
        ...,
        pattern=r"^FILE-[a-f0-9]{12}$",
        description="Physical file identifier from V0.1 inventory (FILE-<sha256(relative_path)[:12]>)",
    )
    source_legacy_id: str = Field(
        ...,
        pattern=r"^(SRC-\d{3,4}|UNKNOWN)$",
        description="Authoritative legacy source identifier (e.g. SRC-011, SRC-138) from V0.1",
    )
    relative_path: str = Field(
        ...,
        description="Relative file path of raw document under private/raw/",
    )
    source_sha256: str = Field(
        ...,
        pattern=r"^[a-f0-9]{64}$",
        description="Cryptographic SHA-256 hash of original file bytes",
    )
    processing_unit: Literal["page", "document", "sheets", "audio_metadata", "transcript", "section", "audio"] = Field(
        ...,
        description="Type of processing unit from V0.1 extraction",
    )
    unit_identifier: str = Field(
        ...,
        description="Processing unit from V0.1 extraction (e.g. page_0001, raw_document, raw_sheets)",
    )
    raw_block_locator: str = Field(
        ...,
        description="Granular locator within raw extraction (e.g. para_index:309, cell:B3, ocr_box)",
    )
    extractor_adapter: str = Field(
        ...,
        description="Extractor adapter name from V0.1",
    )
    extractor_version: str = Field(
        ...,
        description="Version of extractor adapter",
    )
    normalizer_version: str = Field(
        ...,
        description="Version of normalizer logic",
    )
    canonical_content_sha256: Optional[str] = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
        description="Deterministic SHA-256 of canonical payload (excluding volatile run timestamps)",
    )
    normalized_at: Optional[str] = Field(
        default=None,
        description="Optional ISO 8601 UTC timestamp of execution. Excluded from canonical content hash.",
    )
