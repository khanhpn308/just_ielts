"""Tests for IELTS Vocabulary Knowledge Base (V1.0).

Follows repository standards:
- Non-corpus unit tests run in standard CI without requiring private raw PDFs or private databases.
- Public tests use synthetic fixtures (no copyrighted textbook excerpts).
- Real PDF/corpus integration tests are marked with @pytest.mark.corpus and executed with --corpus.
"""

import datetime
import json
from pathlib import Path
import pytest

from harness.config import REPO_ROOT
from harness.vocabulary.inventory import (
    build_source_inventory,
    VOCAB_RAW_DIR,
    VOCAB_KB_DIR,
    SOURCE_METADATA_CONFIG,
)
from harness.vocabulary.taxonomy import TOPIC_TAXONOMY, LANGUAGE_FUNCTIONS, classify_topics_by_keywords
from harness.vocabulary.unit_indexer import build_unit_and_topic_indexes
from harness.vocabulary.parser import FamilyAParser, FamilyBParser, FamilyCParser
from harness.vocabulary.kb import (
    normalize_expression,
    build_entry_key,
    build_knowledge_base,
    get_unit_details,
    query_vocabulary_by_topic,
    query_collocations_by_topic,
    query_paraphrases_by_topic,
    get_exercise_with_hidden_answer,
    merge_lexical_entries,
    KB_VOCAB_FILE,
    KB_COLLOCATIONS_FILE,
    KB_PARAPHRASES_FILE,
    KB_EXERCISES_FILE,
    KB_ANSWER_KEYS_FILE,
    KB_LEXICAL_INDEX_FILE,
)
from harness.vocabulary.session import (
    parse_learning_intent,
    load_curriculum_state,
    save_curriculum_state,
    load_vocabulary_journal,
    assess_and_schedule_item,
    save_vocabulary_batch,
    get_due_vocabulary,
    execute_tutor_command,
    STAGE_GAPS,
)
from harness.vocabulary.enrichment import (
    extract_unit_vocabulary_candidates,
    build_tutor_enriched_item,
    enrich_unit_pipeline,
)


# ==============================================================================
# Pure CI Unit Tests (Zero dependency on private PDFs, 100% synthetic fixtures)
# ==============================================================================

def test_taxonomy_and_language_functions():
    """Validates 20 shared topics and 14 academic language functions."""
    assert len(TOPIC_TAXONOMY) == 20
    assert "education_and_learning" in TOPIC_TAXONOMY
    assert "environment_and_climate" in TOPIC_TAXONOMY
    assert "work_and_careers" in TOPIC_TAXONOMY

    assert len(LANGUAGE_FUNCTIONS) == 14
    assert "cause_and_effect" in LANGUAGE_FUNCTIONS
    assert "argumentation" in LANGUAGE_FUNCTIONS
    assert "register" in LANGUAGE_FUNCTIONS

    # Test keyword classifier with synthetic prompt
    topics = classify_topics_by_keywords("Higher education and university degrees")
    assert "education_and_learning" in topics


def test_lexical_normalization_and_entry_key():
    """Validates lemma normalization and unique compound entry key creation."""
    assert normalize_expression("  Synthetic Term  ") == "synthetic term"
    assert normalize_expression("Acquire Knowledge...") == "acquire knowledge"

    key = build_entry_key("Synthetic Term", "phrase", "test definition sense")
    assert key == "synthetic term|phrase|test definition sense"


def test_intent_parser_for_tutor_commands():
    """Validates deterministic natural language command recognition for IELTS Tutor."""
    # 1. Unit commands
    r1 = parse_learning_intent("Học IVU-60 Unit 1.")
    assert r1["intent"] == "LEARN_UNIT"
    assert r1["source_id"] == "IVU-60"
    assert r1["unit_number"] == 1
    assert r1["unit_key"] == "IVU-60-U001"

    r2 = parse_learning_intent("Học EVU-B2 Unit 14.")
    assert r2["intent"] == "LEARN_UNIT"
    assert r2["source_id"] == "EVU-B2"
    assert r2["unit_number"] == 14
    assert r2["unit_key"] == "EVU-B2-U014"

    # 2. Topic command
    r3 = parse_learning_intent("Học từ vựng chủ đề Education.")
    assert r3["intent"] == "LEARN_TOPIC"
    assert r3["topic_id"] == "education_and_learning"

    # 3. Next unit command
    r4 = parse_learning_intent("Học Unit tiếp theo.")
    assert r4["intent"] == "LEARN_NEXT_UNIT"

    # 4. Spaced review command
    r5 = parse_learning_intent("Ôn từ vựng hôm nay.")
    assert r5["intent"] == "REVIEW_DUE_VOCABULARY"

    # 5. Consent command
    r6 = parse_learning_intent("Lưu kết quả buổi học")
    assert r6["intent"] == "SAVE_PROGRESS"
    assert r6["user_consented"] is True


def test_pr10_spaced_repetition_and_consent_contract(tmp_path):
    """Ensures Level 0-3, Stage 0-5 gaps, same-day duplicate prevention, and consent requirement."""
    p_file = tmp_path / "vocabulary.jsonl"
    d0 = datetime.date(2026, 1, 1)

    # 1. Day 1: New item taught (not assessed yet)
    rec1 = assess_and_schedule_item(
        existing_record=None,
        expression="synthetic verb",
        pos="verb",
        sense_key="to perform testing",
        meaning_vi="thử nghiệm tổng hợp",
        level=0,
        outcome="not_assessed",
        session_date=d0,
    )
    assert rec1["review_stage"] == 0
    assert rec1["review_count"] == 0
    assert rec1["last_review_date"] is None
    assert rec1["next_review_date"] == "2026-01-02"

    # Saving WITHOUT consent must fail and not create the file
    res_unapproved = save_vocabulary_batch([rec1], user_consented=False, progress_file=p_file)
    assert res_unapproved["saved"] is False
    assert not p_file.exists()

    # Saving WITH consent persists the item
    res_approved = save_vocabulary_batch([rec1], user_consented=True, progress_file=p_file)
    assert res_approved["saved"] is True
    assert p_file.exists()
    assert len(load_vocabulary_journal(p_file)) == 1

    # 2. Day 2: Due review with successful unaided recall (Level 2)
    d1 = datetime.date(2026, 1, 2)
    due_items = get_due_vocabulary("2026-01-02", progress_file=p_file)
    assert len(due_items) == 1

    rec2 = assess_and_schedule_item(
        existing_record=rec1,
        expression="synthetic verb",
        pos="verb",
        sense_key="to perform testing",
        meaning_vi="thử nghiệm tổng hợp",
        level=2,
        session_date=d1,
    )
    # Stage advances 0 -> 1 (gap = STAGE_GAPS[1] = 2 days: 2026-01-02 + 2 days = 2026-01-04)
    assert rec2["review_stage"] == 1
    assert rec2["next_review_date"] == "2026-01-04"
    assert rec2["review_count"] == 1
    save_vocabulary_batch([rec2], user_consented=True, progress_file=p_file)

    # 3. Same-day practice on Day 2: cannot advance stage twice in one calendar day
    rec2_retry = assess_and_schedule_item(
        existing_record=rec2,
        expression="synthetic verb",
        pos="verb",
        sense_key="to perform testing",
        meaning_vi="thử nghiệm tổng hợp",
        level=3,
        session_date=d1,
    )
    assert rec2_retry["review_stage"] == 1  # Unchanged, still 1!
    assert rec2_retry["review_count"] == 1  # Not double-counted!
    assert rec2_retry["next_review_date"] == "2026-01-04"

    # 4. Same-day observed failure on Day 2: resets stage to 0 and reschedules tomorrow
    rec2_failed = assess_and_schedule_item(
        existing_record=rec2,
        expression="synthetic verb",
        pos="verb",
        sense_key="to perform testing",
        meaning_vi="thử nghiệm tổng hợp",
        level=0,
        outcome="failed",
        session_date=d1,
    )
    assert rec2_failed["review_stage"] == 0
    assert rec2_failed["next_review_date"] == "2026-01-03"


def test_no_fabricated_defaults_in_enrichment():
    """Ensures enrichment does not fabricate fake default IPA, CEFR, register or definitions."""
    candidate = {
        "expression": "synthetic collocation",
        "source_context": "Synthetic collocation occurs in laboratory experiments.",
        "source_gloss": "collocation for testing",
        "extraction_method": "source_collocation_phrase",
        "source_provenance": {
            "source_id": "SYNTH-SRC",
            "unit_key": "SYNTH-U01",
            "page": 1,
        },
    }

    # Tutor enriches only Vietnamese meaning, leaving unverified fields None
    item = build_tutor_enriched_item(
        candidate=candidate,
        pos="noun",
        sense_key="laboratory test concept",
        meaning_vi="khái niệm thử nghiệm tổng hợp",
        us_ipa=None,
        cefr_level=None,
        register=None,
    )

    # Must NOT have fabricated fake defaults
    assert item["us_ipa"] is None
    assert item["cefr_level"] is None
    assert item["register"] is None
    assert item["meaning_vi"] == "khái niệm thử nghiệm tổng hợp"
    assert item["provenance_metadata"]["enrichment_agent"] == "tutor_agent"
    assert item["provenance_metadata"]["source_grounded"] is True


def test_merge_lexical_entries_preserves_sources():
    """Ensures merging preserves all valid source references and deduplicates by entry_key."""
    item1 = {
        "expression": "lead",
        "pos": "verb",
        "sense_key": "guide",
        "sources": [{"source_id": "SRC-A", "unit_key": "U01", "physical_page": 10}],
    }
    item2 = {
        "expression": "lead",
        "pos": "verb",
        "sense_key": "guide",
        "meaning_vi": "dẫn đường",
        "sources": [{"source_id": "SRC-B", "unit_key": "U05", "physical_page": 22}],
    }

    merged = merge_lexical_entries(item1, item2)
    assert len(merged["sources"]) == 2
    assert merged["meaning_vi"] == "dẫn đường"


def test_isolated_curriculum_state_consent(tmp_path):
    """Ensures curriculum progress is not saved to disk without consent."""
    c_file = tmp_path / "curriculum.json"

    state0 = load_curriculum_state(c_file)
    state0["current_unit_key"] = "IVU-60-U002"

    # Without consent: does not write to disk
    saved = save_curriculum_state(state0, c_file, user_consented=False)
    assert saved is False
    assert not c_file.exists()

    # With consent: persists
    saved = save_curriculum_state(state0, c_file, user_consented=True)
    assert saved is True
    assert c_file.exists()
    assert load_curriculum_state(c_file)["current_unit_key"] == "IVU-60-U002"


# ==============================================================================
# Corpus Integration Tests (Requires private/raw/ corpus files)
# ==============================================================================

@pytest.mark.corpus
def test_source_inventory():
    """Validates that all eight textbooks are inventoried with correct metadata and SHA-256."""
    inv = build_source_inventory()
    sources = inv["sources"]
    assert len(sources) == 8

    expected_ids = ["EVU-B2", "EVU-ADV", "ECI-INT", "ECI-ADV", "AVU", "IVU-60", "IVU-65", "NB-PARA"]
    for sid in expected_ids:
        assert sid in sources
        s = sources[sid]
        assert s["source_id"] == sid
        assert Path(REPO_ROOT / s["relative_path"]).exists()
        assert len(s["sha256"]) == 64
        assert s["pdf_page_count"] > 0
        assert s["unit_count"] > 0

    assert sources["AVU"]["edition"] == "Second Edition"
    assert sources["EVU-ADV"]["unit_count"] == 101


@pytest.mark.corpus
def test_unit_and_topic_indexes():
    """Validates structural unit index count (433 units) and 20-topic taxonomy."""
    unit_idx, topic_idx = build_unit_and_topic_indexes()
    assert len(unit_idx) == 433
    assert len(topic_idx) == 20
    assert "EVU-ADV-U101" in unit_idx


@pytest.mark.corpus
def test_parsers_family_a_b_c_with_composite_ids():
    """Validates representative unit extraction across all three parsing families with composite IDs."""
    unit_idx, _ = build_unit_and_topic_indexes()

    # Family A: EVU-B2 Unit 14 (Education)
    p_a = FamilyAParser("EVU-B2")
    res_a = p_a.parse_unit(unit_idx["EVU-B2-U014"])
    assert res_a["unit_key"] == "EVU-B2-U014"
    assert len(res_a["exercises"]) >= 1
    # Check composite exercise ID format: EX-EVU-B2-U014-14.1
    assert any("EX-EVU-B2-U014-14.1" in ex["exercise_id"] for ex in res_a["exercises"])
    assert res_a["answer_key"]["verification_status"] == "authoritative_textbook_key"
    assert "14.1" in res_a["answer_key"]["answers"]

    # Family B: IVU-60 Unit 1 (Growing up)
    p_b = FamilyBParser("IVU-60")
    res_b = p_b.parse_unit(unit_idx["IVU-60-U001"])
    assert res_b["unit_key"] == "IVU-60-U001"
    assert res_b["answer_key"]["verification_status"] == "uncertain_ocr_key"

    # Family C: NB-PARA Education Section
    p_c = FamilyCParser()
    res_c = p_c.parse_section(unit_idx["NB-PARA-PRAC-EDU"])
    assert res_c["unit_key"] == "NB-PARA-PRAC-EDU"
    assert len(res_c["paraphrase_groups"]) >= 5


@pytest.mark.corpus
def test_generalized_on_demand_enrichment_outside_education():
    """Demonstrates generalized on-demand enrichment on an arbitrary unit (ECI-INT-U030 Work)."""
    tutor_enrichments = [
        {
            "expression": "high-powered job",
            "pos": "phrase",
            "sense_key": "an important job with high responsibility",
            "us_ipa": "/ˌhaɪˈpaʊ.ɚd dʒɑːb/",
            "meaning_vi": "công việc quyền cao chức trọng",
            "collocations": ["hold a high-powered job"],
        }
    ]

    # First run: extracts candidates and persists enriched item
    res1 = enrich_unit_pipeline("ECI-INT-U030", tutor_enrichments=tutor_enrichments, force_reextract=True)
    assert res1["from_cache"] is False
    assert len(res1["candidates"]) > 0
    assert len(res1["enriched_unit"]["enriched_vocabulary"]) >= 1
    assert res1["enriched_unit"]["enriched_vocabulary"][0]["provenance_metadata"]["enrichment_agent"] == "tutor_agent"

    # Second run: instant cache hit
    res2 = enrich_unit_pipeline("ECI-INT-U030", force_reextract=False)
    assert res2["from_cache"] is True
    assert res2["elapsed_seconds"] < 0.1
