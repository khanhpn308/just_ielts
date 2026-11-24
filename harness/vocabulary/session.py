"""Vocabulary Session, Curriculum Progression and Spaced Review Manager.

Implements the PR #10 Vocabulary Progress Contract:
- Level 0–3 (unknown/failed, recognized, recalled, productive).
- Stage 0–5 spaced repetition review schedule (Gaps: 1, 2, 3, 7, 16, 30 days).
- Sense-based journal identity (expression + POS + sense_key).
- One current record per identity in private/progress/vocabulary.jsonl.
- Prevention of duplicate records and repeated same-day advancement.
- Explicit user consent required before persisting progress or curriculum state.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from harness.vocabulary.kb import (
    VOCAB_KB_DIR,
    build_entry_key,
    normalize_expression,
    get_unit_details,
    query_vocabulary_by_topic,
    query_collocations_by_topic,
    query_paraphrases_by_topic,
)

DEFAULT_PROGRESS_FILE = Path("private/progress/vocabulary.jsonl")
DEFAULT_CURRICULUM_FILE = Path("private/progress/curriculum.json")

# Primary curriculum backbone order
CURRICULUM_BACKBONE = [f"IVU-60-U{i:03d}" for i in range(1, 26)] + [f"IVU-65-U{i:03d}" for i in range(1, 26)]

# Baseline schedule gaps for Review Stage 0..5 (in days)
STAGE_GAPS = [1, 2, 3, 7, 16, 30]


def parse_learning_intent(prompt: str) -> Dict[str, Any]:
    """Deterministically identifies the vocabulary learning intent from user input."""
    p_lower = prompt.lower().strip()

    # 1. User consent to save: "lưu kết quả buổi học", "lưu tiến độ", "save progress"
    if any(k in p_lower for k in ["lưu kết quả buổi học", "lưu kết quả", "lưu tiến độ", "save progress"]):
        return {
            "intent": "SAVE_PROGRESS",
            "user_consented": True,
            "raw_prompt": prompt,
        }

    # 2. Review due vocabulary: "ôn từ vựng hôm nay", "ôn từ vựng đến hạn", "review due vocabulary"
    if any(k in p_lower for k in ["ôn từ vựng hôm nay", "ôn từ vựng", "review vocabulary", "ôn tập từ vựng"]):
        return {
            "intent": "REVIEW_DUE_VOCABULARY",
            "raw_prompt": prompt,
        }

    # 3. Next unit in curriculum: "học unit tiếp theo", "bài tiếp theo", "next unit"
    if any(k in p_lower for k in ["học unit tiếp theo", "unit tiếp theo", "bài tiếp theo", "next unit"]):
        return {
            "intent": "LEARN_NEXT_UNIT",
            "raw_prompt": prompt,
        }

    # 4. Specific unit: e.g. "Học IVU-60 Unit 1", "Học EVU-B2 Unit 14", "Học AVU Unit 37"
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

    # 5. Topic-based: "Học từ vựng chủ đề Education", "Luyện từ vựng Environment"
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
    """Loads current curriculum position and completed units."""
    c_file = curriculum_file or DEFAULT_CURRICULUM_FILE
    if not c_file.exists():
        return {
            "current_unit_key": CURRICULUM_BACKBONE[0],
            "completed_units": [],
            "last_updated": None,
        }
    with open(c_file, "r", encoding="utf-8") as f:
        return json.load(f)


def save_curriculum_state(
    state: Dict[str, Any],
    curriculum_file: Optional[Path] = None,
    user_consented: bool = False,
) -> bool:
    """Saves updated curriculum position only if user consented."""
    if not user_consented:
        return False

    c_file = curriculum_file or DEFAULT_CURRICULUM_FILE
    c_file.parent.mkdir(parents=True, exist_ok=True)
    state["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    tmp_file = c_file.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    tmp_file.replace(c_file)
    return True


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
    """Calculates updated journal record following Level 0-3 and Stage 0-5 spaced repetition rules.

    - outcome: 'not_assessed', 'failed', 'assisted', 'recalled', or 'productive'.
    - If outcome is 'not_assessed' (new item taught), last_review_date remains null, review_count=0.
    - Level 0 ('failed'): resets stage to 0, schedules tomorrow.
    - Level 1 ('assisted' / recognized): stage unchanged, schedules tomorrow.
    - Level 2 ('recalled') or Level 3 ('productive'): advances stage by 1 (capped at 5).
    - Prevents repeated same-day advancement.
    """
    today = session_date or datetime.date.today()
    today_str = today.isoformat()
    entry_key = build_entry_key(expression, pos, sense_key)

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
        "next_review_date": (today + datetime.timedelta(days=1)).isoformat(),
        "last_outcome": "not_assessed",
        "review_count": 0,
        "lapse_count": 0,
        "errors": [],
    }

    # Determine explicit outcome
    if outcome is None:
        if existing_record is None and level == 0:
            outcome = "not_assessed"
        else:
            outcome_names = {0: "failed", 1: "assisted", 2: "recalled", 3: "productive"}
            outcome = outcome_names.get(level, "not_assessed")

    if outcome == "not_assessed":
        record["last_outcome"] = "not_assessed"
        record["level"] = 0
        record["review_stage"] = 0
        record["last_review_date"] = None
        record["next_review_date"] = (today + datetime.timedelta(days=1)).isoformat()
        if error_event:
            record.setdefault("errors", []).append(error_event)
        return record

    already_reviewed_today = (record.get("last_review_date") == today_str)
    curr_stage = record.get("review_stage", 0)

    if already_reviewed_today:
        # Same-day retry: cannot advance stage again.
        # But an observed failure can reset stage and shorten schedule.
        if outcome == "failed":
            record["review_stage"] = 0
            record["next_review_date"] = (today + datetime.timedelta(days=1)).isoformat()
            record["last_outcome"] = "failed"
            record["level"] = 0
            record["lapse_count"] = record.get("lapse_count", 0) + 1
    else:
        # First assessment today
        record["review_count"] = record.get("review_count", 0) + 1
        record["last_review_date"] = today_str
        record["level"] = level
        record["last_outcome"] = outcome

        if outcome in ["recalled", "productive"] or level >= 2:
            new_stage = min(5, curr_stage + 1)
            gap = STAGE_GAPS[new_stage]
            record["review_stage"] = new_stage
            record["next_review_date"] = (today + datetime.timedelta(days=gap)).isoformat()
        elif outcome == "assisted" or level == 1:
            record["review_stage"] = curr_stage
            record["next_review_date"] = (today + datetime.timedelta(days=1)).isoformat()
        else:
            # Failed
            record["review_stage"] = 0
            record["next_review_date"] = (today + datetime.timedelta(days=1)).isoformat()
            record["lapse_count"] = record.get("lapse_count", 0) + 1

    if error_event:
        record.setdefault("errors", []).append(error_event)

    return record

    if error_event:
        record.setdefault("errors", []).append(error_event)

    return record


def save_vocabulary_batch(
    updates: List[Dict[str, Any]],
    user_consented: bool = False,
    progress_file: Optional[Path] = None,
) -> Dict[str, Any]:
    """Persists a batch of vocabulary records only if user consented.

    Uses atomic replacement and prevents duplicate records.
    """
    if not user_consented:
        return {
            "saved": False,
            "reason": "user_consent_required",
            "message": "Không thể lưu tiến độ khi người học chưa đồng ý (User consent required).",
        }

    p_file = progress_file or DEFAULT_PROGRESS_FILE
    p_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. Read existing records
    journal = load_vocabulary_journal(p_file)

    # 2. Upsert updates by unique entry_key
    for upd in updates:
        k = upd.get("entry_key")
        if not k:
            k = build_entry_key(upd["expression"], upd["pos"], upd.get("sense_key", ""))
            upd["entry_key"] = k
        journal[k] = upd

    # 3. Atomically write to temp file then replace
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
    """Retrieves items whose next_review_date <= target_date (default today)."""
    journal = load_vocabulary_journal(progress_file)
    today_str = target_date or datetime.date.today().isoformat()

    due_items = []
    for rec in journal.values():
        nrd = rec.get("next_review_date")
        if nrd and nrd <= today_str:
            due_items.append(rec)

    # Sort oldest due first
    due_items.sort(key=lambda x: x.get("next_review_date", ""))
    return due_items


def execute_tutor_command(
    prompt: str,
    progress_file: Optional[Path] = None,
    curriculum_file: Optional[Path] = None,
    user_consented: bool = False,
) -> Dict[str, Any]:
    """Routes learning commands to appropriate workflows respecting consent and progress rules."""
    parsed = parse_learning_intent(prompt)
    intent = parsed["intent"]

    if intent == "SAVE_PROGRESS":
        return {
            "status": "ready",
            "workflow": "Workflow C: Track Progress",
            "user_consented": True,
            "message": "Sẵn sàng lưu kết quả buổi học khi có danh sách mục từ vựng hoàn thành.",
        }

    elif intent == "LEARN_UNIT":
        unit_key = parsed["unit_key"]
        unit_data = get_unit_details(unit_key)
        if not unit_data:
            return {
                "status": "not_found",
                "message": f"Unit {unit_key} không tìm thấy trong Knowledge Base.",
                "parsed_intent": parsed,
            }

        # Curriculum state is only persisted if user explicitly consented
        curr_state = load_curriculum_state(curriculum_file)
        curr_state["current_unit_key"] = unit_key
        if user_consented:
            save_curriculum_state(curr_state, curriculum_file, user_consented=True)

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
        if user_consented:
            save_curriculum_state(curr_state, curriculum_file, user_consented=True)

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
