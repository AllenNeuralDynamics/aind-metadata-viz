#!/usr/bin/env python3
"""Manual evaluation script for the /summary endpoint.

Fetches each example asset from DocDB v2, compacts it, and asks Bedrock
for a summary. Prints a human-readable report so you can evaluate quality.

Usage:
    .venv/bin/python scripts/test_summary_endpoint.py

Optional env vars:
    CHAT_MODEL_ID      Override the default Bedrock model
    BEDROCK_ROLE_ARN   Assume a role for Bedrock (if needed)
    AWS_REGION         Bedrock region (default us-west-2)
"""

import asyncio
import json
import sys
import textwrap

from biodata_query.query import retrieve_records

from aind_metadata_viz.chat.summary import (
    DEFAULT_MAX_RECORD_BYTES,
    compact_record,
    summarize_record,
)

ASSETS = [
    "440_SmartSPIM1_20250116",
    "422_MESO2_20260122",
    "860900_2026-05-28_17-35-36_processed_2026-05-29_11-19-54",
    "behavior_850743_2026-06-11_09-45-06",
    "exaSPIM_681465_2025-01-22_13-45-35_flatfield-correction_2025-05-15_17-49-43",
]

SEP = "=" * 80


async def main():
    results = []
    for name in ASSETS:
        print(f"\n{SEP}")
        print(f"Asset: {name}")
        print(SEP)

        print("  Fetching from DocDB v2 ...", end="", flush=True)
        record = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda n=name: (
                retrieve_records({"name": n}, limit=1, force_backend="docdb").records
                or []
            ),
        )
        if not record:
            print(" NOT FOUND (skipping)")
            results.append({"name": name, "status": "not_found"})
            continue
        record = record[0]
        original_bytes = len(json.dumps(record, default=str))
        compacted = compact_record(record, max_bytes=DEFAULT_MAX_RECORD_BYTES)
        compacted_bytes = len(json.dumps(compacted, default=str))
        print(
            f" ok  ({original_bytes:,} bytes -> compacted to {compacted_bytes:,} bytes,"
            f" {100 * compacted_bytes / original_bytes:.0f}%)"
        )

        print("  Calling Bedrock ...", end="", flush=True)
        try:
            result = await summarize_record(record, max_bytes=DEFAULT_MAX_RECORD_BYTES)
        except Exception as exc:
            print(f" FAILED: {exc}")
            results.append({"name": name, "status": "error", "error": str(exc)})
            continue
        print(" done")

        print()
        print(textwrap.fill(result.summary, width=78, initial_indent="  ", subsequent_indent="  "))
        results.append(
            {
                "name": name,
                "status": "ok",
                "original_bytes": result.original_bytes,
                "compacted_bytes": result.compacted_bytes,
                "summary": result.summary,
            }
        )

    print(f"\n{SEP}")
    ok = sum(1 for r in results if r["status"] == "ok")
    not_found = sum(1 for r in results if r["status"] == "not_found")
    errors = sum(1 for r in results if r["status"] == "error")
    print(f"Summary: {ok} summarized, {not_found} not found in v2, {errors} errors")


if __name__ == "__main__":
    asyncio.run(main())
