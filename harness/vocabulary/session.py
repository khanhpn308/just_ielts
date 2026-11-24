"""Vocabulary Session, Adaptive Roadmap, Curriculum Progression and Spaced Review Manager.

Implements:
- PR #10 Vocabulary Progress Contract:
  * Level 0–3 (unknown/failed, recognized, recalled, productive).
  * Stage 0–5 spaced repetition review schedule (Gaps: 1, 2, 3, 7, 16, 30 days).
  * Early successful reviews MUST NOT advance stage or postpone next_review_date.
  * Failed/assisted reviews may shorten schedule (tomorrow or existing due date, whichever is earlier).
  * Sense-based journal identity (expression + POS + sense_key).
  * One current record per identity in private/progress/vocabulary.jsonl.
  * Prevention of duplicate records and repeated same-day advancement.
  * Explicit user consent required before persisting progress or curriculum state.
- Adaptive Vocabulary Roadmap & Progress Navigation:
  * Independent textbook progress across all 8 textbooks and PRIMARY_CORE track.
  * Automatic lesson selection ("Học từ vựng", "Học collocation", "Học paraphrase", "Học theo chủ đề").
  * Track switching without losing progress in other tracks.
  * Resuming unfinished lessons in a fresh conversation.
  * Structured views for "Xem tiến độ" and "Xem lộ trình".
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness.vocabulary.kb import (
    VOCAB_KB_DIR,
    KB_UNITS_DIR,
    build_entry_key,
    normalize_expression,
    get_unit_details,
    query_vocabulary_by_topic,
    query_collocations_by_topic,
    query_paraphrases_by_topic,
)
from harness.vocabulary.taxonomy import TOPIC_TAXONOMY

DEFAULT_PROGRESS_FILE = Path("private/progress/vocabulary.jsonl")
DEFAULT_CURRICULUM_FILE = Path("private/progress/curriculum.json")

# Baseline schedule gaps for Review Stage 0..5 (in days)
STAGE_GAPS = [1, 2, 3, 7, 16, 30]

NB_PARA_UNITS = [
    "NB-PARA-T1-GEN",
    "NB-PARA-T1-WORDS",
    "NB-PARA-T2-GEN",
    "NB-PARA-T2-WORDS",
    "NB-PARA-T2-TOPICS",
    "NB-PARA-PRAC-EDU",
    "NB-PARA-PRAC-WORK",
    "NB-PARA-PRAC-CRIME",
    "NB-PARA-PRAC-ENV",
    "NB-PARA-PRAC-TRANS",
]

TRACK_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "PRIMARY_CORE": {
        "label": "Primary IELTS Core (IVU-60 -> IVU-65)",
        "sources": ["IVU-60", "IVU-65"],
        "units": [f"IVU-60-U{i:03d}" for i in range(1, 26)] + [f"IVU-65-U{i:03d}" for i in range(1, 26)],
    },
    "IVU-60": {
        "label": "IELTS Vocabulary Up to Band 6.0",
        "sources": ["IVU-60"],
        "units": [f"IVU-60-U{i:03d}" for i in range(1, 26)],
    },
    "IVU-65": {
        "label": "IELTS Vocabulary Bands 6.5+",
        "sources": ["IVU-65"],
        "units": [f"IVU-65-U{i:03d}" for i in range(1, 26)],
    },
    "EVU-B2": {
        "label": "English Vocabulary in Use Upper-intermediate",
        "sources": ["EVU-B2"],
        "units": [f"EVU-B2-U{i:03d}" for i in range(1, 102)],
    },
    "EVU-ADV": {
        "label": "English Vocabulary in Use Advanced",
        "sources": ["EVU-ADV"],
        "units": [f"EVU-ADV-U{i:03d}" for i in range(1, 102)],
    },
    "ECI-INT": {
        "label": "English Collocations in Use Intermediate",
        "sources": ["ECI-INT"],
        "units": [f"ECI-INT-U{i:03d}" for i in range(1, 61)],
    },
    "ECI-ADV": {
        "label": "English Collocations in Use Advanced",
        "sources": ["ECI-ADV"],
        "units": [f"ECI-ADV-U{i:03d}" for i in range(1, 61)],
    },
    "AVU": {
        "label": "Academic Vocabulary in Use",
        "sources": ["AVU"],
        "units": [f"AVU-U{i:03d}" for i in range(0, 51)],
    },
    "NB-PARA": {
        "label": "NgocBach — How to Paraphrase",
        "sources": ["NB-PARA"],
        "units": list(NB_PARA_UNITS),
    },
}

# Primary curriculum backbone order (backward compatible alias)
CURRICULUM_BACKBONE = TRACK_DEFINITIONS["PRIMARY_CORE"]["units"]

TEXTBOOK_IDS = ["IVU-60", "IVU-65", "EVU-B2", "EVU-ADV", "ECI-INT", "ECI-ADV", "AVU", "NB-PARA"]

TOPIC_KEYWORDS: Dict[str, str] = {
    "education": "education_and_learning",
    "giáo dục": "education_and_learning",
    "học tập": "education_and_learning",
    "work": "work_and_careers",
    "công việc": "work_and_careers",
    "nghề nghiệp": "work_and_careers",
    "business": "business_and_economy",
    "kinh tế": "business_and_economy",
    "kinh doanh": "business_and_economy",
    "environment": "environment_and_climate",
    "môi trường": "environment_and_climate",
    "khí hậu": "environment_and_climate",
    "technology": "science_and_technology",
    "science": "science_and_technology",
    "công nghệ": "science_and_technology",
    "khoa học": "science_and_technology",
    "health": "health_and_medicine",
    "sức khỏe": "health_and_medicine",
    "y tế": "health_and_medicine",
    "crime": "crime_and_law",
    "tội phạm": "crime_and_law",
    "pháp luật": "crime_and_law",
    "transport": "transport_and_travel",
    "giao thông": "transport_and_travel",
    "du lịch": "transport_and_travel",
    "government": "government_and_politics",
    "chính phủ": "government_and_politics",
    "society": "society_and_global_issues",
    "xã hội": "society_and_global_issues",
    "media": "media_and_communication",
    "truyền thông": "media_and_communication",
    "people": "people_and_relationships",
    "gia đình": "people_and_relationships",
    "food": "food_and_lifestyle",
    "ẩm thực": "food_and_lifestyle",
    "culture": "culture_and_arts",
    "văn hóa": "culture_and_arts",
    "housing": "housing_and_urbanisation",
    "đô thị": "housing_and_urbanisation",
    "nature": "nature_and_animals",
    "thiên nhiên": "nature_and_animals",
    "academic": "academic_language",
    "học thuật": "academic_language",
    "feelings": "feelings_and_behaviour",
    "cảm xúc": "feelings_and_behaviour",
    "sport": "sport_and_leisure",
    "thể thao": "sport_and_leisure",
    "abstract": "abstract_concepts",
}


def _match_topic_in_prompt(p_lower: str) -> Optional[str]:
    for kw, topic_id in TOPIC_KEYWORDS.items():
        if kw in p_lower:
            return topic_id
    for topic_id in TOPIC_TAXONOMY:
        if topic_id in p_lower:
            return topic_id
    return None


def _match_track_in_prompt(p_lower: str) -> Optional[str]:
    if any(k in p_lower for k in ["lộ trình chính", "primary_core", "primary core", "giáo trình chính"]):
        return "PRIMARY_CORE"
    for tid in TEXTBOOK_IDS:
        if tid.lower() in p_lower:
            return tid
    if "collocation" in p_lower:
        return "ECI-INT"
    if "paraphrase" in p_lower:
        return "NB-PARA"
    return None


def parse_learning_intent(prompt: str) -> Dict[str, Any]:
    """Deterministically identifies the vocabulary learning intent from user input."""
    p_lower = prompt.lower().strip()

    # 1. Explicit consent to save: "lưu kết quả buổi học", "lưu tiến độ", "save progress"
    if any(k in p_lower for k in ["lưu kết quả buổi học", "lưu kết quả", "lưu tiến độ", "save progress"]):
        return {
            "intent": "SAVE_PROGRESS",
            "user_consented": True,
            "raw_prompt": prompt,
        }

    # 2. View Progress: "xem tiến độ", "tiến độ học", "view progress"
    if any(k in p_lower for k in ["xem tiến độ", "tiến độ học", "view progress", "progress status"]):
        return {
            "intent": "VIEW_PROGRESS",
            "raw_prompt": prompt,
        }

    # 3. View Adaptive Roadmap: "xem lộ trình", "lộ trình học", "view roadmap"
    if any(k in p_lower for k in ["xem lộ trình", "lộ trình học", "view roadmap", "adaptive roadmap"]):
        return {
            "intent": "VIEW_ROADMAP",
            "raw_prompt": prompt,
        }

    # 4. Resume unfinished lesson: "tiếp tục bài hôm qua", "tiếp tục bài trước", "tiếp tục bài đang học"
    if any(k in p_lower for k in ["tiếp tục bài hôm qua", "tiếp tục bài trước", "tiếp tục bài đang học", "tiếp tục bài vừa học", "tiếp tục bài học", "resume lesson"]):
        return {
            "intent": "RESUME_LESSON",
            "raw_prompt": prompt,
        }

    # 5. Review due vocabulary: "ôn từ vựng hôm nay", "ôn từ vựng đến hạn", "review due vocabulary"
    if any(k in p_lower for k in ["ôn từ vựng hôm nay", "ôn từ vựng", "ôn những từ đến hạn", "review vocabulary", "ôn tập từ vựng"]):
        return {
            "intent": "REVIEW_DUE_VOCABULARY",
            "raw_prompt": prompt,
        }

    # 6. Switch track: "chuyển sang EVU-B2", "quay lại IVU-60", "đổi sang ECI-INT"
    if any(k in p_lower for k in ["chuyển sang", "đổi sang", "quay lại", "switch track", "chuyển lộ trình"]):
        target_track = _match_track_in_prompt(p_lower)
        if target_track:
            return {
                "intent": "SWITCH_TRACK",
                "target_track": target_track,
                "raw_prompt": prompt,
            }

    # 7. Next unit in curriculum: "học unit tiếp theo", "bài tiếp theo", "next unit"
    if any(k in p_lower for k in ["học unit tiếp theo", "unit tiếp theo", "bài tiếp theo", "next unit"]):
        return {
            "intent": "LEARN_NEXT_UNIT",
            "raw_prompt": prompt,
        }

    # 8. Specific unit: e.g. "Học IVU-60 Unit 1", "Học EVU-B2 Unit 14", "Học AVU Unit 0"
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

    topic_id = _match_topic_in_prompt(p_lower)

    # 9. Collocation study: "Học collocation", "Luyện collocation chủ đề Work"
    if "collocation" in p_lower:
        return {
            "intent": "LEARN_COLLOCATION",
            "topic_id": topic_id,
            "raw_prompt": prompt,
        }

    # 10. Paraphrase study: "Học paraphrase", "Học paraphrase chủ đề Crime"
    if "paraphrase" in p_lower:
        return {
            "intent": "LEARN_PARAPHRASE",
            "topic_id": topic_id,
            "raw_prompt": prompt,
        }

    # 11. Topic-based study: "Học theo chủ đề", "Học từ vựng chủ đề Education"
    if "chủ đề" in p_lower or topic_id is not None:
        return {
            "intent": "LEARN_TOPIC",
            "topic_id": topic_id,
            "raw_prompt": prompt,
        }

    # 12. General adaptive vocabulary lesson: "Học từ vựng", "Luyện từ vựng", "Học từ mới"
    if any(k in p_lower for k in ["học từ vựng", "luyện từ vựng", "học từ mới", "học 10 từ"]):
        return {
            "intent": "LEARN_VOCABULARY",
            "raw_prompt": prompt,
        }

    return {
        "intent": "UNKNOWN_VOCABULARY_INTENT",
        "raw_prompt": prompt,
    }


def _normalize_curriculum_state(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ensures curriculum state has all required multi-track and continuity fields."""
    base: Dict[str, Any] = {
        "schema_version": "1.1.0",
        "active_track": "PRIMARY_CORE",
        "current_unit_key": CURRICULUM_BACKBONE[0],
        "track_positions": {"PRIMARY_CORE": CURRICULUM_BACKBONE[0]},
        "completed_units": [],
        "unit_progress": {},
        "topic_progress": {},
        "unfinished_lesson": None,
        "observed_gaps": [],
        "last_updated": None,
    }
    if not raw:
        return base
    merged = dict(base)
    merged.update(raw)
    if "track_positions" not in merged or not isinstance(merged["track_positions"], dict):
        merged["track_positions"] = {"PRIMARY_CORE": merged.get("current_unit_key", CURRICULUM_BACKBONE[0])}
    if "completed_units" not in merged or not isinstance(merged["completed_units"], list):
        merged["completed_units"] = []
    if "unit_progress" not in merged or not isinstance(merged["unit_progress"], dict):
        merged["unit_progress"] = {}
    if "topic_progress" not in merged or not isinstance(merged["topic_progress"], dict):
        merged["topic_progress"] = {}
    if "observed_gaps" not in merged or not isinstance(merged["observed_gaps"], list):
        merged["observed_gaps"] = []
    return merged


def load_curriculum_state(curriculum_file: Optional[Path] = None) -> Dict[str, Any]:
    """Loads current multi-track curriculum position, unit status, and unfinished lesson."""
    c_file = curriculum_file or DEFAULT_CURRICULUM_FILE
    if not c_file.exists():
        return _normalize_curriculum_state(None)
    with open(c_file, "r", encoding="utf-8") as f:
        return _normalize_curriculum_state(json.load(f))


def save_curriculum_state(
    state: Dict[str, Any],
    curriculum_file: Optional[Path] = None,
    user_consented: bool = False,
) -> bool:
    """Saves updated curriculum state only if user explicitly consented."""
    if not user_consented:
        return False

    c_file = curriculum_file or DEFAULT_CURRICULUM_FILE
    c_file.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_curriculum_state(state)
    normalized["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    tmp_file = c_file.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)
    tmp_file.replace(c_file)
    return True


def _track_for_unit(unit_key: str) -> str:
    """Determines canonical track ID for a unit key."""
    if unit_key in CURRICULUM_BACKBONE:
        return "PRIMARY_CORE"
    for tid, cfg in TRACK_DEFINITIONS.items():
        if tid != "PRIMARY_CORE" and unit_key in cfg["units"]:
            return tid
    for sid in TEXTBOOK_IDS:
        if unit_key.startswith(sid + "-"):
            return sid
    return "PRIMARY_CORE"


def _next_uncompleted_in_track(track_id: str, state: Dict[str, Any], after_unit: Optional[str] = None) -> Optional[str]:
    """Returns the next uncompleted unit in a track without disturbing other tracks."""
    units = TRACK_DEFINITIONS.get(track_id, TRACK_DEFINITIONS["PRIMARY_CORE"])["units"]
    completed = set(state.get("completed_units", []))

    start_idx = 0
    if after_unit and after_unit in units:
        start_idx = units.index(after_unit) + 1

    for u in units[start_idx:]:
        if u not in completed:
            return u
    for u in units[:start_idx]:
        if u not in completed:
            return u
    return units[-1] if units else None


def mark_lesson_started(
    state: Dict[str, Any],
    unit_key: str,
    mode: str = "unit",
    topic_id: Optional[str] = None,
    pending_exercises: Optional[List[str]] = None,
    studied_items: Optional[List[str]] = None,
    session_date: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """Updates in-memory state to reflect an active/unfinished lesson on its own track."""
    normalized = _normalize_curriculum_state(state)
    today_str = (session_date or datetime.date.today()).isoformat()
    track_id = _track_for_unit(unit_key)
    source_id = unit_key.split("-")[0]
    if unit_key.startswith("IVU-60"):
        source_id = "IVU-60"
    elif unit_key.startswith("IVU-65"):
        source_id = "IVU-65"
    elif unit_key.startswith("EVU-B2"):
        source_id = "EVU-B2"
    elif unit_key.startswith("EVU-ADV"):
        source_id = "EVU-ADV"
    elif unit_key.startswith("ECI-INT"):
        source_id = "ECI-INT"
    elif unit_key.startswith("ECI-ADV"):
        source_id = "ECI-ADV"
    elif unit_key.startswith("NB-PARA"):
        source_id = "NB-PARA"
    elif unit_key.startswith("AVU"):
        source_id = "AVU"

    normalized["active_track"] = track_id
    normalized["current_unit_key"] = unit_key
    normalized["track_positions"][track_id] = unit_key
    if source_id in ("IVU-60", "IVU-65"):
        normalized["track_positions"][source_id] = unit_key

    normalized["unit_progress"][unit_key] = {
        "status": "in_progress",
        "source_id": source_id,
        "last_studied": today_str,
        "pending_exercises": pending_exercises or [],
    }
    normalized["unfinished_lesson"] = {
        "unit_key": unit_key,
        "source_id": source_id,
        "track_id": track_id,
        "mode": mode,
        "topic_id": topic_id,
        "pending_exercises": pending_exercises or [],
        "studied_items": studied_items or [],
        "started_at": today_str,
        "status": "in_progress",
    }
    if topic_id:
        tp = normalized["topic_progress"].setdefault(topic_id, {"studied_units": [], "last_studied": today_str})
        if unit_key not in tp["studied_units"]:
            tp["studied_units"].append(unit_key)
        tp["last_studied"] = today_str
    return normalized


def mark_lesson_completed(
    state: Dict[str, Any],
    unit_key: str,
    exercises_completed: int = 0,
    session_date: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """Marks a unit completed, clears matching unfinished_lesson, and advances that track's position."""
    normalized = _normalize_curriculum_state(state)
    today_str = (session_date or datetime.date.today()).isoformat()
    track_id = _track_for_unit(unit_key)

    if unit_key not in normalized["completed_units"]:
        normalized["completed_units"].append(unit_key)

    prev = normalized["unit_progress"].get(unit_key, {})
    normalized["unit_progress"][unit_key] = {
        "status": "completed",
        "source_id": prev.get("source_id") or _track_for_unit(unit_key),
        "last_studied": today_str,
        "exercises_completed": exercises_completed,
        "pending_exercises": [],
    }

    unf = normalized.get("unfinished_lesson")
    if isinstance(unf, dict) and unf.get("unit_key") == unit_key:
        normalized["unfinished_lesson"] = None

    next_unit = _next_uncompleted_in_track(track_id, normalized, after_unit=unit_key)
    if next_unit:
        normalized["track_positions"][track_id] = next_unit
        if next_unit.startswith("IVU-60"):
            normalized["track_positions"]["IVU-60"] = next_unit
        elif next_unit.startswith("IVU-65"):
            normalized["track_positions"]["IVU-65"] = next_unit
        if normalized.get("active_track") == track_id:
            normalized["current_unit_key"] = next_unit

    return normalized


def switch_learning_track(state: Dict[str, Any], target_track: str) -> Dict[str, Any]:
    """Switches active track while preserving independent progress in all other tracks."""
    normalized = _normalize_curriculum_state(state)
    track = target_track.upper()
    if track not in TRACK_DEFINITIONS:
        track = "PRIMARY_CORE"

    normalized["active_track"] = track
    pos = normalized["track_positions"].get(track)
    if not pos:
        pos = _next_uncompleted_in_track(track, normalized) or TRACK_DEFINITIONS[track]["units"][0]
        normalized["track_positions"][track] = pos
    normalized["current_unit_key"] = pos
    return normalized


def load_vocabulary_journal(progress_file: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Loads private vocabulary journal indexed by unique entry_key."""
    p_file = progress_file or DEFAULT_PROGRESS_FILE
    if not p_file.exists():
        return {}

    records = {}
    with open(p_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            k = entry.get("entry_key")
            if not k:
                k = build_entry_key(entry["expression"], entry["pos"], entry.get("sense_key", ""))
                entry["entry_key"] = k
            records[k] = entry
    return records


def assess_and_schedule_item(
    existing_record: Optional[Dict[str, Any]],
    expression: str,
    pos: str,
    sense_key: str,
    meaning_vi: str,
    level: int = 0,
    outcome: Optional[str] = None,
    session_date: Optional[datetime.date] = None,
    sources: Optional[List[Dict[str, Any]]] = None,
    error_event: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Calculates updated journal record following the PR #10 Level 0-3 & Stage 0-5 contract.

    Rules enforced:
    - If outcome == 'not_assessed': last_review_date stays null, next_review_date = tomorrow, review_count=0.
    - First time a brand new item is taught & assessed (existing_record is None): review_stage = 0, next_review_date = tomorrow.
    - Due unaided recall/productive use (level 2 or 3, today >= existing next_review_date): advances review_stage by 1 (max 5).
    - Early successful review (today < existing next_review_date, level 2 or 3): MUST NOT advance stage or postpone existing due date.
    - Failed review (level 0 / 'failed'): resets review_stage to 0 and schedules min(tomorrow, existing_nrd) (not earlier than tomorrow).
    - Assisted/recognition review (level 1 / 'assisted'): keeps stage unchanged and schedules min(tomorrow, existing_nrd).
    - Same-day retries never earn stage advancement or double-count review_count/lapse_count.
    """
    today = session_date or datetime.date.today()
    today_str = today.isoformat()
    tomorrow_str = (today + datetime.timedelta(days=1)).isoformat()
    entry_key = build_entry_key(expression, pos, sense_key)

    is_new_item = existing_record is None
    record = dict(existing_record) if existing_record else {
        "entry_key": entry_key,
        "expression": expression,
        "pos": pos,
        "sense_key": sense_key,
        "meaning_vi": meaning_vi,
        "sources": sources or [{"kind": "tutor_created", "ref": None, "locator": None}],
        "level": 0,
        "review_stage": 0,
        "first_studied_date": today_str,
        "last_review_date": None,
        "next_review_date": tomorrow_str,
        "last_outcome": "not_assessed",
        "review_count": 0,
        "lapse_count": 0,
        "errors": [],
    }

    if outcome is None:
        if is_new_item and level == 0:
            outcome = "not_assessed"
        else:
            outcome_names = {0: "failed", 1: "assisted", 2: "recalled", 3: "productive"}
            outcome = outcome_names.get(level, "not_assessed")

    if outcome == "not_assessed":
        record["last_outcome"] = "not_assessed"
        record["level"] = 0
        record["review_stage"] = 0
        record["last_review_date"] = None
        record["next_review_date"] = tomorrow_str
        if error_event:
            record.setdefault("errors", []).append(error_event)
        return record

    existing_nrd = record.get("next_review_date")
    already_reviewed_today = (record.get("last_review_date") == today_str)
    curr_stage = record.get("review_stage", 0)

    if already_reviewed_today:
        # Same-day retry: cannot advance stage again or double-count metrics.
        # An observed later failure on the same day resets stage and shortens schedule.
        if outcome == "failed":
            record["review_stage"] = 0
            record["next_review_date"] = tomorrow_str
            record["last_outcome"] = "failed"
            record["level"] = 0
        elif outcome == "assisted":
            record["last_outcome"] = "assisted"
            record["level"] = min(record.get("level", 1), 1)
            record["next_review_date"] = min(tomorrow_str, existing_nrd) if existing_nrd else tomorrow_str
        # Same-day success after feedback does NOT advance stage or increment review_count
    elif is_new_item:
        # Newly studied and assessed on Day 1: baseline stage 0 -> tomorrow
        record["review_count"] = 1
        record["last_review_date"] = today_str
        record["level"] = level
        record["last_outcome"] = outcome
        record["review_stage"] = 0
        record["next_review_date"] = tomorrow_str
        if outcome == "failed":
            record["lapse_count"] = 1
    else:
        is_due = (existing_nrd is None) or (today_str >= existing_nrd)
        record["review_count"] = record.get("review_count", 0) + 1
        record["last_review_date"] = today_str
        record["level"] = level
        record["last_outcome"] = outcome

        if not is_due:
            # EARLY REVIEW (today_str < existing_nrd):
            if outcome in ("recalled", "productive") or level >= 2:
                # Early successful review MUST NOT advance stage or postpone scheduled review date!
                record["review_stage"] = curr_stage
                record["next_review_date"] = existing_nrd
            elif outcome == "assisted" or level == 1:
                # May shorten schedule to tomorrow (since today < existing_nrd, tomorrow <= existing_nrd)
                record["review_stage"] = curr_stage
                record["next_review_date"] = min(tomorrow_str, existing_nrd)
            else:
                # Failed recall resets stage to 0 and schedules tomorrow
                record["review_stage"] = 0
                record["next_review_date"] = min(tomorrow_str, existing_nrd)
                record["lapse_count"] = record.get("lapse_count", 0) + 1
        else:
            # DUE REVIEW (today_str >= existing_nrd):
            if outcome in ("recalled", "productive") or level >= 2:
                new_stage = min(5, curr_stage + 1)
                gap = STAGE_GAPS[new_stage]
                record["review_stage"] = new_stage
                record["next_review_date"] = (today + datetime.timedelta(days=gap)).isoformat()
            elif outcome == "assisted" or level == 1:
                record["review_stage"] = curr_stage
                record["next_review_date"] = tomorrow_str
            else:
                record["review_stage"] = 0
                record["next_review_date"] = tomorrow_str
                record["lapse_count"] = record.get("lapse_count", 0) + 1

    if error_event:
        record.setdefault("errors", []).append(error_event)

    return record


def save_vocabulary_batch(
    updates: List[Dict[str, Any]],
    user_consented: bool = False,
    progress_file: Optional[Path] = None,
) -> Dict[str, Any]:
    """Persists a batch of vocabulary records only if user explicitly consented."""
    if not user_consented:
        return {
            "saved": False,
            "reason": "user_consent_required",
            "message": "Không thể lưu tiến độ khi người học chưa đồng ý (User consent required).",
        }

    p_file = progress_file or DEFAULT_PROGRESS_FILE
    p_file.parent.mkdir(parents=True, exist_ok=True)

    journal = load_vocabulary_journal(p_file)

    for upd in updates:
        k = upd.get("entry_key")
        if not k:
            k = build_entry_key(upd["expression"], upd["pos"], upd.get("sense_key", ""))
            upd["entry_key"] = k
        journal[k] = upd

    tmp_file = p_file.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        for rec in journal.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp_file.replace(p_file)

    return {
        "saved": True,
        "total_records": len(journal),
        "updated_batch_count": len(updates),
    }


def get_due_vocabulary(
    target_date: Optional[str] = None,
    progress_file: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Retrieves items whose next_review_date <= target_date (default today), oldest due first."""
    journal = load_vocabulary_journal(progress_file)
    today_str = target_date or datetime.date.today().isoformat()

    due_items = [
        rec for rec in journal.values()
        if rec.get("next_review_date") and rec["next_review_date"] <= today_str
    ]
    due_items.sort(key=lambda x: (x.get("next_review_date", ""), -x.get("lapse_count", 0)))
    return due_items


def compute_textbook_progress(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Computes independent progress metrics per textbook."""
    completed = set(state.get("completed_units", []))
    unit_prog = state.get("unit_progress", {})
    track_pos = state.get("track_positions", {})
    report: Dict[str, Dict[str, Any]] = {}

    for book_id in TEXTBOOK_IDS:
        units = TRACK_DEFINITIONS[book_id]["units"]
        done_count = sum(1 for u in units if u in completed)
        in_prog_count = sum(
            1 for u in units if u not in completed and unit_prog.get(u, {}).get("status") == "in_progress"
        )
        pos = track_pos.get(book_id)
        if not pos and book_id in ("IVU-60", "IVU-65"):
            primary_pos = track_pos.get("PRIMARY_CORE", "")
            if primary_pos.startswith(book_id):
                pos = primary_pos
        if not pos:
            pos = _next_uncompleted_in_track(book_id, state)

        report[book_id] = {
            "label": TRACK_DEFINITIONS[book_id]["label"],
            "total_units": len(units),
            "completed_units": done_count,
            "in_progress_units": in_prog_count,
            "current_position": pos,
            "completion_percent": round((done_count / len(units)) * 100, 1) if units else 0.0,
        }
    return report


def get_progress_report(
    progress_file: Optional[Path] = None,
    curriculum_file: Optional[Path] = None,
    target_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Builds the structured progress report for 'Xem tiến độ'."""
    journal = load_vocabulary_journal(progress_file)
    state = load_curriculum_state(curriculum_file)
    due_items = get_due_vocabulary(target_date=target_date, progress_file=progress_file)

    level_counts = {0: 0, 1: 0, 2: 0, 3: 0}
    stage_counts = {i: 0 for i in range(6)}
    total_lapses = 0
    for rec in journal.values():
        lvl = rec.get("level", 0)
        stg = rec.get("review_stage", 0)
        if lvl in level_counts:
            level_counts[lvl] += 1
        if stg in stage_counts:
            stage_counts[stg] += 1
        total_lapses += rec.get("lapse_count", 0)

    return {
        "vocabulary_journal": {
            "total_items": len(journal),
            "due_today_count": len(due_items),
            "level_breakdown": level_counts,
            "stage_breakdown": stage_counts,
            "total_lapses": total_lapses,
        },
        "curriculum": {
            "active_track": state.get("active_track", "PRIMARY_CORE"),
            "current_unit_key": state.get("current_unit_key"),
            "completed_units_count": len(state.get("completed_units", [])),
            "unfinished_lesson": state.get("unfinished_lesson"),
            "observed_gaps": state.get("observed_gaps", []),
        },
        "textbooks": compute_textbook_progress(state),
    }


def _recommend_next_action(
    state: Dict[str, Any],
    due_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Determines the adaptive recommended next learning action."""
    if due_items:
        return {
            "action_type": "review_due_vocabulary",
            "reason": f"Có {len(due_items)} mục từ vựng đến hạn ôn tập hôm nay (ưu tiên Active Recall trước bài mới).",
            "due_count": len(due_items),
        }

    unf = state.get("unfinished_lesson")
    if isinstance(unf, dict) and unf.get("status") == "in_progress":
        return {
            "action_type": "resume_unfinished_lesson",
            "unit_key": unf.get("unit_key"),
            "mode": unf.get("mode", "unit"),
            "reason": f"Đang có bài học chưa hoàn thành: {unf.get('unit_key')} (có thể tiếp tục ngay).",
        }

    active_track = state.get("active_track", "PRIMARY_CORE")
    next_u = _next_uncompleted_in_track(active_track, state)
    return {
        "action_type": "study_next_unit",
        "track": active_track,
        "unit_key": next_u,
        "reason": f"Tiếp tục lộ trình {active_track}: {next_u}.",
    }


def get_adaptive_roadmap(
    progress_file: Optional[Path] = None,
    curriculum_file: Optional[Path] = None,
    target_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Builds the personalized Adaptive Vocabulary Roadmap for 'Xem lộ trình'."""
    state = load_curriculum_state(curriculum_file)
    due_items = get_due_vocabulary(target_date=target_date, progress_file=progress_file)
    textbook_progress = compute_textbook_progress(state)
    recommended = _recommend_next_action(state, due_items)

    return {
        "active_track": state.get("active_track", "PRIMARY_CORE"),
        "track_positions": state.get("track_positions", {}),
        "primary_backbone": {
            "track_id": "PRIMARY_CORE",
            "description": TRACK_DEFINITIONS["PRIMARY_CORE"]["label"],
            "ivu60_progress": textbook_progress["IVU-60"],
            "ivu65_progress": textbook_progress["IVU-65"],
        },
        "supporting_tracks": {
            "general_vocabulary": [textbook_progress["EVU-B2"], textbook_progress["EVU-ADV"]],
            "collocations": [textbook_progress["ECI-INT"], textbook_progress["ECI-ADV"]],
            "academic": [textbook_progress["AVU"]],
            "paraphrase": [textbook_progress["NB-PARA"]],
        },
        "observed_gaps": state.get("observed_gaps", []),
        "due_reviews_count": len(due_items),
        "unfinished_lesson": state.get("unfinished_lesson"),
        "recommended_next_step": recommended,
    }


def _select_adaptive_topic(state: Dict[str, Any]) -> str:
    """Picks an adaptive topic prioritizing observed gaps, then least-covered shared topics."""
    gaps = state.get("observed_gaps", [])
    for g in gaps:
        if g in TOPIC_TAXONOMY:
            return g

    studied_topics = state.get("topic_progress", {})
    for tid in TOPIC_TAXONOMY:
        if tid not in studied_topics:
            return tid
    return "education_and_learning"


def _load_unit_safely(
    unit_key: str,
    index_file: Optional[Path] = None,
    units_dir: Optional[Path] = None,
    sources_file: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    return get_unit_details(
        unit_key,
        index_file=index_file,
        units_dir=units_dir,
        sources_file=sources_file,
    )


def execute_tutor_command(
    prompt: str,
    progress_file: Optional[Path] = None,
    curriculum_file: Optional[Path] = None,
    index_file: Optional[Path] = None,
    units_dir: Optional[Path] = None,
    sources_file: Optional[Path] = None,
    user_consented: bool = False,
    target_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Routes natural learning commands to Adaptive Roadmap, Track Navigation, Review, and Practice."""
    parsed = parse_learning_intent(prompt)
    intent = parsed["intent"]

    if intent == "SAVE_PROGRESS":
        return {
            "status": "ready",
            "workflow": "Workflow C: Track Progress",
            "user_consented": True,
            "message": "Sẵn sàng lưu kết quả buổi học khi có danh sách mục từ vựng hoàn thành.",
        }

    if intent == "VIEW_PROGRESS":
        report = get_progress_report(
            progress_file=progress_file,
            curriculum_file=curriculum_file,
            target_date=target_date,
        )
        return {
            "status": "ready",
            "workflow": "Workflow E: View Progress",
            "progress_report": report,
        }

    if intent == "VIEW_ROADMAP":
        roadmap = get_adaptive_roadmap(
            progress_file=progress_file,
            curriculum_file=curriculum_file,
            target_date=target_date,
        )
        return {
            "status": "ready",
            "workflow": "Workflow E: Adaptive Vocabulary Roadmap",
            "roadmap": roadmap,
        }

    if intent == "SWITCH_TRACK":
        target_track = parsed["target_track"]
        state = load_curriculum_state(curriculum_file)
        new_state = switch_learning_track(state, target_track)
        if user_consented:
            save_curriculum_state(new_state, curriculum_file, user_consented=True)
        unit_data = _load_unit_safely(
            new_state["current_unit_key"],
            index_file=index_file,
            units_dir=units_dir,
            sources_file=sources_file,
        )
        return {
            "status": "ready",
            "workflow": "Workflow E: Switch Track",
            "active_track": new_state["active_track"],
            "unit_key": new_state["current_unit_key"],
            "title": unit_data.get("title") if unit_data else "",
            "track_positions": new_state["track_positions"],
            "unit_data": unit_data,
        }

    if intent == "RESUME_LESSON":
        state = load_curriculum_state(curriculum_file)
        unf = state.get("unfinished_lesson")
        if isinstance(unf, dict) and unf.get("status") == "in_progress":
            ukey = unf["unit_key"]
            unit_data = _load_unit_safely(
                ukey, index_file=index_file, units_dir=units_dir, sources_file=sources_file
            )
            return {
                "status": "ready",
                "workflow": "Workflow F: Resume Unfinished Lesson",
                "resumed": True,
                "unit_key": ukey,
                "mode": unf.get("mode", "unit"),
                "pending_exercises": unf.get("pending_exercises", []),
                "studied_items": unf.get("studied_items", []),
                "title": unit_data.get("title") if unit_data else "",
                "unit_data": unit_data,
            }

        # Fallback if no unfinished lesson saved: suggest next unit on active track
        next_u = _next_uncompleted_in_track(state.get("active_track", "PRIMARY_CORE"), state)
        unit_data = _load_unit_safely(
            next_u, index_file=index_file, units_dir=units_dir, sources_file=sources_file
        ) if next_u else None
        return {
            "status": "ready",
            "workflow": "Workflow F: Resume (No unfinished lesson -> Next in roadmap)",
            "resumed": False,
            "unit_key": next_u,
            "title": unit_data.get("title") if unit_data else "",
            "unit_data": unit_data,
        }

    if intent == "REVIEW_DUE_VOCABULARY":
        due_items = get_due_vocabulary(target_date=target_date, progress_file=progress_file)
        return {
            "status": "ready",
            "workflow": "Workflow E: Learn (Active Recall / Spaced Review)",
            "due_count": len(due_items),
            "due_items": due_items,
        }

    if intent == "LEARN_UNIT":
        unit_key = parsed["unit_key"]
        unit_data = _load_unit_safely(
            unit_key, index_file=index_file, units_dir=units_dir, sources_file=sources_file
        )
        if not unit_data:
            return {
                "status": "not_found",
                "message": f"Unit {unit_key} không tìm thấy trong Knowledge Base.",
                "parsed_intent": parsed,
            }

        curr_state = load_curriculum_state(curriculum_file)
        pending_ex = [ex.get("exercise_id") for ex in unit_data.get("exercises", []) if ex.get("exercise_id")]
        updated = mark_lesson_started(
            curr_state,
            unit_key,
            mode="unit",
            topic_id=(unit_data.get("topics") or [None])[0],
            pending_exercises=pending_ex,
        )
        if user_consented:
            save_curriculum_state(updated, curriculum_file, user_consented=True)

        return {
            "status": "ready",
            "workflow": "Workflow E: Learn (Unit Mode)",
            "active_track": updated["active_track"],
            "unit_key": unit_key,
            "title": unit_data.get("title"),
            "source_id": unit_data.get("source_id"),
            "theory_sections": len(unit_data.get("theory", {}).get("sections", [])),
            "exercises_count": len(unit_data.get("exercises", [])),
            "unit_data": unit_data,
        }

    if intent == "LEARN_NEXT_UNIT":
        curr_state = load_curriculum_state(curriculum_file)
        active_track = curr_state.get("active_track", "PRIMARY_CORE")
        current = curr_state.get("track_positions", {}).get(active_track) or curr_state.get("current_unit_key")
        next_unit_key = _next_uncompleted_in_track(active_track, curr_state, after_unit=current)

        unit_data = _load_unit_safely(
            next_unit_key, index_file=index_file, units_dir=units_dir, sources_file=sources_file
        ) if next_unit_key else None
        if unit_data:
            pending_ex = [ex.get("exercise_id") for ex in unit_data.get("exercises", []) if ex.get("exercise_id")]
            curr_state = mark_lesson_started(
                curr_state,
                next_unit_key,
                mode="unit",
                topic_id=(unit_data.get("topics") or [None])[0],
                pending_exercises=pending_ex,
            )
            if user_consented:
                save_curriculum_state(curr_state, curriculum_file, user_consented=True)

        return {
            "status": "ready",
            "workflow": "Workflow E: Learn (Sequential Progression)",
            "active_track": active_track,
            "previous_unit": current,
            "next_unit_key": next_unit_key,
            "title": unit_data.get("title") if unit_data else "",
            "unit_data": unit_data,
        }

    if intent == "LEARN_TOPIC":
        state = load_curriculum_state(curriculum_file)
        topic_id = parsed.get("topic_id") or _select_adaptive_topic(state)
        vocab = query_vocabulary_by_topic(topic_id, limit=5) if Path(VOCAB_KB_DIR / "vocabulary.jsonl").exists() else []
        collocations = query_collocations_by_topic(topic_id, limit=4) if Path(VOCAB_KB_DIR / "collocations.jsonl").exists() else []
        paraphrases = query_paraphrases_by_topic(topic_id, limit=3) if Path(VOCAB_KB_DIR / "paraphrases.jsonl").exists() else []

        return {
            "status": "ready",
            "workflow": "Workflow E: Learn (Topic Mode)",
            "topic_id": topic_id,
            "auto_selected": parsed.get("topic_id") is None,
            "vocabulary_items": vocab,
            "collocations": collocations,
            "paraphrases": paraphrases,
        }

    if intent == "LEARN_COLLOCATION":
        state = load_curriculum_state(curriculum_file)
        topic_id = parsed.get("topic_id")
        collocations = []
        if topic_id and Path(VOCAB_KB_DIR / "collocations.jsonl").exists():
            collocations = query_collocations_by_topic(topic_id, limit=5)

        # Auto-select next uncompleted unit from ECI-INT -> ECI-ADV
        target_unit = _next_uncompleted_in_track("ECI-INT", state)
        if not target_unit:
            target_unit = _next_uncompleted_in_track("ECI-ADV", state)
        unit_data = _load_unit_safely(
            target_unit, index_file=index_file, units_dir=units_dir, sources_file=sources_file
        ) if target_unit else None

        return {
            "status": "ready",
            "workflow": "Workflow E: Learn Collocation (Adaptive)",
            "topic_id": topic_id,
            "recommended_unit_key": target_unit,
            "title": unit_data.get("title") if unit_data else "",
            "collocations": collocations,
            "unit_data": unit_data,
        }

    if intent == "LEARN_PARAPHRASE":
        state = load_curriculum_state(curriculum_file)
        topic_id = parsed.get("topic_id")
        paraphrases = []
        if topic_id and Path(VOCAB_KB_DIR / "paraphrases.jsonl").exists():
            paraphrases = query_paraphrases_by_topic(topic_id, limit=5)

        # Auto-select next uncompleted section from NB-PARA
        target_unit = _next_uncompleted_in_track("NB-PARA", state)
        unit_data = _load_unit_safely(
            target_unit, index_file=index_file, units_dir=units_dir, sources_file=sources_file
        ) if target_unit else None

        return {
            "status": "ready",
            "workflow": "Workflow E: Learn Paraphrase (Adaptive)",
            "topic_id": topic_id,
            "recommended_unit_key": target_unit,
            "title": unit_data.get("title") if unit_data else "",
            "paraphrases": paraphrases,
            "unit_data": unit_data,
        }

    if intent == "LEARN_VOCABULARY":
        state = load_curriculum_state(curriculum_file)
        due_items = get_due_vocabulary(target_date=target_date, progress_file=progress_file)
        rec = _recommend_next_action(state, due_items)

        target_unit = rec.get("unit_key")
        if not target_unit:
            target_unit = _next_uncompleted_in_track(state.get("active_track", "PRIMARY_CORE"), state)

        unit_data = _load_unit_safely(
            target_unit, index_file=index_file, units_dir=units_dir, sources_file=sources_file
        ) if target_unit else None

        return {
            "status": "ready",
            "workflow": "Workflow E: Adaptive Vocabulary Learning",
            "due_reviews_count": len(due_items),
            "due_items": due_items,
            "recommendation": rec,
            "unit_key": target_unit,
            "title": unit_data.get("title") if unit_data else "",
            "unit_data": unit_data,
        }

    return {
        "status": "unhandled",
        "parsed_intent": parsed,
    }
