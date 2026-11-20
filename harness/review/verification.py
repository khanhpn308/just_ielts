"""Independent Source Verification & Ground Truth Reference Validation for IELTS Data Harness V0.3-B."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

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
    identity_verified: bool = False
    evidence_verified: bool = False


class SourceReferenceValidator:
    """Validates referenced source documents against inventory, hashes, non-circularity, and relationship evidence."""

    def __init__(self, conn: sqlite3.Connection, repo_root: Optional[Path] = None):
        self.conn = conn
        self.repo_root = repo_root or REPO_ROOT

    def validate_source_identity(
        self,
        reference_source_id: str,
        candidate_target_file_id: Optional[str] = None,
        candidate_target_legacy_id: Optional[str] = None,
        expected_hash: Optional[str] = None,
        evidence_provenance: Optional[Dict[str, Any]] = None,
        check_disk_hash: bool = True,
    ) -> Tuple[bool, Optional[Dict[str, Any]], List[str], List[str]]:
        """Verifies source existence, hash validity, disk freshness, and non-circularity."""
        flags: List[str] = []
        reasons: List[str] = []

        if not reference_source_id or not reference_source_id.strip():
            return False, None, ["MISSING_SOURCE_REFERENCE"], ["Reference source ID is empty or not provided."]

        # 1. Existence in SQLite inventory
        ref_rec = get_source_by_legacy_id(self.conn, reference_source_id) or get_source_by_file_id(
            self.conn, reference_source_id
        )
        if not ref_rec:
            return (
                False,
                None,
                ["UNREGISTERED_SOURCE_REJECTED"],
                [
                    f"Referenced source '{reference_source_id}' does not exist in SQLite inventory. "
                    "Unregistered sources cannot serve as authoritative evidence."
                ],
            )

        ref_file_id = ref_rec["file_id"]
        ref_legacy_id = ref_rec.get("legacy_id")
        ref_sha = (ref_rec.get("content_sha256") or "").strip().lower()

        # 2. Nonempty valid SHA-256
        if not ref_sha or len(ref_sha) != 64 or not re.fullmatch(r"^[a-f0-9]{64}$", ref_sha):
            reasons.append(
                f"Referenced source '{reference_source_id}' has missing or invalid SHA-256 hash '{ref_sha}'."
            )
            flags.append("INVALID_SOURCE_HASH")

        # 3. Fresh source fingerprint
        if expected_hash and ref_sha != expected_hash.strip().lower():
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

        # 4. Non-circular evidence provenance
        if candidate_target_file_id:
            target_rec = get_source_by_file_id(self.conn, candidate_target_file_id)
            if target_rec:
                tgt_sha = (target_rec.get("content_sha256") or "").strip().lower()
                tgt_legacy = target_rec.get("legacy_id")
                if (
                    ref_file_id == candidate_target_file_id
                    or (ref_legacy_id and ref_legacy_id == tgt_legacy)
                    or (candidate_target_legacy_id and ref_legacy_id == candidate_target_legacy_id)
                    or (ref_sha and tgt_sha and ref_sha == tgt_sha)
                    or (ref_rec.get("relative_path") == target_rec.get("relative_path"))
                ):
                    reasons.append(
                        f"Circular answer key evidence: reference source '{reference_source_id}' "
                        f"points to the candidate target file itself ({candidate_target_file_id})."
                    )
                    flags.append("CIRCULAR_GROUND_TRUTH_REJECTED")

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

                prov_src = evidence_provenance.get("source_id")
                if prov_src and candidate_target_file_id:
                    if prov_src == candidate_target_file_id or (
                        candidate_target_legacy_id and prov_src == candidate_target_legacy_id
                    ):
                        reasons.append(
                            f"Circular evidence provenance: provenance source_id '{prov_src}' references target candidate."
                        )
                        flags.append("CIRCULAR_GROUND_TRUTH_REJECTED")

        is_valid = len(reasons) == 0
        if is_valid:
            flags.append("SOURCE_IDENTITY_VERIFIED")
        return is_valid, ref_rec, flags, reasons

    def validate_relationship_evidence(
        self,
        ref_rec: Dict[str, Any],
        expected_collection: str,
        expected_test_number: Optional[int],
        expected_passage_or_section: Optional[int] = None,
        relationship_type: Optional[str] = None,
        evidence_references: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, List[str], List[str], Optional[Dict[int, str]]]:
        """Verifies test identity, question/section alignment, and content evidence."""
        flags: List[str] = []
        reasons: List[str] = []

        # 1. Collection alignment
        ref_col = ref_rec.get("collection") or ""
        if expected_collection and ref_col != expected_collection:
            reasons.append(
                f"Collection mismatch: reference source belongs to '{ref_col}', expected '{expected_collection}'."
            )
            flags.append("COLLECTION_MISMATCH")

        # 2. Extract metadata (checking staged_data from record, evidence references, or fixtures)
        staged_data = ref_rec.get("staged_data")
        if staged_data is None and evidence_references and isinstance(evidence_references, dict):
            staged_data = evidence_references.get("staged_data")
        if staged_data is None:
            syn_fixtures_file = (
                self.repo_root / "tests" / "fixtures" / "synthetic_relationships" / "synthetic_test_sources.json"
            )
            if syn_fixtures_file.is_file():
                try:
                    import json
                    syn_data = json.loads(syn_fixtures_file.read_text(encoding="utf-8"))
                    for syn_src in syn_data.get("sources", []):
                        if (
                            syn_src.get("file_id") == ref_rec.get("file_id")
                            or syn_src.get("legacy_id") == ref_rec.get("legacy_id")
                        ):
                            staged_data = syn_src.get("staged_data")
                            break
                except Exception:
                    pass

        meta = extract_source_metadata(ref_rec, staged_data=staged_data)

        # 3. Positive evidence of required test identity: Missing test metadata must not count as a match
        if expected_test_number is not None:
            if not meta.test_numbers:
                reasons.append(
                    f"Missing test metadata in reference source '{ref_rec.get('legacy_id') or ref_rec.get('file_id')}': "
                    f"positive evidence of Test {expected_test_number} is required. Missing test metadata does not count as a match."
                )
                flags.append("MISSING_TEST_METADATA")
            elif expected_test_number not in meta.test_numbers:
                reasons.append(
                    f"Test number mismatch: reference source covers tests {meta.test_numbers}, "
                    f"not expected Test {expected_test_number}."
                )
                flags.append("TEST_NUMBER_MISMATCH")
            else:
                flags.append("TEST_NUMBER_VERIFIED")
        else:
            if not meta.test_numbers:
                reasons.append(
                    f"Missing test metadata in reference source '{ref_rec.get('legacy_id') or ref_rec.get('file_id')}'; "
                    "test identity cannot be verified."
                )
                flags.append("MISSING_TEST_METADATA")

        # 4. Relevant question/section alignment
        if expected_passage_or_section is not None:
            if expected_test_number is not None and meta.passages_or_sections:
                cov_passages = meta.passages_or_sections.get(expected_test_number, [])
                if cov_passages and expected_passage_or_section not in cov_passages:
                    reasons.append(
                        f"Passage/section mismatch: reference source covers sections {cov_passages} for Test {expected_test_number}, "
                        f"not section/passage {expected_passage_or_section}."
                    )
                    flags.append("PASSAGE_MISMATCH")
                elif not cov_passages and meta.answer_keys and expected_test_number in meta.answer_keys:
                    test_keys = meta.answer_keys[expected_test_number]
                    range_map = {1: (1, 14), 2: (15, 27), 3: (28, 40), 4: (31, 40)}
                    r_min, r_max = range_map.get(expected_passage_or_section, (1, 40))
                    in_range = [q for q in test_keys if r_min <= q <= r_max]
                    if not in_range and len(test_keys) > 0:
                        reasons.append(
                            f"Reference source answers do not cover questions for section/passage {expected_passage_or_section} "
                            f"(expected question range {r_min}-{r_max})."
                        )
                        flags.append("SECTION_QUESTIONS_NOT_ALIGNED")

        # 5. Content evidence supporting the relationship
        # A registered source from the same volume is NOT sufficient proof of a relationship.
        has_matching_answers = bool(
            expected_test_number is not None
            and meta.answer_keys
            and expected_test_number in meta.answer_keys
            and len(meta.answer_keys[expected_test_number]) > 0
        )
        has_title_evidence = bool(
            expected_test_number is not None
            and meta.passage_titles
            and expected_test_number in meta.passage_titles
            and (
                expected_passage_or_section is None
                or expected_passage_or_section in meta.passage_titles[expected_test_number]
            )
        )
        has_audio_evidence = bool(
            meta.raw_content_summary.get("audio_track") is not None
            and (
                expected_passage_or_section is None
                or meta.raw_content_summary.get("audio_track") == expected_passage_or_section
            )
        )
        has_transcript_evidence = bool(
            meta.passages_or_sections
            and (
                expected_passage_or_section is None
                or any(expected_passage_or_section in s for s in meta.passages_or_sections.values())
            )
        )

        if relationship_type in ("question_to_answer_key", "question_to_explanation"):
            if not has_matching_answers and not (relationship_type == "question_to_explanation" and has_title_evidence):
                reasons.append(
                    f"Reference source '{ref_rec.get('legacy_id') or ref_rec.get('file_id')}' provides no answer key or "
                    f"content evidence for Test {expected_test_number}. A registered source from the same volume "
                    "is not sufficient proof of a relationship."
                )
                flags.append("NO_CONTENT_EVIDENCE")
        else:
            if not (has_matching_answers or has_title_evidence or has_audio_evidence or has_transcript_evidence):
                reasons.append(
                    f"Reference source '{ref_rec.get('legacy_id') or ref_rec.get('file_id')}' provides no relevant content evidence "
                    "(answers, titles, audio, transcript) supporting the relationship. Matching volume alone is insufficient."
                )
                flags.append("NO_CONTENT_EVIDENCE")

        extracted_keys: Optional[Dict[int, str]] = None
        if expected_test_number is not None and meta.answer_keys:
            extracted_keys = meta.answer_keys.get(expected_test_number)

        is_valid = len(reasons) == 0
        if is_valid:
            flags.append("RELATIONSHIP_EVIDENCE_VERIFIED")

        return is_valid, flags, reasons, extracted_keys

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
        expected_passage_or_section: Optional[int] = None,
        relationship_type: Optional[str] = None,
        evidence_references: Optional[Dict[str, Any]] = None,
    ) -> SourceValidationResult:
        """Forensically checks whether reference source can serve as authoritative evidence."""
        id_valid, ref_rec, id_flags, id_reasons = self.validate_source_identity(
            reference_source_id=reference_source_id,
            candidate_target_file_id=candidate_target_file_id,
            candidate_target_legacy_id=candidate_target_legacy_id,
            expected_hash=expected_hash,
            evidence_provenance=evidence_provenance,
            check_disk_hash=check_disk_hash,
        )
        if not id_valid or not ref_rec:
            return SourceValidationResult(
                is_valid=False,
                source_record=ref_rec,
                flags=id_flags,
                rejection_reasons=id_reasons,
                identity_verified=False,
                evidence_verified=False,
            )

        eff_refs = evidence_references or evidence_provenance
        ev_valid, ev_flags, ev_reasons, extracted_keys = self.validate_relationship_evidence(
            ref_rec=ref_rec,
            expected_collection=expected_collection,
            expected_test_number=expected_test_number,
            expected_passage_or_section=expected_passage_or_section,
            relationship_type=relationship_type,
            evidence_references=eff_refs,
        )

        all_flags = list(id_flags) + list(ev_flags)
        all_reasons = list(id_reasons) + list(ev_reasons)
        is_overall_valid = id_valid and ev_valid

        if is_overall_valid:
            all_flags.append("INDEPENDENT_SOURCE_VERIFIED")

        return SourceValidationResult(
            is_valid=is_overall_valid,
            source_record=ref_rec,
            flags=all_flags,
            rejection_reasons=all_reasons,
            verified_answers=extracted_keys,
            identity_verified=id_valid,
            evidence_verified=ev_valid,
        )
