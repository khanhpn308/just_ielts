"""S03C evidence gate. No source or bundle writes."""

import argparse
from collections import Counter
from contextlib import suppress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from evidence import (Invalid, Sources, digest, json_data, json_lines, load_evidence,
                      nonblank, record_map, require, rooted, sha, shape)


VERSION = "S03C-gate-v1"
BUNDLE = {
    "passage": "passage_reference.json",
    "group": "question_groups.jsonl",
    "question": "questions.jsonl",
    "key": "answer_keys.jsonl",
    "mapping": "canonical_mapping.jsonl",
    "limitation": "source_limitations.jsonl",
}
SCHEMA = {
    "passage": "id volume test passage_number source_id title subtitle paragraphs body_sha256 slots asset_ids",
    "group": "id passage_id source_id question_type instruction context shared_options labels required_answer_count word_limit asset_ids",
    "question": "id passage_id source_id group_id slot_ids prompt options blanks asset_ids",
    "key": "id passage_id source_id question_id orphan_number status raw values alternate_separator authority",
    "mapping": "id entity_type reference_id canonical_ids canonical_slots",
    "limitation": "id target_type target_id kind field reason attempts",
}
CLOZE = {"sentence-completion", "summary-completion", "note-completion", "table-completion",
         "flow-chart-completion", "diagram-label-completion"}
VISUAL = {"table-completion", "flow-chart-completion", "diagram-label-completion"}
CHOICE = {"multiple-choice-single", "multiple-choice-multi"}
BANK = {"matching-headings", "matching-features", "matching-sentence-endings"}
BOOLEAN = {"true-false-not-given": {"T": "TRUE", "F": "FALSE", "NG": "NOT GIVEN"},
           "yes-no-not-given": {"Y": "YES", "N": "NO", "NG": "NOT GIVEN"}}
KINDS = CLOZE | CHOICE | BANK | set(BOOLEAN) | {"matching-information", "short-answer"}
REF_BLOCKERS = {"pending", "unresolved"}
IDENTITY_RE = r"^[A-Za-z0-9._@-]+$"


def identity(value):
    shape(value, "id session", "identity")
    require(all(isinstance(x, str) and re.fullmatch(IDENTITY_RE, x) for x in value.values()),
            "INVALID_IDENTITY", value)


def named_ids(value, where):
    require(isinstance(value, list) and all(nonblank(item) for item in value)
            and len(set(value)) == len(value), "ID_LIST", where)
    return value


def load_batch(batch):
    manifest = json_data(rooted(batch, "batch_manifest.json").read_bytes())
    shape(manifest, "schema scope source_sha256 canonical_inventory_sha256 author files population", "batch manifest")
    require(manifest["schema"] == VERSION, "VERSION", manifest["schema"])
    identity(manifest["author"])
    evidence_name = "evidence_manifest.json"
    require(set(manifest["files"]) == set(BUNDLE.values()) | {evidence_name},
            "BUNDLE_FILES", "manifest")
    files = {name: rooted(batch, name).read_bytes() for name in manifest["files"]}
    for name, raw in files.items():
        require(sha(raw) == manifest["files"][name], "BUNDLE_FILE_HASH", name)
    rows = {kind: record_map([json_data(files[name])] if kind == "passage"
                             else json_lines(files[name]), "id") for kind, name in BUNDLE.items()}
    for kind, group in rows.items():
        for eid, row in group.items():
            shape(row, SCHEMA[kind], f"{kind}/{eid}")
    passage = next(iter(rows["passage"].values()))
    counts = {kind: len(group) for kind, group in rows.items()}
    counts["slots"] = len(passage["slots"])
    require(digest(counts) == digest(manifest["population"]), "POPULATION", "manifest")
    return manifest, rows, json_data(files[evidence_name]), passage


def review_fields(review, rows, claims, spans, source_id, sources):
    fields = review["fields"]
    expected = {f"{kind}/{eid}": row for kind, group in rows.items() for eid, row in group.items()}
    require(set(expected) == set(fields) == set(claims), "ENTITY_COVERAGE", "fields")
    for entity, record in expected.items():
        require(set(record) == set(fields[entity]) == set(claims[entity]),
                "FIELD_COVERAGE", entity)
        for field, value in record.items():
            where = f"{entity}/{field}"
            event = fields[entity][field]
            shape(event, "actual_sha256 expected spans method outcome", where)
            refs = named_ids(event["spans"], where)
            require(refs and refs == claims[entity][field]
                    and all(ref in spans for ref in refs), "FIELD_EVIDENCE", where)
            require(event["actual_sha256"] == digest(value) == digest(event["expected"]),
                    "FIELD_VALUE", where)
            method = event["method"]
            require(event["outcome"] == "match" and method in {"rendered", "native", "derived"},
                    "FIELD_COMPARISON", where)
            evidence_sources = {spans[ref]["source_id"] for ref in refs}
            visual_pdf = any(sources.inventory[spans[ref]["source_id"]]["source_format"] == "pdf"
                             and "native_chars" not in spans[ref]["locator"] for ref in refs)
            if method == "native":
                require(not visual_pdf, "NATIVE_METHOD_ON_VISUAL_PDF", where)
            if entity.startswith("key/") and record["source_id"] is not None:
                require(evidence_sources == {record["source_id"]}, "KEY_PROVENANCE", where)
            else:
                allowed = {source_id}
                if entity.startswith("limitation/") and record["target_type"] == "key":
                    allowed.add(rows["key"][record["target_id"]]["source_id"])
                if entity.startswith("mapping/") and record["entity_type"] == "key":
                    allowed.add(rows["key"][record["reference_id"]]["source_id"])
                if entity.startswith("key/") and record["status"] == "missing":
                    scope = review["scope"]
                    allowed.update(sid for sid, entry in sources.inventory.items()
                                   if "key" in entry["source_role"]
                                   and entry["volume"] == scope["volume"]
                                   and scope["test"] in entry["test_numbers"])
                require(evidence_sources <= allowed, "FIELD_PROVENANCE", where)
            if field in {"title", "subtitle", "instruction", "context", "prompt", "raw"} and value is not None:
                if visual_pdf:
                    require(method == "rendered", "PDF_VERBATIM_METHOD", where)
                joiner = " "
                if field == "raw" and len(refs) > 1 and record["question_id"] in rows["question"]:
                    group_id = rows["question"][record["question_id"]]["group_id"]
                    if (rows["group"][group_id]["question_type"] == "multiple-choice-multi"
                            and all(sources.inventory[sid]["source_format"] == "xlsx"
                                    for sid in evidence_sources)):
                        joiner = ", "
                require(isinstance(value, str)
                        and value == joiner.join(spans[ref]["text"] for ref in refs),
                        "SOURCE_FIELD_TEXT", where)


def verify_body(passage, regions, spans, claims, source_format):
    require(passage["body_sha256"] == digest(passage["paragraphs"]), "BODY_HASH", passage["id"])
    require(isinstance(regions, list) and len(regions) >= 3
            and regions[0]["role"] == "before" and regions[-1]["role"] == "after"
            and all(r["role"] not in {"before", "after"} for r in regions[1:-1]),
            "BODY_BOUNDARIES", passage["id"])
    used, paragraphs, titles = [], [], {}
    positions = []
    for region in regions:
        shape(region, "role spans label", "body region")
        role, refs = region["role"], named_ids(region["spans"], "body regions")
        require(role in {"before", "after", "excluded", "title", "subtitle", "paragraph"}
                and refs, "BODY_REGION", role)
        text = []
        for ref in refs:
            span = spans[ref]
            require(span["source_id"] == passage["source_id"], "BODY_PROVENANCE", ref)
            used.append(ref)
            require(role == "excluded" or nonblank(span["text"]), "EMPTY_BODY_REGION", ref)
            text.append(span["text"])
            locator = span["locator"]
            positions.append(locator["page"] if source_format == "pdf" else locator["element"])
        value = " ".join(text)
        label = region["label"]
        if role == "paragraph":
            require(nonblank(value) and (label is None or nonblank(label)), "PARAGRAPH", refs)
            paragraphs.append({"label": label, "text": value, "spans": refs})
        else:
            require(label is None, "BODY_LABEL", role)
            if role in {"title", "subtitle"}:
                require(role not in titles and nonblank(value), "BODY_HEADING", role)
                require(refs == claims[role], "HEADING_EVIDENCE", role)
                titles[role] = value
    require(len(set(used)) == len(used) and positions == sorted(positions),
            "BODY_SPAN_ORDER_OR_DUPLICATE", passage["id"])
    if source_format == "pdf":
        require(set(positions) == set(range(positions[0], positions[-1] + 1)),
                "BODY_PAGE_GAP", passage["id"])
        boxes = {}
        for ref in used:
            locator = spans[ref]["locator"]
            x0, y0, x1, y1 = locator["box"]
            page_boxes = boxes.setdefault(locator["page"], [])
            require(all(x1 <= a or b <= x0 or y1 <= c or d <= y0 for a, c, b, d in page_boxes),
                    "BODY_REGION_OVERLAP", ref)
            page_boxes.append((x0, y0, x1, y1))
    else:
        for first, second in zip(positions, positions[1:]):
            require(second[:len(first)] != first, "BODY_REGION_OVERLAP", passage["id"])
        blocks = {pos[0] for pos in positions}
        require(blocks == set(range(positions[0][0], positions[-1][0] + 1)),
                "BODY_DOCX_BLOCK_GAP", passage["id"])
    require(all(digest(passage[heading]) == digest(titles.get(heading))
                for heading in ("title", "subtitle")), "BODY_HEADING", passage["id"])
    require(paragraphs and digest(passage["paragraphs"]) == digest(paragraphs),
            "BODY_COVERAGE", passage["id"])
    require(claims["paragraphs"] == [ref for paragraph in paragraphs for ref in paragraph["spans"]],
            "BODY_FIELD_EVIDENCE", passage["id"])
    return set(used)


def limitations(rows, slots):
    held = set()
    pending = set()
    for lid, row in rows["limitation"].items():
        kind, target = row["target_type"], row["target_id"]
        targets = slots if kind == "slot" else rows.get(kind, {})
        require(kind in {"passage", "group", "question", "slot", "key"} and target in targets
                and nonblank(row["reason"]), "LIMITATION_TARGET", lid)
        require(row["kind"] in {"source_defect", *REF_BLOCKERS}
                and type(row["attempts"]) is int and 0 <= row["attempts"] <= 2,
                "LIMITATION_KIND", lid)
        if row["kind"] == "pending":
            require(kind != "slot" and row["field"] in targets[target]
                    and row["field"] != "id", "CORRECTION_FIELD", lid)
            pending.add((kind, target))
        else:
            require(row["field"] is None and row["attempts"] == 0, "LIMITATION_FIELD", lid)
        held.add((kind, target))
    return held, pending


def mappings(rows, questions, slots, catalog, passage, held):
    required = {(kind, eid) for kind in ("passage", "group", "question", "key")
                for eid in rows[kind]}
    seen = set()
    prefixes = {"passage": "PASSAGE-", "group": "QG-", "question": "Q-", "key": "ANS-"}
    by_target = {}
    for mid, row in rows["mapping"].items():
        kind, eid = row["entity_type"], row["reference_id"]
        target = kind, eid
        require(target in required and target not in by_target, "MAPPING_TARGET", mid)
        ids = named_ids(row["canonical_ids"], mid)
        require(all(x.startswith(prefixes[kind]) and re.fullmatch(IDENTITY_RE, x)
                    for x in ids) and (kind == "group" or not seen.intersection(ids)), "CANONICAL_ID", mid)
        canonical_kind = {"group": "question_group", "key": "answer"}.get(kind, kind)
        require(all(x in catalog and catalog[x]["entity_type"] == canonical_kind for x in ids),
                "CANONICAL_TARGET", mid)
        numbers = row["canonical_slots"]
        require(isinstance(numbers, dict) and set(numbers) <= set(ids), "MAPPING_SLOT", mid)
        if kind == "question":
            qslots = questions[eid]["slot_ids"]
            require(set(numbers) == set(ids) and set(numbers.values()) == set(qslots if ids else [])
                    and all(slot in slots for slot in numbers.values())
                    and len(numbers) == len(set(numbers.values())),
                    "MAPPING_SLOT", mid)
        else:
            require(not numbers, "MAPPING_SLOT", mid)
        if kind == "key" and row["canonical_ids"]:
            require(rows["key"][eid]["question_id"] is not None, "ORPHAN_KEY_MAPPING", mid)
        by_target[target] = row
        seen.update(ids)
    require(set(by_target) == required, "MAPPING_COVERAGE", "batch")
    passage_ids = by_target["passage", passage["id"]]["canonical_ids"]
    test_id = f"TEST-IELTS-{passage['volume']}-{passage['test']:02d}-ACAD"
    require(all(catalog[x]["test_id"] == test_id
                and x.endswith(f"-RD{passage['passage_number']:02d}")
                and catalog[x]["source_legacy_id"] == passage["source_id"] for x in passage_ids),
            "CANONICAL_PASSAGE_SCOPE", passage["id"])
    for (kind, eid), row in by_target.items():
        for x in row["canonical_ids"]:
            if kind in {"group", "question"}:
                require(catalog[x]["passage_id"] in passage_ids, "CANONICAL_PASSAGE_SCOPE", x)
            if kind == "question":
                gids = by_target["group", questions[eid]["group_id"]]["canonical_ids"]
                require(catalog[x]["group_id"] in gids or ("question", eid) in held
                        or ("group", questions[eid]["group_id"]) in held, "CANONICAL_GROUP_SCOPE", x)
                sid = row["canonical_slots"][x]
                require(catalog[x]["question_number"] == slots[sid]["number"]
                        or ("slot", sid) in held or ("question", eid) in held,
                        "CANONICAL_QUESTION_NUMBER", x)
            if kind == "key":
                qid = rows["key"][eid]["question_id"]
                qids = by_target["question", qid]["canonical_ids"]
                require(any(x.startswith(f"ANS-{q.removeprefix('Q-')}-") for q in qids),
                        "CANONICAL_KEY_SCOPE", x)
    return by_target


def option_labels(options, where):
    require(isinstance(options, list), "OPTION_LIST", where)
    labels, texts = [], []
    for option in options:
        shape(option, "label text", where)
        require(option["label"] is None or isinstance(option["label"], str), "OPTION_LABEL", where)
        require(isinstance(option["text"], str), "OPTION_TEXT", where)
        labels.append(option["label"])
        texts.append(option["text"])
    unique = (all(nonblank(x) for x in labels + texts)
              and len({x.strip().casefold() for x in labels}) == len(labels)
              and len({x.strip().casefold() for x in texts}) == len(texts))
    return labels, unique


def group_errors(group, members, group_slots, slot_rows, passage):
    """Yield failed practice dependencies even for faithfully transcribed source defects."""
    kind, context = group["question_type"], group["context"]
    gid = group["id"]
    require(kind in KINDS, "QUESTION_TYPE", gid)
    count = group["required_answer_count"]
    require(type(count) is int and count > 0, "ANSWER_COUNT", gid)
    limit = group["word_limit"]
    if limit is not None:
        shape(limit, "words numbers", gid)
        require(all(type(n) is int and n >= 0 for n in limit.values()) and any(limit.values()),
                "WORD_LIMIT", gid)
    labels = named_ids(group["labels"], gid)
    shared, unique = option_labels(group["shared_options"], gid)
    if not unique or (kind in BANK and not shared):
        yield "SHARED_OPTIONS", "group", gid
    if kind in BANK or shared:
        if shared != labels or kind in CHOICE or kind in BOOLEAN or kind == "matching-information":
            yield "SHARED_OPTION_LABELS", "group", gid
    elif kind == "matching-information":
        paragraph_labels = Counter(p["label"] for p in passage["paragraphs"])
        if not labels or any(paragraph_labels[label] != 1 for label in labels):
            yield "PASSAGE_LABELS", "group", gid
    elif kind not in CHOICE and labels:
        yield "UNEXPECTED_LABELS", "group", gid
    if not nonblank(group["instruction"]) or (kind in CLOZE and not nonblank(context)):
        yield "GROUP_CONTEXT_OR_INSTRUCTION", "group", gid
    if kind in VISUAL and not group["asset_ids"]:
        yield "MISSING_GROUP_ASSET", "group", gid
    if kind in CLOZE | {"short-answer"} and not (shared or limit is not None):
        yield "MISSING_WORD_LIMIT", "group", gid
    if kind != "multiple-choice-multi" and count != 1:
        yield "ANSWER_COUNT", "group", gid
    if kind == "multiple-choice-multi" and count < 2:
        yield "ANSWER_COUNT", "group", gid
    if not group_slots:
        yield "EMPTY_GROUP", "group", gid

    occupied = []
    for question in members:
        qid, qslots = question["id"], question["slot_ids"]
        if len(qslots) != count:
            yield "QUESTION_SLOT_COUNT", "question", qid
        opts, unique = option_labels(question["options"], qid)
        if kind in CHOICE:
            if not unique or len(opts) <= count or any(label not in labels for label in opts):
                yield "QUESTION_OPTIONS", "question", qid
            elif set(opts) != set(labels):
                yield "QUESTION_OPTION_COVERAGE", "question", qid
        elif opts:
            yield "UNEXPECTED_OPTIONS", "question", qid
        if kind not in CLOZE and not nonblank(question["prompt"]):
            yield "EMPTY_PROMPT", "question", qid
        blanks = question["blanks"]
        require(isinstance(blanks, dict), "BLANK_MAP", qid)
        if kind in CLOZE:
            if set(blanks) != set(qslots) or not nonblank(context):
                yield "CLOZE_COVERAGE", "question", qid
                continue
            for slot, blank in blanks.items():
                shape(blank, "start end token", qid)
                start, end, token = blank["start"], blank["end"], blank["token"]
                number = slot_rows[slot]["number"]
                if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(context)
                        or not nonblank(token) or context[start:end] != token
                        or number is None or not re.search(rf"(?<!\d){re.escape(str(number))}(?!\d)", token)
                        or not re.search(r"[._…□–-]", token)):
                    yield "CLOZE_POSITION", "question", qid
                else:
                    occupied.append((start, end, slot))
        elif blanks:
            yield "UNEXPECTED_BLANK_MAP", "question", qid
    spans = sorted(occupied)
    if kind in CLOZE and nonblank(context):
        for match in re.finditer(r"(?<!\w)\d+[ \t]*[.)]?[ \t]*[._…□]{2,}", context):
            if not any(start <= match.start() and match.end() <= end for start, end, _ in spans):
                yield "UNMAPPED_CLOZE_BLANK", "group", gid
    if (any(a[1] > b[0] for a, b in zip(spans, spans[1:]))
            or (kind in CLOZE and [s[2] for s in spans] != group_slots)):
        yield "CLOZE_ORDER_OR_COVERAGE", "group", gid


def verify_census(review, passage, groups, spans, claims):
    census = review["question_census"]
    shape(census, "groups slots adjacent_rubrics", "question census")
    require(census["groups"] == list(groups)
            and digest(census["slots"]) == digest(passage["slots"]),
            "QUESTION_CENSUS", passage["id"])
    boundaries = {sid for region in review["body_regions"] if region["role"] in {"after", "excluded"}
                  for sid in region["spans"]}
    instructions = {}
    for gid in groups:
        for ref in claims[f"group/{gid}"]["instruction"]:
            instructions.setdefault(ref, set()).add(gid)
    adjacent = census["adjacent_rubrics"]
    require(isinstance(adjacent, dict) and set(adjacent) <= boundaries - instructions.keys()
            and all(nonblank(reason) for reason in adjacent.values()), "ADJACENT_RUBRIC", passage["id"])
    for ref in sorted((boundaries | instructions.keys()) - set(adjacent)):
        applicable = instructions.get(ref)
        numbers = {slot["number"] for slot in passage["slots"] if type(slot["number"]) is int
                   and (applicable is None or slot["group_id"] in applicable)}
        for line in spans[ref]["text"].splitlines():
            header = re.fullmatch(
                r"\s*Questions?\s+(\d+)(?:\s*(?:[-–—]|to)\s*(\d+)|"
                r"\s*(?:and|&|,)\s*(\d+))?\s*[:.]?\s*", line, flags=re.I,
            )
            if not header:
                continue
            start, end, second = (int(value) if value else None for value in header.groups())
            require(1 <= start <= 999 and (end is None or start <= end <= 999),
                    "RUBRIC_NUMBERS", ref)
            expected = set(range(start, (end or start) + 1))
            if second is not None:
                expected.add(second)
            require(expected <= numbers, "RUBRIC_SLOT_COVERAGE", f"{passage['id']} {sorted(expected - numbers)}")


def verify_content(passage, rows, spans, assets, claims, catalog):
    pid, source = passage["id"], passage["source_id"]
    groups, questions = rows["group"], rows["question"]
    for eid, row in list(groups.items()) + list(questions.items()):
        require(row["passage_id"] == pid and row["source_id"] == source, "MIXED_SOURCE", eid)
    for key in rows["key"].values():
        require(key["passage_id"] == pid, "KEY_PASSAGE", key["id"])
    slots = record_map(passage["slots"], "id")
    held, pending = limitations(rows, slots)
    group_slots = {gid: [] for gid in groups}
    require(all(q["group_id"] in groups for q in questions.values()),
            "DANGLING_GROUP", pid)
    if slots:
        ordered_slot_spans = list(dict.fromkeys(slot["span"] for slot in slots.values()))
        slot_claims = claims[f"passage/{pid}"]["slots"]
        require([ref for ref in slot_claims if ref in ordered_slot_spans] == ordered_slot_spans,
                "SLOT_EVIDENCE_ORDER_OR_COVERAGE", pid)
    for slot in slots.values():
        sid, gid, qid, number = slot["id"], slot["group_id"], slot["question_id"], slot["number"]
        shape(slot, "id number group_id question_id span", sid)
        require(number is None or nonblank(number) or (type(number) is int and number > 0), "PRINTED_NUMBER", sid)
        if gid is not None:
            require(gid in groups, "DANGLING_GROUP", sid)
            group_slots[gid].append(sid)
        if qid is not None:
            if number is not None and ("slot", sid) not in held and ("group", gid) not in held:
                require(re.search(rf"(?<!\w){re.escape(str(number))}(?!\w)",
                                  spans[slot["span"]]["text"]), "SLOT_SOURCE_NUMBER", sid)
            require(qid in questions and gid == questions[qid]["group_id"]
                    and sid in questions[qid]["slot_ids"], "SLOT_QUESTION", sid)
    by_group = {gid: [] for gid in groups}
    for qid, question in questions.items():
        gid = question["group_id"]
        qslots = named_ids(question["slot_ids"], qid)
        require(qslots and all(s in slots and slots[s]["question_id"] == qid for s in qslots)
                and qslots == [s for s in group_slots[gid] if slots[s]["question_id"] == qid],
                "QUESTION_SLOT_COVERAGE", qid)
        by_group[gid].append(question)
    used_assets = set()
    for kind in ("passage", "group", "question"):
        for eid, row in rows[kind].items():
            for asset_id in named_ids(row["asset_ids"], eid):
                require(asset_id in assets, "MISSING_ASSET", f"{eid}/{asset_id}")
                ref = assets[asset_id]["span"]
                require(ref in claims[f"{kind}/{eid}"]["asset_ids"]
                        and spans[ref]["source_id"] == source, "ASSET_PROVENANCE", asset_id)
                used_assets.add(asset_id)
    require(set(assets) == used_assets, "UNMATCHED_ASSET", pid)
    withheld_groups = set()
    withheld_body = ("passage", pid) in held
    for kind, target in held:
        if kind == "slot" and slots[target]["group_id"] is not None:
            withheld_groups.add(slots[target]["group_id"])
        if kind == "group":
            withheld_groups.add(target)
        if kind == "question":
            withheld_groups.add(questions[target]["group_id"])
    seen_numbers = Counter(slot["number"] for slot in slots.values())
    for sid, slot in slots.items():
        number = slot["number"]
        if slot["question_id"] is None or type(number) is not int or seen_numbers[number] > 1:
            require(("slot", sid) in held or ("group", slot["group_id"]) in held,
                    "MISSING_OR_DUPLICATE_NUMBERED_SLOT", sid)
    by_target = mappings(rows, questions, slots, catalog, passage, held)
    for gid, group in groups.items():
        for code, kind, target in group_errors(group, by_group[gid], group_slots[gid], slots, passage):
            require((kind, target) in held or ("group", gid) in held
                    or (code == "CLOZE_ORDER_OR_COVERAGE"
                        and any(("slot", sid) in held for sid in group_slots[gid])),
                    code, target)
        mapped = by_target["group", gid]["canonical_ids"] and all(
            by_target["question", q["id"]]["canonical_ids"] for q in by_group[gid])
        require(mapped or gid in withheld_groups, "MAPPING_DEPENDENCY", gid)
    require(by_target["passage", pid]["canonical_ids"] or withheld_body,
            "MAPPING_DEPENDENCY", pid)
    eligible = [sid for sid, slot in slots.items()
                if not withheld_body and slot["group_id"] not in withheld_groups
                and slot["question_id"] is not None]
    return slots, eligible, withheld_body, held, pending


def normalized_key(key, group):
    raw, kind = key["raw"], group["question_type"]
    require(nonblank(raw), "EMPTY_AVAILABLE_KEY", key["id"])
    sep = key["alternate_separator"]
    if kind == "multiple-choice-multi":
        require(sep is None, "MULTISELECT_SEPARATOR", key["id"])
        values = [v.strip() for v in raw.split(",")]
        require(len(values) == group["required_answer_count"] == len(set(values)),
                "MULTISELECT_ANSWER_SET", key["id"])
    elif kind in BOOLEAN:
        aliases = BOOLEAN[kind]
        token = " ".join(raw.upper().split())
        require(sep is None and token in set(aliases) | set(aliases.values()),
                "BOOLEAN_KEY", key["id"])
        values = [aliases.get(token, token)]
    elif group["labels"]:
        require(sep is None, "OPTION_KEY_SEPARATOR", key["id"])
        values = [raw.strip()]
    else:
        require(sep in {None, "/"}, "KEY_ALTERNATE_SEPARATOR", key["id"])
        values = [" ".join(part.split()) for part in (raw.split(sep) if sep else [raw])]
        require(all(values) and len(values) == len(set(values)), "KEY_ALTERNATES", key["id"])
        limit = group["word_limit"]
        for value in values:
            tokens = value.split()
            numbers = sum(bool(re.fullmatch(r"[+-]?\d+(?:[.,:/-]\d+)*%?", t)) for t in tokens)
            # Under a words-only instruction a numeric token can consume a word slot.
            words = len(tokens) - numbers if limit and limit["numbers"] else len(tokens)
            require(limit is not None and words <= limit["words"]
                    and (not limit["numbers"] or numbers <= limit["numbers"]),
                    "KEY_WORD_LIMIT", key["id"])
    require(not group["labels"] or all(v in group["labels"] for v in values),
            "UNSUPPORTED_OPTION_KEY", key["id"])
    require(digest(key["values"]) == digest(values), "KEY_NORMALIZATION", key["id"])


def verify_keys(rows, eligible, held, pending, sources, passage):
    by_question = {}
    orphans = set()
    grading = {sid: "GRADING_DISABLED" for sid in eligible}
    errors = []
    for aid, key in rows["key"].items():
        qid, source, status = key["question_id"], key["source_id"], key["status"]
        if qid is None:
            orphan = key["orphan_number"]
            require(status == "orphan" and type(orphan) is int and orphan > 0
                    and (source, orphan) not in orphans, "ORPHAN_KEY", aid)
            orphans.add((source, orphan))
        else:
            require(qid in rows["question"] and qid not in by_question and key["orphan_number"] is None
                    and status in {"available", "missing", "ambiguous", "invalid", "pending"},
                    "UNMATCHED_KEY", aid)
            by_question[qid] = key
        try:
            if status == "missing":
                require(source is None and key["raw"] is None and key["values"] == []
                        and key["alternate_separator"] is None and key["authority"] == "missing",
                        "MISSING_KEY_METADATA", aid)
                continue
            entry = sources.inventory[source]
            require(entry["source_role"] in {"reading_key_xlsx", "reading_tests_and_keys_pdf",
                                             "reading_key_explanation_pdf", "orphan_key_pdf",
                                             "orphan_key_explanation_pdf"}
                    and entry["volume"] == passage["volume"]
                    and passage["test"] in entry["test_numbers"]
                    and (status == "orphan" or not entry["source_role"].startswith("orphan_"))
                    and key["authority"] == "unverified", "KEY_AUTHORITY_OR_SOURCE", aid)
            if status == "available":
                question = rows["question"][qid]
                group = rows["group"][question["group_id"]]
                normalized_key(key, group)
                if ("key", aid) not in held and all(s in grading for s in question["slot_ids"]):
                    for sid in question["slot_ids"]:
                        grading[sid] = "GRADING_KEY_AVAILABLE_UNVERIFIED"
            else:
                require(key["values"] == [] and key["alternate_separator"] is None
                        and isinstance(key["raw"], str), "DISABLED_KEY_METADATA", aid)
                require(status != "pending" or ("key", aid) in pending,
                        "KEY_PENDING_UNDOCUMENTED", aid)
        except (Invalid, KeyError) as error:
            errors.append(str(error))
    require(set(by_question) == set(rows["question"]), "KEY_COVERAGE", passage["id"])
    return grading, errors


def validate(workspace, inventory, canonical_inventory, batch, review_path, review_sha):
    manifest, rows, evidence, passage = load_batch(batch)
    revision = digest(manifest)
    require(not review_path.is_relative_to(batch), "REVIEW_PATH", review_path)
    raw = review_path.read_bytes()
    require(sha(raw) == review_sha, "REVIEW_HASH", review_path.name)
    review = json_data(raw)
    shape(review, "schema revision scope reviewer body_regions question_census fields", "review")
    identity(review["reviewer"])
    require(review["schema"] == VERSION and review["revision"] == revision,
            "STALE_REVIEW", passage["id"])
    require(all(review["reviewer"][k].casefold() != manifest["author"][k].casefold()
                for k in ("id", "session")), "NONINDEPENDENT_REVIEW", passage["id"])
    scope = {key: passage[key] for key in ("id", "source_id", "volume", "test", "passage_number")}
    require(digest(scope) == digest(review["scope"]) == digest(manifest["scope"]),
            "SCOPE", passage["id"])
    catalog_bytes = canonical_inventory.read_bytes()
    require(sha(catalog_bytes) == manifest["canonical_inventory_sha256"],
            "CANONICAL_INVENTORY_HASH", canonical_inventory)
    catalog = record_map(json_lines(catalog_bytes), "entity_id")
    sources = Sources(workspace, inventory)
    source_id = scope["source_id"]
    entry = sources.inventory[source_id]
    require(entry["source_sha256"] == manifest["source_sha256"]
            and entry["source_role"] in {"exam_pdf", "reading_tests_pdf", "reading_tests_and_keys_pdf",
                                         "reading_tests_docx", "duplicate_subset_test_pdf"}
            and entry["volume"] == scope["volume"]
            and type(scope["test"]) is int and scope["test"] in entry["test_numbers"]
            and type(scope["passage_number"]) is int and scope["passage_number"] in entry["passages_expected"],
            "SOURCE_SCOPE", passage["id"])
    sources.path(source_id)
    spans, assets = load_evidence(sources, evidence)
    claims = evidence["fields"]
    review_fields(review, rows, claims, spans, source_id, sources)
    used = verify_body(passage, review["body_regions"], spans, claims[f"passage/{passage['id']}"],
                       entry["source_format"])
    used.update(ref for record in claims.values() for refs in record.values() for ref in refs)
    require(used == set(spans), "UNMATCHED_EVIDENCE", passage["id"])
    slots, eligible, body_held, held, pending = verify_content(passage, rows, spans, assets, claims, catalog)
    verify_census(review, passage, rows["group"], spans, claims)
    grading, errors = verify_keys(rows, eligible, held, pending, sources, passage)
    omitted = [slot for slot in slots if slot not in eligible]
    practice = ("HOLD" if body_held else "PASSAGE_ONLY" if not eligible else
                "RESTRICTED_PRACTICE" if omitted else "PRACTICE_READY")
    unresolved = [row for row in rows["limitation"].values() if row["kind"] in REF_BLOCKERS]
    nonkey = [row for row in unresolved if row["target_type"] != "key"]
    if nonkey and not eligible:
        practice = "HOLD_MANUAL_REVIEW" if any(row["attempts"] == 2 for row in nonkey) else "HOLD"
    return {
        "schema": VERSION, "revision": revision, "review_sha256": review_sha,
        "reference": "HOLD" if errors or unresolved else "SOURCE_REFERENCE_CONFIRMED",
        "practice": practice, "eligible_slots": eligible, "omitted_slots": omitted,
        "grading_by_slot": {sid: grading.get(sid, "GRADING_DISABLED") for sid in slots},
        "diagnostic_grading": False, "hide_answers_during_practice": True,
        "blockers": [{"id": row["id"], "target": row["target_id"], "reason": row["reason"],
                      "hold": "HOLD_MANUAL_REVIEW" if row["attempts"] == 2 else "HOLD"}
                     for row in unresolved],
        "errors": errors,
    }


def write_result(path, result):
    require(path.name == "gate_result.json", "RESULT_NAME", path)
    directory = path.parent.resolve(strict=True)
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".gate-result-", delete=False) as handle:
            temp = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp, directory / path.name)
    finally:
        if temp is not None:
            with suppress(FileNotFoundError):
                temp.unlink()


def run(workspace, inventory, canonical_inventory, batch, review, review_sha):
    try:
        return validate(workspace.resolve(strict=True), inventory.resolve(strict=True),
                        canonical_inventory.resolve(strict=True), batch.resolve(strict=True),
                        review.resolve(strict=True), review_sha)
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, OSError,
            subprocess.SubprocessError, ParseError, BadZipFile, RecursionError) as error:
        return {"schema": VERSION, "reference": "HOLD", "practice": "HOLD",
                "eligible_slots": [], "grading_by_slot": {}, "diagnostic_grading": False,
                "hide_answers_during_practice": True, "errors": [str(error)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("workspace", "inventory", "canonical-inventory", "batch", "review"):
        parser.add_argument(f"--{flag}", required=True, type=Path)
    parser.add_argument("--review-sha256", required=True)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    result = run(args.workspace, args.inventory, args.canonical_inventory, args.batch, args.review, args.review_sha256)
    if args.result is not None:
        try:
            write_result(args.result, result)
        except (OSError, Invalid) as error:
            print(f"RESULT_WRITE: {error}", file=sys.stderr)
            return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return int(bool(result["errors"]) or result["practice"] in {"HOLD", "HOLD_MANUAL_REVIEW"})


if __name__ == "__main__":
    sys.exit(main())
