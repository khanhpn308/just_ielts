"""Vocabulary Knowledge Base: Lexical Data Model, Storage, Indexing, and Selective Retrieval."""

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from harness.config import REPO_ROOT
from harness.vocabulary.inventory import VOCAB_KB_DIR, VOCAB_RAW_DIR
from harness.vocabulary.parser import FamilyAParser, FamilyBParser, FamilyCParser, save_parsed_unit

KB_UNITS_DIR = VOCAB_KB_DIR / "units"
KB_VOCAB_FILE = VOCAB_KB_DIR / "vocabulary.jsonl"
KB_COLLOCATIONS_FILE = VOCAB_KB_DIR / "collocations.jsonl"
KB_PARAPHRASES_FILE = VOCAB_KB_DIR / "paraphrases.jsonl"
KB_EXERCISES_FILE = VOCAB_KB_DIR / "exercises.jsonl"
KB_ANSWER_KEYS_FILE = VOCAB_KB_DIR / "answer_keys.jsonl"
KB_LEXICAL_INDEX_FILE = VOCAB_KB_DIR / "lexical_index.json"


def normalize_expression(expr: str) -> str:
    """Normalizes expression: NFKC, lowercase, collapse whitespace, strip trailing punctuation."""
    import unicodedata
    norm = unicodedata.normalize("NFKC", expr).strip().lower()
    norm = re.sub(r"[.,;:!?]+$", "", norm).strip()
    return re.sub(r"\s+", " ", norm)


def build_entry_key(expression: str, pos: str, sense_key: str) -> str:
    """Creates pipe-separated canonical entry key: expr|pos|sense."""
    def escape_pipe(s: str) -> str:
        return s.replace("%", "%25").replace("|", "%7C")
    return f"{escape_pipe(normalize_expression(expression))}|{escape_pipe(pos.strip().lower())}|{escape_pipe(sense_key.strip().lower())}"


# Verified core Education pilot vocabulary entries
EDUCATION_PILOT_VOCABULARY: List[Dict[str, Any]] = [
    {
        "item_id": "VOC-EDU-00001",
        "expression": "cram",
        "lemma": "cram",
        "pos": "verb",
        "sense_key": "study intensively before exam",
        "us_ipa": "/kræm/",
        "uk_ipa": "/kræm/",
        "meaning_en": "to study very hard and intensively over a short period just before an examination",
        "meaning_vi": "học nhồi nhét (học dồn dập trong thời gian ngắn trước kỳ thi)",
        "contextual_meaning": "Before an exam, some students cram for it instead of studying regularly.",
        "cefr_level": "C1",
        "grammar_patterns": ["cram for an exam", "cram sth into sth"],
        "countability": None,
        "register": "informal/academic informal",
        "connotation": "slightly negative (ineffective long-term retention compared to distributed practice)",
        "common_mistakes": "Do not say 'cram an exam'; use 'cram for an exam'.",
        "word_family": {"noun": "cramming", "verb": "cram"},
        "collocations": ["cram for an exam", "cram for a test", "last-minute cramming"],
        "synonyms": ["swot"],
        "contextual_paraphrases": ["revise intensively at the last minute", "study under extreme time pressure"],
        "sources": [
            {
                "source_id": "EVU-ADV",
                "unit_key": "EVU-ADV-U001",
                "unit_title": "Cramming for success: study and academic work",
                "physical_page": 10,
                "example_sentence": "Before an exam, some students cram for it.",
                "provenance": "authoritative_textbook",
            }
        ],
        "topics": ["education_and_learning"],
        "language_functions": ["definition_and_explanation"],
        "learning_priority": "high",
        "productive_target": True,
    },
    {
        "item_id": "VOC-EDU-00002",
        "expression": "rote learning",
        "lemma": "rote learning",
        "pos": "noun",
        "sense_key": "mechanical memorisation",
        "us_ipa": "/ˈroʊt ˌlɝː.nɪŋ/",
        "uk_ipa": "/ˈrəʊt ˌlɜː.nɪŋ/",
        "meaning_en": "learning something in order to be able to repeat it from memory, rather than to understand it",
        "meaning_vi": "học vẹt (học thuộc lòng một cách máy móc không cần hiểu bản chất)",
        "contextual_meaning": "Rote learning is not sufficient for higher-level academic subjects requiring critical thinking.",
        "cefr_level": "C1",
        "grammar_patterns": ["learn by rote", "rely on rote learning"],
        "countability": "uncountable",
        "register": "academic",
        "connotation": "negative in academic contexts",
        "common_mistakes": "Say 'learn by rote' or 'rote learning', not 'by rote learning'.",
        "word_family": {"phrase": "by rote"},
        "collocations": ["rely on rote learning", "discourage rote learning", "traditional rote learning"],
        "synonyms": ["mechanical memorisation"],
        "contextual_paraphrases": ["memorising without deep comprehension", "learning off by heart mechanically"],
        "sources": [
            {
                "source_id": "EVU-ADV",
                "unit_key": "EVU-ADV-U001",
                "unit_title": "Cramming for success: study and academic work",
                "physical_page": 10,
                "example_sentence": "Rote-learning is not sufficient for most subjects.",
                "provenance": "authoritative_textbook",
            }
        ],
        "topics": ["education_and_learning"],
        "language_functions": ["evaluation", "comparison_and_contrast"],
        "learning_priority": "high",
        "productive_target": True,
    },
    {
        "item_id": "VOC-EDU-00003",
        "expression": "acquire knowledge",
        "lemma": "acquire knowledge",
        "pos": "phrase",
        "sense_key": "gain knowledge through learning",
        "us_ipa": "/əˈkwaɪr ˈnɑː.lɪdʒ/",
        "uk_ipa": "/əˈkwaɪər ˈnɒl.ɪdʒ/",
        "meaning_en": "to gain or develop understanding and skills through experience or study",
        "meaning_vi": "tiếp thu / tích lũy kiến thức qua học tập và trải nghiệm",
        "contextual_meaning": "Students should acquire knowledge of academic conventions early in their degree.",
        "cefr_level": "B2",
        "grammar_patterns": ["acquire knowledge of sth", "acquire in-depth knowledge"],
        "countability": "uncountable",
        "register": "academic formal",
        "connotation": "positive / formal",
        "common_mistakes": "In IVU-65, Pauline Cullen highlights: use 'acquire knowledge of [subject]', NOT 'get the knowledge' or 'knowledge about/for [classical music]'. (Note: 'knowledge about' is acceptable in general descriptive contexts like 'knowledge about the world', but before specific academic subjects, 'knowledge of' is standard).",
        "word_family": {"verb": "acquire", "noun": "acquisition", "adjective": "acquired"},
        "collocations": ["acquire extensive knowledge", "acquire specialist knowledge", "acquire firsthand knowledge"],
        "synonyms": ["gain knowledge", "obtain knowledge"],
        "contextual_paraphrases": ["broaden one's knowledge base", "develop expertise in a discipline"],
        "sources": [
            {
                "source_id": "IVU-65",
                "unit_key": "IVU-65-U005",
                "unit_title": "Striving to achieve",
                "printed_page": 26,
                "physical_page": 29,
                "section": "1.4",
                "example_sentence": "Visitors should acquire knowledge of the local customs. (NOT get the knowledge)",
                "provenance": "authoritative_textbook",
            }
        ],
        "topics": ["education_and_learning"],
        "language_functions": ["register", "definition_and_explanation"],
        "learning_priority": "high",
        "productive_target": True,
    },
    {
        "item_id": "VOC-EDU-00004",
        "expression": "prior knowledge",
        "lemma": "prior knowledge",
        "pos": "noun",
        "sense_key": "knowledge before new learning",
        "us_ipa": "/ˈpraɪ.ɚ ˈnɑː.lɪdʒ/",
        "uk_ipa": "/ˈpraɪ.ər ˈnɒl.ɪdʒ/",
        "meaning_en": "information or understanding that you already possess before taking a course or studying a topic",
        "meaning_vi": "kiến thức có trước / kiến thức nền tảng đã tích lũy từ trước",
        "contextual_meaning": "The introductory course assumes no prior knowledge of programming.",
        "cefr_level": "B2",
        "grammar_patterns": ["no prior knowledge is required", "build on prior knowledge"],
        "countability": "uncountable",
        "register": "academic",
        "connotation": "neutral",
        "common_mistakes": "Knowledge is uncountable: do not say 'a prior knowledge'.",
        "word_family": {"adjective": "prior"},
        "collocations": ["require prior knowledge", "assume prior knowledge", "activate prior knowledge"],
        "synonyms": ["background knowledge", "pre-existing knowledge"],
        "contextual_paraphrases": ["existing familiarity with the subject", "prerequisite understanding"],
        "sources": [
            {
                "source_id": "IVU-65",
                "unit_key": "IVU-65-U005",
                "unit_title": "Striving to achieve",
                "physical_page": 29,
                "example_sentence": "The Spanish course is for absolute beginners so no prior knowledge is required.",
                "provenance": "authoritative_textbook",
            }
        ],
        "topics": ["education_and_learning"],
        "language_functions": ["definition_and_explanation"],
        "learning_priority": "high",
        "productive_target": True,
    },
    {
        "item_id": "VOC-EDU-00005",
        "expression": "curriculum",
        "lemma": "curriculum",
        "pos": "noun",
        "sense_key": "educational course of study",
        "us_ipa": "/kəˈrɪk.jə.ləm/",
        "uk_ipa": "/kəˈrɪk.jə.ləm/",
        "meaning_en": "the subjects comprising a course of study in a school or college",
        "meaning_vi": "chương trình giảng dạy / khung chương trình học",
        "contextual_meaning": "Schools are adapting their national curriculum to incorporate digital literacy.",
        "cefr_level": "B2",
        "grammar_patterns": ["on the curriculum", "in the curriculum"],
        "countability": "countable (plural: curricula or curriculums)",
        "register": "academic / institutional",
        "connotation": "neutral",
        "common_mistakes": "Plural is often 'curricula', not 'curriculums' in formal academic writing.",
        "word_family": {"adjective": "extracurricular", "noun": "curriculum"},
        "collocations": ["national curriculum", "core curriculum", "broad curriculum", "extracurricular activities"],
        "synonyms": ["syllabus", "course of study"],
        "contextual_paraphrases": ["academic programme", "educational syllabus"],
        "sources": [
            {
                "source_id": "EVU-B2",
                "unit_key": "EVU-B2-U014",
                "unit_title": "Education",
                "physical_page": 35,
                "example_sentence": "The school curriculum includes both academic and vocational subjects.",
                "provenance": "authoritative_textbook",
            }
        ],
        "topics": ["education_and_learning"],
        "language_functions": ["classification"],
        "learning_priority": "high",
        "productive_target": True,
    },
    {
        "item_id": "VOC-EDU-00006",
        "expression": "compulsory",
        "lemma": "compulsory",
        "pos": "adjective",
        "sense_key": "mandatory by regulation",
        "us_ipa": "/kəmˈpʌl.sɚ.i/",
        "uk_ipa": "/kəmˈpʌl.sər.i/",
        "meaning_en": "required by law or a rule; obligatory",
        "meaning_vi": "bắt buộc (theo luật định hoặc quy định nhà trường)",
        "contextual_meaning": "Primary and secondary schooling is compulsory for children between the ages of 5 and 16.",
        "cefr_level": "B2",
        "grammar_patterns": ["compulsory for sb", "compulsory education"],
        "countability": None,
        "register": "formal / legal / academic",
        "connotation": "neutral / restrictive",
        "common_mistakes": "Do not confuse compulsory (obligatory) with compulsive (psychological urge, e.g. compulsive gambling).",
        "word_family": {"noun": "compulsion", "adjective": "compulsory", "adverb": "compulsorily"},
        "collocations": ["compulsory education", "compulsory subject", "compulsory attendance", "make sth compulsory"],
        "synonyms": ["mandatory", "obligatory"],
        "contextual_paraphrases": ["statutorily required", "non-optional"],
        "sources": [
            {
                "source_id": "EVU-B2",
                "unit_key": "EVU-B2-U014",
                "unit_title": "Education",
                "physical_page": 35,
                "example_sentence": "In the UK, education is compulsory between the ages of 5 and 16.",
                "provenance": "authoritative_textbook",
            }
        ],
        "topics": ["education_and_learning", "crime_and_law"],
        "language_functions": ["evaluation", "definition_and_explanation"],
        "learning_priority": "high",
        "productive_target": True,
    },
    {
        "item_id": "VOC-EDU-00007",
        "expression": "vocational",
        "lemma": "vocational",
        "pos": "adjective",
        "sense_key": "relating to career practical skills",
        "us_ipa": "/voʊˈkeɪ.ʃən.əl/",
        "uk_ipa": "/vəʊˈkeɪ.ʃən.əl/",
        "meaning_en": "providing skills and education that prepare you for a job or career",
        "meaning_vi": "thuộc về học nghề / đào tạo kỹ năng nghề nghiệp thực hành",
        "contextual_meaning": "Governments are investing heavily in vocational courses to tackle youth unemployment.",
        "cefr_level": "B2",
        "grammar_patterns": ["vocational training", "vocational qualification"],
        "countability": None,
        "register": "academic / policy",
        "connotation": "positive / practical",
        "common_mistakes": "Contrast with 'academic' (theoretical knowledge).",
        "word_family": {"noun": "vocation", "adjective": "vocational"},
        "collocations": ["vocational training", "vocational course", "vocational education", "vocational skills"],
        "synonyms": ["career-oriented", "job-specific"],
        "contextual_paraphrases": ["hands-on skills training", "non-academic career preparation"],
        "sources": [
            {
                "source_id": "IVU-65",
                "unit_key": "IVU-65-U005",
                "unit_title": "Striving to achieve",
                "physical_page": 31,
                "example_sentence": "You can earn a good living by taking a vocational course.",
                "provenance": "authoritative_textbook",
            }
        ],
        "topics": ["education_and_learning", "work_and_careers"],
        "language_functions": ["comparison_and_contrast", "classification"],
        "learning_priority": "high",
        "productive_target": True,
    },
    {
        "item_id": "VOC-EDU-00008",
        "expression": "continuous assessment",
        "lemma": "continuous assessment",
        "pos": "noun",
        "sense_key": "periodic progressive evaluation",
        "us_ipa": "/kənˈtɪn.ju.əs əˈses.mənt/",
        "uk_ipa": "/kənˈtɪn.ju.əs əˈses.mənt/",
        "meaning_en": "a system of giving marks on the basis of school or university work done throughout the term rather than on the result of one final examination",
        "meaning_vi": "đánh giá quá trình (chấm điểm định kỳ dựa trên tiểu luận và bài tập suốt khóa học thay vì thi một lần)",
        "contextual_meaning": "Grading is based on 50% continuous assessment and 50% final exam.",
        "cefr_level": "B2",
        "grammar_patterns": ["based on continuous assessment"],
        "countability": "uncountable",
        "register": "academic",
        "connotation": "positive (promotes consistent effort)",
        "common_mistakes": "Do not confuse continuous (unbroken over time) with continual (repeated frequently).",
        "word_family": {"verb": "assess", "noun": "assessment", "adjective": "continuous"},
        "collocations": ["system of continuous assessment", "combine continuous assessment with exams"],
        "synonyms": ["formative assessment", "ongoing evaluation"],
        "contextual_paraphrases": ["coursework-based evaluation", "ongoing performance tracking"],
        "sources": [
            {
                "source_id": "EVU-B2",
                "unit_key": "EVU-B2-U014",
                "unit_title": "Education",
                "physical_page": 35,
                "example_sentence": "Marks are given for coursework and continuous assessment throughout the year.",
                "provenance": "authoritative_textbook",
            }
        ],
        "topics": ["education_and_learning"],
        "language_functions": ["evaluation", "comparison_and_contrast"],
        "learning_priority": "high",
        "productive_target": True,
    },
    {
        "item_id": "VOC-EDU-00009",
        "expression": "secure a place",
        "lemma": "secure a place",
        "pos": "phrase",
        "sense_key": "win admission to university",
        "us_ipa": "/səˈkjʊr ə pleɪs/",
        "uk_ipa": "/sɪˈkjʊər ə pleɪs/",
        "meaning_en": "to successfully obtain admission or an offer to study at a competitive institution",
        "meaning_vi": "giành được một suất trúng tuyển (vào trường đại học/ngành học)",
        "contextual_meaning": "She worked diligently to secure a place at a top-tier medical school.",
        "cefr_level": "C1",
        "grammar_patterns": ["secure a place at university", "secure a place to read [subject]"],
        "countability": None,
        "register": "academic formal",
        "connotation": "achievement / competitive success",
        "common_mistakes": "In British academic English, 'read' means 'study': 'secure a place to read English Literature'.",
        "word_family": {"adjective": "secure", "verb": "secure", "noun": "security"},
        "collocations": ["secure a university place", "secure a place at Oxford", "secure a funded place"],
        "synonyms": ["gain admission", "win a place"],
        "contextual_paraphrases": ["be accepted into university", "earn an offer of admission"],
        "sources": [
            {
                "source_id": "ECI-ADV",
                "unit_key": "ECI-ADV-U017",
                "unit_title": "Student life",
                "physical_page": 42,
                "example_sentence": "Amelia was fortunate enough to secure a place at Cambridge University to read English Literature.",
                "provenance": "authoritative_textbook",
            }
        ],
        "topics": ["education_and_learning"],
        "language_functions": ["evaluation", "academic_reporting"],
        "learning_priority": "high",
        "productive_target": True,
    },
    {
        "item_id": "VOC-EDU-00010",
        "expression": "higher education",
        "lemma": "higher education",
        "pos": "noun",
        "sense_key": "tertiary level education",
        "us_ipa": "/ˌhaɪ.ɚ edʒ.əˈkeɪ.ʃən/",
        "uk_ipa": "/ˌhaɪ.ər edʒ.ʊˈkeɪ.ʃən/",
        "meaning_en": "education at colleges or universities, typically beyond secondary school",
        "meaning_vi": "giáo dục đại học và sau đại học (bậc cao đẳng, đại học)",
        "contextual_meaning": "Increasing numbers of secondary school graduates are opting to enter higher education.",
        "cefr_level": "B1",
        "grammar_patterns": ["in higher education", "enter higher education", "pursue higher education"],
        "countability": "uncountable",
        "register": "academic",
        "connotation": "neutral / aspirational",
        "common_mistakes": "Use 'higher education' or 'tertiary education', not 'high education'.",
        "word_family": {"adjective": "educational", "noun": "education"},
        "collocations": ["enter higher education", "higher education institution", "higher education sector", "access to higher education"],
        "synonyms": ["tertiary education", "university education"],
        "contextual_paraphrases": ["college-level study", "post-secondary education"],
        "sources": [
            {
                "source_id": "NB-PARA",
                "unit_key": "NB-PARA-PRAC-EDU",
                "unit_title": "Practice: Education Paraphrasing",
                "physical_page": 30,
                "example_sentence": "Governments should subsidise higher education to encourage more students to attend university.",
                "provenance": "authoritative_textbook",
            }
        ],
        "topics": ["education_and_learning"],
        "language_functions": ["comparison_and_contrast", "definition_and_explanation"],
        "learning_priority": "high",
        "productive_target": True,
    },
]


def build_knowledge_base():
    """Initializes and builds the integrated Education pilot and core knowledge base files."""
    VOCAB_KB_DIR.mkdir(parents=True, exist_ok=True)
    KB_UNITS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Write vocabulary.jsonl
    lexical_index = {}
    with open(KB_VOCAB_FILE, "w", encoding="utf-8") as f:
        for item in EDUCATION_PILOT_VOCABULARY:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            norm_expr = normalize_expression(item["expression"])
            entry_key = build_entry_key(item["expression"], item["pos"], item["sense_key"])
            if norm_expr not in lexical_index:
                lexical_index[norm_expr] = []
            lexical_index[norm_expr].append({
                "item_id": item["item_id"],
                "entry_key": entry_key,
                "pos": item["pos"],
                "sense_key": item["sense_key"],
                "meaning_vi": item["meaning_vi"],
                "sources": [s["source_id"] for s in item["sources"]],
            })

    # 2. Write lexical_index.json
    with open(KB_LEXICAL_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(lexical_index, f, indent=2, ensure_ascii=False)

    # 3. Write collocations.jsonl
    collocations = [
        {
            "collocation_id": "COL-EDU-00001",
            "expression": "acquire knowledge of",
            "components": ["acquire (v)", "knowledge (n)", "of (prep)"],
            "collocation_type": "verb + noun + preposition",
            "meaning_vi": "tiếp thu / tích lũy kiến thức về lĩnh vực nào đó",
            "context_sentence": "University students must acquire knowledge of rigorous research methodologies.",
            "usage_warning": "In IVU-65, Pauline Cullen highlights: say 'knowledge OF [a subject/discipline]' (e.g. knowledge of classical music), NOT 'knowledge about/for [a field of study]'. Also avoid 'get the knowledge' (use 'acquire/gain knowledge').",
            "sources": [{"source_id": "IVU-65", "unit_key": "IVU-65-U005", "page": 29}],
            "topics": ["education_and_learning"],
        },
        {
            "collocation_id": "COL-EDU-00002",
            "expression": "secure a place at university",
            "components": ["secure (v)", "a place (n)", "at (prep)"],
            "collocation_type": "verb + noun + preposition",
            "meaning_vi": "giành được một suất vào đại học",
            "context_sentence": "Outstanding academic performance helped her secure a place at Oxford.",
            "sources": [{"source_id": "ECI-ADV", "unit_key": "ECI-ADV-U017", "page": 42}],
            "topics": ["education_and_learning"],
        },
        {
            "collocation_id": "COL-EDU-00003",
            "expression": "continuous assessment",
            "components": ["continuous (adj)", "assessment (n)"],
            "collocation_type": "adjective + noun",
            "meaning_vi": "đánh giá quá trình liên tục",
            "context_sentence": "Many educators argue that continuous assessment reflects student progress more accurately than one-off exams.",
            "sources": [{"source_id": "EVU-B2", "unit_key": "EVU-B2-U014", "page": 35}],
            "topics": ["education_and_learning"],
        },
        {
            "collocation_id": "COL-EDU-00004",
            "expression": "cram for an exam",
            "components": ["cram (v)", "for (prep)", "an exam (n)"],
            "collocation_type": "verb + preposition + noun",
            "meaning_vi": "học nhồi nhét trước kỳ thi",
            "context_sentence": "Cramming for an exam rarely leads to long-term memory consolidation.",
            "sources": [{"source_id": "EVU-ADV", "unit_key": "EVU-ADV-U001", "page": 10}],
            "topics": ["education_and_learning"],
        },
    ]
    with open(KB_COLLOCATIONS_FILE, "w", encoding="utf-8") as f:
        for c in collocations:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # 4. Write paraphrases.jsonl
    paraphrases = [
        {
            "paraphrase_id": "PARA-EDU-00001",
            "topic": "education_and_learning",
            "original_expression": "attend university",
            "paraphrase_variants": [
                "pursue higher education",
                "enter tertiary education",
                "enrol in a degree programme",
                "go to college"
            ],
            "meaning_vi": "học đại học / theo đuổi giáo dục bậc cao",
            "nuances": "enter tertiary education is more formal/academic; go to college is common US usage; enrol in a degree programme emphasizes registration.",
            "sources": [{"source_id": "NB-PARA", "unit_key": "NB-PARA-PRAC-EDU", "page": 30}],
        },
        {
            "paraphrase_id": "PARA-EDU-00002",
            "topic": "education_and_learning",
            "original_expression": "tuition fees",
            "paraphrase_variants": [
                "the cost of university study",
                "tertiary education costs",
                "university fees",
                "academic expenses"
            ],
            "meaning_vi": "học phí / chi phí học đại học",
            "nuances": "tuition fees specifically refers to fees charged for instruction; education costs encompasses living expenses and materials.",
            "sources": [{"source_id": "NB-PARA", "unit_key": "NB-PARA-PRAC-EDU", "page": 30}],
        },
        {
            "paraphrase_id": "PARA-EDU-00003",
            "topic": "education_and_learning",
            "original_expression": "students who have graduated",
            "paraphrase_variants": [
                "university graduates",
                "degree holders",
                "college alumni"
            ],
            "meaning_vi": "sinh viên tốt nghiệp / người có bằng đại học",
            "nuances": "degree holders emphasizes the qualification held; graduates emphasizes completion of study.",
            "sources": [{"source_id": "NB-PARA", "unit_key": "NB-PARA-PRAC-EDU", "page": 31}],
        },
    ]
    with open(KB_PARAPHRASES_FILE, "w", encoding="utf-8") as f:
        for p in paraphrases:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    # 5. Write exercises.jsonl and answer_keys.jsonl
    exercises = [
        {
            "exercise_id": "EX-EVU-B2-14.1",
            "source_id": "EVU-B2",
            "unit_key": "EVU-B2-U014",
            "exercise_number": "14.1",
            "exercise_type": "gap_fill",
            "printed_page": 35,
            "physical_page": 36,
            "origin_type": "original_textbook_exercise",
            "instructions": "Fill the gaps in this life story of a British woman.",
            "question_text": "Amy first went to her local 1 primary school at the age of five. The year before that she attended a 2 _________ , but her parents didn't send her to a 3 _________ when she was very small. When Amy was ready to go on to secondary school, she passed a special exam and so gained 4 _________ to her local 5 _________ school. Her friends didn't do that exam. Like most children, they went to a 6 _________ school. Only a few children from very rich families go to famous 7 _________ schools and Amy only knew one girl from her class at primary school who did. At the age of 16, Amy went on to 8 _________ , where she is currently studying English, History and Maths. Her ambition is to go on to 9 _________ and become a teacher.",
            "acceptable_answers": [
                "2 nursery school",
                "3 crèche",
                "4 admission",
                "5 grammar",
                "6 comprehensive",
                "7 public",
                "8 sixth-form college",
                "9 higher education / university"
            ],
            "hidden_key": True,
        },
        {
            "exercise_id": "EX-EVU-ADV-1.1",
            "source_id": "EVU-ADV",
            "unit_key": "EVU-ADV-U001",
            "exercise_number": "1.1",
            "exercise_type": "error_correction",
            "printed_page": 9,
            "physical_page": 11,
            "origin_type": "original_textbook_exercise",
            "instructions": "Correct the wrong usage of words to do with written work in these sentences.",
            "question_text": "1 His PhD assignment was 90,000 words long and was on the history of US place names.\n2 Little Martha did her first dissertation in school today. It was called 'My family'.\n3 We have to hand in an essay at the end of the course. It can consist of up to five different pieces of work.\n4 The teacher gave us the title of this week's project today. We have to write 1,000 words on the topic of 'If I ruled the world' and hand it in next Monday.\n5 At the end of this course, you have to do a 5,000-word thesis which will be assessed, and the grade will contribute to your final degree.\n6 I think I'll do a study of people's personal banking habits for my MSc composition. It has to be about 12,000 words.\n7 I've chosen to do the portfolio instead of the two exams, because I like to do one single piece of work where I can research something that interests me personally.",
            "acceptable_answers": [
                "1 thesis",
                "2 composition",
                "3 portfolio",
                "4 essay",
                "5 assignment",
                "6 dissertation",
                "7 project"
            ],
            "hidden_key": True,
        },
        {
            "exercise_id": "EX-IVU-65-1.4",
            "source_id": "IVU-65",
            "unit_key": "IVU-65-U005",
            "exercise_number": "1.4",
            "exercise_type": "collocation_completion",
            "printed_page": 26,
            "physical_page": 29,
            "origin_type": "original_textbook_exercise",
            "instructions": "All of the words in the box collocate with the word knowledge. Complete the sentences with the correct combination with the word knowledge.",
            "question_text": "1 Thanks to a few classes at university, I have ______ Russian.\n2 Since the news report, details of the deal are now ______.\n3 Being a reporter requires ______ international affairs.\n4 Visiting the country did so much to ______ the language and people.\n5 The course is for beginners so no ______ is required.",
            "acceptable_answers": [
                "1 a limited knowledge of",
                "2 common knowledge",
                "3 a specialist knowledge of / a detailed knowledge of / an in-depth knowledge of",
                "4 broaden my / (his etc.) knowledge of",
                "5 prior knowledge"
            ],
            "hidden_key": True,
        },
        {
            "exercise_id": "EX-ECI-ADV-17.1",
            "source_id": "ECI-ADV",
            "unit_key": "ECI-ADV-U017",
            "exercise_number": "17.1",
            "exercise_type": "short_answer",
            "printed_page": 39,
            "physical_page": 43,
            "origin_type": "original_textbook_exercise",
            "instructions": "Answer the questions using collocations from Section A.",
            "question_text": "1 What happens when you successfully complete a degree course?\n2 What do you call students who are in their thirties or older?\n3 What are, for example, Harvard, the Sorbonne and Cambridge University?\n4 What kind of people teach at Harvard, the Sorbonne and Cambridge University?\n5 What do you call children who are particularly intelligent or have special talents?\n6 What do you call students whose marks are always excellent?",
            "acceptable_answers": [
                "1 You graduate from university.",
                "2 mature students",
                "3 (prestigious) seats of learning",
                "4 distinguished scholars or leading authorities (in their fields)",
                "5 gifted children",
                "6 straight-A students"
            ],
            "hidden_key": True,
        },
        {
            "exercise_id": "EX-NB-PARA-EDU-1",
            "source_id": "NB-PARA",
            "unit_key": "NB-PARA-PRAC-EDU",
            "exercise_number": "EDU-1",
            "exercise_type": "paraphrase_transformation",
            "printed_page": 30,
            "physical_page": 30,
            "origin_type": "tutor_transfer_exercise_grounded_in_source",
            "instructions": "[Tutor Transfer Exercise grounded in NB-PARA Education paraphrase pairs p. 30] Paraphrase the following sentence using academic vocabulary: 'More students are going to university these days, but tuition fees are very high.'",
            "question_text": "More students are going to university these days, but tuition fees are very high.",
            "acceptable_answers": [
                "An increasing proportion of young people are pursuing higher education, despite the escalating costs of tertiary study.",
                "A rising number of school-leavers enter tertiary education, although university tuition fees remain substantial."
            ],
            "hidden_key": True,
        },
    ]

    with open(KB_EXERCISES_FILE, "w", encoding="utf-8") as f_ex, open(KB_ANSWER_KEYS_FILE, "w", encoding="utf-8") as f_ak:
        for ex in exercises:
            f_ex.write(json.dumps({k: v for k, v in ex.items() if k != "acceptable_answers"}, ensure_ascii=False) + "\n")
            f_ak.write(json.dumps({
                "exercise_id": ex["exercise_id"],
                "source_id": ex["source_id"],
                "unit_key": ex["unit_key"],
                "acceptable_answers": ex["acceptable_answers"],
                "verification_status": "authoritative_key",
            }, ensure_ascii=False) + "\n")

    print(f"Knowledge Base built: {len(EDUCATION_PILOT_VOCABULARY)} vocab items, {len(collocations)} collocations, {len(paraphrases)} paraphrases, {len(exercises)} exercises.")


def get_unit_details(unit_key: str) -> Optional[Dict[str, Any]]:
    """Retrieves full details for a unit, parsing and caching on demand if not yet cached."""
    index_file = VOCAB_KB_DIR / "unit_index.json"
    if not index_file.exists():
        return None
    with open(index_file, "r", encoding="utf-8") as f:
        unit_idx = json.load(f)

    unit_info = unit_idx.get(unit_key)
    if not unit_info:
        # Check source + number e.g. "EVU-B2-14"
        for k, v in unit_idx.items():
            if k.lower() == unit_key.lower():
                unit_info = v
                unit_key = k
                break
    if not unit_info:
        return None

    source_id = unit_info["source_id"]
    cached_path = KB_UNITS_DIR / source_id / f"{unit_key}.json"
    if cached_path.exists():
        with open(cached_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # Parse on demand
    family = unit_info.get("source_id")
    if source_id in ["EVU-B2", "EVU-ADV", "ECI-INT", "ECI-ADV", "AVU"]:
        parser = FamilyAParser(source_id)
        parsed = parser.parse_unit(unit_info)
    elif source_id in ["IVU-60", "IVU-65"]:
        parser = FamilyBParser(source_id)
        parsed = parser.parse_unit(unit_info)
    elif source_id == "NB-PARA":
        parser = FamilyCParser()
        parsed = parser.parse_section(unit_info)
    else:
        return unit_info

    save_parsed_unit(parsed)
    return parsed


def query_vocabulary_by_topic(topic_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieves vocabulary items matching a topic from vocabulary.jsonl."""
    if not KB_VOCAB_FILE.exists():
        build_knowledge_base()

    results = []
    with open(KB_VOCAB_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            if topic_id in item.get("topics", []):
                results.append(item)
                if len(results) >= limit:
                    break
    return results


def query_collocations_by_topic(topic_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Retrieves collocations matching a topic from collocations.jsonl."""
    if not KB_COLLOCATIONS_FILE.exists():
        build_knowledge_base()

    results = []
    with open(KB_COLLOCATIONS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            if topic_id in item.get("topics", []):
                results.append(item)
                if len(results) >= limit:
                    break
    return results


def query_paraphrases_by_topic(topic_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Retrieves paraphrases matching a topic from paraphrases.jsonl."""
    if not KB_PARAPHRASES_FILE.exists():
        build_knowledge_base()

    results = []
    with open(KB_PARAPHRASES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("topic") == topic_id or topic_id in item.get("topics", []):
                results.append(item)
                if len(results) >= limit:
                    break
    return results


def get_exercise_with_hidden_answer(exercise_id: str) -> Optional[Tuple[Dict[str, Any], Optional[List[str]]]]:
    """Retrieves an exercise and returns (exercise_data_without_answers, acceptable_answers)."""
    if not KB_EXERCISES_FILE.exists():
        build_knowledge_base()

    ex_found = None
    with open(KB_EXERCISES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            ex = json.loads(line)
            if ex["exercise_id"] == exercise_id:
                ex_found = ex
                break

    if not ex_found:
        return None

    answers = None
    if KB_ANSWER_KEYS_FILE.exists():
        with open(KB_ANSWER_KEYS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                ak = json.loads(line)
                if ak["exercise_id"] == exercise_id:
                    answers = ak["acceptable_answers"]
                    break

    return ex_found, answers


if __name__ == "__main__":
    build_knowledge_base()
