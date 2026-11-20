"""Independent Source Verification & Ground Truth Reference Validation for IELTS Data Harness V0.3-B."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from harness.config import REPO_ROOT
from harness.db import get_source_by_file_id, get_source_by_legacy_id
from harness.matching.metadata import extract_source_metadata


class SourceVerificationError(Exception):
    """Raised when an external or ground-truth source reference fails integrity checks."""
    pass


class CircularEvidenceError(SourceVerificationError):
    """Raised when ground truth is circular (sourced from candidate itself)."""
    pass


class UnregisteredSourceError(SourceVerificationError):
    """Raised when referenced ground truth source is not cataloged in inventory."""
    pass


class SourceHashMismatchError(SourceVerificationError):
    """Raised when source hash does not match inventory or on-disk content."""
    pass


class IdentityMismatchError(SourceVerificationError):
    """Raised when collection or test identity does not match."""
    pass


@dataclass
class SourceValidationResult:
    """Outcome of validating a reference source against inventory and policy."""

    is_valid: bool
    source_record: Optional[Dict[str, Any]] = None
    flags: List[str] = field(default_factory=list)
    rejection_reasons: List[str] = field(default_factory=list)
    verified_answers: Optional[Dict[int, str]] = None


class SourceReferenceValidator:
    """Validates referenced source documents against inventory, hashes, and non-circularity."""

    def __init__(self, conn: sqlite3.Connection, repo_root: Optional[Path] = None):
        self.conn = conn
        self.repo_root = repo_root or REPO_ROOT

    def validate_reference(
        self,
        reference_source_id: str,
        expected_collection: str,
        expected_test_number: Optional[int],
        candidate_target_file_id: str,
        candidate_target_legacy_id: Optional[str] = None,
        expected_hash: Optional[str] = None,
        evidence_provenance: Optional[Dict[str, Any]] = None,
        check_disk_hash: bool = True,
    ) -> SourceValidationResult:
        """Forensically checks whether reference source can serve as authoritative evidence."""
        flags: List[str] = []
        reasons: List[str] = []

        if not reference_source_id or not reference_source_id.strip():
            return SourceValidationResult(
                is_valid=False,
                flags=["MISSING_SOURCE_REFERENCE"],
                rejection_reasons=["Reference source ID is empty or not provided."],
            )

        # 1. Check existence in SQLite inventory
        ref_rec = get_source_by_legacy_id(self.conn, reference_source_id) or get_source_by_file_id(
            self.conn, reference_source_id
        )
        if not ref_rec:
            return SourceValidationResult(
                is_valid=False,
                flags=["UNREGISTERED_SOURCE_REJECTED"],
                rejection_reasons=[
                    f"Referenced source '{reference_source_id}' does not exist in SQLite inventory. "
                    "Unregistered sources cannot serve as authoritative evidence."
                ],
            )

        ref_file_id = ref_rec["file_id"]
        ref_legacy_id = ref_rec.get("legacy_id")
        ref_sha = ref_rec.get("content_sha256") or ""

        # 2. Check circularity: ground truth must NOT be sourced from candidate target itself
        target_rec = get_source_by_file_id(self.conn, candidate_target_file_id)
        if target_rec:
            tgt_sha = target_rec.get("content_sha256") or ""
            tgt_legacy = target_rec.get("legacy_id")
            if (
                ref_file_id == candidate_target_file_id
                or (ref_legacy_id and ref_legacy_id == tgt_legacy)
                or (candidate_target_legacy_id and ref_legacy_id == candidate_target_legacy_id)
                or (ref_sha and tgt_sha and ref_sha == tgt_sha)
                or (ref_rec.get("relative_path") == target_rec.get("relative_path"))
            ):
                return SourceValidationResult(
                    is_valid=False,
                    source_record=ref_rec,
                    flags=["CIRCULAR_GROUND_TRUTH_REJECTED"],
                    rejection_reasons=[
                        f"Circular answer key evidence: reference source '{reference_source_id}' "
                        f"points to the candidate target file itself ({candidate_target_file_id})."
                    ],
                )

        # 3. Source hash match
        if expected_hash and ref_sha != expected_hash:
            reasons.append(
                f"Source hash mismatch: recorded inventory SHA '{ref_sha}' does not match expected '{expected_hash}'."
            )
            flags.append("SOURCE_HASH_MISMATCH")

        if check_disk_hash and ref_rec.get("relative_path"):
            disk_p = self.repo_root / ref_rec["relative_path"]
            if disk_p.is_file():
                try:
                    actual_disk_sha = hashlib.sha256(disk_p.read_bytes()).hexdigest()
                    if actual_disk_sha != ref_sha:
                        reasons.append(
                            f"Stale on-disk source: physical file '{ref_rec['relative_path']}' "
                            f"hash '{actual_disk_sha}' does not match inventory hash '{ref_sha}'."
                        )
                        flags.append("STALE_SOURCE_HASH")
                except OSError as e:
                    reasons.append(f"Cannot read physical source file '{disk_p}': {e}")
                    flags.append("SOURCE_INACCESSIBLE")

        # 4. Collection & Test Identity alignment
        ref_col = ref_rec.get("collection") or ""
        if expected_collection and ref_col != expected_collection:
            reasons.append(
                f"Collection mismatch: reference source belongs to '{ref_col}', "
                f"expected '{expected_collection}'."
            )
            flags.append("COLLECTION_MISMATCH")

        # Extract metadata to check test coverage and answer keys
        meta = extract_source_metadata(ref_rec, staged_data=ref_rec.get("staged_data"))
        if expected_test_number is not None:
            if meta.test_numbers and expected_test_number not in meta.test_numbers:
                reasons.append(
                    f"Test number mismatch: reference source covers tests {meta.test_numbers}, "
                    f"not expected Test {expected_test_number}."
                )
                flags.append("TEST_NUMBER_MISMATCH")

        # 5. Provenance validation for reviewer-provided evidence
        if evidence_provenance is not None:
            if not isinstance(evidence_provenance, dict) or len(evidence_provenance) == 0:
                reasons.append("Evidence provenance is empty or invalid dictionary.")
                flags.append("INVALID_PROVENANCE")
            else:
                has_audit_field = any(
                    k in evidence_provenance
                    for k in ("provenance_type", "authority", "source_id", "verifier", "operator_id")
                )
                if not has_audit_field:
                    reasons.append("Evidence provenance missing audit tracking fields (e.g. provenance_type, authority).")
                    flags.append("INCOMPLETE_PROVENANCE")

        # Check extracted answers for expected test
        extracted_keys: Optional[Dict[int, str]] = None
        if expected_test_number is not None and meta.answer_keys:
            extracted_keys = meta.answer_keys.get(expected_test_number)

        if reasons:
            return SourceValidationResult(
                is_valid=False,
                source_record=ref_rec,
                flags=flags,
                rejection_reasons=reasons,
                verified_answers=extracted_keys,
            )

        flags.append("INDEPENDENT_SOURCE_VERIFIED")
        return SourceValidationResult(
            is_valid=True,
            source_record=ref_rec,
            flags=flags,
            verified_answers=extracted_keys,
        )
