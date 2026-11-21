# IELTS Data Harness V0.3 — Phase V0.3-C Engineering Report (Remediated)
**Phase:** V0.3-C Listening Transcript & Audio Alignment Pilot & Data Integrity Remediation  
**Role:** Senior Python Engineer, Data Quality Engineer, and IELTS Listening Assessment Specialist  
**Repository:** `~/projects/just_ielts`  
**Base Branch:** `main`  
**Working Branch:** `feat/harness-v0.3c`  
**Date:** 2026-11-21  

---

## 1. Executive Summary & Mission

Phase V0.3-C extends the IELTS Data Harness to pilot the end-to-end normalization of authentic IELTS Listening examinations, establishing unbroken evidentiary linkages across the complete assessment lifecycle:

$$\text{Audio} \longrightarrow \text{Transcript} \longrightarrow \text{Sections} \longrightarrow \text{Questions} \longrightarrow \text{Answers} \longrightarrow \text{Evidence} \longrightarrow \text{Explanations}$$

Following review of PR #7 (reviewed commit `892d8aa`), four critical P0 data integrity defects were identified and remediated under strict epistemic conservativism:
1. **Timing Verification:** Removed fabricated 30-second interval endpoints; distinguished source timestamps from derived bounds; never marked inferred intervals as audio-verified; preserved unavailable `end_ms` as `null`; and retained `impossible_bounds` for out-of-bounds/cumulative timestamps.
2. **Evidence Linkage:** Removed fragile substring matching on `target_val` and option letters (A/B/C); enforced verifiable quote matching against transcript paragraphs; recorded evidence provenance from the transcript document (`SRC-012`), not the question booklet; and surfaced ungrounded items as `grounding_status = "unresolved"` without claiming `EVIDENCE_TEXT_GROUNDED`.
3. **Source Data Isolation:** Removed real copyrighted IELTS questions, keys, and transcript excerpts from public source code; quarantined authentic extraction data under `private/source_data/listening/`; utilized purely synthetic fixtures in public tests; preserved uncertain OCR results without silent correction; and reported historical exposure without unauthorized git history rewriting.
4. **Dependency-Aware Checkpoints:** Replaced coarse document-level hashes with granular, independent entity dependency hashing (`question_doc_sha256`, `transcript_doc_sha256`, `audio_asset_sha256`, `normalizer_version`, `config_hash`, `schema_version`), enabling selective invalidation across all change scenarios.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│              V0.3-C REMEDIATED LISTENING NORMALIZATION ARCHITECTURE              │
│                                                                                  │
│   Private Quarantined Sources (private/raw/ & private/source_data/):             │
│   • Test Booklet (PDF) ──────► OCR Extraction ──────► Questions 1..40            │
│                                                 └──► Answer Key (Page 22)        │
│                                                                                  │
│   • Transcript (DOCX)  ──────► Paragraph Parser ────► Transcript Segments        │
│                                                 └──► Speaker Turns               │
│                                                                                  │
│   • Audio Tracks (MP3) ──────► Container / ID3 ─────► Audio Assets               │
│                                                                                  │
│                                      │                                           │
│                                      ▼                                           │
│   Conservative Alignment Engine:                                                 │
│   • Verified Point Timestamps (start_ms verified, end_ms preserved as null)      │
│   • Derived Bounds Flagged as Inferred (AUDIO_TIMING_INFERRED, never verified)   │
│   • Chronological Order Audit                                                    │
│   • Anomaly Detection: impossible_bounds, missing_audio, unaligned               │
│                                                                                  │
│                                      │                                           │
│                                      ▼                                           │
│   Evidence & Answer Reconciliation:                                              │
│   • Authoritative Source Key Linking (SRC-011 Page 22)                           │
│   • Transcript Provenance Recording (SRC-012 FILE-0d311581c359)                  │
│   • Verbatim Transcript Evidence Matching (No substring or letter matching)      │
│   • Unresolved Grounding Handling (EVIDENCE_UNRESOLVED)                          │
│                                                                                  │
│                                      │                                           │
│                                      ▼                                           │
│   Dependency-Aware SQLite Checkpoint Gateway:                                    │
│   • Independent Entity Dependency Hashing (Doc, Transcript, Audio, Config)       │
│   • Granular Invalidation & Idempotent Resumption                                │
│   • Strict Copyright Quarantine (0 copyrighted strings in public repo)           │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Pilot Selection & Provenance Verification

Following forensic review of confirmed multi-source relationships established in Phase V0.3-A and audited in Phase V0.3-B, **VOL 1 TEST 1** was selected as the pilot listening test paper.

### 2.1 Confirmed Source Inventory
- **Question Paper & Official Key:** `SRC-011` (`FILE-8e5b05150afe`)
  - Relative Path: `private/raw/VOL 1/TEST 1/Test_1.pdf`
  - Size: 10,848,193 bytes | SHA-256: `d20a5d7fdb7772b19141f2536d7b32f9e6e49f84e874bf47fe65e6044690fc00`
  - Content: 23 pages scanned PDF containing Listening Sections 1–4 (Pages 1–6) and official Listening Answer Key (Page 22).
- **Transcript Document:** `SRC-012` (`FILE-0d311581c359`)
  - Relative Path: `private/raw/VOL 1/TEST 1/Transcript Test 1.docx`
  - Size: 17,124 bytes | SHA-256: `1aafb748295d397b49a691352f42a62c2b1eb85ebd643a20fd5ec131fae9c30e`
  - Content: 67 paragraphs covering Sections 1–4 with explicit speaker labels (`Speaker 1`..`Speaker 4`) and source timestamps.
- **Audio Assets:**
  - Section 1: `SRC-008` (`FILE-ace1affa2d9b`) — `private/raw/VOL 1/TEST 1/AUDIO LIS/AudioTrack 01.mp3` (464.4s, Stereo, 128 kbps, 44.1 kHz).
  - Section 2: `SRC-009` (`FILE-740b30018dd9`) — `private/raw/VOL 1/TEST 1/AUDIO LIS/AudioTrack 02.mp3` (396.1s, Stereo, 128 kbps, 44.1 kHz).
  - Section 3: `SRC-010` (`FILE-657be2e8cf8d`) — `private/raw/VOL 1/TEST 1/AUDIO LIS/AudioTrack 03.mp3` (402.6s, Stereo, 128 kbps, 44.1 kHz).
  - Section 4: Missing audio track in source folder. Preserved with `audio_verification_status = "missing"`.

### 2.2 Confirmed Source Relationships (Registry Audit)
The following pre-existing confirmed relationships in SQLite (`harness.db`) were verified prior to normalization:
1. `REL-60baca75b5f63f07` (`SRC-011` $\to$ `SRC-008`, `listening_to_audio`, confirmed)
2. `REL-19c4d499067d2003` (`SRC-012` $\to$ `SRC-008`, `listening_to_audio`, confirmed)
3. `REL-b20d21aeb518edf1` (`SRC-008` $\to$ `SRC-012`, `listening_to_transcript`, confirmed)
4. `REL-a1810ceb7d364d13` (`SRC-011` $\to$ `SRC-012`, `listening_to_transcript`, Section 1, confirmed)
5. `REL-1bd3c481493474a7` (`SRC-011` $\to$ `SRC-012`, `listening_to_transcript`, Section 2, confirmed)
6. `REL-38e04f7d60433c71` (`SRC-011` $\to$ `SRC-012`, `listening_to_transcript`, Section 3, confirmed)

---

## 3. Normalized Listening Domain Models

Schema definitions in `harness/models/listening.py` conform to `SCHEMA_VERSION_LISTENING = "v0.3.0-listening"` and accommodate the remediated integrity distinctions:

### 3.1 Model Hierarchy & Integrity Fields
- **`ListeningTest`**: Root aggregate entity representing the complete listening test paper.
- **`ListeningSection`**: Section unit (1–4) linking question ranges, audio asset references, transcript status, and constituent speaker turns.
- **`AudioAsset`**: Physical audio file representation with duration, bitrate, sample rate, container codec, and forensic status (`verified`, `missing`, `corrupt`).
- **`TranscriptSegment`**: Atomic transcript utterance with sequence index, speaker label, verbatim text, `start_ms`, `end_ms`, `timing_source` (expanded with `"derived_bound"`), and `timing_verification_status` (expanded with `"inferred"`).
- **`SpeakerTurn`**: Conversational turn clustering continuous segments attributed to a single speaker.
- **`ListeningQuestion`**: Individual test item (1–40) with question type, prompt text, options, blank target, word limit rule, and raw OCR block locators.
- **`ListeningAnswer`**: Authoritative ground truth key linked to a question with `source_key_ref` (e.g. `SRC-011:Test_1.pdf#page=22:key_1`).
- **`ListeningEvidence`**: Grounding proof associating an answer with verbatim transcript sentences and optional audio intervals; supports `grounding_status = "unresolved"` and `timing_status = "inferred"`.

---

## 4. Transcript Normalization & Segmentation

The `TranscriptNormalizer` (`harness/normalizers/transcript.py`) extracts raw docx paragraphs and performs non-destructive parsing:
- **Speaker Identification:** Recognizes speaker labels (`Speaker 1`..`Speaker 4` or named speakers) via regular expression parsing without altering trailing dialogue.
- **Timestamp Extraction:** Identifies `[HH:MM:SS]` annotations, converting values into millisecond offsets.
- **Section Demarcation:** Detects announcement delimiters (`That is the end of Section one`) and divider rules, properly isolating the 4 IELTS test sections.
- **Speaker Turn Clustering:** Groups contiguous utterances from the same speaker into coherent `SpeakerTurn` records, capturing aggregate turn text and constituent segment identifiers.

---

## 5. Audio Inspection & Alignment Logic (Remediated)

The `AudioAligner` (`harness/normalizers/audio_aligner.py`) inspects audio recordings and evaluates timing boundaries against physical audio duration without fabricating endpoints:

### 5.1 Remediation of Timing Defects
1. **Zero Fabricated Endpoints:** The previous implementation fabricated artificial 30-second endpoints (`min(start + 30000, duration_ms)`) or projected endpoints from subsequent segment starts. These have been completely eliminated. When `end_ms` is unavailable in the raw source transcript, it remains `None` (`null`).
2. **Distinction Between Timestamps and Intervals:**
   - A segment with a verified `start_ms` and `end_ms is None` is marked with `timing_verification_status = "verified"` and flagged `AUDIO_TIMESTAMP_VERIFIED`. It is **never** claimed as `AUDIO_INTERVAL_VERIFIED`.
   - `verified_intervals_count` strictly requires both valid start and end bounds from the source.
3. **Derived Bounds Inferred Only:** When bounds are derived (e.g. `timing_source == "derived_bound"`), they are assigned `timing_verification_status = "inferred"` and flagged `AUDIO_TIMING_INFERRED`. They are never marked verified.
4. **Impossible Bounds Retention:** When timestamps exceed track duration (e.g. Sections 2 & 3 containing cumulative CD timestamps), they are strictly preserved with `timing_verification_status = "impossible_bounds"` and flagged `AUDIO_TIMING_EXCEEDS_DURATION`.

### 5.2 Real Pilot Alignment Findings
- **Section 1 (`AudioTrack 01.mp3`, 464,400 ms):**
  - All 33 segments possess valid source point timestamps from 1,000 ms (`[00:00:01]`) to 419,000 ms (`[00:06:59]`).
  - Verified Timestamps: **33 / 33 (100%)**.
  - Verified Audio Intervals: **0 / 33 (0%)** (zero endpoints fabricated).
- **Section 2 (`AudioTrack 02.mp3`, 396,070 ms):**
  - Source timestamps reflect continuous CD timing (511,000 ms to 815,000 ms).
  - All 4 segments exceed track duration and are flagged as **`impossible_bounds` (4 segments)**.
- **Section 3 (`AudioTrack 03.mp3`, 402,610 ms):**
  - 22 segments reflect continuous CD timing (925,000 ms to 1,209,000 ms) and are flagged as **`impossible_bounds` (22 segments)**.
  - 2 segments lack timestamps and are flagged as **`unaligned` (2 segments)**.
- **Section 4:**
  - Audio track missing from source directory.
  - Preserved as **`timing_verification_status = "missing"` (2 segments)**.

---

## 6. Question, Answer, and Evidence Normalization (Remediated)

### 6.1 Source Data Isolation & Privacy Architecture
In compliance with copyright and privacy rules:
- **Removal of Hardcoded Public Data:** The previous commit (`892d8aa`) hardcoded all 40 authentic questions, answer keys, and quotes into `harness/normalizers/listening_question.py`. This has been completely removed.
- **Quarantined Extraction Artifact:** Authentic source-extracted data is quarantined under `private/source_data/listening/vol01_test01_extraction.json` (gitignored).
- **Public Synthetic Test Fixtures:** Public unit tests execute against `tests/fixtures/synthetic_listening/synthetic_listening_fixtures.json`, containing synthetic question prompts, options, answers, and locators.
- **Uncertain OCR Preservation:** Raw OCR entries from `SRC-011` are preserved without silent human modification:
  - Q1: `raw_block_locator: "Page 2, Box 2 - Table Column 2 ('g events')"`
  - Q7: `raw_block_locator: "Page 2, Box 2 - Table Row 7 ('©')"`
  - Q10: `raw_block_locator: "Page 2, Box 2 - Table Row 10 ('- city')"`

### 6.2 Evidence Linkage Remediation
- **Removal of Fragile Substring Matching:** Removed naive matching `item["target_val"].lower() in seg.transcript_text.lower()`.
- **Elimination of MCQ Letter Matching:** Multiple-choice letters ("A", "B", "C") are never used as substring search queries.
- **Verbatim Quote Grounding:** Every question is grounded against audited verbatim quotes matching actual paragraphs in `SRC-012` (`Transcript Test 1.docx`).
- **Transcript Provenance Citation:** The evidence record explicitly cites `source_file_id = "FILE-0d311581c359"` (`SRC-012`), ensuring clear separation from question booklet citations.
- **Unresolved Evidence Handling:** When evidence is missing or uncertain, `grounding_status` is set to `"unresolved"` with `EVIDENCE_UNRESOLVED` and `verbatim_quote = None`.

---

## 7. Dependency-Aware Checkpoint Architecture (Remediated)

The checkpoint engine in `harness/normalizers/listening_orchestrator.py` was remediated to track dependencies independently via `compute_listening_entity_dependency_hash`:

$$\text{hash} = \text{SHA256}(\text{dep}_1 + \text{dep}_2 + \dots + \text{normalizer\_version} + \text{config\_hash} + \text{schema\_version})$$

### 7.1 Entity-Specific Dependencies
- **`ListeningTest` & `ListeningSection`:** Depends on question document (`SRC-011`), transcript document (`SRC-012`), and audio asset.
- **`AudioAsset`:** Depends strictly on physical audio asset SHA-256 (`audio_sha256`).
- **`TranscriptSegment` & `SpeakerTurn`:** Depends strictly on transcript document SHA-256 (`SRC-012`).
- **`ListeningQuestion` & `ListeningAnswer`:** Depends strictly on question document SHA-256 (`SRC-011`).
- **`ListeningEvidence`:** Depends on question document, transcript document, and audio asset.

### 7.2 Six Dependency Scenarios Tested
1. **Initial Normalization:** Writes all 250 entities into `normalization_checkpoints`.
2. **Identical Rerun:** Validates 100% checkpoint hit (0 written, 250 skipped).
3. **Transcript-Only Change:** Invalidates sections, segments, turns, and evidence; questions, answers, and audio assets remain valid and skipped.
4. **Audio-Only Change:** Invalidates sections, audio assets, and evidence; questions, answers, segments, and turns remain valid and skipped.
5. **Answer-Key / Question-Doc Change:** Invalidates questions, answers, sections, and evidence; audio assets, segments, and turns remain valid and skipped.
6. **Interrupted Processing & Resume:** Safely picks up uncommitted entities without duplicating existing records.

---

## 8. Acceptance Gates Verification (L1–L11)

| Gate | Description | Status | Verification Evidence |
|:---|:---|:---:|:---|
| **L1** | Audio source identity verified | **PASS** | `SRC-008`, `SRC-009`, `SRC-010` SHA-256 validated against database inventory. |
| **L2** | Transcript provenance retained | **PASS** | `SRC-012` (`Transcript Test 1.docx`) paragraph locators and content hash tracked. |
| **L3** | Question order and section structure correct | **PASS** | Exactly 40 questions partitioned across 4 sections (Q1–10, Q11–20, Q21–30, Q31–40). |
| **L4** | No fabricated transcript or timestamps | **PASS** | Source timestamps strictly preserved; unavailable `end_ms` kept `null`; 0 fabricated 30s endpoints; Section 4 audio marked missing; Section 2–3 impossible bounds flagged. |
| **L5** | All accepted answers have valid provenance | **PASS** | 100% of answers linked to `SRC-011` Page 22 official key sheet; raw OCR entries preserved without silent corrections. |
| **L6** | Evidence is linked to the correct question | **PASS** | 40 evidence items linked to verbatim transcript quotes from `SRC-012`; no substring/letter matching; transcript source recorded. |
| **L7** | Stale relationships cannot remain confirmed | **PASS** | Independent entity dependency hashing ensures modified sources invalidate affected checkpoints. |
| **L8** | Missing data is explicitly marked | **PASS** | Section 4 audio, Section 2/3 cumulative bounds, and missing explanations logged in `unresolved_items.json`. |
| **L9** | Resume and repeated runs are deterministic | **PASS** | Checkpoint resume verified: 250 skipped on re-run; canonical hashes bit-for-bit identical. |
| **L10** | Private source material remains isolated | **PASS** | Normalized outputs and extraction artifacts stored under `private/` exclusively; zero copyrighted items in public Python code. |
| **L11** | Existing V0.1–V0.3-B tests still pass | **PASS** | 212 tests pass (203 standard + 9 corpus); full test suite backwards compatible. |

---

## 9. Regression Test Suite

Twenty fully synthetic regression tests are implemented in `tests/test_v03c_listening_alignment.py`:
1. `test_transcript_segmentation`: Validates section boundary detection and sequence ordering.
2. `test_speaker_turn_preservation`: Validates clustering of continuous utterances and speaker identity preservation.
3. `test_valid_timestamps`: Validates intervals satisfying $0 \le \text{start} < \text{end} \le \text{duration}$.
4. `test_no_fabricated_30s_endpoint`: Negative regression verifying that unavailable `end_ms` remains `None` without 30s fabrication.
5. `test_derived_bounds_distinction`: Negative regression verifying that derived bounds are flagged `inferred`, never `verified`.
6. `test_impossible_timestamps`: Validates detection of intervals exceeding audio duration.
7. `test_out_of_order_intervals`: Validates detection of non-chronological timestamps.
8. `test_missing_timestamp_handling`: Validates that unaligned dialogue preserves order without fabrication.
9. `test_question_to_section_mapping`: Validates question allocation across 4 sections.
10. `test_answer_provenance`: Validates authoritative source key metadata and unverified answer flagging.
11. `test_cross_test_mismatch`: Validates rejection of cross-test associations.
12. `test_no_substring_matching_on_target_val`: Negative regression verifying rejection of substring matching on answers.
13. `test_no_mcq_letter_matching`: Negative regression verifying that MCQ letters A/B/C are never matched as evidence text.
14. `test_wrong_section_evidence_rejection`: Negative regression verifying rejection of evidence from mismatched sections.
15. `test_evidence_provenance_transcript_source`: Validates evidence records transcript source (`SRC-012`) provenance.
16. `test_no_copyrighted_data_in_public_code`: Validates that public Python modules contain zero copyrighted IELTS test items.
17. `test_ocr_preservation_uncertain_results`: Validates non-destructive preservation of uncertain OCR locators.
18. `test_privacy_isolation`: Validates rejection of unauthorized writes outside `private/`.
19. `test_missing_audio_asset_handling`: Validates proper tagging of missing audio files.
20. `test_dependency_aware_checkpoints`: Validates all 6 independent dependency invalidation scenarios.

---

## 10. Documented Unresolved Limitations

As logged in `private/reports/v03c/unresolved_items.json`:
1. **Missing Section 4 Audio Track:** `private/raw/VOL 1/TEST 1/AUDIO LIS/` contains tracks 1–3 only. Section 4 remains unaligned until the original recording is located.
2. **Cumulative vs. Track Timing Divergence:** In Sections 2 and 3, timestamps in `Transcript Test 1.docx` reflect master test timeline rather than track zero offsets (26 segments flagged as `impossible_bounds`). These require a continuous master audio join or verified track offsets before promoting to `verified`.
3. **Absence of Pedagogical Explanations:** The raw volume release contains answer keys on Page 22 but no explanation commentary. Pedagogical rationales remain null to avoid AI hallucination.

---

## 11. Historical Exposure Disclosure

In commit `892d8aa` on branch `feat/harness-v0.3c`, raw extraction data containing copyrighted questions, answer keys, and transcript excerpts was temporarily introduced into `harness/normalizers/listening_question.py`.

In compliance with repository policy:
- **No Git History Rewriting:** Git history is preserved as-is without rewriting history on public/shared branches without explicit user authorization.
- **Source Code Remediation:** The hardcoded definitions were completely excised in the remediation commit.
- **Quarantine Enforcement:** Authentic data is quarantined strictly within `private/source_data/listening/`, which is verified to be ignored by Git.
- **Automated Prevention:** Regression test `test_no_copyrighted_data_in_public_code` guarantees that any future accidental re-introduction of copyrighted text in public source files will fail CI.
