"""Configuration settings and constants for Harness V0.1."""

from pathlib import Path
import hashlib
import json

# Repository root and key directory paths
REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "private" / "raw"
STAGING_DIR = REPO_ROOT / "private" / "staging" / "raw_extracted"
STATE_DIR = REPO_ROOT / "harness" / "state"
DB_PATH = STATE_DIR / "harness.db"
INVENTORY_CSV = REPO_ROOT / "private" / "reports" / "discovery" / "source_inventory.csv"

# Global Harness and Schema versions
HARNESS_VERSION = "0.1.0"
OUTPUT_SCHEMA_VERSION = "v0.1.0-raw-block-schema"

# Parser adapter versions
PARSER_VERSIONS = {
    "pdf_native": "0.1.0-pdfminer",
    "pdf_ocr": "0.1.0-tesseract-pdftoppm",
    "docx": "0.1.0-lxml-docx",
    "xlsx": "0.1.0-lxml-xlsx",
    "audio_meta": "0.1.0-file-id3",
}

# Approved pilot candidates: 7 unique files across 6 pilot categories
PILOT_SOURCE_IDS = [
    "SRC-004",  # PILOT-01: Digital Strategy PDF (Ngoc Bach Process)
    "SRC-011",  # PILOT-02: Scanned Exam PDF (Vol 1 Test 1)
    "SRC-138",  # PILOT-03 & PILOT-05: Reading DOCX (Vol 6 Reading)
    "SRC-077",  # PILOT-04: Answer Key XLSX (Vol 3 Reading Key)
    "SRC-137",  # PILOT-05: Scanned Key & Explanations PDF (Vol 6 Reading Key)
    "SRC-008",  # PILOT-06: Listening MP3 (Vol 1 Test 1 AudioTrack 01)
    "SRC-012",  # PILOT-06: Listening Transcript DOCX (Vol 1 Test 1 Transcript)
]

# Extractor defaults
OCR_DPI = 200
OCR_LANG = "eng+vie"
OCR_PSM = "1"
MAX_OCR_WORKERS = 2

def compute_config_hash(config_dict: dict) -> str:
    """Computes deterministic 12-char SHA-256 hash of configuration dictionary."""
    serialized = json.dumps(config_dict, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]
