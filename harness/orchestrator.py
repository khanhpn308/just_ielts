"""Normalization pipeline orchestrator for IELTS Data Harness V0.2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness.config import REPO_ROOT
from harness.db import (
    get_db_connection,
    get_source_by_file_id,
    get_source_by_legacy_id,
    is_normalization_checkpoint_valid,
    upsert_normalization_checkpoint,
)
from harness.models.question_bank import IELTSAnswer, IELTSEvidence, IELTSExplanation
from harness.normalizers.answer_reconciler import AnswerReconciler
from harness.normalizers.base import (
    NORMALIZER_VERSION,
    SCHEMA_VERSION,
    BaseNormalizer,
    compute_canonical_content_hash,
)
from harness.normalizers.evidence_resolver import EvidenceResolver
from harness.normalizers.reading_docx import DocxReadingNormalizer

STAGING_NORMALIZED_DIR = REPO_ROOT / "private" / "staging" / "normalized"
STAGING_RAW_DIR = REPO_ROOT / "private" / "staging" / "raw_extracted"


class NormalizationOrchestrator:
    """Coordinates reading parsers, answer reconcilers, and evidence resolvers."""

    def __init__(
        self,
        output_dir: Path = STAGING_NORMALIZED_DIR,
        raw_staging_dir: Path = STAGING_RAW_DIR,
        normalizer_version: str = NORMALIZER_VERSION,
    ):
        self.output_dir = output_dir
        self.raw_staging_dir = raw_staging_dir
        self.normalizer_version = normalizer_version
        self.docx_normalizer = DocxReadingNormalizer(normalizer_version=normalizer_version)
        self.answer_reconciler = AnswerReconciler(normalizer_version=normalizer_version)
        self.evidence_resolver = EvidenceResolver(normalizer_version=normalizer_version)

    def run_pilot(
        self,
        dry_run: bool = False,
        force: bool = False,
        test_number: int = 5,
        passage_number: int = 1,
        volume_code: str = "VOL06",
    ) -> Dict[str, Any]:
        """Runs the approved Reading Pilot (SRC-138 + SRC-137) end-to-end."""
        return self.normalize_reading_pilot(
            doc_legacy_id="SRC-138",
            key_legacy_id="SRC-137",
            test_number=test_number,
            passage_number=passage_number,
            volume_code=volume_code,
            dry_run=dry_run,
            force=force,
        )

    def normalize_reading_pilot(
        self,
        doc_legacy_id: str,
        key_legacy_id: str,
        test_number: int = 5,
        passage_number: int = 1,
        volume_code: str = "VOL06",
        dry_run: bool = False,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Executes normalization for a Reading test passage with answer key & explanations."""
        conn = get_db_connection()

        doc_source = get_source_by_legacy_id(conn, doc_legacy_id)
        if not doc_source:
            conn.close()
            raise ValueError(f"Source {doc_legacy_id} not found in database inventory.")

        key_source = get_source_by_legacy_id(conn, key_legacy_id)
        if not key_source:
            conn.close()
            raise ValueError(f"Source {key_legacy_id} not found in database inventory.")

        # 1. Load raw extraction artifacts
        raw_doc_path = self.raw_staging_dir / doc_legacy_id / "raw_document.json"
        if not raw_doc_path.exists():
            conn.close()
            raise FileNotFoundError(f"Raw extraction not found at {raw_doc_path}")

        raw_doc_bytes = raw_doc_path.read_bytes()
        raw_doc_sha = hashlib.sha256(raw_doc_bytes).hexdigest()
        raw_document = json.loads(raw_doc_bytes.decode("utf-8"))

        # Load key pages
        key_dir = self.raw_staging_dir / key_legacy_id
        key_pages = []
        for p_file in sorted(key_dir.glob("page_*.json")):
            key_pages.append(json.loads(p_file.read_text(encoding="utf-8")))

        # 2. Parse Reading Passage and Questions
        reading_result = self.docx_normalizer.normalize(
            raw_document=raw_document,
            source_record=doc_source,
            test_number=test_number,
            passage_number=passage_number,
            volume_code=volume_code,
            publication_permission="private_copyrighted",
        )

        test_entity = reading_result["test"]
        passage_entity = reading_result["passage"]
        group_entities = reading_result["groups"]
        question_entities = reading_result["questions"]

        # 3. Parse and reconcile Answer Keys
        raw_keys = self.answer_reconciler.parse_pdf_ocr_explanation_keys(key_pages)
        answer_entities = self.answer_reconciler.reconcile_answers(
            questions=question_entities,
            raw_key_map=raw_keys,
            source_record=key_source,
            volume_code=volume_code,
            test_number=test_number,
            publication_permission="private_copyrighted",
        )

        # 4. Resolve Evidence Spans and Explanations for Questions 3–6
        evidence_entities: List[IELTSEvidence] = []
        explanation_entities: List[IELTSExplanation] = []

        q_map = {q.question_number: q for q in question_entities}
        ans_map = {a.answer_id.split("-")[-2]: a for a in answer_entities}

        # Explicit candidate evidence quotes and explanations verified from SRC-137
        known_evidence = {
            3: {
                "evidence_type": "insufficient_information_not_given",
                "paragraph_label": "1",
                "quote": None,
                "missing_rationale": (
                    "The passage discusses how images and objects have been brought together to show visual styles "
                    "at different periods and places, but contains no information about whether collecting objects "
                    "from some periods was more difficult than others."
                ),
                "rationale_en": (
                    "The passage tells that the images and objects have been brought together to show visual styles "
                    "at different periods and different places, but there is no information whether more objects were "
                    "collected from one period than another."
                ),
                "paraphrases": [],
            },
            4: {
                "evidence_type": "direct_support",
                "paragraph_label": "2",
                "quote": "The course is organised around a series of issues that relate to the production of art and people's responses to it.",
                "missing_rationale": None,
                "rationale_en": "Paragraph 2 states that the course relates to the production of art and people's responses to it, which means how art is made and perceived.",
                "paraphrases": [{"prompt_term": "perceived", "passage_term": "people's responses to it"}],
            },
            5: {
                "evidence_type": "contradictory_evidence",
                "paragraph_label": "3",
                "quote": "The optional courses listed below are not available every year and prospective students are advised to check on the availability of specific courses.",
                "missing_rationale": None,
                "rationale_en": "The optional courses listed below are not available every year means students cannot do any of the optional courses that are listed, which is opposite to the statement.",
                "paraphrases": [],
            },
            6: {
                "evidence_type": "direct_support",
                "paragraph_label": "3",
                "quote": "Students wishing to take a course that does not appear in the list but is offered by the Faculty of History will need to get permission from the relevant Course Tutor.",
                "missing_rationale": None,
                "rationale_en": "Students wishing to take an unlisted course can do so if they get permission from the relevant course tutor, confirming the statement.",
                "paraphrases": [
                    {"prompt_term": "take an unlisted course", "passage_term": "a course that does not appear in the list"},
                    {"prompt_term": "appropriate approval", "passage_term": "permission from the relevant Course Tutor"},
                ],
            },
        }

        for q_num, ev_info in known_evidence.items():
            q_ent = q_map.get(q_num)
            ans_key = f"{q_num:03d}"
            ans_ent = ans_map.get(ans_key)

            if not q_ent or not ans_ent:
                continue

            ev_id = f"EVID-{volume_code}-{test_number:02d}-RD-{q_num:03d}-01"
            ev_entity = self.evidence_resolver.resolve_evidence(
                evidence_id=ev_id,
                answer=ans_ent,
                passage=passage_entity,
                evidence_type=ev_info["evidence_type"],  # type: ignore[arg-type]
                candidate_quote=ev_info["quote"],
                paragraph_label=ev_info["paragraph_label"],
                missing_information_rationale=ev_info["missing_rationale"],
                source_record=key_source,
                publication_permission="private_copyrighted",
            )
            evidence_entities.append(ev_entity)

            expl_id = f"EXPL-{volume_code}-{test_number:02d}-RD-{q_num:03d}"
            expl_entity = self.evidence_resolver.resolve_explanation(
                explanation_id=expl_id,
                question=q_ent,
                answer=ans_ent,
                evidence=ev_entity,
                rationale_en=ev_info["rationale_en"],
                rationale_vi=None,
                paraphrase_map=ev_info["paraphrases"],
                author_type="source_published",
                source_record=key_source,
                publication_permission="private_copyrighted",
            )
            explanation_entities.append(expl_entity)

        # 5. Persist entities and record checkpoints
        saved_files = []
        skipped_count = 0
        written_count = 0
        config_hash = "default_config"

        all_entities: List[Tuple[str, str, Any, str, str]] = [
            ("test", test_entity.test_id, test_entity, f"{test_entity.test_id}.json", doc_source["file_id"]),
            ("passage", passage_entity.passage_id, passage_entity, f"{passage_entity.passage_id}.json", doc_source["file_id"]),
        ]
        for g in group_entities:
            all_entities.append(("question_group", g.group_id, g, f"{g.group_id}.json", doc_source["file_id"]))
        for q in question_entities:
            all_entities.append(("question", q.question_id, q, f"{q.question_id}.json", doc_source["file_id"]))
        for a in answer_entities:
            all_entities.append(("answer", a.answer_id, a, f"{a.answer_id}.json", key_source["file_id"]))
        for e in evidence_entities:
            all_entities.append(("evidence", e.evidence_id, e, f"{e.evidence_id}.json", key_source["file_id"]))
        for ex in explanation_entities:
            all_entities.append(("explanation", ex.explanation_id, ex, f"{ex.explanation_id}.json", key_source["file_id"]))

        manifest_entries = []

        for entity_type, entity_id, entity_obj, filename, src_fid in all_entities:
            out_path = self.output_dir / filename

            # Checkpoint check
            if not force and is_normalization_checkpoint_valid(
                conn=conn,
                entity_id=entity_id,
                normalizer_version=self.normalizer_version,
                raw_sha256=raw_doc_sha,
                config_hash=config_hash,
                schema_version=SCHEMA_VERSION,
            ):
                skipped_count += 1
                saved_files.append(out_path)
                continue

            final_dict = BaseNormalizer.finalize_and_hash_entity(entity_obj)
            c_hash = final_dict["_provenance"]["canonical_content_sha256"]

            if not dry_run:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                BaseNormalizer.write_entity(out_path, final_dict)

                out_sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
                lifecycle = final_dict.get("quality_profile", {}).get("lifecycle_status", "extracted")

                # Upsert checkpoint
                upsert_normalization_checkpoint(
                    conn=conn,
                    cp_data={
                        "entity_id": entity_id,
                        "entity_type": entity_type,
                        "source_file_id": src_fid,
                        "source_legacy_id": doc_legacy_id if src_fid == doc_source["file_id"] else key_legacy_id,
                        "normalizer_version": self.normalizer_version,
                        "schema_version": SCHEMA_VERSION,
                        "config_hash": config_hash,
                        "raw_sha256": raw_doc_sha,
                        "canonical_content_sha256": c_hash,
                        "output_path": str(out_path),
                        "output_sha256": out_sha,
                        "lifecycle_status": lifecycle,
                        "status": "COMPLETED",
                    },
                )
                written_count += 1
                saved_files.append(out_path)

            manifest_entries.append({
                "entity_id": entity_id,
                "entity_type": entity_type,
                "canonical_content_sha256": c_hash,
                "output_filename": filename,
            })

        # Write execution run manifest
        if not dry_run:
            manifest_path = self.output_dir / "manifest.json"
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "pipeline": "harness_v02b_reading_pilot",
                        "normalizer_version": self.normalizer_version,
                        "schema_version": SCHEMA_VERSION,
                        "test_id": test_entity.test_id,
                        "total_entities": len(all_entities),
                        "written_count": written_count,
                        "skipped_count": skipped_count,
                        "entities": manifest_entries,
                    },
                    f,
                    indent=2,
                )

        conn.close()

        return {
            "test_id": test_entity.test_id,
            "passage_id": passage_entity.passage_id,
            "total_entities": len(all_entities),
            "written_count": written_count,
            "skipped_count": skipped_count,
            "dry_run": dry_run,
            "output_dir": str(self.output_dir),
            "files": [str(f) for f in saved_files],
            "stats": {
                "questions": len(question_entities),
                "answers": len(answer_entities),
                "evidence": len(evidence_entities),
                "explanations": len(explanation_entities),
            },
        }
