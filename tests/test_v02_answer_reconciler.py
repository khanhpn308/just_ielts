"""Unit tests for AnswerReconciler and answer normalization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from jsonschema import Draft202012Validator
import pytest
from referencing import Registry, Resource

from harness.models.provenance import ProvenanceEnvelope
from harness.models.quality import QualityProfile
from harness.models.question_bank import IELTSQuestion
from harness.normalizers.answer_reconciler import (
    AnswerReconciler,
    normalize_answer_value,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v02"


@pytest.fixture(scope="module")
def answer_validator() -> Draft202012Validator:
    schemas = {}
    for p in SCHEMAS_DIR.glob("*.json"):
        with open(p, "r", encoding="utf-8") as f:
            schemas[p.name] = json.load(f)

    reg = Registry()
    for s_name, s_data in schemas.items():
        res = Resource.from_contents(s_data)
        reg = reg.with_resource(s_data["$id"], res)
        reg = reg.with_resource(s_name, res)

    return Draft202012Validator(schemas["answer.schema.json"], registry=reg)


def test_normalize_answer_value_booleans():
    assert normalize_answer_value("True") == ("TRUE", ["T"], [])
    assert normalize_answer_value("T") == ("TRUE", ["T"], [])
    assert normalize_answer_value("FALSE") == ("FALSE", ["F"], [])
    assert normalize_answer_value("f") == ("FALSE", ["F"], [])
    assert normalize_answer_value("Not Given") == ("NOT GIVEN", ["NG"], [])
    assert normalize_answer_value("NG") == ("NOT GIVEN", ["NG"], [])

    # NOT GIVEN must remain distinct from FALSE
    ng_val, _, _ = normalize_answer_value("NOT GIVEN")
    f_val, _, _ = normalize_answer_value("FALSE")
    assert ng_val != f_val


def test_normalize_answer_ocr_typo():
    val, alts, flags = normalize_answer_value("Fraudulant")
    assert val == "fraudulent"
    assert "Fraudulant" in alts
    assert "OCR_TYPO_CORRECTED" in flags


def test_normalize_empty_or_none():
    val, alts, flags = normalize_answer_value(None)
    assert val is None
    assert "MISSING_SOURCE_ANSWER_KEY" in flags

    val, alts, flags = normalize_answer_value("   ")
    assert val is None
    assert "MISSING_SOURCE_ANSWER_KEY" in flags


def test_reconciler_missing_and_orphan_keys(answer_validator):
    reconciler = AnswerReconciler()
    source_rec = {
        "file_id": "FILE-000000000003",
        "legacy_id": "SRC-997",
        "relative_path": "synthetic/key.pdf",
        "content_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }
    prov = ProvenanceEnvelope(
        source_file_id="FILE-000000000001",
        source_legacy_id="SRC-999",
        relative_path="synthetic/test.docx",
        source_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        processing_unit="document",
        unit_identifier="raw_document",
        raw_block_locator="para:1",
        extractor_adapter="docx",
        extractor_version="0.1.0",
        normalizer_version="0.2.0-b",
    )
    qp = QualityProfile(
        lifecycle_status="extracted",
        extraction_quality="complete_clean",
        source_fidelity="authoritative_official",
        answer_verification="authoritative_key",
        explanation_verification="source_provided",
        publication_permission="public_synthetic",
    )

    questions = [
        IELTSQuestion(
            question_id="Q-VOL99-01-RD-001",
            group_id="QG-VOL99-01-RD01-G01",
            question_number=1,
            question_type="true-false-not-given",
            prompt_text="Statement 1",
            quality_profile=qp,
            _provenance=prov,
        ),
        IELTSQuestion(
            question_id="Q-VOL99-01-RD-002",
            group_id="QG-VOL99-01-RD01-G01",
            question_number=2,
            question_type="true-false-not-given",
            prompt_text="Statement 2",
            quality_profile=qp,
            _provenance=prov,
        ),
    ]

    # Key map has Q1 (matched) and Q99 (orphan), missing Q2
    raw_keys = {
        1: {"raw_val": "TRUE", "source_ref": "Page 10, Q1"},
        99: {"raw_val": "FALSE", "source_ref": "Page 10, Q99"},
    }

    answers = reconciler.reconcile_answers(
        questions=questions,
        raw_key_map=raw_keys,
        source_record=source_rec,
        volume_code="VOL99",
        test_number=1,
        publication_permission="public_synthetic",
    )

    assert len(answers) == 3

    # Q1: Matched answer
    ans_1 = next(a for a in answers if a.answer_id == "ANS-VOL99-01-RD-001-KEY")
    assert ans_1.target_value == "TRUE"
    assert ans_1.question_id == "Q-VOL99-01-RD-001"
    answer_validator.validate(ans_1.model_dump(by_alias=True))

    # Q2: Missing answer
    ans_2 = next(a for a in answers if a.answer_id == "ANS-VOL99-01-RD-002-KEY")
    assert ans_2.target_value is None
    assert ans_2.quality_profile.answer_verification == "missing_key"
    assert ans_2.quality_profile.lifecycle_status == "review_required"
    assert "MISSING_SOURCE_ANSWER_KEY" in ans_2.quality_profile.validation_flags
    answer_validator.validate(ans_2.model_dump(by_alias=True))

    # Q99: Orphan answer
    ans_orphan = next(a for a in answers if a.answer_id == "ANS-VOL99-01-RD-099-KEY")
    assert ans_orphan.question_id is None
    assert ans_orphan.target_value == "FALSE"
    assert ans_orphan.quality_profile.lifecycle_status == "review_required"
    assert "ORPHAN_ANSWER_KEY_UNLINKED" in ans_orphan.quality_profile.validation_flags
    answer_validator.validate(ans_orphan.model_dump(by_alias=True))
