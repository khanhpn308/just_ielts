"""Tests for IELTS Vocabulary Knowledge Base (V1.0) & Adaptive Roadmap.

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
    PROCESSING_VERSION,
    build_source_inventory,
)
from harness.vocabulary.taxonomy import TOPIC_TAXONOMY, LANGUAGE_FUNCTIONS, classify_topics_by_keywords
from harness.vocabulary.unit_indexer import build_unit_and_topic_indexes
from harness.vocabulary.parser import FamilyAParser, FamilyBParser, FamilyCParser
from harness.vocabulary.kb import (
    normalize_expression,
    build_entry_key,
    merge_lexical_entries,
    is_cache_valid,
)
from harness.vocabulary.session import (
    parse_learning_intent,
    load_curriculum_state,
    save_curriculum_state,
    load_vocabulary_journal,
    assess_and_schedule_item,
    save_vocabulary_batch,
    get_due_vocabulary,
    mark_lesson_started,
    mark_lesson_completed,
    switch_learning_track,
    execute_tutor_command,
    STAGE_GAPS,
)
from harness.vocabulary.enrichment import (
    build_tutor_enriched_item,
    enrich_unit_pipeline,
)


def _create_synthetic_kb(tmp_path: Path, sha256: str = "sha256-test-v1"):
    """Helper building an isolated synthetic KB (index, units, enriched, vocab) in tmp_path."""
    kb_dir = tmp_path / "kb"
    units_dir = kb_dir / "units"
    enriched_dir = kb_dir / "enriched"
    kb_dir.mkdir(parents=True, exist_ok=True)

    sources_file = kb_dir / "sources.json"
    sources_file.write_text(
        json.dumps({
            "sources": {
                "SYNTH": {"source_id": "SYNTH", "sha256": sha256},
                "IVU-60": {"source_id": "IVU-60", "sha256": "sha-ivu60"},
                "EVU-B2": {"source_id": "EVU-B2", "sha256": "sha-evub2"},
                "ECI-INT": {"source_id": "ECI-INT", "sha256": "sha-eciint"},
                "NB-PARA": {"source_id": "NB-PARA", "sha256": "sha-nbpara"},
            }
        }),
        encoding="utf-8",
    )

    unit_index = {
        "SYNTH-U001": {
            "unit_key": "SYNTH-U001",
            "source_id": "SYNTH",
            "unit_number": 1,
            "title": "Synthetic Innovation",
            "physical_pages": [10, 11],
            "topics": ["science_and_technology"],
        },
        "IVU-60-U001": {
            "unit_key": "IVU-60-U001",
            "source_id": "IVU-60",
            "unit_number": 1,
            "title": "Synthetic Core Unit 1",
            "physical_pages": [10, 13],
            "topics": ["people_and_relationships"],
        },
        "IVU-60-U002": {
            "unit_key": "IVU-60-U002",
            "source_id": "IVU-60",
            "unit_number": 2,
            "title": "Synthetic Core Unit 2",
            "physical_pages": [14, 17],
            "topics": ["health_and_medicine"],
        },
        "EVU-B2-U014": {
            "unit_key": "EVU-B2-U014",
            "source_id": "EVU-B2",
            "unit_number": 14,
            "title": "Synthetic General Unit 14",
            "physical_pages": [35, 36],
            "topics": ["education_and_learning"],
        },
        "ECI-INT-U001": {
            "unit_key": "ECI-INT-U001",
            "source_id": "ECI-INT",
            "unit_number": 1,
            "title": "Synthetic Collocations Unit 1",
            "physical_pages": [10, 11],
            "topics": ["academic_language"],
        },
        "NB-PARA-T1-GEN": {
            "unit_key": "NB-PARA-T1-GEN",
            "source_id": "NB-PARA",
            "unit_number": 1,
            "title": "Synthetic Paraphrase Section 1",
            "physical_pages": [3, 6],
            "topics": ["academic_language"],
        },
    }
    index_file = kb_dir / "unit_index.json"
    index_file.write_text(json.dumps(unit_index), encoding="utf-8")

    # Pre-populate cached unit JSONs with matching sha256 and version
    unit_payloads = {
        ("SYNTH", "SYNTH-U001"): {
            "processing_version": PROCESSING_VERSION,
            "source_sha256": sha256,
            "unit_key": "SYNTH-U001",
            "source_id": "SYNTH",
            "unit_number": 1,
            "title": "Synthetic Innovation",
            "physical_pages": [10, 11],
            "topics": ["science_and_technology"],
            "theory": {
                "raw_text": "101\nSynthetic Innovation\nA\nResearchers apply incremental methodology [step-by-step refinement] in lab work.\n1 careful improvement\n",
                "sections": [{"section_id": "A", "title": "Methods", "content": "incremental methodology"}],
            },
            "exercises": [
                {
                    "exercise_id": "EX-SYNTH-U001-1.1",
                    "source_id": "SYNTH",
                    "unit_key": "SYNTH-U001",
                    "exercise_number": "1.1",
                    "instructions": "Complete synthetic sentence.",
                    "content": "1 Teams rely on ______ methodology.",
                }
            ],
            "answer_key": {
                "status": "extracted_authoritative_key",
                "verification_status": "authoritative_textbook_key",
                "answers": {"EX-SYNTH-U001-1.1": "1 incremental"},
            },
        },
        ("IVU-60", "IVU-60-U001"): {
            "processing_version": PROCESSING_VERSION,
            "source_sha256": "sha-ivu60",
            "unit_key": "IVU-60-U001",
            "source_id": "IVU-60",
            "title": "Synthetic Core Unit 1",
            "topics": ["people_and_relationships"],
            "theory": {"sections": [{"section_id": "A", "title": "Core", "content": "synthetic core text"}]},
            "exercises": [{"exercise_id": "EX-IVU-60-U001-1.1", "exercise_number": "1.1", "instructions": "Test", "content": "Q1"}],
        },
        ("IVU-60", "IVU-60-U002"): {
            "processing_version": PROCESSING_VERSION,
            "source_sha256": "sha-ivu60",
            "unit_key": "IVU-60-U002",
            "source_id": "IVU-60",
            "title": "Synthetic Core Unit 2",
            "topics": ["health_and_medicine"],
            "theory": {"sections": [{"section_id": "A", "title": "Core 2", "content": "synthetic core 2"}]},
            "exercises": [{"exercise_id": "EX-IVU-60-U002-2.1", "exercise_number": "2.1", "instructions": "Test 2", "content": "Q2"}],
        },
        ("EVU-B2", "EVU-B2-U014"): {
            "processing_version": PROCESSING_VERSION,
            "source_sha256": "sha-evub2",
            "unit_key": "EVU-B2-U014",
            "source_id": "EVU-B2",
            "title": "Synthetic General Unit 14",
            "topics": ["education_and_learning"],
            "theory": {"sections": [{"section_id": "A", "title": "Gen 14", "content": "synthetic gen 14"}]},
            "exercises": [{"exercise_id": "EX-EVU-B2-U014-14.1", "exercise_number": "14.1", "instructions": "Fill", "content": "Q14"}],
        },
        ("ECI-INT", "ECI-INT-U001"): {
            "processing_version": PROCESSING_VERSION,
            "source_sha256": "sha-eciint",
            "unit_key": "ECI-INT-U001",
            "source_id": "ECI-INT",
            "title": "Synthetic Collocations Unit 1",
            "topics": ["academic_language"],
            "theory": {"sections": [{"section_id": "A", "title": "Colloc 1", "content": "synthetic colloc"}]},
            "exercises": [{"exercise_id": "EX-ECI-INT-U001-1.1", "exercise_number": "1.1", "instructions": "Match", "content": "Q1"}],
        },
        ("NB-PARA", "NB-PARA-T1-GEN"): {
            "processing_version": PROCESSING_VERSION,
            "source_sha256": "sha-nbpara",
            "unit_key": "NB-PARA-T1-GEN",
            "source_id": "NB-PARA",
            "title": "Synthetic Paraphrase Section 1",
            "topics": ["academic_language"],
            "raw_text": "synthetic paraphrase text",
            "exercises": [],
        },
    }

    for (sid, ukey), payload in unit_payloads.items():
        d = units_dir / sid
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{ukey}.json").write_text(json.dumps(payload), encoding="utf-8")

    return {
        "kb_dir": kb_dir,
        "units_dir": units_dir,
        "enriched_dir": enriched_dir,
        "index_file": index_file,
        "sources_file": sources_file,
        "vocab_file": kb_dir / "vocabulary.jsonl",
        "lexical_index_file": kb_dir / "lexical_index.json",
    }


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

    topics = classify_topics_by_keywords("Higher education and university degrees")
    assert "education_and_learning" in topics


def test_lexical_normalization_and_entry_key():
    """Validates lemma normalization and unique compound entry key creation."""
    assert normalize_expression("  Synthetic Term  ") == "synthetic term"
    assert normalize_expression("Acquire Knowledge...") == "acquire knowledge"
    key = build_entry_key("Synthetic Term", "phrase", "test definition sense")
    assert key == "synthetic term|phrase|test definition sense"


def test_intent_parser_all_roadmap_and_tutor_commands():
    """Validates intent recognition for all adaptive roadmap, navigation, and study commands."""
    assert parse_learning_intent("Học từ vựng")["intent"] == "LEARN_VOCABULARY"
    assert parse_learning_intent("Học collocation")["intent"] == "LEARN_COLLOCATION"
    assert parse_learning_intent("Học paraphrase")["intent"] == "LEARN_PARAPHRASE"
    assert parse_learning_intent("Học theo chủ đề")["intent"] == "LEARN_TOPIC"
    assert parse_learning_intent("Học theo chủ đề Education")["topic_id"] == "education_and_learning"
    assert parse_learning_intent("Xem tiến độ")["intent"] == "VIEW_PROGRESS"
    assert parse_learning_intent("Xem lộ trình")["intent"] == "VIEW_ROADMAP"
    assert parse_learning_intent("Tiếp tục bài hôm qua")["intent"] == "RESUME_LESSON"
    assert parse_learning_intent("Chuyển sang EVU-B2")["intent"] == "SWITCH_TRACK"
    assert parse_learning_intent("Chuyển sang EVU-B2")["target_track"] == "EVU-B2"
    assert parse_learning_intent("Chuyển sang lộ trình chính")["target_track"] == "PRIMARY_CORE"
    assert parse_learning_intent("Học IVU-60 Unit 1.")["unit_key"] == "IVU-60-U001"
    assert parse_learning_intent("Học Unit tiếp theo.")["intent"] == "LEARN_NEXT_UNIT"
    assert parse_learning_intent("Ôn từ vựng hôm nay.")["intent"] == "REVIEW_DUE_VOCABULARY"
    assert parse_learning_intent("Lưu kết quả buổi học")["user_consented"] is True


def test_defect_1_early_successful_review_must_not_advance_or_postpone(tmp_path):
    """Defect 1 Regression: Early successful reviews must preserve stage & due date."""
    p_file = tmp_path / "vocabulary.jsonl"

    # Existing item at Stage 2, due on 2026-01-10
    existing = {
        "entry_key": "reduce|verb|make less",
        "expression": "reduce",
        "pos": "verb",
        "sense_key": "make less",
        "meaning_vi": "làm giảm",
        "sources": [{"kind": "tutor_created", "ref": None, "locator": None}],
        "level": 2,
        "review_stage": 2,
        "first_studied_date": "2026-01-01",
        "last_review_date": "2026-01-04",
        "next_review_date": "2026-01-10",
        "last_outcome": "recalled",
        "review_count": 2,
        "lapse_count": 0,
        "errors": [],
    }

    # Early successful recall on 2026-01-06 (4 days BEFORE due date 2026-01-10)
    early_success = assess_and_schedule_item(
        existing_record=existing,
        expression="reduce",
        pos="verb",
        sense_key="make less",
        meaning_vi="làm giảm",
        level=3,
        outcome="productive",
        session_date=datetime.date(2026, 1, 6),
    )
    assert early_success["review_stage"] == 2  # MUST NOT advance to 3!
    assert early_success["next_review_date"] == "2026-01-10"  # MUST NOT postpone!
    assert early_success["review_count"] == 3

    # Genuine early failure on 2026-01-07 MAY shorten due date and reset stage
    early_fail = assess_and_schedule_item(
        existing_record=early_success,
        expression="reduce",
        pos="verb",
        sense_key="make less",
        meaning_vi="làm giảm",
        level=0,
        outcome="failed",
        session_date=datetime.date(2026, 1, 7),
    )
    assert early_fail["review_stage"] == 0
    assert early_fail["next_review_date"] == "2026-01-08"
    assert early_fail["lapse_count"] == 1

    # Due review on 2026-01-08 succeeds -> NOW advances stage 0 -> 1 (+2 days)
    due_success = assess_and_schedule_item(
        existing_record=early_fail,
        expression="reduce",
        pos="verb",
        sense_key="make less",
        meaning_vi="làm giảm",
        level=2,
        outcome="recalled",
        session_date=datetime.date(2026, 1, 8),
    )
    assert due_success["review_stage"] == 1
    assert due_success["next_review_date"] == "2026-01-10"


def test_defect_2_cache_invalidation_by_sha256_and_version(tmp_path):
    """Defect 2 Regression: Invalidate extraction & enrichment caches when sha256 or version mismatches."""
    env = _create_synthetic_kb(tmp_path, sha256="sha256-v1")

    # Populate valid completed enrichment cache with sha256-v1
    res1 = enrich_unit_pipeline(
        "SYNTH-U001",
        tutor_enrichments=[{
            "expression": "incremental methodology",
            "pos": "noun",
            "sense_key": "step-by-step approach",
            "meaning_vi": "phương pháp cải tiến từng bước",
        }],
        index_file=env["index_file"],
        units_dir=env["units_dir"],
        enriched_dir=env["enriched_dir"],
        vocab_file=env["vocab_file"],
        lexical_index_file=env["lexical_index_file"],
        sources_file=env["sources_file"],
    )
    assert res1["from_cache"] is False
    assert res1["enrichment_status"] == "completed"

    # Cache hit when sha256 and version match
    res_hit = enrich_unit_pipeline(
        "SYNTH-U001",
        index_file=env["index_file"],
        units_dir=env["units_dir"],
        enriched_dir=env["enriched_dir"],
        vocab_file=env["vocab_file"],
        lexical_index_file=env["lexical_index_file"],
        sources_file=env["sources_file"],
    )
    assert res_hit["from_cache"] is True

    # Invalidate when source_sha256 changes!
    assert is_cache_valid(res_hit["enriched_unit"], "SYNTH", "sha256-v2-changed", PROCESSING_VERSION) is False
    # Invalidate when processing_version changes!
    assert is_cache_valid(res_hit["enriched_unit"], "SYNTH", "sha256-v1", "9.9.9-new") is False

    # Passing new sha256-v2 to enrich_unit_pipeline forces invalidation (from_cache=False)
    res_recheck = enrich_unit_pipeline(
        "SYNTH-U001",
        source_sha256="sha256-v2-changed",
        index_file=env["index_file"],
        units_dir=env["units_dir"],
        enriched_dir=env["enriched_dir"],
        vocab_file=env["vocab_file"],
        lexical_index_file=env["lexical_index_file"],
        sources_file=env["sources_file"],
    )
    assert res_recheck["from_cache"] is False


def test_defect_3_candidate_only_cache_not_treated_as_completed(tmp_path):
    """Defect 3 Regression: Candidate-only / empty enrichment caches must NOT block subsequent enrichment."""
    env = _create_synthetic_kb(tmp_path)

    # Step 1: Extract candidates only (tutor_enrichments=None)
    res_cand = enrich_unit_pipeline(
        "SYNTH-U001",
        tutor_enrichments=None,
        index_file=env["index_file"],
        units_dir=env["units_dir"],
        enriched_dir=env["enriched_dir"],
        vocab_file=env["vocab_file"],
        lexical_index_file=env["lexical_index_file"],
        sources_file=env["sources_file"],
    )
    assert res_cand["from_cache"] is False
    assert res_cand["enrichment_status"] == "candidates_only"
    assert len(res_cand["candidates"]) > 0
    assert len(res_cand["enriched_unit"]["enriched_vocabulary"]) == 0

    # Step 2: Calling again without tutor_enrichments MUST NOT return completed cache hit
    res_cand2 = enrich_unit_pipeline(
        "SYNTH-U001",
        tutor_enrichments=None,
        index_file=env["index_file"],
        units_dir=env["units_dir"],
        enriched_dir=env["enriched_dir"],
        vocab_file=env["vocab_file"],
        lexical_index_file=env["lexical_index_file"],
        sources_file=env["sources_file"],
    )
    assert res_cand2["from_cache"] is False
    assert res_cand2["enrichment_status"] == "candidates_only"

    # Step 3: Subsequent Tutor enrichment populates it and marks it completed!
    res_populated = enrich_unit_pipeline(
        "SYNTH-U001",
        tutor_enrichments=[{
            "expression": "incremental methodology",
            "pos": "noun",
            "sense_key": "step-by-step improvement",
            "meaning_vi": "phương pháp cải tiến từng bước",
        }],
        index_file=env["index_file"],
        units_dir=env["units_dir"],
        enriched_dir=env["enriched_dir"],
        vocab_file=env["vocab_file"],
        lexical_index_file=env["lexical_index_file"],
        sources_file=env["sources_file"],
    )
    assert res_populated["from_cache"] is False
    assert res_populated["enrichment_status"] == "completed"
    assert len(res_populated["enriched_unit"]["enriched_vocabulary"]) == 1

    # Step 4: Now subsequent lookup hits completed cache!
    res_final = enrich_unit_pipeline(
        "SYNTH-U001",
        index_file=env["index_file"],
        units_dir=env["units_dir"],
        enriched_dir=env["enriched_dir"],
        vocab_file=env["vocab_file"],
        lexical_index_file=env["lexical_index_file"],
        sources_file=env["sources_file"],
    )
    assert res_final["from_cache"] is True
    assert res_final["enrichment_status"] == "completed"


def test_defect_4_unmatched_tutor_content_not_attributed_to_textbook(tmp_path):
    """Defect 4 Regression: Unmatched Tutor items must NOT claim authoritative textbook provenance."""
    env = _create_synthetic_kb(tmp_path)

    res = enrich_unit_pipeline(
        "SYNTH-U001",
        tutor_enrichments=[
            {
                "expression": "incremental methodology",
                "pos": "noun",
                "sense_key": "gradual method",
                "meaning_vi": "phương pháp tuần tự",
            },
            {
                "expression": "completely invented term",
                "pos": "noun",
                "sense_key": "not in textbook",
                "meaning_vi": "từ gia sư bổ sung ngoài sách",
                "contextual_meaning": "Tutor created context sentence.",
            },
        ],
        index_file=env["index_file"],
        units_dir=env["units_dir"],
        enriched_dir=env["enriched_dir"],
        vocab_file=env["vocab_file"],
        lexical_index_file=env["lexical_index_file"],
        sources_file=env["sources_file"],
    )

    items = {it["expression"]: it for it in res["enriched_unit"]["enriched_vocabulary"]}

    # Matched item -> grounded in textbook
    matched = items["incremental methodology"]
    assert matched["provenance_metadata"]["source_grounded"] is True
    assert matched["sources"][0]["provenance"] == "authoritative_textbook"
    assert matched["sources"][0]["source_id"] == "SYNTH"
    assert matched["sources"][0]["unit_key"] == "SYNTH-U001"

    # Unmatched item -> NOT attributed to textbook!
    unmatched = items["completely invented term"]
    assert unmatched["provenance_metadata"]["source_grounded"] is False
    assert unmatched["provenance_metadata"]["extraction_method"] == "unmatched_tutor_enrichment"
    assert unmatched["sources"][0]["provenance"] == "tutor_created"
    assert unmatched["sources"][0]["kind"] == "tutor_created"
    assert unmatched["sources"][0]["ref"] is None
    assert "source_id" not in unmatched["sources"][0]


def test_adaptive_roadmap_navigation_track_switching_and_resume(tmp_path):
    """Demonstrates all roadmap commands, independent textbook progress, track switching, and fresh-conversation resume."""
    env = _create_synthetic_kb(tmp_path)
    p_file = tmp_path / "progress" / "vocabulary.jsonl"
    c_file = tmp_path / "progress" / "curriculum.json"
    d_today = datetime.date(2026, 2, 1)

    # 1. Start with empty progress -> save 1 journal item (due today) with consent
    rec = assess_and_schedule_item(
        None, "synthetic item", "noun", "test sense", "mục tổng hợp",
        level=0, outcome="not_assessed", session_date=datetime.date(2026, 1, 31)
    )
    save_vocabulary_batch([rec], user_consented=True, progress_file=p_file)

    # 2. Study & complete IVU-60-U001 on PRIMARY_CORE track -> save with consent
    state = load_curriculum_state(c_file)
    state = mark_lesson_started(state, "IVU-60-U001", session_date=d_today)
    state = mark_lesson_completed(state, "IVU-60-U001", exercises_completed=1, session_date=d_today)
    save_curriculum_state(state, c_file, user_consented=True)

    # 3. Switch track to EVU-B2 ("Chuyển sang EVU-B2") and start unfinished lesson EVU-B2-U014
    res_switch = execute_tutor_command(
        "Chuyển sang EVU-B2",
        progress_file=p_file, curriculum_file=c_file,
        index_file=env["index_file"], units_dir=env["units_dir"], sources_file=env["sources_file"],
        user_consented=True,
    )
    assert res_switch["active_track"] == "EVU-B2"

    res_u14 = execute_tutor_command(
        "Học EVU-B2 Unit 14.",
        progress_file=p_file, curriculum_file=c_file,
        index_file=env["index_file"], units_dir=env["units_dir"], sources_file=env["sources_file"],
        user_consented=True,
    )
    assert res_u14["unit_key"] == "EVU-B2-U014"

    # 4. Simulate a FRESH conversation: verify unfinished lesson & independent PRIMARY_CORE track preserved!
    fresh_resume = execute_tutor_command(
        "Tiếp tục bài hôm qua",
        progress_file=p_file, curriculum_file=c_file,
        index_file=env["index_file"], units_dir=env["units_dir"], sources_file=env["sources_file"],
    )
    assert fresh_resume["resumed"] is True
    assert fresh_resume["unit_key"] == "EVU-B2-U014"
    assert "EX-EVU-B2-U014-14.1" in fresh_resume["pending_exercises"]

    # Switch back to PRIMARY_CORE -> resumes independently at IVU-60-U002!
    back_primary = execute_tutor_command(
        "Chuyển sang lộ trình chính",
        progress_file=p_file, curriculum_file=c_file,
        index_file=env["index_file"], units_dir=env["units_dir"], sources_file=env["sources_file"],
    )
    assert back_primary["active_track"] == "PRIMARY_CORE"
    assert back_primary["unit_key"] == "IVU-60-U002"

    # 5. Test all 6 priority commands:
    cmd_vocab = execute_tutor_command(
        "Học từ vựng", progress_file=p_file, curriculum_file=c_file,
        index_file=env["index_file"], units_dir=env["units_dir"], sources_file=env["sources_file"],
        target_date="2026-02-01",
    )
    assert cmd_vocab["status"] == "ready"
    assert cmd_vocab["due_reviews_count"] == 1  # Prioritizes due review!
    assert cmd_vocab["recommendation"]["action_type"] == "review_due_vocabulary"

    cmd_colloc = execute_tutor_command(
        "Học collocation", progress_file=p_file, curriculum_file=c_file,
        index_file=env["index_file"], units_dir=env["units_dir"], sources_file=env["sources_file"],
    )
    assert cmd_colloc["status"] == "ready"
    assert cmd_colloc["recommended_unit_key"] == "ECI-INT-U001"

    cmd_para = execute_tutor_command(
        "Học paraphrase", progress_file=p_file, curriculum_file=c_file,
        index_file=env["index_file"], units_dir=env["units_dir"], sources_file=env["sources_file"],
    )
    assert cmd_para["status"] == "ready"
    assert cmd_para["recommended_unit_key"] == "NB-PARA-T1-GEN"

    cmd_topic = execute_tutor_command(
        "Học theo chủ đề", progress_file=p_file, curriculum_file=c_file,
        index_file=env["index_file"], units_dir=env["units_dir"], sources_file=env["sources_file"],
    )
    assert cmd_topic["status"] == "ready"
    assert cmd_topic["auto_selected"] is True
    assert cmd_topic["topic_id"] in TOPIC_TAXONOMY

    cmd_prog = execute_tutor_command(
        "Xem tiến độ", progress_file=p_file, curriculum_file=c_file,
        target_date="2026-02-01",
    )
    assert cmd_prog["status"] == "ready"
    prog = cmd_prog["progress_report"]
    assert prog["vocabulary_journal"]["total_items"] == 1
    assert prog["vocabulary_journal"]["due_today_count"] == 1
    assert prog["textbooks"]["IVU-60"]["completed_units"] == 1
    assert prog["textbooks"]["EVU-B2"]["in_progress_units"] == 1

    cmd_road = execute_tutor_command(
        "Xem lộ trình", progress_file=p_file, curriculum_file=c_file,
        target_date="2026-02-01",
    )
    assert cmd_road["status"] == "ready"
    assert cmd_road["roadmap"]["primary_backbone"]["ivu60_progress"]["current_position"] == "IVU-60-U002"
    assert cmd_road["roadmap"]["unfinished_lesson"]["unit_key"] == "EVU-B2-U014"


def test_pr10_consent_and_same_day_duplicate_prevention(tmp_path):
    """Ensures no file creation without consent and no double-counting on same calendar day."""
    p_file = tmp_path / "vocabulary.jsonl"
    c_file = tmp_path / "curriculum.json"
    d0 = datetime.date(2026, 1, 1)
    d1 = datetime.date(2026, 1, 2)

    rec1 = assess_and_schedule_item(None, "synthetic verb", "verb", "do test", "thử nghiệm", level=0, outcome="not_assessed", session_date=d0)
    assert save_vocabulary_batch([rec1], user_consented=False, progress_file=p_file)["saved"] is False
    assert not p_file.exists()

    assert save_curriculum_state(load_curriculum_state(c_file), c_file, user_consented=False) is False
    assert not c_file.exists()

    assert save_vocabulary_batch([rec1], user_consented=True, progress_file=p_file)["saved"] is True
    rec2 = assess_and_schedule_item(rec1, "synthetic verb", "verb", "do test", "thử nghiệm", level=2, session_date=d1)
    assert rec2["review_stage"] == 1
    assert rec2["next_review_date"] == "2026-01-04"

    # Same-day retry cannot advance stage again
    rec2_retry = assess_and_schedule_item(rec2, "synthetic verb", "verb", "do test", "thử nghiệm", level=3, session_date=d1)
    assert rec2_retry["review_stage"] == 1
    assert rec2_retry["review_count"] == 1


# ==============================================================================
# Corpus Integration Tests (Requires private/raw/ corpus files)
# ==============================================================================

@pytest.mark.corpus
def test_source_inventory():
    """Validates that all eight textbooks are inventoried with correct metadata and SHA-256."""
    inv = build_source_inventory()
    sources = inv["sources"]
    assert len(sources) == 8
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

    p_a = FamilyAParser("EVU-B2")
    res_a = p_a.parse_unit(unit_idx["EVU-B2-U014"])
    assert res_a["unit_key"] == "EVU-B2-U014"
    assert res_a["source_sha256"] is not None
    assert any("EX-EVU-B2-U014-14.1" in ex["exercise_id"] for ex in res_a["exercises"])
    assert res_a["answer_key"]["verification_status"] == "authoritative_textbook_key"

    p_b = FamilyBParser("IVU-60")
    res_b = p_b.parse_unit(unit_idx["IVU-60-U001"])
    assert res_b["unit_key"] == "IVU-60-U001"
    assert res_b["source_sha256"] is not None
    assert res_b["answer_key"]["verification_status"] == "uncertain_ocr_key"

    p_c = FamilyCParser()
    res_c = p_c.parse_section(unit_idx["NB-PARA-PRAC-EDU"])
    assert res_c["unit_key"] == "NB-PARA-PRAC-EDU"
    assert res_c["source_sha256"] is not None
    assert len(res_c["paraphrase_groups"]) >= 5


@pytest.mark.corpus
def test_generalized_on_demand_enrichment_outside_education():
    """Demonstrates generalized on-demand enrichment on ECI-INT-U030 (Work)."""
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

    res1 = enrich_unit_pipeline("ECI-INT-U030", tutor_enrichments=tutor_enrichments, force_reextract=True)
    assert res1["from_cache"] is False
    assert res1["enrichment_status"] == "completed"
    assert len(res1["candidates"]) > 0
    assert res1["enriched_unit"]["enriched_vocabulary"][0]["provenance_metadata"]["enrichment_agent"] == "tutor_agent"

    res2 = enrich_unit_pipeline("ECI-INT-U030", force_reextract=False)
    assert res2["from_cache"] is True
    assert res2["elapsed_seconds"] < 0.1
