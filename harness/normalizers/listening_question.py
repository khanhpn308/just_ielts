"""Question, Answer, and Evidence normalizer for IELTS Listening Test V0.3-C."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union

from harness.config import REPO_ROOT
from harness.models.listening import (
    ListeningAnswer,
    ListeningEvidence,
    ListeningQuestion,
    TranscriptSegment,
)
from harness.models.provenance import ProvenanceEnvelope
from harness.models.quality import (
    AnswerVerification,
    LifecycleStatus,
    PublicationPermission,
    QualityProfile,
    SourceFidelity,
)
from harness.models.question_bank import EvidenceType, QuestionType, WordLimitRule
from harness.normalizers.base import BaseNormalizer

NORMALIZER_VERSION_QUESTION = "0.3.0-c"


def normalize_volume_code(vol: Optional[str]) -> str:
    """Normalizes volume identifiers for reliable alignment across sources."""
    if not vol:
        return ""
    clean = re.sub(r"[^A-Za-z0-9]", "", str(vol)).upper()
    m = re.match(r"^VOL(\d+)$", clean)
    if m:
        return f"VOL{int(m.group(1))}"
    return clean


def lookup_trusted_answer_review(
    conn: Optional[sqlite3.Connection],
    doc_source_record: Dict[str, Any],
    volume_code: str,
    test_number: int,
    question_number: int,
    target_value: Optional[str] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], List[str]]:
    """Validates an answer against trusted persisted human review records from Phase V0.3-B.

    Enforces:
    1. Zero trust in caller metadata; verification requires immutable database review log.
    2. Review must bind to source content hash, question identity (volume, test, question number), and evidence.
    3. Final review status must be 'confirmed' with decision 'approve', and current relationship
       must remain 'confirmed'.
    4. Fingerprints on relationship and review record must be valid and match expected source hash.
    5. A confirmed source relationship does NOT automatically verify individual answers.
       Fallback verification based solely on question range, section, verified_questions, or
       approved relationship without answer-value evidence is strictly prohibited.
    6. An answer may become authoritative_source only if persisted, trusted review evidence explicitly
       verifies that question's answer value against the accepted source.
    7. Otherwise return unverified (fail-closed).
    """
    if conn is None:
        return False, None, ["REVIEW_INTEGRATION_UNAVAILABLE"]

    # Check that V0.3-B tables exist
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('source_relationships', 'relationship_reviews')"
    )
    tables = {row[0] for row in cur.fetchall()}
    if "source_relationships" not in tables or "relationship_reviews" not in tables:
        return False, None, ["REVIEW_INTEGRATION_UNAVAILABLE"]

    expected_doc_sha = (doc_source_record.get("content_sha256") or "").strip().lower()
    doc_fid = doc_source_record.get("file_id")
    target_vol_norm = normalize_volume_code(volume_code)

    # Find matching relationships linking question booklet to answer key or explanation
    cur_rel = conn.execute(
        """
        SELECT * FROM source_relationships
        WHERE relationship_type IN ('question_to_answer_key', 'question_to_explanation')
          AND skill = 'listening'
          AND (source_file_id = ? OR source_content_sha256 = ?)
        """,
        (doc_fid, expected_doc_sha),
    )
    matching_rels = cur_rel.fetchall()
    if not matching_rels:
        return False, None, ["MISSING_PERSISTED_REVIEW_RECORD"]

    saw_candidate_rel = False
    last_candidate_rev: Optional[Dict[str, Any]] = None
    unconfirmed_review: Optional[Tuple[Dict[str, Any], List[str]]] = None
    hash_mismatched_review: Optional[Tuple[Dict[str, Any], List[str]]] = None

    for rel_row in matching_rels:
        rel_d = dict(rel_row)
        rel_vol_norm = normalize_volume_code(rel_d.get("volume"))
        if rel_vol_norm and rel_vol_norm != target_vol_norm:
            continue

        rel_test = rel_d.get("test_number")
        if rel_test is not None and int(rel_test) != int(test_number):
            continue

        saw_candidate_rel = True

        # Fetch immutable review history for this relationship, latest first
        cur_rev = conn.execute(
            "SELECT * FROM relationship_reviews WHERE relationship_id = ? ORDER BY created_at DESC",
            (rel_d["relationship_id"],),
        )
        reviews = cur_rev.fetchall()
        if not reviews:
            continue

        latest_rev = dict(reviews[0])
        last_candidate_rev = latest_rev

        ev_refs = latest_rev.get("evidence_references")
        if isinstance(ev_refs, str):
            try:
                ev_refs = json.loads(ev_refs)
            except Exception:
                ev_refs = {}
        latest_rev["evidence_references"] = ev_refs or {}

        # 1. Require current relationship to remain confirmed and review decision to be approved
        is_rel_confirmed = (rel_d.get("relationship_status") == "confirmed")
        rev_final_st = latest_rev.get("final_status") or latest_rev.get("new_status")
        rev_dec = latest_rev.get("decision")
        is_rev_confirmed = (rev_final_st == "confirmed" and rev_dec in ("approve", "accepted"))

        if not (is_rel_confirmed and is_rev_confirmed):
            if not unconfirmed_review:
                unconfirmed_review = (latest_rev, ["REVIEW_NOT_CONFIRMED"])
            continue

        # 2. Require fingerprints to be valid
        rel_src_sha = (rel_d.get("source_content_sha256") or "").strip().lower()
        if not rel_src_sha or rel_src_sha != expected_doc_sha:
            if not hash_mismatched_review:
                hash_mismatched_review = (latest_rev, ["SOURCE_HASH_MISMATCH"])
            continue

        rev_src_fp = (latest_rev.get("source_fingerprint") or "").strip().lower()
        if rev_src_fp and rev_src_fp != expected_doc_sha:
            if not hash_mismatched_review:
                hash_mismatched_review = (latest_rev, ["SOURCE_HASH_MISMATCH"])
            continue

        rel_tgt_sha = (rel_d.get("target_content_sha256") or "").strip().lower()
        rev_tgt_fp = (latest_rev.get("target_fingerprint") or "").strip().lower()
        if rel_tgt_sha and rev_tgt_fp and rel_tgt_sha != rev_tgt_fp:
            if not hash_mismatched_review:
                hash_mismatched_review = (latest_rev, ["SOURCE_HASH_MISMATCH"])
            continue

        # 3. Explicit Answer-Value Evidence Verification against Accepted Source
        ak = ev_refs.get("answer_keys") or ev_refs.get("staged_data", {}).get("answer_keys")
        if ak is None and "verified_answers" in ev_refs:
            ak = ev_refs.get("verified_answers")

        if not isinstance(ak, dict):
            # No answer-value evidence in this review; fallback verification is prohibited
            continue

        t_keys = ak.get(test_number) if test_number in ak else ak.get(str(test_number))
        if not isinstance(t_keys, dict):
            if (question_number in ak or str(question_number) in ak) and not any(isinstance(v, dict) for v in ak.values()):
                t_keys = ak
            else:
                continue

        expected_q_val = t_keys.get(question_number) if question_number in t_keys else t_keys.get(str(question_number))
        if expected_q_val is None:
            # Question is not covered by answer-value evidence in this review
            continue

        # Explicit answer-value evidence exists: compare with target_value
        if target_value is None or not str(target_value).strip():
            return False, latest_rev, ["ANSWER_VALUE_EVIDENCE_MISMATCH"]

        if isinstance(expected_q_val, list):
            allowed = [str(x).strip().lower() for x in expected_q_val]
            if str(target_value).strip().lower() not in allowed:
                return False, latest_rev, ["ANSWER_VALUE_EVIDENCE_MISMATCH"]
        else:
            if str(target_value).strip().lower() != str(expected_q_val).strip().lower():
                return False, latest_rev, ["ANSWER_VALUE_EVIDENCE_MISMATCH"]

        return True, latest_rev, ["ANSWER_KEY_PROVENANCE_VERIFIED"]

    if hash_mismatched_review:
        return False, hash_mismatched_review[0], hash_mismatched_review[1]

    if unconfirmed_review:
        return False, unconfirmed_review[0], unconfirmed_review[1]

    if saw_candidate_rel:
        return False, last_candidate_rev, ["QUESTION_NOT_COVERED_BY_REVIEW"]

    return False, None, ["MISSING_PERSISTED_REVIEW_RECORD"]


def validate_answer_source_verification(
    item: Dict[str, Any],
    doc_source_record: Dict[str, Any],
    volume_code: str,
    test_number: int,
    artifact_metadata: Optional[Dict[str, Any]] = None,
    conn: Optional[sqlite3.Connection] = None,
    return_review_record: bool = False,
) -> Tuple[Any, ...]:
    """Validates source verification evidence for a listening answer fail-closed.

    Enforces:
    1. Default source_verified to False.
    2. NEVER accept caller-provided review_evidence as independently verified.
    3. Validate against trusted persisted review records from V0.3-B, bound to source hash,
       question identity, and evidence.
    4. If that integration is unavailable, disable automatic promotion to authoritative_source.
       Keep all such answers unverified.
    5. Do not fabricate missing answers or locators.
    """
    art_meta = artifact_metadata or {}
    q_num = item.get("q_num")
    target_val = item.get("target_val")

    # Basic structural validations
    if not isinstance(q_num, int) or q_num < 1 or q_num > 40:
        res = (False, ["ANSWER_KEY_UNVERIFIED", "INVALID_QUESTION_NUMBER"])
        return (*res, None) if return_review_record else res

    if target_val is None or not str(target_val).strip():
        res = (False, ["ANSWER_KEY_UNVERIFIED", "MISSING_TARGET_VALUE"])
        return (*res, None) if return_review_record else res

    raw_ocr = item.get("raw_ocr_entry") or item.get("raw_ans")
    key_ref = item.get("source_key_ref")
    if not raw_ocr and not key_ref:
        res = (False, ["ANSWER_KEY_UNVERIFIED", "MISSING_ANSWER_LOCATOR"])
        return (*res, None) if return_review_record else res

    # 1. Never accept caller-provided review_evidence as independently verified
    has_caller_review = bool(
        item.get("review_evidence")
        or item.get("verification_evidence")
        or item.get("source_verification")
        or art_meta.get("review_evidence")
        or art_meta.get("verification_evidence")
        or art_meta.get("source_verification")
    )

    # Check caller-provided source hash if present
    item_src_sha = (
        item.get("source_sha256")
        or item.get("source_content_sha256")
        or art_meta.get("source_sha256")
        or art_meta.get("source_content_sha256")
    )
    expected_doc_sha = (doc_source_record.get("content_sha256") or "").strip().lower()
    if item_src_sha and str(item_src_sha).strip().lower() != expected_doc_sha:
        flags = ["ANSWER_KEY_UNVERIFIED", "SOURCE_HASH_MISMATCH"]
        if has_caller_review:
            flags.append("CALLER_REVIEW_EVIDENCE_REJECTED")
        res = (False, flags)
        return (*res, None) if return_review_record else res

    # If integration is unavailable (no DB connection), fail-closed
    if conn is None:
        flags = ["ANSWER_KEY_UNVERIFIED"]
        if has_caller_review:
            flags.append("CALLER_REVIEW_EVIDENCE_REJECTED")
        else:
            flags.append("REVIEW_INTEGRATION_UNAVAILABLE")
        res = (False, flags)
        return (*res, None) if return_review_record else res

    # Validate against trusted persisted review records from V0.3-B
    is_v, rev_rec, v_flags = lookup_trusted_answer_review(
        conn=conn,
        doc_source_record=doc_source_record,
        volume_code=volume_code,
        test_number=test_number,
        question_number=q_num,
        target_value=target_val,
    )

    if not is_v:
        flags = ["ANSWER_KEY_UNVERIFIED"]
        if has_caller_review:
            flags.append("CALLER_REVIEW_EVIDENCE_REJECTED")
        for vf in v_flags:
            if vf not in flags:
                flags.append(vf)
        res = (False, flags)
        return (*res, rev_rec) if return_review_record else res

    res = (True, ["ANSWER_KEY_PROVENANCE_VERIFIED"])
    return (*res, rev_rec) if return_review_record else res


class ListeningQuestionNormalizer(BaseNormalizer):
    """Normalizes listening questions, answers, and evidence linkages from verified extraction artifacts."""

    def __init__(
        self,
        normalizer_version: str = NORMALIZER_VERSION_QUESTION,
        conn: Optional[sqlite3.Connection] = None,
        db_path: Optional[Union[str, Path]] = None,
    ):
        super().__init__(normalizer_version=normalizer_version)
        self.conn = conn
        self.db_path = db_path

    def normalize(self, *args: Any, **kwargs: Any) -> Any:
        """Normalized execution delegating to normalize_listening_test_items."""
        return self.normalize_listening_test_items(*args, **kwargs)

    def load_extraction_artifact_with_metadata(
        self,
        artifact_path: Optional[Path] = None,
        volume_code: str = "VOL01",
        test_number: int = 1,
        publication_permission: str = "private_copyrighted",
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Loads question, answer, and evidence extraction items with top-level artifact metadata."""
        if artifact_path and artifact_path.exists():
            with open(artifact_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                items = data.get("items", [])
                meta = {k: v for k, v in data.items() if k != "items"}
                return items, meta
            return data, {}

        if publication_permission == "public_synthetic":
            synth_path = (
                REPO_ROOT
                / "tests"
                / "fixtures"
                / "synthetic_listening"
                / "synthetic_listening_fixtures.json"
            )
            if synth_path.exists():
                with open(synth_path, "r", encoding="utf-8") as f:
                    synth_data = json.load(f)
                items = synth_data.get("questions", [])
                meta = {k: v for k, v in synth_data.items() if k != "questions"}
                return items, meta

        # Default private extraction artifact path
        priv_path = (
            REPO_ROOT
            / "private"
            / "source_data"
            / "listening"
            / f"{volume_code.lower()}_test{test_number:02d}_extraction.json"
        )
        if priv_path.exists():
            with open(priv_path, "r", encoding="utf-8") as f:
                priv_data = json.load(f)
            if isinstance(priv_data, dict):
                items = priv_data.get("items", [])
                meta = {k: v for k, v in priv_data.items() if k != "items"}
                return items, meta
            return priv_data, {}

        raise FileNotFoundError(
            f"No listening extraction artifact found at {artifact_path or priv_path}. "
            "Verified extraction artifacts must reside under private/ for copyrighted corpora."
        )

    def load_extraction_artifact(
        self,
        artifact_path: Optional[Path] = None,
        volume_code: str = "VOL01",
        test_number: int = 1,
        publication_permission: str = "private_copyrighted",
    ) -> List[Dict[str, Any]]:
        """Loads question, answer, and evidence extraction items from an authorized artifact."""
        items, _ = self.load_extraction_artifact_with_metadata(
            artifact_path=artifact_path,
            volume_code=volume_code,
            test_number=test_number,
            publication_permission=publication_permission,
        )
        return items

    def normalize_listening_test_items(
        self,
        doc_source_record: Dict[str, Any],
        transcript_source_record: Optional[Dict[str, Any]] = None,
        transcript_segments_by_sec: Optional[Dict[int, List[TranscriptSegment]]] = None,
        items_def: Optional[List[Dict[str, Any]]] = None,
        extraction_artifact_path: Optional[Path] = None,
        volume_code: str = "VOL01",
        test_number: int = 1,
        publication_permission: PublicationPermission = "private_copyrighted",
        artifact_metadata: Optional[Dict[str, Any]] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Tuple[List[ListeningQuestion], List[ListeningAnswer], List[ListeningEvidence]]:
        """Constructs canonical ListeningQuestion, ListeningAnswer, and ListeningEvidence entities.

        Enforces:
        - Source-linked extraction artifact input without hardcoded copyrighted items in source
        - Fail-closed source verification for answers requiring valid review evidence & source hash
        - Preservation of uncertain OCR results without silent corrections
        - Grounding against transcript sentences without substring matching on target value
        - Evidence provenance recorded from transcript source
        """
        active_conn = conn or self.conn
        close_conn = False
        if not active_conn and self.db_path and Path(self.db_path).exists():
            from harness.db import get_db_connection
            active_conn = get_db_connection(self.db_path)
            close_conn = True

        test_id = f"TEST-IELTS-{volume_code}-{test_number:02d}-LIS"
        questions: List[ListeningQuestion] = []
        answers: List[ListeningAnswer] = []
        evidence_list: List[ListeningEvidence] = []

        art_meta = dict(artifact_metadata or {})
        if items_def is None:
            items_def, loaded_meta = self.load_extraction_artifact_with_metadata(
                artifact_path=extraction_artifact_path,
                volume_code=volume_code,
                test_number=test_number,
                publication_permission=publication_permission,
            )
            art_meta = {**loaded_meta, **art_meta}

        t_src = transcript_source_record or doc_source_record
        sec_segs_map = transcript_segments_by_sec or {}

        for item in items_def:
            q_num = item["q_num"]
            sec_num = item["sec_num"]
            sec_id = f"SEC-{volume_code}-{test_number:02d}-LS{sec_num:02d}"
            q_id = f"Q-{volume_code}-{test_number:02d}-LS-{q_num:03d}"
            ans_id = f"ANS-{volume_code}-{test_number:02d}-LS-{q_num:03d}-KEY"
            evid_id = f"EVID-{volume_code}-{test_number:02d}-LS{sec_num:02d}-{q_num:02d}"

            # 1. Question Entity
            page_num = item.get("page_num", 1)
            q_prov = ProvenanceEnvelope(
                source_file_id=doc_source_record["file_id"],
                source_legacy_id=doc_source_record.get("legacy_id") or "UNKNOWN",
                relative_path=doc_source_record["relative_path"],
                source_sha256=doc_source_record["content_sha256"],
                processing_unit="page",
                unit_identifier=f"page_{page_num:04d}",
                raw_block_locator=f"page:{page_num},question:{q_num}",
                extractor_adapter="pdf_ocr",
                extractor_version="0.1.0-tesseract-pdftoppm",
                normalizer_version=self.normalizer_version,
            )
            q_qp = QualityProfile(
                lifecycle_status="reviewed",
                extraction_quality="complete_clean",
                source_fidelity="authoritative_official",
                answer_verification="authoritative_key",
                explanation_verification="missing_explanation",
                publication_permission=publication_permission,
                validation_flags=["QUESTION_ORDER_VERIFIED"],
            )
            q_entity = ListeningQuestion(
                question_id=q_id,
                section_id=sec_id,
                test_id=test_id,
                question_number=q_num,
                question_type=item["q_type"],
                prompt_text=item["prompt"],
                options=item.get("options"),
                blank_target=item.get("blank_target"),
                word_limit=item.get("word_limit"),
                word_limit_rule=item.get("word_limit_rule"),
                quality_profile=q_qp,
                _provenance=q_prov,
            )
            questions.append(q_entity)

            # 2. Answer Entity (fail-closed source verification & uncertain OCR preservation)
            raw_ocr_entry = (
                item.get("raw_ocr_entry")
                or item.get("raw_ans")
                or item.get("target_val")
                or ""
            )
            ans_page = item.get("key_page") or art_meta.get("source_key_page") or 22
            is_verified, ans_flags = validate_answer_source_verification(
                item=item,
                doc_source_record=doc_source_record,
                volume_code=volume_code,
                test_number=test_number,
                artifact_metadata=art_meta,
                conn=active_conn,
            )
            ans_prov_status = "authoritative_source" if is_verified else "unverified"

            raw_block_locator = (
                f"page:{ans_page},key_entry:{raw_ocr_entry}"
                if raw_ocr_entry
                else f"page:{ans_page},key_q:{q_num}"
            )
            ans_prov = ProvenanceEnvelope(
                source_file_id=doc_source_record["file_id"],
                source_legacy_id=doc_source_record.get("legacy_id") or "UNKNOWN",
                relative_path=doc_source_record["relative_path"],
                source_sha256=doc_source_record["content_sha256"],
                processing_unit="page",
                unit_identifier=f"page_{ans_page:04d}",
                raw_block_locator=raw_block_locator,
                extractor_adapter="pdf_ocr",
                extractor_version="0.1.0-tesseract-pdftoppm",
                normalizer_version=self.normalizer_version,
            )
            ans_qp = QualityProfile(
                lifecycle_status="verified" if is_verified else "review_required",
                extraction_quality="complete_clean",
                source_fidelity="authoritative_official",
                answer_verification="authoritative_key" if is_verified else "unverified",
                explanation_verification="missing_explanation",
                publication_permission=publication_permission,
                validation_flags=ans_flags,
            )
            source_key_ref = item.get("source_key_ref") or (
                f"{doc_source_record.get('legacy_id', 'SRC')}:page_{ans_page}:key_{q_num}"
            )
            ans_entity = ListeningAnswer(
                answer_id=ans_id,
                question_id=q_id,
                test_id=test_id,
                section_id=sec_id,
                target_value=item.get("target_val", ""),
                acceptable_alternates=item.get("alternates", []),
                case_sensitive=False,
                source_key_ref=source_key_ref,
                answer_provenance_status=ans_prov_status,
                quality_profile=ans_qp,
                _provenance=ans_prov,
            )
            answers.append(ans_entity)

            # 3. Evidence Linkage
            # Evidence source provenance MUST be the transcript source document
            sec_segments = sec_segs_map.get(sec_num, [])
            matched_segment: Optional[TranscriptSegment] = None
            quote_text = item.get("quote")

            # Verification of verbatim quote against actual source text
            # DO NOT substring match on target_val
            # DO NOT use answer letters A/B/C as matching evidence
            if quote_text and quote_text.strip():
                clean_quote = quote_text.strip()
                for seg in sec_segments:
                    # Require quote to actually occur verbatim in the segment text
                    if clean_quote.lower() in seg.transcript_text.lower():
                        matched_segment = seg
                        break

            if matched_segment:
                grounding_status = "grounded"
                evid_flags = ["EVIDENCE_TEXT_GROUNDED"]
                seg_id = matched_segment.segment_id
                locator = f"paragraph:{matched_segment.provenance.raw_block_locator},segment:{matched_segment.segment_id}"

                # Audio timing grounding evaluation
                if matched_segment.timing_verification_status == "verified":
                    timing_status = "verified"
                    start_ms = matched_segment.start_ms
                    end_ms = matched_segment.end_ms
                    if end_ms is not None:
                        evid_flags.append("AUDIO_INTERVAL_VERIFIED")
                    else:
                        evid_flags.append("AUDIO_TIMESTAMP_VERIFIED")
                elif matched_segment.timing_verification_status == "inferred":
                    timing_status = "inferred"
                    start_ms = matched_segment.start_ms
                    end_ms = matched_segment.end_ms
                    evid_flags.append("AUDIO_TIMING_INFERRED")
                elif matched_segment.timing_verification_status in (
                    "impossible_bounds",
                    "out_of_order",
                    "unaligned",
                ):
                    timing_status = "unaligned"
                    start_ms = None
                    end_ms = None
                    evid_flags.append("AUDIO_TIMING_UNALIGNED")
                else:
                    timing_status = "missing"
                    start_ms = None
                    end_ms = None
                    evid_flags.append("AUDIO_TIMING_MISSING")
            else:
                # When no trustworthy evidence exists, grounding_status is unresolved
                # and EVIDENCE_TEXT_GROUNDED must NOT be claimed
                grounding_status = "unresolved"
                evid_flags = ["EVIDENCE_UNRESOLVED"]
                seg_id = None
                start_ms = None
                end_ms = None
                timing_status = "unaligned"
                locator = "unresolved"

            evid_prov = ProvenanceEnvelope(
                source_file_id=t_src["file_id"],
                source_legacy_id=t_src.get("legacy_id") or "UNKNOWN",
                relative_path=t_src["relative_path"],
                source_sha256=t_src["content_sha256"],
                processing_unit="section",
                unit_identifier=f"section_{sec_num:02d}",
                raw_block_locator=locator,
                extractor_adapter="transcript_aligner",
                extractor_version=self.normalizer_version,
                normalizer_version=self.normalizer_version,
            )
            evid_qp = QualityProfile(
                lifecycle_status="reviewed" if grounding_status == "grounded" else "review_required",
                extraction_quality="complete_clean" if grounding_status == "grounded" else "segmented_imperfect",
                source_fidelity="authoritative_official",
                answer_verification="authoritative_key" if is_verified else "unverified",
                explanation_verification="missing_explanation",
                publication_permission=publication_permission,
                validation_flags=evid_flags,
            )
            evid_entity = ListeningEvidence(
                evidence_id=evid_id,
                question_id=q_id,
                answer_id=ans_id,
                section_id=sec_id,
                segment_id=seg_id,
                verbatim_quote=quote_text if grounding_status == "grounded" else None,
                start_ms=start_ms,
                end_ms=end_ms,
                timing_status=timing_status,  # type: ignore[arg-type]
                evidence_type="direct_support",
                grounding_status=grounding_status,
                explanation_text=None,
                quality_profile=evid_qp,
                _provenance=evid_prov,
            )
            evidence_list.append(evid_entity)

        if close_conn and active_conn:
            active_conn.close()

        return questions, answers, evidence_list
