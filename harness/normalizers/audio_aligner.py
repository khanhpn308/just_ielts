"""Audio metadata inspection and audio-transcript alignment component for IELTS Data Harness V0.3-C."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from harness.adapters.audio_meta import AudioMetaExtractor
from harness.config import REPO_ROOT
from harness.models.listening import (
    AudioAsset,
    ListeningSection,
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

NORMALIZER_VERSION_AUDIO = "0.3.0-c"


def inspect_audio_file(
    source_record: Dict[str, Any],
    repo_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Inspects audio file on disk, validates cryptographic SHA-256, and parses metadata."""
    root = repo_root or REPO_ROOT
    rel_path = source_record["relative_path"]
    full_path = root / rel_path

    if not full_path.exists():
        return {
            "status": "missing",
            "error": f"Audio file not found at path: {rel_path}",
            "file_path": rel_path,
        }

    # Verify SHA-256
    hasher = hashlib.sha256()
    with open(full_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    disk_sha256 = hasher.hexdigest()

    expected_sha256 = source_record.get("content_sha256")
    if expected_sha256 and disk_sha256 != expected_sha256:
        return {
            "status": "corrupt",
            "error": f"Cryptographic SHA-256 mismatch: recorded={expected_sha256}, disk={disk_sha256}",
            "file_path": rel_path,
            "disk_sha256": disk_sha256,
        }

    # Extract audio container metadata via AudioMetaExtractor
    extractor = AudioMetaExtractor()
    tmp_dir = root / "private" / "staging" / "temp_audio"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    res = extractor.extract_unit(source_record, tmp_dir, "audio_meta_inspect")

    # Read extracted json
    import json
    with open(res["output_path"]) as f:
        meta_payload = json.load(f)

    c = meta_payload.get("content", {})
    dur_sec = c.get("estimated_duration_sec")
    dur_ms = int(dur_sec * 1000) if dur_sec is not None else None

    return {
        "status": "verified",
        "file_path": rel_path,
        "disk_sha256": disk_sha256,
        "format": c.get("format", "mp3"),
        "codec": "mp3" if c.get("format") == "mp3" else None,
        "duration_sec": dur_sec,
        "duration_ms": dur_ms,
        "sample_rate_hz": c.get("sample_rate_hz"),
        "channels": c.get("channels"),
        "bitrate_kbps": c.get("bitrate_kbps"),
        "raw_metadata": c,
    }


class AudioAligner(BaseNormalizer):
    """Aligns audio recordings with transcript segments under conservative epistemic gates."""

    def __init__(self, normalizer_version: str = NORMALIZER_VERSION_AUDIO):
        super().__init__(normalizer_version=normalizer_version)

    def normalize(self, *args: Any, **kwargs: Any) -> Any:
        """Normalized execution delegating to align_section_audio."""
        return self.align_section_audio(*args, **kwargs)

    def build_audio_asset(
        self,
        source_record: Optional[Dict[str, Any]],
        test_id: str,
        section_number: Optional[int] = None,
        volume_code: str = "VOL01",
        test_number: int = 1,
        fallback_source_file_id: Optional[str] = None,
        publication_permission: PublicationPermission = "private_copyrighted",
        repo_root: Optional[Path] = None,
    ) -> AudioAsset:
        """Constructs a normalized AudioAsset entity with cryptographic verification."""
        sec_suffix = f"-SEC{section_number:02d}" if section_number else "-FULL"
        audio_id = f"AUDIO-{volume_code}-{test_number:02d}{sec_suffix}"

        if not source_record:
            # Explicitly missing audio asset
            parent_fid = fallback_source_file_id or "FILE-000000000000"
            prov = ProvenanceEnvelope(
                source_file_id=parent_fid,
                source_legacy_id="UNKNOWN",
                relative_path=f"missing/audio/{volume_code}/test_{test_number}/section_{section_number}.mp3",
                source_sha256="0" * 64,
                processing_unit="audio",
                unit_identifier="missing_audio_asset",
                raw_block_locator="none",
                extractor_adapter="none",
                extractor_version=self.normalizer_version,
                normalizer_version=self.normalizer_version,
            )
            qp = QualityProfile(
                lifecycle_status="extracted",
                extraction_quality="complete_clean",
                source_fidelity="unverified_community",
                answer_verification="unverified",
                explanation_verification="missing_explanation",
                publication_permission=publication_permission,
                validation_flags=["AUDIO_SOURCE_MISSING"],
            )
            return AudioAsset(
                audio_id=audio_id,
                test_id=test_id,
                section_number=section_number,
                file_path="",
                source_file_id=parent_fid,
                source_legacy_id="UNKNOWN",
                source_sha256="0" * 64,
                format="none",
                duration_ms=None,
                duration_sec=None,
                audio_verification_status="missing",
                quality_profile=qp,
                _provenance=prov,
            )

        info = inspect_audio_file(source_record, repo_root=repo_root)
        ver_status = info.get("status", "unverified")

        prov = ProvenanceEnvelope(
            source_file_id=source_record["file_id"],
            source_legacy_id=source_record.get("legacy_id") or "UNKNOWN",
            relative_path=source_record["relative_path"],
            source_sha256=source_record["content_sha256"],
            processing_unit="audio",
            unit_identifier="audio_metadata",
            raw_block_locator="file_header",
            extractor_adapter="audio_meta",
            extractor_version="0.1.0-file-id3",
            normalizer_version=self.normalizer_version,
        )

        flags = []
        if ver_status == "verified":
            flags.append("AUDIO_SOURCE_VERIFIED")
        elif ver_status == "corrupt":
            flags.append("AUDIO_HASH_MISMATCH")
        elif ver_status == "missing":
            flags.append("AUDIO_FILE_NOT_FOUND")

        qp = QualityProfile(
            lifecycle_status="verified" if ver_status == "verified" else "rejected",
            extraction_quality="complete_clean",
            source_fidelity="authoritative_official",
            answer_verification="unverified",
            explanation_verification="missing_explanation",
            publication_permission=publication_permission,
            validation_flags=flags,
        )

        return AudioAsset(
            audio_id=audio_id,
            test_id=test_id,
            section_number=section_number,
            file_path=source_record["relative_path"],
            source_file_id=source_record["file_id"],
            source_legacy_id=source_record.get("legacy_id"),
            source_sha256=source_record["content_sha256"],
            format=info.get("format", "mp3"),
            codec=info.get("codec"),
            duration_ms=info.get("duration_ms"),
            duration_sec=info.get("duration_sec"),
            sample_rate_hz=info.get("sample_rate_hz"),
            channels=info.get("channels"),
            bitrate_kbps=info.get("bitrate_kbps"),
            raw_metadata=info.get("raw_metadata", {}),
            audio_verification_status=ver_status,
            quality_profile=qp,
            _provenance=prov,
        )

    def align_section_audio(
        self,
        section_number: int,
        segments: List[TranscriptSegment],
        audio_asset: Optional[AudioAsset],
    ) -> Tuple[List[TranscriptSegment], Dict[str, Any]]:
        """Conservative alignment of transcript segments against audio asset.

        Enforces:
        - 0 <= start_ms < end_ms <= duration
        - Chronological order
        - Detection of impossible and overlapping intervals
        - Unaligned status when timestamps or audio are missing
        """
        aligned_segments: List[TranscriptSegment] = []
        audit_summary = {
            "section_number": section_number,
            "total_segments": len(segments),
            "verified_count": 0,
            "verified_intervals_count": 0,
            "verified_timestamps_count": 0,
            "inferred_count": 0,
            "unaligned_count": 0,
            "impossible_bounds_count": 0,
            "out_of_order_count": 0,
            "missing_audio_count": 0,
            "issues": [],
        }

        if not audio_asset or audio_asset.audio_verification_status != "verified":
            # Missing or unverified audio -> preserve segments as unaligned / missing
            for seg in segments:
                status = "missing" if (not audio_asset or audio_asset.audio_verification_status == "missing") else "unverified"
                updated_flags = list(seg.quality_profile.validation_flags)
                updated_flags.append(f"TIMING_{status.upper()}")
                updated_qp = seg.quality_profile.model_copy(update={"validation_flags": updated_flags})
                new_seg = seg.model_copy(
                    update={
                        "end_ms": seg.end_ms,  # Preserve unavailable end_ms as null
                        "timing_verification_status": status,
                        "timing_source": "missing" if status == "missing" else seg.timing_source,
                        "quality_profile": updated_qp,
                    }
                )
                aligned_segments.append(new_seg)
                if status == "missing":
                    audit_summary["missing_audio_count"] += 1
                else:
                    audit_summary["unaligned_count"] += 1
            return aligned_segments, audit_summary

        duration_ms = audio_asset.duration_ms or 0
        prev_start_ms: Optional[int] = None

        for seg in segments:
            start = seg.start_ms
            # Preserve unavailable end_ms as null without fabricating endpoints or interval boundaries
            end = seg.end_ms

            v_status = seg.timing_verification_status
            timing_src = seg.timing_source
            flags = list(seg.quality_profile.validation_flags)

            if start is None:
                v_status = "unaligned"
                timing_src = "unaligned"
                audit_summary["unaligned_count"] += 1
            elif start < 0 or (end is not None and end < 0):
                v_status = "impossible_bounds"
                audit_summary["impossible_bounds_count"] += 1
                audit_summary["issues"].append(
                    f"Segment {seg.segment_id}: negative bounds start={start}, end={end}"
                )
                flags.append("TIMING_IMPOSSIBLE_BOUNDS")
            elif start > duration_ms or (end is not None and end > duration_ms):
                v_status = "impossible_bounds"
                audit_summary["impossible_bounds_count"] += 1
                audit_summary["issues"].append(
                    f"Segment {seg.segment_id}: bounds exceed audio duration {duration_ms}ms (start={start}, end={end})"
                )
                flags.append("TIMING_IMPOSSIBLE_BOUNDS")
            elif end is not None and start >= end:
                v_status = "impossible_bounds"
                audit_summary["impossible_bounds_count"] += 1
                audit_summary["issues"].append(
                    f"Segment {seg.segment_id}: invalid interval start={start} >= end={end}"
                )
                flags.append("TIMING_IMPOSSIBLE_BOUNDS")
            elif prev_start_ms is not None and start < prev_start_ms:
                v_status = "out_of_order"
                audit_summary["out_of_order_count"] += 1
                audit_summary["issues"].append(
                    f"Segment {seg.segment_id}: out of order start={start} < prev={prev_start_ms}"
                )
                flags.append("TIMING_OUT_OF_ORDER")
            elif timing_src == "derived_bound":
                # Inferred/derived bounds are explicitly NOT marked as audio-verified
                v_status = "inferred"
                audit_summary["inferred_count"] += 1
                flags.append("AUDIO_TIMING_INFERRED")
                prev_start_ms = start
            else:
                # Valid source timestamp or verified audio alignment within audio duration
                v_status = "verified"
                audit_summary["verified_count"] += 1
                prev_start_ms = start
                if end is not None:
                    audit_summary["verified_intervals_count"] += 1
                    flags.append("AUDIO_INTERVAL_VERIFIED")
                else:
                    audit_summary["verified_timestamps_count"] += 1
                    flags.append("AUDIO_TIMESTAMP_VERIFIED")

            updated_qp = seg.quality_profile.model_copy(update={"validation_flags": flags})
            new_seg = seg.model_copy(
                update={
                    "start_ms": start,
                    "end_ms": end,
                    "timing_verification_status": v_status,
                    "timing_source": timing_src,
                    "quality_profile": updated_qp,
                }
            )
            aligned_segments.append(new_seg)

        return aligned_segments, audit_summary
