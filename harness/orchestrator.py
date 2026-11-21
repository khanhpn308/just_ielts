"""Normalization pipeline orchestrator for IELTS Data Harness V0.2."""

from __future__ import annotations

from datetime import datetime
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
    atomic_write_json,
    compute_canonical_content_hash,
    validate_output_privacy,
)
from harness.normalizers.evidence_resolver import EvidenceResolver
from harness.normalizers.reading_docx import DocxReadingNormalizer

STAGING_NORMALIZED_DIR = REPO_ROOT / "private" / "staging" / "normalized"
STAGING_RAW_DIR = REPO_ROOT / "private" / "staging" / "raw_extracted"

VALID_EVIDENCE_TYPES = {
    "direct_support",
    "contradictory_evidence",
    "insufficient_information_not_given",
}

ANNOTATION_METADATA_KEYS = {
    "pilot_id",
    "volume_code",
    "test_number",
    "passage_number",
    "source_legacy_id",
    "description",
    "version",
    "created_at",
    "updated_at",
    "notes",
}


def is_valid_timezone_aware_timestamp(ts: Any) -> bool:
    """Validates if a timestamp is a valid ISO 8601 string or datetime with timezone information."""
    if isinstance(ts, datetime):
        return ts.tzinfo is not None and ts.tzinfo.utcoffset(ts) is not None
    if not isinstance(ts, str) or not ts.strip():
        return False
    try:
        dt = datetime.fromisoformat(ts.strip())
        return dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None
    except Exception:
        return False


def is_authenticated_human_review(ev_info: Dict[str, Any]) -> bool:
    """Validates whether an annotation item has documented, authenticated human expert review.

    Requires a structured review event with:
    - reviewer_id: nonempty valid identifier
    - reviewed_at: valid timezone-aware timestamp
    - decision: approved / verified / accepted

    Does NOT accept reviewed_by_expert=True alone as sufficient proof.
    Rejects missing or malformed timestamps.
    """
    if not isinstance(ev_info, dict):
        return False

    rev_event = ev_info.get("review_event")
    if rev_event is None:
        # Check if ev_info itself is the review_event dictionary
        if "reviewer_id" in ev_info or "reviewed_at" in ev_info:
            rev_event = ev_info
        else:
            return False

    if not isinstance(rev_event, dict):
        return False

    # 1. Reviewer ID: nonempty valid identifier
    reviewer = rev_event.get("reviewer_id")
    if reviewer is None:
        reviewer = rev_event.get("expert_id") or rev_event.get("expert_reviewer")

    if not isinstance(reviewer, str):
        return False
    reviewer = reviewer.strip()
    invalid_reviewers = {"", "none", "null", "placeholder", "unassigned", "pending", "unknown"}
    if reviewer.lower() in invalid_reviewers:
        return False

    # 2. Decision: approved / verified / accepted
    decision = rev_event.get("decision")
    if decision is None:
        decision = rev_event.get("status")
    if not isinstance(decision, str):
        return False
    decision = decision.strip().lower()
    if decision not in {"approved", "verified", "accepted"}:
        return False

    # 3. Reviewed_at: valid timezone-aware timestamp
    raw_time = rev_event.get("reviewed_at")
    if raw_time is None:
        raw_time = rev_event.get("timestamp")
    if not is_valid_timezone_aware_timestamp(raw_time):
        return False

    return True


def parse_and_validate_annotations(ann_data: Any) -> Dict[int, Dict[str, Any]]:
    """Strictly parses and validates raw annotations data without swallowing exceptions.

    Rejects invalid formats, missing fields, and unapproved evidence types.
    """
    if not isinstance(ann_data, dict):
        raise ValueError(f"Annotations payload must be a JSON object, got {type(ann_data).__name__}")

    known_evidence: Dict[int, Dict[str, Any]] = {}

    if "annotations" in ann_data:
        items = ann_data["annotations"]
        if not isinstance(items, list):
            raise ValueError(f"'annotations' field must be a list, got {type(items).__name__}")

        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"Annotation item at index {idx} must be a JSON object, got {type(item).__name__}")

            raw_qn = item.get("question_number")
            if raw_qn is None:
                raise ValueError(f"Annotation item at index {idx} missing required 'question_number'")
            try:
                qn = int(raw_qn)
            except (ValueError, TypeError) as e:
                raise ValueError(f"Invalid 'question_number' {raw_qn!r} at index {idx}: must be an integer") from e

            if qn < 1 or qn > 40:
                raise ValueError(f"Question number {qn} out of range [1, 40] at index {idx}")

            if "evidence_type" not in item:
                raise ValueError(f"Annotation for question {qn} missing required 'evidence_type'")

            ev_type = item.get("evidence_type")
            if ev_type not in VALID_EVIDENCE_TYPES:
                raise ValueError(
                    f"Invalid evidence_type {ev_type!r} for question {qn}. "
                    f"Must be one of {sorted(VALID_EVIDENCE_TYPES)}"
                )

            known_evidence[qn] = item
    else:
        # Dictionary format: { "3": { ... }, "4": { ... } }
        for k, item in ann_data.items():
            if k in ANNOTATION_METADATA_KEYS:
                continue

            try:
                qn = int(k)
            except (ValueError, TypeError) as e:
                raise ValueError(
                    f"Invalid annotation key {k!r}: must be an integer question number or recognized metadata key"
                ) from e

            if qn < 1 or qn > 40:
                raise ValueError(f"Question number {qn} out of range [1, 40] for key {k!r}")

            if not isinstance(item, dict):
                raise ValueError(f"Annotation entry for question {qn} must be a dictionary, got {type(item).__name__}")

            if "evidence_type" not in item:
                raise ValueError(f"Annotation for question {qn} missing required 'evidence_type'")

            ev_type = item.get("evidence_type")
            if ev_type not in VALID_EVIDENCE_TYPES:
                raise ValueError(
                    f"Invalid evidence_type {ev_type!r} for question {qn}. "
                    f"Must be one of {sorted(VALID_EVIDENCE_TYPES)}"
                )

            known_evidence[qn] = item

    return known_evidence


class NormalizationOrchestrator:
    """Coordinates reading parsers, answer reconcilers, and evidence resolvers."""

    def __init__(
        self,
        output_dir: Path = STAGING_NORMALIZED_DIR,
        raw_staging_dir: Path = STAGING_RAW_DIR,
        normalizer_version: str = NORMALIZER_VERSION,
        db_path: Optional[Path] = None,
        authorized_private_roots: Optional[List[Path]] = None,
    ):
        self.output_dir = Path(output_dir)
        self.raw_staging_dir = Path(raw_staging_dir)
        self.normalizer_version = normalizer_version
        self.db_path = db_path
        self.authorized_private_roots = [
            p.resolve() for p in (authorized_private_roots or [REPO_ROOT / "private"])
        ]
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
        annotations_path: Optional[Path] = None,
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
            annotations_path=annotations_path,
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
        annotations_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Executes normalization for a Reading test passage with answer key & explanations."""
        conn = get_db_connection(self.db_path)

        doc_source = get_source_by_legacy_id(conn, doc_legacy_id)
        if not doc_source:
            conn.close()
            raise ValueError(f"Source {doc_legacy_id} not found in database inventory.")

        key_source = get_source_by_legacy_id(conn, key_legacy_id)
        if not key_source:
            conn.close()
            raise ValueError(f"Source {key_legacy_id} not found in database inventory.")

        # Physical source freshness validation
        for src in [doc_source, key_source]:
            rel_path = src.get("relative_path")
            if rel_path:
                phys_path = Path(rel_path) if Path(rel_path).is_absolute() else REPO_ROOT / rel_path
                if phys_path.is_file():
                    disk_sha = hashlib.sha256(phys_path.read_bytes()).hexdigest()
                    if disk_sha != src["content_sha256"]:
                        conn.close()
                        raise ValueError(
                            f"Physical source freshness violation for {src.get('legacy_id')}: "
                            f"on-disk SHA {disk_sha} != DB SHA {src['content_sha256']}"
                        )

        is_synthetic = doc_source.get("collection") == "synthetic"
        pub_permission = "public_synthetic" if is_synthetic else "private_copyrighted"

        # Enforce pre-write privacy policy validation on output directory
        validate_output_privacy(
            self.output_dir / "privacy_probe.json",
            {"quality_profile": {"publication_permission": pub_permission}},
            self.authorized_private_roots,
        )

        # 1. Load raw extraction artifacts
        raw_doc_path = self.raw_staging_dir / doc_legacy_id / "raw_document.json"
        if not raw_doc_path.exists():
            conn.close()
            raise FileNotFoundError(f"Raw extraction not found at {raw_doc_path}")

        raw_doc_bytes = raw_doc_path.read_bytes()
        raw_doc_sha = hashlib.sha256(raw_doc_bytes).hexdigest()
        raw_document = json.loads(raw_doc_bytes.decode("utf-8"))

        # Load key pages and compute raw_key_sha
        key_dir = self.raw_staging_dir / key_legacy_id
        key_pages = []
        key_hasher = hashlib.sha256()
        key_files = sorted(key_dir.glob("page_*.json")) if key_dir.exists() else []
        for p_file in key_files:
            p_bytes = p_file.read_bytes()
            key_hasher.update(p_bytes)
            key_pages.append(json.loads(p_bytes.decode("utf-8")))

        raw_key_sha = key_hasher.hexdigest() if key_files else key_source.get("content_sha256", "0" * 64)

        # 2. Parse Reading Passage and Questions
        reading_result = self.docx_normalizer.normalize(
            raw_document=raw_document,
            source_record=doc_source,
            test_number=test_number,
            passage_number=passage_number,
            volume_code=volume_code,
            publication_permission=pub_permission,
        )

        test_entity = reading_result["test"]
        passage_entity = reading_result["passage"]
        group_entities = reading_result["groups"]
        question_entities = reading_result["questions"]

        # 3. Parse and reconcile Answer Keys
        raw_keys = self.answer_reconciler.parse_pdf_ocr_explanation_keys(
            key_pages,
            test_number=test_number,
            passage_number=passage_number,
        )
        answer_entities = self.answer_reconciler.reconcile_answers(
            questions=question_entities,
            raw_key_map=raw_keys,
            source_record=key_source,
            volume_code=volume_code,
            test_number=test_number,
            publication_permission=pub_permission,
        )

        # 4. Resolve Evidence Spans and Explanations from private annotations
        evidence_entities: List[IELTSEvidence] = []
        explanation_entities: List[IELTSExplanation] = []

        q_map = {q.question_number: q for q in question_entities}
        ans_map = {a.answer_id.split("-")[-2]: a for a in answer_entities}

        known_evidence = {}
        evidence_source_sha = "none"

        ann_file = annotations_path
        if ann_file is None:
            cand_ann = REPO_ROOT / "private" / "annotations" / f"pilot_{test_number:02d}_reading_evidence.json"
            if cand_ann.exists():
                ann_file = cand_ann
            elif test_number == 5:
                default_ann = REPO_ROOT / "private" / "annotations" / "pilot_05_reading_evidence.json"
                if default_ann.exists():
                    ann_file = default_ann

        if ann_file:
            ann_path = Path(ann_file)
            if not ann_path.exists():
                conn.close()
                raise FileNotFoundError(f"Annotations file not found: {ann_path}")
            ann_bytes = ann_path.read_bytes()
            evidence_source_sha = hashlib.sha256(ann_bytes).hexdigest()
            try:
                ann_data = json.loads(ann_bytes.decode("utf-8"))
            except Exception as e:
                conn.close()
                raise ValueError(f"Malformed JSON in annotations file {ann_path}: {e}") from e

            try:
                known_evidence = parse_and_validate_annotations(ann_data)
            except Exception as e:
                conn.close()
                raise

        for q_num, ev_info in known_evidence.items():
            q_ent = q_map.get(q_num)
            ans_key = f"{q_num:03d}"
            ans_ent = ans_map.get(ans_key)

            if not q_ent or not ans_ent:
                continue

            # Verify presence in raw key_pages text
            expl_text = ev_info.get("rationale_en", "")
            search_term = ev_info.get("source_search_term") or (expl_text[:30] if expl_text else "")
            verified_in_source = False
            source_unit = ev_info.get("source_unit", "page_0001")
            matched_offset = None

            for kp in key_pages:
                kp_content = kp.get("content", {})
                kp_text = kp_content.get("text", "")
                if search_term and search_term.lower() in kp_text.lower():
                    verified_in_source = True
                    source_unit = kp.get("provenance", {}).get("unit_identifier") or f"page_{kp_content.get('page_number', 1):04d}"
                    idx = kp_text.lower().find(search_term.lower())
                    matched_offset = f"offset:{idx}-{idx + len(search_term)}"
                    break

            # Structured, authenticated human expert review event check
            has_human_review = is_authenticated_human_review(ev_info)

            if verified_in_source:
                author_type = "source_published"
                expl_verif = "source_provided"
            elif has_human_review:
                author_type = "expert_teacher"
                expl_verif = "expert_verified"
            else:
                author_type = "machine_drafted"
                expl_verif = "machine_drafted_unverified"

            ev_id = f"EVID-{volume_code}-{test_number:02d}-RD-{q_num:03d}-01"
            ev_entity = self.evidence_resolver.resolve_evidence(
                evidence_id=ev_id,
                answer=ans_ent,
                passage=passage_entity,
                evidence_type=ev_info["evidence_type"],  # type: ignore[arg-type]
                candidate_quote=ev_info.get("quote"),
                paragraph_label=ev_info.get("paragraph_label"),
                missing_information_rationale=ev_info.get("missing_rationale"),
                source_record=key_source,
                publication_permission=pub_permission,
                unit_identifier=source_unit,
                raw_block_locator=matched_offset or f"evidence:{ev_id}",
            )
            evidence_entities.append(ev_entity)

            expl_id = f"EXPL-{volume_code}-{test_number:02d}-RD-{q_num:03d}"
            expl_entity = self.evidence_resolver.resolve_explanation(
                explanation_id=expl_id,
                question=q_ent,
                answer=ans_ent,
                evidence=ev_entity,
                rationale_en=expl_text,
                rationale_vi=ev_info.get("rationale_vi"),
                paraphrase_map=ev_info.get("paraphrases"),
                author_type=author_type,
                source_record=key_source,
                publication_permission=pub_permission,
                unit_identifier=source_unit,
                raw_block_locator=matched_offset or f"explanation:{expl_id}",
                explanation_verification=expl_verif,
                has_human_review=has_human_review,
            )
            explanation_entities.append(expl_entity)

        # 5. Persist entities and record checkpoints
        saved_files = []
        skipped_count = 0
        written_count = 0
        config_hash = "default_config"

        # Dependency-aware checksums
        doc_dep_sha = raw_doc_sha
        ans_dep_sha = hashlib.sha256(f"{raw_doc_sha}:{raw_key_sha}".encode("utf-8")).hexdigest()
        evid_dep_sha = hashlib.sha256(f"{raw_doc_sha}:{raw_key_sha}:{evidence_source_sha}".encode("utf-8")).hexdigest()

        dep_map = {
            "test": doc_dep_sha,
            "passage": doc_dep_sha,
            "question_group": doc_dep_sha,
            "question": doc_dep_sha,
            "answer": ans_dep_sha,
            "evidence": evid_dep_sha,
            "explanation": evid_dep_sha,
        }

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
            expected_raw_sha = dep_map.get(entity_type, raw_doc_sha)

            # Checkpoint check
            if not force and is_normalization_checkpoint_valid(
                conn=conn,
                entity_id=entity_id,
                normalizer_version=self.normalizer_version,
                raw_sha256=expected_raw_sha,
                config_hash=config_hash,
                schema_version=SCHEMA_VERSION,
            ):
                skipped_count += 1
                saved_files.append(out_path)

                # Collect manifest entry for skipped entity to ensure manifest is complete
                c_hash = None
                if out_path.exists():
                    try:
                        existing = json.loads(out_path.read_text(encoding="utf-8"))
                        c_hash = existing.get("_provenance", {}).get("canonical_content_sha256")
                    except Exception:
                        pass
                if not c_hash:
                    final_dict = BaseNormalizer.finalize_and_hash_entity(entity_obj)
                    c_hash = final_dict["_provenance"]["canonical_content_sha256"]

                manifest_entries.append({
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "canonical_content_sha256": c_hash,
                    "output_filename": filename,
                })
                continue

            final_dict = BaseNormalizer.finalize_and_hash_entity(entity_obj)
            c_hash = final_dict["_provenance"]["canonical_content_sha256"]

            if not dry_run:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                BaseNormalizer.write_entity(out_path, final_dict, self.authorized_private_roots)

                out_sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
                lifecycle = final_dict.get("quality_profile", {}).get("lifecycle_status", "extracted")

                # Upsert checkpoint with dependency-aware raw_sha256
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
                        "raw_sha256": expected_raw_sha,
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

        # Stale Entity Reconciliation against active manifest
        stale_reconciled: List[Dict[str, Any]] = []
        other_entities: List[Dict[str, Any]] = []
        if not dry_run:
            manifest_path = self.output_dir / "manifest.json"
            if manifest_path.exists():
                try:
                    prev_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    prev_entities = prev_manifest.get("entities", [])
                    test_slug = test_entity.test_id.replace("TEST-IELTS-", "").rsplit("-", 1)[0]
                    other_entities = [
                        e for e in prev_entities
                        if test_slug not in e.get("entity_id", "")
                    ]

                    prev_map = {
                        e["entity_id"]: e
                        for e in prev_entities
                        if test_slug in e.get("entity_id", "") and e.get("output_filename")
                    }
                    current_entity_ids = {e[1] for e in all_entities}
                    stale_ids = set(prev_map.keys()) - current_entity_ids

                    for sid in stale_ids:
                        s_info = prev_map[sid]
                        s_filename = s_info.get("output_filename")
                        s_file = self.output_dir / s_filename
                        if s_file.exists():
                            archive_dir = self.output_dir / ".historical"
                            archive_dir.mkdir(parents=True, exist_ok=True)
                            archived_path = archive_dir / s_filename
                            s_file.rename(archived_path)
                            stale_reconciled.append({
                                "entity_id": sid,
                                "entity_type": s_info.get("entity_type"),
                                "archived_filename": s_filename,
                                "archived_path": str(archived_path),
                                "status": "deprecated_archived",
                            })
                        # Mark stale checkpoint as DEPRECATED
                        conn.execute(
                            "UPDATE normalization_checkpoints SET status = 'DEPRECATED' WHERE entity_id = ?",
                            (sid,),
                        )
                    conn.commit()
                except Exception:
                    pass

            # Write authoritative execution run manifest atomically
            merged_entities = other_entities + manifest_entries
            manifest_payload = {
                "pipeline": "harness_v02b_reading_pilot",
                "normalizer_version": self.normalizer_version,
                "schema_version": SCHEMA_VERSION,
                "test_id": test_entity.test_id,
                "total_entities": len(merged_entities),
                "written_count": written_count,
                "skipped_count": skipped_count,
                "entities": merged_entities,
                "stale_entities": stale_reconciled,
            }
            atomic_write_json(manifest_path, manifest_payload)

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
                "stale_reconciled": len(stale_reconciled),
            },
            "stale_entities": stale_reconciled,
        }
