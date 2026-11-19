"""Unit and integration tests for V0.2 Pydantic data models and base normalizer engine."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict

from jsonschema import Draft202012Validator
from pydantic import ValidationError
import pytest
from referencing import Registry, Resource

from harness.models.provenance import ProvenanceEnvelope
from harness.models.quality import QualityProfile
from harness.models.question_bank import (
    IELTSAnswer,
    IELTSEvidence,
    IELTSExplanation,
    IELTSQuestion,
    IELTSTest,
    PassageOrSection,
    QuestionGroup,
)
from harness.normalizers.base import (
    BaseNormalizer,
    atomic_write_json,
    compute_canonical_content_hash,
    serialize_canonical_json,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v02"


@pytest.fixture(scope="module")
def schema_registry() -> Dict[str, Any]:
    """Loads all schemas into memory and builds referencing registry."""
    schemas = {}
    for p in SCHEMAS_DIR.glob("*.json"):
        with open(p, "r", encoding="utf-8") as f:
            schemas[p.name] = json.load(f)

    reg = Registry()
    for s_name, s_data in schemas.items():
        res = Resource.from_contents(s_data)
        reg = reg.with_resource(s_data["$id"], res)
        reg = reg.with_resource(s_name, res)
    return {"schemas": schemas, "registry": reg}


def validate_with_jsonschema(schema_name: str, instance: Dict[str, Any], registry_fixture: Dict[str, Any]) -> None:
    schema = registry_fixture["schemas"][schema_name]
    val = Draft202012Validator(schema, registry=registry_fixture["registry"])
    val.validate(instance)


def test_provenance_envelope_valid(schema_registry):
    example = schema_registry["schemas"]["provenance.schema.json"]["examples"][0]
    model = ProvenanceEnvelope(**example)
    dumped = model.model_dump()
    assert dumped["source_file_id"] == "FILE-000000000001"
    assert dumped["schema_version"] == "v0.2.0-normalized"
    validate_with_jsonschema("provenance.schema.json", dumped, schema_registry)


def test_provenance_envelope_invalid_patterns():
    with pytest.raises(ValidationError):
        ProvenanceEnvelope(
            schema_version="v0.2.0-normalized",
            source_file_id="SRC-138",  # invalid pattern for source_file_id
            source_legacy_id="SRC-138",
            relative_path="sample.docx",
            source_sha256="772566bcc5c7d31d3914f68df5952ed78abc3b65c4732b3c80bbbcbba0a0add3",
            processing_unit="document",
            unit_identifier="raw_document",
            raw_block_locator="para:0",
            extractor_adapter="docx",
            extractor_version="0.1.0",
            normalizer_version="0.2.0",
        )

    with pytest.raises(ValidationError):
        ProvenanceEnvelope(
            schema_version="v0.2.0-normalized",
            source_file_id="FILE-5a2cce4d0793",
            source_legacy_id="INVALID_SRC_ID",  # invalid legacy_id
            relative_path="sample.docx",
            source_sha256="772566bcc5c7d31d3914f68df5952ed78abc3b65c4732b3c80bbbcbba0a0add3",
            processing_unit="document",
            unit_identifier="raw_document",
            raw_block_locator="para:0",
            extractor_adapter="docx",
            extractor_version="0.1.0",
            normalizer_version="0.2.0",
        )


def test_quality_profile_model(schema_registry):
    example = schema_registry["schemas"]["quality_profile.schema.json"]["examples"][0]
    model = QualityProfile(**example)
    dumped = model.model_dump()
    assert dumped["lifecycle_status"] == "reviewed"
    assert dumped["validation_flags"] == []
    validate_with_jsonschema("quality_profile.schema.json", dumped, schema_registry)

    # Invalid enum rejection
    bad_data = copy.deepcopy(example)
    bad_data["lifecycle_status"] = "unknown_status"
    with pytest.raises(ValidationError):
        QualityProfile(**bad_data)


def test_test_model(schema_registry):
    example = schema_registry["schemas"]["test.schema.json"]["examples"][0]
    model = IELTSTest(**example)
    dumped = model.model_dump(by_alias=True)
    assert dumped["test_id"] == "TEST-IELTS-VOL99-01-ACAD"
    assert "_provenance" in dumped
    validate_with_jsonschema("test.schema.json", dumped, schema_registry)


def test_passage_or_section_model(schema_registry):
    example = schema_registry["schemas"]["passage_section.schema.json"]["examples"][0]
    model = PassageOrSection(**example)
    dumped = model.model_dump(by_alias=True)
    assert dumped["passage_id"] == "PASSAGE-VOL99-01-RD01"
    validate_with_jsonschema("passage_section.schema.json", dumped, schema_registry)


def test_question_group_model(schema_registry):
    example = schema_registry["schemas"]["question_group.schema.json"]["examples"][0]
    model = QuestionGroup(**example)
    dumped = model.model_dump(by_alias=True)
    assert dumped["group_id"] == "QG-VOL99-01-RD01-G01"
    validate_with_jsonschema("question_group.schema.json", dumped, schema_registry)


def test_question_model(schema_registry):
    example = schema_registry["schemas"]["question.schema.json"]["examples"][0]
    model = IELTSQuestion(**example)
    dumped = model.model_dump(by_alias=True)
    assert dumped["question_id"] == "Q-VOL99-01-RD-001"
    validate_with_jsonschema("question.schema.json", dumped, schema_registry)


def test_answer_model(schema_registry):
    for example in schema_registry["schemas"]["answer.schema.json"]["examples"]:
        model = IELTSAnswer(**example)
        dumped = model.model_dump(by_alias=True)
        assert dumped["answer_id"] == "ANS-VOL99-01-RD-001-KEY"
        validate_with_jsonschema("answer.schema.json", dumped, schema_registry)


def test_evidence_model(schema_registry):
    for example in schema_registry["schemas"]["evidence.schema.json"]["examples"]:
        model = IELTSEvidence(**example)
        dumped = model.model_dump(by_alias=True)
        validate_with_jsonschema("evidence.schema.json", dumped, schema_registry)


def test_explanation_model(schema_registry):
    example = schema_registry["schemas"]["explanation.schema.json"]["examples"][0]
    model = IELTSExplanation(**example)
    dumped = model.model_dump(by_alias=True)
    assert dumped["explanation_id"] == "EXPL-VOL99-01-RD-001"
    validate_with_jsonschema("explanation.schema.json", dumped, schema_registry)


def test_canonical_content_hashing_determinism():
    payload_a = {
        "id": "Q-001",
        "prompt": "Sample text",
        "_provenance": {
            "source_file_id": "FILE-5a2cce4d0793",
            "canonical_content_sha256": None,
            "normalized_at": "2026-11-19T10:00:00Z",
        },
    }
    payload_b = {
        "id": "Q-001",
        "prompt": "Sample text",
        "_provenance": {
            "source_file_id": "FILE-5a2cce4d0793",
            "canonical_content_sha256": "any_old_hash_value",
            "normalized_at": "2026-11-20T18:30:00Z",
        },
    }

    hash_a = compute_canonical_content_hash(payload_a)
    hash_b = compute_canonical_content_hash(payload_b)
    assert hash_a == hash_b, "Canonical content hashes must be identical regardless of normalized_at"


def test_atomic_write_json(tmp_path: Path):
    target = tmp_path / "subdir" / "test_entity.json"
    data = {"name": "test", "items": [1, 2, 3]}
    atomic_write_json(target, data)

    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert content.endswith("\n")
    assert json.loads(content) == data


def test_finalize_and_hash_entity():
    prov = ProvenanceEnvelope(
        source_file_id="FILE-5a2cce4d0793",
        source_legacy_id="SRC-138",
        relative_path="private/raw/VOL 6/READING/VOL 6.docx",
        source_sha256="772566bcc5c7d31d3914f68df5952ed78abc3b65c4732b3c80bbbcbba0a0add3",
        processing_unit="document",
        unit_identifier="raw_document",
        raw_block_locator="para:0",
        extractor_adapter="docx",
        extractor_version="0.1.0-lxml-docx",
        normalizer_version="0.2.0-b",
    )
    qp = QualityProfile(
        lifecycle_status="extracted",
        extraction_quality="complete_clean",
        source_fidelity="authoritative_official",
        answer_verification="authoritative_key",
        explanation_verification="source_provided",
        publication_permission="private_copyrighted",
    )
    ans = IELTSAnswer(
        answer_id="ANS-VOL06-05-RD-002-KEY",
        question_id="Q-VOL06-05-RD-002",
        target_value="FALSE",
        acceptable_alternates=["F"],
        case_sensitive=False,
        source_key_ref="Page 95",
        quality_profile=qp,
        provenance=prov,
    )
    finalized = BaseNormalizer.finalize_and_hash_entity(ans)
    assert finalized["_provenance"]["canonical_content_sha256"] is not None
    assert len(finalized["_provenance"]["canonical_content_sha256"]) == 64
