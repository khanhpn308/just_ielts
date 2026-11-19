"""Unit tests for EvidenceResolver and explanation normalization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from jsonschema import Draft202012Validator
import pytest
from referencing import Registry, Resource

from harness.models.provenance import ProvenanceEnvelope
from harness.models.quality import QualityProfile
from harness.models.question_bank import (
    IELTSAnswer,
    IELTSQuestion,
    ParagraphItem,
    PassageOrSection,
)
from harness.normalizers.evidence_resolver import (
    EvidenceResolver,
    find_exact_quote,
    find_fuzzy_quote,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v02"


@pytest.fixture(scope="module")
def schema_registry() -> Dict[str, Any]:
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


@pytest.fixture
def synthetic_passage() -> PassageOrSection:
    text = (
        "Synthetic polymers were first engineered during the early twentieth century as laboratory curiosities before transforming global industrial manufacturing and material science. "
        "These initial formulations lacked elasticity and fractured easily under sudden mechanical pressure. "
        "Early chemical researchers synthesized bakelite and nylon, establishing molecular bonding principles that enabled durable consumer goods. "
        "By mid-century, polymer manufacturing expanded rapidly across packaging, aerospace, and biomedical applications."
    )
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
    return PassageOrSection(
        passage_id="PASSAGE-VOL99-01-RD01",
        test_id="TEST-IELTS-VOL99-01-ACAD",
        skill="reading",
        sequence_number=1,
        title="History of Synthetic Materials",
        narrative_text=text,
        paragraphs=[
            ParagraphItem(
                label="A",
                sequence_index=0,
                char_start=0,
                char_end=len(text),
                text=text,
            )
        ],
        word_count=len(text.split()),
        quality_profile=qp,
        _provenance=prov,
    )


def test_find_exact_and_fuzzy_quotes(synthetic_passage):
    quote = "These initial formulations lacked elasticity and fractured easily under sudden mechanical pressure."
    exact = find_exact_quote(quote, synthetic_passage.narrative_text)
    assert exact is not None
    start, end = exact
    assert synthetic_passage.narrative_text[start:end] == quote

    # Fuzzy match with slight OCR noise
    noisy_quote = "These initial formulations lacked elasticity and fractured easily under sudden mechanlcal pressure."
    fuzzy = find_fuzzy_quote(noisy_quote, synthetic_passage.narrative_text, min_ratio=0.85)
    assert fuzzy is not None
    f_start, f_end, ratio, matched = fuzzy
    assert ratio > 0.95


def test_resolve_evidence_exact_support(synthetic_passage, schema_registry):
    resolver = EvidenceResolver()
    ans_qp = QualityProfile(
        lifecycle_status="reviewed",
        extraction_quality="complete_clean",
        source_fidelity="authoritative_official",
        answer_verification="authoritative_key",
        explanation_verification="source_provided",
        publication_permission="public_synthetic",
    )
    ans = IELTSAnswer(
        answer_id="ANS-VOL99-01-RD-001-KEY",
        question_id="Q-VOL99-01-RD-001",
        target_value="TRUE",
        acceptable_alternates=["T"],
        source_key_ref="Page 1",
        quality_profile=ans_qp,
        _provenance=synthetic_passage.provenance,
    )

    quote = "These initial formulations lacked elasticity and fractured easily under sudden mechanical pressure."
    evid = resolver.resolve_evidence(
        evidence_id="EVID-VOL99-01-RD-001-01",
        answer=ans,
        passage=synthetic_passage,
        evidence_type="direct_support",
        candidate_quote=quote,
        paragraph_label="A",
        publication_permission="public_synthetic",
    )

    assert evid.exact_match_verified is True
    assert evid.char_start is not None
    assert evid.char_end is not None
    assert synthetic_passage.narrative_text[evid.char_start:evid.char_end] == quote

    # Validate against evidence.schema.json
    val = Draft202012Validator(
        schema_registry["schemas"]["evidence.schema.json"],
        registry=schema_registry["registry"],
    )
    val.validate(evid.model_dump(by_alias=True))


def test_resolve_evidence_not_given(synthetic_passage, schema_registry):
    resolver = EvidenceResolver()
    ans_qp = QualityProfile(
        lifecycle_status="reviewed",
        extraction_quality="complete_clean",
        source_fidelity="authoritative_official",
        answer_verification="authoritative_key",
        explanation_verification="source_provided",
        publication_permission="public_synthetic",
    )
    ans = IELTSAnswer(
        answer_id="ANS-VOL99-01-RD-003-KEY",
        question_id="Q-VOL99-01-RD-003",
        target_value="NOT GIVEN",
        acceptable_alternates=["NG"],
        source_key_ref="Page 1",
        quality_profile=ans_qp,
        _provenance=synthetic_passage.provenance,
    )

    rationale = "The passage does not state whether initial formulation research costs exceeded expectations."
    evid = resolver.resolve_evidence(
        evidence_id="EVID-VOL99-01-RD-003-01",
        answer=ans,
        passage=synthetic_passage,
        evidence_type="insufficient_information_not_given",
        candidate_quote=None,
        paragraph_label="A",
        missing_information_rationale=rationale,
        publication_permission="public_synthetic",
    )

    assert evid.verbatim_quote is None
    assert evid.char_start is None
    assert evid.char_end is None
    assert evid.exact_match_verified is False
    assert evid.missing_information_rationale == rationale

    # Validate schema
    val = Draft202012Validator(
        schema_registry["schemas"]["evidence.schema.json"],
        registry=schema_registry["registry"],
    )
    val.validate(evid.model_dump(by_alias=True))


def test_resolve_explanation(synthetic_passage, schema_registry):
    resolver = EvidenceResolver()
    q_qp = QualityProfile(
        lifecycle_status="extracted",
        extraction_quality="complete_clean",
        source_fidelity="authoritative_official",
        answer_verification="authoritative_key",
        explanation_verification="source_provided",
        publication_permission="public_synthetic",
    )
    question = IELTSQuestion(
        question_id="Q-VOL99-01-RD-001",
        group_id="QG-VOL99-01-RD01-G01",
        question_number=1,
        question_type="true-false-not-given",
        prompt_text="Early synthetic polymers were more brittle than modern alternatives.",
        quality_profile=q_qp,
        _provenance=synthetic_passage.provenance,
    )

    expl = resolver.resolve_explanation(
        explanation_id="EXPL-VOL99-01-RD-001",
        question=question,
        answer=None,
        evidence=None,
        rationale_en="Paragraph A explicitly mentions that early formulations fractured easily.",
        rationale_vi="Đoạn A nêu rõ các công thức đời đầu dễ nứt gãy.",
        paraphrase_map=[{"prompt_term": "more brittle", "passage_term": "fractured easily"}],
        author_type="source_published",
        publication_permission="public_synthetic",
    )

    assert expl.rationale_en is not None
    assert len(expl.paraphrase_map) == 1
    assert expl.paraphrase_map[0].prompt_term == "more brittle"

    # Validate against explanation.schema.json
    val = Draft202012Validator(
        schema_registry["schemas"]["explanation.schema.json"],
        registry=schema_registry["registry"],
    )
    val.validate(expl.model_dump(by_alias=True))
