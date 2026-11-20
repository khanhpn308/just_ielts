"""Transcript extractor and normalizer for IELTS Data Harness V0.3-C."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from harness.models.listening import (
    ListeningSection,
    SpeakerTurn,
    TranscriptSegment,
)
from harness.models.provenance import ProvenanceEnvelope
from harness.models.quality import (
    ExtractionQuality,
    LifecycleStatus,
    PublicationPermission,
    QualityProfile,
    SourceFidelity,
)
from harness.normalizers.base import BaseNormalizer

NORMALIZER_VERSION_TRANSCRIPT = "0.3.0-c"

# Timestamp pattern: [HH:MM:SS] or [MM:SS]
RE_TIMESTAMP = re.compile(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]")
# Speaker label pattern: Speaker \d+ or named speaker prefix
RE_SPEAKER_PREFIX = re.compile(
    r"^(?:(Speaker\s+\d+|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?))\s+(?:\[(\d{1,2}:\d{2}(?::\d{2})?)\])?\s*(.*)$",
    re.DOTALL,
)
RE_TIMESTAMP_ONLY_PREFIX = re.compile(
    r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)$",
    re.DOTALL,
)
RE_SECTION_END = re.compile(
    r"That is the end of (?:[Ss]ection|[Pp]art)\s+(one|two|three|four|\d+)",
    re.IGNORECASE,
)
RE_DIVIDER = re.compile(r"^-{5,}$")


def parse_timestamp_to_ms(ts_str: str) -> Optional[int]:
    """Converts a timestamp string [HH:MM:SS] or [MM:SS] into milliseconds.

    Returns None if format is invalid.
    """
    clean_ts = ts_str.strip("[]").strip()
    parts = clean_ts.split(":")
    try:
        if len(parts) == 3:
            hh, mm, ss = int(parts[0]), int(parts[1]), float(parts[2])
            return int((hh * 3600 + mm * 60 + ss) * 1000)
        elif len(parts) == 2:
            mm, ss = int(parts[0]), float(parts[1])
            return int((mm * 60 + ss) * 1000)
    except (ValueError, TypeError):
        return None
    return None


class TranscriptNormalizer(BaseNormalizer):
    """Normalizes raw transcript paragraphs into canonical TranscriptSegment and SpeakerTurn entities."""

    def __init__(self, normalizer_version: str = NORMALIZER_VERSION_TRANSCRIPT):
        super().__init__(normalizer_version=normalizer_version)

    def normalize(
        self,
        paragraphs: List[Dict[str, Any]],
        source_record: Dict[str, Any],
        volume_code: str = "VOL01",
        test_number: int = 1,
        publication_permission: PublicationPermission = "private_copyrighted",
    ) -> Dict[int, Dict[str, Any]]:
        """Normalize raw transcript paragraphs into canonical sections with segments and turns."""
        return self.segment_transcript(
            paragraphs=paragraphs,
            source_record=source_record,
            volume_code=volume_code,
            test_number=test_number,
            publication_permission=publication_permission,
        )

    def parse_paragraph_line(
        self, raw_text: str
    ) -> Tuple[Optional[str], Optional[str], Optional[int], str]:
        """Parses a transcript paragraph line into (speaker_id, raw_ts_str, start_ms, text).

        Preserves original wording without silent corrections.
        """
        line = raw_text.strip()
        speaker_id: Optional[str] = None
        raw_ts: Optional[str] = None
        start_ms: Optional[int] = None
        text = line

        # 1. Match "Speaker X [00:00:00] text" or "Speaker X text"
        m_spk = RE_SPEAKER_PREFIX.match(line)
        if m_spk:
            candidate_spk = m_spk.group(1).strip()
            # Guard against common words mistaken for speaker names (e.g. "Audio", "That")
            if candidate_spk.lower() not in {"audio", "that", "this", "the", "in", "it"}:
                speaker_id = candidate_spk
                raw_ts = m_spk.group(2)
                text = m_spk.group(3).strip()
                if raw_ts:
                    start_ms = parse_timestamp_to_ms(raw_ts)
                return speaker_id, raw_ts, start_ms, text

        # 2. Match "[00:00:00] text" without speaker
        m_ts = RE_TIMESTAMP_ONLY_PREFIX.match(line)
        if m_ts:
            raw_ts = m_ts.group(1)
            text = m_ts.group(2).strip()
            start_ms = parse_timestamp_to_ms(raw_ts)
            return speaker_id, raw_ts, start_ms, text

        # 3. Plain line
        return speaker_id, raw_ts, start_ms, text

    def segment_transcript(
        self,
        paragraphs: List[Dict[str, Any]],
        source_record: Dict[str, Any],
        volume_code: str = "VOL01",
        test_number: int = 1,
        publication_permission: PublicationPermission = "private_copyrighted",
    ) -> Dict[int, Dict[str, Any]]:
        """Segments raw transcript paragraphs into 4 sections with segments and speaker turns.

        Returns mapping from section_number (1..4) to section payload dict:
        {
            'section_number': int,
            'segments': List[TranscriptSegment],
            'speaker_turns': List[SpeakerTurn],
            'raw_locators': List[str]
        }
        """
        test_id = f"TEST-IELTS-{volume_code}-{test_number:02d}-LIS"
        current_section = 1
        section_data: Dict[int, Dict[str, Any]] = {
            s: {"section_number": s, "segments": [], "speaker_turns": [], "raw_locators": []}
            for s in range(1, 5)
        }

        active_speaker: Optional[str] = None
        current_turn_segments: List[TranscriptSegment] = []
        turn_counter = 0
        segment_counter = 0

        for idx, p in enumerate(paragraphs):
            raw_text = p.get("text", "").strip()
            if not raw_text:
                continue

            # Skip file header comments (e.g. "Audio Test 1.mp3")
            if raw_text.lower().startswith("audio test") or raw_text.lower().endswith(".mp3"):
                continue

            # Skip divider lines
            if RE_DIVIDER.match(raw_text):
                continue

            # Parse line
            spk, raw_ts, start_ms, text = self.parse_paragraph_line(raw_text)

            # End of section check
            is_end_of_sec = bool(RE_SECTION_END.search(raw_text))

            locator = f"para_index:{idx}"
            sec_id = f"SEC-{volume_code}-{test_number:02d}-LS{current_section:02d}"
            segment_counter += 1
            segment_id = f"TRANS-{volume_code}-{test_number:02d}-LS{current_section:02d}-SEG{segment_counter:03d}"

            prov = ProvenanceEnvelope(
                source_file_id=source_record["file_id"],
                source_legacy_id=source_record.get("legacy_id") or "UNKNOWN",
                relative_path=source_record["relative_path"],
                source_sha256=source_record["content_sha256"],
                processing_unit="transcript",
                unit_identifier="transcript_docx",
                raw_block_locator=locator,
                extractor_adapter="docx",
                extractor_version="0.1.0-docx-lxml",
                normalizer_version=self.normalizer_version,
            )

            qp = QualityProfile(
                lifecycle_status="extracted",
                extraction_quality="complete_clean",
                source_fidelity="authoritative_official",
                answer_verification="unverified",
                explanation_verification="missing_explanation",
                publication_permission=publication_permission,
                validation_flags=["SOURCE_TIMESTAMP_PRESENT"] if start_ms is not None else ["UNALIGNED_SEGMENT"],
            )

            timing_src = "source_timestamp" if start_ms is not None else "unaligned"
            timing_ver = "unverified" if start_ms is not None else "unaligned"

            segment = TranscriptSegment(
                segment_id=segment_id,
                section_id=sec_id,
                test_id=test_id,
                sequence_index=len(section_data[current_section]["segments"]),
                speaker_id=spk,
                transcript_text=text,
                start_ms=start_ms,
                end_ms=None,  # Conservatively left None until audio alignment resolves boundaries
                timing_source=timing_src,
                timing_verification_status=timing_ver,
                raw_timestamp_str=f"[{raw_ts}]" if raw_ts else None,
                quality_profile=qp,
                _provenance=prov,
            )

            section_data[current_section]["segments"].append(segment)
            section_data[current_section]["raw_locators"].append(locator)

            # Speaker turn clustering:
            speaker_for_turn = spk or active_speaker or "Unknown Speaker"
            if spk and spk != active_speaker and current_turn_segments:
                # Flush previous turn
                turn_counter += 1
                turn_id = f"TURN-{volume_code}-{test_number:02d}-LS{current_section:02d}-{turn_counter:03d}"
                turn_prov = ProvenanceEnvelope(
                    source_file_id=source_record["file_id"],
                    source_legacy_id=source_record.get("legacy_id") or "UNKNOWN",
                    relative_path=source_record["relative_path"],
                    source_sha256=source_record["content_sha256"],
                    processing_unit="transcript",
                    unit_identifier="transcript_docx",
                    raw_block_locator=f"turn_segments:{current_turn_segments[0].segment_id}..{current_turn_segments[-1].segment_id}",
                    extractor_adapter="docx",
                    extractor_version="0.1.0-docx-lxml",
                    normalizer_version=self.normalizer_version,
                )
                turn_qp = QualityProfile(
                    lifecycle_status="extracted",
                    extraction_quality="complete_clean",
                    source_fidelity="authoritative_official",
                    answer_verification="unverified",
                    explanation_verification="missing_explanation",
                    publication_permission=publication_permission,
                    validation_flags=[],
                )
                turn = SpeakerTurn(
                    turn_id=turn_id,
                    section_id=sec_id,
                    speaker_id=active_speaker or "Unknown Speaker",
                    turn_index=len(section_data[current_section]["speaker_turns"]),
                    text=" ".join(s.transcript_text for s in current_turn_segments),
                    start_ms=current_turn_segments[0].start_ms,
                    end_ms=current_turn_segments[-1].end_ms,
                    segment_ids=[s.segment_id for s in current_turn_segments],
                    quality_profile=turn_qp,
                    _provenance=turn_prov,
                )
                section_data[current_section]["speaker_turns"].append(turn)
                current_turn_segments = []

            if spk:
                active_speaker = spk

            current_turn_segments.append(segment)

            if is_end_of_sec:
                # Flush remaining turn in section
                if current_turn_segments:
                    turn_counter += 1
                    turn_id = f"TURN-{volume_code}-{test_number:02d}-LS{current_section:02d}-{turn_counter:03d}"
                    turn_prov = ProvenanceEnvelope(
                        source_file_id=source_record["file_id"],
                        source_legacy_id=source_record.get("legacy_id") or "UNKNOWN",
                        relative_path=source_record["relative_path"],
                        source_sha256=source_record["content_sha256"],
                        processing_unit="transcript",
                        unit_identifier="transcript_docx",
                        raw_block_locator=f"turn_segments:{current_turn_segments[0].segment_id}..{current_turn_segments[-1].segment_id}",
                        extractor_adapter="docx",
                        extractor_version="0.1.0-docx-lxml",
                        normalizer_version=self.normalizer_version,
                    )
                    turn_qp = QualityProfile(
                        lifecycle_status="extracted",
                        extraction_quality="complete_clean",
                        source_fidelity="authoritative_official",
                        answer_verification="unverified",
                        explanation_verification="missing_explanation",
                        publication_permission=publication_permission,
                        validation_flags=[],
                    )
                    turn = SpeakerTurn(
                        turn_id=turn_id,
                        section_id=sec_id,
                        speaker_id=active_speaker or "Unknown Speaker",
                        turn_index=len(section_data[current_section]["speaker_turns"]),
                        text=" ".join(s.transcript_text for s in current_turn_segments),
                        start_ms=current_turn_segments[0].start_ms,
                        end_ms=current_turn_segments[-1].end_ms,
                        segment_ids=[s.segment_id for s in current_turn_segments],
                        quality_profile=turn_qp,
                        _provenance=turn_prov,
                    )
                    section_data[current_section]["speaker_turns"].append(turn)
                    current_turn_segments = []

                if current_section < 4:
                    current_section += 1
                    active_speaker = None
                    turn_counter = 0

        # Flush any trailing turn
        if current_turn_segments and current_section <= 4:
            turn_counter += 1
            sec_id = f"SEC-{volume_code}-{test_number:02d}-LS{current_section:02d}"
            turn_id = f"TURN-{volume_code}-{test_number:02d}-LS{current_section:02d}-{turn_counter:03d}"
            turn_prov = ProvenanceEnvelope(
                source_file_id=source_record["file_id"],
                source_legacy_id=source_record.get("legacy_id") or "UNKNOWN",
                relative_path=source_record["relative_path"],
                source_sha256=source_record["content_sha256"],
                processing_unit="transcript",
                unit_identifier="transcript_docx",
                raw_block_locator=f"turn_segments:{current_turn_segments[0].segment_id}..{current_turn_segments[-1].segment_id}",
                extractor_adapter="docx",
                extractor_version="0.1.0-docx-lxml",
                normalizer_version=self.normalizer_version,
            )
            turn_qp = QualityProfile(
                lifecycle_status="extracted",
                extraction_quality="complete_clean",
                source_fidelity="authoritative_official",
                answer_verification="unverified",
                explanation_verification="missing_explanation",
                publication_permission=publication_permission,
                validation_flags=[],
            )
            turn = SpeakerTurn(
                turn_id=turn_id,
                section_id=sec_id,
                speaker_id=active_speaker or "Unknown Speaker",
                turn_index=len(section_data[current_section]["speaker_turns"]),
                text=" ".join(s.transcript_text for s in current_turn_segments),
                start_ms=current_turn_segments[0].start_ms,
                end_ms=current_turn_segments[-1].end_ms,
                segment_ids=[s.segment_id for s in current_turn_segments],
                quality_profile=turn_qp,
                _provenance=turn_prov,
            )
            section_data[current_section]["speaker_turns"].append(turn)

        return section_data
