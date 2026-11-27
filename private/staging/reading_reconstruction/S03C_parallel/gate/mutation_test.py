"""Run targeted validator mutations on disposable copies of the gate."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


CASES = [
    ("placeholder body checksum", "gate.py",
     [('passage["body_sha256"] == digest(passage["paragraphs"])', "True")],
     "test_mechanical_rejections_with_consistent_revision[abc123-BODY_HASH]"),
    ("independently delimited DOCX block coverage", "gate.py",
     [('blocks == set(range(positions[0][0], positions[-1][0] + 1))', "True")],
     "test_native_body_block_cannot_be_omitted_from_bundle_and_review"),
    ("printed rubric slot coverage", "gate.py",
     [('expected <= numbers', "True")],
     "test_missing_advertised_slot"),
    ("cloze count from source", "gate.py",
     [('yield "UNMAPPED_CLOZE_BLANK", "group", gid', "pass")],
     "test_cloze_cannot_omit_extra_source_blank"),
    ("native printed slot number", "gate.py",
     [('spans[slot["span"]]["text"]), "SLOT_SOURCE_NUMBER"', 'spans[slot["span"]]["text"]) or True, "SLOT_SOURCE_NUMBER"')],
     "test_slot_evidence_must_include_printed_number"),
    ("frozen canonical target", "gate.py",
     [('all(x in catalog and catalog[x]["entity_type"] == canonical_kind for x in ids)', "True"),
      ('catalog[x]["passage_id"] in passage_ids', 'x not in catalog or catalog[x]["passage_id"] in passage_ids'),
      ('catalog[x]["group_id"] in gids or', 'any(g not in catalog for g in gids) or catalog[x]["group_id"] in gids or')],
     "test_unknown_canonical_id"),
    ("body coverage and field span order", "gate.py",
     [('paragraphs and digest(passage["paragraphs"]) == digest(paragraphs)', "True"),
      ('claims["paragraphs"] == [ref for paragraph in paragraphs for ref in paragraph["spans"]]', "True")],
     "test_vol03_actual_pdf_boundaries[q27_35_contamination]"),
    ("revision binding", "gate.py",
     [('review["schema"] == VERSION and review["revision"] == revision', 'review["schema"] == VERSION')],
     "test_rehashing_bundle_does_not_reapprove_field[prompt]"),
    ("pinned review hash", "gate.py",
     [('sha(raw) == review_sha', 'True')],
     "test_pinned_review_required_even_if_everything_is_rehashed"),
    ("exact field values", "gate.py",
     [('event["actual_sha256"] == digest(value) == digest(event["expected"])', 'True')],
     "test_rehashing_bundle_does_not_reapprove_field[canonical_ids]"),
    ("empty evidence", "gate.py",
     [('require(refs and refs == claims', 'require(refs == claims')],
     "test_empty_evidence_arrays"),
    ("reviewer independence", "gate.py",
     [('for k in ("id", "session")), "NONINDEPENDENT_REVIEW"', 'for k in ()), "NONINDEPENDENT_REVIEW"')],
     "test_no_self_approval[session]"),
    ("source byte verification", "evidence.py",
     [('file_sha(path) == source["source_sha256"]', 'True')],
     "test_source_file_hash_recomputed"),
    ("PDF page bounds", "evidence.py",
     [('1 <= page <= self.page_counts[path]', 'page >= 1')],
     "test_pdf_evidence_out_of_bounds"),
    ("native cell value", "evidence.py",
     [('(native is None or native == span["text"])', 'True')],
     "test_mechanical_rejections_with_consistent_revision[wrong_cell-NATIVE_TEXT_MISMATCH]"),
    ("canonical slot linkage", "gate.py",
     [('set(numbers.values()) == set(qslots if ids else [])', 'True'),
      ('all(slot in slots for slot in numbers.values())', 'True')],
     "test_mechanical_rejections_with_consistent_revision[wrong_mapping-MAPPING_SLOT]"),
    ("restricted dependency closure", "gate.py",
     [('withheld_groups.add(questions[target]["group_id"])', 'pass')],
     "test_restricted_group_dependency_closure"),
    ("cloze offsets", "gate.py",
     [('or not nonblank(token) or context[start:end] != token', 'or not nonblank(token)')],
     "test_mechanical_rejections_with_consistent_revision[bad_blank-CLOZE_POSITION]"),
    ("asset digest", "evidence.py",
     [('path.stat().st_size > 0 and file_sha(path) == entry["sha256"]', 'path.stat().st_size > 0')],
     "test_evidence_asset_is_hash_checked_and_deletion_is_detected"),
    ("multi-select uniqueness", "gate.py",
     [('len(values) == group["required_answer_count"] == len(set(values))',
       'len(values) == group["required_answer_count"]')],
     "test_key_mutations_reject_grading[F,F-values2-MULTISELECT_ANSWER_SET]"),
    ("option normalization", "gate.py",
     [('digest(key["values"]) == digest(values)', 'True')],
     "test_key_mutations_reject_grading[F-values1-KEY_NORMALIZATION]"),
    ("word and number limits", "gate.py",
     [('limit is not None and words <= limit["words"]', 'limit is not None')],
     "test_invalid_alternate_exceeds_word_limit"),
]


def main():
    gate = Path(__file__).resolve().parent
    repo = gate.parents[4]
    env = {**os.environ, "S03C_TEST_REPO": str(repo), "PYTHONDONTWRITEBYTECODE": "1"}
    killed = 0
    for label, filename, replacements, test in CASES:
        with TemporaryDirectory(prefix="s03c-mutant-") as temp:
            copy = Path(temp)
            for name in ("gate.py", "evidence.py", "test_gate.py"):
                shutil.copyfile(gate / name, copy / name)
            path = copy / filename
            code = path.read_text()
            for original, changed in replacements:
                if code.count(original) != 1:
                    raise ValueError(f"{label}: expected one mutation site")
                code = code.replace(original, changed)
            compile(code, str(path), "exec")
            path.write_text(code)
            result = subprocess.run(
                [sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider", "-q",
                 f"{copy / 'test_gate.py'}::{test}"],
                env=env, capture_output=True, text=True, timeout=60,
            )
            if (result.returncode == 1 and "1 failed in " in result.stdout
                    and ("AssertionError" in result.stdout or "DID NOT RAISE" in result.stdout)):
                print(f"KILLED {label}", flush=True)
                killed += 1
            else:
                print(f"FAILED TO KILL {label}\n{result.stdout}{result.stderr}", flush=True)
    print(f"{killed}/{len(CASES)} code mutations killed")
    return int(killed != len(CASES))


if __name__ == "__main__":
    sys.exit(main())
