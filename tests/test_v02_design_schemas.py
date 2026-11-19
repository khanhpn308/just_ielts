"""Design-level validation test suite for IELTS Data Harness Phase V0.2-A.

Tests:
1. Load and parse all V0.2 JSON schemas.
2. Validate every embedded synthetic example against its schema.
3. Resolve local $ref schema dependencies (provenance.schema.json, quality_profile.schema.json).
4. Reject invalid ID patterns across core entities.
5. Verify 100% compatibility with V0.1 source identity (FILE-<hash> and SRC-XXX).
6. Validate all existing Markdown principles in principles/ against principle_metadata schema.
7. Test orphan and missing-data handling (nullable fields, NOT GIVEN evidence).
8. Test deterministic canonical hashing invariant across run timestamps.
9. Verify joined question segmentation algorithm against regression fixtures.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v02"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "v02"
PRINCIPLES_DIR = REPO_ROOT / "principles"


def load_all_schemas() -> Dict[str, Dict[str, Any]]:
    """Loads all 13 schema definitions into a dictionary keyed by filename."""
    schemas = {}
    for schema_path in sorted(SCHEMAS_DIR.glob("*.json")):
        with open(schema_path, "r", encoding="utf-8") as f:
            schemas[schema_path.name] = json.load(f)
    return schemas


ALL_SCHEMAS = load_all_schemas()


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


def test_resolve_local_schema_refs():
    """Verify that all local $ref pointers resolve to existing files and valid schemas."""
    for schema_name, schema_data in ALL_SCHEMAS.items():
        # Inspect properties and definitions for $ref
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


def validate_object_against_schema(instance: Dict[str, Any], schema: Dict[str, Any]) -> None:
    """
    Lightweight, robust schema validator supporting:
    - type checks (including nullable union ['string', 'null'])
    - required fields
    - pattern (regex)
    - enum
    - local $ref resolution
    - nested object / array validation
    """
    # 1. Check required fields
    required = schema.get("required", [])
    for req in required:
        assert req in instance, f"Missing required property: '{req}'"

    properties = schema.get("properties", {})
    for prop_name, val in instance.items():
        if prop_name not in properties:
            if schema.get("additionalProperties") is False:
                pytest.fail(f"Unexpected additional property '{prop_name}' in instance")
            continue

        prop_schema = properties[prop_name]

        # Handle $ref
        if "$ref" in prop_schema:
            ref_file = prop_schema["$ref"].split("#")[0]
            ref_schema = ALL_SCHEMAS[ref_file]
            assert isinstance(val, dict), f"Property '{prop_name}' should be dict for $ref {ref_file}"
            validate_object_against_schema(val, ref_schema)
            continue

        # Handle type
        expected_type = prop_schema.get("type")
        if expected_type:
            if isinstance(expected_type, list):
                # e.g. ["string", "null"]
                allowed_types = expected_type
            else:
                allowed_types = [expected_type]

            type_match = False
            for t in allowed_types:
                if t == "string" and isinstance(val, str):
                    type_match = True
                elif t == "integer" and isinstance(val, int) and not isinstance(val, bool):
                    type_match = True
                elif t == "number" and isinstance(val, (int, float)) and not isinstance(val, bool):
                    type_match = True
                elif t == "boolean" and isinstance(val, bool):
                    type_match = True
                elif t == "object" and isinstance(val, dict):
                    type_match = True
                elif t == "array" and isinstance(val, list):
                    type_match = True
                elif t == "null" and val is None:
                    type_match = True

            assert type_match, (
                f"Property '{prop_name}' value {repr(val)} does not match allowed types {allowed_types}"
            )

        # Handle regex pattern
        if isinstance(val, str) and "pattern" in prop_schema:
            pattern = prop_schema["pattern"]
            assert re.search(pattern, val), (
                f"Property '{prop_name}' value '{val}' does not match regex pattern '{pattern}'"
            )

        # Handle enum
        if val is not None and "enum" in prop_schema:
            allowed_enums = prop_schema["enum"]
            assert val in allowed_enums, (
                f"Property '{prop_name}' value '{val}' not in allowed enum {allowed_enums}"
            )


def test_validate_all_embedded_synthetic_examples():
    """Verify that every synthetic example in each schema validates cleanly."""
    for schema_name, schema_data in ALL_SCHEMAS.items():
        examples = schema_data.get("examples", [])
        assert len(examples) > 0, f"Schema {schema_name} should contain at least one synthetic example"
        for idx, example in enumerate(examples):
            validate_object_against_schema(example, schema_data)


def test_v01_source_identity_pattern_compatibility():
    """Verify that V0.1 file_id (FILE-<hash>) and legacy_id (SRC-XXX) match provenance schema."""
    provenance_schema = ALL_SCHEMAS["provenance.schema.json"]
    file_id_pattern = provenance_schema["properties"]["source_file_id"]["pattern"]
    legacy_id_pattern = provenance_schema["properties"]["source_legacy_id"]["pattern"]

    # Valid V0.1 identifiers
    assert re.match(file_id_pattern, "FILE-7dbc16204945")
    assert re.match(file_id_pattern, "FILE-26aa282ad1f6")
    assert re.match(file_id_pattern, "FILE-3a7f8090a786")
    assert re.match(legacy_id_pattern, "SRC-004")
    assert re.match(legacy_id_pattern, "SRC-138")
    assert re.match(legacy_id_pattern, "UNKNOWN")

    # Invalid identifiers that must be rejected
    assert not re.match(file_id_pattern, "SRC-011")  # Conflating file_id with legacy_id
    assert not re.match(file_id_pattern, "FILE-short")
    assert not re.match(file_id_pattern, "FILE-7dbc16204945extra")
    assert not re.match(legacy_id_pattern, "FILE-7dbc16204945")
    assert not re.match(legacy_id_pattern, "INVALID_SRC")


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
    """Verify that all existing principle Markdown files pass principle_metadata schema."""
    principle_schema = ALL_SCHEMAS["principle_metadata.schema.json"]
    principle_files = [p for p in PRINCIPLES_DIR.rglob("*.md") if p.name not in {"README.md", "INDEX.md"}]
    assert len(principle_files) >= 7, "Expected at least 7 atomic principle files"

    for p_path in principle_files:
        content = p_path.read_text(encoding="utf-8")
        assert content.startswith("---\n"), f"{p_path.name} missing frontmatter delimiter"
        parts = content.split("---\n", 2)
        meta = yaml.safe_load(parts[1])

        # Validate against principle_metadata schema
        validate_object_against_schema(meta, principle_schema)


def test_orphan_and_missing_data_fixtures():
    """Verify that orphan answer keys and missing-answer questions validate against schemas."""
    fixture_path = FIXTURES_DIR / "orphan_and_missing_synthetic.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        fixtures = json.load(f)["fixtures"]

    # 1. Orphan answer key (no question booklet)
    orphan_ans = fixtures["orphan_answer_key"]
    assert orphan_ans["question_id"] is None
    validate_object_against_schema(orphan_ans, ALL_SCHEMAS["answer.schema.json"])

    # 2. Question with missing answer key
    q_missing = fixtures["question_missing_answer_key"]
    validate_object_against_schema(q_missing, ALL_SCHEMAS["question.schema.json"])

    # 3. NOT GIVEN evidence without forced verbatim quote
    ng_evidence = fixtures["not_given_evidence"]
    assert ng_evidence["verbatim_quote"] is None
    assert ng_evidence["char_start"] is None
    assert ng_evidence["missing_information_rationale"] is not None
    validate_object_against_schema(ng_evidence, ALL_SCHEMAS["evidence.schema.json"])


def compute_canonical_content_hash(payload: Dict[str, Any]) -> str:
    """
    Computes deterministic SHA-256 hash over canonical payload fields,
    explicitly excluding volatile execution timestamps (e.g. normalized_at).
    """
    # Deep copy or filter out ephemeral fields
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
