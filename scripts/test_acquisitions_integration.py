"""Integration test: full platform/acquisition_type lifecycle against the production server.

Steps
-----
1.  POST /acquisition-types    — register (platform="test", acquisition_type=<unique>)
2.  POST /acquisition-types    — re-post the same pair → still 200, dedupes (idempotent)
3.  GET  /acquisition-types    — verify the pair is present
4.  POST /scheduled-acquisitions with an unregistered acquisition_type → expect 400
5.  POST /scheduled-acquisitions with a missing field → expect 422 (typed body)
6.  POST /scheduled-acquisitions, date=today, our acquisition_type → 200, get uuid
7.  GET  /scheduled-acquisitions/{uuid} — verify subject_id, date, platform="test", acquisition_type
8.  GET  /scheduled-acquisitions/{made-up-uuid} → expect 404
9.  GET  /scheduled-acquisitions (default, future-only) — today's uuid is present
10. POST /scheduled-acquisitions, date=yesterday (past) — second uuid
11. GET  /scheduled-acquisitions (default, future-only) — past uuid is excluded
12. GET  /scheduled-acquisitions?include_past=true — both uuids present

Usage
-----
    python scripts/test_acquisitions_integration.py
"""

import sys
import time
from datetime import date, timedelta

import requests

BASE_URL = "https://metadata-portal.allenneuraldynamics.org"
PLATFORM = "test"
ACQUISITION_TYPE = f"integration-test-type-{int(time.time())}"
SUBJECT_ID = f"integration-test-subject-{int(time.time())}"

ACQUISITION_TYPES_URL = f"{BASE_URL}/acquisition-types"
SCHEDULED_ACQUISITIONS_URL = f"{BASE_URL}/scheduled-acquisitions"

print(f"Testing against: {BASE_URL}")
print(f"platform={PLATFORM!r} acquisition_type={ACQUISITION_TYPE!r}")
print("=" * 60)


def sep(title):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def check(response, expected_status):
    if response.status_code != expected_status:
        print(f"  FAIL  status={response.status_code}  body={response.text[:400]}")
        sys.exit(1)
    print(f"  OK    status={response.status_code}")
    try:
        return response.json()
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Step 1: POST /acquisition-types — register platform="test" + acquisition_type
# ---------------------------------------------------------------------------

sep("Step 1: POST /acquisition-types (register platform:test pair)")
r = requests.post(ACQUISITION_TYPES_URL, json={"platform": PLATFORM, "acquisition_type": ACQUISITION_TYPE})
entry = check(r, 200)
assert entry == {"platform": PLATFORM, "acquisition_type": ACQUISITION_TYPE}, f"unexpected entry: {entry}"
print(f"  entry: {entry}")

# ---------------------------------------------------------------------------
# Step 2: POST again — dedupes, still 200
# ---------------------------------------------------------------------------

sep("Step 2: POST /acquisition-types again (expect 200, idempotent dedupe)")
r = requests.post(ACQUISITION_TYPES_URL, json={"platform": PLATFORM, "acquisition_type": ACQUISITION_TYPE})
check(r, 200)

# ---------------------------------------------------------------------------
# Step 3: GET /acquisition-types — verify the pair is present exactly once
# ---------------------------------------------------------------------------

sep("Step 3: GET /acquisition-types (verify pair present)")
r = requests.get(ACQUISITION_TYPES_URL)
entries = check(r, 200)
matches = [e for e in entries if e == {"platform": PLATFORM, "acquisition_type": ACQUISITION_TYPE}]
assert len(matches) == 1, f"expected exactly 1 match, found {len(matches)} in {len(entries)} entries"
print(f"  found {len(matches)} matching entry among {len(entries)} total")

# ---------------------------------------------------------------------------
# Step 4: POST /scheduled-acquisitions with an unregistered acquisition_type → 400
# ---------------------------------------------------------------------------

sep("Step 4: POST /scheduled-acquisitions with unknown acquisition_type (expect 400)")
r = requests.post(
    SCHEDULED_ACQUISITIONS_URL,
    json={
        "subject_id": SUBJECT_ID,
        "date": date.today().isoformat(),
        "acquisition_type": f"not-a-real-type-{int(time.time())}",
    },
)
check(r, 400)

# ---------------------------------------------------------------------------
# Step 5: POST /scheduled-acquisitions with a missing field → 422 (typed body)
# ---------------------------------------------------------------------------

sep("Step 5: POST /scheduled-acquisitions missing acquisition_type (expect 422)")
r = requests.post(
    SCHEDULED_ACQUISITIONS_URL,
    json={"subject_id": SUBJECT_ID, "date": date.today().isoformat()},
)
check(r, 422)

# ---------------------------------------------------------------------------
# Step 6: POST /scheduled-acquisitions, date=today, our acquisition_type → 200
# ---------------------------------------------------------------------------

sep("Step 6: POST /scheduled-acquisitions (date=today, expect 200 + uuid)")
r = requests.post(
    SCHEDULED_ACQUISITIONS_URL,
    json={"subject_id": SUBJECT_ID, "date": date.today().isoformat(), "acquisition_type": ACQUISITION_TYPE},
)
created = check(r, 200)
assert "uuid" in created, f"missing uuid in response: {created}"
today_uuid = created["uuid"]
print(f"  uuid: {today_uuid}")

# ---------------------------------------------------------------------------
# Step 7: GET /scheduled-acquisitions/{uuid} — verify full record
# ---------------------------------------------------------------------------

sep("Step 7: GET /scheduled-acquisitions/{uuid} (verify record)")
r = requests.get(f"{SCHEDULED_ACQUISITIONS_URL}/{today_uuid}")
record = check(r, 200)
assert record["subject_id"] == SUBJECT_ID, f"unexpected subject_id: {record}"
assert record["date"] == date.today().isoformat(), f"unexpected date: {record}"
assert record["platform"] == PLATFORM, f"expected platform resolved to 'test', got {record}"
assert record["acquisition_type"] == ACQUISITION_TYPE, f"unexpected acquisition_type: {record}"
print(f"  record: {record}")

# ---------------------------------------------------------------------------
# Step 8: GET /scheduled-acquisitions/{made-up-uuid} → 404
# ---------------------------------------------------------------------------

sep("Step 8: GET /scheduled-acquisitions/{made-up-uuid} (expect 404)")
r = requests.get(f"{SCHEDULED_ACQUISITIONS_URL}/not-a-real-uuid-{int(time.time())}")
check(r, 404)

# ---------------------------------------------------------------------------
# Step 9: GET /scheduled-acquisitions (default, future-only) — today's uuid present
# ---------------------------------------------------------------------------

sep("Step 9: GET /scheduled-acquisitions (future-only, today's uuid should appear)")
r = requests.get(SCHEDULED_ACQUISITIONS_URL)
future_records = check(r, 200)
future_uuids = {rec["uuid"] for rec in future_records}
assert today_uuid in future_uuids, f"today's uuid {today_uuid} missing from future-only list"
print(f"  today's uuid present among {len(future_records)} future records")

# ---------------------------------------------------------------------------
# Step 10: POST /scheduled-acquisitions, date=yesterday (past) — second uuid
# ---------------------------------------------------------------------------

sep("Step 10: POST /scheduled-acquisitions (date=yesterday, expect 200 + uuid)")
yesterday = (date.today() - timedelta(days=1)).isoformat()
r = requests.post(
    SCHEDULED_ACQUISITIONS_URL,
    json={"subject_id": SUBJECT_ID, "date": yesterday, "acquisition_type": ACQUISITION_TYPE},
)
created_past = check(r, 200)
past_uuid = created_past["uuid"]
print(f"  uuid: {past_uuid}")

# ---------------------------------------------------------------------------
# Step 11: GET /scheduled-acquisitions (default, future-only) — past uuid excluded
# ---------------------------------------------------------------------------

sep("Step 11: GET /scheduled-acquisitions (future-only, past uuid should be excluded)")
r = requests.get(SCHEDULED_ACQUISITIONS_URL)
future_records = check(r, 200)
future_uuids = {rec["uuid"] for rec in future_records}
assert past_uuid not in future_uuids, f"past uuid {past_uuid} unexpectedly present in future-only list"
assert today_uuid in future_uuids, "today's uuid should still be present"
print(f"  past uuid correctly excluded; today's uuid still present ({len(future_records)} future records)")

# ---------------------------------------------------------------------------
# Step 12: GET /scheduled-acquisitions?include_past=true — both uuids present
# ---------------------------------------------------------------------------

sep("Step 12: GET /scheduled-acquisitions?include_past=true (both uuids should appear)")
r = requests.get(SCHEDULED_ACQUISITIONS_URL, params={"include_past": "true"})
all_records = check(r, 200)
all_uuids = {rec["uuid"] for rec in all_records}
assert today_uuid in all_uuids, "today's uuid missing from include_past=true list"
assert past_uuid in all_uuids, "past uuid missing from include_past=true list"
print(f"  both uuids present among {len(all_records)} total records")

print("\n" + "=" * 60)
print("  ALL STEPS PASSED")
print("=" * 60)
