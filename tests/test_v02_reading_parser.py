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
