"""Executable historical reproductions and successor gate tests."""

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from evidence import Invalid, Sources, digest, file_sha, load_evidence, sha
from gate import BUNDLE, VERSION, run, verify_body


REPO = Path(os.environ["S03C_TEST_REPO"]) if "S03C_TEST_REPO" in os.environ else Path(__file__).resolve().parents[5]
BASE = REPO / "private/staging/reading_reconstruction"
S03B = BASE / "S03B_reference_finalization"
INVENTORY = BASE / "S01_freeze_containment/source_inventory.jsonl"


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def save_lines(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")


def one(rows, kind):
    return rows[kind][0]


def mapping(kind, eid, ids, slots=None):
    return {"id": f"m-{kind}-{eid}", "entity_type": kind, "reference_id": eid,
            "canonical_ids": ids, "canonical_slots": slots or {}}


class Sample:
    def __init__(self, tmp):
        self.tmp = tmp
        self.batch = tmp / "author"
        self.review_path = tmp / "review.json"
        self.inventory = tmp / "inventory.jsonl"
        self.catalog = tmp / "canonical.jsonl"
        self.docx = tmp / "test.docx"
        self.xlsx = tmp / "key.xlsx"
        self.batch.mkdir()
        self.texts = []
        self.spans = {}
        self.assets = []
        self.scope = {"id": "p", "volume": "VOL01", "test": 1, "passage_number": 1,
                      "source_id": "SRC"}
        self.before = self.block("PASSAGE 1")
        self.title = self.block("Water birds")
        self.intro = self.block("Some birds feed at dawn.")
        self.para = self.block("Several species migrate.")
        self.after = self.block("Questions 1")
        self.q2_group = "QG-X"
        self.instruction = self.block("Choose one letter for each answer.")
        self.prompt = self.block("Which option describes the birds?")
        self.slot_span = self.block("1")
        self.option_span = self.block("D Swim\nF Fly\nG Walk")
        self.regions = [
            {"role": role, "spans": [span], "label": label}
            for role, span, label in [("before", self.before, None), ("title", self.title, None),
                                      ("paragraph", self.intro, "A"), ("paragraph", self.para, "B"),
                                      ("after", self.after, None)]
        ]
        self.rows = {
            "passage": [{**self.scope, "title": "Water birds", "subtitle": None,
                         "paragraphs": [{"label": "A", "text": self.texts[self.intro], "spans": [self.intro]},
                                        {"label": "B", "text": self.texts[self.para], "spans": [self.para]}],
                         "body_sha256": "", "asset_ids": [],
                         "slots": [{"id": "s1", "number": 1, "group_id": "g",
                                    "question_id": "q", "span": self.slot_span}]}],
            "group": [{"id": "g", "passage_id": "p", "source_id": "SRC",
                       "question_type": "multiple-choice-single", "instruction": self.texts[self.instruction],
                       "context": None, "shared_options": [], "labels": ["D", "F", "G"],
                       "required_answer_count": 1, "word_limit": None, "asset_ids": []}],
            "question": [{"id": "q", "passage_id": "p", "source_id": "SRC", "group_id": "g",
                          "slot_ids": ["s1"], "prompt": self.texts[self.prompt],
                          "options": [{"label": label, "text": text}
                                      for label, text in [("D", "Swim"), ("F", "Fly"), ("G", "Walk")]],
                          "blanks": {}, "asset_ids": []}],
            "key": [{"id": "k", "passage_id": "p", "source_id": None, "question_id": "q",
                     "orphan_number": None, "status": "missing", "raw": None, "values": [],
                     "alternate_separator": None, "authority": "missing"}],
            "mapping": [mapping("passage", "p", ["PASSAGE-X-RD01"]), mapping("group", "g", ["QG-X"]),
                        mapping("question", "q", ["Q-1"], {"Q-1": "s1"}),
                        mapping("key", "k", [])],
            "limitation": [],
        }
        self.overrides = {
            "passage/p": {"title": [self.title], "paragraphs": [self.intro, self.para],
                          "slots": [self.slot_span]},
            "group/g": {"instruction": [self.instruction]},
            "question/q": {"prompt": [self.prompt], "options": [self.option_span]},
        }
        self.author = {"id": "author", "session": "author-session"}
        self.reviewer = {"id": "reader", "session": "independent-session"}
        self.attachments = {}
        self.key_text = None
        self.key_cell = "B7"

    def block(self, text):
        self.texts.append(text)
        return len(self.texts) - 1

    def available(self, text, values):
        self.key_text = text
        one(self.rows, "key").update(source_id="KEY", status="available", raw=text,
                                     values=values, authority="unverified")

    def multiselect(self):
        self.texts[self.after] = "Questions 1 and 2"
        one(self.rows, "group").update(question_type="multiple-choice-multi", required_answer_count=2)
        one(self.rows, "question")["slot_ids"].append("s2")
        slot = self.block("2")
        one(self.rows, "passage")["slots"].append(
            {"id": "s2", "number": 2, "group_id": "g", "question_id": "q", "span": slot})
        self.overrides["passage/p"]["slots"].append(slot)
        self.rows["mapping"][2]["canonical_ids"].append("Q-2")
        self.rows["mapping"][2]["canonical_slots"]["Q-2"] = "s2"

    def cloze(self, text="Birds eat 1 .... at dawn."):
        group, question = one(self.rows, "group"), one(self.rows, "question")
        group.update(question_type="summary-completion", labels=[], context=text,
                     word_limit={"words": 1, "numbers": 0})
        question.update(prompt=None, options=[], blanks={"s1": {"start": 10, "end": 16, "token": "1 ...."}})
        del self.overrides["question/q"]["prompt"]
        del self.overrides["question/q"]["options"]
        if text is not None:
            self.overrides["group/g"]["context"] = [self.block(text)]

    def limit(self, kind, eid, reason="Printed choice is missing", status="source_defect", field=None, attempts=0):
        self.rows["limitation"].append({"id": f"lim-{eid}", "target_type": kind, "target_id": eid,
                                        "kind": status, "field": field, "reason": reason,
                                        "attempts": attempts})

    def add_second_group(self):
        self.texts[self.after] = "Questions 1 and 2"
        self.q2_group = "QG-2"
        src = self.block("2")
        one(self.rows, "passage")["slots"].append(
            {"id": "s2", "number": 2, "group_id": "g2", "question_id": "q2", "span": src})
        self.overrides["passage/p"]["slots"].append(src)
        self.rows["group"].append(dict(one(self.rows, "group"), id="g2"))
        self.rows["question"].append(dict(deepcopy(one(self.rows, "question")),
                                          id="q2", group_id="g2", slot_ids=["s2"]))
        self.rows["key"].append(dict(one(self.rows, "key"), id="k2", question_id="q2"))
        self.rows["mapping"] += [mapping("group", "g2", ["QG-2"]),
                                 mapping("question", "q2", ["Q-2"], {"Q-2": "s2"}),
                                 mapping("key", "k2", [])]
        for kind in ("group", "question"):
            original, copy = ("g", "g2") if kind == "group" else ("q", "q2")
            self.overrides[f"{kind}/{copy}"] = deepcopy(self.overrides[f"{kind}/{original}"])

    def prepare_sources(self):
        w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        with ZipFile(self.docx, "w") as z:
            content = "".join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in self.texts)
            z.writestr("word/document.xml",
                       f'<w:document xmlns:w="{w}"><w:body>{content}</w:body></w:document>')
        specs = {"SRC": (self.docx, "docx", "reading_tests_docx")}
        if self.key_text is not None:
            s = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
            r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
            with ZipFile(self.xlsx, "w") as z:
                z.writestr("xl/workbook.xml", f'<workbook xmlns="{s}" xmlns:r="{r}"><sheets>'
                           '<sheet name="Test 1" sheetId="1" r:id="r1"/></sheets></workbook>')
                z.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="r1" '
                           'Target="worksheets/sheet1.xml"/></Relationships>')
                z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{s}"><sheetData><row r="7">'
                           f'<c r="B7" t="inlineStr"><is><t>{escape(self.key_text)}</t></is></c>'
                           '<c r="C7" t="inlineStr"><is><t>G</t></is></c></row></sheetData></worksheet>')
            specs["KEY"] = (self.xlsx, "xlsx", "reading_key_xlsx")
        self.source_hashes = {sid: file_sha(spec[0]) for sid, spec in specs.items()}
        save_lines(self.inventory, [{"source_id": sid, "source_path": path.name,
                                     "source_sha256": self.source_hashes[sid], "source_format": fmt,
                                     "source_role": role, "source_availability": "AVAILABLE",
                                     "volume": "VOL01", "test_numbers": [1], "passages_expected": [1]}
                                    for sid, (path, fmt, role) in specs.items()])

    def span(self, index):
        source = "KEY" if isinstance(index, str) else "SRC"
        if source == "KEY":
            locator = {"sheet": "Test 1", "cell": self.key_cell if index == "key" else index}
            text = self.key_text if index == "key" else "G"
        else:
            locator = {"element": [index]}
            text = self.texts[index]
        location = {"source_id": source, "source_sha256": self.source_hashes[source], "locator": locator}
        sid = digest(location)
        self.spans[sid] = {"id": sid, **location,
                           "text": text,
                           "file": self.attachments.get(index)}
        return sid

    def seal(self):
        self.prepare_sources()
        save_lines(self.catalog, [
            {"entity_id": "PASSAGE-X-RD01", "entity_type": "passage",
             "test_id": "TEST-IELTS-VOL01-01-ACAD", "source_legacy_id": "SRC"},
            {"entity_id": "PASSAGE-X-RD02", "entity_type": "passage",
             "test_id": "TEST-IELTS-VOL01-01-ACAD", "source_legacy_id": "SRC"},
            *({"entity_id": gid, "entity_type": "question_group", "passage_id": "PASSAGE-X-RD01"}
              for gid in ("QG-X", "QG-2")),
            *({"entity_id": qid, "entity_type": "question", "passage_id": "PASSAGE-X-RD01",
               "group_id": gid, "question_number": number}
              for qid, gid, number in (("Q-1", "QG-X", 1), ("Q-2", self.q2_group, 2))),
        ])
        rows = deepcopy(self.rows)
        passage = one(rows, "passage")
        for paragraph in passage["paragraphs"]:
            paragraph["spans"] = [self.span(i) for i in paragraph["spans"]]
        for slot in passage["slots"]:
            slot["span"] = self.span(slot["span"])
        if not passage["body_sha256"]:
            passage["body_sha256"] = digest(passage["paragraphs"])
        fields, events = {}, {}
        for kind, records in rows.items():
            for record in records:
                entity = f"{kind}/{record['id']}"
                fields[entity], events[entity] = {}, {}
                for name, value in record.items():
                    source = "key" if kind == "key" and record["source_id"] == "KEY" else self.after
                    if kind == "limitation" and record["target_type"] == "key" and self.key_text is not None:
                        source = "key"
                    indices = self.overrides.get(entity, {}).get(name, [source])
                    refs = [self.span(i) for i in indices]
                    fields[entity][name] = refs
                    events[entity][name] = {"actual_sha256": digest(value), "expected": value, "spans": refs,
                                            "method": "native", "outcome": "match"}
        regions = [dict(r, spans=[self.span(i) for i in r["spans"]]) for r in self.regions]
        assets = [dict(a, span=self.span(a["span"])) for a in self.assets]
        save(self.batch / "evidence_manifest.json", {"fields": fields, "spans": list(self.spans.values()),
                                                      "assets": assets})
        for kind, name in BUNDLE.items():
            if kind == "passage":
                save(self.batch / name, passage)
            else:
                save_lines(self.batch / name, rows[kind])
        manifest = {"schema": VERSION, "scope": self.scope, "author": self.author,
                    "source_sha256": self.source_hashes["SRC"],
                    "canonical_inventory_sha256": file_sha(self.catalog),
                    "files": {p.name: file_sha(p) for p in self.batch.iterdir()
                              if p.name != "batch_manifest.json"},
                    "population": {**{kind: len(rs) for kind, rs in rows.items()},
                                   "slots": len(passage["slots"])}}
        save(self.batch / "batch_manifest.json", manifest)
        save(self.review_path, {"schema": VERSION, "scope": self.scope, "reviewer": self.reviewer,
                                "revision": digest(manifest), "fields": events, "body_regions": regions,
                                "question_census": {"groups": [r["id"] for r in rows["group"]],
                                                    "slots": passage["slots"], "adjacent_rubrics": {}}})
        self.review_hash = file_sha(self.review_path)
        return self

    def validate(self):
        return run(self.tmp, self.inventory, self.catalog, self.batch, self.review_path, self.review_hash)

    def reseal_manifest(self, set_review_revision=False):
        path = self.batch / "batch_manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["files"] = {name: file_sha(self.batch / name) for name in manifest["files"]}
        save(path, manifest)
        if set_review_revision:
            review = json.loads(self.review_path.read_bytes())
            review["revision"] = digest(manifest)
            save(self.review_path, review)

    def change_review(self, mutate, repin=True):
        review = json.loads(self.review_path.read_bytes())
        mutate(review)
        save(self.review_path, review)
        if repin:
            self.review_hash = file_sha(self.review_path)


@pytest.fixture
def sample(tmp_path):
    return Sample(tmp_path)


def fails(result, code):
    assert any(code in error for error in result["errors"]), result
    assert result["reference"] == "HOLD"


@pytest.fixture(scope="module")
def legacy():
    spec = importlib.util.spec_from_file_location("legacy_tests", S03B / "tests/test_s03b_lock_validator.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LEGACY_FALSE_ACCEPTS = ["unrelated", "duplicated", "reordered", "empty_evidence", "dangling", "blank_key"]


@pytest.mark.parametrize("case", LEGACY_FALSE_ACCEPTS)
def test_legacy_false_accepts(legacy, case):
    bundle = legacy._make_valid_bundle()
    question = one(bundle, "questions")
    passage = bundle["passage"]
    if case == "unrelated":
        question["prompt_text_verbatim"] = "The astronaut exchanged 1 ........ with an unrelated crew."
    elif case == "duplicated":
        passage["paragraphs"].append(deepcopy(passage["paragraphs"][0]))
    elif case == "reordered":
        passage["paragraphs"].reverse()
    elif case == "empty_evidence":
        for record in [passage, *bundle["groups"], *bundle["questions"], *bundle["answer_keys"]]:
            record["evidence_refs"] = []
    elif case == "dangling":
        question["reference_group_id"] = "REF-QG-NONEXISTENT"
    elif case == "blank_key":
        one(bundle, "answer_keys")["answer_value_verbatim"] = ""
    assert legacy.validate_passage_bundle(bundle) == (True, [])


def test_practice_without_key(sample):
    result = sample.seal().validate()
    assert result["errors"] == []
    assert result["reference"] == "SOURCE_REFERENCE_CONFIRMED"
    assert result["practice"] == "PRACTICE_READY"
    assert result["grading_by_slot"] == {"s1": "GRADING_DISABLED"}
    assert result["hide_answers_during_practice"] and not result["diagnostic_grading"]


def test_option_f_retained_with_unverified_key(sample):
    sample.available("F", ["F"])
    result = sample.seal().validate()
    assert result["errors"] == []
    assert result["grading_by_slot"] == {"s1": "GRADING_KEY_AVAILABLE_UNVERIFIED"}


def test_pending_key_disables_grading_only(sample):
    sample.available("F", [])
    one(sample.rows, "key")["status"] = "pending"
    sample.limit("key", "k", "Check the faint printed cell", "pending", "raw")
    result = sample.seal().validate()
    assert result["errors"] == [] and result["reference"] == "HOLD"
    assert result["practice"] == "PRACTICE_READY"
    assert result["grading_by_slot"] == {"s1": "GRADING_DISABLED"}


def test_restricted_group_dependency_closure(sample):
    sample.add_second_group()
    options = one(sample.rows, "question")["options"]
    options[1]["label"] = options[0]["label"]
    sample.limit("question", "q")
    result = sample.seal().validate()
    assert result["errors"] == [] and result["reference"] == "SOURCE_REFERENCE_CONFIRMED"
    assert result["practice"] == "RESTRICTED_PRACTICE"
    assert result["eligible_slots"] == ["s2"] and result["omitted_slots"] == ["s1"]
    assert result["grading_by_slot"]["s1"] == "GRADING_DISABLED"


def test_source_limitation_can_leave_passage_only(sample):
    sample.limit("group", "g")
    result = sample.seal().validate()
    assert result["errors"] == [] and result["practice"] == "PASSAGE_ONLY"
    assert result["eligible_slots"] == []


def test_missing_printed_question_is_restricted(sample):
    sample.add_second_group()
    slot = one(sample.rows, "passage")["slots"][0]
    slot["question_id"] = None
    for kind in ("question", "key"):
        eid = sample.rows[kind].pop(0)["id"]
        sample.rows["mapping"] = [r for r in sample.rows["mapping"] if r["reference_id"] != eid]
    sample.limit("slot", "s1")
    result = sample.seal().validate()
    assert not result["errors"] and result["practice"] == "RESTRICTED_PRACTICE"
    assert result["eligible_slots"] == ["s2"]


def test_pending_question_two_attempts(sample):
    sample.limit("question", "q", "Unconfirmed edited stem", "pending", "prompt", attempts=2)
    result = sample.seal().validate()
    assert result["practice"] == "HOLD_MANUAL_REVIEW"
    assert result["blockers"][0]["target"] == "q"


def test_complete_cloze_context(sample):
    sample.cloze()
    assert sample.seal().validate()["practice"] == "PRACTICE_READY"


@pytest.mark.parametrize(("case", "error"), [
    ("abc123", "BODY_HASH"), ("duplicated", "BODY_COVERAGE"), ("reordered", "BODY_COVERAGE"),
    ("missing_paragraph", "BODY_COVERAGE"), ("dangling", "DANGLING_GROUP"),
    ("duplicate_slot", "DUPLICATE_OR_EMPTY_ID"), ("number_collision", "MISSING_OR_DUPLICATE_NUMBERED_SLOT"),
    ("missing_slot", "QUESTION_SLOT_COVERAGE"), ("wrong_mapping", "MAPPING_SLOT"),
    ("wrong_option_label", "QUESTION_OPTIONS"), ("truncated_options", "QUESTION_OPTION_COVERAGE"),
    ("duplicate_option", "QUESTION_OPTIONS"), ("unmatched_key", "UNMATCHED_KEY"),
    ("mixed_source", "MIXED_SOURCE"), ("no_context", "GROUP_CONTEXT_OR_INSTRUCTION"),
    ("context_placeholder", "SOURCE_FIELD_TEXT"), ("bad_blank", "CLOZE_POSITION"),
    ("missing_asset", "MISSING_ASSET"), ("wrong_cell", "NATIVE_TEXT_MISMATCH"),
    ("unsupported_key", "UNSUPPORTED_OPTION_KEY"),
])
def test_mechanical_rejections_with_consistent_revision(sample, case, error):
    rows = sample.rows
    p, q = one(rows, "passage"), one(rows, "question")
    if case == "abc123":
        p["body_sha256"] = "abc123"
    elif case == "duplicated":
        p["paragraphs"].append(deepcopy(p["paragraphs"][0]))
    elif case == "reordered":
        p["paragraphs"].reverse()
    elif case == "missing_paragraph":
        p["paragraphs"].pop()
    elif case == "dangling":
        q["group_id"] = "elsewhere"
    elif case == "duplicate_slot":
        p["slots"].append(deepcopy(p["slots"][0]))
    elif case == "number_collision":
        sample.add_second_group()
        p["slots"][1]["number"] = 1
        sample.texts[p["slots"][1]["span"]] = "1"
    elif case == "missing_slot":
        p["slots"] = []
    elif case == "wrong_mapping":
        rows["mapping"][2]["canonical_slots"]["Q-1"] = "other-slot"
    elif case == "wrong_option_label":
        q["options"][-1]["label"] = "X"
    elif case == "truncated_options":
        q["options"].pop()
    elif case == "duplicate_option":
        q["options"][1] = deepcopy(q["options"][0])
    elif case == "unmatched_key":
        one(rows, "key")["question_id"] = "other-question"
    elif case == "mixed_source":
        q["source_id"] = "other-doc"
    elif case == "no_context":
        sample.cloze(None)
    elif case == "context_placeholder":
        one(rows, "group")["context"] = {"requires_group_context_verbatim_from_source": True}
    elif case == "bad_blank":
        sample.cloze()
        q["blanks"]["s1"]["start"] = 11
    elif case == "missing_asset":
        q["asset_ids"] = ["absent-diagram"]
    elif case == "wrong_cell":
        sample.available("F", ["F"])
        sample.key_cell = "C7"
    elif case == "unsupported_key":
        sample.available("Z", ["Z"])
    fails(sample.seal().validate(), error)


@pytest.mark.parametrize(("raw", "values", "error"), [
    ("", [], "EMPTY_AVAILABLE_KEY"), ("F", ["FALSE"], "KEY_NORMALIZATION"),
    ("F,F", ["F", "F"], "MULTISELECT_ANSWER_SET"), ("F", ["F"], "MULTISELECT_ANSWER_SET"),
    ("D,F", ["D", "G"], "KEY_NORMALIZATION"), ("F,Z", ["F", "Z"], "UNSUPPORTED_OPTION_KEY"),
])
def test_key_mutations_reject_grading(sample, raw, values, error):
    if error == "MULTISELECT_ANSWER_SET" or "," in raw:
        sample.multiselect()
    sample.available(raw, values)
    result = sample.seal().validate()
    fails(result, error)
    assert result["practice"] == "PRACTICE_READY"
    assert set(result["grading_by_slot"].values()) == {"GRADING_DISABLED"}


def test_valid_multiselect(sample):
    sample.multiselect()
    sample.available("D,F", ["D", "F"])
    result = sample.seal().validate()
    assert result["errors"] == []
    assert result["grading_by_slot"] == dict.fromkeys(["s1", "s2"], "GRADING_KEY_AVAILABLE_UNVERIFIED")


def test_invalid_alternate_exceeds_word_limit(sample):
    sample.cloze()
    sample.available("seeds / sunflower seeds", ["seeds", "sunflower seeds"])
    one(sample.rows, "key")["alternate_separator"] = "/"
    fails(sample.seal().validate(), "KEY_WORD_LIMIT")


@pytest.mark.parametrize("field", ["prompt", "canonical_ids"])
def test_rehashing_bundle_does_not_reapprove_field(sample, field):
    sample.seal()
    name = BUNDLE["question" if field == "prompt" else "mapping"]
    path = sample.batch / name
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    rows[0][field] = "A stem about another passage." if field == "prompt" else ["PASSAGE-OTHER"]
    save_lines(path, rows)
    sample.reseal_manifest()
    fails(sample.validate(), "STALE_REVIEW")
    sample.reseal_manifest(set_review_revision=True)
    fails(sample.validate(), "REVIEW_HASH")
    sample.review_hash = file_sha(sample.review_path)
    fails(sample.validate(), "FIELD_VALUE")


def test_pinned_review_required_even_if_everything_is_rehashed(sample):
    sample.seal()
    sample.change_review(lambda review: review["reviewer"].update(id="untrusted"), repin=False)
    fails(sample.validate(), "REVIEW_HASH")
    sample.review_path.unlink()
    fails(sample.validate(), "review.json")


@pytest.mark.parametrize("kind", ["id", "session"])
def test_no_self_approval(sample, kind):
    sample.reviewer[kind] = sample.author[kind].upper()
    fails(sample.seal().validate(), "NONINDEPENDENT_REVIEW")


def test_absent_field_review(sample):
    sample.seal()
    sample.change_review(lambda review: review["fields"]["question/q"].pop("prompt"))
    fails(sample.validate(), "FIELD_COVERAGE")


def test_empty_evidence_arrays(sample):
    sample.overrides["question/q"]["prompt"] = []
    fails(sample.seal().validate(), "FIELD_EVIDENCE")


def test_evidence_asset_is_hash_checked_and_deletion_is_detected(sample):
    asset = sample.tmp / "diagram.svg"
    asset.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"><text>Diagram</text></svg>')
    graphic_span = sample.block("Diagram")
    sample.assets.append({"id": "diagram", "span": graphic_span,
                          "file": {"path": asset.name, "sha256": file_sha(asset)}})
    sample.cloze()
    one(sample.rows, "group").update(question_type="diagram-label-completion", asset_ids=["diagram"])
    sample.overrides["group/g"]["asset_ids"] = [graphic_span]
    sample.seal()
    assert sample.validate()["practice"] == "PRACTICE_READY"
    asset.write_bytes(b"something else")
    fails(sample.validate(), "EVIDENCE_HASH")
    asset.unlink()
    fails(sample.validate(), "diagram.svg")


def test_deleted_source_evidence(sample):
    artifact = sample.tmp / "reviewed-block.txt"
    artifact.write_text(sample.texts[sample.intro])
    sample.attachments[sample.intro] = {"path": artifact.name, "sha256": file_sha(artifact)}
    assert sample.seal().validate()["errors"] == []
    artifact.unlink()
    fails(sample.validate(), artifact.name)


def test_source_file_hash_recomputed(sample):
    sample.seal()
    with sample.docx.open("ab") as stream:
        stream.write(b"tampered")
    fails(sample.validate(), "SOURCE_HASH")


def test_cli_read_only_and_atomic_result(sample):
    sample.seal()
    command = [sys.executable, "-B", str(Path(__file__).with_name("gate.py")),
               "--workspace", str(sample.tmp), "--inventory", str(sample.inventory),
               "--canonical-inventory", str(sample.catalog),
               "--batch", str(sample.batch), "--review", str(sample.review_path),
               "--review-sha256", sample.review_hash]
    snapshot = {p: file_sha(p) for p in sample.tmp.rglob("*") if p.is_file()}
    first = subprocess.run(command, check=True, capture_output=True, text=True)
    second = subprocess.run(command, check=True, capture_output=True, text=True)
    assert first.stdout == second.stdout
    assert {p: file_sha(p) for p in sample.tmp.rglob("*") if p.is_file()} == snapshot
    result = sample.tmp / "gate_result.json"
    output = command + ["--result", str(result)]
    subprocess.run(output, check=True, capture_output=True)
    assert json.loads(result.read_bytes()) == json.loads(first.stdout)
    assert subprocess.run(output, capture_output=True).returncode == 2
    assert json.loads(result.read_bytes()) == json.loads(first.stdout)
    assert set(sample.tmp.rglob(".gate-result-*")) == set()
    assert subprocess.run(command + ["--result", str(sample.inventory)], capture_output=True).returncode == 2
    assert file_sha(sample.inventory) == snapshot[sample.inventory]


@pytest.fixture(scope="module")
def vol03_body():
    """Physical PDF pages 63–65, reviewed at 115 DPI against the original source."""
    bundle = S03B / "verified_reference/VOL03/TEST06/PASSAGE03"
    precedent = json.loads((bundle / "passage_reference.json").read_bytes())
    old = [p["text_verbatim"] for p in precedent["paragraphs"]]
    sources = Sources(REPO.resolve(), INVENTORY)
    source_id = "SRC-079"
    source_hash = "498c1f830655031ca85581dfee157e0e2aec1dfb024fce5d0cc4ffa510df93ea"
    assert sources.inventory[source_id]["source_sha256"] == source_hash
    regions, records, body = [], [], []

    def add(role, page, top, bottom, text, label=None):
        loc = {"source_id": source_id, "source_sha256": source_hash,
               "locator": {"page": page, "box": [1100, top, 8900, bottom]}}
        ref = digest(loc)
        records.append(dict(loc, id=ref, text=text, file=None))
        regions.append({"role": role, "spans": [ref], "label": label})
        if role == "paragraph":
            body.append({"label": label, "text": text, "spans": [ref]})
        return ref

    add("before", 63, 800, 1580, "READING PASSAGE 3")
    title = "A new stage in the study and teaching of history"
    title_span = add("title", 63, 1680, 1910, title)
    add("paragraph", 63, 2000, 2820, old[1])
    add("paragraph", 63, 2960, 4620, old[2].removeprefix("A "), "A")
    add("paragraph", 63, 4700, 6340, old[3].replace("B Ina ", "In a ", 1), "B")
    add("paragraph", 63, 6410, 8260, old[4].removeprefix("Cc "), "C")
    add("paragraph", 64, 820, 1920, old[5], "D")
    add("paragraph", 64, 2000, 3280, old[6], "E")
    add("paragraph", 64, 3370, 5190, old[7], "F")
    add("paragraph", 64, 5280, 6570,
        old[8].removesuffix(" Reading Passage 3 has seven paragraphs, A-G."), "G")
    first = add("after", 65, 800, 1860, "Reading Passage 3 has seven paragraphs, A-G.")
    questions = add("after", 65, 2050, 4840, old[12])
    regions[-2]["spans"].append(questions)
    regions.pop()
    evidence, _ = load_evidence(sources, {"spans": records, "assets": [], "fields": {}})
    assert evidence[first]["locator"]["page"] == evidence[questions]["locator"]["page"] == 65
    assert old[12].startswith("27 ") and " 35 " in old[12]
    # Digests pin the transcriptions against silent changes to the historical fixture.
    assert digest([p["text"] for p in body]) == "e795e82a55a6382d061aeebc1d241a360865d0025fe42c85d3ea743039067149"
    assert digest(evidence[questions]["text"]) == "9626f3de31db63c2120a1940a79f56eabe9b5ae603f8d40d1085db661960dc2e"
    return {"id": precedent["reference_passage_id"], "source_id": source_id, "title": title,
            "subtitle": None, "paragraphs": body, "body_sha256": digest(body)}, regions, evidence, {
               "title": [title_span], "paragraphs": [r for paragraph in body for r in paragraph["spans"]]
            }, questions


@pytest.mark.parametrize("case", ["valid", "paragraph_missing", "q27_35_contamination"])
def test_vol03_actual_pdf_boundaries(vol03_body, case):
    passage, regions, evidence, claims, questions = deepcopy(vol03_body)
    if case == "valid":
        assert questions in verify_body(passage, regions, evidence, claims, "pdf")
        return
    if case == "paragraph_missing":
        passage["paragraphs"].pop(4)
    else:
        passage["paragraphs"].append({"label": None, "text": evidence[questions]["text"],
                                      "spans": [questions]})
    passage["body_sha256"] = digest(passage["paragraphs"])
    claims["paragraphs"] = [ref for p in passage["paragraphs"] for ref in p["spans"]]
    with pytest.raises(Invalid, match="BODY_COVERAGE"):
        verify_body(passage, regions, evidence, claims, "pdf")


def test_pdf_evidence_out_of_bounds(vol03_body):
    _, _, evidence, _, _ = deepcopy(vol03_body)
    span = next(iter(evidence.values()))
    span["locator"]["page"] = 119
    span["id"] = digest({k: span[k] for k in ("source_id", "source_sha256", "locator")})
    sources = Sources(REPO.resolve(), INVENTORY)
    with pytest.raises(Invalid, match="PDF_PAGE"):
        load_evidence(sources, {"spans": [span], "assets": [], "fields": {}})



def test_multi_select_key_in_two_cells(sample):
    sample.multiselect()
    sample.available("D", ["D", "G"])
    one(sample.rows, "key")["raw"] = "D, G"
    sample.overrides["key/k"] = {"raw": ["key", "C7"]}
    result = sample.seal().validate()
    assert not result["errors"]
    assert result["grading_by_slot"] == dict.fromkeys(["s1", "s2"], "GRADING_KEY_AVAILABLE_UNVERIFIED")


def test_vol03_native_xlsx_cells():
    sources = Sources(REPO.resolve(), INVENTORY)
    assert sources.locate("SRC-077", {"sheet": "Test 6", "cell": "C9"}) == "27.0"
    assert sources.locate("SRC-077", {"sheet": "Test 6", "cell": "D9"}) == "C"
    assert sources.locate("SRC-077", {"sheet": "Test 6", "cell": "D11"}) == "F"



def test_missing_advertised_slot(sample):
    sample.texts[sample.after] = "Questions 1 and 2"
    fails(sample.seal().validate(), "RUBRIC_SLOT_COVERAGE")


def test_native_body_block_cannot_be_omitted_from_bundle_and_review(sample):
    one(sample.rows, "passage")["paragraphs"].pop()
    sample.regions.pop(3)
    sample.overrides["passage/p"]["paragraphs"].pop()
    fails(sample.seal().validate(), "BODY_DOCX_BLOCK_GAP")


def test_cloze_cannot_omit_extra_source_blank(sample):
    sample.cloze("Birds eat 1 .... at dawn. They fly to 2 .... at night.")
    fails(sample.seal().validate(), "UNMAPPED_CLOZE_BLANK")


def test_slot_evidence_must_include_printed_number(sample):
    one(sample.rows, "passage")["slots"][0]["span"] = sample.prompt
    sample.overrides["passage/p"]["slots"] = [sample.prompt]
    fails(sample.seal().validate(), "SLOT_SOURCE_NUMBER")


def test_unknown_canonical_id(sample):
    sample.rows["mapping"][1]["canonical_ids"] = ["QG-NONEXISTENT"]
    fails(sample.seal().validate(), "CANONICAL_TARGET")


def test_crossed_canonical_groups(sample):
    sample.add_second_group()
    first, second = [r for r in sample.rows["mapping"] if r["entity_type"] == "group"]
    first["canonical_ids"], second["canonical_ids"] = second["canonical_ids"], first["canonical_ids"]
    fails(sample.seal().validate(), "CANONICAL_GROUP_SCOPE")


def test_wrong_known_canonical_passage(sample):
    sample.rows["mapping"][0]["canonical_ids"] = ["PASSAGE-X-RD02"]
    fails(sample.seal().validate(), "CANONICAL_PASSAGE_SCOPE")


def test_changed_canonical_inventory_fails(sample):
    sample.seal()
    with sample.catalog.open("ab") as stream:
        stream.write(b"\n")
    fails(sample.validate(), "CANONICAL_INVENTORY_HASH")


def test_missing_independent_census_slot(sample):
    sample.seal()
    sample.change_review(lambda review: review["question_census"]["slots"].clear())
    fails(sample.validate(), "QUESTION_CENSUS")


def test_digital_pdf_native_excerpt():
    sources = Sources(REPO.resolve(), INVENTORY)
    sid = "SRC-152"
    title = "Chilli Peppers"
    start = len("PASSAGE 1\nRead the text and answer questions 1–13\n")
    location = {"source_id": sid, "source_sha256": sources.inventory[sid]["source_sha256"],
                "locator": {"page": 1, "box": [0, 0, 10000, 10000],
                            "native_chars": [start, start + len(title)]}}
    span = dict(location, id=digest(location), text=title, file=None)
    manifest = {"spans": [span], "assets": [], "fields": {}}
    load_evidence(sources, manifest)
    span["text"] = "Unrelated title"
    with pytest.raises(Invalid, match="NATIVE_TEXT_MISMATCH"):
        load_evidence(sources, manifest)
