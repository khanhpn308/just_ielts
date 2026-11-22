"""Automated tests for Reading DOCX and PDF normalizers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from harness.normalizers.reading_docx import (
    DocxReadingNormalizer,
    detect_question_type_from_instructions,
    detect_word_limit_rule,
    segment_joined_questions,
)
from harness.normalizers.reading_pdf import PdfReadingNormalizer

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "v02"


def test_segment_joined_questions_standard_fixtures():
    """Verify segmentation on standard synthetic test cases."""
    fixture_path = FIXTURES_DIR / "joined_questions_synthetic.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        cases = json.load(f)["fixtures"]

    for case in cases:
        start_n, end_n = case["expected_range"]
        input_text = case["input_text"]
        items, flags = segment_joined_questions(input_text, start_n, end_n)

        if case.get("should_fail_or_flag_review"):
            assert case["expected_flag"] in flags
        else:
            assert len(items) == case["expected_count"]
            for i, expected in enumerate(case["expected_items"]):
                assert items[i]["number"] == expected["number"]
                assert items[i]["prompt"] == expected["prompt"]


def test_segment_joined_questions_numeric_distractors():
    """Verify delimiter regex ignores numbers inside body text without uppercase lookahead."""
    text = (
        "1 In 1980 the committee established 2 distinct research branches.2 Approximately "
        "25 percent of respondents approved of the initiative.3 Over 50 countries participated."
    )
    items, flags = segment_joined_questions(text, 1, 3)
    assert not flags
    assert len(items) == 3
    assert items[0]["number"] == 1
    assert "established 2 distinct research branches." in items[0]["prompt"]
    assert items[1]["number"] == 2
    assert "25 percent" in items[1]["prompt"]
    assert items[2]["number"] == 3
    assert "Over 50 countries participated." in items[2]["prompt"]


def test_segment_joined_questions_missing_number():
    """Verify missing question numbers in sequence trigger sequence gap flag."""
    text = "1 First question text.3 Third question text."
    items, flags = segment_joined_questions(text, 1, 3)
    assert "SEGMENTATION_SEQUENCE_GAP" in flags
    assert len(items) == 0


def test_detect_question_type():
    assert detect_question_type_from_instructions("write TRUE, FALSE, or NOT GIVEN") == "true-false-not-given"
    assert detect_question_type_from_instructions("write YES, NO, or NOT GIVEN") == "yes-no-not-given"
    assert detect_question_type_from_instructions("Complete the notes below.") == "note-completion"
    assert detect_question_type_from_instructions("Complete the summary below.") == "summary-completion"
    assert detect_question_type_from_instructions("Choose the correct heading for each paragraph") == "matching-headings"
    assert detect_question_type_from_instructions("Choose the correct letter, A, B, C or D.") == "multiple-choice-single"


def test_detect_word_limit():
    assert detect_word_limit_rule("Choose ONE WORD ONLY from the passage.") == "one_word_only"
    assert detect_word_limit_rule("Write NO MORE THAN TWO WORDS AND/OR A NUMBER.") == "no_more_than_two_words_and_or_a_number"
    assert detect_word_limit_rule("Write NO MORE THAN THREE WORDS.") == "no_more_than_three_words"
    assert detect_word_limit_rule("Do the following statements agree...") is None


def test_docx_reading_normalizer_synthetic():
    normalizer = DocxReadingNormalizer()
    synthetic_doc = {
        "content": {
            "paragraphs": [
                {"text": "TEST 1"},
                {"text": "READING PASSAGE 1"},
                {"text": "You should spend about 20 minutes on Questions 1-3..."},
                {"text": "Synthetic Marine Energy Research"},
                {
                    "text": (
                        "A Ocean tidal power systems generate predictable kinetic electricity through marine current turbines. "
                        "These submerged hydrokinetic generators harvest energy directly from gravitational sea movements without "
                        "requiring expansive barrage dams or causing significant environmental disruption to coastal ecosystems."
                    )
                },
                {
                    "text": (
                        "B Turbines anchored in deep water channels experience minimal cavitation compared to shallow installations. "
                        "Subsea engineering teams utilize corrosion resistant alloys and modular composite blades to withstand severe "
                        "saline hydrostatic pressures while maintaining operational reliability across prolonged deployment cycles."
                    )
                },
                {"text": "Questions 1-3"},
                {"text": "Do the following statements agree with the information given in Reading Passage 1? Write TRUE, FALSE or NOT GIVEN."},
                {"text": "1 Tidal power produces kinetic electricity.2 Deep water channels suffer significant cavitation.3 Global deployment costs increased in 2020."},
            ]
        }
    }
    source_rec = {
        "file_id": "FILE-000000000001",
        "legacy_id": "SRC-999",
        "relative_path": "synthetic/sample.docx",
        "content_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }

    res = normalizer.normalize(
        raw_document=synthetic_doc,
        source_record=source_rec,
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
        publication_permission="public_synthetic",
    )

    assert res["test"].test_id == "TEST-IELTS-VOL99-01-ACAD"
    assert res["passage"].passage_id == "PASSAGE-VOL99-01-RD01"
    assert len(res["passage"].paragraphs) == 2
    assert len(res["groups"]) == 1
    assert res["groups"][0].question_type == "true-false-not-given"
    assert len(res["questions"]) == 3
    assert res["questions"][0].question_number == 1
    assert res["questions"][0].prompt_text == "Tidal power produces kinetic electricity."
    assert res["questions"][1].question_number == 2
    assert res["questions"][2].question_number == 3


def test_pdf_reading_normalizer_synthetic():
    normalizer = PdfReadingNormalizer()
    pages = [
        {
            "content": {
                "page_number": 1,
                "text": (
                    "Synthetic Advanced Materials in Modern Aeronautical Engineering\n\n"
                    "High performance carbon fibers provide exceptional structural resilience for lightweight aerospace vehicles. "
                    "Polymer composite manufacturing significantly reduces parasitic structural mass in modern electric commercial aircraft. "
                    "Advanced thermosetting resin matrices reinforce long strand fibers against high stress fatigue and thermal shocks.\n\n"
                    "Aerospace engineers thoroughly test component elasticity under extreme cyclic vibration and turbulence loading scenarios. "
                    "Novel thermoplastic tape placement methods enable rapid fabrication of complex fuselage geometry with zero defect rates.\n\n"
                    "Questions 1-2\n\n"
                    "Do the following statements agree with the text?\n"
                    "1 Carbon fibers improve vehicle durability.\n"
                    "2 Electric airplanes require heavier metallic fuselages.\n"
                ),
                "ocr_applied": False,
            }
        }
    ]
    source_rec = {
        "file_id": "FILE-000000000002",
        "legacy_id": "SRC-998",
        "relative_path": "synthetic/sample.pdf",
        "content_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }

    res = normalizer.normalize(
        pages=pages,
        source_record=source_rec,
        test_number=1,
        passage_number=1,
        volume_code="VOL99",
        publication_permission="public_synthetic",
    )

    assert res["test"].test_id == "TEST-IELTS-VOL99-01-ACAD"
    assert res["passage"].passage_id == "PASSAGE-VOL99-01-RD01"
    assert len(res["questions"]) >= 2


def test_pdf_reading_cross_test_isolation_test_5_and_6():
    """Verify Issue 1: multi-test PDF with Test 5 and Test 6 isolations.

    - Requesting Test 6 returns only Test 6 content, 0 Test 5 questions.
    - Requesting Test 5 returns only Test 5 content, 0 Test 6 questions.
    - Requesting Test 99 fails cleanly without emitting entities.
    - Accurate page and source provenance is preserved.
    """
    normalizer = PdfReadingNormalizer()
    pages = [
        {
            "content": {
                "page_number": 1,
                "text": (
                    "TEST 5\n"
                    "READING PASSAGE 1\n"
                    "Deep Sea Hydrothermal Vent Ecology\n"
                    "Hydrothermal vent ecosystems survive entirely independent of sunlight energy inputs through geothermal chemical pathways. "
                    "Specialized chemosynthetic bacteria oxidize toxic hydrogen sulfide compounds emitted from subterranean seafloor fissures. "
                    "These primary producers sustain dense colonies of giant tube worms and vent shrimp in high hydrostatic pressure environments. "
                    "Marine ecologists utilize autonomous submersibles to survey fragile vent fields without disturbing sensitive geochemical formations. "
                    "Long-term benthic monitoring indicates hydrothermal communities remain stable despite sudden volcanic interruptions and seismic shifts.\n\n"
                    "Questions 1-2\n"
                    "Do the following statements agree with the information given in the passage?\n"
                    "1 Chemosynthetic bacteria require direct sunlight for metabolic growth.\n"
                    "2 Deep sea vent ecosystems withstand major seismic disruptions.\n"
                ),
                "ocr_applied": False,
            }
        },
        {
            "content": {
                "page_number": 2,
                "text": (
                    "TEST 6\n"
                    "READING PASSAGE 1\n"
                    "Autonomous Unmanned Aerial Systems in Agricultural Surveying\n"
                    "Precision agriculture increasingly relies upon autonomous aerial imaging drones to monitor crop vitality across expansive farmland. "
                    "Multispectral optical sensors capture narrow wavelength infrared reflections indicating chlorophyll health and soil moisture deficits. "
                    "Agricultural data pipelines automatically synthesize multi-gigabyte orthomosaic maps within hours of completing systematic flight transects. "
                    "Early detection of subterranean fungal pathogens enables targeted fungicide applications, drastically minimizing chemical run-off hazards. "
                    "Agronomists report that mechanized drone surveys produce significant cost reductions compared to traditional manned aircraft operations.\n\n"
                    "Questions 1-2\n"
                    "Do the following statements agree with the information given in the passage?\n"
                    "1 Multispectral sensors detect variations in plant chlorophyll health.\n"
                    "2 Drone surveys cost more than manned aircraft imaging operations.\n"
                ),
                "ocr_applied": False,
            }
        },
    ]
    source_rec = {
        "file_id": "FILE-000000000005",
        "legacy_id": "SRC-005",
        "relative_path": "synthetic/tests_5_and_6.pdf",
        "content_sha256": "5" * 64,
    }

    # 1. Requesting Test 99 must fail without emitting entities
    with pytest.raises(ValueError, match="Requested Test 99 not found in PDF page boundaries"):
        normalizer.normalize(
            pages=pages,
            source_record=source_rec,
            test_number=99,
            passage_number=1,
            volume_code="VOL06",
        )

    # 2. Requesting Test 6 returns only Test 6 content and 0 Test 5 questions
    res6 = normalizer.normalize(
        pages=pages,
        source_record=source_rec,
        test_number=6,
        passage_number=1,
        volume_code="VOL06",
    )
    assert res6["test"].test_number == 6
    assert res6["test"].test_id == "TEST-IELTS-VOL06-06-ACAD"
    assert res6["passage"].title == "Autonomous Unmanned Aerial Systems in Agricultural Surveying"
    assert res6["passage"].passage_id == "PASSAGE-VOL06-06-RD01"
    assert len(res6["questions"]) == 2
    assert res6["questions"][0].prompt_text == "Multispectral sensors detect variations in plant chlorophyll health."
    assert res6["questions"][1].prompt_text == "Drone surveys cost more than manned aircraft imaging operations."
    # Ensure zero Test 5 content or questions leaked into Test 6
    for q in res6["questions"]:
        assert "chemosynthetic" not in q.prompt_text.lower()
        assert "vent" not in q.prompt_text.lower()
    assert "hydrothermal" not in res6["passage"].narrative_text.lower()
    # Provenance must point strictly to page 2
    assert res6["test"].provenance.unit_identifier == "page_0002"
    assert res6["test"].provenance.raw_block_locator == "page:2"
    assert res6["passage"].provenance.unit_identifier == "page_0002"
    assert res6["passage"].provenance.raw_block_locator == "page:2"

    # 3. Requesting Test 5 returns only Test 5 content and 0 Test 6 questions
    res5 = normalizer.normalize(
        pages=pages,
        source_record=source_rec,
        test_number=5,
        passage_number=1,
        volume_code="VOL06",
    )
    assert res5["test"].test_number == 5
    assert res5["test"].test_id == "TEST-IELTS-VOL06-05-ACAD"
    assert res5["passage"].title == "Deep Sea Hydrothermal Vent Ecology"
    assert len(res5["questions"]) == 2
    assert res5["questions"][0].prompt_text == "Chemosynthetic bacteria require direct sunlight for metabolic growth."
    assert res5["questions"][1].prompt_text == "Deep sea vent ecosystems withstand major seismic disruptions."
    # Ensure zero Test 6 content or questions leaked into Test 5
    for q in res5["questions"]:
        assert "multispectral" not in q.prompt_text.lower()
        assert "drone" not in q.prompt_text.lower()
    assert "agriculture" not in res5["passage"].narrative_text.lower()
    # Provenance must point strictly to page 1
    assert res5["test"].provenance.unit_identifier == "page_0001"
    assert res5["test"].provenance.raw_block_locator == "page:1"


def test_pdf_reading_missing_passage_boundary_rejected():
    """Verify rejection of missing or ambiguous passage boundaries."""
    normalizer = PdfReadingNormalizer()
    pages = [
        {
            "content": {
                "page_number": 1,
                "text": (
                    "TEST 6\n"
                    "READING PASSAGE 1\n"
                    "Autonomous Unmanned Aerial Systems in Agricultural Surveying\n"
                    "Precision agriculture increasingly relies upon autonomous aerial imaging drones to monitor crop vitality across expansive farmland. "
                    "Multispectral optical sensors capture narrow wavelength infrared reflections indicating chlorophyll health and soil moisture deficits. "
                    "Agricultural data pipelines automatically synthesize multi-gigabyte orthomosaic maps within hours of completing systematic flight transects. "
                    "Early detection of subterranean fungal pathogens enables targeted fungicide applications, drastically minimizing chemical run-off hazards. "
                    "Agronomists report that mechanized drone surveys produce significant cost reductions compared to traditional manned aircraft operations.\n\n"
                    "Questions 1-2\n"
                    "Do the following statements agree with the information given in the passage?\n"
                    "1 Multispectral sensors detect variations in plant chlorophyll health.\n"
                    "2 Drone surveys cost more than manned aircraft imaging operations.\n"
                ),
            }
        }
    ]
    source_rec = {
        "file_id": "FILE-000000000006",
        "legacy_id": "SRC-006",
        "relative_path": "synthetic/test_6.pdf",
        "content_sha256": "6" * 64,
    }

    # Passage 2 does not exist in Test 6; must fail without emitting entities
    with pytest.raises(ValueError, match="Reading Passage 2 not found for Test 6"):
        normalizer.normalize(
            pages=pages,
            source_record=source_rec,
            test_number=6,
            passage_number=2,
            volume_code="VOL06",
        )


def test_pdf_reading_unsafe_fallbacks_rejected():
    """Verify Issue 2: removal of unsafe fallbacks.

    1. Missing question markers: no 60% document split; explicit failure.
    2. Missing question range: no invented question ranges; explicit failure.
    3. Missing instruction text: no fabricated default instruction text; uses verbatim header and review_required.
    4. Text padding: truncated narrative text rejected explicitly without padding.
    """
    normalizer = PdfReadingNormalizer()
    source_rec = {
        "file_id": "FILE-000000000007",
        "legacy_id": "SRC-007",
        "relative_path": "synthetic/fallback_test.pdf",
        "content_sha256": "7" * 64,
        "collection": "synthetic",
    }

    # 1. No question marker -> must fail explicitly (no 60% split)
    pages_no_q = [
        {
            "content": {
                "page_number": 1,
                "text": (
                    "Marine Hydrodynamics and Tidal Energy Generation Systems\n\n"
                    "Tidal turbine arrays generate predictable baseload power without requiring expansive hydraulic reservoir dams. "
                    "Subsea mechanical components must endure severe cyclic hydrodynamic shear forces during maximum tidal flow velocity phases. "
                    "Corrosion resistant titanium composites extend operational lifespans under aggressive saline marine conditions.\n\n"
                    "Comprehensive acoustic surveys confirm that low speed turbine rotation does not significantly alter benthic marine mammal migration corridors. "
                    "Further technological advancements in modular turbine power trains promise substantial decreases in offshore installation capital costs.\n"
                ),
            }
        }
    ]
    with pytest.raises(ValueError, match="No question marker found in passage content"):
        normalizer.normalize(
            pages=pages_no_q,
            source_record=source_rec,
            test_number=1,
            passage_number=1,
            volume_code="VOL01",
        )

    # 2. Group header without range -> must fail explicitly (no invented range)
    pages_no_range = [
        {
            "content": {
                "page_number": 1,
                "text": (
                    "Marine Hydrodynamics and Tidal Energy Generation Systems\n\n"
                    "Tidal turbine arrays generate predictable baseload power without requiring expansive hydraulic reservoir dams. "
                    "Subsea mechanical components must endure severe cyclic hydrodynamic shear forces during maximum tidal flow velocity phases. "
                    "Corrosion resistant titanium composites extend operational lifespans under aggressive saline marine conditions.\n\n"
                    "Comprehensive acoustic surveys confirm that low speed turbine rotation does not significantly alter benthic marine mammal migration corridors. "
                    "Further technological advancements in modular turbine power trains promise substantial decreases in offshore installation capital costs.\n\n"
                    "Questions\n"
                    "Do the following statements agree with the text?\n"
                    "1 Tidal turbines generate predictable power.\n"
                ),
            }
        }
    ]
    with pytest.raises(ValueError, match="Could not determine question range from group header"):
        normalizer.normalize(
            pages=pages_no_range,
            source_record=source_rec,
            test_number=1,
            passage_number=1,
            volume_code="VOL01",
        )

    # 3. Missing instruction text -> no default fabricated instruction; captures header & flags review_required
    pages_no_instr = [
        {
            "content": {
                "page_number": 1,
                "text": (
                    "Marine Hydrodynamics and Tidal Energy Generation Systems\n\n"
                    "Tidal turbine arrays generate predictable baseload power without requiring expansive hydraulic reservoir dams. "
                    "Subsea mechanical components must endure severe cyclic hydrodynamic shear forces during maximum tidal flow velocity phases. "
                    "Corrosion resistant titanium composites extend operational lifespans under aggressive saline marine conditions.\n\n"
                    "Comprehensive acoustic surveys confirm that low speed turbine rotation does not significantly alter benthic marine mammal migration corridors. "
                    "Further technological advancements in modular turbine power trains promise substantial decreases in offshore installation capital costs.\n\n"
                    "Questions 1-2\n"
                    "1 Tidal turbines generate predictable power.\n"
                    "2 Modular power trains increase installation expenses.\n"
                ),
            }
        }
    ]
    res_no_instr = normalizer.normalize(
        pages=pages_no_instr,
        source_record=source_rec,
        test_number=1,
        passage_number=1,
        volume_code="VOL01",
    )
    group = res_no_instr["groups"][0]
    # Instruction text must NOT be the fabricated string
    assert "Do the following statements agree" not in group.instruction_text
    assert group.instruction_text == "Questions 1-2"
    assert group.quality_profile.lifecycle_status == "review_required"
    assert "MISSING_INSTRUCTION_TEXT" in res_no_instr["test"].quality_profile.validation_flags

    # 4. Truncated narrative text -> must fail explicitly without text padding
    pages_short_narrative = [
        {
            "content": {
                "page_number": 1,
                "text": (
                    "Short Title\n\n"
                    "Short text.\n\n"
                    "Questions 1-2\n"
                    "Do the following statements agree?\n"
                    "1 Short text question one.\n"
                    "2 Short text question two.\n"
                ),
            }
        }
    ]
    with pytest.raises(ValueError, match="Extracted passage narrative text is insufficient or truncated"):
        normalizer.normalize(
            pages=pages_short_narrative,
            source_record=source_rec,
            test_number=1,
            passage_number=1,
            volume_code="VOL01",
        )

