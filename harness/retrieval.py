"""Tutor retrieval engine for IELTS Data Harness V0.2.

Provides deterministic, schema-compliant retrieval of normalized IELTS questions,
passages, answer keys, evidence spans, pedagogical explanations, and linked principles
while explicitly disclosing epistemic uncertainty, source authority, and missing data.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

import yaml

from harness.config import REPO_ROOT
from harness.normalizers.base import SCHEMA_VERSION

STAGING_NORMALIZED_DIR = REPO_ROOT / "private" / "staging" / "normalized"
PRINCIPLES_DIR = REPO_ROOT / "principles"


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
        self._load_principles()

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

    def _load_json(self, filename: str) -> Optional[Dict[str, Any]]:
        """Safely loads a JSON entity file from the normalized directory."""
        path = self.normalized_dir / filename
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def retrieve_question(self, question_id: str) -> Dict[str, Any]:
        """Retrieves complete question bundle for AI Tutor diagnostic and guidance use.

        Args:
            question_id: Canonical question identifier (e.g. 'Q-VOL06-05-RD-004').

        Returns:
            Dictionary containing question, instructions, passage context, answer key,
            evidence span, pedagogical explanation, linked principles, and explicit
            uncertainty disclosure.
        """
        q_data = self._load_json(f"{question_id}.json")
        if not q_data:
            raise FileNotFoundError(f"Question entity '{question_id}' not found in '{self.normalized_dir}'.")

        passage_id = q_data.get("passage_id")
        group_id = q_data.get("group_id")
        q_num = q_data.get("question_number")

        # 1. Associated passage
        passage_data = self._load_json(f"{passage_id}.json") if passage_id else None

        # 2. Associated question group
        group_data = self._load_json(f"{group_id}.json") if group_id else None

        # 3. Associated answer key
        ans_filename = f"ANS-{question_id[2:]}-KEY.json"
        answer_data = self._load_json(ans_filename)

        # 4. Associated evidence
        evid_data = None
        for cand_evid_num in [1, 2]:
            cand_filename = f"EVID-{question_id[2:]}-{cand_evid_num:02d}.json"
            evid_data = self._load_json(cand_filename)
            if evid_data:
                break

        # 5. Associated explanation
        expl_filename = f"EXPL-{question_id[2:]}.json"
        expl_data = self._load_json(expl_filename)

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
        """Evaluates epistemic uncertainty and produces explicit disclosure and readiness rating."""
        flags: List[str] = []
        is_answer_missing = False
        is_key_unverified = False
        is_evidence_missing = evid_data is None
        is_explanation_missing = expl_data is None
        is_human_verified = False

        # Answer evaluation
        if answer_data is None or answer_data.get("target_value") is None:
            is_answer_missing = True
            flags.append("MISSING_SOURCE_ANSWER_KEY")
        else:
            ans_qp = answer_data.get("quality_profile", {})
            flags.extend(ans_qp.get("validation_flags", []))
            if ans_qp.get("answer_verification") == "unverified":
                is_key_unverified = True
            if ans_qp.get("lifecycle_status") == "verified":
                is_human_verified = True

        # Evidence evaluation
        if evid_data:
            ev_qp = evid_data.get("quality_profile", {})
            flags.extend(ev_qp.get("validation_flags", []))
            if evid_data.get("evidence_type") == "insufficient_information_not_given":
                flags.append("NOT_GIVEN_EVIDENCE_INVARIANT")
        else:
            flags.append("MISSING_EVIDENCE_SPAN")

        # Explanation evaluation
        if expl_data:
            ex_qp = expl_data.get("quality_profile", {})
            flags.extend(ex_qp.get("validation_flags", []))
            if expl_data.get("author_type") == "machine_drafted":
                flags.append("MACHINE_DRAFTED_EXPLANATION")
        else:
            flags.append("MISSING_PEDAGOGICAL_EXPLANATION")

        # Deduplicate flags
        flags = sorted(list(set(flags)))

        # Assign readiness
        # BLOCKED: Missing answer key -> Cannot evaluate or tutor without key
        # REVIEW_REQUIRED: Answer key exists but is unverified secondary or lacks complete evidence/explanation
        # READY: Verified authoritative key with grounded evidence and verified explanation
        if is_answer_missing:
            readiness = "BLOCKED"
            readiness_reason = (
                "Answer key is completely missing from physical source materials (scan omission or page truncation). "
                "The tutor cannot evaluate learner responses or provide definitive feedback."
            )
        elif is_key_unverified or is_evidence_missing or is_explanation_missing or not is_human_verified:
            readiness = "REVIEW_REQUIRED"
            readiness_reason = (
                "Entity relies on single-source secondary materials without authenticated human expert verification, "
                "or lacks complete evidence/explanation grounding."
            )
        else:
            readiness = "READY"
            readiness_reason = "Complete authoritative chain with verified evidence and explanations."

        # Human-readable uncertainty disclosure text
        disclosure_lines = []
        if is_answer_missing:
            disclosure_lines.append(
                "CRITICAL WARNING: The official answer key for this question is missing in the source materials. "
                "No authoritative key was scanned in SRC-137, and supplementary keys (e.g. SRC-077) belong to a different volume. "
                "Any proposed answer is speculative and must not be used for diagnostic grading."
            )
        elif is_key_unverified:
            disclosure_lines.append(
                f"NOTICE: The answer key '{answer_data.get('target_value')}' is extracted from a secondary guide (SRC-137) "
                "without publisher authoritative confirmation or human expert review."
            )

        if evid_data:
            if evid_data.get("evidence_type") == "insufficient_information_not_given":
                disclosure_lines.append(
                    "EVIDENCE: This is a NOT GIVEN item. The passage does not contain information to prove or disprove the prompt. "
                    "Per data invariant, no verbatim quote is cited."
                )
            elif evid_data.get("exact_match_verified"):
                disclosure_lines.append(
                    f"EVIDENCE: Direct textual support verified at character offsets {evid_data.get('char_start')}-{evid_data.get('char_end')}."
                )
        else:
            disclosure_lines.append("EVIDENCE: No textual evidence span has been grounded for this item.")

        if expl_data:
            if expl_data.get("author_type") == "machine_drafted":
                disclosure_lines.append(
                    "EXPLANATION: Pedagogical explanation is machine-drafted and has not been certified by a certified IELTS tutor."
                )
        else:
            disclosure_lines.append("EXPLANATION: No pedagogical explanation is currently available in the dataset.")

        return {
            "readiness": readiness,
            "readiness_reason": readiness_reason,
            "is_answer_missing": is_answer_missing,
            "is_key_unverified": is_key_unverified,
            "is_human_verified": is_human_verified,
            "flags": flags,
            "disclosure_text": " ".join(disclosure_lines),
        }
