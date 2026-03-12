# Extend Session Viewer: Add Dynamic Foraging + Rig-Side Manifest Detection

## Context

We built a Phase 0 Session Status Viewer as a Streamlit page in [aind-metadata-viz](https://github.com/AllenNeuralDynamics/aind-metadata-viz) (see [PR #64](https://github.com/AllenNeuralDynamics/aind-metadata-viz/pull/64)). It currently works for VR Foraging (`vr_foraging_fiber` job type), joining DTS job status with DocDB asset records.

Now we need to extend it to support **Dynamic Foraging** and, critically, to replicate **Alex Piet's automated session tracking email** which detects sessions at the rig level — including sessions that never made it to the DTS.

## What Alex's Tracker Does

Alex runs a daily cron job from the repo [AllenNeuralDynamics/behavior_communication](https://github.com/AllenNeuralDynamics/behavior_communication). The key files are in `data_transfer/`:

### How it detects sessions at the rig (pre-DTS)

`check_upload_manifests.py` SSHs into every behavior rig computer (listed in `computer_list.json`) and lists the contents of two directories:

- `C:\Users\svc_aind_behavior\Documents\aind_watchdog_service\manifest` — sessions waiting to upload
- `C:\Users\svc_aind_behavior\Documents\aind_watchdog_service\manifest_complete` — sessions that have uploaded

Manifest filenames follow the pattern: `manifest_behavior_<subject_id>_<date>_<time>.yml`

This is how Alex detects "missing data" sessions — mice that were scheduled/expected to run but have no manifest file, meaning the acquisition software either didn't run or didn't produce output.

### How it determines status

`parse_upload_manifests.py` (38KB, the main logic) cross-references manifests against DocDB and Code Ocean to assign each session a status:

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

`get_watchdog_logs.py` SSHs into rigs and SCPs the watchdog log file from `C:\ProgramData\aind\aind-watchdog-service\aind-watchdog-service.log`

These are saved to: `/allen/programs/mindscope/workgroups/behavioral-dynamics/aind_logs/watchdog_logs/`

### The email output

The daily email shows: status, Beh/Video/FIP pass/fail columns, mouse ID, PI, hostname, trainer, manifest filename. Color-coded by status. Includes summary counts and a backlog section.

## What to Build

### Goal

Add Dynamic Foraging support to the session viewer that replicates and extends Alex's tracker, making it interactive rather than a static daily email.

### Approach: Two tiers

**Tier 1 (same as VR Foraging — no new infrastructure):**
- Query DocDB for Dynamic Foraging sessions (project name filtering)
- Query DTS API for matching jobs
- Join them and show status table with DTS drill-down links
- This should work with the existing session_tracker.py logic

**Tier 2 (replicate Alex's rig-level detection):**
- Read manifest files to detect sessions at the rig level
- This catches "missing data" and "stalled" sessions that Tier 1 misses
- Alex's scripts save manifest listings and watchdog logs to `/allen/programs/mindscope/workgroups/behavioral-dynamics/aind_logs/`
- If the metadata portal server can read this network path, we can use the already-fetched data
- If not, start with Tier 1 only and add Tier 2 later

### Recommended approach

Start with **Tier 1** to get dynamic foraging into the viewer quickly:

1. Add dynamic foraging project(s) to the project dropdown
2. Determine the correct DTS job type(s) for dynamic foraging sessions
3. The existing join logic (DocDB + DTS) should work as-is
4. Add behavior-specific derived asset columns (Beh, Video, FIP pass/fail as Alex shows)

Then investigate whether `/allen/programs/mindscope/workgroups/behavioral-dynamics/aind_logs/` is accessible for Tier 2 manifest detection.

### Dynamic Foraging specifics

From Alex's email, dynamic foraging sessions can have these modalities:
- **Beh** (behavior) — always present
- **Video** (behavior-videos) — usually present
- **FIP** (fiber photometry) — sometimes presenta

You'll need to check what the project name(s) are in DocDB for dynamic foraging. It might be multiple project names across different PIs.

### Key files to reference

- Your existing `session_tracker.py` from PR #64 — extend this
- `parse_upload_manifests.py` at https://github.com/AllenNeuralDynamics/behavior_communication/blob/main/data_transfer/parse_upload_manifests.py — reference for status logic
- `check_upload_manifests.py` at https://github.com/AllenNeuralDynamics/behavior_communication/blob/main/data_transfer/check_upload_manifests.py — reference for manifest detection

### What NOT to do

- Don't try to SSH into rigs from the Streamlit app (not feasible)
- Don't rebuild the DTS task view or log viewer — link to them via deep-linkable URLs
- Don't worry about Loki/Grafana integration for now
- Don't add scheduling or WaterLog features