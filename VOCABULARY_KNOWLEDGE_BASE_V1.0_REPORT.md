# BÁO CÁO NGHIỆM THU: VOCABULARY KNOWLEDGE BASE V1.0 — PR #11 TARGETED BUG FIXES

**Hệ thống:** IELTS Adaptive Learning System & Tutor  
**Mục tiêu:** Xây dựng Cơ sở Tri thức Từ vựng chuẩn hóa, liên kết 8 bộ giáo trình gốc phục vụ mục tiêu IELTS Academic Band 7.5+  
**Chiến lược kỹ thuật:** *Parse once — Enrich progressively — Learn repeatedly (Không overengineering, không vector DB thừa, không đa agent)*  
**Trạng thái nghiệm thu:** **VERIFIED & READY FOR LEARNING (DEFECTS RESOLVED)**

---

## 1. TỔNG QUAN VÀ MỤC TIÊU DỰ ÁN

Mục tiêu tối thượng của dự án là **hiệu quả học tập của người học (Learning first)**. Kiến trúc phần mềm và kỹ thuật trích xuất dữ liệu đóng vai trò là cơ chế hỗ trợ, bảo đảm:
- Chuyển hóa toàn diện 8 bộ giáo trình từ vựng kinh điển sang dạng dữ liệu có cấu trúc, lưu vết nguồn gốc (provenance) chính xác từng trang và mục bài.
- Tích hợp trực tiếp vào Gia sư kiên trì (**Persistent IELTS Tutor Skill**) mà không tạo ra hệ thống cạnh tranh hay làm xáo trộn luồng hội thoại.
- Áp dụng các nguyên tắc học tập thực chứng: Học trong ngữ cảnh (Contextual Learning), Gợi nhớ chủ động (Active Recall), Lặp lại ngắt quãng (Spaced Repetition), và Vận dụng vào 4 kỹ năng (Knowledge Transfer).
- Tuân thủ chính sách bản quyền và bảo vệ dữ liệu cá nhân: 100% dữ liệu gốc, bài tập trích xuất và đáp án sách giáo khoa nằm độc quyền trong thư mục `private/` (được bảo vệ tuyệt đối bởi Git ignore, không đưa vào repository công khai).

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
  - Đã thực hiện trích xuất toàn bộ 383 Unit từ 6 đầu sách có text-layer vào `private/knowledge/vocabulary/units/<source_id>/`.
  - Bộ nhớ đệm đáp án (Answer Key Cache) trong parser giúp tốc độ bóc tách chỉ mất trung bình 0.05s/Unit.
- **Sách scan xử lý OCR theo yêu cầu (Bounded On-Demand OCR):** `50 Units` (IVU-60: 25 Units, IVU-65: 25 Units).
  - Không chạy OCR hàng loạt gây quá tải đĩa và CPU; chỉ OCR trang thuộc Unit khi người học bắt đầu học Unit đó, sau đó ghi cache vĩnh viễn.
- **Hệ thống phân loại đa chiều:**
  - `20 Topics dùng chung`: 100% 433 Units đã liên kết với chủ đề tương ứng.
  - `14 Language Functions`: Phân loại chức năng học thuật chuẩn (Cause & effect, Trend description, Evaluation, Argumentation...).

---

## 4. KẾT QUẢ XỬ LÝ TARGETED DEFECTS (PR #11 BUG FIXES)

### 4.1. Khái quát hóa On-Demand Enrichment (Defect Area 1)
- **Loại bỏ từ điển hardcode:** Đã xóa bỏ hoàn toàn từ điển Unit 101 trong `enrichment.py`.
- **Trích xuất sự kiện gốc (Source Facts):** Python trích xuất các ứng viên từ vựng, ngữ cảnh, định nghĩa chú thích (footnotes) và ghi chú trong ngoặc vuông trực tiếp từ nội dung sách giáo khoa (`extract_unit_vocabulary_candidates`).
- **Gia sư làm giàu ngữ nghĩa:** Gia sư IELTS Tutor thực hiện làm giàu ngữ nghĩa (IPA, CEFR, Từ loại, Giải nghĩa tiếng Việt, Collocation) theo nhu cầu thực tế của người học mà không gọi API LLM ngoài.
- **Không ngụy tạo dữ liệu mặc định:** Không tạo phiên âm giả mạo dạng `/{expression}/`, không gán mặc định `C1`, không tự chế định nghĩa tiếng Anh giả. Nếu chưa kiểm chứng, trường thông tin được giữ `None`.
- **Phân định xuất xứ dữ liệu rõ ràng:** Tách biệt tường minh giữa sự kiện gốc từ giáo trình (`source_facts`, `authoritative_textbook`) và nội dung do gia sư làm giàu (`enrichment_agent: tutor_agent`). Các mục từ do gia sư bổ sung ngoài nội dung đối soát được từ sách gốc (`unmatched`) được gắn nhãn `source_grounded: false` và `provenance: tutor_created`, **tuyệt đối không gán nhầm xuất xứ cho sách giáo khoa**.
- **Không coi bộ đệm chỉ có ứng viên là đã hoàn tất làm giàu:** Khi chưa có dữ liệu làm giàu từ gia sư (`enrichment_status: candidates_only` hoặc `enriched_vocabulary: []`), lần truy xuất sau sẽ không trả về cache rỗng mà cho phép gia sư bổ sung dữ liệu và hoàn tất trạng thái `completed`.
- **Minh chứng trên Unit độc lập ngoài Education và Unit 101:** Đã kiểm thử thành công trên **`ECI-INT-U030` ("Work Jobs, career and work")**:
  - Trích xuất 23 ứng viên từ vựng gốc từ bài đọc và chú thích.
  - Gia sư làm giàu các cụm từ: `high-powered job`, `embark on a career`, `climb the career ladder`.
  - Tái truy xuất lần 2 đạt **Cache Hit tức thời trong 0.1 ms**.

### 4.2. Bảo toàn Hợp đồng Tiến độ Học tập PR #10 (Defect Area 2)
- **Loại bỏ thuật toán cạnh tranh:** Đã gỡ bỏ hàm ghi đè tiến độ cũ trong `session.py`.
- **Bảo toàn Level 0–3 & Stage 0–5:**
  - Cấp độ nhận thức: `Level 0` (chưa đánh giá/thất bại), `Level 1` (nhận diện/có trợ giúp), `Level 2` (gợi nhớ độc lập), `Level 3` (vận dụng chủ động).
  - Chu kỳ lặp lại ngắt quãng chuẩn: `Stage 0` (+1 ngày), `Stage 1` (+2 ngày), `Stage 2` (+3 ngày), `Stage 3` (+7 ngày), `Stage 4` (+16 ngày), `Stage 5` (+30 ngày) tương ứng các mốc Day 1, 2, 4, 7, 14, 30.
- **Ôn tập sớm (Early Review) không làm nhảy Stage hoặc dời lịch:** Nếu người học tự ôn tập thành công trước `next_review_date`, hệ thống giữ nguyên `review_stage` và `next_review_date` hiện tại. Chỉ khi ôn tập đúng hạn hoặc quá hạn (`today >= next_review_date`) với `Level >= 2` mới thăng cấp Stage; nếu ôn tập thất bại/cần trợ giúp sớm có thể rút ngắn lịch về ngày mai.
- **Định danh mục từ theo sense:** Khóa định danh `entry_key = expression|pos|sense_key` (thoát ký tự `|`).
- **Chống trùng lặp và thăng cấp nhiều lần trong ngày:**
  - Mỗi mục từ duy trì đúng 1 bản ghi duy nhất trong `private/progress/vocabulary.jsonl`.
  - Trong cùng một ngày dương lịch, chỉ lượt đánh giá độc lập đầu tiên mới có thể thăng cấp Stage. Luyện tập thêm trong ngày không làm nhảy cấp tiến độ hay tăng trùng lặp `review_count`/`lapse_count`.
- **Ràng buộc sự đồng thuận người học (User Consent):**
  - Không tự ý ghi nhật ký tiến độ hoặc trạng thái giáo trình khi người học chưa đồng ý (`user_consented=True`).

### 4.3. Chống mất mát tri thức & Tối ưu lưu trữ (Defect Area 3)
- **Hàm `build-kb` không phá hủy và có tính lũy tích (Idempotent & Non-destructive):**
  - Đọc và hợp nhất các mục từ đã có sẵn trong `vocabulary.jsonl`, không ghi đè mất các từ đã làm giàu trước đó.
- **Hợp nhất nguồn gốc đa giáo trình:**
  - Hàm `merge_lexical_entries` bảo toàn toàn bộ danh sách `sources` khi một từ xuất hiện ở nhiều sách khác nhau.
- **Chỉ mục từ vựng nhất quán:** `lexical_index.json` ánh xạ đồng thời `entry_key` và biểu thức chuẩn hóa `norm_expr`.
- **Hủy bộ đệm cũ theo SHA-256 và Processing Version (Cache Invalidation):** Sử dụng đồng thời `source_sha256` và `PROCESSING_VERSION = "1.1.0"` trên cả cache trích xuất (`units/`), cache OCR (`.meta.json`), và cache làm giàu (`enriched/`) để tự động vô hiệu hóa và bóc tách lại khi tệp nguồn hoặc phiên bản xử lý thay đổi.

### 4.4. Tính toàn vẹn bài tập & Bảo mật bản quyền (Defect Area 4)
- **Định danh bài tập phức hợp (Composite IDs):**
  - Chuyển sang định dạng duy nhất toàn cục: `EX-{source_id}-U{unit_num:03d}-{exercise_number}` (ví dụ: `EX-EVU-B2-U014-14.1`, `EX-IVU-65-U005-1.4`).
  - Tránh hoàn toàn xung đột khóa đáp án (Answer Key Collision) giữa các Unit khác nhau.
- **Không cắt ngắn nội dung câu hỏi:** Loại bỏ các giới hạn cắt chuỗi (`[:200]`, `[:1200]`) trong parser để giữ nguyên văn bản bài tập gốc.
- **Phân loại nguồn đáp án minh bạch:**
  - `authoritative_textbook_key`: Đáp án chính thức từ sách giáo khoa số hóa.
  - `uncertain_ocr_key`: Đáp án từ OCR sách scan (có thể có sai số nhận dạng).
  - `tutor_suggested_answer`: Gợi ý giải thích từ gia sư cho các bài tập mở/vận dụng.
- **Ẩn đáp án trong phiên luyện tập:** Khi giao bài tập cho người học, trường đáp án bị ẩn hoàn toàn (`hidden_key = True`), đáp án chỉ được nạp từ `answer_keys.jsonl` tại thời điểm chấm bài.
- **Bảo mật bản quyền:** 100% trích đoạn bài tập gốc và đáp án bản quyền đã được chuyển hoàn toàn vào thư mục riêng tư `private/` (`seed_education.json`, `exercises.jsonl`, `answer_keys.jsonl`), không lưu trữ văn bản bản quyền trong mã nguồn Python công khai hay báo cáo Markdown công khai.
- **Kiểm thử công khai bằng Synthetic Fixtures:** Các bài kiểm thử CI sử dụng dữ liệu giả lập tổng hợp, không phụ thuộc PDF riêng tư hay trích đoạn sách có bản quyền.

### 4.5. Điều hướng Lộ trình Thích ứng & Tiến độ Đa giáo trình (Adaptive Vocabulary Roadmap & Navigation)
- **Tiến độ độc lập theo từng giáo trình (`track_positions` & `unit_progress`):** Theo dõi riêng vị trí hiện tại, số Unit hoàn thành và đang học dở cho từng cuốn trong 8 bộ giáo trình (`IVU-60`, `IVU-65`, `EVU-B2`, `EVU-ADV`, `ECI-INT`, `ECI-ADV`, `AVU`, `NB-PARA`) và trục chính `PRIMARY_CORE`.
- **Chuyển đổi luồng học & Tiếp tục bài học dở trong hội thoại mới:** Hỗ trợ chuyển giữa các bộ giáo trình (như `"Chuyển sang EVU-B2"`, `"Chuyển sang lộ trình chính"`) mà không ghi đè tiến độ của nhau; lệnh `"Tiếp tục bài hôm qua"` tự động khôi phục bài học đang dở (`unfinished_lesson`) cùng danh sách bài tập còn chờ.
- **Định tuyến 6 nhóm lệnh tự nhiên cốt lõi:**
  - `"Học từ vựng"`: Tự động ưu tiên ôn từ đến hạn (`due_reviews`), khôi phục bài dở hoặc chọn Unit tiếp theo trên lộ trình đang hoạt động.
  - `"Học collocation"`: Tự động chọn bài học tiếp theo trong `ECI-INT` / `ECI-ADV` (hoặc theo chủ đề).
  - `"Học paraphrase"`: Tự động chọn chuyên đề tiếp theo trong `NB-PARA` (hoặc theo chủ đề).
  - `"Học theo chủ đề"`: Truy xuất cụm chủ đề đa nguồn (tự động chọn chủ đề có lỗ hổng hoặc chưa học nếu người học không chỉ định tên).
  - `"Xem tiến độ"`: Thống kê nhật ký từ vựng (Level 0–3, Stage 0–5, số từ đến hạn) và tiến độ từng đầu sách.
  - `"Xem lộ trình"`: Hiển thị trục chính (`IVU-60` -> `IVU-65`), các luồng bổ trợ và bước học gợi ý kế tiếp.

---

## 5. KẾT QUẢ KIỂM THỬ VÀ HỒI QUY (TEST & REGRESSION SUITE)

- **Kiểm thử phân hệ Từ vựng (`tests/test_vocabulary_kb.py`):**
  - Chạy chế độ CI tiêu chuẩn (không có PDF riêng tư): **9/9 passed in 0.23s** (100% Synthetic fixtures: bao gồm toàn bộ hồi quy cho 4 defects mới, Adaptive Roadmap, chuyển luồng sách và khôi phục bài dở trong hội thoại mới).
  - Chạy chế độ Acceptance với cờ `--corpus`: **13 passed in 25.34s** (Kiểm kê 8 sách, 433 unit index, bóc tách Family A/B/C với composite ID, SHA-256 verification và On-Demand Enrichment trên `ECI-INT-U030`).
- **Kiểm thử hồi quy toàn bộ repository:**
  ```bash
  ./.venv/bin/python -m pytest -q tests/
  ```
  **Kết quả:** `241 passed, 14 skipped in 23.23s` (100% Đạt, zero failures).
- **Kiểm tra nguyên tắc và dữ liệu:**
  - `./.venv/bin/python scripts/build_principles_index.py --check`: Hợp lệ 7 atomic principles; index up to date.
  - `./.venv/bin/python scripts/validate_data.py`: Hợp lệ.
- **Bảo mật và Quyền riêng tư:**
  - `git status` xác nhận không có bất kỳ tệp dữ liệu cá nhân hay PDF bản quyền nào thuộc `private/` bị đưa vào Git staging.

---

## 6. QUYẾT ĐỊNH NGHIỆM THU

### **FINAL APPROVAL: ALL TARGETED DEFECTS & ADAPTIVE ROADMAP VERIFIED — READY FOR MERGE**

Toàn bộ yêu cầu kỹ thuật và các lỗi xác nhận đã được khắc phục hoàn chỉnh trên kiến trúc sẵn có:
1. Đã hoàn thiện Adaptive Vocabulary Roadmap & Progress Navigation với đầy đủ 6 nhóm lệnh tự nhiên, chuyển đổi luồng giáo trình độc lập và khôi phục bài học dở trong hội thoại mới.
2. Đã sửa dứt điểm lỗi ôn tập sớm, lỗi vô hiệu hóa cache thiếu SHA-256, lỗi cache rỗng chặn làm giàu từ vựng và lỗi gán nhầm xuất xứ giáo trình cho mục từ không khớp.
3. Đã khôi phục hoàn chỉnh Hợp đồng Tiến độ PR #10 và bảo đảm tính lũy tích, bảo mật bản quyền tuyệt đối.
