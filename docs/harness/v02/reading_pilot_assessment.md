# IELTS Data Harness V0.2 — Reading Pilot Assessment
**Phase V0.2-A: Schema Design & Normalization Contract**  
**Target:** Ground-Truth Audit of V0.1 Reading Pilot Extractions  
**Evaluated Pilot Candidate:** PILOT-05 (`SRC-138` DOCX Question Paper + `SRC-137` Scanned Key & Explanations)  
**Comparative Candidates:** PILOT-02 (`SRC-011` Scanned Exam PDF) & PILOT-04 (`SRC-077` Tabular XLSX Key)  
**Status:** Completed Technical Audit  
**Date:** 2026-11-19  

---

## 1. Objectives & Scope of Assessment

In accordance with Phase V0.2-A requirements, this report evaluates actual V0.1 staged extractions to determine whether authentic physical materials can support the complete, end-to-end learning relationship:

$$\text{Passage} \longrightarrow \text{Question Group} \longrightarrow \text{Question Item} \longrightarrow \text{Answer Key} \longrightarrow \text{Evidence Span} \longrightarrow \text{Pedagogical Explanation}$$

### Evaluation Rules
1. **No Imputation / No Guessing:** Relationships must be substantiated by authentic staged files.
2. **Provenance Traceability:** Every link must be auditable against physical file paths, byte blocks, or page numbers.
3. **Discrepancy Reporting:** All missing inputs, OCR degradations, truncated pages, and ambiguous structural joinings must be explicitly cataloged.

---

## 2. Primary Audit: PILOT-05 (VOL 6 Reading Test 5, Passage 1)

### 2.1 Source Pair Profile
- **Question Paper Source:** `SRC-138` (`private/raw/VOL 6/READING/VOL 6.docx`)
  - Staged Extraction: `private/staging/raw_extracted/SRC-138/raw_document.json`
  - Nature: High-fidelity digital Microsoft Word OpenXML document (430 paragraphs, 3 tables).
  - Target Passage: Test 5, Reading Passage 1 ("Studies in the History of Art and Visual Culture", paragraphs 296–325).
- **Answer Key & Explanation Source:** `SRC-137` (`private/raw/VOL 6/READING/KEY + EXPLANATION 5-6.pdf`)
  - Staged Extraction: `private/staging/raw_extracted/SRC-137/page_0001.json` and `page_0002.json`.
  - Nature: Scanned 200 DPI PDF processed via `PdfOcrExtractor` (Tesseract `eng+vie`).
  - Target Section: Pages 1–2 (physical book pages 95–96).

---

### 2.2 Entity-by-Entity Relationship Audit

#### Component 1: Passage Text (`PassageOrSection`)
- **Staged Location:** `SRC-138/raw_document.json`, paragraphs 298–306.
- **Passage Title:** *"Studies in the History of Art and Visual Culture"*
- **Structure:** Subsections titled *General Information*, *Theory and Methods*, *Choosing Courses*, *Authenticity and Replication*, *French Painting 1880-1912*, *Medieval European Art*, *Reception of Classical European Art*, and *Women, Art and Culture in Early Modern Europe*.
- **Assessment:** **CONFIRMED & COMPLETE.** Digital text is 100% clean, devoid of OCR noise, with paragraph boundaries perfectly demarcated by OpenXML block indices.

---

#### Component 2: Question Groups & Items (`QuestionGroup` & `Question`)
- **Staged Location:** `SRC-138/raw_document.json`, paragraphs 307–325.
- **Group 1 (Questions 1–6):** True/False/Not Given (Paragraph 307: `"Questions 1-6"`, Paragraph 308: Instructions).
  - **Structural Defect Detected (Joined Paragraph Run):**  
    In `raw_document.json`, paragraph 309 contains all six questions concatenated into a single string without paragraph breaks:
    ```text
    " 1 Applicants to the department must have previously studied art history.2 Students can choose two optional courses instead of the Theory and Methods course.3 The course organisers had more problems collecting art objects from some historical periods than others.4 The Theory and Methods course focuses on the way art is made and perceived5 Students will be able to do any of the optional courses that are listed.6 Students may be able to take an unlisted course if they get the appropriate approval."
    ```
  - **Remediation Feasibility:** Highly feasible via automated regex segmentation:  
    `(?:\s|^)(\d{1,2})\s+([A-Z][^\d\n]+?)(?=(?:\s+\d{1,2}\s+[A-Z])|$)`.
- **Group 2 (Questions 7–13):** Note completion (Paragraph 310: `"Questions 7-13"`, Paragraph 311: `"Choose ONE WORD ONLY from the passage..."`).
  - Paragraphs 312–325 contain cleanly separated note items across the subsection headings.
- **Assessment:** **CONFIRMED (Requires Regex Segmentation for Q1–Q6).**

---

#### Component 3: Answer Keys (`Answer`)
- **Staged Location:** `SRC-137/page_0001.json` and `page_0002.json`.
- **Item-Level Findings:**
  - **Question 1:** **MISSING FROM SOURCE.** `page_0001.json` is physically page 95 of the original printed book and begins at the top with `"Methods course. \n Answer: False"`. Question 1 was printed on page 94, which was **not scanned** into `SRC-137`.
  - **Question 2:** **CONFIRMED.** Answer: `False` (visible at top of Page 1).
  - **Question 3:** **CONFIRMED.** Answer: `Not Given` (Page 1).
  - **Question 4:** **CONFIRMED.** Answer: `True` (Page 1).
  - **Question 5:** **CONFIRMED.** Answer: `False` (Page 2).
  - **Question 6:** **CONFIRMED.** Answer: `True` (Page 2).
  - **Questions 7–10:** **CONFIRMED (With OCR Noise):**
    - Q7: Printed as `"Fraudulant"` (OCR misspelling of `fraudulent`).
    - Q8: Printed as `"museums"`.
    - Q9: Printed as `"Cubism"`.
    - Q10: Printed as `"cinema"`.
  - **Questions 11–13:** **MISSING FROM SOURCE.** At the bottom of Page 2 (book page 96), text ends abruptly at `"Medieval European Art \n 96"`. Page 3 (book page 97) immediately begins with Reading Passage 2 (*"Sleep - who needs it?"*). Questions 11–13 were omitted or lost during the scanning of the explanation booklet.
- **Assessment:** **PARTIALLY COMPLETE (69% Coverage: 9 of 13 answers present; Q1, Q11, Q12, Q13 missing).**

---

#### Component 4: Evidence Spans (`Evidence`)
- **Staged Location:** `SRC-137/page_0001.json` and `page_0002.json` under `"Location: ..."` headers.
- **Item-Level Grounding Verification against `SRC-138`:**
  - **Question 3:**
    - `SRC-137` Quote: *"The course aims to redefine art history and includes a broader range of objects and visual media than other art history courses. Images and objects produced in many contexts- ranging from the scientific to the popular- have been brought together to show how visual styles at different periods and in different places can be understood..."*
    - Verification in `SRC-138`: Matches paragraph 300 (*Theory and Methods*) verbatim. Exact character span verified.
  - **Question 4:**
    - `SRC-137` Quote: *"...production of art and people's responses to it."*
    - Verification in `SRC-138`: Matches paragraph 300 verbatim.
  - **Question 5:**
    - `SRC-137` Quote: *"The optional courses listed below are not available every year and prospective students are advised to check on the availability of specific courses."*
    - Verification in `SRC-138`: Matches paragraph 301 (*Choosing Courses*) verbatim.
  - **Question 6:**
    - `SRC-137` Quote: *"Students wishing to take a course that does not appear in the list but is offered by the Faculty of History will need to get permission from the relevant Course Tutor."*
    - Verification in `SRC-138`: Matches paragraph 301 verbatim.
  - **Questions 7–10:** No location quotes provided in `SRC-137`. However, answers are verbatim single words appearing in paragraph 302 (*Authenticity and Replication*) and paragraph 303 (*French Painting*).
- **Assessment:** **CONFIRMED FOR Q3–Q6; DERIVABLE FOR Q7–Q10; UNRESOLVED FOR Q1, Q11–Q13.**

---

#### Component 5: Explanations (`Explanation`)
- **Staged Location:** `SRC-137/page_0001.json` and `page_0002.json` under `"Explanation: ..."` headers.
- **Pedagogical Quality:**
  - **Question 3:** Explains that while objects from different periods were collected, *"there is no information whether more objects were collected from one period than another"*, providing the exact rationale for `NOT GIVEN`.
  - **Question 4:** Explicitly connects prompt phrase *"is made and perceived"* with passage phrase *"production of art and people's responses to it"*.
  - **Question 5:** Demonstrates that *"not available every year"* contradicts prompt statement *"will be able to do any of the optional courses"*.
  - **Question 6:** Maps *"unlisted course"* to *"course that does not appear in the list"*, and *"appropriate approval"* to *"permission from the relevant course tutor"*.
- **Assessment:** **EXCELLENT PEDAGOGICAL FIDELITY FOR Q3–Q6; MISSING FOR REMAINDER.**

---

### 2.3 Comprehensive Relationship Matrix: Test 5 Passage 1

| Q# | Question Prompt (`SRC-138`) | Ground Truth Answer (`SRC-137`) | Evidence Quote (`SRC-137` / `SRC-138`) | Pedagogical Explanation (`SRC-137`) | End-to-End Status |
|---|---|---|---|---|---|
| **1** | Present (Concatenated in p. 309) | **MISSING** (Scan started p. 95) | **MISSING** | **MISSING** | **INCOMPLETE (Missing Key)** |
| **2** | Present (Concatenated in p. 309) | `False` | Fragmented in OCR header | Missing / Fragmented | **PARTIAL (Answer Only)** |
| **3** | Present (Concatenated in p. 309) | `Not Given` | **VERIFIED** (Passage para 300) | **VERIFIED** (Explains lack of comparative data) | **COMPLETE & VERIFIED** |
| **4** | Present (Concatenated in p. 309) | `True` | **VERIFIED** (Passage para 300) | **VERIFIED** (Paraphrase: perceived = responses) | **COMPLETE & VERIFIED** |
| **5** | Present (Concatenated in p. 309) | `False` | **VERIFIED** (Passage para 301) | **VERIFIED** (Contradiction established) | **COMPLETE & VERIFIED** |
| **6** | Present (Concatenated in p. 309) | `True` | **VERIFIED** (Passage para 301) | **VERIFIED** (Paraphrase: unlisted = not in list) | **COMPLETE & VERIFIED** |
| **7** | Present (Note item, p. 314) | `fraudulent` (OCR: Fraudulant) | Derivable in para 302 | None | **PARTIAL (Key Derivable)** |
| **8** | Present (Note item, p. 315) | `museums` | Derivable in para 302 | None | **PARTIAL (Key Derivable)** |
| **9** | Present (Note item, p. 317) | `Cubism` | Derivable in para 303 | None | **PARTIAL (Key Derivable)** |
| **10**| Present (Note item, p. 318) | `cinema` | Derivable in para 303 | None | **PARTIAL (Key Derivable)** |
| **11**| Present (Note item, p. 321) | **MISSING** (Cut off at p. 96) | **MISSING** | **MISSING** | **INCOMPLETE (Missing Key)** |
| **12**| Present (Note item, p. 324) | **MISSING** (Cut off at p. 96) | **MISSING** | **MISSING** | **INCOMPLETE (Missing Key)** |
| **13**| Present (Note item, p. 325) | **MISSING** (Cut off at p. 96) | **MISSING** | **MISSING** | **INCOMPLETE (Missing Key)** |

---

## 3. Comparative Pilot Assessments

### 3.1 PILOT-02: `SRC-011` (VOL 1 Test 1 Reading)
- **Passage & Questions:** Available across pages 8–10 (`page_0008.json`–`page_0010.json`).
- **Answer Key:** Page 23 (`page_0023.json`) contains complete official answers for Questions 1–13 (e.g. 1: `white`, 8: `TRUE`, 9: `NOT GIVEN`, 10: `FALSE`).
- **Evidence & Explanations:** **100% ABSENT.** The booklet provides zero evidence quotes and zero explanations.
- **Architectural Conclusion:** `SRC-011` can validate the relationship $\text{Passage} \to \text{Question} \to \text{Answer}$, but cannot validate Evidence or Explanation without human authoring.

### 3.2 PILOT-04: `SRC-077` (VOL 3 Reading `key.xlsx`)
- **Answer Key:** Highly structured tabular ground truth across 9 sheets (`Test 1` through `Test 9`), 40 questions per test.
- **Passages & Questions:** In `SRC-079` (`FULL reading vol 2.pdf`), which was not part of the 7 pilot files in V0.1.
- **Architectural Conclusion:** Demonstrates tabular answer key normalization, but represents an **orphaned key** until `SRC-079` is extracted in Phase V0.2.

---

## 4. Key Engineering Takeaways for Phase V0.2-B Normalizer

1. **Robust Splitters for Joined DOCX Runs:**
   The normalizer must incorporate a robust sentence and item splitter to separate joined question paragraphs (e.g., `1 Applicants... 2 Students...`).
2. **Missing Input Tolerant Schema:**
   The schema must allow `answer: null`, `evidence: null`, and `explanation: null` while assigning the entity a status of `review_required`.
3. **OCR Typo Remediation Layer:**
   A dictionary check or Levenshtein comparison is required to catch OCR misreadings in answer keys (such as `Fraudulant` $\to$ `fraudulent`).
4. **Multi-Source Reconciliation Strategy:**
   Where scanned explanation books have missing pages (such as page 94 missing in `SRC-137`), the pipeline should support joining an alternative answer source (such as `SRC-136` `KEY.pdf` or an official key table).
