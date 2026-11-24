"""Vocabulary Session, Curriculum Progression and Spaced Review Manager.

Handles natural learning commands, progress tracking, and session resumption
with full privacy isolation (synthetic or user-isolated progress files).
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness.vocabulary.kb import (
    VOCAB_KB_DIR,
    get_unit_details,
    query_vocabulary_by_topic,
    query_collocations_by_topic,
    query_paraphrases_by_topic,
)

DEFAULT_PROGRESS_FILE = Path("private/progress/vocabulary.jsonl")
DEFAULT_CURRICULUM_FILE = Path("private/progress/curriculum.json")

# Primary curriculum backbone order
CURRICULUM_BACKBONE = [f"IVU-60-U{i:03d}" for i in range(1, 26)] + [f"IVU-65-U{i:03d}" for i in range(1, 26)]


def parse_learning_intent(prompt: str) -> Dict[str, Any]:
    """Deterministically identifies the vocabulary learning intent from user input."""
    p_lower = prompt.lower().strip()

    # 1. Review due vocabulary: "ôn từ vựng hôm nay", "ôn từ vựng đến hạn", "review due vocabulary"
    if any(k in p_lower for k in ["ôn từ vựng hôm nay", "ôn từ vựng", "review vocabulary", "ôn tập từ vựng"]):
        return {
            "intent": "REVIEW_DUE_VOCABULARY",
            "raw_prompt": prompt,
        }

    # 2. Next unit in curriculum: "học unit tiếp theo", "bài tiếp theo", "next unit"
    if any(k in p_lower for k in ["học unit tiếp theo", "unit tiếp theo", "bài tiếp theo", "next unit"]):
        return {
            "intent": "LEARN_NEXT_UNIT",
            "raw_prompt": prompt,
        }

    # 3. Specific unit: e.g. "Học IVU-60 Unit 1", "Học EVU-B2 Unit 14", "Học AVU Unit 37"
    unit_match = re.search(r"(?:học|luyện|xem)\s+([A-Z0-9\-]+)\s+(?:unit|bài)\s+(\d+)", prompt, re.IGNORECASE)
    if unit_match:
        source_prefix = unit_match.group(1).upper()
        unit_num = int(unit_match.group(2))
        unit_key = f"{source_prefix}-U{unit_num:03d}"
        return {
            "intent": "LEARN_UNIT",
            "source_id": source_prefix,
            "unit_number": unit_num,
            "unit_key": unit_key,
            "raw_prompt": prompt,
        }

    # 4. Topic-based: "Học từ vựng chủ đề Education", "Luyện từ vựng Environment"
    topic_map = {
        "education": "education_and_learning",
        "giáo dục": "education_and_learning",
        "work": "work_and_careers",
        "công việc": "work_and_careers",
        "business": "business_and_economy",
        "kinh tế": "business_and_economy",
        "environment": "environment_and_climate",
        "môi trường": "environment_and_climate",
        "technology": "science_and_technology",
        "công nghệ": "science_and_technology",
        "health": "health_and_medicine",
        "sức khỏe": "health_and_medicine",
        "crime": "crime_and_law",
        "tội phạm": "crime_and_law",
        "transport": "transport_and_travel",
        "giao thông": "transport_and_travel",
    }
    for kw, topic_id in topic_map.items():
        if kw in p_lower:
            return {
                "intent": "LEARN_TOPIC",
                "topic_id": topic_id,
                "raw_prompt": prompt,
            }

    return {
        "intent": "UNKNOWN_VOCABULARY_INTENT",
        "raw_prompt": prompt,
    }


def load_curriculum_state(curriculum_file: Optional[Path] = None) -> Dict[str, Any]:
    """Loads current curriculum position, completed units and bookmarks."""
    c_file = curriculum_file or DEFAULT_CURRICULUM_FILE
    if not c_file.exists():
        return {
            "current_unit_key": CURRICULUM_BACKBONE[0],
            "completed_units": [],
            "last_updated": None,
        }
    with open(c_file, "r", encoding="utf-8") as f:
        return json.load(f)


def save_curriculum_state(state: Dict[str, Any], curriculum_file: Optional[Path] = None) -> None:
    """Saves updated curriculum position."""
    c_file = curriculum_file or DEFAULT_CURRICULUM_FILE
    c_file.parent.mkdir(parents=True, exist_ok=True)
    state["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(c_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get_due_vocabulary(
    target_date: Optional[str] = None,
    progress_file: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Retrieves items whose next_review_date <= target_date (default today)."""
    p_file = progress_file or DEFAULT_PROGRESS_FILE
    if not p_file.exists():
        return []

    today_str = target_date or datetime.date.today().isoformat()
    due_items = []

    with open(p_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            nrd = entry.get("next_review_date")
            if nrd and nrd <= today_str:
                due_items.append(entry)

    return due_items


def record_vocabulary_review(
    item_id: str,
    expression: str,
    success: bool,
    progress_file: Optional[Path] = None,
    interval_days: int = 3,
) -> Dict[str, Any]:
    """Appends an updated spaced repetition record for a vocabulary item."""
    p_file = progress_file or DEFAULT_PROGRESS_FILE
    p_file.parent.mkdir(parents=True, exist_ok=True)

    today = datetime.date.today()
    if interval_days == 0:
        next_date = today
    elif success:
        next_date = today + datetime.timedelta(days=interval_days)
    else:
        next_date = today + datetime.timedelta(days=1)

    record = {
        "item_id": item_id,
        "expression": expression,
        "reviewed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "success": success,
        "repetitions": 1 if success else 0,
        "next_review_date": next_date.isoformat(),
    }

    with open(p_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record


def execute_tutor_command(
    prompt: str,
    progress_file: Optional[Path] = None,
    curriculum_file: Optional[Path] = None,
) -> Dict[str, Any]:
    """Simulates the tutor routing and knowledge retrieval for learning commands."""
    parsed = parse_learning_intent(prompt)
    intent = parsed["intent"]

    if intent == "LEARN_UNIT":
        unit_key = parsed["unit_key"]
        unit_data = get_unit_details(unit_key)
        if not unit_data:
            return {
                "status": "not_found",
                "message": f"Unit {unit_key} không tìm thấy trong Knowledge Base.",
                "parsed_intent": parsed,
            }

        # Update curriculum position to this unit
        curr_state = load_curriculum_state(curriculum_file)
        curr_state["current_unit_key"] = unit_key
        save_curriculum_state(curr_state, curriculum_file)

        return {
            "status": "ready",
            "workflow": "Workflow E: Learn (Unit Mode)",
            "unit_key": unit_key,
            "title": unit_data.get("title"),
            "source_id": unit_data.get("source_id"),
            "theory_sections": len(unit_data.get("theory", {}).get("sections", [])),
            "exercises_count": len(unit_data.get("exercises", [])),
            "unit_data": unit_data,
        }

    elif intent == "LEARN_TOPIC":
        topic_id = parsed["topic_id"]
        vocab = query_vocabulary_by_topic(topic_id, limit=5)
        collocations = query_collocations_by_topic(topic_id, limit=4)
        paraphrases = query_paraphrases_by_topic(topic_id, limit=3)

        return {
            "status": "ready",
            "workflow": "Workflow E: Learn (Topic Mode)",
            "topic_id": topic_id,
            "vocabulary_items": vocab,
            "collocations": collocations,
            "paraphrases": paraphrases,
        }

    elif intent == "LEARN_NEXT_UNIT":
        curr_state = load_curriculum_state(curriculum_file)
        current = curr_state.get("current_unit_key", CURRICULUM_BACKBONE[0])

        if current in CURRICULUM_BACKBONE:
            idx = CURRICULUM_BACKBONE.index(current)
            next_idx = min(idx + 1, len(CURRICULUM_BACKBONE) - 1)
            next_unit_key = CURRICULUM_BACKBONE[next_idx]
        else:
            m = re.match(r"^([A-Z0-9\-]+)-U(\d{3})$", current)
            if m:
                src, num = m.group(1), int(m.group(2))
                candidate = f"{src}-U{num+1:03d}"
                index_file = VOCAB_KB_DIR / "unit_index.json"
                unit_exists = False
                if index_file.exists():
                    with open(index_file, "r", encoding="utf-8") as f:
                        unit_exists = candidate in json.load(f)
                next_unit_key = candidate if unit_exists else CURRICULUM_BACKBONE[0]
            else:
                next_unit_key = CURRICULUM_BACKBONE[0]

        unit_data = get_unit_details(next_unit_key)
        curr_state["current_unit_key"] = next_unit_key
        save_curriculum_state(curr_state, curriculum_file)

        return {
            "status": "ready",
            "workflow": "Workflow E: Learn (Sequential Progression)",
            "previous_unit": current,
            "next_unit_key": next_unit_key,
            "title": unit_data.get("title") if unit_data else "",
            "unit_data": unit_data,
        }

    elif intent == "REVIEW_DUE_VOCABULARY":
        due_items = get_due_vocabulary(progress_file=progress_file)
        return {
            "status": "ready",
            "workflow": "Workflow E: Learn (Active Recall / Spaced Review)",
            "due_count": len(due_items),
            "due_items": due_items,
        }

    return {
        "status": "unhandled",
        "parsed_intent": parsed,
    }
