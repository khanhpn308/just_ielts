"""Service coordinator for human review workflows in IELTS Data Harness V0.3-B."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from harness.config import DB_PATH, REPO_ROOT
from harness.db import (
    apply_relationship_review_atomic,
    get_db_connection,
    get_source_by_file_id,
    get_source_relationship,
    list_relationship_conflicts,
    list_relationship_reviews,
    list_source_relationships,
)
from harness.models.relationship import (
    RelationshipReview,
    RelationshipStatus,
    ReviewDecision,
    SourceRelationship,
    compute_review_id,
)
from harness.review.policy import (
    PolicyEvaluationResult,
    ReviewPolicyValidator,
    ReviewPolicyViolation,
    StaleRelationshipError,
)


class RelationshipReviewService:
    """Coordinates listing, inspecting, deciding, and auditing human source relationship reviews."""

    def __init__(self, db_path: Optional[Path] = None, repo_root: Optional[Path] = None):
        from harness import config
        self.db_path = db_path or config.DB_PATH
        self.repo_root = repo_root or config.REPO_ROOT

    def _get_connection(self) -> sqlite3.Connection:
        return get_db_connection(self.db_path)

    def list_relationships(
        self,
        status: str = "unresolved",
        volume: Optional[str] = None,
        relationship_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Lists relationships for review based on epistemic status and optional filters."""
        conn = self._get_connection()
        clauses = []
        params: List[Any] = []

        if status == "unresolved":
            clauses.append("relationship_status IN ('candidate', 'review_required')")
        elif status and status != "all":
            clauses.append("relationship_status = ?")
            params.append(status)

        if volume:
            clauses.append("volume = ?")
            params.append(volume)

        if relationship_type:
            clauses.append("relationship_type = ?")
            params.append(relationship_type)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_sql = f"LIMIT {int(limit)}" if limit else ""
        sql = f"SELECT * FROM source_relationships {where_sql} ORDER BY created_at ASC {limit_sql}"

        cur = conn.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        results = []
        for r in rows:
            for k in ("identity_evidence", "validation_flags", "provenance"):
                val = r.get(k)
                if isinstance(val, str):
                    try:
                        import json
                        r[k] = json.loads(val)
                    except Exception:
                        pass
            results.append(r)
        return results

    def get_relationship_details(self, relationship_id: str) -> Dict[str, Any]:
        """Fetches detailed relationship view including provenance, conflicts, policy assessment, and history."""
        conn = self._get_connection()
        rel = get_source_relationship(conn, relationship_id)
        if not rel:
            conn.close()
            raise ValueError(f"Relationship '{relationship_id}' not found in registry.")

        src = get_source_by_file_id(conn, rel["source_file_id"])
        tgt = get_source_by_file_id(conn, rel["target_file_id"])
        conflicts = list_relationship_conflicts(conn, relationship_id=relationship_id)
        history = list_relationship_reviews(conn, relationship_id=relationship_id)

        policy = ReviewPolicyValidator(conn, repo_root=self.repo_root)
        is_fresh, freshness_reason = policy.check_relationship_freshness(rel)

        # Preview approval eligibility
        now_sample = datetime.now(timezone.utc).isoformat()
        approval_preview = policy.evaluate_decision(
            relationship=rel,
            decision="approve",
            reviewer_id="PREVIEW-AUDIT",
            reason="Preview policy assessment",
            reviewed_at=now_sample,
        )

        conn.close()
        return {
            "relationship": rel,
            "source": src,
            "target": tgt,
            "conflicts": conflicts,
            "history": history,
            "is_fresh": is_fresh,
            "freshness_reason": freshness_reason,
            "approval_preview": {
                "can_approve": approval_preview.can_proceed,
                "rejection_reasons": approval_preview.rejection_reasons,
                "resulting_flags": approval_preview.validation_flags,
            },
        }

    def decide(
        self,
        relationship_id: str,
        decision: ReviewDecision,
        reviewer_id: str,
        reason: str,
        reviewed_at: Optional[str] = None,
        evidence_references: Optional[Dict[str, Any]] = None,
        evidence_source_id: Optional[str] = None,
        dry_run: bool = False,
        expert_verified: bool = False,
    ) -> Dict[str, Any]:
        """Evaluates policy and executes an atomic review decision."""
        conn = self._get_connection()
        rel = get_source_relationship(conn, relationship_id)
        if not rel:
            conn.close()
            raise ValueError(f"Relationship '{relationship_id}' not found in registry.")

        now_iso = reviewed_at or datetime.now(timezone.utc).isoformat()

        # Policy validation
        validator = ReviewPolicyValidator(conn, repo_root=self.repo_root)
        policy_result: PolicyEvaluationResult = validator.evaluate_decision(
            relationship=rel,
            decision=decision,
            reviewer_id=reviewer_id,
            reason=reason,
            reviewed_at=now_iso,
            evidence_references=evidence_references,
            evidence_source_id=evidence_source_id,
            expert_verified=expert_verified,
        )

        if not policy_result.can_proceed:
            conn.close()
            reasons_str = "\n  - " + "\n  - ".join(policy_result.rejection_reasons)
            raise ReviewPolicyViolation(
                f"Review decision '{decision}' rejected by policy:{reasons_str}"
            )

        review_id = compute_review_id(
            relationship_id=relationship_id,
            reviewer_id=reviewer_id,
            decision=decision,
            reviewed_at=now_iso,
        )

        ev_refs = dict(evidence_references or {})
        if evidence_source_id and "source_id" not in ev_refs:
            ev_refs["source_id"] = evidence_source_id

        requested_status = "confirmed" if decision == "approve" else ("rejected" if decision == "reject" else "deferred")

        review_event = RelationshipReview(
            review_id=review_id,
            relationship_id=relationship_id,
            reviewer_id=reviewer_id,
            reviewer=reviewer_id,
            previous_status=policy_result.previous_status,
            requested_status=requested_status,
            final_status=policy_result.final_status,
            new_status=policy_result.final_status,
            decision=decision,
            reason=reason,
            reviewed_at=now_iso,
            created_at=now_iso,
            source_fingerprint=policy_result.source_fingerprint,
            target_fingerprint=policy_result.target_fingerprint,
            evidence_references=ev_refs,
            review_policy_version=policy_result.policy_version,
            expert_verified=False,
        )

        if dry_run:
            conn.close()
            return {
                "dry_run": True,
                "status": "success",
                "relationship_id": relationship_id,
                "previous_status": policy_result.previous_status,
                "final_status": policy_result.final_status,
                "decision": decision,
                "review_event": review_event.model_dump(),
                "message": f"[DRY-RUN] Review decision '{decision}' evaluated successfully. No persistent changes made.",
            }

        # Atomic commit
        apply_relationship_review_atomic(
            conn=conn,
            review_data=review_event.model_dump(),
            expected_status=policy_result.previous_status,
            expected_updated_at=rel.get("updated_at"),
            new_validation_flags=policy_result.validation_flags,
        )
        conn.close()

        return {
            "dry_run": False,
            "status": "success",
            "relationship_id": relationship_id,
            "previous_status": policy_result.previous_status,
            "final_status": policy_result.final_status,
            "decision": decision,
            "review_event": review_event.model_dump(),
            "message": f"Review decision '{decision}' successfully committed for {relationship_id}.",
        }

    def get_history(self, relationship_id: str) -> List[Dict[str, Any]]:
        """Returns immutable chronological audit history for a relationship."""
        conn = self._get_connection()
        history = list_relationship_reviews(conn, relationship_id=relationship_id)
        conn.close()
        return history
