"""Independent Source Verification & Ground Truth Reference Validation for IELTS Data Harness V0.3-B."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from harness.config import DB_PATH, REPO_ROOT
from harness.db import get_source_by_file_id, get_source_by_legacy_id
from harness.matching.metadata import SourceDocumentMetadata, extract_source_metadata


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
    traceable_locations: Optional[Dict[str, Any]] = None


class SourceReferenceValidator:
    """Validates referenced source documents against inventory, hashes, non-circularity, and relationship evidence."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        repo_root: Optional[Path] = None,
        allow_synthetic_fixtures: Optional[bool] = None,
        synthetic_fixtures: Optional[Dict[str, Any]] = None,
    ):
        self.conn = conn
        self.repo_root = repo_root or REPO_ROOT
        self.allow_synthetic_fixtures = allow_synthetic_fixtures
        self.synthetic_fixtures = dict(synthetic_fixtures or {})

    def is_isolated_test_context(self) -> bool:
        """Determines if execution is currently within an isolated test context."""
        in_test_env = bool(
            os.environ.get("PYTEST_CURRENT_TEST")
            or os.environ.get("JUST_IELTS_TEST_ENV")
        )
        if not in_test_env:
            return False

        try:
            cur = self.conn.execute("PRAGMA database_list")
            db_rows = cur.fetchall()
            if db_rows:
                db_file = db_rows[0][2]
                if db_file and Path(db_file).resolve() == DB_PATH.resolve():
                    return False
        except Exception:
            pass

        return True

    def validate_source_identity(
        self,
        reference_source_id: str,
        candidate_target_file_id: Optional[str] = None,
        candidate_target_legacy_id: Optional[str] = None,
        candidate_source_file_id: Optional[str] = None,
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

        if candidate_source_file_id:
            source_rec = get_source_by_file_id(self.conn, candidate_source_file_id)
            if source_rec:
                src_sha = (source_rec.get("content_sha256") or "").strip().lower()
                src_legacy = source_rec.get("legacy_id")
                if (
                    ref_file_id == candidate_source_file_id
                    or (ref_legacy_id and ref_legacy_id == src_legacy)
                    or (ref_sha and src_sha and ref_sha == src_sha)
                    or (ref_rec.get("relative_path") == source_rec.get("relative_path"))
                ):
                    reasons.append(
                        f"Circular evidence: reference source '{reference_source_id}' "
                        f"points to the candidate source file itself ({candidate_source_file_id})."
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

                if prov_src and candidate_source_file_id:
                    if prov_src == candidate_source_file_id:
                        reasons.append(
                            f"Circular evidence provenance: provenance source_id '{prov_src}' references source candidate."
                        )
                        flags.append("CIRCULAR_GROUND_TRUTH_REJECTED")

        is_valid = len(reasons) == 0
        if is_valid:
            flags.append("SOURCE_IDENTITY_VERIFIED")
        return is_valid, ref_rec, flags, reasons

    def load_source_evidence(
        self,
        ref_rec: Dict[str, Any],
        evidence_references: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[SourceDocumentMetadata], List[str], List[str], Optional[Dict[str, Any]]]:
        """Loads evidence strictly from trusted extraction artifacts or isolated synthetic test fixtures."""
        flags: List[str] = []
        reasons: List[str] = []
        traceable_locations: Dict[str, Any] = {}

        # 1. Never trust caller-supplied staged_data as verified source content
        if evidence_references and isinstance(evidence_references, dict) and "staged_data" in evidence_references:
            reasons.append(
                "Untrusted caller-supplied staged_data rejected: caller-supplied staged_data cannot serve as verified source content."
            )
            flags.append("CALLER_STAGED_DATA_REJECTED")

        # 2. Check physical source file
        rel_path = ref_rec.get("relative_path", "")
        disk_p = (self.repo_root / rel_path) if rel_path else None
        physical_exists = bool(disk_p and disk_p.is_file())

        meta: Optional[SourceDocumentMetadata] = None
        trusted_extraction_found = False
        verified_units: List[str] = []

        # 3. Load evidence from trusted, inventory-linked extraction artifacts with verified checksums
        staging_dir = self.repo_root / "private" / "staging" / "raw_extracted" / (
            ref_rec.get("legacy_id") or ref_rec.get("file_id") or ""
        )
        if staging_dir.is_dir():
            manifest_p = staging_dir / "manifest.json"
            if manifest_p.is_file():
                try:
                    manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
                    m_sha = (manifest.get("source_sha256") or "").lower()
                    r_sha = (ref_rec.get("content_sha256") or "").lower()
                    m_fid = manifest.get("file_id")
                    m_lid = manifest.get("legacy_id")
                    r_fid = ref_rec.get("file_id")
                    r_lid = ref_rec.get("legacy_id")

                    if m_sha == r_sha and (m_fid == r_fid or (m_lid and m_lid == r_lid)):
                        unit_errors = []
                        for u in manifest.get("units", []):
                            u_path_str = u.get("output_path")
                            if u_path_str:
                                u_path = Path(u_path_str)
                                if not u_path.is_file():
                                    unit_errors.append(f"Missing unit file '{u_path.name}' in extraction staging.")
                                elif u.get("output_sha256"):
                                    actual_u_sha = hashlib.sha256(u_path.read_bytes()).hexdigest()
                                    if actual_u_sha.lower() != u["output_sha256"].lower():
                                        unit_errors.append(
                                            f"Checksum mismatch for extraction unit '{u_path.name}' "
                                            f"({actual_u_sha[:8]} != {u['output_sha256'][:8]})."
                                        )
                                    else:
                                        verified_units.append(u.get("unit_identifier") or u_path.name)
                        if not unit_errors and verified_units:
                            trusted_extraction_found = True
                        elif unit_errors:
                            reasons.extend(unit_errors)
                            flags.append("EXTRACTION_CHECKSUM_MISMATCH")
                except Exception as e:
                    reasons.append(f"Error parsing extraction manifest: {e}")
                    flags.append("INVALID_EXTRACTION_MANIFEST")

        if not trusted_extraction_found and not reasons:
            try:
                cur = self.conn.execute(
                    "SELECT unit_identifier, processing_unit, output_path, output_sha256, source_sha256, status "
                    "FROM processing_checkpoints "
                    "WHERE (file_id = ? OR legacy_id = ?) AND stage = 'raw_extraction' AND status = 'COMPLETED'",
                    (ref_rec.get("file_id"), ref_rec.get("legacy_id")),
                )
                cp_rows = cur.fetchall()
                if cp_rows:
                    cp_errors = []
                    for row in cp_rows:
                        cp_u_path = Path(row["output_path"]) if row["output_path"] else None
                        if not cp_u_path or not cp_u_path.is_file():
                            cp_errors.append(f"Checkpoint unit file missing: {row['unit_identifier']}")
                        else:
                            actual_sha = hashlib.sha256(cp_u_path.read_bytes()).hexdigest()
                            if actual_sha.lower() != (row["output_sha256"] or "").lower():
                                cp_errors.append(
                                    f"Checkpoint unit checksum mismatch: {row['unit_identifier']} "
                                    f"({actual_sha[:8]} != {str(row['output_sha256'])[:8]})"
                                )
                            else:
                                verified_units.append(row["unit_identifier"])
                    if not cp_errors and verified_units:
                        trusted_extraction_found = True
                    elif cp_errors:
                        reasons.extend(cp_errors)
                        flags.append("EXTRACTION_CHECKSUM_MISMATCH")
            except sqlite3.Error:
                pass

        if trusted_extraction_found and not reasons:
            meta = extract_source_metadata(ref_rec, staged_dir=staging_dir)
            rel_staging = str(staging_dir.relative_to(self.repo_root)) if staging_dir.is_relative_to(self.repo_root) else str(staging_dir)
            traceable_locations = {
                "provenance_type": "trusted_extraction_artifact",
                "source_file": rel_path,
                "extraction_dir": rel_staging,
                "verified_units": verified_units,
            }
            flags.append("TRUSTED_EXTRACTION_LOADED")

        # 4. Check synthetic fixtures (only in isolated test contexts)
        if not trusted_extraction_found and not reasons:
            is_isolated = self.is_isolated_test_context()
            can_use_synthetic = is_isolated and (self.allow_synthetic_fixtures is not False)

            lid = ref_rec.get("legacy_id") or ""
            fid = ref_rec.get("file_id") or ""
            is_private_path = rel_path.startswith("private/")

            is_synthetic_src = not is_private_path and (
                ref_rec.get("collection") in ("synthetic", "VOL 99", "VOL 88")
                or lid.startswith("SRC-SYN-")
                or fid.startswith("FILE-a0")
                or (lid in self.synthetic_fixtures)
                or (fid in self.synthetic_fixtures)
            )

            if is_synthetic_src and not can_use_synthetic:
                flags.append("SYNTHETIC_FIXTURE_NOT_PERMITTED")
                reasons.append("Synthetic fixture injection is permitted only in isolated test contexts.")
            elif is_synthetic_src and can_use_synthetic:
                staged = None
                if lid in self.synthetic_fixtures:
                    staged = self.synthetic_fixtures[lid]
                    traceable_locations = {
                        "provenance_type": "synthetic_test_fixture",
                        "fixture_context": "injected_synthetic_fixtures",
                        "legacy_id": lid,
                    }
                elif fid in self.synthetic_fixtures:
                    staged = self.synthetic_fixtures[fid]
                    traceable_locations = {
                        "provenance_type": "synthetic_test_fixture",
                        "fixture_context": "injected_synthetic_fixtures",
                        "file_id": fid,
                    }
                else:
                    syn_fixtures_file = (
                        self.repo_root / "tests" / "fixtures" / "synthetic_relationships" / "synthetic_test_sources.json"
                    )
                    if syn_fixtures_file.is_file():
                        try:
                            syn_data = json.loads(syn_fixtures_file.read_text(encoding="utf-8"))
                            for syn_src in syn_data.get("sources", []):
                                if (
                                    syn_src.get("file_id") == fid
                                    or (lid and syn_src.get("legacy_id") == lid)
                                ):
                                    staged = syn_src.get("staged_data")
                                    traceable_locations = {
                                        "provenance_type": "synthetic_test_fixture",
                                        "fixture_file": "tests/fixtures/synthetic_relationships/synthetic_test_sources.json",
                                        "legacy_id": syn_src.get("legacy_id"),
                                    }
                                    break
                        except Exception:
                            pass

                meta = extract_source_metadata(ref_rec, staged_data=staged)
                flags.append("SYNTHETIC_TEST_FIXTURE_LOADED")
                if not traceable_locations:
                    traceable_locations = {
                        "provenance_type": "synthetic_test_fixture",
                        "source_file": rel_path,
                        "legacy_id": lid or fid,
                    }

        # 5. Handle missing physical source and missing extraction artifact
        if meta is None and not reasons:
            if not physical_exists:
                flags.append("MISSING_PHYSICAL_SOURCE_AND_EXTRACTION")
                reasons.append(
                    f"Reference source '{ref_rec.get('legacy_id') or ref_rec.get('file_id')}' physical file is missing "
                    "and has no trusted extraction artifact."
                )
            else:
                flags.append("MISSING_TRUSTED_EXTRACTION")
                reasons.append(
                    f"Reference source '{ref_rec.get('legacy_id') or ref_rec.get('file_id')}' has physical file on disk "
                    "but no trusted extraction artifact with verified checksums."
                )

        is_valid = len(reasons) == 0 and meta is not None
        return is_valid, meta, flags, reasons, (traceable_locations if is_valid else None)

    def validate_relationship_evidence(
        self,
        ref_rec: Dict[str, Any],
        expected_collection: str,
        expected_test_number: Optional[int],
        expected_passage_or_section: Optional[int] = None,
        relationship_type: Optional[str] = None,
        evidence_references: Optional[Dict[str, Any]] = None,
        candidate_target_file_id: Optional[str] = None,
        meta: Optional[SourceDocumentMetadata] = None,
        traceable_locations: Optional[Dict[str, Any]] = None,
        candidate_source_file_id: Optional[str] = None,
    ) -> Tuple[bool, List[str], List[str], Optional[Dict[int, str]], Dict[str, Any]]:
        """Verifies test identity, question/section alignment, and positive content evidence."""
        flags: List[str] = []
        reasons: List[str] = []
        trace_locs = dict(traceable_locations or {})

        if meta is None:
            load_ok, meta, l_flags, l_reasons, l_trace = self.load_source_evidence(
                ref_rec, evidence_references=evidence_references
            )
            flags.extend(l_flags)
            reasons.extend(l_reasons)
            if l_trace:
                trace_locs.update(l_trace)
            if not load_ok or meta is None:
                return False, flags, reasons, None, trace_locs

        # 1. Collection alignment
        ref_col = ref_rec.get("collection") or ""
        if expected_collection and ref_col != expected_collection:
            reasons.append(
                f"Collection mismatch: reference source belongs to '{ref_col}', expected '{expected_collection}'."
            )
            flags.append("COLLECTION_MISMATCH")

        # 2. Positive evidence of required test identity
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
                trace_locs["test_number"] = expected_test_number
        else:
            if not meta.test_numbers:
                reasons.append(
                    f"Missing test metadata in reference source '{ref_rec.get('legacy_id') or ref_rec.get('file_id')}'; "
                    "test identity cannot be verified."
                )
                flags.append("MISSING_TEST_METADATA")

        # 3. Question / Section Alignment & Positive Content Evidence
        # An answer key containing answers for the same Test is not sufficient for confirmation.
        test_keys: Dict[int, str] = {}
        if expected_test_number is not None and meta.answer_keys and expected_test_number in meta.answer_keys:
            test_keys = meta.answer_keys[expected_test_number]

        in_range_keys: Dict[int, str] = {}

        if expected_passage_or_section is not None:
            trace_locs["passage_or_section"] = expected_passage_or_section
            if expected_test_number is not None and meta.passages_or_sections:
                cov_passages = meta.passages_or_sections.get(expected_test_number, [])
                if cov_passages and expected_passage_or_section not in cov_passages:
                    reasons.append(
                        f"Passage/section mismatch: reference source covers sections {cov_passages} for Test {expected_test_number}, "
                        f"not section/passage {expected_passage_or_section}."
                    )
                    flags.append("PASSAGE_MISMATCH")

            range_map = {1: (1, 14), 2: (14, 27), 3: (27, 40), 4: (31, 40)}
            r_min, r_max = range_map.get(expected_passage_or_section, (1, 40))
            in_range_keys = {q: ans for q, ans in test_keys.items() if r_min <= q <= r_max}

            has_matching_answers = bool(len(in_range_keys) > 0)
            has_title_evidence = bool(
                expected_test_number is not None
                and meta.passage_titles
                and expected_test_number in meta.passage_titles
                and expected_passage_or_section in meta.passage_titles[expected_test_number]
            )
            has_audio_evidence = bool(
                meta.raw_content_summary.get("audio_track") is not None
                and meta.raw_content_summary.get("audio_track") == expected_passage_or_section
            )
            has_transcript_evidence = bool(
                meta.passages_or_sections
                and any(expected_passage_or_section in s for s in meta.passages_or_sections.values())
            )

            if relationship_type in ("question_to_answer_key", "question_to_explanation"):
                if not has_matching_answers and not (relationship_type == "question_to_explanation" and has_title_evidence):
                    reasons.append(
                        f"Reference source '{ref_rec.get('legacy_id') or ref_rec.get('file_id')}' provides no answer key or "
                        f"content evidence for section/passage {expected_passage_or_section} of Test {expected_test_number} "
                        f"(expected questions {r_min}-{r_max}). An answer key containing answers for the same Test is not sufficient for confirmation."
                    )
                    flags.append("NO_MATCHING_QUESTION_EVIDENCE")
                else:
                    if has_matching_answers:
                        trace_locs["matching_questions"] = sorted(list(in_range_keys.keys()))
                        trace_locs["question_range"] = [r_min, r_max]
            else:
                if not (has_matching_answers or has_title_evidence or has_audio_evidence or has_transcript_evidence):
                    reasons.append(
                        f"Reference source provides no content evidence for section {expected_passage_or_section}. "
                        "Matching volume alone is insufficient."
                    )
                    flags.append("NO_CONTENT_EVIDENCE")
        else:
            # Whole test scope (expected_passage_or_section is None)
            has_matching_answers = bool(len(test_keys) > 0)
            has_title_evidence = bool(
                expected_test_number is not None
                and meta.passage_titles
                and expected_test_number in meta.passage_titles
            )
            if relationship_type in ("question_to_answer_key", "question_to_explanation"):
                if not has_matching_answers and not (relationship_type == "question_to_explanation" and has_title_evidence):
                    reasons.append(
                        f"Reference source provides no answer key evidence for Test {expected_test_number}. "
                        "Matching volume alone is insufficient."
                    )
                    flags.append("NO_CONTENT_EVIDENCE")
                elif has_matching_answers:
                    trace_locs["matching_questions"] = sorted(list(test_keys.keys()))

        # 4. Content alignment between Actual Relationship Participants
        target_rec = get_source_by_file_id(self.conn, candidate_target_file_id) if candidate_target_file_id else None
        tgt_meta: Optional[SourceDocumentMetadata] = None
        if target_rec:
            tgt_ok, t_m, _, _, _ = self.load_source_evidence(target_rec)
            if tgt_ok:
                tgt_meta = t_m

        source_rec = get_source_by_file_id(self.conn, candidate_source_file_id) if candidate_source_file_id else None
        src_meta: Optional[SourceDocumentMetadata] = None
        if source_rec:
            src_ok, s_m, _, _, _ = self.load_source_evidence(source_rec)
            if src_ok:
                src_meta = s_m

        # Synthetic evidence isolation check: never allow synthetic evidence to validate production relationships
        is_synthetic_ref = not ref_rec.get("relative_path", "").startswith("private/") and (
            ref_rec.get("collection") in ("synthetic", "VOL 99", "VOL 88")
            or (ref_rec.get("legacy_id") or "").startswith("SRC-SYN-")
            or (ref_rec.get("file_id") or "").startswith("FILE-a0")
        )
        target_is_prod = bool(
            target_rec and (
                target_rec.get("relative_path", "").startswith("private/")
                or target_rec.get("collection") not in ("synthetic", "VOL 99", "VOL 88")
            )
        )
        source_is_prod = bool(
            source_rec and (
                source_rec.get("relative_path", "").startswith("private/")
                or source_rec.get("collection") not in ("synthetic", "VOL 99", "VOL 88")
            )
        )
        expected_is_prod = bool(
            expected_collection and expected_collection not in ("synthetic", "VOL 99", "VOL 88")
        )
        if is_synthetic_ref and (target_is_prod or source_is_prod or expected_is_prod):
            reasons.append(
                "Synthetic evidence isolation violation: Synthetic evidence is strictly prohibited from validating "
                "production relationships or sources."
            )
            flags.append("SYNTHETIC_EVIDENCE_FORBIDDEN_IN_PRODUCTION")

        # Title alignment check
        s_title = None
        t_title = None
        ref_title = None
        if expected_test_number is not None:
            if expected_passage_or_section is not None:
                if src_meta and src_meta.passage_titles:
                    s_title = src_meta.passage_titles.get(expected_test_number, {}).get(expected_passage_or_section)
                if tgt_meta and tgt_meta.passage_titles:
                    t_title = tgt_meta.passage_titles.get(expected_test_number, {}).get(expected_passage_or_section)
                if meta and meta.passage_titles:
                    ref_title = meta.passage_titles.get(expected_test_number, {}).get(expected_passage_or_section)
            else:
                if src_meta and src_meta.passage_titles and expected_test_number in src_meta.passage_titles:
                    s_title = next(iter(src_meta.passage_titles[expected_test_number].values()), None)
                if tgt_meta and tgt_meta.passage_titles and expected_test_number in tgt_meta.passage_titles:
                    t_title = next(iter(tgt_meta.passage_titles[expected_test_number].values()), None)
                if meta and meta.passage_titles and expected_test_number in meta.passage_titles:
                    ref_title = next(iter(meta.passage_titles[expected_test_number].values()), None)

        def _clean_title(t: Optional[str]) -> str:
            if not t:
                return ""
            return re.sub(r"[^\w\s]", "", t.lower()).strip()

        norm_s = _clean_title(s_title)
        norm_t = _clean_title(t_title)
        norm_ref = _clean_title(ref_title)

        has_title_match = False
        title_contradiction = False

        if norm_s and norm_t:
            if norm_s in norm_t or norm_t in norm_s:
                has_title_match = True
            else:
                title_contradiction = True
                reasons.append(
                    f"Contradictory passage titles: source participant title '{s_title}' "
                    f"contradicts target participant title '{t_title}'."
                )
                flags.append("PASSAGE_TITLE_MISMATCH")

        if norm_ref:
            if norm_s:
                if norm_s in norm_ref or norm_ref in norm_s:
                    has_title_match = True
                elif not title_contradiction:
                    title_contradiction = True
                    reasons.append(
                        f"Passage title mismatch: reference source title '{ref_title}' "
                        f"contradicts source candidate title '{s_title}'."
                    )
                    flags.append("PASSAGE_TITLE_MISMATCH")
            if norm_t:
                if norm_t in norm_ref or norm_ref in norm_t:
                    has_title_match = True
                elif not title_contradiction:
                    title_contradiction = True
                    reasons.append(
                        f"Passage title mismatch: reference source title '{ref_title}' "
                        f"contradicts target candidate title '{t_title}'."
                    )
                    flags.append("PASSAGE_TITLE_MISMATCH")

        # Answer key alignment check
        relevant_ref_keys = in_range_keys if in_range_keys else test_keys
        has_verified_answer_match = False
        from harness.matching.engine import normalize_answer_value

        if tgt_meta and expected_test_number is not None and expected_test_number in tgt_meta.answer_keys:
            tgt_keys = tgt_meta.answer_keys[expected_test_number]
            overlap_tgt = set(relevant_ref_keys.keys()).intersection(set(tgt_keys.keys()))
            if overlap_tgt:
                contradictions = []
                matching_ans = []
                for q in sorted(overlap_tgt):
                    r_val, _, _ = normalize_answer_value(relevant_ref_keys[q])
                    t_val, _, _ = normalize_answer_value(tgt_keys[q])
                    if r_val is not None and t_val is not None:
                        if r_val == t_val:
                            matching_ans.append(q)
                        else:
                            contradictions.append((q, r_val, t_val))
                if contradictions:
                    reasons.append(
                        f"Contradictory answer key evidence: reference source contradicts candidate target answers "
                        f"on {len(contradictions)} questions: {[f'Q{q}' for q, _, _ in contradictions[:5]]}."
                    )
                    flags.append("CONFLICTING_ANSWER_KEYS")
                elif matching_ans:
                    has_verified_answer_match = True

        if src_meta and expected_test_number is not None and expected_test_number in src_meta.answer_keys:
            src_keys = src_meta.answer_keys[expected_test_number]
            overlap_src = set(relevant_ref_keys.keys()).intersection(set(src_keys.keys()))
            if overlap_src:
                contradictions = []
                matching_ans = []
                for q in sorted(overlap_src):
                    r_val, _, _ = normalize_answer_value(relevant_ref_keys[q])
                    s_val, _, _ = normalize_answer_value(src_keys[q])
                    if r_val is not None and s_val is not None:
                        if r_val == s_val:
                            matching_ans.append(q)
                        else:
                            contradictions.append((q, r_val, s_val))
                if contradictions:
                    reasons.append(
                        f"Contradictory answer key evidence: reference source contradicts candidate source answers "
                        f"on {len(contradictions)} questions: {[f'Q{q}' for q, _, _ in contradictions[:5]]}."
                    )
                    flags.append("CONFLICTING_ANSWER_KEYS")
                elif matching_ans:
                    has_verified_answer_match = True

        if (
            src_meta and tgt_meta and expected_test_number is not None
            and expected_test_number in src_meta.answer_keys
            and expected_test_number in tgt_meta.answer_keys
        ):
            s_k = src_meta.answer_keys[expected_test_number]
            t_k = tgt_meta.answer_keys[expected_test_number]
            overlap_st = set(s_k.keys()).intersection(set(t_k.keys()))
            if overlap_st:
                contradictions = []
                matching_ans = []
                for q in sorted(overlap_st):
                    s_val, _, _ = normalize_answer_value(s_k[q])
                    t_val, _, _ = normalize_answer_value(t_k[q])
                    if s_val is not None and t_val is not None:
                        if s_val == t_val:
                            matching_ans.append(q)
                        else:
                            contradictions.append((q, s_val, t_val))
                if contradictions:
                    reasons.append(
                        f"Contradictory answer key evidence: candidate source contradicts candidate target answers "
                        f"on {len(contradictions)} questions: {[f'Q{q}' for q, _, _ in contradictions[:5]]}."
                    )
                    flags.append("CONFLICTING_ANSWER_KEYS")
                elif matching_ans:
                    has_verified_answer_match = True

        # Audio / transcript alignment
        has_audio_transcript_match = False
        if relationship_type in ("listening_to_audio", "listening_to_transcript"):
            if (
                meta.raw_content_summary.get("audio_track") is not None
                and expected_passage_or_section is not None
                and meta.raw_content_summary.get("audio_track") == expected_passage_or_section
            ):
                has_audio_transcript_match = True
            elif (
                meta.passages_or_sections
                and expected_passage_or_section is not None
                and any(expected_passage_or_section in s for s in meta.passages_or_sections.values())
            ):
                has_audio_transcript_match = True

        # Content alignment between relationship participants
        # An independent answer key merely containing question numbers in the same range
        # is NOT sufficient to verify content alignment between participants.
        is_content_aligned = bool(
            has_title_match or has_verified_answer_match or has_audio_transcript_match
        )

        if not is_content_aligned:
            reasons.append(
                "Independently verifiable alignment between the actual relationship participants is required. "
                "Relationship matches only on Volume, Test, Passage, and question numbers without verified "
                "content alignment (no matching title, verified answers, or transcript/audio); retaining review_required."
            )
            flags.append("INSUFFICIENT_CONTENT_ALIGNMENT")
            flags.append("REVIEW_REQUIRED_RETAINED")

        is_valid = len(reasons) == 0 and is_content_aligned
        if is_valid:
            flags.append("RELATIONSHIP_EVIDENCE_VERIFIED")
            flags.append("CONTENT_ALIGNMENT_VERIFIED")

        extracted_keys: Optional[Dict[int, str]] = None
        if is_valid:
            extracted_keys = in_range_keys if (expected_passage_or_section is not None and in_range_keys) else test_keys

        return is_valid, flags, reasons, extracted_keys, trace_locs

    def validate_reference(
        self,
        reference_source_id: str,
        expected_collection: str,
        expected_test_number: Optional[int],
        candidate_target_file_id: str,
        candidate_target_legacy_id: Optional[str] = None,
        candidate_source_file_id: Optional[str] = None,
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
            candidate_source_file_id=candidate_source_file_id,
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
                traceable_locations=None,
            )

        eff_refs = evidence_references or evidence_provenance
        load_valid, meta, load_flags, load_reasons, traceable_locations = self.load_source_evidence(
            ref_rec, evidence_references=eff_refs
        )
        if not load_valid or not meta:
            return SourceValidationResult(
                is_valid=False,
                source_record=ref_rec,
                flags=list(id_flags) + list(load_flags),
                rejection_reasons=list(id_reasons) + list(load_reasons),
                identity_verified=id_valid,
                evidence_verified=False,
                traceable_locations=None,
            )

        ev_valid, ev_flags, ev_reasons, extracted_keys, final_trace = self.validate_relationship_evidence(
            ref_rec=ref_rec,
            expected_collection=expected_collection,
            expected_test_number=expected_test_number,
            expected_passage_or_section=expected_passage_or_section,
            relationship_type=relationship_type,
            evidence_references=eff_refs,
            candidate_target_file_id=candidate_target_file_id,
            candidate_source_file_id=candidate_source_file_id,
            meta=meta,
            traceable_locations=traceable_locations,
        )

        all_flags = list(id_flags) + list(load_flags) + list(ev_flags)
        all_reasons = list(id_reasons) + list(load_reasons) + list(ev_reasons)
        is_overall_valid = id_valid and load_valid and ev_valid

        if is_overall_valid:
            all_flags.append("INDEPENDENT_SOURCE_VERIFIED")
            all_flags.append("CONTENT_ALIGNMENT_ESTABLISHED")

        return SourceValidationResult(
            is_valid=is_overall_valid,
            source_record=ref_rec,
            flags=all_flags,
            rejection_reasons=all_reasons,
            verified_answers=extracted_keys,
            identity_verified=id_valid,
            evidence_verified=ev_valid,
            traceable_locations=final_trace if is_overall_valid else None,
        )
