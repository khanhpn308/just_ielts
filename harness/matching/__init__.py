"""Matching engine and relationship resolver package for IELTS Data Harness V0.3-A."""

from harness.matching.engine import MATCHER_VERSION, MatchingEngine, compute_conflict_id
from harness.matching.metadata import (
    DocumentRole,
    SourceDocumentMetadata,
    canonicalize_volume,
    extract_source_metadata,
)

__all__ = [
    "MATCHER_VERSION",
    "MatchingEngine",
    "compute_conflict_id",
    "SourceDocumentMetadata",
    "DocumentRole",
    "canonicalize_volume",
    "extract_source_metadata",
]
