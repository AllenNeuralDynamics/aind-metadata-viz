# Extend Session Viewer: Add Dynamic Foraging + Rig-Side Manifest Detection

## Context

We built a Phase 0 Session Status Viewer as a Streamlit page in [aind-metadata-viz](https://github.com/AllenNeuralDynamics/aind-metadata-viz) (see [PR #64](https://github.com/AllenNeuralDynamics/aind-metadata-viz/pull/64)). It currently works for VR Foraging (`vr_foraging_fiber` job type), joining DTS job status with DocDB asset records.

Now we need to extend it to support **Dynamic Foraging** and, critically, to replicate **Alex Piet's automated session tracking email** which detects sessions at the rig level — including sessions that never made it to the DTS.

## Current Status (as of 2026-03-19)

**Tier 1 is complete** for both Dynamic Foraging and VR/Patch Foraging:

- Dynamic Foraging added to the project dropdown
- DTS job types configured (`dynamic_foraging_behavior_and_fiber`, `dynamic_foraging_behavior_only`, `dynamic_foraging_compression`, `dynamic_foraging`)
- DocDB query strategy: raw records via `name $in [DTS job names]` (fast, ~0.1s), derived records via `data_description.input_data_name $in [DTS job names]` (~8s in V1)
- Derived asset columns: Behavior Asset, Video Asset, FIP Asset
- Modal inspector for metadata and DTS task drill-down

**Tier 2 (rig-level detection) is now implemented for Dynamic Foraging.** See below.

---

## What Alex's Tracker Does

Alex runs a cron job from the repo [AllenNeuralDynamics/behavior_communication](https://github.com/AllenNeuralDynamics/behavior_communication). The key files are in `data_transfer/`:

### How it detects sessions at the rig (pre-DTS)

`check_upload_manifests.py` SSHs into every behavior rig computer (listed in `computer_list.json`) and lists the contents of two directories:

- `C:\Users\svc_aind_behavior\Documents\aind_watchdog_service\manifest` — sessions waiting to upload
- `C:\Users\svc_aind_behavior\Documents\aind_watchdog_service\manifest_complete` — sessions that have uploaded

Manifest filenames follow the pattern: `manifest_behavior_<subject_id>_<date>_<time>.yml`

This is how Alex detects "missing data" sessions — mice that were scheduled/expected to run but have no manifest file, meaning the acquisition software either didn't run or didn't produce output.

### How it determines status

`parse_upload_manifests.py` cross-references manifests against DocDB and Code Ocean to assign each session a status:

- **missing data** — no manifest file from yesterday (session expected but didn't happen)
- **stalled** — manifest exists but didn't move to the complete folder
- **lingering manifest** — manifest in both folders (shouldn't happen)
- **no data assets** — manifest exists but no assets on Code Ocean
- **no processed data asset** — raw asset exists but no derived asset
- **processing errors** — derived asset exists but has errors
- **complete** — raw and processed assets both exist
- **on-track** — queued for upload, hasn't reached upload time yet
- **scheduled** — scheduled to run today but no manifest yet

### How it gets watchdog logs

`get_watchdog_logs.py` SSHs into rigs and SCPs the watchdog log file from:
`C:\ProgramData\aind\aind-watchdog-service\aind-watchdog-service.log`

These are saved to: `/allen/programs/mindscope/workgroups/behavioral-dynamics/aind_logs/watchdog_logs/`

### The email output

The daily email shows: status, Beh/Video/FIP pass/fail columns, mouse ID, PI, hostname, trainer, manifest filename. Color-coded by status. Includes summary counts and a backlog section.

---

## Tier 2 Implementation (completed 2026-03-19)

### Key architectural decision: no SSH from the app

Alex's cron job does the SSH to rigs. **We do not SSH from the Panel app.** Instead, we read from the network share where Alex saves the already-fetched data:

```
/allen/programs/mindscope/workgroups/behavioral-dynamics/aind_logs/watchdog_manifests/
```

The cron job runs **once daily at 6am** and writes two files per rig:
- `{RIG}.txt` — Windows `dir` listing of `manifest/` (staged, awaiting watchdog pickup)
- `{RIG}_complete.txt` — Windows `dir` listing of `manifest_complete/` (watchdog processed)

Each file is a raw Windows directory listing, e.g.:
```
03/18/2026  09:35 AM     764 manifest_behavior_841859_2026-03-18_09-35-42.yml
```

### What was implemented

Three changes to `session_viewer.py`:

#### 1. `load_manifest_sessions()` — new cached data loader

Reads all `{RIG}.txt` and `{RIG}_complete.txt` files from `MANIFEST_DIR`. Parses each line with a regex to extract the manifest filename, strips the `manifest_` prefix and `.yml` suffix to get the raw asset name (e.g. `behavior_822683_2026-03-18_09-35-42`), then applies `get_session_name()` to get the canonical join key.

Returns `{session_name: {"rig": str, "status": "pending"|"complete", "session_raw": str}}`.

- `status = "complete"` — manifest was in `manifest_complete/` (watchdog processed it, should have been submitted to DTS)
- `status = "pending"` — manifest was still in `manifest/` at 6am (not yet picked up)
- `"complete"` takes precedence if the same session appears in both files
- Cached for 1 hour (files only update once daily)
- Degrades gracefully if `MANIFEST_DIR` is not mounted

#### 2. `rig_log_cell()` — new HTML cell renderer

Replaces the old `(not yet implemented)` placeholder in the "Rig Log" column:
- `⬜` — no manifest found for this session
- `✅ {rig}` — manifest processed by watchdog; hover shows rig hostname
- `⏳ {rig}` — manifest staged on rig, awaiting watchdog pickup (amber color)

#### 3. Manifest-only rows in `build_session_table()`

After the main DTS+DocDB session loop, a second pass over `manifest_sessions` adds rows for sessions that:
- Are within the selected date range
- Are **not** already in `all_sessions` (absent from both DTS and DocDB)

These "fell through the cracks" rows show the rig manifest status, Watchdog events (if any), and ⬜ for all pipeline columns. The DTS column shows ⬜ (within 14 days) or "N/A >14 days" (older).

### How it's enabled per-project

`PROJECT_CONFIG` for Dynamic Foraging has `"use_manifests": True`. In `on_load()`, this flag triggers a call to `load_manifest_sessions()` and passes the result to `build_session_table()`. Projects without the flag (VR/Patch Foraging) get an empty dict, so the Rig Log column shows ⬜ for all rows and no extra rows are added.

Subject ID filtering is applied to manifest sessions when the subject filter is active.

### Coverage and limitations

- **Scope**: Dynamic Foraging only. All manifest files use the `behavior_` prefix, which is the Dynamic Foraging naming convention. VR/Patch Foraging rigs may use different manifest formats or may not be covered by Alex's cron job.
- **Staleness**: Data is a snapshot from 6am. Sessions run after 6am will not appear as manifest-only rows until the next morning. They will appear via DTS once uploaded.
- **"complete" ≠ successfully uploaded**: A manifest in `manifest_complete/` means the watchdog picked it up and attempted to submit to DTS. The DTS job may have still failed — in that case the session will appear via DTS with a failed status (not as a manifest-only row).
- **Network access**: `MANIFEST_DIR` must be mounted on the server running the Panel app. The app degrades gracefully (Rig Log shows ⬜ for all rows) if the path is unavailable.

### Extension to Patch Foraging

Unclear. Alex's system is focused on Dynamic Foraging behavior rigs. Patch foraging rigs may or may not:
- Use the same watchdog service / manifest format
- Be included in `computer_list.json`
- Write to the same or a parallel network share

If not covered by Alex's system, Patch Foraging Tier 2 would need to wait for the token server implementation (a planned AIND infrastructure feature that would provide a proper API for rig-side session status).

### Key files

- `session_viewer.py` — `MANIFEST_DIR`, `_MANIFEST_LINE_RE`, `load_manifest_sessions()`, `rig_log_cell()`, `build_session_table()` manifest-only rows, `on_load()` manifest loading
- `parse_upload_manifests.py` at https://github.com/AllenNeuralDynamics/behavior_communication/blob/main/data_transfer/parse_upload_manifests.py
- `check_upload_manifests.py` at https://github.com/AllenNeuralDynamics/behavior_communication/blob/main/data_transfer/check_upload_manifests.py
- `computer_list.json` in the same repo — lists all rigs that are SSHed into

### What NOT to do

- Don't SSH into rigs from the Panel app
- Don't rebuild the DTS task view or log viewer — link to them (already done via modal)
- Don't worry about Loki/Grafana integration for now
- Don't add scheduling or WaterLog features
