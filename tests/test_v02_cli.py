"""Automated tests for V0.2 CLI commands and checkpointing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
import pytest

from harness.cli import main
from harness.db import get_db_connection, init_db, upsert_normalization_checkpoint

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_cli_normalization_status_empty():
    """Verify normalization-status executes without errors."""
    init_db()
    with patch("sys.argv", ["harness", "normalization-status"]):
        main()


def test_cli_normalize_dry_run_flag():
    """Verify normalize command accepts --dry-run and executes without writing files."""
    init_db()
    with patch("sys.argv", ["harness", "normalize", "--pilot", "--dry-run"]):
        main()


def test_cli_verify_synthetic_entities(tmp_path: Path):
    """Verify Quality Gate runner executed via CLI on a directory of synthetic entities."""
    # Write a minimal set of valid synthetic entities
    test_data = {
        "test_id": "TEST-IELTS-VOL99-01-ACAD",
        "title": "Synthetic Practice Test 1 (Academic)",
        "volume": "VOL_99",
        "test_number": 1,
        "track": "academic",
        "source_reference_id": "REF-SYNTH-01",
        "sections_present": ["reading"],
        "quality_profile": {
            "lifecycle_status": "reviewed",
            "extraction_quality": "complete_clean",
            "source_fidelity": "authoritative_official",
            "answer_verification": "authoritative_key",
            "explanation_verification": "source_provided",
            "publication_permission": "public_synthetic",
            "validation_flags": [],
        },
        "_provenance": {
            "schema_version": "v0.2.0-normalized",
            "source_file_id": "FILE-000000000001",
            "source_legacy_id": "SRC-999",
            "relative_path": "synthetic/sample.docx",
            "source_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "processing_unit": "document",
            "unit_identifier": "raw_document",
            "raw_block_locator": "para:0",
            "extractor_adapter": "docx",
            "extractor_version": "0.1.0",
            "normalizer_version": "0.2.0-b",
            "canonical_content_sha256": None,
            "normalized_at": None,
        },
    }
    from harness.normalizers.base import BaseNormalizer
    test_dict = BaseNormalizer.finalize_and_hash_entity(test_data)
    (tmp_path / "TEST-IELTS-VOL99-01-ACAD.json").write_text(json.dumps(test_dict, indent=2))

    passage_text = (
        "Synthetic polymers were first engineered during the early twentieth century as laboratory curiosities before transforming global industrial manufacturing and material science. "
        "These initial formulations lacked elasticity and fractured easily under sudden mechanical pressure in industrial testing facilities. "
        "Subsequent chemical advances introduced thermoplastic polymer chains that vastly improved tensile elasticity and shock absorption."
    )
    passage_data = {
        "passage_id": "PASSAGE-VOL99-01-RD01",
        "test_id": "TEST-IELTS-VOL99-01-ACAD",
        "skill": "reading",
        "sequence_number": 1,
        "title": "History of Synthetic Materials",
        "subtitle": None,
        "narrative_text": passage_text,
        "paragraphs": [
            {
                "label": "1",
                "sequence_index": 0,
                "char_start": 0,
                "char_end": len(passage_text),
                "text": passage_text,
            }
        ],
        "audio_track_ref": None,
        "word_count": len(passage_text.split()),
        "quality_profile": test_data["quality_profile"],
        "_provenance": test_data["_provenance"],
    }
    pass_dict = BaseNormalizer.finalize_and_hash_entity(passage_data)
    (tmp_path / "PASSAGE-VOL99-01-RD01.json").write_text(json.dumps(pass_dict, indent=2))

    group_data = {
        "group_id": "QG-VOL99-01-RD01-G01",
        "passage_id": "PASSAGE-VOL99-01-RD01",
        "start_question_number": 1,
        "end_question_number": 1,
        "question_type": "true-false-not-given",
        "instruction_text": "Do the following statements agree with the passage? Write TRUE, FALSE or NOT GIVEN.",
        "word_limit_rule": None,
        "shared_options": None,
        "quality_profile": test_data["quality_profile"],
        "_provenance": test_data["_provenance"],
    }
    group_dict = BaseNormalizer.finalize_and_hash_entity(group_data)
    (tmp_path / "QG-VOL99-01-RD01-G01.json").write_text(json.dumps(group_dict, indent=2))

    q_data = {
        "question_id": "Q-VOL99-01-RD-001",
        "group_id": "QG-VOL99-01-RD01-G01",
        "passage_id": "PASSAGE-VOL99-01-RD01",
        "question_number": 1,
        "question_type": "true-false-not-given",
        "prompt_text": "Early synthetic polymers fractured easily under mechanical pressure.",
        "options": None,
        "blank_target": None,
        "linked_principle_ids": ["RD-TFNG-001"],
        "quality_profile": test_data["quality_profile"],
        "_provenance": test_data["_provenance"],
    }
    q_dict = BaseNormalizer.finalize_and_hash_entity(q_data)
    (tmp_path / "Q-VOL99-01-RD-001.json").write_text(json.dumps(q_dict, indent=2))

    ans_data = {
        "answer_id": "ANS-VOL99-01-RD-001-KEY",
        "question_id": "Q-VOL99-01-RD-001",
        "target_value": "TRUE",
        "acceptable_alternates": ["T"],
        "case_sensitive": False,
        "source_key_ref": "Page 1, Q1",
        "quality_profile": test_data["quality_profile"],
        "_provenance": test_data["_provenance"],
    }
    ans_dict = BaseNormalizer.finalize_and_hash_entity(ans_data)
    (tmp_path / "ANS-VOL99-01-RD-001-KEY.json").write_text(json.dumps(ans_dict, indent=2))

    ev_quote = "These initial formulations lacked elasticity and fractured easily under sudden mechanical pressure in industrial testing facilities."
    ev_start = passage_text.find(ev_quote)
    ev_data = {
        "evidence_id": "EVID-VOL99-01-RD-001-01",
        "answer_id": "ANS-VOL99-01-RD-001-KEY",
        "passage_id": "PASSAGE-VOL99-01-RD01",
        "evidence_type": "direct_support",
        "paragraph_label": "1",
        "char_start": ev_start,
        "char_end": ev_start + len(ev_quote),
        "verbatim_quote": ev_quote,
        "exact_match_verified": True,
        "missing_information_rationale": None,
        "audio_interval": None,
        "quality_profile": test_data["quality_profile"],
        "_provenance": test_data["_provenance"],
    }
    ev_dict = BaseNormalizer.finalize_and_hash_entity(ev_data)
    (tmp_path / "EVID-VOL99-01-RD-001-01.json").write_text(json.dumps(ev_dict, indent=2))

    expl_data = {
        "explanation_id": "EXPL-VOL99-01-RD-001",
        "question_id": "Q-VOL99-01-RD-001",
        "answer_id": "ANS-VOL99-01-RD-001-KEY",
        "evidence_id": "EVID-VOL99-01-RD-001-01",
        "rationale_en": "Paragraph 1 explicitly confirms the prompt statement.",
        "rationale_vi": None,
        "paraphrase_map": [],
        "distractor_notes": None,
        "author_type": "source_published",
        "quality_profile": test_data["quality_profile"],
        "_provenance": test_data["_provenance"],
    }
    expl_dict = BaseNormalizer.finalize_and_hash_entity(expl_data)
    (tmp_path / "EXPL-VOL99-01-RD-001.json").write_text(json.dumps(expl_dict, indent=2))

    with patch(
        "sys.argv",
        [
            "harness",
            "verify",
            "--test-id",
            "TEST-IELTS-VOL99-01-ACAD",
            "--normalized-dir",
            str(tmp_path),
        ],
    ):
        main()
