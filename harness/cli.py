"""Command-line interface (CLI) for IELTS Data Harness V0.1."""

import argparse
import json
import sys
from pathlib import Path


def cmd_inventory(args):
    """Scans raw sources and synchronizes SQLite database inventory."""
    from harness.db import get_db_connection
    from harness.inventory import sync_inventory_to_db

    print(">>> Scanning raw sources and updating inventory...")
    total_files, total_bytes = sync_inventory_to_db()
    print(f"Inventory sync complete: {total_files} files cataloged ({total_bytes:,} bytes).")

    conn = get_db_connection()
    cur = conn.execute("SELECT duplicate_group, COUNT(*) FROM sources WHERE duplicate_group != 'none' GROUP BY duplicate_group")
    dup_rows = cur.fetchall()
    if dup_rows:
        print("Duplicate content groups identified:")
        for grp, cnt in dup_rows:
            print(f"  - {grp}: {cnt} identical files")
    conn.close()


def cmd_classify(args):
    """Classifies sources and reports recommended extraction adapters."""
    from harness.classifier import classify_source
    from harness.config import PILOT_SOURCE_IDS
    from harness.db import (
        get_db_connection,
        get_source_by_file_id,
        get_source_by_legacy_id,
        list_sources,
    )

    conn = get_db_connection()
    if args.source_id:
        src = get_source_by_legacy_id(conn, args.source_id) or get_source_by_file_id(conn, args.source_id)
        if not src:
            print(f"Error: Source '{args.source_id}' not found in database inventory.")
            conn.close()
            sys.exit(1)
        sources = [src]
    elif args.pilot:
        sources = list_sources(conn, pilot_only=True, pilot_ids=PILOT_SOURCE_IDS)
    else:
        sources = list_sources(conn)

    print(f"{'Source ID':<10} | {'Type':<12} | {'Pages':<6} | {'Recommended Adapter':<16} | {'Path'}")
    print("-" * 80)
    for s in sources:
        res = classify_source(s)
        legacy_id = s.get("legacy_id") or s["file_id"]
        pg = str(res.get("page_count", 0))
        adp = res.get("recommended_adapter") or "none"
        print(f"{legacy_id:<10} | {res['subtype']:<12} | {pg:<6} | {adp:<16} | {s['relative_path']}")
    conn.close()


def cmd_extract(args):
    """Executes raw extraction with checkpointing and resume support."""
    from harness.config import PILOT_SOURCE_IDS
    from harness.db import (
        get_db_connection,
        get_source_by_file_id,
        get_source_by_legacy_id,
        list_sources,
    )
    from harness.engine import ExtractionEngine

    engine = ExtractionEngine()

    if getattr(args, "_sources_override", None):
        sources = args._sources_override
    else:
        conn = get_db_connection()
        if args.source_id:
            src = get_source_by_legacy_id(conn, args.source_id) or get_source_by_file_id(conn, args.source_id)
            if not src:
                print(f"Error: Source '{args.source_id}' not found in database inventory.")
                conn.close()
                sys.exit(1)
            sources = [src]
        elif args.pilot:
            sources = list_sources(conn, pilot_only=True, pilot_ids=PILOT_SOURCE_IDS)
        else:
            print("Error: Specify --pilot or --source-id <id>.")
            conn.close()
            sys.exit(1)
        conn.close()

    total_failed_units = 0
    force_flag = getattr(args, "force", False)

    print(f">>> Running extraction on {len(sources)} source(s)... (Force={force_flag})")
    for s in sources:
        legacy_id = s.get("legacy_id") or s["file_id"]
        print(f"\n--- Extracting {legacy_id} ({s['relative_path']}) ---")
        res = engine.process_source(
            source_record=s,
            force=force_flag,
            specific_unit=getattr(args, "unit", None),
            adapter_override=getattr(args, "adapter", None),
        )
        print(
            f"Result for {legacy_id}: Total units={res['total_units']}, "
            f"Completed={res['completed']}, Skipped={res['skipped']}, Failed={res['failed']}"
        )
        if res["failed"] > 0:
            total_failed_units += res["failed"]
            for u in res["results"]:
                if u["status"] == "FAILED":
                    print(f"  [ERROR] Unit {u['unit_identifier']}: {u['error']}")

    if total_failed_units > 0:
        print(f"\n[ERROR] Extraction completed with {total_failed_units} failed unit(s).")
        sys.exit(1)


def cmd_resume(args):
    """Resumes interrupted or incomplete extraction tasks across pilot or non-pilot sources."""
    from harness.config import PILOT_SOURCE_IDS
    from harness.db import (
        get_db_connection,
        get_interrupted_sources,
        get_source_by_file_id,
        get_source_by_legacy_id,
        list_sources,
    )

    conn = get_db_connection()
    if args.source_id:
        src = get_source_by_legacy_id(conn, args.source_id) or get_source_by_file_id(conn, args.source_id)
        if not src:
            print(f"Error: Source '{args.source_id}' not found in database inventory.")
            conn.close()
            sys.exit(1)
        sources = [src]
    elif getattr(args, "all", False):
        sources = get_interrupted_sources(conn)
        if not sources:
            print("No interrupted sources found across inventory.")
            conn.close()
            return
    elif getattr(args, "pilot", False):
        sources = list_sources(conn, pilot_only=True, pilot_ids=PILOT_SOURCE_IDS)
    else:
        # Default resume: check for interrupted sources first, otherwise fallback to pilot
        interrupted = get_interrupted_sources(conn)
        sources = interrupted if interrupted else list_sources(conn, pilot_only=True, pilot_ids=PILOT_SOURCE_IDS)

    conn.close()
    args.force = False
    args._sources_override = sources
    cmd_extract(args)


def cmd_status(args):
    """Displays inventory and extraction checkpoint status."""
    from harness.config import PILOT_SOURCE_IDS
    from harness.db import get_db_connection, list_sources

    conn = get_db_connection()
    total_sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    total_cp = conn.execute("SELECT COUNT(*) FROM processing_checkpoints").fetchone()[0]

    cur = conn.execute("SELECT status, COUNT(*) FROM processing_checkpoints GROUP BY status")
    cp_by_status = dict(cur.fetchall())

    print("=== HARNESS V0.1 STATUS SUMMARY ===")
    print(f"Total Sources in Inventory: {total_sources}")
    print(f"Total Processing Checkpoints: {total_cp}")
    for st in ["COMPLETED", "SKIPPED", "IN_PROGRESS", "FAILED"]:
        cnt = cp_by_status.get(st, 0)
        print(f"  - {st:<12}: {cnt}")

    pilot_sources = list_sources(conn, pilot_only=True, pilot_ids=PILOT_SOURCE_IDS)
    print("\n=== PILOT SOURCES PROGRESS ===")
    for ps in pilot_sources:
        lid = ps["legacy_id"]
        fid = ps["file_id"]
        cur = conn.execute(
            "SELECT status, COUNT(*) FROM processing_checkpoints WHERE file_id = ? GROUP BY status",
            (fid,),
        )
        st_counts = dict(cur.fetchall())
        comp = st_counts.get("COMPLETED", 0)
        fail = st_counts.get("FAILED", 0)
        in_p = st_counts.get("IN_PROGRESS", 0)
        print(f"  - {lid:<10}: {comp} completed, {fail} failed, {in_p} in-progress ({ps['filename']})")
    conn.close()


def cmd_validate(args):
    """Validates staged output JSON files against integrity rules."""
    from harness.validator import validate_all_staged, validate_staged_source

    if args.source_id:
        print(f">>> Validating staged artifacts for {args.source_id}...")
        res = validate_staged_source(args.source_id)
        print(f"Status: {res['status']}")
        print(
            f"Total files: {res['total_files']}, Passed: {res['passed']}, "
            f"Empty/Review: {res['empty']}, Failed: {res['failed']}"
        )
        if res["errors"]:
            print("Errors encountered:")
            for e in res["errors"]:
                print(f"  - {e}")
        if res["status"] == "FAIL":
            sys.exit(1)
    else:
        print(">>> Validating all staged outputs in staging directory...")
        res = validate_all_staged()
        print(f"Overall Status: {res['status']}")
        print(
            f"Total sources inspected: {res['total_sources']}, "
            f"Passed sources: {res['passed_sources']}, "
            f"Review required sources: {res['review_required_sources']}, "
            f"Failed sources: {res['failed_sources']}"
        )
        if res["errors"]:
            for e in res["errors"]:
                print(f"  [ERROR] {e}")
        for s in res["sources"]:
            mark = s["status"]
            print(f"  [{mark:<15}] {s['source_id']}: {s['passed']}/{s['total_files']} files valid")
            if s.get("empty_units"):
                print(f"                  Notice: Review required for unit(s): {s['empty_units']}")
            if s["errors"]:
                for e in s["errors"]:
                    print(f"                  Error: {e}")
        if res["status"] == "FAIL" or res["total_sources"] == 0 or res["failed_sources"] > 0:
            sys.exit(1)


def cmd_check_env(args):
    """Diagnoses the current Python virtual environment and system dependencies."""
    from harness.dependencies import check_all_dependencies

    print(f">>> Diagnosing Python Environment: {sys.executable}")
    report = check_all_dependencies()

    print("\n[Python Packages]")
    for name, info in report["python"].items():
        status = "OK" if info["installed"] else "MISSING"
        print(f"  [{status:<7}] {name:<12} (pip: {info['package']:<14}) — {info['desc']}")

    print("\n[System Commands]")
    for name, info in report["system"].items():
        status = "OK" if info["installed"] else "MISSING"
        path_str = info["path"] or f"missing (install with apt: {info['package']})"
        print(f"  [{status:<7}] {name:<12} — {path_str}")

    if report["all_satisfied"]:
        print("\nAll required Python and system dependencies are satisfied.")
    else:
        print("\nSome dependencies are missing. Please review the installation instructions above.")
        sys.exit(1)


def cmd_normalize(args):
    """Executes V0.2 normalization pipeline with checkpointing and quality gates."""
    from harness.orchestrator import NormalizationOrchestrator

    print(">>> Starting V0.2 Normalization Pipeline...")
    output_dir = Path(args.output_dir) if getattr(args, "output_dir", None) else None
    annotations_path = Path(args.annotations) if getattr(args, "annotations", None) else None
    orch = NormalizationOrchestrator(output_dir=output_dir) if output_dir else NormalizationOrchestrator()

    if getattr(args, "pilot", False) or getattr(args, "source_id", None) in {"SRC-138", None}:
        print(f"Target: Reading Pilot (SRC-138 + SRC-137), Test {args.test_number}, Passage {args.passage_number}")
        res = orch.run_pilot(
            dry_run=getattr(args, "dry_run", False),
            force=getattr(args, "force", False),
            test_number=args.test_number,
            passage_number=args.passage_number,
            annotations_path=annotations_path,
        )
        print("\n=== NORMALIZATION RESULT ===")
        print(f"Test ID: {res['test_id']}")
        print(f"Passage ID: {res['passage_id']}")
        print(f"Total entities processed: {res['total_entities']}")
        print(f"  - Written: {res['written_count']}")
        print(f"  - Skipped (Valid Checkpoint): {res['skipped_count']}")
        print(f"  - Dry-run: {res['dry_run']}")
        print(f"Output Directory: {res['output_dir']}")
        print(f"Entity Breakdown: {res['stats']}")
    else:
        print(f"Processing source {args.source_id}...")
        res = orch.normalize_reading_pilot(
            doc_legacy_id=args.source_id,
            key_legacy_id=getattr(args, "key_source_id", "SRC-137"),
            test_number=args.test_number,
            passage_number=args.passage_number,
            dry_run=getattr(args, "dry_run", False),
            force=getattr(args, "force", False),
            annotations_path=annotations_path,
        )
        print(f"Completed normalization for {args.source_id}: {res['total_entities']} entities.")


def cmd_verify(args):
    """Verifies normalized entities against Quality Gates G1 through G7."""
    from harness.verifier import QualityGateRunner
    from harness.config import REPO_ROOT

    norm_dir = Path(args.normalized_dir) if getattr(args, "normalized_dir", None) else REPO_ROOT / "private" / "staging" / "normalized"
    test_id = getattr(args, "test_id", None) or "TEST-IELTS-VOL06-05-ACAD"

    print(f">>> Running Quality Gates G1-G7 Verification on {test_id}...")
    print(f"Directory: {norm_dir}")

    runner = QualityGateRunner()
    entities = runner.load_entities_for_test(norm_dir, test_id)

    total_loaded = sum(len(v) for v in entities.values())
    if total_loaded == 0:
        print(f"[ERROR] No normalized entities found for test {test_id} in {norm_dir}.")
        sys.exit(1)

    print(f"Loaded {total_loaded} entity files across categories.")
    report = runner.verify_all_gates(entities)

    print("\n=== QUALITY GATES RESULTS ===")
    for gate_name, gate_info in report["gates"].items():
        status_tag = "PASS" if gate_info.get("passed") else "FAIL"
        print(f"  [{status_tag:<4}] {gate_name}")
        if not gate_info.get("passed") and gate_info.get("errors"):
            for err in gate_info["errors"]:
                print(f"         Error: {err}")

    print("\n=== STATISTICS ===")
    for k, v in report["statistics"].items():
        print(f"  - {k}: {v}")

    if report["warnings"]:
        print("\n=== WARNINGS / DIAGNOSTICS ===")
        for w in report["warnings"]:
            print(f"  [WARN] {w}")

    if report["unresolved_items"]:
        print("\n=== UNRESOLVED ITEMS ===")
        for u in report["unresolved_items"]:
            print(f"  [UNRESOLVED] {u['id']}: {u['note']}")

    print(f"\nOverall Verification Status: {report['overall_status']}")

    if getattr(args, "report", False):
        report_dir = REPO_ROOT / "private" / "reports" / "v02b"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"quality_report_{test_id}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Saved local quality report to: {report_path}")

    if report["overall_status"] == "FAIL":
        sys.exit(1)


def cmd_normalization_status(args):
    """Displays V0.2 normalization status and checkpoints."""
    from harness.db import get_db_connection, list_normalization_checkpoints, count_normalization_by_lifecycle

    conn = get_db_connection()
    checkpoints = list_normalization_checkpoints(conn)
    lifecycle_counts = count_normalization_by_lifecycle(conn)

    print("=== HARNESS V0.2 NORMALIZATION STATUS ===")
    print(f"Total Normalized Checkpoints: {len(checkpoints)}")

    cur = conn.execute("SELECT entity_type, COUNT(*) FROM normalization_checkpoints GROUP BY entity_type")
    type_counts = dict(cur.fetchall())
    print("\nEntities by Type:")
    for et, cnt in sorted(type_counts.items()):
        print(f"  - {et:<18}: {cnt}")

    print("\nEntities by Lifecycle Status:")
    for st in ["extracted", "review_required", "reviewed", "verified", "rejected"]:
        cnt = lifecycle_counts.get(st, 0)
        print(f"  - {st:<18}: {cnt}")

    conn.close()


def cmd_retrieve(args):
    """Retrieves full question learning context with uncertainty disclosure."""
    from harness.retrieval import TutorRetriever, STAGING_NORMALIZED_DIR

    norm_dir = Path(args.normalized_dir) if args.normalized_dir else STAGING_NORMALIZED_DIR
    try:
        retriever = TutorRetriever(normalized_dir=norm_dir)
        res = retriever.retrieve_question(args.question_id)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.format == "json":
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(f"=== RETRIEVAL RESULT: {res['question_id']} ===")
        print(f"Question #{res['question_number']} ({res['question_type']}):")
        print(f"  Prompt: {res['prompt_text']}")
        if res.get("group") and res["group"].get("instruction_text"):
            print(f"  Instructions: {res['group']['instruction_text']}")

        ans = res.get("answer")
        if ans:
            print(f"\nAnswer Key: {ans.get('target_value')} (Status: {ans.get('verification_status')}, Missing: {ans.get('is_missing')})")
            if ans.get("validation_flags"):
                print(f"  Flags: {ans['validation_flags']}")
        else:
            print("\nAnswer Key: NOT FOUND")

        ev = res.get("evidence")
        if ev:
            print(f"\nEvidence ({ev.get('evidence_type')}):")
            if ev.get("verbatim_quote"):
                print(f"  Quote: \"{ev['verbatim_quote']}\"")
                print(f"  Offsets: chars {ev.get('char_start')}-{ev.get('char_end')}, paragraph {ev.get('paragraph_label')}")
            elif ev.get("missing_information_rationale"):
                print(f"  Rationale: {ev['missing_information_rationale']}")
        else:
            print("\nEvidence: None available")

        ex = res.get("explanation")
        if ex:
            print(f"\nPedagogical Explanation ({ex.get('author_type')} / {ex.get('explanation_verification')}):")
            print(f"  EN: {ex.get('rationale_en')}")
            if ex.get("paraphrase_map"):
                print(f"  Paraphrases: {ex['paraphrase_map']}")
        else:
            print("\nPedagogical Explanation: None available")

        if res.get("linked_principles"):
            print("\nLinked Principles:")
            for p in res["linked_principles"]:
                print(f"  - [{p['id']}] {p['title']} ({p['file_path']})")

        unc = res.get("uncertainty_disclosure", {})
        print(f"\n=== UNCERTAINTY & READINESS ===")
        print(f"Readiness: {unc.get('readiness')} - {unc.get('readiness_reason')}")
        print(f"Disclosure: {unc.get('disclosure_text')}")


def main():
    parser = argparse.ArgumentParser(
        prog="harness",
        description="IELTS Data Harness V0.1 — Ingestion, Classification & Raw Extraction",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # inventory
    subparsers.add_parser("inventory", help="Scan raw sources and sync to SQLite inventory")

    # classify
    parser_classify = subparsers.add_parser("classify", help="Classify sources and recommend adapters")
    parser_classify.add_argument("--pilot", action="store_true", help="Classify only the 7 pilot sources")
    parser_classify.add_argument("--source-id", type=str, help="Specific source ID to classify")

    # extract
    parser_extract = subparsers.add_parser("extract", help="Extract raw structured data")
    parser_extract.add_argument("--pilot", action="store_true", help="Extract the 7 approved pilot sources")
    parser_extract.add_argument("--source-id", type=str, help="Specific source ID to extract")
    parser_extract.add_argument("--unit", type=str, help="Specific unit identifier (e.g. page_0001)")
    parser_extract.add_argument("--force", action="store_true", help="Force re-extraction, ignoring checkpoints")
    parser_extract.add_argument("--adapter", type=str, help="Override adapter selection")

    # resume
    parser_resume = subparsers.add_parser("resume", help="Resume interrupted or incomplete extraction tasks")
    parser_resume.add_argument("--source-id", type=str, help="Specific source ID to resume (pilot or non-pilot)")
    parser_resume.add_argument("--pilot", action="store_true", help="Resume the 7 approved pilot sources")
    parser_resume.add_argument("--all", action="store_true", help="Resume all interrupted sources across inventory")
    parser_resume.add_argument("--unit", type=str, help="Specific unit identifier (e.g. page_0001)")
    parser_resume.add_argument("--adapter", type=str, help="Override adapter selection")

    # status
    subparsers.add_parser("status", help="Show inventory and extraction checkpoint status")

    # validate
    parser_val = subparsers.add_parser("validate", help="Validate integrity of staged outputs")
    parser_val.add_argument("--source-id", type=str, help="Validate specific staged source ID")

    # check-env
    subparsers.add_parser("check-env", help="Diagnose Python virtual environment and system dependencies")

    # normalize
    parser_norm = subparsers.add_parser("normalize", help="Run V0.2 normalization pipeline")
    parser_norm.add_argument("--pilot", action="store_true", help="Run approved Reading Pilot (SRC-138 + SRC-137)")
    parser_norm.add_argument("--source-id", type=str, help="Specific source ID to normalize (e.g. SRC-138)")
    parser_norm.add_argument("--key-source-id", type=str, help="Answer key source ID (e.g. SRC-137)")
    parser_norm.add_argument("--test-number", type=int, default=5, help="Test number to normalize (default 5)")
    parser_norm.add_argument("--passage-number", type=int, default=1, help="Passage number to normalize (default 1)")
    parser_norm.add_argument("--dry-run", action="store_true", help="Run normalizer without writing to disk")
    parser_norm.add_argument("--force", action="store_true", help="Force reprocessing, bypassing checkpoints")
    parser_norm.add_argument("--resume", action="store_true", help="Resume from existing valid checkpoints")
    parser_norm.add_argument("--output-dir", type=str, help="Custom output directory")
    parser_norm.add_argument("--annotations", type=str, help="Path to evidence annotations JSON")

    # verify
    parser_ver = subparsers.add_parser("verify", help="Run Quality Gates G1-G7 verification")
    parser_ver.add_argument("--test-id", type=str, default="TEST-IELTS-VOL06-05-ACAD", help="Target test ID to verify")
    parser_ver.add_argument("--normalized-dir", type=str, help="Directory containing normalized JSONs")
    parser_ver.add_argument("--report", action="store_true", help="Write quality report to private/reports/v02b/")

    # normalization-status
    subparsers.add_parser("normalization-status", help="Show V0.2 normalization checkpoint status")

    # retrieve
    parser_ret = subparsers.add_parser("retrieve", help="Retrieve normalized question bundle for AI Tutor")
    parser_ret.add_argument("--question-id", type=str, required=True, help="Question ID to retrieve (e.g. Q-VOL06-05-RD-004)")
    parser_ret.add_argument("--normalized-dir", type=str, help="Directory containing normalized JSONs")
    parser_ret.add_argument("--format", choices=["text", "json"], default="text", help="Output format (default: text)")

    args = parser.parse_args()

    if args.subcommand == "inventory":
        cmd_inventory(args)
    elif args.subcommand == "classify":
        cmd_classify(args)
    elif args.subcommand == "extract":
        cmd_extract(args)
    elif args.subcommand == "resume":
        cmd_resume(args)
    elif args.subcommand == "status":
        cmd_status(args)
    elif args.subcommand == "validate":
        cmd_validate(args)
    elif args.subcommand == "check-env":
        cmd_check_env(args)
    elif args.subcommand == "normalize":
        cmd_normalize(args)
    elif args.subcommand == "verify":
        cmd_verify(args)
    elif args.subcommand == "normalization-status":
        cmd_normalization_status(args)
    elif args.subcommand == "retrieve":
        cmd_retrieve(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
