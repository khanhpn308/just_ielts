"""Command-line interface (CLI) for IELTS Data Harness V0.1."""

import argparse
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

    print(f">>> Running extraction on {len(sources)} source(s)... (Force={args.force})")
    for s in sources:
        legacy_id = s.get("legacy_id") or s["file_id"]
        print(f"\n--- Extracting {legacy_id} ({s['relative_path']}) ---")
        res = engine.process_source(
            source_record=s,
            force=args.force,
            specific_unit=args.unit,
            adapter_override=args.adapter,
        )
        print(
            f"Result for {legacy_id}: Total units={res['total_units']}, "
            f"Completed={res['completed']}, Skipped={res['skipped']}, Failed={res['failed']}"
        )
        if res["failed"] > 0:
            for u in res["results"]:
                if u["status"] == "FAILED":
                    print(f"  [ERROR] Unit {u['unit_identifier']}: {u['error']}")


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
        print(f"Total files: {res['total_files']}, Passed: {res['passed']}, Failed: {res['failed']}")
        if res["errors"]:
            print("Errors encountered:")
            for e in res["errors"]:
                print(f"  - {e}")
        if res["status"] != "PASS":
            sys.exit(1)
    else:
        print(">>> Validating all staged outputs in staging directory...")
        res = validate_all_staged()
        print(f"Total sources inspected: {res['total_sources']}")
        print(f"Passed sources: {res['passed_sources']}, Failed sources: {res['failed_sources']}")
        for s in res["sources"]:
            mark = "PASS" if s["status"] == "PASS" else "FAIL"
            print(f"  [{mark}] {s['source_id']}: {s['passed']}/{s['total_files']} files valid")
            if s["errors"]:
                for e in s["errors"]:
                    print(f"         Error: {e}")
        if res["failed_sources"] > 0:
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
    subparsers.add_parser("resume", help="Resume interrupted or incomplete extraction tasks")

    # status
    subparsers.add_parser("status", help="Show inventory and extraction checkpoint status")

    # validate
    parser_val = subparsers.add_parser("validate", help="Validate integrity of staged outputs")
    parser_val.add_argument("--source-id", type=str, help="Validate specific staged source ID")

    # check-env
    subparsers.add_parser("check-env", help="Diagnose Python virtual environment and system dependencies")

    args = parser.parse_args()

    if args.subcommand == "inventory":
        cmd_inventory(args)
    elif args.subcommand == "classify":
        cmd_classify(args)
    elif args.subcommand == "extract":
        cmd_extract(args)
    elif args.subcommand == "resume":
        args.pilot = True
        args.source_id = None
        args.unit = None
        args.force = False
        args.adapter = None
        cmd_extract(args)
    elif args.subcommand == "status":
        cmd_status(args)
    elif args.subcommand == "validate":
        cmd_validate(args)
    elif args.subcommand == "check-env":
        cmd_check_env(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
