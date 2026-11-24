"""Generalized On-Demand Vocabulary Enrichment Pipeline.

Distinguishes source facts from tutor-generated semantic enrichment.
Python deterministically extracts source-grounded vocabulary candidates,
context sentences, and textbook glosses/footnotes.
The Tutor Agent provides semantic enrichment (IPA, CEFR, register, meaning_vi, collocations)
and persists results on demand without introducing external LLM APIs, fabricating fake defaults,
or attributing unmatched Tutor-generated items to an authoritative textbook.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness.vocabulary.inventory import PROCESSING_VERSION, get_source_sha256
from harness.vocabulary.kb import (
    VOCAB_KB_DIR,
    KB_UNITS_DIR,
    KB_VOCAB_FILE,
    KB_LEXICAL_INDEX_FILE,
    build_entry_key,
    normalize_expression,
    merge_lexical_entries,
    get_unit_details,
    is_cache_valid,
)

ENRICHED_UNITS_DIR = VOCAB_KB_DIR / "enriched"


def get_enriched_unit_path(
    source_id: str,
    unit_key: str,
    enriched_dir: Optional[Path] = None,
) -> Path:
    base = enriched_dir or ENRICHED_UNITS_DIR
    return base / source_id / f"{unit_key}.json"


def _get_unit_searchable_text(parsed_unit: Dict[str, Any]) -> str:
    """Collects all extracted text from a parsed unit for evidence verification."""
    parts: List[str] = []
    theory = parsed_unit.get("theory", {})
    if isinstance(theory, dict):
        if theory.get("raw_text"):
            parts.append(theory["raw_text"])
        for sec in theory.get("sections", []):
            if sec.get("title"):
                parts.append(sec["title"])
            if sec.get("content"):
                parts.append(sec["content"])
        for box_key in ("vocabulary_notes", "error_warnings", "test_tips"):
            for b in theory.get(box_key, []):
                parts.append(str(b))
    if parsed_unit.get("raw_text"):
        parts.append(parsed_unit["raw_text"])
    for ex in parsed_unit.get("exercises", []):
        if ex.get("instructions"):
            parts.append(ex["instructions"])
        if ex.get("content"):
            parts.append(ex["content"])
    return "\n".join(parts)


def find_source_evidence_in_unit(expression: str, parsed_unit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Checks if expression actually appears in the parsed unit's extracted text.

    Returns a source-grounded candidate dict if verified, or None if unmatched.
    """
    norm_expr = normalize_expression(expression)
    if not norm_expr:
        return None
    searchable = _get_unit_searchable_text(parsed_unit)
    if not searchable:
        return None

    # Allow flexible whitespace between words in expression
    words = [re.escape(w) for w in norm_expr.split()]
    pat = re.compile(r"\b" + r"\s+".join(words) + r"\b", re.IGNORECASE)
    for line in searchable.splitlines():
        if pat.search(line):
            return {
                "expression": expression,
                "source_context": line.strip(),
                "source_gloss": "",
                "extraction_method": "source_text_match",
                "source_grounded": True,
                "source_provenance": {
                    "source_id": parsed_unit.get("source_id", ""),
                    "unit_key": parsed_unit.get("unit_key", ""),
                    "page": parsed_unit.get("physical_pages", [0])[0],
                },
            }
    return None


def extract_unit_vocabulary_candidates(parsed_unit: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deterministically extracts candidate vocabulary items and source facts from unit content.

    Extracts expressions, bracketed notes, superscript footnotes, and bulleted/diagram items
    directly grounded in the original source text without fabrication.
    """
    candidates = []
    seen = set()

    source_id = parsed_unit.get("source_id", "")
    unit_key = parsed_unit.get("unit_key", "")
    page = parsed_unit.get("physical_pages", [0])[0]

    raw_text = parsed_unit.get("theory", {}).get("raw_text", "") or parsed_unit.get("raw_text", "")

    # Pattern 1: Numbered superscript footnotes
    footnote_defs = dict(re.findall(r"^(\d)\s+([^\n]+)", raw_text, re.MULTILINE))
    footnote_terms = re.findall(r"([A-Za-z\s\-\'/]{3,35}?)(\d)\b", raw_text)
    for term, num in footnote_terms:
        clean_term = term.strip().strip("-").strip()
        if clean_term and clean_term.lower() not in seen and len(clean_term) >= 3 and not clean_term.isupper():
            seen.add(clean_term.lower())
            candidates.append({
                "expression": clean_term,
                "source_context": f"{clean_term} {footnote_defs.get(num, '')}".strip(),
                "source_gloss": footnote_defs.get(num, ""),
                "extraction_method": "source_footnote",
                "source_grounded": True,
                "source_provenance": {
                    "source_id": source_id,
                    "unit_key": unit_key,
                    "page": page,
                    "footnote_index": num,
                },
            })

    # Pattern 2: Defined expressions with brackets like "term [definition]"
    bracket_matches = re.findall(r"([A-Za-z\s\-\'/]{3,40})\s+\[(.*?)\]", raw_text)
    for expr, hint in bracket_matches:
        expr_clean = expr.strip()
        if len(expr_clean) > 2 and expr_clean.lower() not in seen and not expr_clean.isupper():
            seen.add(expr_clean.lower())
            candidates.append({
                "expression": expr_clean,
                "source_context": f"{expr_clean} [{hint.strip()}]",
                "source_gloss": hint.strip(),
                "extraction_method": "bracketed_source_note",
                "source_grounded": True,
                "source_provenance": {
                    "source_id": source_id,
                    "unit_key": unit_key,
                    "page": page,
                },
            })

    # Pattern 3: Key collocations / phrases in diagram blocks or bullet points
    for line in raw_text.splitlines():
        l_str = line.strip()
        m = re.match(r"^(?:[•\-*]\s*)?((?:to\s+)?[a-z]{3,15}(?:\s+[a-z]{2,15}){1,4})$", l_str)
        if m:
            cand = m.group(1).strip()
            if cand.lower() not in seen and len(cand) >= 5 and " " in cand:
                seen.add(cand.lower())
                candidates.append({
                    "expression": cand,
                    "source_context": l_str,
                    "source_gloss": "",
                    "extraction_method": "source_collocation_phrase",
                    "source_grounded": True,
                    "source_provenance": {
                        "source_id": source_id,
                        "unit_key": unit_key,
                        "page": page,
                    },
                })

    return candidates


def build_tutor_enriched_item(
    candidate: Dict[str, Any],
    pos: str,
    sense_key: str,
    meaning_vi: str,
    meaning_en: str = "",
    us_ipa: Optional[str] = None,
    uk_ipa: Optional[str] = None,
    cefr_level: Optional[str] = None,
    collocations: Optional[List[str]] = None,
    grammar_patterns: Optional[List[str]] = None,
    common_mistakes: Optional[str] = None,
    countability: Optional[str] = None,
    register: Optional[str] = None,
    item_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Combines source facts (when grounded) with Tutor Agent semantic enrichment.

    Strictly preserves provenance:
    - Does NOT fabricate default fake IPA, fake CEFR or fake definitions.
    - Only attributes to an authoritative textbook when source_grounded is True and provenance exists.
    - Unmatched Tutor-generated items are labeled provenance='tutor_created' with source_grounded=False.
    """
    expr = candidate["expression"]
    norm_expr = normalize_expression(expr)
    is_grounded = bool(candidate.get("source_grounded", False))
    prov = candidate.get("source_provenance") or {}

    if is_grounded and prov.get("source_id"):
        prefix = f"VOC-{prov['source_id']}-{prov.get('unit_key', 'U')}"
        source_entry = {
            "kind": "material",
            "source_id": prov.get("source_id", ""),
            "unit_key": prov.get("unit_key", ""),
            "physical_page": prov.get("page", 0),
            "example_sentence": candidate.get("source_context", ""),
            "source_gloss": candidate.get("source_gloss", ""),
            "provenance": "authoritative_textbook",
        }
        extraction_method = candidate.get("extraction_method", "textbook_extraction")
    else:
        is_grounded = False
        prefix = "VOC-TUTOR"
        source_entry = {
            "kind": "tutor_created",
            "ref": None,
            "locator": None,
            "example_sentence": candidate.get("source_context", ""),
            "provenance": "tutor_created",
        }
        extraction_method = "unmatched_tutor_enrichment"

    assigned_id = item_id or f"{prefix}-{abs(hash((norm_expr, pos, sense_key))) % 100000:05d}"

    return {
        "item_id": assigned_id,
        "entry_key": build_entry_key(expr, pos, sense_key),
        "expression": expr,
        "lemma": norm_expr,
        "pos": pos,
        "sense_key": sense_key,
        "us_ipa": us_ipa,
        "uk_ipa": uk_ipa,
        "meaning_en": meaning_en or candidate.get("source_gloss", ""),
        "meaning_vi": meaning_vi,
        "contextual_meaning": candidate.get("source_context", ""),
        "cefr_level": cefr_level,
        "grammar_patterns": grammar_patterns or [],
        "countability": countability,
        "register": register,
        "collocations": collocations or [],
        "common_mistakes": common_mistakes or "",
        "sources": [source_entry],
        "provenance_metadata": {
            "source_grounded": is_grounded,
            "extraction_method": extraction_method,
            "enrichment_agent": "tutor_agent",
            "enriched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }


def persist_enriched_unit_data(
    unit_key: str,
    enriched_items: List[Dict[str, Any]],
    parsed_unit: Dict[str, Any],
    candidates: Optional[List[Dict[str, Any]]] = None,
    enriched_dir: Optional[Path] = None,
    vocab_file: Optional[Path] = None,
    lexical_index_file: Optional[Path] = None,
    source_sha256: Optional[str] = None,
) -> Path:
    """Persists enriched unit outputs to disk and updates vocabulary.jsonl and lexical_index.json."""
    source_id = parsed_unit["source_id"]
    enriched_file = get_enriched_unit_path(source_id, unit_key, enriched_dir=enriched_dir)
    enriched_file.parent.mkdir(parents=True, exist_ok=True)

    # Merge with any existing completed enriched items in this file (if updating)
    existing_enriched_by_key: Dict[str, Dict[str, Any]] = {}
    if enriched_file.exists():
        try:
            old = json.loads(enriched_file.read_text(encoding="utf-8"))
            if is_cache_valid(old, source_id, source_sha256, PROCESSING_VERSION):
                for it in old.get("enriched_vocabulary", []):
                    k = it.get("entry_key") or build_entry_key(it["expression"], it["pos"], it.get("sense_key", ""))
                    existing_enriched_by_key[k] = it
        except Exception:
            pass

    for it in enriched_items:
        k = it.get("entry_key") or build_entry_key(it["expression"], it["pos"], it.get("sense_key", ""))
        if k in existing_enriched_by_key:
            existing_enriched_by_key[k] = merge_lexical_entries(existing_enriched_by_key[k], it)
        else:
            existing_enriched_by_key[k] = it

    final_enriched = list(existing_enriched_by_key.values())
    enrichment_status = "completed" if len(final_enriched) > 0 else "candidates_only"

    enriched_data = {
        "processing_version": PROCESSING_VERSION,
        "source_sha256": source_sha256 or parsed_unit.get("source_sha256"),
        "enrichment_status": enrichment_status,
        "unit_key": unit_key,
        "source_id": source_id,
        "title": parsed_unit.get("title", ""),
        "candidates": candidates or [],
        "enriched_vocabulary": final_enriched,
        "exercises": parsed_unit.get("exercises", []),
        "answer_key": parsed_unit.get("answer_key", {}),
        "enriched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    tmp_enriched = enriched_file.with_suffix(".tmp")
    with open(tmp_enriched, "w", encoding="utf-8") as f:
        json.dump(enriched_data, f, indent=2, ensure_ascii=False)
    tmp_enriched.replace(enriched_file)

    if not final_enriched:
        return enriched_file

    # Non-destructive sync to vocabulary.jsonl
    target_vocab = vocab_file or KB_VOCAB_FILE
    target_vocab.parent.mkdir(parents=True, exist_ok=True)
    existing_by_key: Dict[str, Dict[str, Any]] = {}
    if target_vocab.exists():
        with open(target_vocab, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                k = build_entry_key(
                    entry.get("expression", ""),
                    entry.get("pos", ""),
                    entry.get("sense_key", entry.get("lemma", "")),
                )
                existing_by_key[k] = entry

    for it in final_enriched:
        k = it.get("entry_key") or build_entry_key(it["expression"], it["pos"], it.get("sense_key", ""))
        if k in existing_by_key:
            existing_by_key[k] = merge_lexical_entries(existing_by_key[k], it)
        else:
            existing_by_key[k] = it

    tmp_vocab = target_vocab.with_suffix(".tmp")
    with open(tmp_vocab, "w", encoding="utf-8") as f:
        for it in existing_by_key.values():
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    tmp_vocab.replace(target_vocab)

    # Update lexical index
    target_idx = lexical_index_file or KB_LEXICAL_INDEX_FILE
    lex_index: Dict[str, Any] = {
        "schema_version": "1.1.0",
        "processing_version": PROCESSING_VERSION,
        "entries": {},
    }
    for it in existing_by_key.values():
        k = it.get("entry_key") or build_entry_key(it["expression"], it["pos"], it.get("sense_key", ""))
        norm_expr = normalize_expression(it["expression"])
        summary = {
            "item_id": it["item_id"],
            "entry_key": k,
            "expression": it["expression"],
            "pos": it["pos"],
            "sense_key": it.get("sense_key", ""),
            "meaning_vi": it.get("meaning_vi", ""),
            "sources": [s.get("source_id") for s in it.get("sources", []) if s.get("source_id")],
        }
        lex_index["entries"][k] = summary
        if norm_expr not in lex_index:
            lex_index[norm_expr] = []
        lex_index[norm_expr].append(summary)
        lex_index[k] = summary

    tmp_idx = target_idx.with_suffix(".tmp")
    with open(tmp_idx, "w", encoding="utf-8") as f:
        json.dump(lex_index, f, indent=2, ensure_ascii=False)
    tmp_idx.replace(target_idx)

    return enriched_file


def enrich_unit_pipeline(
    unit_key: str,
    tutor_enrichments: Optional[List[Dict[str, Any]]] = None,
    force_reextract: bool = False,
    index_file: Optional[Path] = None,
    units_dir: Optional[Path] = None,
    enriched_dir: Optional[Path] = None,
    vocab_file: Optional[Path] = None,
    lexical_index_file: Optional[Path] = None,
    sources_file: Optional[Path] = None,
    source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Executes the generalized 7-step on-demand extraction and enrichment workflow for a unit.

    - Invalidates extraction & enrichment caches when source SHA-256 or processing_version changes.
    - Never treats empty or candidate-only enrichment caches as completed enrichment.
    - Never attributes unmatched Tutor-generated items to an authoritative textbook.
    """
    t_start = time.time()
    steps_log = []

    # Step 1: Retrieve Unit from structural index
    idx_path = index_file or (VOCAB_KB_DIR / "unit_index.json")
    if not idx_path.exists():
        raise FileNotFoundError(f"Unit index not found at {idx_path}")

    with open(idx_path, "r", encoding="utf-8") as f:
        unit_idx = json.load(f)

    unit_info = unit_idx.get(unit_key)
    if not unit_info:
        for k, v in unit_idx.items():
            if k.lower() == unit_key.lower():
                unit_info = v
                unit_key = k
                break
    if not unit_info:
        raise ValueError(f"Unit key {unit_key} not found in unit index.")

    source_id = unit_info["source_id"]
    expected_sha = source_sha256 or unit_info.get("source_sha256") or get_source_sha256(source_id, sources_file=sources_file)

    steps_log.append({
        "step": 1,
        "action": "Retrieve Unit from structural index",
        "status": "success",
        "unit_key": unit_key,
        "source_id": source_id,
        "title": unit_info.get("title"),
        "pages": unit_info.get("physical_pages"),
    })

    # Step 7 Check: Return cached enriched unit ONLY if:
    # - file exists & not forcing reextract & no new tutor_enrichments are supplied
    # - source_sha256 and processing_version match
    # - enrichment_status == "completed" and enriched_vocabulary is non-empty!
    enriched_file = get_enriched_unit_path(source_id, unit_key, enriched_dir=enriched_dir)
    if enriched_file.exists() and not force_reextract and not tutor_enrichments:
        t_cache = time.time()
        try:
            with open(enriched_file, "r", encoding="utf-8") as f:
                cached_result = json.load(f)
            is_valid = is_cache_valid(cached_result, source_id, expected_sha, PROCESSING_VERSION)
            is_populated = (
                cached_result.get("enrichment_status") == "completed"
                and len(cached_result.get("enriched_vocabulary", [])) > 0
            )
            if is_valid and is_populated:
                return {
                    "unit_key": unit_key,
                    "source_id": source_id,
                    "from_cache": True,
                    "enrichment_status": "completed",
                    "elapsed_seconds": round(time.time() - t_cache, 4),
                    "steps_log": [
                        {
                            "step": 7,
                            "action": "Cache Hit: Retrieved completed enriched unit without re-extraction",
                            "status": "cached",
                            "path": str(enriched_file),
                        }
                    ],
                    "enriched_unit": cached_result,
                }
        except Exception:
            pass

    # Step 2: Extract source content (checks source SHA-256 and processing_version)
    parsed_unit = get_unit_details(
        unit_key,
        force_reextract=force_reextract,
        units_dir=units_dir,
        index_file=idx_path,
        sources_file=sources_file,
        source_sha256=expected_sha,
    )
    if not parsed_unit:
        raise RuntimeError(f"Failed to extract source content for {unit_key}")

    steps_log.append({
        "step": 2,
        "action": "Extract source content",
        "status": "success",
        "sections_count": len(parsed_unit.get("theory", {}).get("sections", [])),
        "exercises_count": len(parsed_unit.get("exercises", [])),
    })

    # Step 3: Extract source-grounded candidates
    raw_candidates = extract_unit_vocabulary_candidates(parsed_unit)
    steps_log.append({
        "step": 3,
        "action": "Extract source-grounded vocabulary candidates",
        "status": "success",
        "candidates_found": len(raw_candidates),
        "sample_candidates": [c["expression"] for c in raw_candidates[:6]],
    })

    # Step 4: Semantic enrichment via Tutor Agent
    enriched_items = []
    if tutor_enrichments:
        cand_map = {normalize_expression(c["expression"]): c for c in raw_candidates}
        for te in tutor_enrichments:
            expr_norm = normalize_expression(te["expression"])
            # 1. Check extracted candidates
            cand = cand_map.get(expr_norm)
            # 2. Check full parsed unit text for actual source evidence
            if cand is None:
                cand = find_source_evidence_in_unit(te["expression"], parsed_unit)
            # 3. Unmatched Tutor-generated lexical item: DO NOT attribute to textbook!
            if cand is None:
                cand = {
                    "expression": te["expression"],
                    "source_context": te.get("contextual_meaning", ""),
                    "source_gloss": "",
                    "extraction_method": "unmatched_tutor_enrichment",
                    "source_grounded": False,
                    "source_provenance": None,
                }

            item = build_tutor_enriched_item(
                candidate=cand,
                pos=te["pos"],
                sense_key=te["sense_key"],
                meaning_vi=te["meaning_vi"],
                meaning_en=te.get("meaning_en", ""),
                us_ipa=te.get("us_ipa"),
                uk_ipa=te.get("uk_ipa"),
                cefr_level=te.get("cefr_level"),
                collocations=te.get("collocations"),
                grammar_patterns=te.get("grammar_patterns"),
                common_mistakes=te.get("common_mistakes"),
                countability=te.get("countability"),
                register=te.get("register"),
                item_id=te.get("item_id"),
            )
            enriched_items.append(item)

    steps_log.append({
        "step": 4,
        "action": "Enrich selected vocabulary via Tutor Agent",
        "status": "success" if enriched_items else "awaiting_tutor_enrichment",
        "enriched_count": len(enriched_items),
        "items": [it["expression"] for it in enriched_items],
    })

    # Step 5: Retrieve original exercises and answer keys
    exercises = parsed_unit.get("exercises", [])
    answer_key = parsed_unit.get("answer_key", {})
    steps_log.append({
        "step": 5,
        "action": "Retrieve original exercises and answer keys",
        "status": "success",
        "exercises_retrieved": len(exercises),
        "verification_status": answer_key.get("verification_status", answer_key.get("status")),
        "answer_key_items": len(answer_key.get("answers", {})),
    })

    # Step 6: Save reusable knowledge-base outputs
    saved_path = persist_enriched_unit_data(
        unit_key=unit_key,
        enriched_items=enriched_items,
        parsed_unit=parsed_unit,
        candidates=raw_candidates,
        enriched_dir=enriched_dir,
        vocab_file=vocab_file,
        lexical_index_file=lexical_index_file,
        source_sha256=expected_sha,
    )
    saved_payload = json.loads(saved_path.read_text(encoding="utf-8"))
    enrichment_status = saved_payload.get("enrichment_status", "candidates_only")

    steps_log.append({
        "step": 6,
        "action": "Save reusable knowledge-base outputs",
        "status": "success",
        "enrichment_status": enrichment_status,
        "enriched_file": str(saved_path),
    })

    elapsed = round(time.time() - t_start, 4)
    return {
        "unit_key": unit_key,
        "source_id": source_id,
        "from_cache": False,
        "enrichment_status": enrichment_status,
        "elapsed_seconds": elapsed,
        "steps_log": steps_log,
        "candidates": raw_candidates,
        "enriched_unit": saved_payload,
    }
