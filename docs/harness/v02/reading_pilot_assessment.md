# IELTS Data Harness V0.2 — Reading Pilot Assessment
**Phase V0.2-A: Schema Design & Normalization Contract (Remediated)**  
**Target:** Ground-Truth Audit of V0.1 Reading Pilot Extractions  
**Evaluated Pilot Candidate:** PILOT-05 (`SRC-138` DOCX Question Paper + `SRC-137` Scanned Key & Explanations)  
**Comparative Candidates:** PILOT-02 (`SRC-011` Scanned Exam PDF) & PILOT-04 (`SRC-077` Tabular XLSX Key)  
**Status:** Completed Technical Audit (Sanitized for Public Documentation)  
**Date:** 2026-11-19 (Remediated)  

---

## 1. Objectives & Privacy Boundary

In accordance with Phase V0.2-A requirements, this report evaluates actual V0.1 staged extractions to determine whether authentic physical materials can support the complete, end-to-end learning relationship:

$$\text{Passage} \longrightarrow \text{Question Group} \longrightarrow \text{Question Item} \longrightarrow \text{Answer Key} \longrightarrow \text{Evidence Span} \longrightarrow \text{Pedagogical Explanation}$$

### Privacy & Copyright Invariants
- **No Verbatim Public Exposure:** Per repository privacy rules, verbatim source texts from copyrighted examination booklets (`VOL 6.docx`) and explanation guides (`KEY + EXPLANATION 5-6.pdf`) are strictly excluded from public repository documents. All findings below are described via **structural descriptions, character counts, and synthetic illustrations**. Full extracted text runs reside exclusively in gitignored `private/staging/`.
- **Historical Exposure Audit:** An audit of initial V0.2-A draft artifacts identified verbatim excerpts in preliminary review notes. All such occurrences have been purged and replaced with structural characterizations.

---

## 2. Primary Audit: PILOT-05 (VOL 6 Reading Test 5, Passage 1)

### 2.1 Source Pair Profile
- **Question Paper Source:** `FILE-3a7f8090a786` (`SRC-138`, `private/raw/VOL 6/READING/VOL 6.docx`)
  - Staged Extraction: `private/staging/raw_extracted/SRC-138/raw_document.json`
  - Structure: Microsoft Word OpenXML (430 paragraphs, 3 tables).
  - Target Passage: Test 5, Reading Passage 1 (Paragraphs 296–325).
- **Answer Key & Explanation Source:** `FILE-998877665544` (`SRC-137`, `private/raw/VOL 6/READING/KEY + EXPLANATION 5-6.pdf`)
  - Staged Extraction: `private/staging/raw_extracted/SRC-137/page_0001.json` and `page_0002.json`.
  - Structure: Scanned 200 DPI PDF processed via `PdfOcrExtractor`.
  - Target Section: Pages 1–2 (corresponding to book pages 95–96).

---

## 3. Component-by-Component Relationship Evaluation

### 3.1 Passage Text (`PassageOrSection`)
- **Staged Location:** `SRC-138/raw_document.json`, paragraphs 298–306.
- **Structural Profile:** 9 distinct subsections covering art history course structure, methodology, authenticity, and historical periods.
- **Finding:** **CONFIRMED & COMPLETE.** Digital OpenXML paragraphs are 100% complete and cleanly demarcated with zero OCR corruption.

### 3.2 Question Groups & Items (`QuestionGroup` & `Question`)
- **Staged Location:** `SRC-138/raw_document.json`, paragraphs 307–325.
- **Structural Finding (Joined Sentence Run):**
  Paragraph index `309` contains all six True/False/Not Given questions concatenated without paragraph breaks:
  - *Structural Pattern:* `[Digit 1][Prompt 1][Period][Digit 2][Prompt 2]...[Word][Digit 5][Prompt 5]...`
  - *Regex Resolution:* Verified solvable with zero text loss using delimiter pattern `(?:^|[\.\?!a-zA-Z\s])(k)(?:[\.\s]*)(?=[A-Z])`.
- **Group 2 (Questions 7–13):** Note completion items across 8 paragraphs. Cleanly separated.

### 3.3 Answer Keys (`Answer`)
- **Staged Location:** `SRC-137/page_0001.json` and `page_0002.json`.
- **Item-Level Findings:**
  - **Question 1:** **MISSING FROM SOURCE.** `page_0001.json` corresponds to printed book page 95 and begins mid-sentence with Question 2. Question 1 was printed on book page 94, which was **omitted from the physical scan**.
  - **Questions 2–6:** **CONFIRMED.** Answers present (`False`, `Not Given`, `True`, `False`, `True`).
  - **Questions 7–10:** **CONFIRMED.** Answers present with minor OCR spelling noise (`Fraudulant` for `fraudulent`).
  - **Questions 11–13:** **MISSING FROM SOURCE.** Text at the bottom of Page 2 ends abruptly at book page 96. Page 3 jumps immediately to Reading Passage 2. Questions 11–13 were truncated during book scanning.
- **Coverage:** 9 of 13 answers present (69% coverage).

### 3.4 Evidence Spans (`Evidence`)
- **Questions 3–6:**
  - Q3 (`NOT GIVEN`): `SRC-137` correctly identifies the relevant passage paragraph, but notes that comparative collection difficulty is never discussed. Modeled as `evidence_type: "insufficient_information_not_given"` with `verbatim_quote: null`.
  - Q4 (`TRUE`): Verbatim quote in `SRC-137` matches paragraph 300 of `SRC-138` with exact character offsets.
  - Q5 (`FALSE`): Contradictory passage sentence located in paragraph 301, disproving the prompt statement.
  - Q6 (`TRUE`): Direct supporting sentence located in paragraph 301.
- **Questions 1, 7–13:** Evidence quotes absent or cut off in source.

### 3.5 Explanations (`Explanation`)
- **Questions 3–6:** Pedagogical reasoning is of high quality, establishing explicit lexical paraphrase links (e.g. prompt terms mapped to passage equivalents) and explaining why distractor inferences fail.
- **Remainder:** Missing from source.

---

## 4. End-to-End Relationship Summary Matrix

| Question Range | Passage (`SRC-138`) | Prompt (`SRC-138`) | Key (`SRC-137`) | Evidence (`SRC-138` / `SRC-137`) | Explanation (`SRC-137`) | End-to-End Status |
|---|---|---|---|---|---|---|
| **Q1** | Present | Present (in p. 309) | **MISSING** (Scan gap) | **MISSING** | **MISSING** | **INCOMPLETE (Missing Key)** |
| **Q2** | Present | Present (in p. 309) | Present (`False`) | Fragmented | Fragmented | **PARTIAL (Answer Only)** |
| **Q3** | Present | Present (in p. 309) | Present (`Not Given`) | **VERIFIED** (Insufficient Info) | **VERIFIED** (Absence rationale) | **COMPLETE & VERIFIED** |
| **Q4** | Present | Present (in p. 309) | Present (`True`) | **VERIFIED** (Direct Support) | **VERIFIED** (Paraphrase map) | **COMPLETE & VERIFIED** |
| **Q5** | Present (in p. 309) | Present | Present (`False`) | **VERIFIED** (Contradiction) | **VERIFIED** (Opposition proof) | **COMPLETE & VERIFIED** |
| **Q6** | Present (in p. 309) | Present | Present (`True`) | **VERIFIED** (Direct Support) | **VERIFIED** (Paraphrase map) | **COMPLETE & VERIFIED** |
| **Q7–Q10** | Present | Present | Present (OCR typo) | Derivable in text | None | **PARTIAL (Key Only)** |
| **Q11–Q13** | Present | Present | **MISSING** (Scan cutoff) | **MISSING** | **MISSING** | **INCOMPLETE (Missing Key)** |

---

## 5. Comparative Pilot Assessments

- **PILOT-02 (`SRC-011`, VOL 1 Test 1):** Complete Question Booklet and complete official Answer Key (p. 23). Zero evidence quotes and zero explanations provided in source.
- **PILOT-04 (`SRC-077`, VOL 3 `key.xlsx`):** Tabular ground truth for 360 questions across Tests 1–9. Questions reside in unextracted `SRC-079`. Represents orphaned answer key bank.

---

## 6. Key Takeaways for V0.2-B Normalizer
1. **Joined Question Segmentation:** Implement monotonic lookahead delimiter `(?:^|[\.\?!a-zA-Z\s])(k)(?:[\.\s]*)(?=[A-Z])`.
2. **Nullable Foreign Keys:** Accommodate scan gaps and orphaned keys without guessing or imputing values.
3. **NOT GIVEN Evidence Modeling:** Prohibit forced verbatim quotes for NOT GIVEN items.
