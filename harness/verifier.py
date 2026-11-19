"""Verification engine and Quality Gates (G1-G7) runner for IELTS Data Harness V0.2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from harness.config import DB_PATH, REPO_ROOT
from harness.db import get_db_connection, get_source_by_file_id, get_source_by_legacy_id
from harness.normalizers.base import compute_canonical_content_hash

SCHEMAS_DIR = REPO_ROOT / "schemas" / "v02"


def load_validator_registry() -> Tuple[Dict[str, Dict[str, Any]], Registry]:
    """Loads all V0.2 JSON schemas and returns schema dictionary and referencing registry."""
    schemas = {}
    for p in SCHEMAS_DIR.glob("*.json"):
        with open(p, "r", encoding="utf-8") as f:
            schemas[p.name] = json.load(f)

    reg = Registry()
    for s_name, s_data in schemas.items():
        res = Resource.from_contents(s_data)
        reg = reg.with_resource(s_data["$id"], res)
        reg = reg.with_resource(s_name, res)

    return schemas, reg


class QualityGateRunner:
    """Verifies normalized IELTS entities against Quality Gates G1 to G7."""

    def __init__(self, schemas_dir: Path = SCHEMAS_DIR, db_path: Path = DB_PATH):
        self.schemas_dir = schemas_dir
        self.db_path = db_path
        self.schemas, self.registry = load_validator_registry()

    def load_entities_for_test(self, normalized_dir: Path, test_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """Loads all normalized JSON files associated with test_id from normalized_dir."""
        entities: Dict[str, List[Dict[str, Any]]] = {
            "test": [],
            "passages": [],
            "groups": [],
            "questions": [],
            "answers": [],
            "evidence": [],
            "explanations": [],
        }

        # Substring key in filename e.g. VOL06-05
        test_slug = test_id.replace("TEST-IELTS-", "").rsplit("-", 1)[0]

        for p in normalized_dir.glob("*.json"):
            if p.name == "manifest.json":
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue

            if not isinstance(data, dict):
                continue

            if p.name.startswith("TEST-") and (data.get("test_id") == test_id or test_slug in p.name):
                entities["test"].append(data)
            elif p.name.startswith("PASSAGE-") and (data.get("test_id") == test_id or test_slug in p.name):
                entities["passages"].append(data)
            elif p.name.startswith("QG-") and test_slug in p.name:
                entities["groups"].append(data)
            elif p.name.startswith("Q-") and test_slug in p.name:
                entities["questions"].append(data)
            elif p.name.startswith("ANS-") and test_slug in p.name:
                entities["answers"].append(data)
            elif p.name.startswith("EVID-") and test_slug in p.name:
                entities["evidence"].append(data)
            elif p.name.startswith("EXPL-") and test_slug in p.name:
                entities["explanations"].append(data)

        # Sort questions and answers by numerical sequence
        entities["questions"].sort(key=lambda x: x.get("question_number", 0))
        entities["answers"].sort(key=lambda x: x.get("answer_id", ""))
        return entities

    def verify_all_gates(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Runs Quality Gates G1 through G7 against loaded entities."""
        report: Dict[str, Any] = {
            "overall_status": "PASS",
            "gates": {},
            "statistics": {
                "tests_count": len(entities["test"]),
                "passages_count": len(entities["passages"]),
                "groups_count": len(entities["groups"]),
                "questions_count": len(entities["questions"]),
                "answers_count": len(entities["answers"]),
                "evidence_count": len(entities["evidence"]),
                "explanations_count": len(entities["explanations"]),
            },
            "unresolved_items": [],
            "warnings": [],
            "errors": [],
        }

        # G1: Source Integrity
        g1_res = self.verify_g1_source_integrity(entities)
        report["gates"]["G1_source_integrity"] = g1_res
        if not g1_res["passed"]:
            report["errors"].extend(g1_res["errors"])

        # G2: Structural Fidelity
        g2_res = self.verify_g2_structural_fidelity(entities)
        report["gates"]["G2_structural_fidelity"] = g2_res
        if not g2_res["passed"]:
            report["errors"].extend(g2_res["errors"])
        report["warnings"].extend(g2_res.get("warnings", []))

        # G3: Schema Compliance
        g3_res = self.verify_g3_schema_compliance(entities)
        report["gates"]["G3_schema_compliance"] = g3_res
        if not g3_res["passed"]:
            report["errors"].extend(g3_res["errors"])

        # G4: Referential Integrity
        g4_res = self.verify_g4_referential_integrity(entities)
        report["gates"]["G4_referential_integrity"] = g4_res
        if not g4_res["passed"]:
            report["errors"].extend(g4_res["errors"])
        report["unresolved_items"].extend(g4_res.get("unresolved", []))

        # G5: Evidence Fidelity
        g5_res = self.verify_g5_evidence_fidelity(entities)
        report["gates"]["G5_evidence_fidelity"] = g5_res
        if not g5_res["passed"]:
            report["errors"].extend(g5_res["errors"])

        # G6: Deterministic Processing
        g6_res = self.verify_g6_deterministic_processing(entities)
        report["gates"]["G6_deterministic_processing"] = g6_res
        if not g6_res["passed"]:
            report["errors"].extend(g6_res["errors"])

        # G7: Privacy Isolation
        g7_res = self.verify_g7_privacy_isolation(entities)
        report["gates"]["G7_privacy_isolation"] = g7_res
        if not g7_res["passed"]:
            report["errors"].extend(g7_res["errors"])

        # Determine overall status: FAIL if any error, PASS_WITH_UNRESOLVED if warnings/unresolved items, else PASS
        has_fail = any(not g.get("passed") for g in report["gates"].values())
        has_unresolved = (
            any(g.get("status") in ("PASS_WITH_UNRESOLVED", "REVIEW_REQUIRED") for g in report["gates"].values())
            or len(report["unresolved_items"]) > 0
        )
        if has_fail:
            report["overall_status"] = "FAIL"
        elif has_unresolved:
            report["overall_status"] = "PASS_WITH_UNRESOLVED"
        else:
            report["overall_status"] = "PASS"

        return report

    def verify_g1_source_integrity(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """G1: Verify source files and staged extractions match expected hashes."""
        errors = []
        db_available = self.db_path.exists()
        conn = get_db_connection(self.db_path) if db_available else None

        all_items = (
            entities["test"]
            + entities["passages"]
            + entities["groups"]
            + entities["questions"]
            + entities["answers"]
            + entities["evidence"]
            + entities["explanations"]
        )

        checked_sources = set()
        for item in all_items:
            # Skip SQLite source check for synthetic public test fixtures
            qp = item.get("quality_profile", {})
            if qp.get("publication_permission") == "public_synthetic":
                continue

            # For non-synthetic entities, database source verification is mandatory
            if not db_available or not conn:
                errors.append(f"Mandatory source verification unavailable: SQLite database not found at {self.db_path}")
                break

            prov = item.get("_provenance", {})
            file_id = prov.get("source_file_id")
            legacy_id = prov.get("source_legacy_id")
            source_sha = prov.get("source_sha256")

            if not file_id or not source_sha:
                errors.append(f"Entity {item.get('test_id', item.get('question_id', 'unknown'))} missing provenance IDs.")
                continue

            if file_id in checked_sources:
                continue
            checked_sources.add(file_id)

            src_rec = get_source_by_file_id(conn, file_id) or get_source_by_legacy_id(conn, legacy_id)
            if not src_rec:
                errors.append(f"Source {legacy_id} ({file_id}) not found in SQLite sources table.")
            elif src_rec["content_sha256"] != source_sha:
                errors.append(f"Source SHA mismatch for {legacy_id}: DB={src_rec['content_sha256']} vs Prov={source_sha}")

        if conn:
            conn.close()

        status = "FAIL" if errors else "PASS"
        return {"passed": len(errors) == 0, "status": status, "errors": errors, "sources_verified": len(checked_sources)}

    def verify_g2_structural_fidelity(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """G2: Verify sequential numbering, count consistency, and group boundaries."""
        errors = []
        warnings = []
        questions = entities["questions"]
        groups = entities["groups"]

        if not questions:
            errors.append("No questions found for structural validation.")
            return {"passed": False, "status": "FAIL", "errors": errors, "warnings": warnings}

        q_nums = [q.get("question_number") for q in questions]
        expected_range = list(range(min(q_nums), max(q_nums) + 1))

        # Check duplicates
        seen = set()
        for n in q_nums:
            if n in seen:
                errors.append(f"Duplicate question number detected: {n}")
            seen.add(n)

        # Check missing numbers
        missing_nums = set(expected_range) - set(q_nums)
        if missing_nums:
            errors.append(f"Missing question numbers in sequence: {sorted(missing_nums)}")

        # Validate question group boundaries and counts
        group_expected_total = 0
        all_group_q_nums = set()
        for g in groups:
            g_id = g.get("group_id", "unknown_group")
            start_q = g.get("start_question_number")
            end_q = g.get("end_question_number")

            if start_q is None or end_q is None or start_q > end_q:
                errors.append(f"Group {g_id} has invalid boundaries: start={start_q}, end={end_q}")
                continue

            expected_group_q = set(range(start_q, end_q + 1))
            group_expected_total += len(expected_group_q)

            # Check for overlapping group ranges
            if all_group_q_nums & expected_group_q:
                errors.append(f"Group {g_id} range overlaps with another group: {sorted(all_group_q_nums & expected_group_q)}")
            all_group_q_nums.update(expected_group_q)

            # Verify questions assigned to this group
            assigned_questions = [q for q in questions if q.get("group_id") == g_id]
            assigned_q_nums = [q.get("question_number") for q in assigned_questions]

            # All assigned questions must be within [start_q, end_q]
            for qn in assigned_q_nums:
                if qn < start_q or qn > end_q:
                    errors.append(f"Question {qn} assigned to group {g_id} is outside boundary [{start_q}, {end_q}]")

            # Check question count for this group
            if len(assigned_questions) != len(expected_group_q):
                errors.append(f"Group {g_id} expects {len(expected_group_q)} questions [{start_q}-{end_q}], but found {len(assigned_questions)}")

        # Check total questions vs total expected across groups
        if groups and len(questions) != group_expected_total:
            errors.append(f"Total questions count ({len(questions)}) does not match expected groups sum ({group_expected_total})")

        # Check questions with unresolved prompts or forbidden placeholders
        for q in questions:
            prompt_text = q.get("prompt_text", "")
            if "[question" in prompt_text.lower() and "unresolved]" in prompt_text.lower():
                errors.append(f"Question {q.get('question_id')} contains forbidden placeholder prompt: '{prompt_text}'")
            flags = q.get("quality_profile", {}).get("validation_flags", [])
            if "UNRESOLVED_QUESTION_PROMPT" in flags:
                warnings.append(f"Question {q.get('question_id')} has unresolved prompt.")

        status = "FAIL" if errors else ("REVIEW_REQUIRED" if warnings else "PASS")
        return {"passed": len(errors) == 0, "status": status, "errors": errors, "warnings": warnings}

    def verify_g3_schema_compliance(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """G3: Validate every entity against its JSON schema."""
        errors = []
        mapping = {
            "test": "test.schema.json",
            "passages": "passage_section.schema.json",
            "groups": "question_group.schema.json",
            "questions": "question.schema.json",
            "answers": "answer.schema.json",
            "evidence": "evidence.schema.json",
            "explanations": "explanation.schema.json",
        }

        total_checked = 0
        for category, schema_name in mapping.items():
            schema = self.schemas.get(schema_name)
            if not schema:
                errors.append(f"Schema not found: {schema_name}")
                continue
            validator = Draft202012Validator(schema, registry=self.registry)

            for item in entities[category]:
                total_checked += 1
                try:
                    validator.validate(item)
                except Exception as e:
                    item_id = item.get("test_id", item.get("question_id", item.get("answer_id", item.get("evidence_id", item.get("explanation_id", "unknown")))))
                    errors.append(f"Schema validation error on {category} ({item_id}): {e.message if hasattr(e, 'message') else str(e)}")

        status = "FAIL" if errors else "PASS"
        return {"passed": len(errors) == 0, "status": status, "errors": errors, "entities_validated": total_checked}

    def verify_g4_referential_integrity(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """G4: Verify relational integrity across entities."""
        errors = []
        unresolved = []

        test_ids = {t["test_id"] for t in entities["test"]}
        passage_ids = {p["passage_id"] for p in entities["passages"]}
        group_ids = {g["group_id"] for g in entities["groups"]}
        question_ids = {q["question_id"] for q in entities["questions"]}
        answer_ids = {a["answer_id"] for a in entities["answers"]}
        evidence_ids = {e["evidence_id"] for e in entities["evidence"]}

        # Passages point to Test
        for p in entities["passages"]:
            if p["test_id"] not in test_ids:
                errors.append(f"Passage {p['passage_id']} references missing test_id: {p['test_id']}")

        # Groups point to Passage
        for g in entities["groups"]:
            if g.get("passage_id") and g["passage_id"] not in passage_ids:
                errors.append(f"Group {g['group_id']} references missing passage_id: {g['passage_id']}")

        # Questions point to Group and Passage
        for q in entities["questions"]:
            if q["group_id"] not in group_ids:
                errors.append(f"Question {q['question_id']} references missing group_id: {q['group_id']}")
            if q.get("passage_id") and q["passage_id"] not in passage_ids:
                errors.append(f"Question {q['question_id']} references missing passage_id: {q['passage_id']}")

        # Answers point to Question
        for a in entities["answers"]:
            q_id = a.get("question_id")
            if q_id is not None:
                if q_id not in question_ids:
                    errors.append(f"Answer {a['answer_id']} references non-existent question_id: {q_id}")
            else:
                unresolved.append({"type": "orphan_answer", "id": a["answer_id"], "note": "Orphan key without question"})

            if a.get("target_value") is None:
                unresolved.append({"type": "missing_answer_key", "id": a["answer_id"], "note": f"Missing key for {q_id}"})

        # Evidence points to Answer and Passage
        for e in entities["evidence"]:
            if e.get("answer_id") and e["answer_id"] not in answer_ids:
                errors.append(f"Evidence {e['evidence_id']} references missing answer_id: {e['answer_id']}")
            if e.get("passage_id") and e["passage_id"] not in passage_ids:
                errors.append(f"Evidence {e['evidence_id']} references missing passage_id: {e['passage_id']}")

        # Explanations point to Question, Answer, Evidence
        for ex in entities["explanations"]:
            if ex["question_id"] not in question_ids:
                errors.append(f"Explanation {ex['explanation_id']} references missing question_id: {ex['question_id']}")
            if ex.get("answer_id") and ex["answer_id"] not in answer_ids:
                errors.append(f"Explanation {ex['explanation_id']} references missing answer_id: {ex['answer_id']}")
            if ex.get("evidence_id") and ex["evidence_id"] not in evidence_ids:
                errors.append(f"Explanation {ex['explanation_id']} references missing evidence_id: {ex['evidence_id']}")

        # Check questions without matching answer
        answers_by_q = {a.get("question_id"): a for a in entities["answers"] if a.get("question_id")}
        for q in entities["questions"]:
            qid = q.get("question_id")
            if qid not in answers_by_q:
                unresolved.append({"type": "unanswered_question", "id": qid, "note": f"Question {qid} has no matching answer record"})

        status = "FAIL" if errors else ("PASS_WITH_UNRESOLVED" if unresolved else "PASS")
        return {"passed": len(errors) == 0, "status": status, "errors": errors, "unresolved": unresolved}

    def verify_g5_evidence_fidelity(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """G5: Verify evidence grounding and NOT GIVEN null quotation rule, separating textual and semantic checks."""
        errors = []
        textual_errors = []
        semantic_errors = []
        verified_spans = 0
        checked_semantic = 0

        passages_by_id = {p["passage_id"]: p for p in entities["passages"]}
        answers_by_id = {a["answer_id"]: a for a in entities["answers"]}

        for evid in entities["evidence"]:
            p_id = evid.get("passage_id")
            passage = passages_by_id.get(p_id)
            ev_type = evid.get("evidence_type")

            # 1. Textual Grounding Verification
            if ev_type == "insufficient_information_not_given":
                # Must NOT have verbatim quote or char offsets
                if evid.get("verbatim_quote") is not None:
                    textual_errors.append(f"NOT GIVEN evidence {evid['evidence_id']} has non-null verbatim_quote.")
                if evid.get("char_start") is not None or evid.get("char_end") is not None:
                    textual_errors.append(f"NOT GIVEN evidence {evid['evidence_id']} has non-null character offsets.")
                if not evid.get("missing_information_rationale"):
                    textual_errors.append(f"NOT GIVEN evidence {evid['evidence_id']} missing information rationale.")
            elif ev_type in {"direct_support", "contradictory_evidence"}:
                quote = evid.get("verbatim_quote")
                c_start = evid.get("char_start")
                c_end = evid.get("char_end")

                if not quote:
                    textual_errors.append(f"Evidence {evid['evidence_id']} ({ev_type}) missing verbatim_quote.")
                elif c_start is None or c_end is None or c_start < 0 or c_start >= c_end:
                    textual_errors.append(f"Evidence {evid['evidence_id']} has invalid offsets: [{c_start}, {c_end}]")
                elif evid.get("exact_match_verified") is True:
                    if passage:
                        narrative = passage.get("narrative_text", "")
                        actual_span = narrative[c_start:c_end]
                        if actual_span != quote:
                            textual_errors.append(
                                f"Evidence span mismatch on {evid['evidence_id']}: span='{actual_span[:30]}' vs quote='{quote[:30]}'"
                            )
                        else:
                            verified_spans += 1

            # 2. Semantic Answer Verification
            ans_id = evid.get("answer_id")
            if ans_id and ans_id in answers_by_id:
                ans_rec = answers_by_id[ans_id]
                target_val = ans_rec.get("target_value")
                if target_val:
                    checked_semantic += 1
                    norm_target = str(target_val).strip().upper()
                    if norm_target in ("TRUE", "YES") and ev_type != "direct_support":
                        semantic_errors.append(
                            f"Semantic mismatch on evidence {evid['evidence_id']}: answer is '{norm_target}' but evidence_type is '{ev_type}' (expected 'direct_support')"
                        )
                    elif norm_target in ("FALSE", "NO") and ev_type != "contradictory_evidence":
                        semantic_errors.append(
                            f"Semantic mismatch on evidence {evid['evidence_id']}: answer is '{norm_target}' but evidence_type is '{ev_type}' (expected 'contradictory_evidence')"
                        )
                    elif norm_target == "NOT GIVEN" and ev_type != "insufficient_information_not_given":
                        semantic_errors.append(
                            f"Semantic mismatch on evidence {evid['evidence_id']}: answer is 'NOT GIVEN' but evidence_type is '{ev_type}' (expected 'insufficient_information_not_given')"
                        )

        errors.extend(textual_errors)
        errors.extend(semantic_errors)
        status = "FAIL" if errors else "PASS"

        return {
            "passed": len(errors) == 0,
            "status": status,
            "errors": errors,
            "textual_grounding": {
                "passed": len(textual_errors) == 0,
                "errors": textual_errors,
                "verified_spans": verified_spans,
            },
            "semantic_verification": {
                "passed": len(semantic_errors) == 0,
                "errors": semantic_errors,
                "checked_pairs": checked_semantic,
            },
        }

    def verify_g6_deterministic_processing(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """G6: Verify canonical content hashes match deterministic payload computation."""
        errors = []
        all_items = (
            entities["test"]
            + entities["passages"]
            + entities["groups"]
            + entities["questions"]
            + entities["answers"]
            + entities["evidence"]
            + entities["explanations"]
        )

        checked_count = 0
        for item in all_items:
            item_id = item.get("test_id", item.get("question_id", item.get("answer_id", item.get("evidence_id", item.get("explanation_id", item.get("passage_id", item.get("group_id", "unknown")))))))
            prov = item.get("_provenance", {})
            recorded_hash = prov.get("canonical_content_sha256")
            if not recorded_hash:
                errors.append(f"Missing canonical_content_sha256 in provenance for {item_id}")
                continue

            computed = compute_canonical_content_hash(item)
            if computed != recorded_hash:
                errors.append(f"Canonical hash mismatch on {item_id}: recorded={recorded_hash} vs computed={computed}")
            else:
                checked_count += 1

        status = "FAIL" if errors else "PASS"
        return {
            "passed": len(errors) == 0,
            "status": status,
            "errors": errors,
            "entities_checked": checked_count,
        }

    def verify_g7_privacy_isolation(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """G7: Verify no private copyrighted text is exposed to public paths or unisolated outputs."""
        errors = []

        # 1. Check all in-memory entities: if publication_permission is private_copyrighted,
        # ensure output destination path or relative path is confined to private/
        for category, items in entities.items():
            for item in items:
                qp = item.get("quality_profile", {})
                prov = item.get("_provenance", {})
                perm = qp.get("publication_permission")
                output_rel_path = item.get("_output_path") or prov.get("relative_path") or ""
                if perm == "private_copyrighted":
                    if output_rel_path and not output_rel_path.startswith("private/"):
                        item_id = item.get("test_id", item.get("question_id", item.get("answer_id", item.get("evidence_id", item.get("explanation_id", "unknown")))))
                        errors.append(f"Private copyrighted entity {item_id} has public/non-private output path: {output_rel_path}")

        # 2. Check all public filesystem paths for leaked private_copyrighted entities
        public_dirs = [
            REPO_ROOT / "data",
            REPO_ROOT / "schemas",
            REPO_ROOT / "harness",
            REPO_ROOT / "tests",
            REPO_ROOT / "principles",
            REPO_ROOT / "docs",
        ]
        for pdir in public_dirs:
            if not pdir.exists():
                continue
            for p in pdir.rglob("*.json"):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        qp = data.get("quality_profile", {})
                        if qp.get("publication_permission") == "private_copyrighted":
                            errors.append(f"Private copyrighted entity stored under public path {p.relative_to(REPO_ROOT)}")
                    elif isinstance(data, list):
                        for elem in data:
                            if isinstance(elem, dict) and elem.get("quality_profile", {}).get("publication_permission") == "private_copyrighted":
                                errors.append(f"Private copyrighted entity found in list under public path {p.relative_to(REPO_ROOT)}")
                except Exception:
                    pass

        status = "FAIL" if errors else "PASS"
        return {"passed": len(errors) == 0, "status": status, "errors": errors}
