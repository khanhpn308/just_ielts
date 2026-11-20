"""Deterministic layered matching engine for IELTS Data Harness V0.3-A."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, List, Optional, Set, Tuple

from harness.matching.metadata import SourceDocumentMetadata
from harness.models.relationship import (
    ConflictSeverity,
    ConflictType,
    RelationshipConflict,
    RelationshipStatus,
    RelationshipType,
    SCHEMA_VERSION_RELATIONSHIP,
    SourceRelationship,
    compute_relationship_id,
)
from harness.normalizers.answer_reconciler import normalize_answer_value

MATCHER_VERSION = "0.3.0-a"


def compute_conflict_id(source_file_id: str, target_file_id: str, conflict_type: str, detail_key: str) -> str:
    """Computes stable deterministic conflict ID."""
    raw = f"{source_file_id}:{target_file_id}:{conflict_type}:{detail_key}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"CONF-{digest}"


class MatchingEngine:
    """Multi-source evidence-based matching and relationship resolver."""

    def __init__(self, matcher_version: str = MATCHER_VERSION):
        self.matcher_version = matcher_version

    def evaluate_relationship(
        self,
        source_meta: SourceDocumentMetadata,
        target_meta: SourceDocumentMetadata,
        relationship_type: RelationshipType,
        test_number: Optional[int] = None,
        passage_or_section: Optional[int] = None,
        known_ground_truth_answers: Optional[Dict[int, str]] = None,
    ) -> Tuple[SourceRelationship, List[RelationshipConflict]]:
        """Evaluates relationship across 4 deterministic layers."""
        conflicts: List[RelationshipConflict] = []
        validation_flags: List[str] = []
        identity_evidence: Dict[str, Any] = {}
        now_iso = datetime.now(timezone.utc).isoformat()

        # Target Volume & Collection
        eff_volume = source_meta.volume or target_meta.volume or "UNKNOWN_VOL"
        eff_collection = source_meta.collection or target_meta.collection or "UNKNOWN_COLL"

        # -------------------------------------------------------------
        # LAYER 1: METADATA COMPATIBILITY
        # -------------------------------------------------------------
        # 1.1 Volume Verification
        if source_meta.volume and target_meta.volume:
            if source_meta.volume != target_meta.volume:
                conf = RelationshipConflict(
                    conflict_id=compute_conflict_id(
                        source_meta.file_id, target_meta.file_id, "CROSS_VOLUME_MISMATCH", f"{source_meta.volume}!={target_meta.volume}"
                    ),
                    source_file_id=source_meta.file_id,
                    target_file_id=target_meta.file_id,
                    conflict_type="CROSS_VOLUME_MISMATCH",
                    severity="critical",
                    description=(
                        f"Cross-volume mismatch: source belongs to '{source_meta.volume}' "
                        f"while target belongs to '{target_meta.volume}'."
                    ),
                    evidence={
                        "source_volume": source_meta.volume,
                        "target_volume": target_meta.volume,
                        "source_path": source_meta.relative_path,
                        "target_path": target_meta.relative_path,
                    },
                    detected_at=now_iso,
                )
                conflicts.append(conf)
                validation_flags.append("VOLUME_MISMATCH")
            else:
                validation_flags.append("VOLUME_MATCH")
                identity_evidence["volume"] = source_meta.volume
        elif not source_meta.volume and not target_meta.volume:
            if source_meta.collection == target_meta.collection:
                validation_flags.append("COLLECTION_MATCH")
                identity_evidence["collection"] = source_meta.collection
            else:
                conf = RelationshipConflict(
                    conflict_id=compute_conflict_id(
                        source_meta.file_id, target_meta.file_id, "MISSING_METADATA", "collection_mismatch"
                    ),
                    source_file_id=source_meta.file_id,
                    target_file_id=target_meta.file_id,
                    conflict_type="MISSING_METADATA",
                    severity="high",
                    description=f"Collection mismatch: '{source_meta.collection}' vs '{target_meta.collection}'.",
                    evidence={"source_collection": source_meta.collection, "target_collection": target_meta.collection},
                    detected_at=now_iso,
                )
                conflicts.append(conf)
                validation_flags.append("COLLECTION_MISMATCH")
        else:
            # One has volume, other does not
            conf = RelationshipConflict(
                conflict_id=compute_conflict_id(
                    source_meta.file_id, target_meta.file_id, "MISSING_METADATA", "partial_volume"
                ),
                source_file_id=source_meta.file_id,
                target_file_id=target_meta.file_id,
                conflict_type="MISSING_METADATA",
                severity="medium",
                description="One source has volume metadata while the other does not.",
                evidence={"source_volume": source_meta.volume, "target_volume": target_meta.volume},
                detected_at=now_iso,
            )
            conflicts.append(conf)
            validation_flags.append("VOLUME_PARTIAL_MISSING")

        # 1.2 Skill Compatibility
        skill_resolved = self._verify_skill_compatibility(
            source_meta, target_meta, relationship_type, conflicts, validation_flags, now_iso
        )

        # 1.3 Test Number Alignment
        eff_test_number = self._verify_test_number_alignment(
            source_meta, target_meta, test_number, conflicts, validation_flags, identity_evidence, now_iso
        )

        # 1.4 Passage or Section Alignment
        eff_passage_sec = self._verify_passage_alignment(
            source_meta, target_meta, eff_test_number, passage_or_section, conflicts, validation_flags, identity_evidence, now_iso
        )

        # -------------------------------------------------------------
        # LAYER 2: STRUCTURAL CHECKS
        # -------------------------------------------------------------
        self._verify_structural_alignment(
            source_meta, target_meta, relationship_type, eff_test_number, eff_passage_sec,
            validation_flags, identity_evidence
        )

        # -------------------------------------------------------------
        # LAYER 3: CONTENT ALIGNMENT & CONFLICTING KEYS DETECTION
        # -------------------------------------------------------------
        self._verify_content_and_answers(
            source_meta, target_meta, eff_test_number, eff_passage_sec,
            known_ground_truth_answers, conflicts, validation_flags, identity_evidence, now_iso
        )

        # -------------------------------------------------------------
        # LAYER 4: CONFLICT AUDIT & STATUS ASSIGNMENT
        # -------------------------------------------------------------
        has_critical = any(c.severity in {"critical", "high"} for c in conflicts)
        has_medium = any(c.severity == "medium" for c in conflicts)

        rel_id = compute_relationship_id(
            source_file_id=source_meta.file_id,
            target_file_id=target_meta.file_id,
            relationship_type=relationship_type,
            volume=eff_volume,
            test_number=eff_test_number,
            passage_or_section=eff_passage_sec,
        )

        # Associate conflicts with relationship_id
        for c in conflicts:
            c.relationship_id = rel_id

        # Epistemic Status Determination
        if has_critical:
            status: RelationshipStatus = "rejected"
            confidence = 0.0
        elif has_medium or ("VOLUME_PARTIAL_MISSING" in validation_flags) or ("AMBIGUOUS_TEST_IDENTITY" in validation_flags):
            status = "review_required"
            confidence = 0.5
        else:
            # Check confirmation gate criteria:
            # 1. Exact volume match (or matching collection)
            # 2. Skill match
            # 3. Verified test number
            # 4. Zero critical or medium conflicts
            # 5. Positive structural or content alignment
            is_volume_ok = ("VOLUME_MATCH" in validation_flags) or ("COLLECTION_MATCH" in validation_flags)
            is_skill_ok = "SKILL_MATCH" in validation_flags
            is_test_ok = "TEST_NUMBER_MATCH" in validation_flags or "TEST_NUMBER_CONTAINED" in validation_flags
            is_content_or_struct_ok = (
                "ANSWERS_ALIGNED" in validation_flags
                or "CONTENT_TITLE_MATCH" in validation_flags
                or "TRANSCRIPT_AUDIO_ALIGNED" in validation_flags
                or "QUESTION_RANGE_ALIGNED" in validation_flags
            )

            if is_volume_ok and is_skill_ok and is_test_ok and is_content_or_struct_ok:
                status = "confirmed"
                confidence = 1.0
                validation_flags.append("GATE_CONFIRMED_PASSED")
            elif is_volume_ok and is_skill_ok:
                # Plausible candidate but needs further verification or human review
                status = "candidate"
                confidence = 0.7
            else:
                status = "review_required"
                confidence = 0.4

        provenance_dict = {
            "matcher_name": "SourceMatchingEngine",
            "matcher_version": self.matcher_version,
            "evaluated_at": now_iso,
            "source_file_id": source_meta.file_id,
            "source_legacy_id": source_meta.legacy_id,
            "target_file_id": target_meta.file_id,
            "target_legacy_id": target_meta.legacy_id,
            "source_path": source_meta.relative_path,
            "target_path": target_meta.relative_path,
            "conflicts_detected": len(conflicts),
            "layers_passed": [
                layer for layer in ["metadata", "structural", "content"]
                if not any(c.conflict_type.startswith(layer.upper()) for c in conflicts)
            ],
        }

        relationship = SourceRelationship(
            relationship_id=rel_id,
            source_file_id=source_meta.file_id,
            target_file_id=target_meta.file_id,
            relationship_type=relationship_type,
            collection=eff_collection,
            volume=eff_volume,
            test_number=eff_test_number,
            passage_or_section=eff_passage_sec,
            skill=skill_resolved or "reading",
            identity_evidence=identity_evidence,
            validation_flags=validation_flags,
            match_confidence=confidence,
            relationship_status=status,
            provenance=provenance_dict,
            schema_version=SCHEMA_VERSION_RELATIONSHIP,
        )

        return relationship, conflicts

    def _verify_skill_compatibility(
        self,
        source_meta: SourceDocumentMetadata,
        target_meta: SourceDocumentMetadata,
        relationship_type: RelationshipType,
        conflicts: List[RelationshipConflict],
        validation_flags: List[str],
        now_iso: str,
    ) -> Optional[str]:
        """Validates skill alignment against relationship type expectations."""
        expected_skill = {
            "question_to_answer_key": None,  # reading or listening
            "question_to_explanation": None,  # reading or listening
            "listening_to_audio": "listening",
            "listening_to_transcript": "listening",
            "writing_to_sample_answer": "writing",
        }.get(relationship_type)

        s_skill = source_meta.skill
        t_skill = target_meta.skill

        if expected_skill:
            if s_skill and s_skill != expected_skill:
                conf = RelationshipConflict(
                    conflict_id=compute_conflict_id(
                        source_meta.file_id, target_meta.file_id, "SKILL_MISMATCH", f"source_{s_skill}!={expected_skill}"
                    ),
                    source_file_id=source_meta.file_id,
                    target_file_id=target_meta.file_id,
                    conflict_type="SKILL_MISMATCH",
                    severity="critical",
                    description=f"Source skill '{s_skill}' does not match required relationship skill '{expected_skill}'.",
                    evidence={"source_skill": s_skill, "expected_skill": expected_skill},
                    detected_at=now_iso,
                )
                conflicts.append(conf)
                validation_flags.append("SKILL_MISMATCH")
                return None

            if t_skill and t_skill != expected_skill:
                conf = RelationshipConflict(
                    conflict_id=compute_conflict_id(
                        source_meta.file_id, target_meta.file_id, "SKILL_MISMATCH", f"target_{t_skill}!={expected_skill}"
                    ),
                    source_file_id=source_meta.file_id,
                    target_file_id=target_meta.file_id,
                    conflict_type="SKILL_MISMATCH",
                    severity="critical",
                    description=f"Target skill '{t_skill}' does not match required relationship skill '{expected_skill}'.",
                    evidence={"target_skill": t_skill, "expected_skill": expected_skill},
                    detected_at=now_iso,
                )
                conflicts.append(conf)
                validation_flags.append("SKILL_MISMATCH")
                return None

            validation_flags.append("SKILL_MATCH")
            return expected_skill

        # General skill comparison for reading/listening
        if s_skill and t_skill and s_skill != t_skill:
            conf = RelationshipConflict(
                conflict_id=compute_conflict_id(
                    source_meta.file_id, target_meta.file_id, "SKILL_MISMATCH", f"{s_skill}!={t_skill}"
                ),
                source_file_id=source_meta.file_id,
                target_file_id=target_meta.file_id,
                conflict_type="SKILL_MISMATCH",
                severity="critical",
                description=f"Source skill '{s_skill}' directly contradicts target skill '{t_skill}'.",
                evidence={"source_skill": s_skill, "target_skill": t_skill},
                detected_at=now_iso,
            )
            conflicts.append(conf)
            validation_flags.append("SKILL_MISMATCH")
            return None

        resolved = s_skill or t_skill or "reading"
        validation_flags.append("SKILL_MATCH")
        return resolved

    def _verify_test_number_alignment(
        self,
        source_meta: SourceDocumentMetadata,
        target_meta: SourceDocumentMetadata,
        requested_test: Optional[int],
        conflicts: List[RelationshipConflict],
        validation_flags: List[str],
        identity_evidence: Dict[str, Any],
        now_iso: str,
    ) -> Optional[int]:
        """Aligns and verifies test numbers across source and target."""
        s_tests = set(source_meta.test_numbers)
        t_tests = set(target_meta.test_numbers)

        if requested_test is not None:
            if s_tests and requested_test not in s_tests:
                conf = RelationshipConflict(
                    conflict_id=compute_conflict_id(
                        source_meta.file_id, target_meta.file_id, "TEST_NUMBER_MISMATCH", f"req_{requested_test}_not_in_source"
                    ),
                    source_file_id=source_meta.file_id,
                    target_file_id=target_meta.file_id,
                    conflict_type="TEST_NUMBER_MISMATCH",
                    severity="critical",
                    description=f"Requested test number {requested_test} is not covered by source tests {sorted(s_tests)}.",
                    evidence={"requested_test": requested_test, "source_tests": sorted(s_tests)},
                    detected_at=now_iso,
                )
                conflicts.append(conf)
                validation_flags.append("TEST_NUMBER_MISMATCH")
                return requested_test

            if t_tests and requested_test not in t_tests:
                conf = RelationshipConflict(
                    conflict_id=compute_conflict_id(
                        source_meta.file_id, target_meta.file_id, "TEST_NUMBER_MISMATCH", f"req_{requested_test}_not_in_target"
                    ),
                    source_file_id=source_meta.file_id,
                    target_file_id=target_meta.file_id,
                    conflict_type="TEST_NUMBER_MISMATCH",
                    severity="critical",
                    description=f"Requested test number {requested_test} is not covered by target tests {sorted(t_tests)}.",
                    evidence={"requested_test": requested_test, "target_tests": sorted(t_tests)},
                    detected_at=now_iso,
                )
                conflicts.append(conf)
                validation_flags.append("TEST_NUMBER_MISMATCH")
                return requested_test

            validation_flags.append("TEST_NUMBER_MATCH")
            identity_evidence["test_number"] = requested_test
            return requested_test

        # Infer from intersection
        common_tests = s_tests.intersection(t_tests) if (s_tests and t_tests) else set()
        if s_tests and t_tests and not common_tests:
            conf = RelationshipConflict(
                conflict_id=compute_conflict_id(
                    source_meta.file_id, target_meta.file_id, "TEST_NUMBER_MISMATCH", "disjoint_test_sets"
                ),
                source_file_id=source_meta.file_id,
                target_file_id=target_meta.file_id,
                conflict_type="TEST_NUMBER_MISMATCH",
                severity="critical",
                description=(
                    f"Disjoint test sets: source covers {sorted(s_tests)} while target covers {sorted(t_tests)}."
                ),
                evidence={"source_tests": sorted(s_tests), "target_tests": sorted(t_tests)},
                detected_at=now_iso,
            )
            conflicts.append(conf)
            validation_flags.append("TEST_NUMBER_MISMATCH")
            return None

        if len(common_tests) == 1:
            t_num = next(iter(common_tests))
            validation_flags.append("TEST_NUMBER_MATCH")
            identity_evidence["test_number"] = t_num
            return t_num

        if len(common_tests) > 1:
            # Multi-test coverage (e.g. Vol 6 tests 5 and 6)
            min_test = min(common_tests)
            validation_flags.append("TEST_NUMBER_CONTAINED")
            identity_evidence["common_tests"] = sorted(common_tests)
            return min_test

        # One side has test number, other does not
        if s_tests:
            single = min(s_tests) if len(s_tests) == 1 else None
            validation_flags.append("TEST_NUMBER_PARTIAL")
            return single
        if t_tests:
            single = min(t_tests) if len(t_tests) == 1 else None
            validation_flags.append("TEST_NUMBER_PARTIAL")
            return single

        validation_flags.append("TEST_NUMBER_UNSPECIFIED")
        return None

    def _verify_passage_alignment(
        self,
        source_meta: SourceDocumentMetadata,
        target_meta: SourceDocumentMetadata,
        test_number: Optional[int],
        requested_passage: Optional[int],
        conflicts: List[RelationshipConflict],
        validation_flags: List[str],
        identity_evidence: Dict[str, Any],
        now_iso: str,
    ) -> Optional[int]:
        """Aligns passage/section numbers between source and target."""
        if requested_passage is not None:
            identity_evidence["passage_or_section"] = requested_passage
            validation_flags.append("PASSAGE_REQUESTED")
            return requested_passage

        if test_number is not None:
            s_passages = set(source_meta.passages_or_sections.get(test_number, []))
            t_passages = set(target_meta.passages_or_sections.get(test_number, []))

            if s_passages and t_passages:
                common = s_passages.intersection(t_passages)
                if not common:
                    conf = RelationshipConflict(
                        conflict_id=compute_conflict_id(
                            source_meta.file_id, target_meta.file_id, "PASSAGE_MISMATCH", f"disjoint_passages_t{test_number}"
                        ),
                        source_file_id=source_meta.file_id,
                        target_file_id=target_meta.file_id,
                        conflict_type="PASSAGE_MISMATCH",
                        severity="high",
                        description=f"Disjoint passage numbers for Test {test_number}: {sorted(s_passages)} vs {sorted(t_passages)}.",
                        evidence={"source_passages": sorted(s_passages), "target_passages": sorted(t_passages)},
                        detected_at=now_iso,
                    )
                    conflicts.append(conf)
                    validation_flags.append("PASSAGE_MISMATCH")
                    return None
                p_num = min(common)
                identity_evidence["passage_or_section"] = p_num
                validation_flags.append("PASSAGE_MATCH")
                return p_num

            if s_passages and len(s_passages) == 1:
                return min(s_passages)
            if t_passages and len(t_passages) == 1:
                return min(t_passages)

        return None

    def _verify_structural_alignment(
        self,
        source_meta: SourceDocumentMetadata,
        target_meta: SourceDocumentMetadata,
        relationship_type: RelationshipType,
        test_number: Optional[int],
        passage_or_section: Optional[int],
        validation_flags: List[str],
        identity_evidence: Dict[str, Any],
    ) -> None:
        """Checks question ranges and section boundary compatibility."""
        if relationship_type in {"listening_to_audio", "listening_to_transcript"}:
            # Audio / Transcript structural check: section track alignment
            if passage_or_section is not None:
                identity_evidence["section_number"] = passage_or_section
                validation_flags.append("TRANSCRIPT_AUDIO_ALIGNED")
            return

        # Reading passage structural checks: question numbering
        if passage_or_section is not None:
            expected_range = {
                1: (1, 14),
                2: (14, 27),
                3: (27, 40),
            }.get(passage_or_section, (1, 40))

            identity_evidence["expected_question_range"] = expected_range

            if test_number and test_number in target_meta.answer_keys:
                target_q_nums = set(target_meta.answer_keys[test_number].keys())
                in_range_qs = [q for q in target_q_nums if expected_range[0] <= q <= expected_range[1]]
                if in_range_qs:
                    validation_flags.append("QUESTION_RANGE_ALIGNED")
                    identity_evidence["target_in_range_questions"] = sorted(in_range_qs)

    def _verify_content_and_answers(
        self,
        source_meta: SourceDocumentMetadata,
        target_meta: SourceDocumentMetadata,
        test_number: Optional[int],
        passage_or_section: Optional[int],
        ground_truth_answers: Optional[Dict[int, str]],
        conflicts: List[RelationshipConflict],
        validation_flags: List[str],
        identity_evidence: Dict[str, Any],
        now_iso: str,
    ) -> None:
        """Audits content titles and compares answers against known keys to detect contradictions."""
        # 1. Content Title / Passage Name Check
        if test_number and passage_or_section:
            s_title = source_meta.passage_titles.get(test_number, {}).get(passage_or_section)
            t_title = target_meta.passage_titles.get(test_number, {}).get(passage_or_section)
            if s_title and t_title:
                clean_s = s_title.lower().strip()
                clean_t = t_title.lower().strip()
                if clean_s in clean_t or clean_t in clean_s:
                    validation_flags.append("CONTENT_TITLE_MATCH")
                    identity_evidence["passage_title"] = s_title

        # 2. Answer Key Alignment & Contradiction Auditing
        # Known keys can come from:
        # a) ground_truth_answers passed directly
        # b) source_meta.answer_keys if present
        s_keys: Dict[int, str] = {}
        if ground_truth_answers:
            s_keys.update(ground_truth_answers)
        elif test_number and test_number in source_meta.answer_keys:
            s_keys.update(source_meta.answer_keys[test_number])

        t_keys: Dict[int, str] = {}
        if test_number and test_number in target_meta.answer_keys:
            t_keys.update(target_meta.answer_keys[test_number])

        if s_keys and t_keys:
            overlapping_qs = set(s_keys.keys()).intersection(set(t_keys.keys()))
            if overlapping_qs:
                matching_qs = []
                contradictory_qs = []
                details = {}

                for q in sorted(overlapping_qs):
                    s_val, _, s_flags = normalize_answer_value(s_keys[q])
                    t_val, _, t_flags = normalize_answer_value(t_keys[q])

                    if s_val is not None and t_val is not None:
                        if s_val == t_val:
                            matching_qs.append(q)
                        else:
                            contradictory_qs.append(q)
                            details[f"Q{q}"] = {
                                "source_answer": s_val,
                                "target_answer": t_val,
                            }

                identity_evidence["answer_audit"] = {
                    "overlapping_count": len(overlapping_qs),
                    "matching_count": len(matching_qs),
                    "contradictory_count": len(contradictory_qs),
                }

                if contradictory_qs:
                    conf = RelationshipConflict(
                        conflict_id=compute_conflict_id(
                            source_meta.file_id, target_meta.file_id, "CONFLICTING_ANSWER_KEYS", f"t{test_number}_q_{contradictory_qs[0]}"
                        ),
                        source_file_id=source_meta.file_id,
                        target_file_id=target_meta.file_id,
                        conflict_type="CONFLICTING_ANSWER_KEYS",
                        severity="critical",
                        description=(
                            f"Target answer key directly contradicts known answers on {len(contradictory_qs)} question(s): "
                            f"{[f'Q{q}' for q in contradictory_qs[:5]]}."
                        ),
                        evidence={
                            "test_number": test_number,
                            "contradictory_questions": contradictory_qs,
                            "sample_mismatches": details,
                        },
                        detected_at=now_iso,
                    )
                    conflicts.append(conf)
                    validation_flags.append("CONFLICTING_ANSWER_KEYS")
                elif matching_qs:
                    validation_flags.append("ANSWERS_ALIGNED")
                    identity_evidence["matching_answers"] = matching_qs
