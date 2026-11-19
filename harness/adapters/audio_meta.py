"""Audio metadata extractor adapter using system file inspection and ID3 header parsing."""

from pathlib import Path
import re
import struct
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from harness.adapters.base import BaseExtractor
from harness.config import PARSER_VERSIONS, REPO_ROOT
from harness.dependencies import require_system_tool


class AudioMetaExtractor(BaseExtractor):
    """Adapter for audio and media files (MP3, WAV, MP4) extracting metadata and tags."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(
            name="audio_meta",
            version=PARSER_VERSIONS["audio_meta"],
            config=config or {"parse_id3": True},
        )

    def get_processing_units(self, source_record: Dict[str, Any]) -> List[str]:
        """Audio files are processed as a single metadata unit in V0.1."""
        return ["audio_metadata"]

    def _parse_id3_frames(self, file_path: Path) -> Tuple[Dict[str, str], int]:
        """Parses ID3v2 tags and returns (tags_dict, id3_size_bytes)."""
        tags: Dict[str, str] = {}
        id3_size = 0
        try:
            with open(file_path, "rb") as f:
                header = f.read(10)
                if not header.startswith(b"ID3"):
                    return tags, 0

                b0, b1, b2, b3 = header[6:10]
                id3_size = ((b0 & 0x7F) << 21) | ((b1 & 0x7F) << 14) | ((b2 & 0x7F) << 7) | (b3 & 0x7F)
                tag_data = f.read(id3_size)
                idx = 0
                while idx + 10 < len(tag_data):
                    frame_id = tag_data[idx : idx + 4].decode("latin1", errors="ignore")
                    if not frame_id.isalnum() or frame_id == "\x00\x00\x00\x00":
                        break
                    f_size = struct.unpack(">I", tag_data[idx + 4 : idx + 8])[0]
                    idx += 10
                    f_body = tag_data[idx : idx + f_size]
                    idx += f_size
                    if not f_body:
                        continue
                    try:
                        # Encoding byte: 0x01/0x03 -> utf-16/utf-8, else latin1
                        enc = "utf-8" if f_body[0:1] in [b"\x01", b"\x03"] else "latin1"
                        val = f_body[1:].decode(enc, errors="replace").strip("\x00 \t\r\n")
                        if val:
                            tags[frame_id] = val
                    except Exception:
                        pass
        except Exception:
            pass
        return tags, id3_size

    def extract_unit(
        self,
        source_record: Dict[str, Any],
        output_dir: Path,
        unit_identifier: str = "audio_metadata",
    ) -> Dict[str, Any]:
        """Extracts media codec, bitrate, channels, and metadata tags."""
        cmd_file = require_system_tool("file", system_package="file", feature_description="Media format inspection")

        file_path = REPO_ROOT / source_record["relative_path"]
        ext = source_record.get("extension", "").lower().lstrip(".")

        # Run system file utility
        raw_info = ""
        try:
            res = subprocess.run([cmd_file, str(file_path)], capture_output=True, text=True, check=True)
            raw_info = res.stdout.strip()
        except Exception as e:
            raw_info = f"Error running file: {e}"

        # Parse bitrate, sample rate, channels from file info
        bitrate_kbps = None
        sample_rate_hz = None
        channels = None

        m_bitrate = re.search(r"(\d+)\s*kbps", raw_info, re.IGNORECASE)
        if m_bitrate:
            bitrate_kbps = int(m_bitrate.group(1))

        m_sample = re.search(r"([\d\.]+)\s*kHz", raw_info, re.IGNORECASE)
        if m_sample:
            sample_rate_hz = int(float(m_sample.group(1)) * 1000)

        if "stereo" in raw_info.lower():
            channels = "Stereo"
        elif "mono" in raw_info.lower():
            channels = "Mono"

        # Parse ID3 tags if available
        id3_tags, id3_size = self._parse_id3_frames(file_path)

        # Estimate duration
        duration_sec = None
        if "TLEN" in id3_tags and id3_tags["TLEN"].replace(".", "").isdigit():
            # TLEN is in milliseconds
            try:
                duration_sec = round(float(id3_tags["TLEN"]) / 1000.0, 2)
            except Exception:
                pass
        elif bitrate_kbps and bitrate_kbps > 0:
            audio_bytes = max(0, source_record["size_bytes"] - (id3_size + 10))
            duration_sec = round((audio_bytes * 8.0) / (bitrate_kbps * 1000.0), 2)

        provenance = self.build_provenance(
            source_record=source_record,
            processing_unit="audio_metadata",
            unit_identifier=unit_identifier,
        )

        payload = {
            "provenance": provenance,
            "content": {
                "format": ext,
                "bitrate_kbps": bitrate_kbps,
                "sample_rate_hz": sample_rate_hz,
                "channels": channels,
                "estimated_duration_sec": duration_sec,
                "id3_tags": id3_tags,
                "raw_file_info": raw_info,
            },
        }

        target_file = output_dir / f"{unit_identifier}.json"
        out_sha256, out_size = self.atomic_write_json(target_file, payload)

        return {
            "processing_unit": "audio_metadata",
            "unit_identifier": unit_identifier,
            "output_path": str(target_file),
            "output_sha256": out_sha256,
            "output_size": out_size,
            "status": "COMPLETED",
            "output_validity": "valid",
        }
