# Start Learning — Operational IELTS System Guide (S06)

> [!IMPORTANT]
> **Provisional Reading Scope & S05 Governance Limits:**
> - **Accepted Reading Verdict:** `PASS_FOR_PRIVATE_PROVISIONAL_USE` (`S03D-20261128-r01` / `S04_pilot`)
> - **Authority Status:** `INDEPENDENT_BATCH_REVIEW_SKIPPED` (`approved_locks = 0`, `official_s04_scope = 0`)
> - **Disabled Capabilities:** `automatic_grading = false`, `diagnostic_grading = false`, `official_answer_authority = false`, `publication_authorized = false`
> - **Preserved Governance Flags:** `PUBLICATION_AUTHORIZATION_NOT_ESTABLISHED`, `CHATGPT_PROJECT_E2E_NOT_EXECUTED`, `RUNTIME_CONTAINMENT_NOT_ENFORCED`
> - Do **not** treat unverified self-check keys (`Khóa tham khảo chưa xác minh`) as official answers or estimate band scores from provisional practice.

All commands below assume the repository root (`/home/khanh/projects/just_ielts`) and the repository-local Python virtual environment (`./.venv/bin/python`).

---

## 1. Environment & Integrity Pre-Check

```bash
./.venv/bin/python -m harness.cli check-env
./.venv/bin/python scripts/build_principles_index.py --check
./.venv/bin/python scripts/validate_data.py
```

---

## 2. Provisional Reading Tutor (`S04_pilot`)

**Usable provisional coverage:** 101 available passages (`82` `PRACTICE_CANDIDATE`, `18` `RESTRICTED_PRACTICE_CANDIDATE`, `1` `READING_ONLY`: `PASSAGE-VOL03-03-RD01`) across 38 tests, 257 groups, and 1,230 items (`1,238` practice slots: `598` unverified self-check slots + `640` grading-disabled practice slots). `10` `HELD` passages, `47` excluded groups, `229` withheld slots, and `438` quarantined orphan keys are strictly blocked.

```bash
pilot="private/staging/reading_reconstruction/S04_pilot"

# 1. Inspect available provisional Reading tests and passages
ls "$pilot/corpus/practice/indexes/"
head -n 30 "$pilot/corpus/practice/indexes/reading_test_index.json"

# 2. Display a provisional Reading passage and its questions (answers hidden)
PYTHONPATH=. ./.venv/bin/python -B "$pilot/scratch-export/tutor.py" show PASSAGE-VOL03-05-RD02

# 3. Display a specific question group (e.g., diagram + numbered context)
PYTHONPATH=. ./.venv/bin/python -B "$pilot/scratch-export/tutor.py" show PASSAGE-VOL07-12-RD02 --group-id QG-VOL07-12-RD02-G01

# 4. Display a restricted passage (withheld question numbers are listed and omitted)
PYTHONPATH=. ./.venv/bin/python -B "$pilot/scratch-export/tutor.py" show PASSAGE-VOL06-06-RD03

# 5. Display a reading-only passage
PYTHONPATH=. ./.venv/bin/python -B "$pilot/scratch-export/tutor.py" show PASSAGE-VOL03-03-RD01

# 6. Submit answers for unverified self-check / key-status feedback
#    (Multi-select items must be submitted together at the first printed question number)
PYTHONPATH=. ./.venv/bin/python -B "$pilot/scratch-export/tutor.py" submit PASSAGE-VOL03-05-RD02 '{"20":["A","D"]}'

# 7. Direct Harness question retrieval from the practice-only corpus (no keys/evidence/explanations)
./.venv/bin/python -m harness.cli retrieve --normalized-dir "$pilot/corpus/practice" --format json --question-id Q-VOL06-06-RD-027
```

**Important Notes for Provisional Reading:**
- Always pass `--normalized-dir private/staging/reading_reconstruction/S04_pilot/corpus/practice` (or use `$pilot/scratch-export/tutor.py`) for the accepted S04 provisional Reading corpus.
- Do **not** use production `harness.cli normalize` regeneration on Reading sources until defect `R4-N06` is fixed in `harness/normalizers/reading_pdf.py` and `reading_docx.py`.

---

## 3. Existing Non-Reading Workflows

### 3.1 Vocabulary Knowledge Base (8 Textbooks, 444 Units, 20 Topics)

```bash
# Inspect textbook inventory and available unit count
./.venv/bin/python -m harness.cli vocab inventory

# Query vocabulary, collocations, and paraphrases by topic
./.venv/bin/python -m harness.cli vocab query --topic education_and_learning --limit 10

# Query a specific textbook unit (e.g., IVU-60-U001, IVU-65-U005, EVU-B2-U014, AVU-U037)
./.venv/bin/python -m harness.cli vocab query --unit IVU-60-U001
```

- **Tutor natural-language triggers:** `"Học từ vựng"`, `"Học 10 từ mới"`, `"Học IVU-60 Unit 1"`, `"Học EVU-B2 Unit 14"`, `"Học collocation"`, `"Học paraphrase"`, `"Học theo chủ đề Education"`, `"Ôn từ vựng hôm nay"`, `"Xem tiến độ"`.
- **Progress storage (consent required):** `private/progress/vocabulary.jsonl` and `private/progress/curriculum.json`.

### 3.2 Listening Practice

- **Indexes:** `private/staging/normalized/indexes/listening_index.json`, `listening_tests.jsonl` (`76` tests), `listening_sections.jsonl` (`304` sections), `listening_questions.jsonl` (`1,560` questions), `listening_answer_keys.jsonl` (`1,200` keys).
- **Audio status disclosure (A09 audit limitation):** Only `VOL09-06` (`TEST-IELTS-VOL09-06-LIS.json`) and `VOL09-07` (`TEST-IELTS-VOL09-07-LIS.json`) have complete 4-section audio files on disk under `private/raw/`. Other tests have partial or missing audio tracks; check `audio_status` in `listening_sections.jsonl` before starting a full timed test.

```bash
# Inspect a complete Listening test entity and its section/audio metadata
./.venv/bin/python -c '
import json
t = json.loads(open("private/staging/normalized/listening_test/TEST-IELTS-VOL09-06-LIS.json").read())
print(t["test_id"], t["title"], len(t.get("section_ids", [])), "sections")
'
```

### 3.3 Writing & Speaking Practice

- **Writing index:** `private/staging/normalized/indexes/ngocbach_writing_index.json` (`99` tasks/items).
- **Speaking index:** `private/staging/normalized/indexes/ngocbach_speaking_index.json` (`188` tasks/items).
- **Tutor natural-language triggers:**
  - Writing: `"Làm bài Writing Task 1"`, `"Viết bài Writing Task 2"`
  - Speaking: `"Luyện Speaking Part 2"`, `"Luyện Speaking 4/3/2"`, `"Đánh giá Speaking tháng này"`
  - Fluency routine: `"Xem lịch học IELTS"`, `"Học IELTS theo lịch"`
  - Resume: `"Tiếp tục bài hôm qua"`

### 3.4 Principles & Progress Recording

- **Principles lookup:** `principles/INDEX.md` (`22` atomic principles + `principles/general/8_golden_principles`).
- **Progress templates:** `progress/templates/session.md`, `progress/templates/error.md`, `progress/templates/weekly-review.md`.
- **Personal progress directory (gitignored):** `private/progress/` (only written after explicit learner consent).
