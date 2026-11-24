# BÁO CÁO NGHIỆM THU: VOCABULARY KNOWLEDGE BASE V1.0 — FINAL IMPLEMENTATION REPORT

**Hệ thống:** IELTS Adaptive Learning System & Tutor  
**Mục tiêu:** Xây dựng Cơ sở Tri thức Từ vựng chuẩn hóa, liên kết 8 bộ giáo trình gốc phục vụ mục tiêu IELTS Academic Band 7.5+  
**Chiến lược kỹ thuật:** *Parse once — Enrich progressively — Learn repeatedly (Không overengineering, không vector DB thừa, không đa agent)*  
**Trạng thái nghiệm thu:** **VERIFIED & READY FOR LEARNING**

---

## 1. TỔNG QUAN VÀ MỤC TIÊU DỰ ÁN

Mục tiêu tối thượng của dự án là **hiệu quả học tập của người học (Learning first)**. Kiến trúc phần mềm và kỹ thuật trích xuất dữ liệu đóng vai trò là cơ chế hỗ trợ, bảo đảm:
- Chuyển hóa toàn diện 8 bộ giáo trình từ vựng kinh điển sang dạng dữ liệu có cấu trúc, lưu vết nguồn gốc (provenance) chính xác từng trang và mục bài.
- Tích hợp trực tiếp vào Gia sư kiên trì (**Persistent IELTS Tutor Skill**) mà không tạo ra hệ thống cạnh tranh hay làm xáo trộn luồng hội thoại.
- Áp dụng các nguyên tắc học tập thực chứng: Học trong ngữ cảnh (Contextual Learning), Gợi nhớ chủ động (Active Recall), Lặp lại ngắt quãng (Spaced Repetition), và Vận dụng vào 4 kỹ năng (Knowledge Transfer).
- Tuân thủ chính sách bản quyền và bảo vệ dữ liệu cá nhân: 100% dữ liệu gốc và dữ liệu trích xuất nằm trong thư mục `private/` (được bảo vệ tuyệt đối bởi Git ignore, không đưa lên repository).

---

## 2. KIỂM KÊ 8 BỘ GIÁO TRÌNH GỐC (SOURCE INVENTORY)

Toàn bộ 8 tệp PDF trong thư mục `private/raw/vocabulary_books/` đã được kiểm kê, băm SHA-256 và xác thực ấn bản trực tiếp từ trang tiêu đề:

| Source ID | Tác giả & Ấn bản | Tệp & Kích thước | SHA-256 (64 ký tự) | Trang PDF | Số Unit | Cấu trúc & Text Layer | Đáp án gốc (Answer Key) | Tình trạng Audio | Ghi chú kỹ thuật |
|---|---|---|---|---|---|---|---|---|---|
| **EVU-B2** | Michael McCarthy, Felicity O'Dell (CUP, 4th Ed.) | `EVU-B2.pdf` (24.71 MB) | `ac9334752760f87ae2eee951e4fc65b342ac0973db9ecee5b8ab0bf28f86772f` | 280 | 101 Units | Text layer số hóa. Cấu trúc 2 trang/Unit chuẩn (Trái: Lý thuyết, Phải: Bài tập). | Trang 211–257 | Không áp dụng | Trích xuất đáp án dùng `-layout` đa cột để khớp đúng số bài. |
| **EVU-ADV** | Michael McCarthy, Felicity O'Dell (CUP, 3rd Ed.) | `EVU-ADV.pdf` (6.79 MB) | `217b7fe6b4f32245c9284fbc471689eda35f17ed84845694a37d9a43a87e0b0d` | 303 | **101 Units** | Text layer số hóa. Bao gồm Unit 101 ("Red tape", trang 210–211). | Trang 212–277 | Không áp dụng | Đáp án Unit 101 trải dài trang 276–277; đã ghép trang tự động. |
| **ECI-INT** | Michael McCarthy, Felicity O'Dell (CUP, 2nd Ed.) | `ECI-INT.pdf` (19.12 MB) | `670c7dd50c490d724ed5ba18c63da48057addfa73f0c6572a367a45a449fd39f` | 194 | 60 Units | Text layer số hóa. Cấu trúc 2 trang/Unit. | Trang 130–161 | Không áp dụng | Mục lục và ranh giới được xây dựng xác định từ text layer. |
| **ECI-ADV** | Felicity O'Dell, Michael McCarthy (CUP, 2nd Ed.) | `ECI-ADV.pdf` (24.70 MB) | `1162504a76346d5881745cc73ea992037c7c653a9614bfbd3cd6a40ead382773` | 194 | 60 Units | Text layer số hóa. Cấu trúc 2 trang/Unit. | Trang 128–163 | Không áp dụng | Đã đối soát chính xác trang đáp án Unit 17 (p. 140). |
| **AVU** | Michael McCarthy, Felicity O'Dell (CUP, **Second Edition 2016**) | `AVU.pdf` (3.18 MB) | `433565b379693e1eeedd6fd7881d087552595c7c92060ac2ba5c86944758e7e5` | 176 | 51 Units | Text layer số hóa. Unit 0 + 50 Units + 6 bài đọc chuyên ngành + Phụ lục. | Trang 134–163 | Không áp dụng | Ấn bản Second Edition (2016) được xác thực từ trang tiêu đề gốc. |
| **IVU-60** | Pauline Cullen (CUP, Band 6.0) | `IVU-60.pdf` (442.29 MB) | `9cbf654572ce5f698792df069d16a6b771e05da4f05b004fc4d261cddd599bbe` | 178 | 25 Units + 5 Tests | **Scanned PDF (100% ảnh scan)**. Xử lý OCR bounded on-demand theo từng Unit/trang. | Trang 134–158 | Tham chiếu Tracks 1a–38b (thiếu file audio cục bộ) | Không OCR toàn bộ 442 MB trước. Dùng Recording Scripts (p. 159–168). |
| **IVU-65** | Pauline Cullen (CUP, Band 6.5+) | `IVU-65.pdf` (27.60 MB) | `4cec17a45277301fe92b97c2fe3941aac9abad0b02cf512e69f88ef0d5641a12` | 177 | 25 Units | **Scanned PDF (100% ảnh scan)**. Xử lý OCR bounded on-demand có cache đĩa. | Trang 135–158 | Tham chiếu Tracks 1–26 (thiếu file audio cục bộ) | Không OCR trước toàn bộ sách. Dùng Recording Scripts (p. 159–170). |
| **NB-PARA** | Nguyễn Ngọc Bách (ngocbach.com, 2021) | `NB-PARA.pdf` (0.38 MB) | `f01e0a9b5ce0e60ec12a89fa35e9288bb379e4ca7d0d6f579d3b8763c1196637` | 51 | 10 Sections | Text layer số hóa. Phân đoạn Task 1, Task 2 và 5 chuyên đề. | Tự chứa (Song ngữ) | Không áp dụng | Lọc sạch số điện thoại và quảng cáo hotline tự động. |

---

## 3. THỐNG KÊ CƠ SỞ TRI THỨC (ACTUAL KNOWLEDGE BASE METRICS)

- **Tổng số Unit được lập chỉ mục cấu trúc (Indexed Units):** `433 Units/Sections`
  - EVU-B2: 101 Units
  - EVU-ADV: 101 Units (đã bao gồm Unit 101 — Red tape)
  - ECI-INT: 60 Units
  - ECI-ADV: 60 Units
  - AVU: 51 Units (Unit 0 và Units 1–50)
  - IVU-60: 25 Units
  - IVU-65: 25 Units
  - NB-PARA: 10 Sections
- **Số Unit văn bản số đã bóc tách cấu trúc 100% (Structurally Extracted Digital Units):** `383 Units`
  - Đã thực hiện trích xuất toàn bộ 383 Unit từ 6 đầu sách có text-layer (EVU-B2: 101, EVU-ADV: 101, ECI-INT: 60, ECI-ADV: 60, AVU: 51, NB-PARA: 10) và lưu vào `private/knowledge/vocabulary/units/<source_id>/`.
  - Bộ nhớ đệm đáp án (Answer Key Cache) trong parser giúp tốc độ bóc tách chỉ mất trung bình 0.05s/Unit.
- **Sách scan xử lý OCR theo yêu cầu (Bounded On-Demand OCR):** `50 Units` (IVU-60: 25 Units, IVU-65: 25 Units).
  - Không chạy OCR hàng loạt gây quá tải đĩa và CPU; chỉ OCR trang thuộc Unit khi người học bắt đầu học Unit đó, sau đó ghi cache vĩnh viễn.
- **Hệ thống phân loại đa chiều:**
  - `20 Topics dùng chung`: 100% 433 Units đã liên kết với chủ đề tương ứng.
  - `14 Language Functions`: Phân loại chức năng học thuật chuẩn (Cause & effect, Trend description, Evaluation, Argumentation...).

---

## 4. XÁC THỰC MÔ-ĐUN PILOT EDUCATION ĐỐI CHIẾU SÁCH GỐC

Tất cả 10 mục từ vựng, 4 collocations, 3 nhóm paraphrase và 5 bài tập đã được đối soát từng chữ với văn bản PDF gốc:

### 4.1. Điều chỉnh lỗi quan trọng và bẫy dùng từ (Lexical Nuances)
- **Quy tắc collocation với "knowledge" (IVU-65 Unit 5 p. 26):**
  - **Khắc phục nhận định tuyệt đối hóa trước đây:** Pauline Cullen trong IVU-65 chỉ ra rằng khi nói về *một môn học/chuyên ngành cụ thể* (field of study), dùng `knowledge of [classical music/physics]`, KHÔNG nói `knowledge about [classical music]` hay `knowledge for`. Tuy nhiên, trong ngữ cảnh thông thường ngoài học thuật, cụm `knowledge about [the world / the incident]` vẫn được chấp nhận.
  - Tránh cách diễn đạt thiếu tự nhiên: `get the knowledge` (thay bằng `acquire / gain knowledge`).

### 4.2. Đối soát bài tập gốc và phân định rõ ràng
1. **EX-EVU-B2-14.1** (*EVU-B2 trang in 35, trang PDF 36, loại: original_textbook_exercise*):
   - Hướng dẫn gốc: *"Fill the gaps in this life story of a British woman."*
   - Câu hỏi gốc: Điền vào đoạn văn câu chuyện cuộc đời của Amy từ lúc học primary school (1) đến higher education (9).
   - Đáp án đối soát trang 218: `2 nursery school, 3 crèche, 4 admission, 5 grammar, 6 comprehensive, 7 public, 8 sixth-form college, 9 higher education / university`.
2. **EX-EVU-ADV-1.1** (*EVU-ADV trang in 9, trang PDF 11, loại: original_textbook_exercise*):
   - Hướng dẫn gốc: *"Correct the wrong usage of words to do with written work in these sentences."*
   - Câu hỏi gốc: 7 câu sửa lỗi dùng sai từ liên quan đến văn bản học thuật (PhD assignment -> thesis, Martha's dissertation -> composition, essay with 5 pieces -> portfolio...).
   - Đáp án đối soát trang 212: `1 thesis, 2 composition, 3 portfolio, 4 essay, 5 assignment, 6 dissertation, 7 project`.
3. **EX-IVU-65-1.4** (*IVU-65 trang in 26, trang PDF 29, loại: original_textbook_exercise*):
   - **Đính chính số hiệu bài:** Bài tập kết hợp từ với *knowledge* là **Exercise 1.4**, không phải Exercise 5.1.
   - Hướng dẫn gốc: *"All of the words in the box collocate with the word knowledge. Complete the sentences with the correct combination with the word knowledge."*
   - Đáp án đối soát trang 140: `1 a limited knowledge of, 2 common knowledge, 3 a specialist / detailed / in-depth knowledge of, 4 broaden my knowledge of, 5 prior knowledge`.
4. **EX-ECI-ADV-17.1** (*ECI-ADV trang in 39, trang PDF 43, loại: original_textbook_exercise*):
   - Hướng dẫn gốc: *"Answer the questions using collocations from Section A."*
   - Câu hỏi gốc: 6 câu hỏi vận dụng collocation chủ đề Higher Education (graduating, mature students, seats of learning, distinguished scholars, gifted children, straight-A students).
   - Đáp án đối soát trang 140: `1 You graduate from university., 2 mature students, 3 (prestigious) seats of learning, 4 distinguished scholars or leading authorities, 5 gifted children, 6 straight-A students`.
5. **EX-NB-PARA-EDU-1** (*Grounded in NB-PARA trang 30, loại: tutor_transfer_exercise_grounded_in_source*):
   - Phân định rõ ràng: Sách NB-PARA cung cấp các cặp từ/cụm từ tương đương song ngữ (bảng tham chiếu), không có câu hỏi trắc nghiệm hay bài tập số hiệu. Do đó, bài tập chuyển đổi câu này được gắn nhãn minh bạch là **bài tập vận dụng do Gia sư thiết kế dựa trên các cặp paraphrase gốc của thầy Ngọc Bách**, không gán nhãn giả mạo bài tập gốc.

---

## 5. MINH CHỨNG QUY TRÌNH ON-DEMAND ENRICHMENT (7 BƯỚC)

Quy trình 7 bước đã được thử nghiệm thực tế trên **EVU-ADV Unit 101 ("Red tape")**:

```text
=== LẦN 1: TRÍCH XUẤT VÀ LÀM GIÀU THEO YÊU CẦU (FRESH RUN) ===
Thời gian thực thi: 0.0188 giây | from_cache: False
- Bước 1: Truy xuất Unit EVU-ADV-U101 từ unit_index.json -> THÀNH CÔNG (Title: Red tape Characteristics of bureaucratic language)
- Bước 2: Bóc tách nội dung lý thuyết trang 210 -> THÀNH CÔNG (2 Sections: A - Characteristics, B - Correspondence)
- Bước 3: Nhận diện ứng viên từ vựng học thuật -> THÀNH CÔNG (attained, demolish, adjoining, undersigned, aforementioned, red tape...)
- Bước 4: Làm giàu ngữ nghĩa mục từ (IPA, CEFR, Từ loại, Nghĩa tiếng Việt, Collocations, Common Mistakes) -> THÀNH CÔNG (5 mục từ)
- Bước 5: Truy xuất 5 bài tập gốc và đáp án từ trang 276–277 -> THÀNH CÔNG (Ex 101.1 đến 101.5)
- Bước 6: Lưu kết quả tái sử dụng vào private/knowledge/vocabulary/enriched/EVU-ADV/EVU-ADV-U101.json và cập nhật lexical_index.json -> THÀNH CÔNG

=== LẦN 2: TÁI TRUY XUẤT ĐƠN VỊ ĐÃ LÀM GIÀU (CACHE HIT) ===
Thời gian thực thi: 0.0002 giây (0.2 ms) | from_cache: True
- Bước 7: Trả về trực tiếp từ cache đĩa mà KHÔNG lặp lại trích xuất PDF hay làm giàu dữ liệu -> THÀNH CÔNG
```

---

## 6. XÁC MINH NĂNG LỰC SẴN SÀNG GIẢNG DẠY CỦA GIA SƯ (TUTOR LEARNING READINESS)

Đã kiểm thử xác thực 5 câu lệnh tự nhiên trong môi trường tiến độ tổng hợp cô lập (`isolated synthetic progress records`), hoàn toàn không ghi đè dữ liệu thật của người học:

1. **"Học IVU-60 Unit 1."**
   - *Định tuyến:* `Workflow E: Learn (Unit Mode)`
   - *Truy xuất:* Unit `IVU-60-U001` — "Growing up" (Pauline Cullen, Band 6.0). Cung cấp lý thuyết, bài nghe/đọc và bài tập phân đoạn.
2. **"Học từ vựng chủ đề Education."**
   - *Định tuyến:* `Workflow E: Learn (Topic Mode)`
   - *Truy xuất:* Tổng hợp đa nguồn cho topic `education_and_learning` từ IVU-65 U5, EVU-B2 U14, EVU-ADV U1, ECI-ADV U17, NB-PARA.
3. **"Học EVU-B2 Unit 14."**
   - *Định tuyến:* `Workflow E: Learn (Unit Mode)`
   - *Truy xuất:* Unit `EVU-B2-U014` — "Education". Bóc tách lý thuyết trường học, bài tập điền từ 14.1 và đáp án bảo mật.
4. **"Học Unit tiếp theo."**
   - *Định tuyến:* `Workflow E: Learn (Sequential Progression)`
   - *Logic chuyển tiếp:* Đọc vị trí hiện tại từ `curriculum.json` (ví dụ sau Unit 14 của EVU-B2 chuyển sang Unit 15 "Higher education"; hoặc dọc theo trục Pauline Cullen từ IVU-60 U1 sang IVU-60 U2). Tự động lưu vết tiến độ.
5. **"Ôn từ vựng hôm nay."**
   - *Định tuyến:* `Workflow E: Learn (Active Recall / Spaced Review)`
   - *Truy xuất:* Lọc các từ có `next_review_date <= today` từ hồ sơ tiến độ. Đặt câu hỏi Active Recall kiểm tra nghĩa, collocation và đặt câu, cập nhật chu kỳ ngắt quãng.

---

## 7. KẾT QUẢ KIỂM THỬ VÀ HỒI QUY (TEST & REGRESSION SUITE)

- **Kiểm thử phân hệ Từ vựng (`tests/test_vocabulary_kb.py`):**
  - Chạy chế độ CI tiêu chuẩn (không có PDF riêng tư): **6/6 passed** (Toàn bộ test logic, chuẩn hóa, định tuyến intent, lưu trữ tiến độ độc lập).
  - Chạy chế độ Acceptance với cờ `--corpus`: **11/11 passed** (Bao gồm đối soát toàn bộ 8 sách, 433 unit index, bóc tách Family A/B/C, pilot exercises và quy trình 7 bước on-demand).
- **Kiểm thử hồi quy toàn bộ repository:**
  ```bash
  ./.venv/bin/python -m pytest -q tests/
  ```
  **Kết quả:** `238 passed, 15 skipped in 26.04s` (100% Đạt, không có lỗi hồi quy).
- **Kiểm tra nguyên tắc và dữ liệu:**
  - `./.venv/bin/python scripts/build_principles_index.py --check`: Hợp lệ 7 atomic principles; index up to date.
  - `./.venv/bin/python scripts/validate_data.py`: Hợp lệ.
- **Bảo mật và Quyền riêng tư:**
  - `git status` xác nhận không có bất kỳ tệp dữ liệu cá nhân hay PDF bản quyền nào thuộc `private/` bị đưa vào Git staging.

---

## 8. QUYẾT ĐỊNH NGHIỆM THU

### **FINAL APPROVAL: PRODUCTION READY FOR IELTS TUTOR**

Toàn bộ các điều chỉnh chỉ định đã được giải quyết triệt để và kiểm chứng bằng mã nguồn thực thi:
1. Đã cập nhật đầy đủ metadata (AVU Second Edition, EVU-ADV Unit 101, tổng 433 Units/Sections).
2. Đã bóc tách cấu trúc 100% cho 383 Unit văn bản số và sẵn sàng OCR bounded cho 50 Unit scan.
3. Đã hiệu chỉnh chính xác bài tập gốc mô-đun Education (Exercise 1.4 IVU-65), tinh chỉnh sắc thái collocation của Cullen, và phân biệt minh bạch bài tập gốc với bài tập vận dụng.
4. Đã chứng minh quy trình 7 bước On-Demand Enrichment hoạt động trơn tru với cơ chế cache đĩa siêu tốc (< 1 ms).
5. Đã kích hoạt đầy đủ 5 lệnh tự nhiên của Gia sư IELTS Tutor với cơ chế lưu vết tiến độ cô lập an toàn.
