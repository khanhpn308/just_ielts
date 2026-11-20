"""Tutor retrieval engine for IELTS Data Harness V0.2.

Provides deterministic, schema-compliant retrieval of normalized IELTS questions,
passages, answer keys, evidence spans, pedagogical explanations, and linked principles
while strictly enforcing authoritative manifest integrity, active entity validation,
and explicit disclosure of epistemic uncertainty and missing data.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set

import yaml

from harness.config import REPO_ROOT
from harness.normalizers.base import SCHEMA_VERSION, compute_canonical_content_hash

STAGING_NORMALIZED_DIR = REPO_ROOT / "private" / "staging" / "normalized"
PRINCIPLES_DIR = REPO_ROOT / "principles"

QUESTION_ID_PATTERN = re.compile(r"^Q-[A-Z0-9-]+-(RD|LS|WR|SP)-\d{3}$")


def is_safe_entity_filename(filename: str) -> bool:
    """Validates that an entity filename is safe from directory traversal and injection.

    Reuses canonical safe filename rules:
    - Non-empty string
    - No null bytes, forward slashes, or backslashes
    - No parent traversal ('..') or leading dot
    - Pure basename matching Path(filename).name
    """
    if not filename or not isinstance(filename, str):
        return False
    if "\0" in filename:
        return False
    if "/" in filename or "\\" in filename:
        return False
    if ".." in filename or filename.startswith("."):
        return False
    if Path(filename).name != filename:
        return False
    return True


class TutorRetriever:
    """Retrieves full question learning contexts with rigorous uncertainty disclosure."""

    def __init__(
        self,
        normalized_dir: Path = STAGING_NORMALIZED_DIR,
        principles_dir: Path = PRINCIPLES_DIR,
    ):
        self.normalized_dir = Path(normalized_dir)
        self.principles_dir = Path(principles_dir)
        self._principles_cache: Dict[str, Dict[str, Any]] = {}
        self.manifest: Dict[str, Any] = {}
        self._active_entities_by_id: Dict[str, Dict[str, Any]] = {}
        self._active_entities_by_filename: Dict[str, Dict[str, Any]] = {}
        self._stale_entities: Set[str] = set()

        self._load_principles()
        self._load_manifest()

    def _load_principles(self) -> None:
        """Loads and indexes all markdown principles in principles_dir."""
        if not self.principles_dir.exists():
            return

        for p_path in self.principles_dir.rglob("*.md"):
            if p_path.name == "INDEX.md":
                continue
            try:
                content = p_path.read_text(encoding="utf-8")
                if not content.startswith("---"):
                    continue
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    fm = yaml.safe_load(parts[1])
                    if isinstance(fm, dict) and "id" in fm:
                        rel_path = str(p_path.relative_to(self.principles_dir))
                        fm["relative_path"] = rel_path
                        self._principles_cache[fm["id"]] = fm
            except Exception:
                continue

    def _load_manifest(self) -> None:
        """Loads and validates the authoritative manifest.json.

        Fails closed on missing, corrupted, or structurally invalid manifests.
        """
        manifest_path = self.normalized_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"Authoritative manifest missing at '{manifest_path}'. Retrieval must fail closed."
            )

        try:
            m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise ValueError(
                f"Authoritative manifest at '{manifest_path}' is corrupted: {e}"
            ) from e

        if not isinstance(m_data, dict) or "entities" not in m_data or not isinstance(m_data["entities"], list):
            raise ValueError(
                f"Authoritative manifest at '{manifest_path}' is invalid: missing required 'entities' list."
            )

        total_entities = m_data.get("total_entities")
        if total_entities is not None:
            if not isinstance(total_entities, int) or total_entities != len(m_data["entities"]):
                raise ValueError(
                    f"Manifest total_entities mismatch at '{manifest_path}': "
                    f"manifest specifies {total_entities!r}, but entities list contains {len(m_data['entities'])} entries."
                )

        self.manifest = m_data
        for s in m_data.get("stale_entities", []):
            if isinstance(s, str):
                self._stale_entities.add(s)

        seen_ids: Set[str] = set()
        seen_filenames: Set[str] = set()

        for idx, entry in enumerate(m_data["entities"]):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"Manifest entry at index {idx} must be a JSON object, got {type(entry).__name__}."
                )

            entity_id = entry.get("entity_id")
            if not entity_id or not isinstance(entity_id, str) or not entity_id.strip():
                raise ValueError(f"Manifest entry at index {idx} missing valid 'entity_id'.")
            entity_id = entity_id.strip()

            if entity_id in seen_ids:
                raise ValueError(f"Duplicate entity_id '{entity_id}' declared in manifest '{manifest_path}'.")
            seen_ids.add(entity_id)

            filename = entry.get("output_filename")
            if not filename or not isinstance(filename, str) or not filename.strip():
                raise ValueError(f"Manifest entry for entity '{entity_id}' missing valid 'output_filename'.")
            filename = filename.strip()

            if not is_safe_entity_filename(filename):
                raise ValueError(f"Unsafe output_filename '{filename}' declared in manifest '{manifest_path}'.")

            if filename in seen_filenames:
                raise ValueError(f"Duplicate output_filename '{filename}' declared in manifest '{manifest_path}'.")
            seen_filenames.add(filename)

            c_hash = entry.get("canonical_content_sha256")
            if not c_hash or not isinstance(c_hash, str) or len(c_hash) != 64:
                raise ValueError(
                    f"Manifest entry for entity '{entity_id}' missing valid 64-char 'canonical_content_sha256'."
                )

            self._active_entities_by_id[entity_id] = entry
            self._active_entities_by_filename[filename] = entry

    def _validate_question_id(self, question_id: str) -> None:
        """Validates question_id to prevent path traversal and malformed inputs."""
        if not question_id or not isinstance(question_id, str):
            raise ValueError(f"Invalid question_id: must be non-empty string, got {question_id!r}")
        if "\0" in question_id or "/" in question_id or "\\" in question_id or ".." in question_id:
            raise ValueError(
                f"Unsafe question_id: path traversal or invalid characters detected in '{question_id}'."
            )
        if not QUESTION_ID_PATTERN.match(question_id):
            raise ValueError(
                f"Malformed question_id: '{question_id}' does not match canonical pattern "
                r"^Q-[A-Z0-9-]+-(RD|LS|WR|SP)-\d{3}$."
            )

    def _load_active_entity(self, entity_id: str) -> Dict[str, Any]:
        """Loads and verifies an active normalized entity by its entity_id.

        Validates identity, checksum, file existence, and rejects stale/deprecated/corrupted records.
        """
        # 1. Check if entity is declared in active manifest
        if entity_id not in self._active_entities_by_id:
            possible_path = self.normalized_dir / f"{entity_id}.json"
            if (
                possible_path.exists()
                or entity_id in self._stale_entities
                or f"{entity_id}.json" in self._stale_entities
            ):
                raise ValueError(
                    f"Entity '{entity_id}' is stale, deprecated, or not declared in the authoritative manifest."
                )
            raise FileNotFoundError(
                f"Entity '{entity_id}' not found in authoritative manifest."
            )

        entry = self._active_entities_by_id[entity_id]
        filename = entry["output_filename"]
        expected_sha = entry["canonical_content_sha256"]
        file_path = self.normalized_dir / filename

        # 2. Verify file exists on disk
        if not file_path.is_file():
            raise FileNotFoundError(
                f"Declared active entity file '{filename}' for entity '{entity_id}' does not exist on disk in '{self.normalized_dir}'."
            )

        # 3. Read and parse JSON
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise ValueError(f"Corrupted normalized entity file at '{file_path}': {e}") from e

        if not isinstance(data, dict):
            raise ValueError(
                f"Normalized entity at '{file_path}' must be a JSON object, got {type(data).__name__}."
            )

        # 4. Validate identity based on entity type or canonical ID prefix
        etype = entry.get("entity_type")
        if etype == "test" or entity_id.startswith("TEST-"):
            actual_id = data.get("test_id")
        elif etype == "passage" or entity_id.startswith("PASSAGE-") or entity_id.startswith("SECTION-"):
            actual_id = data.get("passage_id")
        elif etype == "question_group" or entity_id.startswith("QG-"):
            actual_id = data.get("group_id")
        elif etype == "question" or entity_id.startswith("Q-"):
            actual_id = data.get("question_id")
        elif etype == "answer" or entity_id.startswith("ANS-"):
            actual_id = data.get("answer_id")
        elif etype == "evidence" or entity_id.startswith("EVID-"):
            actual_id = data.get("evidence_id")
        elif etype == "explanation" or entity_id.startswith("EXPL-"):
            actual_id = data.get("explanation_id")
        else:
            actual_id = (
                data.get("question_id")
                or data.get("group_id")
                or data.get("passage_id")
                or data.get("answer_id")
                or data.get("evidence_id")
                or data.get("explanation_id")
                or data.get("test_id")
            )
        if actual_id != entity_id:
            raise ValueError(
                f"Entity identity mismatch in '{filename}': "
                f"manifest declared '{entity_id}', file contains '{actual_id}'."
            )

        # 5. Check lifecycle status / deprecation
        lifecycle_status = data.get("quality_profile", {}).get("lifecycle_status")
        if lifecycle_status in {"rejected", "deprecated"}:
            raise ValueError(
                f"Entity '{entity_id}' has lifecycle status '{lifecycle_status}' and is rejected."
            )

        # 6. Validate checksum against canonical computation
        computed_sha = compute_canonical_content_hash(data)
        if computed_sha != expected_sha:
            raise ValueError(
                f"Canonical checksum mismatch on entity '{entity_id}' ({filename}): "
                f"manifest specifies '{expected_sha}', computed '{computed_sha}'."
            )

        prov_sha = data.get("_provenance", {}).get("canonical_content_sha256")
        if prov_sha and prov_sha != computed_sha:
            raise ValueError(
                f"Provenance canonical checksum mismatch on entity '{entity_id}' ({filename}): "
                f"provenance specifies '{prov_sha}', computed '{computed_sha}'."
            )

        return data

    def retrieve_question(self, question_id: str) -> Dict[str, Any]:
        """Retrieves complete question bundle for AI Tutor diagnostic and guidance use.

        Args:
            question_id: Canonical question identifier (e.g. 'Q-VOL06-05-RD-004').

        Returns:
            Dictionary containing question, instructions, passage context, answer key,
            evidence span, pedagogical explanation, linked principles, and explicit
            uncertainty disclosure.
        """
        # Validate question ID against path traversal and malformed strings
        self._validate_question_id(question_id)

        # Load active question entity
        q_data = self._load_active_entity(question_id)

        passage_id = q_data.get("passage_id")
        group_id = q_data.get("group_id")
        q_num = q_data.get("question_number")

        # 1. Associated passage - must exist if referenced
        passage_data = None
        if passage_id:
            try:
                passage_data = self._load_active_entity(passage_id)
            except Exception as e:
                raise ValueError(
                    f"Referenced passage '{passage_id}' for question '{question_id}' failed retrieval: {e}"
                ) from e

        # 2. Associated question group - must exist if referenced
        group_data = None
        if group_id:
            try:
                group_data = self._load_active_entity(group_id)
            except Exception as e:
                raise ValueError(
                    f"Referenced question group '{group_id}' for question '{question_id}' failed retrieval: {e}"
                ) from e

        # 3. Associated answer key
        ans_id = f"ANS-{question_id[2:]}-KEY"
        answer_data = None
        if ans_id in self._active_entities_by_id:
            answer_data = self._load_active_entity(ans_id)
        else:
            for cand_id in self._active_entities_by_id:
                if cand_id.startswith(f"ANS-{question_id[2:]}-"):
                    answer_data = self._load_active_entity(cand_id)
                    break

        # 4. Associated evidence
        evid_data = None
        for cand_evid_num in range(1, 10):
            cand_id = f"EVID-{question_id[2:]}-{cand_evid_num:02d}"
            if cand_id in self._active_entities_by_id:
                evid_data = self._load_active_entity(cand_id)
                break

        # 5. Associated explanation
        expl_id = f"EXPL-{question_id[2:]}"
        expl_data = None
        if expl_id in self._active_entities_by_id:
            expl_data = self._load_active_entity(expl_id)
            expl_evid_ref = expl_data.get("evidence_id")
            if expl_evid_ref and expl_evid_ref not in self._active_entities_by_id:
                raise ValueError(
                    f"Explanation '{expl_id}' references evidence '{expl_evid_ref}' which is missing from active manifest."
                )

        # 6. Linked principles resolution
        linked_principles: List[Dict[str, Any]] = []
        for p_id in q_data.get("linked_principle_ids", []):
            if p_id in self._principles_cache:
                p_meta = self._principles_cache[p_id]
                linked_principles.append({
                    "id": p_meta.get("id"),
                    "title": p_meta.get("title"),
                    "type": p_meta.get("type"),
                    "skill": p_meta.get("skill"),
                    "question_types": p_meta.get("question_types", []),
                    "triggers": p_meta.get("triggers", []),
                    "status": p_meta.get("status"),
                    "file_path": f"principles/{p_meta.get('relative_path')}",
                })

        # 7. Uncertainty and Epistemic Readiness Assessment
        uncertainty = self._evaluate_uncertainty(
            q_data=q_data,
            answer_data=answer_data,
            evid_data=evid_data,
            expl_data=expl_data,
            passage_data=passage_data,
        )

        # Structure Passage Context
        passage_summary = None
        if passage_data:
            passage_summary = {
                "passage_id": passage_data.get("passage_id"),
                "title": passage_data.get("title"),
                "subtitle": passage_data.get("subtitle"),
                "word_count": passage_data.get("word_count"),
                "paragraphs_count": len(passage_data.get("paragraphs", [])),
                "narrative_text": passage_data.get("narrative_text"),
            }

        # Structure Group Context
        group_summary = None
        if group_data:
            group_summary = {
                "group_id": group_data.get("group_id"),
                "instruction_text": group_data.get("instruction_text"),
                "question_type": group_data.get("question_type"),
                "word_limit_rule": group_data.get("word_limit_rule"),
            }

        # Structure Answer Summary
        answer_summary = None
        if answer_data:
            qp_ans = answer_data.get("quality_profile", {})
            answer_summary = {
                "answer_id": answer_data.get("answer_id"),
                "target_value": answer_data.get("target_value"),
                "acceptable_alternates": answer_data.get("acceptable_alternates", []),
                "verification_status": qp_ans.get("answer_verification", "unverified"),
                "lifecycle_status": qp_ans.get("lifecycle_status", "review_required"),
                "source_fidelity": qp_ans.get("source_fidelity", "secondary_reputable"),
                "is_missing": answer_data.get("target_value") is None,
                "validation_flags": qp_ans.get("validation_flags", []),
                "provenance": {
                    "source_legacy_id": answer_data.get("_provenance", {}).get("source_legacy_id"),
                    "source_file_id": answer_data.get("_provenance", {}).get("source_file_id"),
                    "raw_block_locator": answer_data.get("_provenance", {}).get("raw_block_locator"),
                },
            }

        # Structure Evidence Summary
        evidence_summary = None
        if evid_data:
            qp_ev = evid_data.get("quality_profile", {})
            evidence_summary = {
                "evidence_id": evid_data.get("evidence_id"),
                "evidence_type": evid_data.get("evidence_type"),
                "paragraph_label": evid_data.get("paragraph_label"),
                "char_start": evid_data.get("char_start"),
                "char_end": evid_data.get("char_end"),
                "verbatim_quote": evid_data.get("verbatim_quote"),
                "exact_match_verified": evid_data.get("exact_match_verified", False),
                "missing_information_rationale": evid_data.get("missing_information_rationale"),
                "lifecycle_status": qp_ev.get("lifecycle_status", "review_required"),
            }

        # Structure Explanation Summary
        explanation_summary = None
        if expl_data:
            qp_ex = expl_data.get("quality_profile", {})
            explanation_summary = {
                "explanation_id": expl_data.get("explanation_id"),
                "author_type": expl_data.get("author_type"),
                "explanation_verification": qp_ex.get("explanation_verification", "unverified"),
                "rationale_en": expl_data.get("rationale_en"),
                "rationale_vi": expl_data.get("rationale_vi"),
                "paraphrase_map": expl_data.get("paraphrase_map", []),
                "lifecycle_status": qp_ex.get("lifecycle_status", "review_required"),
                "validation_flags": qp_ex.get("validation_flags", []),
            }

        return {
            "schema_version": SCHEMA_VERSION,
            "question_id": question_id,
            "question_number": q_num,
            "question_type": q_data.get("question_type"),
            "prompt_text": q_data.get("prompt_text"),
            "blank_target": q_data.get("blank_target"),
            "options": q_data.get("options"),
            "passage": passage_summary,
            "group": group_summary,
            "answer": answer_summary,
            "evidence": evidence_summary,
            "explanation": explanation_summary,
            "linked_principles": linked_principles,
            "uncertainty_disclosure": uncertainty,
        }

    def _evaluate_uncertainty(
        self,
        q_data: Dict[str, Any],
        answer_data: Optional[Dict[str, Any]],
        evid_data: Optional[Dict[str, Any]],
        expl_data: Optional[Dict[str, Any]],
        passage_data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Evaluates epistemic uncertainty and produces explicit disclosure and readiness rating.

        Enforces strict verification across the entire Answer-Evidence-Explanation chain:
        - READY requires sufficient verification across all three dimensions.
        - BLOCKED is assigned when answer key is missing, ungradable, or disputed.
        - REVIEW_REQUIRED is assigned when any element lacks complete verification.
        """
        flags: List[str] = []
        disclosure_lines: List[str] = []

        # --- 1. Answer Verification ---
        is_answer_missing = False
        is_answer_disputed = False
        is_answer_verified = False

        if answer_data is None or answer_data.get("target_value") is None:
            is_answer_missing = True
            flags.append("MISSING_SOURCE_ANSWER_KEY")
            disclosure_lines.append(
                "CRITICAL WARNING: The official answer key for this question is missing in the source materials. "
                "Any proposed answer is speculative and must not be used for diagnostic grading."
            )
        else:
            ans_qp = answer_data.get("quality_profile", {})
            flags.extend(ans_qp.get("validation_flags", []))
            ans_ver = ans_qp.get("answer_verification", "unverified")
            ans_lifecycle = ans_qp.get("lifecycle_status", "review_required")

            if ans_ver == "missing_key":
                is_answer_missing = True
                flags.append("MISSING_SOURCE_ANSWER_KEY")
                disclosure_lines.append(
                    "CRITICAL WARNING: The official answer key for this question is marked as missing in source materials. "
                    "Cannot evaluate learner responses without authoritative key."
                )
            elif ans_ver == "disputed" or ans_lifecycle == "rejected":
                is_answer_disputed = True
                flags.append("DISPUTED_ANSWER_KEY")
                disclosure_lines.append(
                    "CRITICAL WARNING: The answer key for this question is disputed or rejected. "
                    "Automated diagnostic grading is prohibited."
                )
            elif ans_ver in {"authoritative_key", "consensus_key"} and ans_lifecycle in {"verified", "reviewed"}:
                is_answer_verified = True
            else:
                if "SINGLE_SOURCE_UNVERIFIED_KEY" not in flags:
                    flags.append("SINGLE_SOURCE_UNVERIFIED_KEY")
                disclosure_lines.append(
                    f"NOTICE: The answer key '{answer_data.get('target_value')}' is extracted from secondary materials "
                    "without publisher authoritative confirmation or authenticated human expert review."
                )

        # --- 2. Evidence Verification ---
        is_evidence_missing = evid_data is None
        is_evidence_verified = False

        if is_evidence_missing:
            flags.append("MISSING_EVIDENCE_SPAN")
            disclosure_lines.append("EVIDENCE: No textual evidence span has been grounded for this item.")
        else:
            ev_qp = evid_data.get("quality_profile", {})
            flags.extend(ev_qp.get("validation_flags", []))
            ev_type = evid_data.get("evidence_type")
            ev_lifecycle = ev_qp.get("lifecycle_status", "review_required")

            if ev_type == "insufficient_information_not_given":
                flags.append("NOT_GIVEN_EVIDENCE_INVARIANT")
                # NOT GIVEN invariant: quote must be None, char offsets must be None, rationale must exist
                has_rationale = bool(evid_data.get("missing_information_rationale"))
                quote_is_none = (
                    evid_data.get("verbatim_quote") is None
                    and evid_data.get("char_start") is None
                    and evid_data.get("char_end") is None
                )
                if quote_is_none and has_rationale and ev_lifecycle in {"verified", "reviewed"}:
                    is_evidence_verified = True

                disclosure_lines.append(
                    "EVIDENCE: This is a NOT GIVEN item. The passage does not contain information to prove or disprove the prompt. "
                    "Per data invariant, no verbatim quote is cited."
                )
            elif ev_type in {"direct_support", "contradictory_evidence"}:
                exact_match = evid_data.get("exact_match_verified", False)
                quote = evid_data.get("verbatim_quote")
                c_start = evid_data.get("char_start")
                c_end = evid_data.get("char_end")

                valid_slice = (
                    exact_match is True
                    and isinstance(quote, str)
                    and len(quote) > 0
                    and isinstance(c_start, int)
                    and isinstance(c_end, int)
                    and 0 <= c_start < c_end
                )

                if valid_slice and passage_data:
                    narrative = passage_data.get("narrative_text", "")
                    if narrative[c_start:c_end] != quote:
                        valid_slice = False
                        flags.append("EVIDENCE_OFFSET_MISMATCH")

                # Exact text match does NOT equate to semantic correctness.
                # Evidence verification requires valid slice AND verified/reviewed lifecycle.
                if valid_slice and ev_lifecycle in {"verified", "reviewed"}:
                    is_evidence_verified = True

                if valid_slice:
                    disclosure_lines.append(
                        f"EVIDENCE: Direct textual support verified at character offsets {c_start}-{c_end}."
                    )
                else:
                    disclosure_lines.append("EVIDENCE: Evidence span character offsets are unverified or mismatched.")
            else:
                disclosure_lines.append(f"EVIDENCE: Unknown evidence type '{ev_type}'.")

        # --- 3. Explanation Verification ---
        is_explanation_missing = expl_data is None
        is_explanation_verified = False

        if is_explanation_missing:
            flags.append("MISSING_PEDAGOGICAL_EXPLANATION")
            disclosure_lines.append("EXPLANATION: No pedagogical explanation is currently available in the dataset.")
        else:
            ex_qp = expl_data.get("quality_profile", {})
            flags.extend(ex_qp.get("validation_flags", []))
            ex_ver = ex_qp.get("explanation_verification", "unverified")
            author_type = expl_data.get("author_type")
            ex_lifecycle = ex_qp.get("lifecycle_status", "review_required")
            has_rationale = bool(expl_data.get("rationale_en") or expl_data.get("rationale_vi"))

            if author_type == "machine_drafted":
                flags.append("MACHINE_DRAFTED_EXPLANATION")
                disclosure_lines.append(
                    "EXPLANATION: Pedagogical explanation is machine-drafted and has not been certified by an IELTS tutor."
                )

            # Answer verification does NOT equate to explanation verification.
            # Explanation verification requires pedagogical rationale AND expert verification or certified official source.
            if has_rationale and ex_lifecycle in {"verified", "reviewed"}:
                if ex_ver == "expert_verified":
                    is_explanation_verified = True
                elif ex_ver == "source_provided" and author_type != "machine_drafted":
                    is_explanation_verified = True

        # --- 4. Readiness Classification ---
        flags = sorted(list(set(flags)))

        if is_answer_missing:
            readiness = "BLOCKED"
            readiness_reason = (
                "Answer key is completely missing from physical source materials (scan omission or page truncation). "
                "The tutor cannot evaluate learner responses or provide definitive feedback."
            )
        elif is_answer_disputed:
            readiness = "BLOCKED"
            readiness_reason = (
                "Answer key is disputed or rejected. Autonomous evaluation and quizzing are prohibited."
            )
        elif is_answer_verified and is_evidence_verified and is_explanation_verified:
            readiness = "READY"
            readiness_reason = (
                "Complete authoritative chain verified across Answer, Evidence, and Pedagogical Explanation."
            )
        else:
            readiness = "REVIEW_REQUIRED"
            unverified_reasons = []
            if not is_answer_verified:
                unverified_reasons.append("Answer key lacks authenticated human expert or authoritative publisher verification.")
            if not is_evidence_verified:
                unverified_reasons.append("Evidence grounding is missing, unverified, or lacks semantic verification.")
            if not is_explanation_verified:
                unverified_reasons.append("Pedagogical explanation is unverified, machine-drafted, or missing.")
            readiness_reason = "Verification required: " + " ".join(unverified_reasons)

        is_human_verified = (
            is_answer_verified
            and is_evidence_verified
            and is_explanation_verified
            and bool(answer_data and answer_data.get("quality_profile", {}).get("lifecycle_status") == "verified")
        )

        return {
            "readiness": readiness,
            "readiness_reason": readiness_reason,
            "is_answer_missing": is_answer_missing,
            "is_key_unverified": not is_answer_verified,
            "is_human_verified": is_human_verified,
            "flags": flags,
            "disclosure_text": " ".join(disclosure_lines),
        }
