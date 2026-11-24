"""Builds comprehensive structural Unit Index and Topic Index across all 8 vocabulary textbooks."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pikepdf
import subprocess
import re

from harness.config import REPO_ROOT
from harness.vocabulary.inventory import SOURCE_METADATA_CONFIG, VOCAB_RAW_DIR, VOCAB_KB_DIR
from harness.vocabulary.taxonomy import TOPIC_TAXONOMY, LANGUAGE_FUNCTIONS, classify_topics_by_keywords


# Explicit unit titles and topic mappings for IVU-60
IVU_60_UNITS = [
    {
        "unit": 1, "title": "Growing up", "subtopics": "Relationships, families and early learning",
        "p_start": 10, "p_end": 13, "test_practice": "Listening Part 1",
        "topics": ["people_and_relationships", "education_and_learning"], "functions": ["word_formation"],
    },
    {
        "unit": 2, "title": "Mental and physical development", "subtopics": "The body, the mind",
        "p_start": 14, "p_end": 17, "test_practice": "Speaking Part 2 / GT Writing Task 1",
        "topics": ["health_and_medicine", "feelings_and_behaviour"], "functions": ["describing_trends"],
    },
    {
        "unit": 3, "title": "Keeping fit", "subtopics": "Diet, health and exercise",
        "p_start": 18, "p_end": 21, "test_practice": "GT Reading Section 1",
        "topics": ["health_and_medicine", "food_and_lifestyle", "sport_and_leisure"], "functions": ["problem_and_solution"],
    },
    {
        "unit": 4, "title": "Lifestyles", "subtopics": "Life, leisure",
        "p_start": 22, "p_end": 25, "test_practice": "Listening Part 2",
        "topics": ["food_and_lifestyle", "sport_and_leisure", "people_and_relationships"], "functions": ["comparison_and_contrast"],
    },
    {
        "unit": 5, "title": "Student life", "subtopics": "Study, education, research",
        "p_start": 26, "p_end": 31, "test_practice": "GT Reading Section 2",
        "topics": ["education_and_learning", "academic_language"], "functions": ["academic_reporting", "evidence_and_reasoning"],
    },
    {
        "unit": 6, "title": "Effective communication", "subtopics": "Language, linguistics",
        "p_start": 34, "p_end": 39, "test_practice": "Academic Reading",
        "topics": ["media_and_communication", "academic_language"], "functions": ["definition_and_explanation"],
    },
    {
        "unit": 7, "title": "On the move", "subtopics": "Tourism, travel, transport",
        "p_start": 40, "p_end": 43, "test_practice": "Academic Reading",
        "topics": ["transport_and_travel"], "functions": ["describing_trends"],
    },
    {
        "unit": 8, "title": "Through the ages", "subtopics": "Time, history",
        "p_start": 44, "p_end": 47, "test_practice": "Listening Part 4",
        "topics": ["abstract_concepts", "society_and_global_issues"], "functions": ["comparison_and_contrast"],
    },
    {
        "unit": 9, "title": "The natural world", "subtopics": "Flora and fauna, agriculture",
        "p_start": 48, "p_end": 53, "test_practice": "Academic Reading",
        "topics": ["nature_and_animals", "environment_and_climate"], "functions": ["classification"],
    },
    {
        "unit": 10, "title": "Reaching for the skies", "subtopics": "Space, architecture",
        "p_start": 54, "p_end": 57, "test_practice": "Listening Part 3",
        "topics": ["housing_and_urbanisation", "science_and_technology"], "functions": ["evaluation"],
    },
    {
        "unit": 11, "title": "Design and innovation", "subtopics": "Building, engineering, innovation",
        "p_start": 60, "p_end": 65, "test_practice": "Academic Reading",
        "topics": ["science_and_technology", "housing_and_urbanisation"], "functions": ["problem_and_solution"],
    },
    {
        "unit": 12, "title": "Information technology", "subtopics": "Telecommunications, computers, technology",
        "p_start": 66, "p_end": 69, "test_practice": "Academic Reading",
        "topics": ["science_and_technology", "media_and_communication"], "functions": ["cause_and_effect"],
    },
    {
        "unit": 13, "title": "The modern world", "subtopics": "Globalisation, changing attitudes and trends",
        "p_start": 70, "p_end": 73, "test_practice": "Academic Writing Task 2",
        "topics": ["society_and_global_issues", "business_and_economy"], "functions": ["describing_trends", "argumentation"],
    },
    {
        "unit": 14, "title": "Urbanisation", "subtopics": "Problems and solutions, big city life",
        "p_start": 74, "p_end": 79, "test_practice": "Academic Reading",
        "topics": ["housing_and_urbanisation", "society_and_global_issues"], "functions": ["problem_and_solution", "cause_and_effect"],
    },
    {
        "unit": 15, "title": "The green revolution", "subtopics": "The environment, climate change and pollution",
        "p_start": 80, "p_end": 83, "test_practice": "Academic Reading",
        "topics": ["environment_and_climate"], "functions": ["cause_and_effect", "argumentation"],
    },
    {
        "unit": 16, "title": "The energy crisis", "subtopics": "Natural resources, alternative fuels",
        "p_start": 86, "p_end": 91, "test_practice": "Academic Reading",
        "topics": ["environment_and_climate", "science_and_technology"], "functions": ["problem_and_solution", "evaluation"],
    },
    {
        "unit": 17, "title": "Talking business", "subtopics": "Employment, management and marketing",
        "p_start": 92, "p_end": 95, "test_practice": "GT Writing Task 1 / Academic Writing Task 2",
        "topics": ["business_and_economy", "work_and_careers"], "functions": ["register", "argumentation"],
    },
    {
        "unit": 18, "title": "The law", "subtopics": "Crime, punishment",
        "p_start": 96, "p_end": 99, "test_practice": "GT Writing Task 2",
        "topics": ["crime_and_law", "government_and_politics"], "functions": ["evaluation", "argumentation"],
    },
    {
        "unit": 19, "title": "The media", "subtopics": "The news, fame",
        "p_start": 100, "p_end": 105, "test_practice": "GT Writing Task 1",
        "topics": ["media_and_communication"], "functions": ["register", "academic_reporting"],
    },
    {
        "unit": 20, "title": "The arts", "subtopics": "Art and materials, performing arts",
        "p_start": 106, "p_end": 109, "test_practice": "Academic Reading",
        "topics": ["culture_and_arts"], "functions": ["evaluation", "comparison_and_contrast"],
    },
    {
        "unit": 21, "title": "Language building 1", "subtopics": "Using a dictionary, word families",
        "p_start": 112, "p_end": 115, "test_practice": "Strategy",
        "topics": ["academic_language", "education_and_learning"], "functions": ["word_formation"],
    },
    {
        "unit": 22, "title": "Language building 2", "subtopics": "Learning vocabulary, collocations",
        "p_start": 116, "p_end": 119, "test_practice": "Strategy",
        "topics": ["academic_language", "education_and_learning"], "functions": ["register"],
    },
    {
        "unit": 23, "title": "Academic Writing Task 1", "subtopics": "Data, graphs and tables, diagrams",
        "p_start": 120, "p_end": 123, "test_practice": "Writing Task 1",
        "topics": ["academic_language"], "functions": ["describing_trends", "quantity_and_degree"],
    },
    {
        "unit": 24, "title": "Academic Writing Task 2", "subtopics": "Structuring an essay, connecting ideas",
        "p_start": 124, "p_end": 127, "test_practice": "Writing Task 2",
        "topics": ["academic_language"], "functions": ["argumentation", "cause_and_effect"],
    },
    {
        "unit": 25, "title": "General Training Writing", "subtopics": "Letters, writing an essay",
        "p_start": 128, "p_end": 131, "test_practice": "GT Writing",
        "topics": ["academic_language"], "functions": ["register"],
    },
]

# Explicit unit titles and topic mappings for IVU-65
IVU_65_UNITS = [
    {
        "unit": 1, "title": "Human nature", "subtopics": "Character, psychology",
        "p_start": 11, "p_end": 14, "test_practice": "Listening Part 4",
        "topics": ["people_and_relationships", "feelings_and_behaviour"], "functions": ["word_formation", "evaluation"],
    },
    {
        "unit": 2, "title": "Time for a change", "subtopics": "Time, change",
        "p_start": 15, "p_end": 20, "test_practice": "Reading",
        "topics": ["abstract_concepts"], "functions": ["describing_trends", "cause_and_effect"],
    },
    {
        "unit": 3, "title": "No man is an island", "subtopics": "Individuality, community",
        "p_start": 21, "p_end": 24, "test_practice": "Writing Task 1",
        "topics": ["society_and_global_issues", "people_and_relationships"], "functions": ["comparison_and_contrast"],
    },
    {
        "unit": 4, "title": "Scientific discovery", "subtopics": "Chemistry, medicine",
        "p_start": 25, "p_end": 28, "test_practice": "Reading",
        "topics": ["science_and_technology", "health_and_medicine"], "functions": ["evidence_and_reasoning"],
    },
    {
        "unit": 5, "title": "Striving to achieve", "subtopics": "Study, work",
        "p_start": 29, "p_end": 34, "test_practice": "Speaking",
        "topics": ["education_and_learning", "work_and_careers"], "functions": ["evaluation", "academic_reporting"],
    },
    {
        "unit": 6, "title": "Powers of persuasion", "subtopics": "Advertising, marketing",
        "p_start": 35, "p_end": 38, "test_practice": "Reading",
        "topics": ["media_and_communication", "business_and_economy"], "functions": ["argumentation"],
    },
    {
        "unit": 7, "title": "Ways and means", "subtopics": "Tourism, travel",
        "p_start": 39, "p_end": 44, "test_practice": "Writing Task 1",
        "topics": ["transport_and_travel"], "functions": ["classification"],
    },
    {
        "unit": 8, "title": "State control", "subtopics": "Government, society",
        "p_start": 45, "p_end": 48, "test_practice": "Writing Task 2",
        "topics": ["government_and_politics", "society_and_global_issues"], "functions": ["argumentation", "agreement_and_disagreement"],
    },
    {
        "unit": 9, "title": "Natural history", "subtopics": "Animals, conservation",
        "p_start": 49, "p_end": 54, "test_practice": "Reading",
        "topics": ["nature_and_animals", "environment_and_climate"], "functions": ["classification", "cause_and_effect"],
    },
    {
        "unit": 10, "title": "Rocket science", "subtopics": "Space, physics",
        "p_start": 55, "p_end": 58, "test_practice": "Listening Part 4",
        "topics": ["science_and_technology"], "functions": ["definition_and_explanation"],
    },
    {
        "unit": 11, "title": "Progress", "subtopics": "Technology, design",
        "p_start": 59, "p_end": 64, "test_practice": "Reading",
        "topics": ["science_and_technology", "society_and_global_issues"], "functions": ["evaluation", "problem_and_solution"],
    },
    {
        "unit": 12, "title": "The latest thing", "subtopics": "Fashion and trends, consumerism",
        "p_start": 65, "p_end": 68, "test_practice": "Reading",
        "topics": ["business_and_economy", "food_and_lifestyle"], "functions": ["describing_trends"],
    },
    {
        "unit": 13, "title": "Urban jungle", "subtopics": "Rural life, city life",
        "p_start": 69, "p_end": 74, "test_practice": "Listening Part 1",
        "topics": ["housing_and_urbanisation", "society_and_global_issues"], "functions": ["comparison_and_contrast"],
    },
    {
        "unit": 14, "title": "Tackling issues", "subtopics": "Problems, solutions",
        "p_start": 75, "p_end": 78, "test_practice": "Writing Task 2",
        "topics": ["society_and_global_issues"], "functions": ["problem_and_solution", "cause_and_effect"],
    },
    {
        "unit": 15, "title": "This Earth", "subtopics": "Natural phenomena, agriculture",
        "p_start": 79, "p_end": 84, "test_practice": "Listening Part 3",
        "topics": ["nature_and_animals", "environment_and_climate"], "functions": ["cause_and_effect"],
    },
    {
        "unit": 16, "title": "Energy efficient", "subtopics": "Energy, natural resources",
        "p_start": 85, "p_end": 88, "test_practice": "Writing Task 2",
        "topics": ["environment_and_climate", "science_and_technology"], "functions": ["problem_and_solution", "evaluation"],
    },
    {
        "unit": 17, "title": "Getting down to business", "subtopics": "Management, personal finance",
        "p_start": 89, "p_end": 94, "test_practice": "Reading",
        "topics": ["business_and_economy", "work_and_careers"], "functions": ["register", "argumentation"],
    },
    {
        "unit": 18, "title": "Law enforcement", "subtopics": "Crime, punishment",
        "p_start": 95, "p_end": 98, "test_practice": "Writing Task 2",
        "topics": ["crime_and_law", "government_and_politics"], "functions": ["evaluation", "problem_and_solution"],
    },
    {
        "unit": 19, "title": "The media", "subtopics": "Fame and the media, media bias",
        "p_start": 99, "p_end": 104, "test_practice": "Speaking",
        "topics": ["media_and_communication"], "functions": ["register", "evaluation"],
    },
    {
        "unit": 20, "title": "A matter of taste", "subtopics": "The arts, personal taste",
        "p_start": 105, "p_end": 110, "test_practice": "Reading",
        "topics": ["culture_and_arts", "food_and_lifestyle"], "functions": ["comparison_and_contrast"],
    },
    {
        "unit": 21, "title": "Learning vocabulary", "subtopics": "Dictionaries, wordlists",
        "p_start": 111, "p_end": 112, "test_practice": "Strategy",
        "topics": ["academic_language", "education_and_learning"], "functions": ["word_formation"],
    },
    {
        "unit": 22, "title": "IELTS Reading", "subtopics": "Reading skills, question types",
        "p_start": 113, "p_end": 116, "test_practice": "Strategy",
        "topics": ["academic_language"], "functions": ["academic_reporting"],
    },
    {
        "unit": 23, "title": "IELTS Writing", "subtopics": "Writing Task 1, Writing Task 2",
        "p_start": 117, "p_end": 120, "test_practice": "Strategy",
        "topics": ["academic_language"], "functions": ["argumentation", "describing_trends"],
    },
    {
        "unit": 24, "title": "IELTS Listening", "subtopics": "Listening Part 1 to 4",
        "p_start": 121, "p_end": 124, "test_practice": "Strategy",
        "topics": ["academic_language"], "functions": ["definition_and_explanation"],
    },
    {
        "unit": 25, "title": "IELTS Speaking", "subtopics": "Speaking Part 1 to 3",
        "p_start": 125, "p_end": 134, "test_practice": "Strategy",
        "topics": ["academic_language"], "functions": ["register", "evaluation"],
    },
]

# NgocBach Paraphrase Sections
NB_PARA_SECTIONS = [
    {
        "section_id": "NB-PARA-T1-GEN", "title": "Task 1 Paraphrasing: General Principles",
        "p_start": 3, "p_end": 5, "topics": ["academic_language"], "functions": ["describing_trends", "quantity_and_degree"],
    },
    {
        "section_id": "NB-PARA-T1-WORDS", "title": "Task 1 Paraphrasing: Key Expression Groups",
        "p_start": 6, "p_end": 16, "topics": ["academic_language", "business_and_economy"], "functions": ["describing_trends", "quantity_and_degree"],
    },
    {
        "section_id": "NB-PARA-T2-GEN", "title": "Task 2 Paraphrasing: General Principles",
        "p_start": 17, "p_end": 23, "topics": ["academic_language"], "functions": ["argumentation", "word_formation"],
    },
    {
        "section_id": "NB-PARA-T2-WORDS", "title": "Task 2 Paraphrasing: Key Expression Groups",
        "p_start": 24, "p_end": 26, "topics": ["academic_language"], "functions": ["argumentation", "cause_and_effect"],
    },
    {
        "section_id": "NB-PARA-T2-TOPICS", "title": "Task 2 Paraphrasing: Topic-Based Patterns",
        "p_start": 27, "p_end": 29, "topics": ["society_and_global_issues"], "functions": ["comparison_and_contrast"],
    },
    {
        "section_id": "NB-PARA-PRAC-EDU", "title": "Practice: Education Paraphrasing",
        "p_start": 30, "p_end": 34, "topics": ["education_and_learning", "academic_language"], "functions": ["argumentation", "definition_and_explanation"],
    },
    {
        "section_id": "NB-PARA-PRAC-WORK", "title": "Practice: Work Paraphrasing",
        "p_start": 35, "p_end": 38, "topics": ["work_and_careers"], "functions": ["cause_and_effect"],
    },
    {
        "section_id": "NB-PARA-PRAC-CRIME", "title": "Practice: Crime Paraphrasing",
        "p_start": 39, "p_end": 42, "topics": ["crime_and_law", "government_and_politics"], "functions": ["problem_and_solution"],
    },
    {
        "section_id": "NB-PARA-PRAC-ENV", "title": "Practice: The Environment Paraphrasing",
        "p_start": 43, "p_end": 46, "topics": ["environment_and_climate"], "functions": ["cause_and_effect", "problem_and_solution"],
    },
    {
        "section_id": "NB-PARA-PRAC-TRANS", "title": "Practice: Transport Paraphrasing",
        "p_start": 47, "p_end": 51, "topics": ["transport_and_travel", "housing_and_urbanisation"], "functions": ["problem_and_solution"],
    },
]


def extract_in_use_unit_title(pdf_path: Path, p_start: int, unit_num: int) -> str:
    """Extracts clean unit title from physical start page of an In-Use textbook."""
    out = subprocess.run(
        ["pdftotext", "-f", str(p_start), "-l", str(p_start), str(pdf_path), "-"],
        capture_output=True, text=True
    ).stdout
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    cand = []
    for l in lines[:8]:
        if l in [str(unit_num), "A", "B"] or l.isdigit():
            continue
        if "in Use" in l or "Cambridge" in l or l.startswith("Unit "):
            continue
        cand.append(l)

    if not cand:
        return f"Unit {unit_num}"
    if len(cand) >= 2 and len(cand[0].split()) <= 4 and len(cand[1].split()) <= 4 and not cand[0].endswith((".", ":")):
        return f"{cand[0]} {cand[1]}"
    return cand[0]


def assign_topics_to_unit(source_id: str, unit_num: int, title: str) -> Tuple[List[str], List[str]]:
    """Heuristically and rule-based assigns topic and function tags to a unit."""
    t_lower = title.lower()
    topics = []
    funcs = []

    # Domain specific overrides
    if "education" in t_lower or "study" in t_lower or "school" in t_lower or "university" in t_lower or "student" in t_lower or "cram" in t_lower or "learn" in t_lower:
        topics.append("education_and_learning")
    if "work" in t_lower or "job" in t_lower or "career" in t_lower or "interview" in t_lower or "employment" in t_lower or "colleague" in t_lower:
        topics.append("work_and_careers")
    if "business" in t_lower or "money" in t_lower or "market" in t_lower or "trade" in t_lower or "enterprise" in t_lower:
        topics.append("business_and_economy")
    if "environment" in t_lower or "climate" in t_lower or "weather" in t_lower or "planet" in t_lower or "earth" in t_lower or "pollution" in t_lower:
        topics.append("environment_and_climate")
    if "technology" in t_lower or "computer" in t_lower or "digital" in t_lower or "science" in t_lower or "research" in t_lower:
        topics.append("science_and_technology")
    if "health" in t_lower or "medicine" in t_lower or "disease" in t_lower or "illness" in t_lower or "doctor" in t_lower or "fitness" in t_lower:
        topics.append("health_and_medicine")
    if "travel" in t_lower or "transport" in t_lower or "tourism" in t_lower or "holiday" in t_lower or "journey" in t_lower or "road" in t_lower:
        topics.append("transport_and_travel")
    if "crime" in t_lower or "law" in t_lower or "punishment" in t_lower or "court" in t_lower or "police" in t_lower:
        topics.append("crime_and_law")
    if "government" in t_lower or "policy" in t_lower or "state" in t_lower or "bureaucra" in t_lower or "red tape" in t_lower:
        topics.append("government_and_politics")
    if "media" in t_lower or "news" in t_lower or "headline" in t_lower or "press" in t_lower or "television" in t_lower:
        topics.append("media_and_communication")
    if "people" in t_lower or "family" in t_lower or "relationship" in t_lower or "friend" in t_lower or "appearance" in t_lower or "personality" in t_lower:
        topics.append("people_and_relationships")
    if "food" in t_lower or "cooking" in t_lower or "eating" in t_lower or "diet" in t_lower or "lifestyle" in t_lower:
        topics.append("food_and_lifestyle")
    if "art" in t_lower or "music" in t_lower or "theatre" in t_lower or "literature" in t_lower or "book" in t_lower:
        topics.append("culture_and_arts")
    if "town" in t_lower or "city" in t_lower or "urban" in t_lower or "house" in t_lower or "flat" in t_lower or "building" in t_lower:
        topics.append("housing_and_urbanisation")
    if "animal" in t_lower or "nature" in t_lower or "wildlife" in t_lower or "countryside" in t_lower:
        topics.append("nature_and_animals")
    if "academic" in t_lower or "essay" in t_lower or "writing" in t_lower or "lecture" in t_lower or "argument" in t_lower:
        topics.append("academic_language")

    # Functions
    if "cause" in t_lower or "effect" in t_lower:
        funcs.append("cause_and_effect")
    if "compare" in t_lower or "contrast" in t_lower:
        funcs.append("comparison_and_contrast")
    if "argument" in t_lower:
        funcs.append("argumentation")
    if "agree" in t_lower or "disagree" in t_lower:
        funcs.append("agreement_and_disagreement")
    if "trend" in t_lower or "change" in t_lower or "statistic" in t_lower or "graph" in t_lower:
        funcs.append("describing_trends")
    if "problem" in t_lower or "solution" in t_lower:
        funcs.append("problem_and_solution")
    if "register" in t_lower:
        funcs.append("register")
    if "classify" in t_lower or "type" in t_lower:
        funcs.append("classification")

    if not topics:
        keyword_topics = classify_topics_by_keywords(title)
        if keyword_topics:
            topics.append(keyword_topics[0])
        else:
            topics.append("abstract_concepts")

    return list(set(topics)), list(set(funcs))


def build_unit_and_topic_indexes() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Generates complete unit index and cross-source topic index."""
    unit_index = {}
    topic_index = {
        topic_id: {
            "topic_id": topic_id,
            "name": data["name"],
            "description": data["description"],
            "units": [],
        }
        for topic_id, data in TOPIC_TAXONOMY.items()
    }

    # 1. EVU-B2 (101 units)
    evu_b2_path = VOCAB_RAW_DIR / "EVU-B2.pdf"
    with pikepdf.open(evu_b2_path) as pdf:
        out = pdf.open_outline()
        evu_b2_outlines = {}
        for it in out.root:
            m = re.match(r"^(\d+)\s+(.*)", str(it.title))
            if m:
                evu_b2_outlines[int(m.group(1))] = m.group(2).strip()

    for u in range(1, 102):
        p_start = 9 + (u - 1) * 2
        p_end = p_start + 1
        title = evu_b2_outlines.get(u) or extract_in_use_unit_title(evu_b2_path, p_start, u)
        topics, funcs = assign_topics_to_unit("EVU-B2", u, title)
        key = f"EVU-B2-U{u:03d}"
        entry = {
            "unit_key": key,
            "source_id": "EVU-B2",
            "unit_number": u,
            "title": title,
            "physical_pages": [p_start, p_end],
            "theory_pages": [p_start],
            "exercise_pages": [p_end],
            "answer_key_pdf_pages": [211, 257],
            "topics": topics,
            "language_functions": funcs,
            "audio_required": False,
            "text_layer": True,
            "scanned": False,
        }
        unit_index[key] = entry
        for t in topics:
            if t in topic_index:
                topic_index[t]["units"].append(key)

    # 2. EVU-ADV (101 units)
    evu_adv_path = VOCAB_RAW_DIR / "EVU-ADV.pdf"
    for u in range(1, 102):
        p_start = 10 + (u - 1) * 2
        p_end = p_start + 1
        title = extract_in_use_unit_title(evu_adv_path, p_start, u)
        topics, funcs = assign_topics_to_unit("EVU-ADV", u, title)
        key = f"EVU-ADV-U{u:03d}"
        entry = {
            "unit_key": key,
            "source_id": "EVU-ADV",
            "unit_number": u,
            "title": title,
            "physical_pages": [p_start, p_end],
            "theory_pages": [p_start],
            "exercise_pages": [p_end],
            "answer_key_pdf_pages": [212, 277],
            "topics": topics,
            "language_functions": funcs,
            "audio_required": False,
            "text_layer": True,
            "scanned": False,
        }
        unit_index[key] = entry
        for t in topics:
            if t in topic_index:
                topic_index[t]["units"].append(key)

    # 3. ECI-INT (60 units)
    eci_int_path = VOCAB_RAW_DIR / "ECI-INT.pdf"
    for u in range(1, 61):
        p_start = 10 + (u - 1) * 2
        p_end = p_start + 1
        title = extract_in_use_unit_title(eci_int_path, p_start, u)
        topics, funcs = assign_topics_to_unit("ECI-INT", u, title)
        key = f"ECI-INT-U{u:03d}"
        entry = {
            "unit_key": key,
            "source_id": "ECI-INT",
            "unit_number": u,
            "title": title,
            "physical_pages": [p_start, p_end],
            "theory_pages": [p_start],
            "exercise_pages": [p_end],
            "answer_key_pdf_pages": [130, 161],
            "topics": topics,
            "language_functions": funcs,
            "audio_required": False,
            "text_layer": True,
            "scanned": False,
        }
        unit_index[key] = entry
        for t in topics:
            if t in topic_index:
                topic_index[t]["units"].append(key)

    # 4. ECI-ADV (60 units)
    eci_adv_path = VOCAB_RAW_DIR / "ECI-ADV.pdf"
    for u in range(1, 61):
        p_start = 10 + (u - 1) * 2
        p_end = p_start + 1
        title = extract_in_use_unit_title(eci_adv_path, p_start, u)
        topics, funcs = assign_topics_to_unit("ECI-ADV", u, title)
        key = f"ECI-ADV-U{u:03d}"
        entry = {
            "unit_key": key,
            "source_id": "ECI-ADV",
            "unit_number": u,
            "title": title,
            "physical_pages": [p_start, p_end],
            "theory_pages": [p_start],
            "exercise_pages": [p_end],
            "answer_key_pdf_pages": [128, 163],
            "topics": topics,
            "language_functions": funcs,
            "audio_required": False,
            "text_layer": True,
            "scanned": False,
        }
        unit_index[key] = entry
        for t in topics:
            if t in topic_index:
                topic_index[t]["units"].append(key)

    # 5. AVU (Unit 0 + Units 1-50)
    avu_path = VOCAB_RAW_DIR / "AVU.pdf"
    # Unit 0
    entry_u0 = {
        "unit_key": "AVU-U000",
        "source_id": "AVU",
        "unit_number": 0,
        "title": "Before you start",
        "physical_pages": [10, 11],
        "theory_pages": [10],
        "exercise_pages": [11],
        "answer_key_pdf_pages": [134, 163],
        "topics": ["academic_language", "education_and_learning"],
        "language_functions": ["definition_and_explanation"],
        "audio_required": False,
        "text_layer": True,
        "scanned": False,
    }
    unit_index["AVU-U000"] = entry_u0
    topic_index["academic_language"]["units"].append("AVU-U000")
    topic_index["education_and_learning"]["units"].append("AVU-U000")

    for u in range(1, 51):
        p_start = 12 + (u - 1) * 2
        p_end = p_start + 1
        title = extract_in_use_unit_title(avu_path, p_start, u)
        topics, funcs = assign_topics_to_unit("AVU", u, title)
        key = f"AVU-U{u:03d}"
        entry = {
            "unit_key": key,
            "source_id": "AVU",
            "unit_number": u,
            "title": title,
            "physical_pages": [p_start, p_end],
            "theory_pages": [p_start],
            "exercise_pages": [p_end],
            "answer_key_pdf_pages": [134, 163],
            "topics": topics,
            "language_functions": funcs,
            "audio_required": False,
            "text_layer": True,
            "scanned": False,
        }
        unit_index[key] = entry
        for t in topics:
            if t in topic_index:
                topic_index[t]["units"].append(key)

    # 6. IVU-60 (25 units)
    for u_info in IVU_60_UNITS:
        u = u_info["unit"]
        key = f"IVU-60-U{u:03d}"
        p_start = u_info["p_start"]
        p_end = u_info["p_end"]
        theory_pages = [p_start, p_start + 1]
        exercise_pages = list(range(p_start + 2, p_end + 1))
        entry = {
            "unit_key": key,
            "source_id": "IVU-60",
            "unit_number": u,
            "title": u_info["title"],
            "subtopics": u_info["subtopics"],
            "test_practice": u_info["test_practice"],
            "physical_pages": list(range(p_start, p_end + 1)),
            "theory_pages": theory_pages,
            "exercise_pages": exercise_pages,
            "answer_key_pdf_pages": [134, 158],
            "recording_scripts_pdf_pages": [159, 168],
            "wordlist_pdf_pages": [169, 175],
            "topics": u_info["topics"],
            "language_functions": u_info["functions"],
            "audio_required": True,
            "audio_available": False,
            "text_layer": False,
            "scanned": True,
        }
        unit_index[key] = entry
        for t in u_info["topics"]:
            if t in topic_index:
                topic_index[t]["units"].append(key)

    # 7. IVU-65 (25 units)
    for u_info in IVU_65_UNITS:
        u = u_info["unit"]
        key = f"IVU-65-U{u:03d}"
        p_start = u_info["p_start"]
        p_end = u_info["p_end"]
        theory_pages = [p_start, p_start + 1]
        exercise_pages = list(range(p_start + 2, p_end + 1))
        entry = {
            "unit_key": key,
            "source_id": "IVU-65",
            "unit_number": u,
            "title": u_info["title"],
            "subtopics": u_info["subtopics"],
            "test_practice": u_info["test_practice"],
            "physical_pages": list(range(p_start, p_end + 1)),
            "theory_pages": theory_pages,
            "exercise_pages": exercise_pages,
            "answer_key_pdf_pages": [135, 158],
            "recording_scripts_pdf_pages": [159, 170],
            "wordlist_pdf_pages": [171, 175],
            "topics": u_info["topics"],
            "language_functions": u_info["functions"],
            "audio_required": True,
            "audio_available": False,
            "text_layer": False,
            "scanned": True,
        }
        unit_index[key] = entry
        for t in u_info["topics"]:
            if t in topic_index:
                topic_index[t]["units"].append(key)

    # 8. NB-PARA (10 sections)
    for sec in NB_PARA_SECTIONS:
        key = sec["section_id"]
        entry = {
            "unit_key": key,
            "source_id": "NB-PARA",
            "unit_number": key,
            "title": sec["title"],
            "physical_pages": list(range(sec["p_start"], sec["p_end"] + 1)),
            "theory_pages": list(range(sec["p_start"], sec["p_end"] + 1)),
            "exercise_pages": list(range(sec["p_start"], sec["p_end"] + 1)),
            "answer_key_pdf_pages": None,
            "topics": sec["topics"],
            "language_functions": sec["functions"],
            "audio_required": False,
            "text_layer": True,
            "scanned": False,
        }
        unit_index[key] = entry
        for t in sec["topics"]:
            if t in topic_index:
                topic_index[t]["units"].append(key)

    return unit_index, topic_index


def save_indexes(output_dir: Path = VOCAB_KB_DIR):
    """Saves unit_index.json and topic_index.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    unit_idx, topic_idx = build_unit_and_topic_indexes()

    with open(output_dir / "unit_index.json", "w", encoding="utf-8") as f:
        json.dump(unit_idx, f, indent=2, ensure_ascii=False)

    with open(output_dir / "topic_index.json", "w", encoding="utf-8") as f:
        json.dump(topic_idx, f, indent=2, ensure_ascii=False)

    print(f"Saved unit_index.json ({len(unit_idx)} units) and topic_index.json ({len(topic_idx)} topics).")


if __name__ == "__main__":
    save_indexes()
