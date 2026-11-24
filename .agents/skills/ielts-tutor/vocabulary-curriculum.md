# IELTS Vocabulary Curriculum & Knowledge Base Navigation

Tài liệu định hướng chương trình từ vựng IELTS tích hợp từ 8 bộ giáo trình chuẩn hóa tại `private/knowledge/vocabulary/`.

---

## 1. Cấu trúc Chương trình (Curriculum Architecture)

### 1.1. Giáo trình Cốt lõi (Primary Curriculum Backbone)
Dựa trên 2 bộ giáo trình của Pauline Cullen làm khung sườn tiến độ:
1. **IVU-60 (Cambridge Vocabulary for IELTS - Band 6.0):** 25 Unit + 5 Review Tests. Xây dựng nền tảng từ vựng theo chủ đề thường gặp trong đề thi thật.
2. **IVU-65 (Cambridge Vocabulary for IELTS Advanced - Band 6.5+):** 25 Unit. Nâng cao độ chính xác học thuật, bẫy từ vựng (Error Warnings), collocation và kỹ năng diễn đạt học thuật.

### 1.2. Nguồn Bổ trợ Chuyên sâu (Supporting Knowledge Sources)
- **EVU-B2 (English Vocabulary in Use Upper-intermediate - 101 Units):** Củng cố nền tảng từ vựng chung theo chủ điểm đời sống và xã hội.
- **EVU-ADV (English Vocabulary in Use Advanced - 100 Units):** Mở rộng trường từ vựng nâng cao, sắc thái ngữ nghĩa tinh tế và văn phong học thuật.
- **ECI-INT (English Collocations in Use Intermediate - 60 Units):** Nền tảng kết hợp từ tự nhiên theo ngữ cảnh.
- **ECI-ADV (English Collocations in Use Advanced - 60 Units):** Nâng cao register, collocation học thuật và diễn đạt tự nhiên chuẩn bản xứ.
- **AVU (Academic Vocabulary in Use - Unit 0 + 50 Units):** Từ vựng chuyên dụng cho bài báo cáo khoa học, phân tích số liệu, nguyên nhân - hệ quả, trích dẫn học thuật.
- **NB-PARA (How to Paraphrase in the IELTS Test - 10 Sections):** Chiến lược biến đổi câu, mẫu paraphrase Task 1, Task 2 và 5 chuyên đề thực hành trọng điểm.

### 1.3. Nguồn Vận dụng Thực tế (Applied Practice)
- Bài đọc Reading (`PASSAGE-<ID>.json`).
- Bài nghe Listening (`TEST-IELTS-...-LIS.json`).
- Đề Writing Task 1, Task 2 và bài mẫu.
- Bộ đề Speaking Part 1, 2, 3.
- Lỗi sai thực tế đã ghi nhận trong quá trình học.

---

## 2. Hệ thống Chủ đề (20 Shared Topics)

| Topic ID | Tên chủ đề | Unit tiêu biểu liên kết đa nguồn |
|---|---|---|
| `education_and_learning` | Education and Learning | IVU-60 U5, IVU-65 U5, EVU-B2 U14-U15, EVU-ADV U1-U2, ECI-ADV U17, AVU U0/U20, NB-PARA EDU |
| `work_and_careers` | Work and Careers | IVU-60 U17, IVU-65 U5/U17, EVU-ADV U3-U7, ECI-INT U30, NB-PARA WORK |
| `business_and_economy` | Business and Economy | IVU-60 U17, IVU-65 U6/U17, EVU-ADV U34, ECI-INT U31, AVU U23 |
| `environment_and_climate` | Environment and Climate | IVU-60 U15-U16, IVU-65 U15-U16, EVU-ADV U28-U33, NB-PARA ENV |
| `science_and_technology` | Science and Technology | IVU-60 U11-U12, IVU-65 U4/U10-U11, EVU-ADV U44-U48 |
| `health_and_medicine` | Health and Medicine | IVU-60 U2-U3, IVU-65 U4, EVU-ADV U41-U43, ECI-INT U26 |
| `transport_and_travel` | Transport and Travel | IVU-60 U7, IVU-65 U7, EVU-B2 U37-U38, ECI-INT U14, NB-PARA TRANS |
| `crime_and_law` | Crime and Law | IVU-60 U18, IVU-65 U18, EVU-ADV U35, ECI-INT U34-U35, NB-PARA CRIME |
| `government_and_politics` | Government and Politics | IVU-65 U8, EVU-ADV U35-U36, ECI-INT U38 |
| `society_and_global_issues`| Society and Global Issues | IVU-60 U13-U14, IVU-65 U3/U8/U14, EVU-ADV U34, ECI-INT U39 |
| `media_and_communication` | Media and Communication | IVU-60 U6/U19, IVU-65 U6/U19, EVU-ADV U49-U52 |
| `people_and_relationships`| People and Relationships | IVU-60 U1, IVU-65 U1/U3, EVU-B2 U7-U10, EVU-ADV U8-U15, ECI-INT U17-U20 |
| `food_and_lifestyle` | Food and Lifestyle | IVU-60 U3-U4, IVU-65 U12/U20, EVU-ADV U23-U24, ECI-INT U21-U22 |
| `culture_and_arts` | Culture and Arts | IVU-60 U20, IVU-65 U20, EVU-ADV U20-U22 |
| `housing_and_urbanisation` | Housing and Urbanisation | IVU-60 U10/U14, IVU-65 U13, EVU-B2 U11, ECI-INT U16/U21 |
| `nature_and_animals` | Nature and Animals | IVU-60 U9, IVU-65 U9/U15, EVU-ADV U32, ECI-INT U15 |
| `academic_language` | Academic Language | AVU U0-U50, IVU-60 U21-U25, IVU-65 U21-U25, ECI-ADV U18, NB-PARA T1/T2 |
| `feelings_and_behaviour` | Feelings and Behaviour | IVU-65 U1, EVU-ADV U13-U14, ECI-INT U17 |
| `sport_and_leisure` | Sport and Leisure | IVU-60 U3-U4, EVU-ADV U16, ECI-INT U25 |
| `abstract_concepts` | Abstract Concepts | IVU-60 U8, IVU-65 U2, EVU-ADV U53-U59, ECI-INT U40-U50 |

---

## 3. Hệ thống Chức năng Ngôn ngữ (Language Functions)

- `cause_and_effect`: Nguyên nhân - hệ quả (AVU U37, IVU-60 U15, ECI-INT U53).
- `comparison_and_contrast`: So sánh và đối chiếu (AVU U46, ECI-INT U10-U11).
- `argumentation`: Xây dựng lập luận và phản biện (AVU U39, IVU-60 U24).
- `agreement_and_disagreement`: Đồng thuận và phản đối (ECI-INT U55).
- `describing_trends`: Mô tả xu hướng số liệu (AVU U35/U48, IVU-60 U23, NB-PARA T1).
- `quantity_and_degree`: Định lượng và mức độ (AVU U7/U33, ECI-INT U46).
- `evaluation`: Đánh giá và bình phẩm (AVU U47, IVU-65 U1).
- `register`: Sắc thái trang trọng/thân mật (AVU Ref 1, ECI-INT U5, ECI-ADV U5).
- `word_formation`: Cấu tạo từ gia đình từ (IVU-60 U21, IVU-65 U21).
- `classification`: Phân loại và chia nhóm (AVU U38).
- `problem_and_solution`: Vấn đề và giải pháp (AVU U44, IVU-60 U14, IVU-65 U14).
- `definition_and_explanation`: Định nghĩa và giải thích (AVU U31).
- `evidence_and_reasoning`: Chứng cứ và suy luận (AVU U42).
- `academic_reporting`: Trích dẫn và báo cáo học thuật (AVU U30, IVU-65 U5).

---

## 4. Quy trình Học Từ vựng Tích hợp (Tutor Workflow)

1. **Nhận diện yêu cầu tự nhiên:**
   - Theo Unit: *"Học IVU-65 Unit 5"*, *"Học EVU-B2 Unit 14"*, *"Học AVU Unit 37"*.
   - Theo Chủ đề đa nguồn: *"Học từ vựng chủ đề Education"*, *"Học Environment kết hợp các nguồn"*.
   - Luyện chuyên sâu: *"Luyện collocation chủ đề Work"*, *"Học paraphrase chủ đề Crime"*.
   - Kiểm tra / Ôn tập: *"Kiểm tra EVU-B2 Unit 14"*, *"Ôn từ vựng hôm nay"*, *"Kiểm tra Unit vừa học"*.
2. **Kiểm tra ôn tập đến hạn (Spaced Review):**
   - Đọc `private/progress/vocabulary.jsonl` (nếu có).
   - Kiểm tra các từ có `next_review_date <= today` trước khi giới thiệu bài mới.
3. **Truy xuất nội dung chọn lọc từ Knowledge Base:**
   - Tra cứu Unit hoặc Topic từ `private/knowledge/vocabulary/unit_index.json` và `topic_index.json`.
   - Nạp nội dung Unit từ `units/<source_id>/<unit_key>.json` hoặc parse on-demand qua `FamilyAParser`/`FamilyBParser`/`FamilyCParser`.
4. **Giảng dạy theo định dạng sư phạm:**
   - Từ vựng trọng tâm (Lemma, Cambridge US IPA, Từ loại).
   - Nghĩa tiếng Việt chuẩn xác và ngữ nghĩa trong ngữ cảnh cụ thể.
   - Collocation tự nhiên (2–4 cụm).
   - Paraphrase học thuật có ghi chú khác biệt về sắc thái/ngữ cảnh.
   - Cảnh báo bẫy dùng sai (Error Warning) nếu có.
   - Ví dụ ngữ cảnh từ giáo trình.
5. **Thực hành Active Recall & Bài tập gốc:**
   - Trích xuất bài tập từ giáo trình gốc (giữ **ẨN ĐÁP ÁN** hoàn toàn).
   - Học viên gửi câu trả lời ngắn -> Chấm bài, đối chiếu đáp án gốc và giải thích.
6. **Vận dụng chủ động (Productive Practice):**
   - Yêu cầu người học tự đặt câu hoặc viết đoạn ngắn ứng dụng từ vào bối cảnh Writing/Speaking mới.
   - Sửa lỗi ngữ pháp, giới từ, kết hợp từ và độ tự nhiên.
7. **Lưu tiến độ & Cập nhật Spaced Repetition:**
   - Hỏi ý kiến người học: *"Bạn có muốn lưu kết quả buổi học vào hồ sơ cá nhân `private/progress/vocabulary.jsonl` không?"*
   - Cập nhật cấp độ nhận biết/vận dụng (Level 0–3) và lịch ôn tập (Stage 0–5) theo quy định tại `vocabulary-learning.md`.
