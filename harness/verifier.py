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
            report["overall_status"] = "FAIL"
            report["errors"].extend(g1_res["errors"])

        # G2: Structural Fidelity
        g2_res = self.verify_g2_structural_fidelity(entities)
        report["gates"]["G2_structural_fidelity"] = g2_res
        if not g2_res["passed"]:
            report["overall_status"] = "FAIL"
            report["errors"].extend(g2_res["errors"])
        report["warnings"].extend(g2_res.get("warnings", []))

        # G3: Schema Compliance
        g3_res = self.verify_g3_schema_compliance(entities)
        report["gates"]["G3_schema_compliance"] = g3_res
        if not g3_res["passed"]:
            report["overall_status"] = "FAIL"
            report["errors"].extend(g3_res["errors"])

        # G4: Referential Integrity
        g4_res = self.verify_g4_referential_integrity(entities)
        report["gates"]["G4_referential_integrity"] = g4_res
        if not g4_res["passed"]:
            report["overall_status"] = "FAIL"
            report["errors"].extend(g4_res["errors"])
        report["unresolved_items"].extend(g4_res.get("unresolved", []))

        # G5: Evidence Fidelity
        g5_res = self.verify_g5_evidence_fidelity(entities)
        report["gates"]["G5_evidence_fidelity"] = g5_res
        if not g5_res["passed"]:
            report["overall_status"] = "FAIL"
            report["errors"].extend(g5_res["errors"])

        # G6: Deterministic Processing
        g6_res = self.verify_g6_deterministic_processing(entities)
        report["gates"]["G6_deterministic_processing"] = g6_res
        if not g6_res["passed"]:
            report["overall_status"] = "FAIL"
            report["errors"].extend(g6_res["errors"])

        # G7: Privacy Isolation
        g7_res = self.verify_g7_privacy_isolation(entities)
        report["gates"]["G7_privacy_isolation"] = g7_res
        if not g7_res["passed"]:
            report["overall_status"] = "FAIL"
            report["errors"].extend(g7_res["errors"])

        return report

    def verify_g1_source_integrity(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """G1: Verify source files and staged extractions match expected hashes."""
        errors = []
        conn = get_db_connection(self.db_path) if self.db_path.exists() else None

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

            if conn:
                src_rec = get_source_by_file_id(conn, file_id) or get_source_by_legacy_id(conn, legacy_id)
                if not src_rec:
                    errors.append(f"Source {legacy_id} ({file_id}) not found in SQLite sources table.")
                elif src_rec["content_sha256"] != source_sha:
                    errors.append(f"Source SHA mismatch for {legacy_id}: DB={src_rec['content_sha256']} vs Prov={source_sha}")

        if conn:
            conn.close()

        return {"passed": len(errors) == 0, "errors": errors, "sources_verified": len(checked_sources)}

    def verify_g2_structural_fidelity(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """G2: Verify sequential numbering, count consistency, and absence of unaccounted text loss."""
        errors = []
        warnings = []
        questions = entities["questions"]

        if not questions:
            errors.append("No questions found for structural validation.")
            return {"passed": False, "errors": errors, "warnings": warnings}

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

        # Check questions with unresolved prompts
        for q in questions:
            flags = q.get("quality_profile", {}).get("validation_flags", [])
            if "UNRESOLVED_QUESTION_PROMPT" in flags:
                warnings.append(f"Question {q.get('question_id')} has unresolved prompt.")

        return {"passed": len(errors) == 0, "errors": errors, "warnings": warnings}

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

        return {"passed": len(errors) == 0, "errors": errors, "entities_validated": total_checked}

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

        return {"passed": len(errors) == 0, "errors": errors, "unresolved": unresolved}

    def verify_g5_evidence_fidelity(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """G5: Verify evidence grounding and NOT GIVEN null quotation rule."""
        errors = []
        passages_by_id = {p["passage_id"]: p for p in entities["passages"]}

        for evid in entities["evidence"]:
            p_id = evid.get("passage_id")
            passage = passages_by_id.get(p_id)
            ev_type = evid.get("evidence_type")

            if ev_type == "insufficient_information_not_given":
                # Must NOT have verbatim quote or char offsets
                if evid.get("verbatim_quote") is not None:
                    errors.append(f"NOT GIVEN evidence {evid['evidence_id']} has non-null verbatim_quote.")
                if evid.get("char_start") is not None or evid.get("char_end") is not None:
                    errors.append(f"NOT GIVEN evidence {evid['evidence_id']} has non-null character offsets.")
                if not evid.get("missing_information_rationale"):
                    errors.append(f"NOT GIVEN evidence {evid['evidence_id']} missing information rationale.")
            elif ev_type in {"direct_support", "contradictory_evidence"}:
                quote = evid.get("verbatim_quote")
                c_start = evid.get("char_start")
                c_end = evid.get("char_end")

                if not quote:
                    errors.append(f"Evidence {evid['evidence_id']} ({ev_type}) missing verbatim_quote.")
                elif evid.get("exact_match_verified") is True:
                    if passage:
                        narrative = passage.get("narrative_text", "")
                        actual_span = narrative[c_start:c_end]
                        if actual_span != quote:
                            errors.append(f"Evidence span mismatch on {evid['evidence_id']}: span='{actual_span[:30]}' vs quote='{quote[:30]}'")

        return {"passed": len(errors) == 0, "errors": errors}

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

        for item in all_items:
            prov = item.get("_provenance", {})
            recorded_hash = prov.get("canonical_content_sha256")
            if not recorded_hash:
                continue

            computed = compute_canonical_content_hash(item)
            if computed != recorded_hash:
                item_id = item.get("test_id", item.get("question_id", item.get("answer_id", "unknown")))
                errors.append(f"Canonical hash mismatch on {item_id}: recorded={recorded_hash} vs computed={computed}")

        return {"passed": len(errors) == 0, "errors": errors}

    def verify_g7_privacy_isolation(self, entities: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """G7: Verify no private copyrighted text is exposed to public paths."""
        errors = []
        # Check if any private_copyrighted entities are saved outside private/
        for p in (REPO_ROOT / "data").rglob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                qp = data.get("quality_profile", {})
                if qp.get("publication_permission") == "private_copyrighted":
                    errors.append(f"Private copyrighted entity committed or stored under public data/: {p}")
            except Exception:
                pass

        return {"passed": len(errors) == 0, "errors": errors}
