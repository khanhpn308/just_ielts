"""Design-level validation test suite for IELTS Data Harness Phase V0.2-A.

Standards-compliant testing using JSON Schema Draft 2020-12 (jsonschema + referencing):
1. Load and parse all V0.2 JSON schemas.
2. Validate Draft 2020-12 meta-schema conformance (check_schema).
3. Resolve local $ref schema dependencies (provenance.schema.json, quality_profile.schema.json).
4. Validate every embedded synthetic example against its schema via Draft202012Validator.
5. Verify boundary constraints: minLength/maxLength, minimum/maximum, minItems/maxItems.
6. Verify additionalProperties: false rejects undeclared properties.
7. Verify required and nullable field constraints.
8. Verify 100% compatibility with V0.1 source identity (FILE-<hash> and SRC-XXX).
9. Verify real source ID mappings locally against SQLite database when present.
10. Reject invalid ID patterns across core entities.
11. Validate all existing Markdown principles in principles/ against principle_metadata schema.
12. Test orphan and missing-data handling (nullable fields, NOT GIVEN evidence).
13. Test deterministic canonical hashing invariant across run timestamps.
14. Verify joined question segmentation algorithm against regression fixtures.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
import pytest
from referencing import Registry, Resource
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v02"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "v02"
PRINCIPLES_DIR = REPO_ROOT / "principles"
HARNESS_DB_PATH = REPO_ROOT / "harness" / "state" / "harness.db"


def load_all_schemas() -> Dict[str, Dict[str, Any]]:
    """Loads all 13 schema definitions into a dictionary keyed by filename."""
    schemas = {}
    for schema_path in sorted(SCHEMAS_DIR.glob("*.json")):
        with open(schema_path, "r", encoding="utf-8") as f:
            schemas[schema_path.name] = json.load(f)
    return schemas


ALL_SCHEMAS = load_all_schemas()


def build_schema_registry(schemas: Dict[str, Dict[str, Any]]) -> Registry:
    """Builds a referencing.Registry to resolve local $ref pointers across schemas."""
    registry = Registry()
    for name, schema_dict in schemas.items():
        res = Resource.from_contents(schema_dict)
        registry = registry.with_resource(name, res)
        if "$id" in schema_dict:
            registry = registry.with_resource(schema_dict["$id"], res)
    return registry


SCHEMA_REGISTRY = build_schema_registry(ALL_SCHEMAS)


def get_validator(schema_name: str) -> Draft202012Validator:
    """Returns a Draft202012Validator bound to the shared schema registry."""
    return Draft202012Validator(ALL_SCHEMAS[schema_name], registry=SCHEMA_REGISTRY)


def test_schema_inventory():
    """Verify all 13 required V0.2 schemas exist and load without syntax errors."""
    expected_schemas = {
        "provenance.schema.json",
        "quality_profile.schema.json",
        "test.schema.json",
        "passage_section.schema.json",
        "question_group.schema.json",
        "question.schema.json",
        "answer.schema.json",
        "evidence.schema.json",
        "explanation.schema.json",
        "principle_metadata.schema.json",
        "writing_task.schema.json",
        "speaking_task.schema.json",
        "vocabulary_item.schema.json",
    }
    loaded_names = set(ALL_SCHEMAS.keys())
    assert expected_schemas.issubset(loaded_names), f"Missing schemas: {expected_schemas - loaded_names}"
    assert len(loaded_names) == 13


def test_schema_draft_2020_12_conformance():
    """Verify that all 13 schemas conform strictly to JSON Schema Draft 2020-12 meta-schema."""
    for schema_name, schema_data in ALL_SCHEMAS.items():
        Draft202012Validator.check_schema(schema_data)


def test_resolve_local_schema_refs():
    """Verify that all local $ref pointers resolve to existing files and schemas."""
    for schema_name, schema_data in ALL_SCHEMAS.items():
        def find_refs(node: Any, path: str = ""):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "$ref":
                        target_filename = v.split("#")[0]
                        assert (SCHEMAS_DIR / target_filename).is_file(), (
                            f"Unresolved $ref '{v}' found in {schema_name} at {path}"
                        )
                        assert target_filename in ALL_SCHEMAS
                    else:
                        find_refs(v, f"{path}.{k}" if path else k)
            elif isinstance(node, list):
                for i, elem in enumerate(node):
                    find_refs(elem, f"{path}[{i}]")

        find_refs(schema_data)


def test_validate_all_embedded_synthetic_examples_standard():
    """Verify every synthetic example in each schema validates cleanly with Draft202012Validator."""
    for schema_name, schema_data in ALL_SCHEMAS.items():
        validator = get_validator(schema_name)
        examples = schema_data.get("examples", [])
        assert len(examples) > 0, f"Schema {schema_name} should contain at least one synthetic example"
        for idx, example in enumerate(examples):
            validator.validate(example)


def test_schema_constraints_min_max_length():
    """Verify Draft 2020-12 validator enforces minLength and maxLength constraints."""
    passage_val = get_validator("passage_section.schema.json")
    passage_ex = copy.deepcopy(ALL_SCHEMAS["passage_section.schema.json"]["examples"][0])

    # Valid passage passes
    passage_val.validate(passage_ex)

    # Narrative text < 100 characters must fail minLength: 100
    passage_short = copy.deepcopy(passage_ex)
    passage_short["narrative_text"] = "Too short text under 100 characters."
    with pytest.raises(ValidationError):
        passage_val.validate(passage_short)

    # Test title < 3 characters must fail minLength: 3
    test_val = get_validator("test.schema.json")
    test_ex = copy.deepcopy(ALL_SCHEMAS["test.schema.json"]["examples"][0])
    test_ex["title"] = "AB"
    with pytest.raises(ValidationError):
        test_val.validate(test_ex)


def test_schema_constraints_min_max_numerical():
    """Verify Draft 2020-12 validator enforces minimum and maximum integer constraints."""
    q_val = get_validator("question.schema.json")
    q_ex = copy.deepcopy(ALL_SCHEMAS["question.schema.json"]["examples"][0])

    # Minimum: 1 (0 is invalid)
    q_0 = copy.deepcopy(q_ex)
    q_0["question_number"] = 0
    with pytest.raises(ValidationError):
        q_val.validate(q_0)

    # Maximum: 40 (41 is invalid)
    q_41 = copy.deepcopy(q_ex)
    q_41["question_number"] = 41
    with pytest.raises(ValidationError):
        q_val.validate(q_41)

    # In range 1..40 passes
    for n in (1, 20, 40):
        q_valid = copy.deepcopy(q_ex)
        q_valid["question_number"] = n
        q_val.validate(q_valid)


def test_schema_constraints_min_items():
    """Verify Draft 2020-12 validator enforces minItems array constraints."""
    qg_val = get_validator("question_group.schema.json")
    qg_ex = copy.deepcopy(ALL_SCHEMAS["question_group.schema.json"]["examples"][0])

    # shared_options minItems: 2. Single item must fail
    qg_single = copy.deepcopy(qg_ex)
    qg_single["shared_options"] = ["A. Only one option"]
    with pytest.raises(ValidationError):
        qg_val.validate(qg_single)


def test_schema_constraints_additional_properties_false():
    """Verify Draft 2020-12 validator rejects undeclared properties when additionalProperties is false."""
    for schema_name in ["question.schema.json", "answer.schema.json", "evidence.schema.json"]:
        val = get_validator(schema_name)
        ex = copy.deepcopy(ALL_SCHEMAS[schema_name]["examples"][0])
        ex["undeclared_injected_property_123"] = "prohibited"
        with pytest.raises(ValidationError):
            val.validate(ex)


def test_schema_constraints_required_and_nullable():
    """Verify required vs nullable field enforcement."""
    # Required field missing
    t_val = get_validator("test.schema.json")
    t_ex = copy.deepcopy(ALL_SCHEMAS["test.schema.json"]["examples"][0])
    del t_ex["test_id"]
    with pytest.raises(ValidationError):
        t_val.validate(t_ex)

    # Non-nullable required field set to null
    t_ex_null = copy.deepcopy(ALL_SCHEMAS["test.schema.json"]["examples"][0])
    t_ex_null["test_id"] = None
    with pytest.raises(ValidationError):
        t_val.validate(t_ex_null)

    # Nullable question_id in answer.schema.json (orphan answer key) passes
    ans_val = get_validator("answer.schema.json")
    ans_ex = copy.deepcopy(ALL_SCHEMAS["answer.schema.json"]["examples"][0])
    ans_ex["question_id"] = None
    ans_val.validate(ans_ex)

    # Nullable verbatim_quote in evidence.schema.json for NOT GIVEN passes
    evid_val = get_validator("evidence.schema.json")
    evid_ex = copy.deepcopy(ALL_SCHEMAS["evidence.schema.json"]["examples"][0])
    evid_ex["verbatim_quote"] = None
    evid_ex["char_start"] = None
    evid_ex["char_end"] = None
    evid_ex["evidence_type"] = "insufficient_information_not_given"
    evid_ex["missing_information_rationale"] = "Information not found in passage."
    evid_val.validate(evid_ex)


def test_v01_source_identity_pattern_compatibility():
    """Verify that V0.1 file_id (FILE-<hash>) and legacy_id (SRC-XXX) match provenance schema."""
    provenance_schema = ALL_SCHEMAS["provenance.schema.json"]
    file_id_pattern = provenance_schema["properties"]["source_file_id"]["pattern"]
    legacy_id_pattern = provenance_schema["properties"]["source_legacy_id"]["pattern"]

    # Valid V0.1 identifiers
    assert re.match(file_id_pattern, "FILE-7dbc16204945")
    assert re.match(file_id_pattern, "FILE-26aa282ad1f6")
    assert re.match(file_id_pattern, "FILE-5a2cce4d0793")
    assert re.match(legacy_id_pattern, "SRC-004")
    assert re.match(legacy_id_pattern, "SRC-138")
    assert re.match(legacy_id_pattern, "UNKNOWN")

    # Invalid identifiers that must be rejected
    assert not re.match(file_id_pattern, "SRC-011")  # Conflating file_id with legacy_id
    assert not re.match(file_id_pattern, "FILE-short")
    assert not re.match(file_id_pattern, "FILE-7dbc16204945extra")
    assert not re.match(legacy_id_pattern, "FILE-7dbc16204945")
    assert not re.match(legacy_id_pattern, "INVALID_SRC")


def test_local_sqlite_source_id_mappings():
    """Verify real source ID mappings locally against SQLite database when present."""
    if not HARNESS_DB_PATH.exists():
        pytest.skip(f"Local harness database not present at {HARNESS_DB_PATH}")

    import sqlite3
    from harness.inventory import compute_file_id

    conn = sqlite3.connect(HARNESS_DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    pilot_legacy_ids = [
        "SRC-004", "SRC-008", "SRC-011", "SRC-012",
        "SRC-077", "SRC-079", "SRC-137", "SRC-138", "SRC-151",
    ]
    cur.execute(
        "SELECT file_id, legacy_id, relative_path, content_sha256 FROM sources WHERE legacy_id IN ({})".format(
            ",".join("?" for _ in pilot_legacy_ids)
        ),
        pilot_legacy_ids,
    )
    rows = {r["legacy_id"]: dict(r) for r in cur.fetchall()}

    for leg_id in pilot_legacy_ids:
        assert leg_id in rows, f"Legacy source {leg_id} missing from SQLite sources table"
        rec = rows[leg_id]
        expected_file_id = compute_file_id(rec["relative_path"])
        assert rec["file_id"] == expected_file_id, (
            f"file_id mismatch for {leg_id}: db={rec['file_id']}, expected={expected_file_id}"
        )
        assert re.match(r"^FILE-[a-f0-9]{12}$", rec["file_id"]), f"Invalid file_id pattern: {rec['file_id']}"
        assert re.match(r"^SRC-\d{3,4}$", rec["legacy_id"]), f"Invalid legacy_id pattern: {rec['legacy_id']}"
        assert len(rec["content_sha256"]) == 64, f"Invalid SHA-256 length for {leg_id}"
        assert re.match(r"^[a-f0-9]{64}$", rec["content_sha256"]), f"Invalid SHA-256 hex for {leg_id}"

    conn.close()


def test_reject_invalid_entity_id_patterns():
    """Verify that regex constraints reject malformed entity identifiers."""
    test_pattern = ALL_SCHEMAS["test.schema.json"]["properties"]["test_id"]["pattern"]
    assert re.match(test_pattern, "TEST-IELTS-VOL01-01-ACAD")
    assert re.match(test_pattern, "TEST-IELTS-VOL99-12-GT")
    assert not re.match(test_pattern, "TEST-01")
    assert not re.match(test_pattern, "TEST-IELTS-VOL01-01")  # Missing track
    assert not re.match(test_pattern, "test-ielts-vol01-01-acad")  # Lowercase

    q_pattern = ALL_SCHEMAS["question.schema.json"]["properties"]["question_id"]["pattern"]
    assert re.match(q_pattern, "Q-VOL01-01-RD-001")
    assert re.match(q_pattern, "Q-VOL06-05-LS-040")
    assert not re.match(q_pattern, "Q-001")
    assert not re.match(q_pattern, "QUESTION-VOL01-01-RD-001")

    ans_pattern = ALL_SCHEMAS["answer.schema.json"]["properties"]["answer_id"]["pattern"]
    assert re.match(ans_pattern, "ANS-VOL01-01-RD-001-KEY")
    assert re.match(ans_pattern, "ANS-VOL01-01-RD-001-ALT01")
    assert not re.match(ans_pattern, "ANS-001")

    evid_pattern = ALL_SCHEMAS["evidence.schema.json"]["properties"]["evidence_id"]["pattern"]
    assert re.match(evid_pattern, "EVID-VOL01-01-RD-001-01")
    assert not re.match(evid_pattern, "EVIDENCE-01")


def test_existing_principles_frontmatter_compatibility():
    """Verify that all existing principle Markdown files pass principle_metadata schema with Draft202012Validator."""
    principle_val = get_validator("principle_metadata.schema.json")
    principle_files = [p for p in PRINCIPLES_DIR.rglob("*.md") if p.name not in {"README.md", "INDEX.md"}]
    assert len(principle_files) >= 7, "Expected at least 7 atomic principle files"

    for p_path in principle_files:
        content = p_path.read_text(encoding="utf-8")
        assert content.startswith("---\n"), f"{p_path.name} missing frontmatter delimiter"
        parts = content.split("---\n", 2)
        meta = yaml.safe_load(parts[1])

        # Validate against principle_metadata schema
        principle_val.validate(meta)


def test_orphan_and_missing_data_fixtures():
    """Verify that orphan answer keys and missing-answer questions validate against schemas with Draft202012Validator."""
    fixture_path = FIXTURES_DIR / "orphan_and_missing_synthetic.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        fixtures = json.load(f)["fixtures"]

    # 1. Orphan answer key (no question booklet)
    orphan_ans = fixtures["orphan_answer_key"]
    assert orphan_ans["question_id"] is None
    get_validator("answer.schema.json").validate(orphan_ans)

    # 2. Question with missing answer key
    q_missing = fixtures["question_missing_answer_key"]
    get_validator("question.schema.json").validate(q_missing)

    # 3. NOT GIVEN evidence without forced verbatim quote
    ng_evidence = fixtures["not_given_evidence"]
    assert ng_evidence["verbatim_quote"] is None
    assert ng_evidence["char_start"] is None
    assert ng_evidence["missing_information_rationale"] is not None
    get_validator("evidence.schema.json").validate(ng_evidence)


def compute_canonical_content_hash(payload: Dict[str, Any]) -> str:
    """
    Computes deterministic SHA-256 hash over canonical payload fields,
    explicitly excluding volatile execution timestamps (e.g. normalized_at).
    """
    def filter_canonical(node: Any) -> Any:
        if isinstance(node, dict):
            filtered = {}
            for k, v in sorted(node.items()):
                if k in {"normalized_at", "canonical_content_sha256"}:
                    continue
                filtered[k] = filter_canonical(v)
            return filtered
        elif isinstance(node, list):
            return [filter_canonical(x) for x in node]
        return node

    canonical_obj = filter_canonical(payload)
    serialized = json.dumps(canonical_obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def test_deterministic_output_hashing_policy():
    """Verify that entities with identical data but differing timestamps produce identical hashes."""
    fixture_path = FIXTURES_DIR / "deterministic_hashing_synthetic.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    hash_run_1 = compute_canonical_content_hash(data["payload_run_1"])
    hash_run_2 = compute_canonical_content_hash(data["payload_run_2"])

    assert hash_run_1 == hash_run_2, "Canonical content hashes must be identical despite differing timestamps"


def segment_joined_questions(text: str, start_num: int, end_num: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Deterministic segmentation algorithm for concatenated DOCX question runs.
    Handles:
    - sentence.2 Next question (no space after period)
    - word2 Next question (no punctuation between word and digit)
    - Numbers within prompt text (e.g. 1980, 25 percent)
    Guarantees:
    - Exact question count and strictly contiguous numbering
    - Zero text loss (period attached to preceding sentence)
    - Unresolvable sequences routed to review
    Returns (parsed_questions, diagnostic_flags).
    """
    flags = []
    expected_numbers = list(range(start_num, end_num + 1))
    positions = []
    curr = 0

    for num in expected_numbers:
        pattern = rf"(?:^|[\.\?!a-zA-Z\s])({num})(?:[\.\s]*)(?=[A-Z])"
        match = re.search(pattern, text[curr:])
        if not match:
            flags.append("SEGMENTATION_SEQUENCE_GAP")
            return [], flags

        digit_start = curr + match.start(1)
        prompt_start = curr + match.end()
        positions.append((num, digit_start, prompt_start))
        curr = prompt_start

    res = []
    for i in range(len(positions)):
        num, _, prompt_start = positions[i]
        prompt_end = positions[i + 1][1] if i + 1 < len(positions) else len(text)
        prompt = text[prompt_start:prompt_end].strip()
        res.append({
            "number": num,
            "prompt": prompt
        })

    return res, flags


def test_joined_question_segmentation_fixtures():
    """Verify that joined DOCX question strings are segmented without text loss."""
    fixture_path = FIXTURES_DIR / "joined_questions_synthetic.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        fixtures = json.load(f)["fixtures"]

    for case in fixtures:
        start_n, end_n = case["expected_range"]
        input_text = case["input_text"]

        items, flags = segment_joined_questions(input_text, start_n, end_n)

        if case.get("should_fail_or_flag_review"):
            assert case["expected_flag"] in flags
        else:
            assert len(items) == case["expected_count"]
            for i, expected_item in enumerate(case["expected_items"]):
                assert items[i]["number"] == expected_item["number"]
                assert items[i]["prompt"] == expected_item["prompt"]
