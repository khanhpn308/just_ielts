"""Review Policy Engine & Validation Gates for IELTS Data Harness V0.3-B."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from harness.config import REPO_ROOT
from harness.db import (
    ConcurrencyConflictError,
    DuplicateReviewError,
    get_source_by_file_id,
    list_relationship_conflicts,
)
from harness.models.relationship import RelationshipReview, RelationshipStatus, ReviewDecision
from harness.review.verification import SourceReferenceValidator

REVIEW_POLICY_VERSION = "v0.3.0-b"


class ReviewPolicyViolation(Exception):
    """Raised when an attempted review action violates review policy rules."""
    pass


class StaleRelationshipError(Exception):
    """Raised when relationship sources or evidence are stale."""
    pass


class ImmutableAuditError(Exception):
    """Raised when attempting to overwrite or mutate historical review audit logs."""
    pass


@dataclass
class PolicyEvaluationResult:
    """Outcome of validating a review decision against Review Policy V0.3-B."""

    can_proceed: bool
    decision: ReviewDecision
    previous_status: RelationshipStatus
    final_status: RelationshipStatus
    rejection_reasons: List[str] = field(default_factory=list)
    validation_flags: List[str] = field(default_factory=list)
    source_fingerprint: str = ""
    target_fingerprint: str = ""
    is_fresh: bool = True
    expert_verified: bool = False
    policy_version: str = REVIEW_POLICY_VERSION


class ReviewPolicyValidator:
    """Enforces deterministic review rules A through E."""

    def __init__(self, conn: sqlite3.Connection, repo_root: Optional[Path] = None):
        self.conn = conn
        self.repo_root = repo_root or REPO_ROOT
        self.source_validator = SourceReferenceValidator(conn, repo_root=self.repo_root)

    def evaluate_decision(
        self,
        relationship: Dict[str, Any],
        decision: ReviewDecision,
        reviewer_id: str,
        reason: str,
        reviewed_at: str,
        evidence_references: Optional[Dict[str, Any]] = None,
        evidence_source_id: Optional[str] = None,
        expert_verified: bool = False,
    ) -> PolicyEvaluationResult:
        """Evaluates an operator review decision against strict epistemic gates."""
        rejection_reasons: List[str] = []
        validation_flags: List[str] = list(relationship.get("validation_flags") or [])
        prev_status: RelationshipStatus = relationship.get("relationship_status") or "candidate"

        # 1. Validate Reviewer Identity (Operator Declaration)
        if not reviewer_id or not str(reviewer_id).strip():
            rejection_reasons.append("Reviewer identity is required and cannot be empty.")
        elif len(str(reviewer_id).strip()) < 2:
            rejection_reasons.append(f"Reviewer identity '{reviewer_id}' is too short (min 2 chars).")

        # 2. Validate Documented Reason
        if not reason or not str(reason).strip():
            rejection_reasons.append("Documented review rationale (reason) is mandatory.")
        elif len(str(reason).strip()) < 5:
            rejection_reasons.append(f"Review reason '{reason}' is too short (min 5 chars).")

        # 3. Validate Timezone-Aware Timestamp
        if not reviewed_at:
            rejection_reasons.append("Review timestamp (reviewed_at) is required.")
        else:
            try:
                dt = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
                if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                    rejection_reasons.append(
                        f"Review timestamp '{reviewed_at}' must be timezone-aware ISO 8601 string."
                    )
            except Exception as e:
                rejection_reasons.append(f"Invalid timestamp format '{reviewed_at}': {e}")

        # 4. Check Source Fingerprints & Freshness
        s_fid = relationship.get("source_file_id", "")
        t_fid = relationship.get("target_file_id", "")
        src_rec = get_source_by_file_id(self.conn, s_fid)
        tgt_rec = get_source_by_file_id(self.conn, t_fid)

        if not src_rec:
            rejection_reasons.append(f"Primary source '{s_fid}' does not exist in SQLite inventory.")
        if not tgt_rec:
            rejection_reasons.append(f"Target source '{t_fid}' does not exist in SQLite inventory.")

        current_s_sha = src_rec.get("content_sha256") if src_rec else ""
        current_t_sha = tgt_rec.get("content_sha256") if tgt_rec else ""

        rel_s_sha = relationship.get("source_content_sha256") or ""
        rel_t_sha = relationship.get("target_content_sha256") or ""

        is_fresh = True
        if rel_s_sha and current_s_sha and rel_s_sha != current_s_sha:
            is_fresh = False
            rejection_reasons.append(
                f"Source content hash changed since relationship creation: {rel_s_sha[:8]} != {current_s_sha[:8]}."
            )
        if rel_t_sha and current_t_sha and rel_t_sha != current_t_sha:
            is_fresh = False
            rejection_reasons.append(
                f"Target content hash changed since relationship creation: {rel_t_sha[:8]} != {current_t_sha[:8]}."
            )

        # Check on-disk content freshness if file is available
        if src_rec and src_rec.get("relative_path"):
            disk_p = self.repo_root / src_rec["relative_path"]
            if disk_p.is_file():
                try:
                    on_disk_sha = hashlib.sha256(disk_p.read_bytes()).hexdigest()
                    if on_disk_sha != current_s_sha:
                        is_fresh = False
                        rejection_reasons.append(
                            f"Physical source '{src_rec['relative_path']}' modified on disk ({on_disk_sha[:8]} != {current_s_sha[:8]})."
                        )
                except OSError:
                    pass

        # -------------------------------------------------------------
        # Decision-Specific Evaluation
        # -------------------------------------------------------------
        if decision == "defer":
            # Defer preserves existing status without false mutation
            final_status = prev_status
            can_proceed = len(rejection_reasons) == 0
            return PolicyEvaluationResult(
                can_proceed=can_proceed,
                decision=decision,
                previous_status=prev_status,
                final_status=final_status,
                rejection_reasons=rejection_reasons,
                validation_flags=validation_flags,
                source_fingerprint=current_s_sha or rel_s_sha,
                target_fingerprint=current_t_sha or rel_t_sha,
                is_fresh=is_fresh,
                expert_verified=expert_verified,
            )

        if decision == "reject":
            final_status = "rejected"
            can_proceed = len(rejection_reasons) == 0
            return PolicyEvaluationResult(
                can_proceed=can_proceed,
                decision=decision,
                previous_status=prev_status,
                final_status=final_status,
                rejection_reasons=rejection_reasons,
                validation_flags=validation_flags,
                source_fingerprint=current_s_sha or rel_s_sha,
                target_fingerprint=current_t_sha or rel_t_sha,
                is_fresh=is_fresh,
                expert_verified=expert_verified,
            )

        if decision == "approve":
            final_status = "confirmed"

            # Rule C: Reject approval if source hashes changed
            if not is_fresh:
                rejection_reasons.append(
                    "Stale relationship: Cannot approve because underlying source content has changed since snapshot."
                )

            # Rule B: Rejected relationship or critical conflicts cannot be bypassed
            conflicts = list_relationship_conflicts(
                self.conn, relationship_id=relationship.get("relationship_id")
            )
            critical_conflicts = [c for c in conflicts if c.get("severity") == "critical"]
            if critical_conflicts:
                for cc in critical_conflicts:
                    rejection_reasons.append(
                        f"Critical conflict '{cc.get('conflict_type')}': {cc.get('description')} "
                        "Critical conflicts strictly prevent promotion to confirmed."
                    )

            # Metadata alignment checks
            forbidden_mismatch_flags = {
                "VOLUME_MISMATCH",
                "SKILL_MISMATCH",
                "TEST_NUMBER_MISMATCH",
                "PASSAGE_MISMATCH",
            }
            active_mismatches = [f for f in validation_flags if f in forbidden_mismatch_flags]
            if active_mismatches:
                rejection_reasons.append(
                    f"Metadata contradictions detected: {active_mismatches}. "
                    "Relationships with volume, skill, test, or passage mismatch cannot be confirmed."
                )

            # Rule D & A: Independent supporting evidence check
            has_independent_evidence = False

            # Case 1: Inherent verified flags
            if "CONTENT_TITLE_MATCH" in validation_flags:
                has_independent_evidence = True
            elif "ANSWERS_ALIGNED" in validation_flags and "CIRCULAR_ANSWER_EVIDENCE_REJECTED" not in validation_flags:
                has_independent_evidence = True
            elif "AUDIO_TRACK_VERIFIED" in validation_flags and "AUDIO_TRACK_MISMATCH" not in validation_flags:
                has_independent_evidence = True
            elif "TRANSCRIPT_SECTION_VERIFIED" in validation_flags:
                has_independent_evidence = True
            elif "TRANSCRIPT_AUDIO_ALIGNED" in validation_flags:
                has_independent_evidence = True

            # Case 2: Reviewer-provided external evidence
            ref_ev_id = evidence_source_id
            if not ref_ev_id and evidence_references:
                ref_ev_id = evidence_references.get("source_id") or evidence_references.get("evidence_source_id")

            if ref_ev_id:
                ev_prov = (
                    evidence_references.get("provenance")
                    if isinstance(evidence_references, dict)
                    else None
                )
                val_res = self.source_validator.validate_reference(
                    reference_source_id=ref_ev_id,
                    expected_collection=relationship.get("collection") or "",
                    expected_test_number=relationship.get("test_number"),
                    candidate_target_file_id=t_fid,
                    evidence_provenance=ev_prov,
                )
                if val_res.is_valid:
                    has_independent_evidence = True
                    validation_flags.append("REVIEWER_EVIDENCE_VERIFIED")
                else:
                    rejection_reasons.extend(
                        [f"Reviewer evidence invalid: {r}" for r in val_res.rejection_reasons]
                    )

            if not has_independent_evidence:
                rejection_reasons.append(
                    "Missing independent supporting evidence: Relationship is supported only by structural "
                    "numbering ranges or unverified metadata. In accordance with Rule D, it must remain "
                    "candidate or review_required until independent evidence is established."
                )

            if len(rejection_reasons) == 0:
                can_proceed = True
                validation_flags.append("HUMAN_REVIEW_APPROVED")
            else:
                can_proceed = False

            return PolicyEvaluationResult(
                can_proceed=can_proceed,
                decision=decision,
                previous_status=prev_status,
                final_status=final_status if can_proceed else prev_status,
                rejection_reasons=rejection_reasons,
                validation_flags=validation_flags,
                source_fingerprint=current_s_sha or rel_s_sha,
                target_fingerprint=current_t_sha or rel_t_sha,
                is_fresh=is_fresh,
                expert_verified=expert_verified,
            )

        raise ValueError(f"Unsupported review decision '{decision}'.")

    def check_relationship_freshness(self, relationship: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Verifies if a relationship's sources remain fresh and uncorrupted on disk and in DB."""
        s_fid = relationship.get("source_file_id", "")
        t_fid = relationship.get("target_file_id", "")
        src = get_source_by_file_id(self.conn, s_fid)
        tgt = get_source_by_file_id(self.conn, t_fid)

        if not src or not tgt:
            return False, "Underlying source file(s) missing from inventory"

        cur_s = src.get("content_sha256") or ""
        cur_t = tgt.get("content_sha256") or ""
        rel_s = relationship.get("source_content_sha256") or ""
        rel_t = relationship.get("target_content_sha256") or ""

        if rel_s and cur_s and rel_s != cur_s:
            return False, f"Source SHA changed: {rel_s[:8]} -> {cur_s[:8]}"
        if rel_t and cur_t and rel_t != cur_t:
            return False, f"Target SHA changed: {rel_t[:8]} -> {cur_t[:8]}"

        # On-disk check
        for rec in (src, tgt):
            if rec.get("relative_path"):
                p = self.repo_root / rec["relative_path"]
                if p.is_file():
                    try:
                        actual = hashlib.sha256(p.read_bytes()).hexdigest()
                        if actual != rec.get("content_sha256"):
                            return False, f"On-disk file '{rec['relative_path']}' modified"
                    except OSError:
                        pass

        return True, None
