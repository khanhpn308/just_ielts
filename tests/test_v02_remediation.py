"""Comprehensive regression and negative tests for V0.2-B Code Review Remediation.

Covers:
- P0: Dependency-Aware Checkpoints
- P0: Complete Manifest on Resume
- P0: Verified Answer Provenance
- P0: Evidence Provenance and Privacy
- P1: Quality Gate Integrity (G1 - G7 negative & positive tests)
- P1: Missing Prompt Handling
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict
import pytest

from harness.db import (
    get_db_connection,
    init_db,
    is_normalization_checkpoint_valid,
    upsert_normalization_checkpoint,
    upsert_source,
)
from harness.models.provenance import ProvenanceEnvelope
from harness.models.quality import QualityProfile
from harness.models.question_bank import (
    IELTSAnswer,
    IELTSEvidence,
    IELTSExplanation,
    IELTSQuestion,
    ParagraphItem,
    PassageOrSection,
    QuestionGroup,
    IELTSTest,
)
from harness.normalizers.answer_reconciler import AnswerReconciler
from harness.normalizers.base import BaseNormalizer, SCHEMA_VERSION, compute_canonical_content_hash
from harness.normalizers.evidence_resolver import EvidenceResolver
from harness.normalizers.reading_docx import DocxReadingNormalizer
from harness.orchestrator import NormalizationOrchestrator
from harness.verifier import QualityGateRunner

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures for Synthetic Testing
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_env(tmp_path: Path):
    """Sets up an isolated SQLite DB, raw staging directory, and output directory."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    raw_dir = tmp_path / "raw_staging"
    raw_dir.mkdir(parents=True)

    output_dir = tmp_path / "normalized"
    output_dir.mkdir(parents=True)

    conn = get_db_connection(db_path)
    upsert_source(
        conn,
        {
            "file_id": "FILE-000000000138",
            "legacy_id": "SRC-999",
            "relative_path": "synthetic/reading_test.docx",
            "filename": "reading_test.docx",
            "extension": ".docx",
            "detected_type": "openxml_word",
            "size_bytes": 1000,
            "content_sha256": "a" * 64,
            "collection": "synthetic",
            "duplicate_group": "none",
            "accessibility_status": "accessible",
        },
    )
    upsert_source(
        conn,
        {
            "file_id": "FILE-000000000137",
            "legacy_id": "SRC-998",
            "relative_path": "synthetic/explanation_key.pdf",
            "filename": "explanation_key.pdf",
            "extension": ".pdf",
            "detected_type": "pdf_digital",
            "size_bytes": 1000,
            "content_sha256": "b" * 64,
            "collection": "synthetic",
            "duplicate_group": "none",
            "accessibility_status": "accessible",
        },
    )
    conn.close()

    # Create synthetic docx extraction JSON
    doc_dir = raw_dir / "SRC-999"
    doc_dir.mkdir(parents=True)
    synthetic_doc = {
        "content": {
            "paragraphs": [
                {"text": "READING PASSAGE 1"},
                {"text": "You should spend about 20 minutes on Questions 1-3 which are based on Reading Passage 1 below."},
                {"text": "Synthetic Renewable Ocean Energy"},
                {
                    "text": (
                        "A Deep sea current turbines generate continuous baseline electrical power from regular tidal streams. "
                        "Unlike terrestrial wind installations which fluctuate with local weather patterns, lunar gravity cycles "
                        "ensure perfectly predictable kinetic yields across every seasonal period."
                    )
                },
                {
                    "text": (
                        "B Submerged rotor assemblies operate under intense hydrostatic pressure and elevated salinity conditions. "
                        "Engineers employ nickel chromium superalloys to prevent electrolytic corrosion of internal drive shafts. "
                        "Routine maintenance schedules require specialized robotic submersibles rather than human divers."
                    )
                },
                {"text": "Questions 1-3"},
                {
                    "text": (
                        "Do the following statements agree with the information given in Reading Passage 1? Write TRUE, FALSE or NOT GIVEN."
                    )
                },
                {"text": "1 Tidal streams generate continuous baseline electrical power."},
                {"text": "2 Submerged drive shafts are manufactured from standard carbon steel."},
                {"text": "3 Deep sea turbine installation budgets exceeded government projections."},
            ]
        }
    }
    (doc_dir / "raw_document.json").write_text(json.dumps(synthetic_doc), encoding="utf-8")

    # Create synthetic OCR key extraction pages
    key_dir = raw_dir / "SRC-998"
    key_dir.mkdir(parents=True)
    p1 = {
        "content": {
            "page_number": 1,
            "text": (
                "Reading Test 1 Answer Explanations\n\n"
                "Question 1\nAnswer: True\n"
                "Explanation: Paragraph A states that deep sea current turbines generate continuous baseline electrical power.\n\n"
                "Question 2\nAnswer: False\n"
                "Explanation: Paragraph B mentions that engineers employ nickel chromium superalloys to prevent corrosion, not carbon steel.\n"
            ),
        },
        "provenance": {
            "unit_identifier": "page_0001",
        },
    }
    p2 = {
        "content": {
            "page_number": 2,
            "text": (
                "Question 3\nAnswer: Not Given\n"
                "Explanation: The passage does not discuss government installation budgets or financial projections.\n"
            ),
        },
        "provenance": {
            "unit_identifier": "page_0002",
        },
    }
    (key_dir / "page_0001.json").write_text(json.dumps(p1), encoding="utf-8")
    (key_dir / "page_0002.json").write_text(json.dumps(p2), encoding="utf-8")

    # Create synthetic annotations file
    ann_file = tmp_path / "synthetic_annotations.json"
    ann_data = {
        "1": {
            "evidence_type": "direct_support",
            "paragraph_label": "A",
            "quote": "Deep sea current turbines generate continuous baseline electrical power from regular tidal streams.",
            "rationale_en": "Paragraph A states that deep sea current turbines generate continuous baseline electrical power.",
            "paraphrases": [],
        },
        "2": {
            "evidence_type": "contradictory_evidence",
            "paragraph_label": "B",
            "quote": "Engineers employ nickel chromium superalloys to prevent electrolytic corrosion of internal drive shafts.",
            "rationale_en": "Paragraph B mentions that engineers employ nickel chromium superalloys to prevent corrosion, not carbon steel.",
            "paraphrases": [],
        },
        "3": {
            "evidence_type": "insufficient_information_not_given",
            "paragraph_label": "A",
            "quote": None,
            "missing_rationale": "The passage mentions technical and environmental factors, but provides no data about government budget overruns.",
            "rationale_en": "The passage does not discuss government installation budgets or financial projections.",
            "paraphrases": [],
        },
    }
    ann_file.write_text(json.dumps(ann_data), encoding="utf-8")

    return {
        "db_path": db_path,
        "raw_dir": raw_dir,
        "output_dir": output_dir,
        "ann_file": ann_file,
    }


# ---------------------------------------------------------------------------
# P0: Dependency-Aware Checkpoints
# ---------------------------------------------------------------------------


def test_dependency_aware_checkpoints(synthetic_env):
    """Verify that modifying the answer key (SRC-137) invalidates Answer, Evidence, and Explanation

    checkpoints while keeping Question and Passage checkpoints cached.
    """
    orch = NormalizationOrchestrator(
        db_path=synthetic_env["db_path"],
        raw_staging_dir=synthetic_env["raw_dir"],
        output_dir=synthetic_env["output_dir"],
    )

    # First run: writes all entities
    res1 = orch.normalize_reading_pilot(
        doc_legacy_id="SRC-999",
        key_legacy_id="SRC-998",
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
        annotations_path=synthetic_env["ann_file"],
    )
    assert res1["written_count"] > 0
    assert res1["skipped_count"] == 0

    # Second run without changes: all entities skipped by checkpoints
    res2 = orch.normalize_reading_pilot(
        doc_legacy_id="SRC-999",
        key_legacy_id="SRC-998",
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
        annotations_path=synthetic_env["ann_file"],
    )
    assert res2["written_count"] == 0
    assert res2["skipped_count"] == res1["written_count"]

    # Now modify the answer key source page
    key_p2 = synthetic_env["raw_dir"] / "SRC-998" / "page_0002.json"
    p2_data = json.loads(key_p2.read_text(encoding="utf-8"))
    p2_data["content"]["text"] += "\n[Updated OCR correction note]"
    key_p2.write_text(json.dumps(p2_data), encoding="utf-8")

    # Third run: document entities (passage, group, questions) should be skipped,
    # but answer, evidence, and explanation entities must be invalidated and re-written!
    res3 = orch.normalize_reading_pilot(
        doc_legacy_id="SRC-999",
        key_legacy_id="SRC-998",
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
        annotations_path=synthetic_env["ann_file"],
    )

    # Document entities: test (1), passage (1), question_group (1), questions (2) = 5 skipped
    assert res3["skipped_count"] == 5
    # Dependent entities re-written: answers (3), evidence (2), explanations (2) = 7 written
    assert res3["written_count"] == 7


# ---------------------------------------------------------------------------
# P0: Complete Manifest on Resume
# ---------------------------------------------------------------------------


def test_complete_manifest_on_resume(synthetic_env):
    """Test:

    1. Normalize full pilot.
    2. Run a second time unchanged.
    3. Confirm all entities remain in manifest.
    4. Corrupt one entity.
    5. Resume.
    6. Confirm exactly the stale output is regenerated and manifest remains complete.
    """
    orch = NormalizationOrchestrator(
        db_path=synthetic_env["db_path"],
        raw_staging_dir=synthetic_env["raw_dir"],
        output_dir=synthetic_env["output_dir"],
    )

    # 1. First run
    res1 = orch.normalize_reading_pilot(
        doc_legacy_id="SRC-999",
        key_legacy_id="SRC-998",
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
        annotations_path=synthetic_env["ann_file"],
    )
    manifest_path = synthetic_env["output_dir"] / "manifest.json"
    assert manifest_path.exists()
    m1 = json.loads(manifest_path.read_text(encoding="utf-8"))
    total_entities_count = len(m1["entities"])
    assert total_entities_count > 0

    # 2. Run a second time unchanged
    res2 = orch.normalize_reading_pilot(
        doc_legacy_id="SRC-999",
        key_legacy_id="SRC-998",
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
        annotations_path=synthetic_env["ann_file"],
    )
    assert res2["skipped_count"] == total_entities_count
    assert res2["written_count"] == 0

    # 3. Confirm all entities remain in manifest
    m2 = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(m2["entities"]) == total_entities_count
    entity_ids_m1 = {e["entity_id"] for e in m1["entities"]}
    entity_ids_m2 = {e["entity_id"] for e in m2["entities"]}
    assert entity_ids_m1 == entity_ids_m2

    # 4. Corrupt one entity (e.g. Q1 answer)
    target_filename = "ANS-VOL99-01-RD-001-KEY.json"
    target_file = synthetic_env["output_dir"] / target_filename
    assert target_file.exists()
    target_file.write_text("corrupted json payload", encoding="utf-8")

    # Invalidate checkpoint for that entity by tampering with output_sha256 in DB
    conn = get_db_connection(synthetic_env["db_path"])
    conn.execute(
        "UPDATE normalization_checkpoints SET output_sha256 = 'bad_hash' WHERE entity_id = 'ANS-VOL99-01-RD-001-KEY'"
    )
    conn.commit()
    conn.close()

    # 5. Resume
    res3 = orch.normalize_reading_pilot(
        doc_legacy_id="SRC-999",
        key_legacy_id="SRC-998",
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
        annotations_path=synthetic_env["ann_file"],
    )

    # 6. Exactly 1 entity is regenerated and manifest remains completely populated
    assert res3["written_count"] == 1
    assert res3["skipped_count"] == total_entities_count - 1

    m3 = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(m3["entities"]) == total_entities_count
    entity_ids_m3 = {e["entity_id"] for e in m3["entities"]}
    assert entity_ids_m3 == entity_ids_m1


# ---------------------------------------------------------------------------
# P0: Verified Answer Provenance
# ---------------------------------------------------------------------------


def test_verified_answer_provenance():
    """Verify answer-key parsing records:

    - Actual processing unit/page
    - Raw matched text
    - Exact source offsets
    - Original answer value
    - Match confidence
    - Ambiguity flags
    And distinguishes secondary keys from authoritative official keys.
    """
    reconciler = AnswerReconciler()
    pages = [
        {
            "content": {
                "page_number": 95,
                "text": "Header info\nQuestion 3\nAnswer: Not Given\nLocation: Paragraph 1\n",
            },
            "provenance": {"unit_identifier": "page_0095"},
        },
        {
            "content": {
                "page_number": 96,
                "text": "Header info\nQuestion 4\nAnswer: True\nLocation: Paragraph 2\n",
            },
            "provenance": {"unit_identifier": "page_0096"},
        },
    ]

    keys = reconciler.parse_pdf_ocr_explanation_keys(pages)
    assert 3 in keys
    assert 4 in keys

    # Verify Q3 metadata
    q3_info = keys[3]
    assert q3_info["unit_identifier"] == "page_0095"
    assert q3_info["page_number"] == 95
    assert q3_info["char_start"] < q3_info["char_end"]
    assert "Not Given" in q3_info["raw_matched_text"]
    assert q3_info["confidence"] >= 0.95
    assert "ambiguity_flags" in q3_info

    # Verify Q4 metadata
    q4_info = keys[4]
    assert q4_info["unit_identifier"] == "page_0096"
    assert q4_info["page_number"] == 96
    assert q4_info["char_start"] < q4_info["char_end"]

    # Reconcile answers with secondary reputable source
    src_record = {
        "file_id": "FILE-000000000137",
        "legacy_id": "SRC-137",
        "relative_path": "sources/secondary/guide.pdf",
        "content_sha256": "c" * 64,
        "source_fidelity": "secondary_reputable",
    }
    dummy_qp = QualityProfile(
        lifecycle_status="extracted",
        extraction_quality="complete_clean",
        source_fidelity="secondary_reputable",
        answer_verification="consensus_key",
        explanation_verification="source_provided",
        publication_permission="public_synthetic",
    )
    dummy_prov = ProvenanceEnvelope(
        schema_version=SCHEMA_VERSION,
        source_file_id="FILE-000000000137",
        source_legacy_id="SRC-137",
        relative_path="sources/secondary/guide.pdf",
        source_sha256="c" * 64,
        processing_unit="page",
        unit_identifier="page_0095",
        raw_block_locator="offset:0-10",
        extractor_adapter="pdf_ocr",
        extractor_version="0.1.0",
        normalizer_version="0.2.0-b",
    )
    q3 = IELTSQuestion(
        question_id="Q-VOL06-05-RD-003",
        group_id="QG-VOL06-05-RD01-G01",
        passage_id="PASSAGE-VOL06-05-RD01",
        question_number=3,
        question_type="true-false-not-given",
        prompt_text="Synthetic prompt 3",
        quality_profile=dummy_qp,
        _provenance=dummy_prov,
    )
    q4 = IELTSQuestion(
        question_id="Q-VOL06-05-RD-004",
        group_id="QG-VOL06-05-RD01-G01",
        passage_id="PASSAGE-VOL06-05-RD01",
        question_number=4,
        question_type="true-false-not-given",
        prompt_text="Synthetic prompt 4",
        quality_profile=dummy_qp,
        _provenance=dummy_prov,
    )
    answers = reconciler.reconcile_answers(
        questions=[q3, q4],
        raw_key_map=keys,
        source_record=src_record,
        test_number=5,
        volume_code="VOL06",
    )

    ans_by_num = {int(a.answer_id.split("-")[-2]): a for a in answers}

    # Q3 and Q4 must NOT be marked authoritative_official or authoritative_key
    assert ans_by_num[3].quality_profile.source_fidelity == "secondary_reputable"
    # Never label single-source secondary answers as consensus_key without independent corroboration
    assert ans_by_num[3].quality_profile.answer_verification == "unverified"
    assert "SINGLE_SOURCE_UNVERIFIED_KEY" in ans_by_num[3].quality_profile.validation_flags
    assert ans_by_num[3].provenance.unit_identifier == "page_0095"
    assert ans_by_num[3].provenance.raw_block_locator.startswith("offset:")

    assert ans_by_num[4].quality_profile.source_fidelity == "secondary_reputable"
    assert ans_by_num[4].quality_profile.answer_verification == "unverified"
    assert ans_by_num[4].provenance.unit_identifier == "page_0096"

    # Test independent corroboration produces consensus_key
    keys_corroborated = copy.deepcopy(keys)
    keys_corroborated[3]["corroborated"] = True
    ans_corr = reconciler.reconcile_answers(
        questions=[q3],
        raw_key_map=keys_corroborated,
        source_record=src_record,
        test_number=5,
        volume_code="VOL06",
    )
    assert ans_corr[0].quality_profile.answer_verification == "consensus_key"

    # Test official source produces authoritative_key
    official_src = dict(src_record, collection="official_cambridge", source_fidelity="authoritative_official")
    ans_off = reconciler.reconcile_answers(
        questions=[q3],
        raw_key_map=keys,
        source_record=official_src,
        test_number=5,
        volume_code="VOL06",
    )
    assert ans_off[0].quality_profile.answer_verification == "authoritative_key"


# ---------------------------------------------------------------------------
# P0: Evidence Provenance and Privacy
# ---------------------------------------------------------------------------


def test_evidence_provenance_and_privacy_no_copyright_in_public_code():
    """Verify that no source-derived copyrighted text is embedded in public harness source files."""
    forbidden_snippets = [
        "Students wishing to take a course",
        "considered 7 Fraudulant",
        "visual styles at different periods and places",
    ]
    for py_file in (REPO_ROOT / "harness").rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            assert snippet not in text, f"Found copyrighted snippet '{snippet}' in public source {py_file}"


# ---------------------------------------------------------------------------
# P1: Quality Gate Integrity — G1 to G7 Negative & Positive Tests
# ---------------------------------------------------------------------------


def create_minimal_valid_entities(db_path: Path) -> Dict[str, List[Dict[str, Any]]]:
    """Helper to generate a structurally valid set of synthetic entities."""
    init_db(db_path)
    conn = get_db_connection(db_path)
    upsert_source(
        conn,
        {
            "file_id": "FILE-000000000099",
            "legacy_id": "SRC-999",
            "relative_path": "synthetic/test.docx",
            "filename": "test.docx",
            "extension": ".docx",
            "detected_type": "openxml_word",
            "size_bytes": 100,
            "content_sha256": "9" * 64,
            "collection": "synthetic",
            "duplicate_group": "none",
            "accessibility_status": "accessible",
        },
    )
    conn.close()

    prov = ProvenanceEnvelope(
        schema_version=SCHEMA_VERSION,
        source_file_id="FILE-000000000099",
        source_legacy_id="SRC-999",
        relative_path="synthetic/test.docx",
        source_sha256="9" * 64,
        processing_unit="document",
        unit_identifier="raw_document",
        raw_block_locator="para:0",
        extractor_adapter="docx",
        extractor_version="0.1.0",
        normalizer_version="0.2.0-b",
    )
    qp = QualityProfile(
        lifecycle_status="reviewed",
        extraction_quality="complete_clean",
        source_fidelity="authoritative_official",
        answer_verification="authoritative_key",
        explanation_verification="source_provided",
        publication_permission="public_synthetic",
    )

    narrative = (
        "Global synthetic materials advanced in durability across aerospace, biomedical and automotive engineering applications. "
        "Engineers synthesized durable cross-linked formulations capable of withstanding intense mechanical friction and elevated thermal loads. "
        "Standardized chemical testing validated continuous baseline reliability throughout extended operational deployment cycles worldwide. "
        "These composite architectures prevented catastrophic structural degradation under harsh environmental conditions without incurring excessive manufacturing expenses."
    )
    test_ent = IELTSTest(
        test_id="TEST-IELTS-VOL99-01-ACAD",
        title="IELTS Academic Reading Test 1",
        volume="VOL99",
        test_number=1,
        track="academic",
        sections_present=["reading"],
        quality_profile=qp,
        _provenance=prov,
    )
    passage = PassageOrSection(
        passage_id="PASSAGE-VOL99-01-RD01",
        test_id="TEST-IELTS-VOL99-01-ACAD",
        skill="reading",
        sequence_number=1,
        title="Synthetic Materials",
        narrative_text=narrative,
        paragraphs=[ParagraphItem(label="A", sequence_index=0, char_start=0, char_end=len(narrative), text=narrative)],
        word_count=len(narrative.split()),
        quality_profile=qp,
        _provenance=prov,
    )
    group = QuestionGroup(
        group_id="QG-VOL99-01-RD01-G01",
        passage_id="PASSAGE-VOL99-01-RD01",
        question_type="true-false-not-given",
        instruction_text="Write TRUE, FALSE or NOT GIVEN.",
        start_question_number=1,
        end_question_number=1,
        quality_profile=qp,
        _provenance=prov,
    )
    question = IELTSQuestion(
        question_id="Q-VOL99-01-RD-001",
        group_id="QG-VOL99-01-RD01-G01",
        passage_id="PASSAGE-VOL99-01-RD01",
        question_number=1,
        question_type="true-false-not-given",
        prompt_text="Global synthetic materials advanced in durability.",
        quality_profile=qp,
        _provenance=prov,
    )
    answer = IELTSAnswer(
        answer_id="ANS-VOL99-01-RD-001-KEY",
        question_id="Q-VOL99-01-RD-001",
        target_value="TRUE",
        acceptable_alternates=["T"],
        source_key_ref="Page 1",
        quality_profile=qp,
        _provenance=prov,
    )
    quote = "Global synthetic materials advanced in durability across aerospace, biomedical and automotive engineering applications."
    evid = IELTSEvidence(
        evidence_id="EVID-VOL99-01-RD-001-01",
        answer_id="ANS-VOL99-01-RD-001-KEY",
        passage_id="PASSAGE-VOL99-01-RD01",
        evidence_type="direct_support",
        verbatim_quote=quote,
        char_start=0,
        char_end=len(quote),
        paragraph_label="A",
        exact_match_verified=True,
        quality_profile=qp,
        _provenance=prov,
    )
    expl = IELTSExplanation(
        explanation_id="EXPL-VOL99-01-RD-001",
        question_id="Q-VOL99-01-RD-001",
        answer_id="ANS-VOL99-01-RD-001-KEY",
        evidence_id="EVID-VOL99-01-RD-001-01",
        rationale_en="The passage explicitly states this in Paragraph A.",
        author_type="source_published",
        quality_profile=qp,
        _provenance=prov,
    )

    entities = {
        "test": [BaseNormalizer.finalize_and_hash_entity(test_ent)],
        "passages": [BaseNormalizer.finalize_and_hash_entity(passage)],
        "groups": [BaseNormalizer.finalize_and_hash_entity(group)],
        "questions": [BaseNormalizer.finalize_and_hash_entity(question)],
        "answers": [BaseNormalizer.finalize_and_hash_entity(answer)],
        "evidence": [BaseNormalizer.finalize_and_hash_entity(evid)],
        "explanations": [BaseNormalizer.finalize_and_hash_entity(expl)],
    }
    return entities


def test_quality_gate_g1_negative(tmp_path: Path):
    """G1: Fail when SQLite DB or mandatory source verification is unavailable."""
    db_path = tmp_path / "nonexistent.db"
    runner = QualityGateRunner(db_path=db_path)

    # Synthetic entity with non-synthetic publication_permission
    entities = create_minimal_valid_entities(tmp_path / "init.db")
    entities["questions"][0]["quality_profile"]["publication_permission"] = "private_copyrighted"

    res = runner.verify_g1_source_integrity(entities)
    assert not res["passed"]
    assert res["status"] == "FAIL"
    assert any("Mandatory source verification unavailable" in err for err in res["errors"])


def test_quality_gate_g2_negative(tmp_path: Path):
    """G2: Validate expected question count and group boundaries, and reject placeholder prompts."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    runner = QualityGateRunner(db_path=db_path)

    entities = create_minimal_valid_entities(db_path)

    # 1. Boundary / Count mismatch: group says 1-2, but only Q1 exists
    entities["groups"][0]["end_question_number"] = 2
    res = runner.verify_g2_structural_fidelity(entities)
    assert not res["passed"]
    assert any("Group QG-VOL99-01-RD01-G01 expects 2 questions" in err for err in res["errors"])

    # 2. Forbidden placeholder prompt
    entities["groups"][0]["end_question_number"] = 1
    entities["questions"][0]["prompt_text"] = "[Question 1 text unresolved]"
    res2 = runner.verify_g2_structural_fidelity(entities)
    assert not res2["passed"]
    assert any("forbidden placeholder" in err for err in res2["errors"])


def test_quality_gate_g4_distinguishes_unresolved(tmp_path: Path):
    """G4: Distinguish PASS_WITH_UNRESOLVED from clean PASS and hard FAIL."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    runner = QualityGateRunner(db_path=db_path)

    # Clean PASS
    entities = create_minimal_valid_entities(db_path)
    res_clean = runner.verify_g4_referential_integrity(entities)
    assert res_clean["passed"]
    assert res_clean["status"] == "PASS"

    # Unresolved: add orphan answer (no question_id)
    orphan_ans = copy.deepcopy(entities["answers"][0])
    orphan_ans["answer_id"] = "ANS-VOL99-01-RD-099-KEY"
    orphan_ans["question_id"] = None
    entities_unres = copy.deepcopy(entities)
    entities_unres["answers"].append(orphan_ans)

    res_unres = runner.verify_g4_referential_integrity(entities_unres)
    assert res_unres["passed"]
    assert res_unres["status"] == "PASS_WITH_UNRESOLVED"
    assert len(res_unres["unresolved"]) > 0

    # Hard FAIL: answer points to non-existent question
    entities_fail = copy.deepcopy(entities)
    entities_fail["answers"][0]["question_id"] = "NON-EXISTENT-Q"
    res_fail = runner.verify_g4_referential_integrity(entities_fail)
    assert not res_fail["passed"]
    assert res_fail["status"] == "FAIL"


def test_quality_gate_g5_separates_textual_and_semantic(tmp_path: Path):
    """G5: Keep textual matching separate from semantic answer verification."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    runner = QualityGateRunner(db_path=db_path)

    # 1. Textual mismatch: span text does not match verbatim quote
    entities_text_err = create_minimal_valid_entities(db_path)
    entities_text_err["evidence"][0]["verbatim_quote"] = "Wrong quote string"
    res1 = runner.verify_g5_evidence_fidelity(entities_text_err)
    assert not res1["passed"]
    assert not res1["textual_grounding"]["passed"]
    assert res1["semantic_verification"]["passed"]  # Semantic is fine

    # 2. Semantic mismatch: answer is TRUE but evidence_type is contradictory_evidence
    entities_sem_err = create_minimal_valid_entities(db_path)
    entities_sem_err["evidence"][0]["evidence_type"] = "contradictory_evidence"
    res2 = runner.verify_g5_evidence_fidelity(entities_sem_err)
    assert not res2["passed"]
    assert res2["textual_grounding"]["passed"]  # Textual span is fine
    assert not res2["semantic_verification"]["passed"]
    assert any("Semantic mismatch" in err for err in res2["semantic_verification"]["errors"])

    # 3. NOT GIVEN with non-null quote fails textual
    entities_ng_err = create_minimal_valid_entities(db_path)
    entities_ng_err["answers"][0]["target_value"] = "NOT GIVEN"
    entities_ng_err["evidence"][0]["evidence_type"] = "insufficient_information_not_given"
    entities_ng_err["evidence"][0]["verbatim_quote"] = "Should not have quote"
    res3 = runner.verify_g5_evidence_fidelity(entities_ng_err)
    assert not res3["passed"]
    assert not res3["textual_grounding"]["passed"]


def test_quality_gate_g6_missing_canonical_hash_fails(tmp_path: Path):
    """G6: Missing canonical hashes must fail."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    runner = QualityGateRunner(db_path=db_path)

    entities = create_minimal_valid_entities(db_path)
    # Remove canonical hash from question
    entities["questions"][0]["_provenance"]["canonical_content_sha256"] = None

    res = runner.verify_g6_deterministic_processing(entities)
    assert not res["passed"]
    assert res["status"] == "FAIL"
    assert any("Missing canonical_content_sha256" in err for err in res["errors"])


def test_quality_gate_g7_privacy_isolation(tmp_path: Path):
    """G7: Validate privacy of all output paths, not only data/*.json."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    runner = QualityGateRunner(db_path=db_path)

    entities = create_minimal_valid_entities(db_path)
    # Mark entity as private_copyrighted but assign public output path
    entities["questions"][0]["quality_profile"]["publication_permission"] = "private_copyrighted"
    entities["questions"][0]["_output_path"] = "data/public_test.json"

    res = runner.verify_g7_privacy_isolation(entities)
    assert not res["passed"]
    assert res["status"] == "FAIL"
    assert any("public/non-private output path" in err for err in res["errors"])


# ---------------------------------------------------------------------------
# P1: Missing Prompt Handling
# ---------------------------------------------------------------------------


def test_missing_prompt_handling_does_not_emit_placeholder():
    """Verify that unextracted prompts are not published as placeholders and are quarantined in

    unresolved_questions.
    """
    normalizer = DocxReadingNormalizer()
    paragraphs = [
        {"text": "READING PASSAGE 1"},
        {"text": "You should spend about 20 minutes on Questions 1-3 which are based on Reading Passage 1 below."},
        {"text": "Synthetic Renewable Ocean Energy"},
        {
            "text": (
                "A Deep sea current turbines generate continuous baseline electrical power from regular tidal streams. "
                "Unlike terrestrial wind installations which fluctuate with local weather patterns, lunar gravity cycles "
                "ensure perfectly predictable kinetic yields across every seasonal period without requiring large barrage "
                "dams or producing detrimental environmental consequences for marine coastal ecosystems."
            )
        },
        {"text": "Questions 1-3"},
        {"text": "Do the following statements agree with the information given in Reading Passage 1? Write TRUE, FALSE or NOT GIVEN."},
        {"text": "1 Valid question prompt 1."},
        # Question 2 is missing from text!
        {"text": "3 Valid question prompt 3."},
    ]

    res = normalizer.normalize(
        raw_document={"content": {"paragraphs": paragraphs}},
        source_record={
            "file_id": "FILE-000000000001",
            "legacy_id": "SRC-999",
            "relative_path": "synthetic/doc.docx",
            "content_sha256": "0" * 64,
        },
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
    )

    questions = res["questions"]
    q_nums = [q.question_number for q in questions]

    # Q2 must NOT be published
    assert 2 not in q_nums
    assert 1 in q_nums
    assert 3 in q_nums

    # No question contains the placeholder string
    for q in questions:
        assert "[question" not in q.prompt_text.lower()

    # Unresolved question 2 is captured in unresolved_questions list
    assert any(uq["question_number"] == 2 for uq in res["unresolved_questions"])


# ---------------------------------------------------------------------------
# P0 Hardening: Verification Status, Stale Reconciliation, Pre-write Privacy
# ---------------------------------------------------------------------------


def test_failed_source_match_never_implies_expert_approval(tmp_path: Path):
    """Verify that ungrounded explanations without documented human expert review

    receive machine_drafted / machine_drafted_unverified, NEVER expert_verified.
    """
    resolver = EvidenceResolver()
    prov = ProvenanceEnvelope(
        schema_version=SCHEMA_VERSION,
        source_file_id="FILE-000000000099",
        source_legacy_id="SRC-999",
        relative_path="synthetic/test.docx",
        source_sha256="9" * 64,
        processing_unit="document",
        unit_identifier="raw_document",
        raw_block_locator="para:0",
        extractor_adapter="docx",
        extractor_version="0.1.0",
        normalizer_version="0.2.0-b",
    )
    qp = QualityProfile(
        lifecycle_status="review_required",
        extraction_quality="complete_clean",
        source_fidelity="secondary_reputable",
        answer_verification="unverified",
        explanation_verification="missing_explanation",
        publication_permission="public_synthetic",
    )
    question = IELTSQuestion(
        question_id="Q-VOL99-01-RD-001",
        group_id="QG-VOL99-01-RD01-G01",
        passage_id="PASSAGE-VOL99-01-RD01",
        question_number=1,
        question_type="true-false-not-given",
        prompt_text="Prompt text here.",
        quality_profile=qp,
        _provenance=prov,
    )
    answer = IELTSAnswer(
        answer_id="ANS-VOL99-01-RD-001-KEY",
        question_id="Q-VOL99-01-RD-001",
        target_value="TRUE",
        acceptable_alternates=["T"],
        source_key_ref="Page 1",
        quality_profile=qp,
        _provenance=prov,
    )

    # 1. Failed source match without human expert review
    expl_ungrounded = resolver.resolve_explanation(
        explanation_id="EXPL-VOL99-01-RD-001",
        question=question,
        answer=answer,
        evidence=None,
        rationale_en="Ungrounded machine rationale.",
        author_type="machine_drafted",
        explanation_verification="machine_drafted_unverified",
        publication_permission="public_synthetic",
    )
    assert expl_ungrounded.author_type == "machine_drafted"
    assert expl_ungrounded.quality_profile.explanation_verification == "machine_drafted_unverified"
    assert expl_ungrounded.quality_profile.lifecycle_status == "review_required"

    # 2. Assigning expert_verified without documented human expert review raises ValueError
    with pytest.raises(ValueError, match="Epistemic violation"):
        resolver.resolve_explanation(
            explanation_id="EXPL-VOL99-01-RD-001",
            question=question,
            answer=answer,
            evidence=None,
            rationale_en="Unreviewed rationale claiming expert approval.",
            author_type="expert_teacher",
            explanation_verification="expert_verified",
            publication_permission="public_synthetic",
            has_human_review=False,
        )

    # 3. Documented human expert review event succeeds
    expl_reviewed = resolver.resolve_explanation(
        explanation_id="EXPL-VOL99-01-RD-001",
        question=question,
        answer=answer,
        evidence=None,
        rationale_en="Human expert reviewed rationale.",
        author_type="expert_teacher",
        explanation_verification="expert_verified",
        publication_permission="public_synthetic",
        has_human_review=True,
    )
    assert expl_reviewed.author_type == "expert_teacher"
    assert expl_reviewed.quality_profile.explanation_verification == "expert_verified"


def test_stale_entity_reconciliation_on_annotation_removal(synthetic_env):
    """Verify active manifest authority and stale artifact archiving when an annotation is removed."""
    orch = NormalizationOrchestrator(
        db_path=synthetic_env["db_path"],
        raw_staging_dir=synthetic_env["raw_dir"],
        output_dir=synthetic_env["output_dir"],
        authorized_private_roots=[synthetic_env["output_dir"].parent],
    )

    # Run 1: with annotations for Q1, Q2, Q3
    res1 = orch.normalize_reading_pilot(
        doc_legacy_id="SRC-999",
        key_legacy_id="SRC-998",
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
        annotations_path=synthetic_env["ann_file"],
    )
    manifest_file = synthetic_env["output_dir"] / "manifest.json"
    m1 = json.loads(manifest_file.read_text(encoding="utf-8"))
    q3_evid_filename = "EVID-VOL99-01-RD-003-01.json"
    q3_expl_filename = "EXPL-VOL99-01-RD-003.json"
    assert (synthetic_env["output_dir"] / q3_evid_filename).exists()
    assert (synthetic_env["output_dir"] / q3_expl_filename).exists()
    assert any(e["output_filename"] == q3_evid_filename for e in m1["entities"])

    # Run 2: remove Q3 annotation
    ann_data = json.loads(synthetic_env["ann_file"].read_text(encoding="utf-8"))
    del ann_data["3"]
    synthetic_env["ann_file"].write_text(json.dumps(ann_data), encoding="utf-8")

    res2 = orch.normalize_reading_pilot(
        doc_legacy_id="SRC-999",
        key_legacy_id="SRC-998",
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
        annotations_path=synthetic_env["ann_file"],
        force=True,
    )

    # Stale artifacts for Q3 must be removed from active output dir and archived in .historical
    assert not (synthetic_env["output_dir"] / q3_evid_filename).exists()
    assert not (synthetic_env["output_dir"] / q3_expl_filename).exists()
    assert (synthetic_env["output_dir"] / ".historical" / q3_evid_filename).exists()
    assert (synthetic_env["output_dir"] / ".historical" / q3_expl_filename).exists()

    # Active manifest must NOT list Q3 evidence or explanation
    m2 = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert not any(e["output_filename"] == q3_evid_filename for e in m2["entities"])
    assert not any(e["output_filename"] == q3_expl_filename for e in m2["entities"])
    assert any(s["entity_id"] == "EVID-VOL99-01-RD-003-01" for s in m2.get("stale_entities", []))

    # Verifier loading entities must treat manifest as authoritative and exclude historical/stale files
    runner = QualityGateRunner(db_path=synthetic_env["db_path"])
    loaded = runner.load_entities_for_test(synthetic_env["output_dir"], "TEST-IELTS-VOL99-01-ACAD")
    loaded_ev_ids = {e["evidence_id"] for e in loaded["evidence"]}
    assert "EVID-VOL99-01-RD-003-01" not in loaded_ev_ids


def test_pre_write_privacy_enforcement_rejects_unauthorized_destinations(tmp_path: Path):
    """Verify that private_copyrighted entities are rejected before write if targeted outside authorized private storage."""
    from harness.normalizers.base import BaseNormalizer, validate_output_privacy

    prov = ProvenanceEnvelope(
        schema_version=SCHEMA_VERSION,
        source_file_id="FILE-000000000099",
        source_legacy_id="SRC-999",
        relative_path="sources/raw.docx",
        source_sha256="0" * 64,
        processing_unit="document",
        unit_identifier="raw_document",
        raw_block_locator="para:0",
        extractor_adapter="docx",
        extractor_version="0.1.0",
        normalizer_version="0.2.0-b",
    )
    qp_private = QualityProfile(
        lifecycle_status="reviewed",
        extraction_quality="complete_clean",
        source_fidelity="secondary_reputable",
        answer_verification="unverified",
        explanation_verification="source_provided",
        publication_permission="private_copyrighted",
    )
    private_entity = IELTSAnswer(
        answer_id="ANS-VOL99-01-RD-001-KEY",
        question_id="Q-VOL99-01-RD-001",
        target_value="TRUE",
        acceptable_alternates=["T"],
        source_key_ref="Page 1",
        quality_profile=qp_private,
        _provenance=prov,
    )

    # 1. Writing directly to public data/ must raise PermissionError
    public_target = REPO_ROOT / "data" / "leak.json"
    with pytest.raises(PermissionError, match="Privacy policy violation"):
        BaseNormalizer.write_entity(public_target, private_entity)

    # 2. Writing via path traversal (private/../data/leak.json) must raise PermissionError
    traversal_target = REPO_ROOT / "private" / ".." / "data" / "leak.json"
    with pytest.raises(PermissionError, match="Privacy policy violation"):
        BaseNormalizer.write_entity(traversal_target, private_entity)

    # 3. Writing to arbitrary external path without authorized root must raise PermissionError
    external_leak = tmp_path / "leak.json"
    with pytest.raises(PermissionError, match="Privacy policy violation"):
        BaseNormalizer.write_entity(external_leak, private_entity)


def test_invalid_annotations_file_fails_visibly(synthetic_env):
    """Verify that malformed or non-existent annotation files fail with explicit errors."""
    orch = NormalizationOrchestrator(
        db_path=synthetic_env["db_path"],
        raw_staging_dir=synthetic_env["raw_dir"],
        output_dir=synthetic_env["output_dir"],
        authorized_private_roots=[synthetic_env["output_dir"].parent],
    )

    # 1. Non-existent file raises FileNotFoundError
    with pytest.raises(FileNotFoundError, match="Annotations file not found"):
        orch.normalize_reading_pilot(
            doc_legacy_id="SRC-999",
            key_legacy_id="SRC-998",
            annotations_path=synthetic_env["raw_dir"] / "nonexistent_annotations.json",
        )

    # 2. Malformed JSON raises ValueError
    bad_json = synthetic_env["raw_dir"] / "bad_annotations.json"
    bad_json.write_text("{malformed json content", encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed JSON"):
        orch.normalize_reading_pilot(
            doc_legacy_id="SRC-999",
            key_legacy_id="SRC-998",
            annotations_path=bad_json,
        )


def test_pre_write_privacy_symlink_escape_rejected(tmp_path: Path):
    """Verify that writing private_copyrighted entities via symlink pointing outside authorized private storage is rejected."""
    from harness.normalizers.base import BaseNormalizer

    prov = ProvenanceEnvelope(
        schema_version=SCHEMA_VERSION,
        source_file_id="FILE-000000000099",
        source_legacy_id="SRC-999",
        relative_path="sources/raw.docx",
        source_sha256="0" * 64,
        processing_unit="document",
        unit_identifier="raw_document",
        raw_block_locator="para:0",
        extractor_adapter="docx",
        extractor_version="0.1.0",
        normalizer_version="0.2.0-b",
    )
    qp_private = QualityProfile(
        lifecycle_status="reviewed",
        extraction_quality="complete_clean",
        source_fidelity="secondary_reputable",
        answer_verification="unverified",
        explanation_verification="source_provided",
        publication_permission="private_copyrighted",
    )
    private_entity = IELTSAnswer(
        answer_id="ANS-VOL99-01-RD-001-KEY",
        question_id="Q-VOL99-01-RD-001",
        target_value="TRUE",
        acceptable_alternates=["T"],
        source_key_ref="Page 1",
        quality_profile=qp_private,
        _provenance=prov,
    )

    private_dir = tmp_path / "private_store"
    private_dir.mkdir()
    public_target_dir = tmp_path / "public_leak"
    public_target_dir.mkdir()

    symlink_path = private_dir / "symlink_escape.json"
    target_leak_file = public_target_dir / "escaped.json"
    symlink_path.symlink_to(target_leak_file)

    with pytest.raises(PermissionError, match="Privacy policy violation"):
        BaseNormalizer.write_entity(symlink_path, private_entity, authorized_private_roots=[private_dir])


def test_stale_entity_reconciliation_on_annotation_modification(synthetic_env):
    """Verify that modifying an annotation produces updated canonical hashes and updates checkpoints."""
    orch = NormalizationOrchestrator(
        db_path=synthetic_env["db_path"],
        raw_staging_dir=synthetic_env["raw_dir"],
        output_dir=synthetic_env["output_dir"],
        authorized_private_roots=[synthetic_env["output_dir"].parent],
    )

    # Run 1: original annotations
    res1 = orch.normalize_reading_pilot(
        doc_legacy_id="SRC-999",
        key_legacy_id="SRC-998",
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
        annotations_path=synthetic_env["ann_file"],
    )
    q3_expl_file = synthetic_env["output_dir"] / "EXPL-VOL99-01-RD-003.json"
    m1_data = json.loads((synthetic_env["output_dir"] / "manifest.json").read_text(encoding="utf-8"))
    q3_expl_entry1 = next(e for e in m1_data["entities"] if e["entity_id"] == "EXPL-VOL99-01-RD-003")
    orig_hash = q3_expl_entry1["canonical_content_sha256"]

    # Run 2: modify Q3 rationale in annotation
    ann_data = json.loads(synthetic_env["ann_file"].read_text(encoding="utf-8"))
    ann_data["3"]["rationale_en"] = "MODIFIED explanation rationale for Q3."
    synthetic_env["ann_file"].write_text(json.dumps(ann_data), encoding="utf-8")

    # Running with resume: dependency-aware checksum detects annotation change and regenerates Q3
    res2 = orch.normalize_reading_pilot(
        doc_legacy_id="SRC-999",
        key_legacy_id="SRC-998",
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
        annotations_path=synthetic_env["ann_file"],
    )
    assert res2["written_count"] > 0

    m2_data = json.loads((synthetic_env["output_dir"] / "manifest.json").read_text(encoding="utf-8"))
    q3_expl_entry2 = next(e for e in m2_data["entities"] if e["entity_id"] == "EXPL-VOL99-01-RD-003")
    new_hash = q3_expl_entry2["canonical_content_sha256"]

    assert new_hash != orig_hash, "Canonical hash must change when annotation content is modified"
    updated_q3_json = json.loads(q3_expl_file.read_text(encoding="utf-8"))
    assert updated_q3_json["rationale_en"] == "MODIFIED explanation rationale for Q3."


def test_quality_gate_rejects_epistemic_integrity_violations(tmp_path: Path):
    """Negative tests for Quality Gates: reject consensus_key without corroboration and expert_verified on unreviewed."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    runner = QualityGateRunner(db_path=db_path)

    entities = create_minimal_valid_entities(db_path)

    # 1. Answer has SINGLE_SOURCE_UNVERIFIED_KEY flag but is labeled consensus_key
    bad_ans = copy.deepcopy(entities["answers"][0])
    bad_ans["quality_profile"]["answer_verification"] = "consensus_key"
    bad_ans["quality_profile"]["validation_flags"] = ["SINGLE_SOURCE_UNVERIFIED_KEY"]
    entities_bad_ans = copy.deepcopy(entities)
    entities_bad_ans["answers"][0] = bad_ans

    res1 = runner.verify_g4_referential_integrity(entities_bad_ans)
    assert not res1["passed"]
    assert any("SINGLE_SOURCE_UNVERIFIED_KEY flag" in err for err in res1["errors"])

    # 2. Explanation has MACHINE_DRAFTED_UNVERIFIED flag but claims expert_verified
    bad_expl = copy.deepcopy(entities["explanations"][0])
    bad_expl["quality_profile"]["explanation_verification"] = "expert_verified"
    bad_expl["quality_profile"]["validation_flags"] = ["MACHINE_DRAFTED_UNVERIFIED"]
    entities_bad_expl = copy.deepcopy(entities)
    entities_bad_expl["explanations"][0] = bad_expl

    res2 = runner.verify_g4_referential_integrity(entities_bad_expl)
    assert not res2["passed"]
    assert any("claims expert_verified despite MACHINE_DRAFTED_UNVERIFIED" in err for err in res2["errors"])


def test_verifier_fails_closed_on_missing_or_corrupted_manifest(tmp_path: Path):
    """Verify that QualityGateRunner fails closed (raising FileNotFoundError or ValueError) when manifest is missing or corrupted."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    runner = QualityGateRunner(db_path=db_path)

    norm_dir = tmp_path / "normalized"
    norm_dir.mkdir()

    # 1. Missing manifest.json must fail closed with FileNotFoundError
    with pytest.raises(FileNotFoundError, match="Authoritative manifest missing"):
        runner.load_entities_for_test(norm_dir, "TEST-IELTS-VOL99-01-ACAD")

    # 2. Corrupted manifest.json (malformed JSON) must fail closed with ValueError
    manifest_path = norm_dir / "manifest.json"
    manifest_path.write_text("{malformed json", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupted"):
        runner.load_entities_for_test(norm_dir, "TEST-IELTS-VOL99-01-ACAD")

    # 3. Invalid manifest structure (missing 'entities' list) must fail closed with ValueError
    manifest_path.write_text(json.dumps({"pipeline": "test"}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing required 'entities' list"):
        runner.load_entities_for_test(norm_dir, "TEST-IELTS-VOL99-01-ACAD")


def test_human_review_truthy_strings_rejected_and_structured_event_required(synthetic_env):
    """Verify that truthy strings ('false', 'pending', 'unreviewed') do NOT trigger expert_verified, while structured review events do."""
    orch = NormalizationOrchestrator(
        db_path=synthetic_env["db_path"],
        raw_staging_dir=synthetic_env["raw_dir"],
        output_dir=synthetic_env["output_dir"],
        authorized_private_roots=[synthetic_env["output_dir"].parent],
    )

    # 1. Truthy strings ('false', 'pending') must be rejected and result in machine_drafted_unverified
    ann_file = synthetic_env["raw_dir"] / "truthy_string_ann.json"
    ann_payload = {
        "pilot_id": "PILOT-TEST",
        "annotations": [
            {
                "question_number": 3,
                "evidence_type": "insufficient_information_not_given",
                "missing_rationale": "Missing rationale.",
                "rationale_en": "Ungrounded rationale text.",
                "reviewed_by_expert": "false",  # Truthy string!
                "expert_reviewer": "pending",   # Bare truthy string!
                "review_event": "unreviewed",   # String not dict!
            }
        ]
    }
    ann_file.write_text(json.dumps(ann_payload), encoding="utf-8")

    orch.normalize_reading_pilot(
        doc_legacy_id="SRC-999",
        key_legacy_id="SRC-998",
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
        annotations_path=ann_file,
        force=True,
    )
    expl_file = synthetic_env["output_dir"] / "EXPL-VOL99-01-RD-003.json"
    expl_data = json.loads(expl_file.read_text(encoding="utf-8"))
    assert expl_data["author_type"] == "machine_drafted"
    assert expl_data["quality_profile"]["explanation_verification"] == "machine_drafted_unverified"

    # 2. Structured review event with valid reviewer and approved status succeeds
    ann_structured = {
        "pilot_id": "PILOT-TEST",
        "annotations": [
            {
                "question_number": 3,
                "evidence_type": "insufficient_information_not_given",
                "missing_rationale": "Missing rationale.",
                "rationale_en": "Ungrounded rationale text.",
                "review_event": {
                    "reviewer_id": "EXP-IELTS-001",
                    "decision": "approved",
                    "timestamp": "2026-11-20T06:00:00Z",
                }
            }
        ]
    }
    ann_file.write_text(json.dumps(ann_structured), encoding="utf-8")

    orch.normalize_reading_pilot(
        doc_legacy_id="SRC-999",
        key_legacy_id="SRC-998",
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
        annotations_path=ann_file,
        force=True,
    )
    expl_data_approved = json.loads(expl_file.read_text(encoding="utf-8"))
    assert expl_data_approved["author_type"] == "expert_teacher"
    assert expl_data_approved["quality_profile"]["explanation_verification"] == "expert_verified"


def test_annotation_validation_rejects_invalid_inputs_without_swallowing_exceptions(synthetic_env):
    """Verify that invalid annotations (missing evidence_type, invalid types, invalid keys) raise ValueError and are not swallowed."""
    orch = NormalizationOrchestrator(
        db_path=synthetic_env["db_path"],
        raw_staging_dir=synthetic_env["raw_dir"],
        output_dir=synthetic_env["output_dir"],
        authorized_private_roots=[synthetic_env["output_dir"].parent],
    )

    # 1. Missing evidence_type in dictionary format must raise ValueError (must not be swallowed by try/except)
    ann_bad_dict = synthetic_env["raw_dir"] / "ann_missing_ev_type.json"
    ann_bad_dict.write_text(json.dumps({
        "pilot_id": "PILOT-TEST",
        "3": {
            "quote": "some quote",
            "rationale_en": "some rationale",
            # missing evidence_type!
        }
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required 'evidence_type'"):
        orch.normalize_reading_pilot(
            doc_legacy_id="SRC-999",
            key_legacy_id="SRC-998",
            annotations_path=ann_bad_dict,
            force=True,
        )

    # 2. Invalid evidence_type must raise ValueError
    ann_bad_type = synthetic_env["raw_dir"] / "ann_bad_type.json"
    ann_bad_type.write_text(json.dumps({
        "pilot_id": "PILOT-TEST",
        "3": {
            "evidence_type": "bogus_unsupported_evidence_type",
            "quote": "some quote",
        }
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid evidence_type"):
        orch.normalize_reading_pilot(
            doc_legacy_id="SRC-999",
            key_legacy_id="SRC-998",
            annotations_path=ann_bad_type,
            force=True,
        )

    # 3. Invalid annotation key (not int and not metadata key) must raise ValueError
    ann_bad_key = synthetic_env["raw_dir"] / "ann_bad_key.json"
    ann_bad_key.write_text(json.dumps({
        "pilot_id": "PILOT-TEST",
        "invalid_key_name": {
            "evidence_type": "direct_support",
            "quote": "some quote",
        }
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid annotation key"):
        orch.normalize_reading_pilot(
            doc_legacy_id="SRC-999",
            key_legacy_id="SRC-998",
            annotations_path=ann_bad_key,
            force=True,
        )



