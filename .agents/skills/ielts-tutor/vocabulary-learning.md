# Vocabulary Learning — IELTS Tutor

This is a selective reference for the existing IELTS Tutor Skill, not a separate agent or Harness phase. Read it when the user requests vocabulary, collocation, paraphrase, word-use practice or vocabulary review. Follow `AGENTS.md` and the general principles in `principles/general/8_golden_principles` (especially Contextual Vocabulary Learning, Systematic Error Analysis, Knowledge Transfer, and Consistency and Spaced Repetition).

## 1. Select useful vocabulary

- Prefer words/expressions from the current or most recently identified Reading/Listening task, observed vocabulary gaps, and useful Writing/Speaking collocations. Do not diagnose a vocabulary gap merely because a test answer was wrong; ask or test when uncertain.
- Next use accessible authorized vocabulary/collocation records, the 8-textbook Vocabulary Knowledge Base at `private/knowledge/vocabulary/` (see `vocabulary-curriculum.md`), and available English Collocations in Use resources if actually present. Use the unit index (`unit_index.json`), topic index (`topic_index.json`), and vocabulary bank (`vocabulary.jsonl`); do not scan the entire corpus or add a new extraction phase. If no suitable source exists, teach common academic vocabulary with clearly labeled tutor-created examples.
- Prioritize high-utility words, useful senses, natural combinations and contrastive paraphrases appropriate to the learner. Do not select rare expressions merely to sound high-band.
- Default to 5–10 new items (10 if the learner asks for 10); fewer if due reviews or errors require attention. Honor explicit counts and requests to study a single term. Never show vocabulary that gives away an outstanding exam question unless the learner explicitly requests help.
- Distinguish source quotations, dictionary information, and tutor-created examples. Do not invent a source locator, dictionary attribution, CEFR level or verification claim. If the requested passage is not identifiable, ask for its ID/name rather than guessing.

## 2. Teach in context

Use Vietnamese explanations with English examples. For each new word or expression provide a compact entry:

- **Word / expression** in its useful lemma or phrase form; **US IPA** (state if uncertain; do not claim Cambridge verification unless checked); **part of speech**.
- **Vietnamese meaning** and the meaning in the actual context, with the original sentence and locator if available.
- **Collocations:** 2–4 natural patterns; **word family** where useful; **paraphrases** with important differences in register or meaning. Avoid presenting near-synonyms as universally interchangeable.
- **Example:** one natural English sentence with short Vietnamese translation; label tutor-created examples. Include a common usage error only when useful and distinguish actual learner errors from illustrative pitfalls.

For a single definition request, answer directly without forcing a full quiz or saving a record.

## 3. Conduct a learning session

1. Identify the active request and material (if any). Read the private vocabulary journal if present; review due items first, unless the user explicitly wants a different task. For a review-only request, do not introduce new vocabulary automatically.
2. For due reviews, test before showing any meaning or solution. Use a manageable batch (default up to 10, oldest due first; prioritize repeatedly missed items within the same due date). State if more remain. If no journal/due items exist, say so, and offer new learning or a clearly labeled unsaved practice.
3. Teach new items in small batches. Use active recall after teaching: hide target answers, meanings or examples as appropriate for the next exercise.
4. Vary tasks: English-to-Vietnamese recall, Vietnamese/context-to-English recall, cloze without word banks when appropriate, collocation choice, and paraphrasing. Accept valid alternatives where the task permits; if testing a specific target, distinguish semantic correctness from target recall. Never disclose the answers to outstanding exercises.
5. Ask the learner to produce their own sentence or short Writing/Speaking response using selected target items in a new context. Correct grammar, word form, prepositions, collocations, meaning and naturalness; explain the key correction and give a focused retry. In voice tasks do not assess pronunciation from text alone.
6. Summarize actual outcomes (new items studied, recalled, productive use, items needing review), not assumed mastery. Offer to save once at the end of a session or batch. A request such as "Lưu kết quả buổi học" is explicit consent for that batch; otherwise ask first. Do not persist fictional attempts, unanswered items as correct, or tutor examples as learner production.

### Recognition and productive knowledge

Assign a level from the learner's demonstrated performance in the current assessment, independently of the spacing stage:

| Level | Meaning | Required evidence |
| --- | --- | --- |
| 0 | Unknown / not yet assessed | Cannot recall/recognize, or only taught and not yet tested; distinguish not assessed in the outcome |
| 1 | Recognized | Correct recognition with choices, a prompt or substantial help |
| 2 | Recalled | Correct unaided retrieval of the target meaning/form, including acceptable inflection when appropriate |
| 3 | Productive use | Correct independent use of the target in a genuinely new context, with appropriate meaning, form and collocation |

Do not promote a level because the learner copied an example, guessed a multiple-choice answer, repeated a solution just shown, or because time has elapsed. Record assisted answers separately. Immediate correction/retry is learning evidence, not an independent spaced recall.

## 4. Spaced repetition

Use a simple calendar-day policy, not an external service or a new database. The baseline schedule is Day 1 (learning), 2, 4, 7, 14, 30, then maintenance every 30 days. These correspond to gaps of 1, 2, 3, 7 and 16 days, followed by 30-day intervals. Delays are relative to the actual review date; never backdate missed reviews.

- `review_stage` is an integer 0–5; stage 0 is newly studied or reset. `next_review_date` for new items is the next calendar day.
- A due, unaided successful recall or productive use (level 2 or 3) advances stage by one up to 5. Schedule the next review after the gap for the resulting stage: stage 0 → 1 day, 1 → 2 days, 2 → 3 days, 3 → 7 days, 4 → 16 days, 5 → 30 days.
- A failed recall resets stage to 0 and schedules tomorrow. Recognition/assisted recall (level 1) keeps stage unchanged and schedules tomorrow; do not advance on an unassessed or skipped item.
- Only the first independent assessed outcome per item per calendar day can advance its stage. An early successful review does not advance stage or postpone the existing due date. A genuine failed/assisted review may shorten it (tomorrow or the existing due date, whichever is earlier, but not earlier than tomorrow after an assessed due item). A same-day retry after feedback cannot earn advancement; an observed later failure can reset stage and shorten the schedule. Use the last actual local calendar date for the session; dates are ISO YYYY-MM-DD.
- Due means `next_review_date <= today`. Review on request, not through a background scheduler. A learner can always request additional practice without advancing the calendar.
- No fixed claim of mastery after Day 30: keep maintenance, especially for words repeatedly used incorrectly.

## 5. Private vocabulary journal (JSONL)

Use only `private/progress/vocabulary.jsonl` for vocabulary state. It is a lightweight personal learning journal, separate from the canonical vocabulary schema and normalized question bank. The existing `/private/` Git ignore rule covers it. Do not create the file until the first approved save. Do not modify `data/vocabulary/`, source materials, schemas, answer keys, databases or Harness. Never stage or push this journal.

One UTF-8 JSON object per line, one current record per identity. The identity is normalized expression + part of speech + sense: Unicode NFKC, trim, collapse whitespace, casefold each component. Reuse the stored sense key for the same meaning, even if the Vietnamese gloss changes. Keep genuinely distinct senses/parts of speech separate. Record useful collocations within the base entry unless separately studied as an independent expression.

Required fields for every record:

| Field | Meaning |
| --- | --- |
| `entry_key` | Normalized identity components joined by `|`; components cannot contain a literal pipe (escape it as %7C, and escape % as %25 first) |
| `expression`, `pos`, `sense_key`, `meaning_vi` | Stable vocabulary identity and short Vietnamese gloss |
| `sources` | Array of unique source references; each has `kind` (material, dictionary, or tutor_created), `ref` (actual relative path/ID/URL or null for tutor-created), and `locator` (actual location or null) |
| `level`, `review_stage` | Integers as defined above |
| `first_studied_date`, `last_review_date`, `next_review_date` | Local ISO dates; last review null until actually assessed |
| `last_outcome` | not_assessed, failed, assisted, recalled, or productive |
| `review_count`, `lapse_count` | Nonnegative counts of assessed calendar days and failed-recall calendar days, respectively; same-day retries do not increment these |
| `errors` | Array of concise observed usage/recall errors with date, category, attempted form and correction; empty when none |

Illustrative synthetic record (not a real learner attempt; never copy into the live journal):

```json
{"entry_key":"reduce|verb|make less","expression":"reduce","pos":"verb","sense_key":"make less","meaning_vi":"làm giảm","sources":[{"kind":"tutor_created","ref":null,"locator":null}],"level":0,"review_stage":0,"first_studied_date":"2026-01-01","last_review_date":null,"next_review_date":"2026-01-02","last_outcome":"not_assessed","review_count":0,"lapse_count":0,"errors":[]}
```

Persistence procedure after explicit approval:

1. Read the latest journal again (if absent, start empty). Parse all nonblank lines, validate required fields, enum/range/date consistency and unique keys. If invalid or duplicates exist, report the issue and do not overwrite or silently discard history.
2. Upsert only records for actually studied/assessed items in the approved batch. Preserve unrelated records, first study date, existing source references, and observed errors; deduplicate source references and identical error events. Use the rules above for daily advancement and counts. If the same day's batch is already saved, do not double-count or advance again.
3. Ensure the resolved journal path is inside the repository's ignored `private/progress/` directory and no symlink escapes it. Use a temporary file in that same directory, validate the complete UTF-8 JSONL, then atomically replace the journal (e.g. Python standard library via `./.venv/bin/python`). Do not truncate the original on failure; if the file changed since reading, reload/reconcile or report conflict rather than overwrite concurrent edits.
4. Confirm the saved record count and next due dates briefly. If unable to persist (missing environment, permissions, malformed file), report that nothing was saved and keep teaching. Do not install packages, create a new schema/DB or fall back to public folders.

## 6. Short commands and expected behavior

| Natural language request | Action |
| --- | --- |
| Học 10 từ mới / Học 10 từ vựng IELTS hôm nay | Review due items first (unless explicitly skipped); teach 10 new items in small batches; quiz and offer save |
| Học IVU-60 Unit 1 / Học IVU-65 Unit 5 / Học EVU-B2 Unit 14 / Học AVU Unit 37 | Load specific Unit from Knowledge Base (`private/knowledge/vocabulary/`); present contextual targets, original exercises (hidden key), and active recall |
| Học từ vựng chủ đề Education / Học Environment kết hợp các nguồn | Retrieve multi-source topic module from Knowledge Base (`topic_index.json`), synthesize vocabulary, collocations and paraphrases |
| Luyện collocation chủ đề Work / Học paraphrase chủ đề Crime | Focused topic exercises using collocations and paraphrase banks |
| Kiểm tra EVU-B2 Unit 14 / Kiểm tra Unit vừa học | Retrieve original textbook exercises for that Unit; conceal answer key until learner submits |
| Học Unit tiếp theo / Tiếp tục bài hôm qua | Resume curriculum progression from saved curriculum state or previous session |
| Xem tiến độ học từ vựng | Summarize vocabulary journal count, due review items, and completed Units |
| Ôn từ vựng hôm nay / Ôn những từ đến hạn hôm nay | Load due items from the journal and quiz without answers; offer to save actual outcomes |
| Kiểm tra từ vựng đã học | Sample saved items, even if not due; distinguish early practice from scheduled reviews |
| Học từ vựng trong bài Reading vừa làm / Lọc từ vựng quan trọng trong bài vừa làm | Use identified material; select contextual items, actual gaps and useful paraphrases; never invent a passage |
| Luyện collocation / Luyện paraphrase | Focused contextual exercises; use existing material when available |
| Kiểm tra những từ tôi thường dùng sai | Prioritize recorded usage errors and lapses; if no evidence, state limitation and offer a diagnostic |
| Cho bài tập Writing sử dụng các collocation đã học | Reuse journal items in a new writing task, correct productive use |
| Lưu kết quả buổi học | Persist the actual approved vocabulary batch, if there is one |

Short answers while an exercise is active are assessed as part of that exercise. Do not require the learner to repeat a setup prompt. If the previous vocabulary quiz was never saved and the conversation is new, do not invent its contents.

## 7. Manual acceptance smoke checks

These are checks to perform in a new local Agent conversation, not claims of tests already executed:

- Start with an absent journal: "Ôn từ vựng hôm nay" reports no saved vocabulary; no file is created. "Học 5 từ mới" starts teaching without a setup prompt.
- During a quiz, a short answer is assessed as vocabulary; solutions to other unanswered items stay hidden. Declining save leaves the journal untouched.
- Approving a real batch creates only private JSONL records. A repeated save on the same date does not duplicate records or advance the spacing stage twice.
- On a later date, due items are offered before new vocabulary; a failed recall resets stage, recognition does not advance, and unaided due recall advances.
- With an invalid journal or missing material, report the limitation without fabricating history or overwriting records. Reading practice and exam-answer concealment remain unchanged.
