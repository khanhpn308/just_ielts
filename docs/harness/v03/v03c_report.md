# IELTS Data Harness V0.3 — Phase V0.3-C Engineering Report
**Phase:** V0.3-C Listening Transcript & Audio Alignment Pilot  
**Role:** Senior Python Engineer, Data Quality Engineer, and IELTS Listening Assessment Specialist  
**Repository:** `~/projects/just_ielts`  
**Base Branch:** `main`  
**Working Branch:** `feat/harness-v0.3c`  
**Date:** 2026-11-21  

---

## 1. Executive Summary & Mission

Phase V0.3-C extends the IELTS Data Harness to pilot the end-to-end normalization of authentic IELTS Listening examinations, establishing unbroken evidentiary linkages across the complete assessment lifecycle:

$$\text{Audio} \longrightarrow \text{Transcript} \longrightarrow \text{Sections} \longrightarrow \text{Questions} \longrightarrow \text{Answers} \longrightarrow \text{Evidence} \longrightarrow \text{Explanations}$$

Heterogeneous listening corpora introduce specific data challenges: audio track boundaries often diverge from CD master timelines, transcripts may contain missing or cumulative timestamps, question booklets combine multiple test skills, and official explanation guides may be absent in raw exam releases.

Phase V0.3-C enforces strict epistemic conservativism:
1. **Zero Fabrication:** Timestamps, transcript utterances, audio alignment, or pedagogical explanations are never invented or estimated.
2. **Conservative Alignment:** Audio intervals are marked `verified` only when strict boundary invariants ($0 \le \text{start\_ms} < \text{end\_ms} \le \text{duration}$) and chronological ordering hold.
3. **Explicit Uncertainty:** Any missing asset, out-of-bounds timestamp, or ungrounded evidence is explicitly surfaced as `missing`, `impossible_bounds`, or `unaligned`.
4. **Isolated Grounding:** All private source content remains quarantined within `private/` storage.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   V0.3-C LISTENING NORMALIZATION ARCHITECTURE                    │
│                                                                                  │
│   Raw Sources:                                                                   │
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
│   • Interval Verification (0 <= start_ms < end_ms <= duration_ms)                │
│   • Order Contiguity Audit                                                       │
│   • Anomaly Detection: impossible_bounds, out_of_order, missing                  │
│                                                                                  │
│                                      │                                           │
│                                      ▼                                           │
│   Evidence & Answer Reconciliation:                                              │
│   • Authoritative Source Key Linking (SRC-011 Page 22)                           │
│   • Verbatim Transcript Evidence Grounding                                       │
│   • Audio Interval Grounding (when verified)                                     │
│   • Missing Explanations Quarantine                                              │
│                                                                                  │
│                                      │                                           │
│                                      ▼                                           │
│   SQLite Checkpoint & Privacy Gateway:                                           │
│   • Deterministic Canonical Content Hashing                                      │
│   • Idempotent Resumption (normalization_checkpoints)                            │
│   • Private Copyright Quarantine Enforcement                                     │
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

Schema definitions were added to `harness/models/listening.py` conforming to `SCHEMA_VERSION_LISTENING = "v0.3.0-listening"`:

### 3.1 Model Hierarchy
- **`ListeningTest`**: Root entity representing the complete listening test paper. Contains sections, audio assets, questions, answers, and evidence linkages.
- **`ListeningSection`**: Section unit (1–4) linking question ranges, audio asset references, transcript status, and constituent speaker turns.
- **`AudioAsset`**: Physical audio file representation with duration, bitrate, sample rate, container codec, and forensic status (`verified`, `missing`, `corrupt`).
- **`TranscriptSegment`**: Atomic transcript utterance with sequence index, speaker label, verbatim text, `start_ms`, `end_ms`, `timing_source`, and `timing_verification_status`.
- **`SpeakerTurn`**: Conversational turn clustering continuous segments attributed to a single speaker.
- **`ListeningQuestion`**: Individual test item (1–40) with question type, prompt text, options, blank target, and word limit rule.
- **`ListeningAnswer`**: Authoritative ground truth key linked to a question with `source_key_ref` (e.g. `SRC-011:Test_1.pdf#page=22:key_1`).
- **`ListeningEvidence`**: Grounding proof associating an answer with verbatim transcript sentences and optional audio intervals.

---

## 4. Transcript Normalization & Segmentation

The `TranscriptNormalizer` (`harness/normalizers/transcript.py`) extracts raw docx paragraphs and performs non-destructive parsing:
- **Speaker Identification:** Recognizes speaker labels (`Speaker 1`..`Speaker 4` or named speakers) via regular expression parsing without altering trailing dialogue.
- **Timestamp Extraction:** Identifies `[HH:MM:SS]` annotations, converting values into millisecond offsets.
- **Section Demarcation:** Detects announcement delimiters (`That is the end of Section one`) and divider rules, properly isolating the 4 IELTS test sections.
- **Speaker Turn Clustering:** Groups contiguous utterances from the same speaker into coherent `SpeakerTurn` records, capturing aggregate turn text and constituent segment identifiers.

---

## 5. Audio Inspection & Alignment Logic

The `AudioAligner` (`harness/normalizers/audio_aligner.py`) inspects audio recordings and evaluates timing boundaries against physical audio duration:

### 5.1 Verification Invariants
1. $0 \le \text{start\_ms} < \text{end\_ms} \le \text{duration\_ms}$
2. Strictly increasing chronological ordering within each section: $\text{start\_ms}_i \ge \text{start\_ms}_{i-1}$
3. Missing audio assets categorically trigger `timing_verification_status = "missing"`.
4. Segments lacking timestamps preserve order with `timing_verification_status = "unaligned"`.

### 5.2 Real Pilot Alignment Findings
- **Section 1 (`AudioTrack 01.mp3`, 464,400 ms):**
  - All 33 segments possess source timestamps starting at 1,000 ms (`[00:00:01]`) through 419,000 ms (`[00:06:59]`).
  - Interval bounds and ordering are verified: **33 / 33 segments verified (100%)**.
- **Section 2 (`AudioTrack 02.mp3`, 396,070 ms):**
  - Source timestamps in `Transcript Test 1.docx` reflect continuous CD master timing: 511,000 ms (`[00:08:31]`) through 815,000 ms (`[00:13:35]`).
  - Evaluated against individual track duration (396,070 ms), values exceed track boundaries.
  - Correctly flagged as **`impossible_bounds` (4 segments)** without fabricating speculative offsets.
- **Section 3 (`AudioTrack 03.mp3`, 402,610 ms):**
  - Utterances contain cumulative master timestamps (15m25s..20m09s) as well as unaligned dialogue lines without timestamps.
  - Correctly flagged as **`impossible_bounds` and `unaligned`** without fabricating alignment.
- **Section 4:**
  - Audio track missing from source directory.
  - Preserved as **`timing_verification_status = "missing"`**.

---

## 6. Question, Answer, and Evidence Normalization

The `ListeningQuestionNormalizer` (`harness/normalizers/listening_question.py`) constructs all 40 test items:
- **Questions 1–10 (Section 1):** Table completion and note completion ("ONE WORD AND/OR A NUMBER").
- **Questions 11–20 (Section 2):** Multiple-choice single, note completion ("NO MORE THAN THREE WORDS"), and multiple-choice multi ("Choose THREE letters A-G").
- **Questions 21–30 (Section 3):** Multiple-choice single and feature matching (comparing student marker categories to A, B, C).
- **Questions 31–40 (Section 4):** Note completion on Bislama linguistics ("ONE WORD ONLY").

### 6.1 Answer Key Provenance
All 40 answer keys were parsed directly from Page 22 of `SRC-011` (`Test_1.pdf`) and linked with `answer_provenance_status = "authoritative_source"` and explicit citations:
$$\text{source\_key\_ref} = \text{"SRC-011:Test\_1.pdf\#page=22:key\_"} + N$$

### 6.2 Evidence Grounding
All 40 answers are grounded in verbatim transcript sentences from `SRC-012`. Section 1 items link verified audio intervals in `AudioTrack 01.mp3`. Missing pedagogical explanation guides in the raw corpus are explicitly quarantined with `explanation_verification = "missing_explanation"`.

---

## 7. Checkpoint & Determinism Architecture

The `ListeningNormalizationOrchestrator` (`harness/normalizers/listening_orchestrator.py`) interfaces with SQLite:
- **Normalization Checkpoints:** Every entity (test, section, audio asset, segment, turn, question, answer, evidence) is recorded in `normalization_checkpoints`.
- **Deterministic Hashing:** Canonical content hashes exclude run timestamps (`normalized_at`), ensuring bit-for-bit identical hashes across repeated executions.
- **Idempotency Proof:**
  - Run 1 (`force=True`): 250 entities written, 0 skipped.
  - Run 2 (`force=False`): 0 entities written, 250 entities skipped (100% valid resume).

---

## 8. Acceptance Gates Verification (L1–L11)

| Gate | Description | Status | Verification Evidence |
|:---|:---|:---:|:---|
| **L1** | Audio source identity verified | **PASS** | `SRC-008`, `SRC-009`, `SRC-010` SHA-256 digests validated against database inventory. |
| **L2** | Transcript provenance retained | **PASS** | `SRC-012` (`Transcript Test 1.docx`) paragraph locators and content hash tracked. |
| **L3** | Question order and section structure correct | **PASS** | Exactly 40 questions partitioned across 4 sections (Q1–10, Q11–20, Q21–30, Q31–40). |
| **L4** | No fabricated transcript or timestamps | **PASS** | Source timestamps preserved verbatim; Section 4 audio marked missing; Section 2–3 impossible bounds flagged. |
| **L5** | All accepted answers have valid provenance | **PASS** | 100% of answers linked to `SRC-011` Page 22 official key sheet. |
| **L6** | Evidence is linked to the correct question | **PASS** | 40 evidence items linked to verbatim transcript quotes and questions. |
| **L7** | Stale relationships cannot remain confirmed | **PASS** | Source hash validation ensures modified sources invalidate checkpoints. |
| **L8** | Missing data is explicitly marked | **PASS** | Section 4 audio, Section 2/3 cumulative bounds, and missing explanations logged in `unresolved_items.json`. |
| **L9** | Resume and repeated runs are deterministic | **PASS** | Checkpoint resume verified: 250 skipped on re-run; canonical hashes identical. |
| **L10** | Private source material remains isolated | **PASS** | Normalized outputs and reports stored under `private/` exclusively. |
| **L11** | Existing V0.1–V0.3-B tests still pass | **PASS** | 196 unit tests passed; full test suite backwards compatible. |

---

## 9. Regression Test Suite

Thirteen fully synthetic regression tests were implemented in `tests/test_v03c_listening_alignment.py` requiring zero private files:
1. `test_transcript_segmentation`: Validates section boundary detection and sequence ordering.
2. `test_speaker_turn_preservation`: Validates clustering of continuous utterances and preservation of speaker identities.
3. `test_valid_timestamps`: Validates intervals satisfying $0 \le \text{start} < \text{end} \le \text{duration}$.
4. `test_impossible_timestamps`: Validates detection of intervals exceeding audio duration.
5. `test_out_of_order_intervals`: Validates detection of non-chronological timestamps.
6. `test_missing_timestamp_handling`: Validates that unaligned text is preserved without timestamp fabrication.
7. `test_question_to_section_mapping`: Validates question allocation across sections.
8. `test_answer_provenance`: Validates authoritative source key metadata and question linking.
9. `test_cross_test_mismatch`: Validates rejection of cross-test question/answer associations.
10. `test_stale_source_detection`: Validates checkpoint invalidation when source hashes change.
11. `test_checkpoint_resume`: Validates idempotent skipping of already-normalized entities.
12. `test_privacy_isolation`: Validates rejection of unauthorized writes outside `private/`.
13. `test_missing_audio_asset_handling`: Validates proper tagging of missing audio files.

---

## 10. Documented Unresolved Limitations

As logged in `private/reports/v03c/unresolved_items.json`:
1. **Missing Section 4 Audio Track:** `private/raw/VOL 1/TEST 1/AUDIO LIS/` contains tracks 1–3 only. Section 4 remains unaligned until the original recording is located.
2. **Cumulative vs. Track Timing Divergence:** In Sections 2 and 3, timestamps in `Transcript Test 1.docx` reflect master test timeline rather than track zero offsets. These require either a continuous master audio join or verified track offsets before promoting to `verified`.
3. **Absence of Pedagogical Explanations:** The raw volume release contains answer keys on Page 22 but no explanation commentary. Pedagogical rationales remain null to avoid AI hallucination.
