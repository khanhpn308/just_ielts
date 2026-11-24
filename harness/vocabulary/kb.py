"""Vocabulary Knowledge Base: Lexical Data Model, Storage, Indexing, and Selective Retrieval.

Non-destructive, idempotent KB builder supporting sense-based deduplication,
provenance preservation, stale cache invalidation, and concealed answer-key practice.
All copyrighted source-derived pilot data is loaded from private storage.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from harness.config import REPO_ROOT
from harness.vocabulary.inventory import VOCAB_KB_DIR, VOCAB_RAW_DIR
from harness.vocabulary.parser import FamilyAParser, FamilyBParser, FamilyCParser, save_parsed_unit

PROCESSING_VERSION = "1.1.0"

KB_UNITS_DIR = VOCAB_KB_DIR / "units"
KB_ENRICHED_DIR = VOCAB_KB_DIR / "enriched"
KB_VOCAB_FILE = VOCAB_KB_DIR / "vocabulary.jsonl"
KB_COLLOCATIONS_FILE = VOCAB_KB_DIR / "collocations.jsonl"
KB_PARAPHRASES_FILE = VOCAB_KB_DIR / "paraphrases.jsonl"
KB_EXERCISES_FILE = VOCAB_KB_DIR / "exercises.jsonl"
KB_ANSWER_KEYS_FILE = VOCAB_KB_DIR / "answer_keys.jsonl"
KB_LEXICAL_INDEX_FILE = VOCAB_KB_DIR / "lexical_index.json"
KB_SEED_FILE = VOCAB_KB_DIR / "seed_education.json"


def normalize_expression(expr: str) -> str:
    """Normalizes expression: NFKC, lowercase, collapse whitespace, strip trailing punctuation."""
    import unicodedata
    norm = unicodedata.normalize("NFKC", expr).strip().lower()
    norm = re.sub(r"[.,;:!?]+$", "", norm).strip()
    return re.sub(r"\s+", " ", norm)


def build_entry_key(expression: str, pos: str, sense_key: str) -> str:
    """Creates pipe-separated canonical entry key: expr|pos|sense with escaped pipes."""
    def escape_pipe(s: str) -> str:
        return s.replace("%", "%25").replace("|", "%7C")
    return f"{escape_pipe(normalize_expression(expression))}|{escape_pipe(pos.strip().lower())}|{escape_pipe(sense_key.strip().lower())}"


def load_seed_data() -> Dict[str, List[Dict[str, Any]]]:
    """Loads private seed data if present without hardcoding copyrighted excerpts in tracked code."""
    if KB_SEED_FILE.exists():
        try:
            with open(KB_SEED_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "vocabulary": [],
        "collocations": [],
        "paraphrases": [],
        "exercises": [],
        "answer_keys": [],
    }


def merge_lexical_entries(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Merges two entries with the same sense-based identity, preserving all valid source references."""
    merged = dict(existing)
    for k, v in incoming.items():
        if v is not None and v != "" and v != []:
            if k not in merged or merged[k] is None or merged[k] == "" or merged[k] == []:
                merged[k] = v

    # Preserve and merge all source references without duplicates
    merged_sources = list(existing.get("sources", []))
    seen_sources = {
        (s.get("source_id"), s.get("unit_key"), s.get("physical_page", s.get("printed_page")))
        for s in merged_sources
    }
    for s in incoming.get("sources", []):
        key = (s.get("source_id"), s.get("unit_key"), s.get("physical_page", s.get("printed_page")))
        if key not in seen_sources:
            seen_sources.add(key)
            merged_sources.append(s)
    merged["sources"] = merged_sources
    return merged


def build_knowledge_base() -> Dict[str, int]:
    """Builds or updates the Vocabulary Knowledge Base idempotently and non-destructively.

    Preserves previously enriched items and deduplicates by expression + POS + sense.
    """
    VOCAB_KB_DIR.mkdir(parents=True, exist_ok=True)
    KB_UNITS_DIR.mkdir(parents=True, exist_ok=True)
    KB_ENRICHED_DIR.mkdir(parents=True, exist_ok=True)

    seed = load_seed_data()

    # 1. Non-destructive Vocabulary sync
    vocab_entries: Dict[str, Dict[str, Any]] = {}

    # Read existing entries first
    if KB_VOCAB_FILE.exists():
        with open(KB_VOCAB_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                item = json.loads(line)
                k = build_entry_key(
                    item.get("expression", ""),
                    item.get("pos", ""),
                    item.get("sense_key", item.get("lemma", ""))
                )
                vocab_entries[k] = item

    # Merge incoming seed entries
    for item in seed.get("vocabulary", []):
        k = build_entry_key(
            item.get("expression", ""),
            item.get("pos", ""),
            item.get("sense_key", item.get("lemma", ""))
        )
        if k in vocab_entries:
            vocab_entries[k] = merge_lexical_entries(vocab_entries[k], item)
        else:
            vocab_entries[k] = item

    # Write back atomically
    tmp_vocab = KB_VOCAB_FILE.with_suffix(".tmp")
    with open(tmp_vocab, "w", encoding="utf-8") as f:
        for item in vocab_entries.values():
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    tmp_vocab.replace(KB_VOCAB_FILE)

    # 2. Consistent Lexical Index: map entry_key and norm_expr
    lexical_index: Dict[str, Any] = {
        "schema_version": "1.1.0",
        "processing_version": PROCESSING_VERSION,
        "entries": {},
    }
    for item in vocab_entries.values():
        norm_expr = normalize_expression(item["expression"])
        entry_key = build_entry_key(item["expression"], item["pos"], item.get("sense_key", item.get("lemma", "")))
        entry_summary = {
            "item_id": item["item_id"],
            "entry_key": entry_key,
            "expression": item["expression"],
            "pos": item["pos"],
            "sense_key": item.get("sense_key", ""),
            "meaning_vi": item.get("meaning_vi", ""),
            "sources": [s.get("source_id") for s in item.get("sources", []) if s.get("source_id")],
        }
        lexical_index["entries"][entry_key] = entry_summary

        # Backward compatibility for direct expression/lemma lookup
        if norm_expr not in lexical_index:
            lexical_index[norm_expr] = []
        lexical_index[norm_expr].append(entry_summary)
        # Direct lookup by item_id or entry_key
        lexical_index[entry_key] = entry_summary

    tmp_idx = KB_LEXICAL_INDEX_FILE.with_suffix(".tmp")
    with open(tmp_idx, "w", encoding="utf-8") as f:
        json.dump(lexical_index, f, indent=2, ensure_ascii=False)
    tmp_idx.replace(KB_LEXICAL_INDEX_FILE)

    # 3. Collocations sync
    colloc_map: Dict[str, Dict[str, Any]] = {}
    if KB_COLLOCATIONS_FILE.exists():
        with open(KB_COLLOCATIONS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                c = json.loads(line)
                colloc_map[c.get("collocation_id", c.get("expression", ""))] = c

    for c in seed.get("collocations", []):
        cid = c.get("collocation_id", c.get("expression", ""))
        if cid not in colloc_map:
            colloc_map[cid] = c

    tmp_col = KB_COLLOCATIONS_FILE.with_suffix(".tmp")
    with open(tmp_col, "w", encoding="utf-8") as f:
        for c in colloc_map.values():
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    tmp_col.replace(KB_COLLOCATIONS_FILE)

    # 4. Paraphrases sync
    para_map: Dict[str, Dict[str, Any]] = {}
    if KB_PARAPHRASES_FILE.exists():
        with open(KB_PARAPHRASES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                p = json.loads(line)
                para_map[p.get("paraphrase_id", p.get("original_expression", ""))] = p

    for p in seed.get("paraphrases", []):
        pid = p.get("paraphrase_id", p.get("original_expression", ""))
        if pid not in para_map:
            para_map[pid] = p

    tmp_para = KB_PARAPHRASES_FILE.with_suffix(".tmp")
    with open(tmp_para, "w", encoding="utf-8") as f:
        for p in para_map.values():
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    tmp_para.replace(KB_PARAPHRASES_FILE)

    # 5. Exercises and Answer Keys sync (Strict concealment)
    ex_map: Dict[str, Dict[str, Any]] = {}
    ak_map: Dict[str, Dict[str, Any]] = {}

    if KB_EXERCISES_FILE.exists():
        with open(KB_EXERCISES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                e = json.loads(line)
                ex_map[e["exercise_id"]] = e

    if KB_ANSWER_KEYS_FILE.exists():
        with open(KB_ANSWER_KEYS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                a = json.loads(line)
                ak_map[a["exercise_id"]] = a

    for ex in seed.get("exercises", []):
        eid = ex["exercise_id"]
        # Conceal answer key from exercise practice presentation
        cleaned_ex = {k: v for k, v in ex.items() if k != "acceptable_answers"}
        cleaned_ex["hidden_key"] = True
        if eid not in ex_map:
            ex_map[eid] = cleaned_ex

        # Store answer key separately
        if "acceptable_answers" in ex:
            if eid not in ak_map:
                ak_map[eid] = {
                    "exercise_id": eid,
                    "source_id": ex.get("source_id", ""),
                    "unit_key": ex.get("unit_key", ""),
                    "exercise_number": ex.get("exercise_number", ""),
                    "acceptable_answers": ex["acceptable_answers"],
                    "verification_status": ex.get("verification_status", "authoritative_textbook_key"),
                }

    for ak in seed.get("answer_keys", []):
        eid = ak["exercise_id"]
        if eid not in ak_map:
            ak_map[eid] = ak

    tmp_ex = KB_EXERCISES_FILE.with_suffix(".tmp")
    with open(tmp_ex, "w", encoding="utf-8") as f:
        for e in ex_map.values():
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    tmp_ex.replace(KB_EXERCISES_FILE)

    tmp_ak = KB_ANSWER_KEYS_FILE.with_suffix(".tmp")
    with open(tmp_ak, "w", encoding="utf-8") as f:
        for a in ak_map.values():
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    tmp_ak.replace(KB_ANSWER_KEYS_FILE)

    counts = {
        "vocab_items": len(vocab_entries),
        "collocations": len(colloc_map),
        "paraphrases": len(para_map),
        "exercises": len(ex_map),
    }
    print(f"Knowledge Base built (non-destructive): {counts['vocab_items']} vocab items, {counts['collocations']} collocations, {counts['paraphrases']} paraphrases, {counts['exercises']} exercises.")
    return counts


def get_unit_details(unit_key: str, force_reextract: bool = False) -> Optional[Dict[str, Any]]:
    """Retrieves full details for a unit, invalidating stale caches using processing version."""
    index_file = VOCAB_KB_DIR / "unit_index.json"
    if not index_file.exists():
        return None
    with open(index_file, "r", encoding="utf-8") as f:
        unit_idx = json.load(f)

    unit_info = unit_idx.get(unit_key)
    if not unit_info:
        for k, v in unit_idx.items():
            if k.lower() == unit_key.lower():
                unit_info = v
                unit_key = k
                break
    if not unit_info:
        return None

    source_id = unit_info["source_id"]
    cached_path = KB_UNITS_DIR / source_id / f"{unit_key}.json"

    # Check cache validity
    if cached_path.exists() and not force_reextract:
        try:
            with open(cached_path, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                # Invalidate stale caches if processing version doesn't match
                if cached_data.get("processing_version") == PROCESSING_VERSION and cached_data.get("source_id") == source_id:
                    return cached_data
        except Exception:
            pass

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

    parsed["processing_version"] = PROCESSING_VERSION
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
    """Retrieves an exercise and returns (exercise_data_without_answers, acceptable_answers).

    Ensures answer keys remain strictly concealed until evaluation.
    """
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
