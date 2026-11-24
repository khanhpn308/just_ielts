"""Tests for IELTS Vocabulary Knowledge Base (V1.0).

Follows repository standards:
- Non-corpus unit tests run in standard CI without requiring private raw PDFs or private databases.
- Real PDF/corpus integration tests are marked with @pytest.mark.corpus and executed with --corpus.
"""

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
    record_vocabulary_review,
    get_due_vocabulary,
    execute_tutor_command,
)
from harness.vocabulary.enrichment import enrich_lexical_item, enrich_unit_pipeline


# ==============================================================================
# Pure CI Unit Tests (Zero dependency on private PDFs or private databases)
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

    # Test keyword classifier
    topics = classify_topics_by_keywords("Higher education and university degrees")
    assert "education_and_learning" in topics


def test_lexical_normalization_and_entry_key():
    """Validates lemma normalization and unique compound entry key creation."""
    assert normalize_expression("  Tertiary Education  ") == "tertiary education"
    assert normalize_expression("Acquire Knowledge...") == "acquire knowledge"

    key = build_entry_key("Acquire Knowledge", "phrase", "gain knowledge through learning")
    assert key == "acquire knowledge|phrase|gain knowledge through learning"


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


def test_isolated_curriculum_state_persistence(tmp_path):
    """Ensures curriculum progress can be saved and resumed in isolation."""
    c_file = tmp_path / "curriculum.json"

    # Initial state (defaults to first backbone unit)
    state0 = load_curriculum_state(c_file)
    assert state0["current_unit_key"] == "IVU-60-U001"

    # Update state
    state0["current_unit_key"] = "IVU-60-U002"
    state0["completed_units"].append("IVU-60-U001")
    save_curriculum_state(state0, c_file)

    # Resume state
    state1 = load_curriculum_state(c_file)
    assert state1["current_unit_key"] == "IVU-60-U002"
    assert "IVU-60-U001" in state1["completed_units"]
    assert state1["last_updated"] is not None


def test_isolated_spaced_repetition_review(tmp_path):
    """Ensures due vocabulary items are correctly tracked and queried."""
    p_file = tmp_path / "vocabulary.jsonl"

    # No items initially
    assert len(get_due_vocabulary(progress_file=p_file)) == 0

    # Record review due today
    record_vocabulary_review(
        item_id="VOC-TEST-001",
        expression="tertiary education",
        success=False,
        progress_file=p_file,
        interval_days=0,
    )

    due = get_due_vocabulary(progress_file=p_file)
    assert len(due) == 1
    assert due[0]["item_id"] == "VOC-TEST-001"
    assert due[0]["expression"] == "tertiary education"


def test_enrich_lexical_item_schema():
    """Validates LexicalEntry schema generation."""
    item = enrich_lexical_item(
        item_id="VOC-TEST-002",
        expression="red tape",
        unit_info={"source_id": "EVU-ADV", "unit_key": "EVU-ADV-U101", "title": "Red tape", "physical_pages": [210, 211]},
        context_sentence="There is too much red tape involved in applying for a visa.",
        meaning_vi="thủ tục hành chính rườm rà",
        meaning_en="official rules and processes that seem unnecessary",
        us_ipa="/ˌred ˈteɪp/",
        uk_ipa="/ˌred ˈteɪp/",
        pos="noun",
        cefr_level="C1",
        collocations=["cut red tape"],
        common_mistakes="'Red tape' is uncountable.",
    )
    assert item["item_id"] == "VOC-TEST-002"
    assert item["expression"] == "red tape"
    assert item["lemma"] == "red tape"
    assert item["pos"] == "noun"
    assert item["cefr_level"] == "C1"
    assert item["countability"] == "uncountable"
    assert item["collocations"] == ["cut red tape"]
    assert len(item["sources"]) == 1
    assert item["sources"][0]["unit_key"] == "EVU-ADV-U101"


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

    # Edition check for AVU (Second Edition)
    assert sources["AVU"]["edition"] == "Second Edition"

    # Unit count check for EVU-ADV (101 units)
    assert sources["EVU-ADV"]["unit_count"] == 101

    # Scanned status verification
    assert sources["IVU-60"]["scanned"] is True
    assert sources["IVU-60"]["text_layer"] is False
    assert sources["IVU-65"]["scanned"] is True
    assert sources["IVU-65"]["text_layer"] is False

    # Digital text layer verification
    assert sources["EVU-B2"]["text_layer"] is True
    assert sources["EVU-ADV"]["text_layer"] is True
    assert sources["ECI-INT"]["text_layer"] is True
    assert sources["ECI-ADV"]["text_layer"] is True
    assert sources["AVU"]["text_layer"] is True
    assert sources["NB-PARA"]["text_layer"] is True


@pytest.mark.corpus
def test_unit_and_topic_indexes():
    """Validates structural unit index count (433 units) and 20-topic taxonomy."""
    unit_idx, topic_idx = build_unit_and_topic_indexes()
    assert len(unit_idx) == 433
    assert len(topic_idx) == 20

    # Verify 20 topics from taxonomy
    for t_id in TOPIC_TAXONOMY:
        assert t_id in topic_idx
        assert len(topic_idx[t_id]["units"]) > 0

    # Verify EVU-ADV Unit 101 presence
    assert "EVU-ADV-U101" in unit_idx
    assert "Red tape" in unit_idx["EVU-ADV-U101"]["title"]

    # Verify education_and_learning has cross-source units
    edu_units = topic_idx["education_and_learning"]["units"]
    assert any(u.startswith("IVU-60-") for u in edu_units)
    assert any(u.startswith("IVU-65-") for u in edu_units)
    assert any(u.startswith("EVU-B2-") for u in edu_units)
    assert any(u.startswith("EVU-ADV-") for u in edu_units)
    assert any(u.startswith("ECI-ADV-") for u in edu_units)
    assert any(u.startswith("AVU-") for u in edu_units)
    assert any(u.startswith("NB-PARA-") for u in edu_units)


@pytest.mark.corpus
def test_parsers_family_a_b_c():
    """Validates representative unit extraction across all three parsing families."""
    unit_idx, _ = build_unit_and_topic_indexes()

    # Family A: EVU-B2 Unit 14 (Education)
    p_a = FamilyAParser("EVU-B2")
    res_a = p_a.parse_unit(unit_idx["EVU-B2-U014"])
    assert res_a["unit_key"] == "EVU-B2-U014"
    assert res_a["title"] == "Education"
    assert len(res_a["theory"]["sections"]) >= 1
    assert len(res_a["exercises"]) >= 1
    assert res_a["answer_key"]["status"] == "extracted_authoritative_key"
    assert "14.1" in res_a["answer_key"]["answers"]

    # Family B: IVU-60 Unit 1 (Growing up)
    p_b = FamilyBParser("IVU-60")
    res_b = p_b.parse_unit(unit_idx["IVU-60-U001"])
    assert res_b["unit_key"] == "IVU-60-U001"
    assert res_b["title"] == "Growing up"
    assert len(res_b["exercises"]) >= 1
    assert res_b["audio_required"] is True
    assert res_b["audio_available"] is False

    # Family C: NB-PARA Education Section
    p_c = FamilyCParser()
    res_c = p_c.parse_section(unit_idx["NB-PARA-PRAC-EDU"])
    assert res_c["unit_key"] == "NB-PARA-PRAC-EDU"
    assert len(res_c["paraphrase_groups"]) >= 5
    assert "0974657403" not in res_c["raw_text"]
    assert "ngocbach.com" not in res_c["raw_text"]


@pytest.mark.corpus
def test_education_pilot_exercises_and_nuance():
    """Validates Education Pilot exercises: EX-IVU-65-1.4, Cullen nuance, authentic exercises."""
    build_knowledge_base()

    with open(KB_EXERCISES_FILE, "r", encoding="utf-8") as f:
        exercises = [json.loads(line) for line in f if line.strip()]

    ex_map = {ex["exercise_id"]: ex for ex in exercises}
    assert "EX-IVU-65-1.4" in ex_map
    assert ex_map["EX-IVU-65-1.4"]["exercise_number"] == "1.4"
    assert ex_map["EX-IVU-65-1.4"]["printed_page"] == 26
    assert "knowledge" in ex_map["EX-IVU-65-1.4"]["instructions"]

    # Verify answer key
    with open(KB_ANSWER_KEYS_FILE, "r", encoding="utf-8") as f:
        keys = [json.loads(line) for line in f if line.strip()]
    ak_map = {k["exercise_id"]: k for k in keys}
    assert "EX-IVU-65-1.4" in ak_map
    assert any("limited knowledge of" in a for a in ak_map["EX-IVU-65-1.4"]["acceptable_answers"])

    # Verify usage warning nuance on acquire knowledge of
    with open(KB_COLLOCATIONS_FILE, "r", encoding="utf-8") as f:
        colls = [json.loads(line) for line in f if line.strip()]
    col_map = {c["collocation_id"]: c for c in colls}
    assert "COL-EDU-00001" in col_map
    assert "subject/discipline" in col_map["COL-EDU-00001"]["usage_warning"]


@pytest.mark.corpus
def test_on_demand_enrichment_7_steps():
    """Validates the 7-step on-demand enrichment workflow on EVU-ADV-U101 and verifies cache hit."""
    # Step 1-6: First run executes extraction and enrichment
    res1 = enrich_unit_pipeline("EVU-ADV-U101", force_reextract=True)
    assert res1["from_cache"] is False
    assert len(res1["steps_log"]) == 6
    assert len(res1["enriched_unit"]["enriched_vocabulary"]) >= 3

    # Step 7: Second run achieves cache hit in under 10ms without re-extraction
    res2 = enrich_unit_pipeline("EVU-ADV-U101", force_reextract=False)
    assert res2["from_cache"] is True
    assert res2["elapsed_seconds"] < 0.1
    assert res2["steps_log"][0]["step"] == 7
