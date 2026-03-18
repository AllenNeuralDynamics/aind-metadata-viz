# Extend Session Viewer: Add Dynamic Foraging + Rig-Side Manifest Detection

## Context

We built a Phase 0 Session Status Viewer as a Streamlit page in [aind-metadata-viz](https://github.com/AllenNeuralDynamics/aind-metadata-viz) (see [PR #64](https://github.com/AllenNeuralDynamics/aind-metadata-viz/pull/64)). It currently works for VR Foraging (`vr_foraging_fiber` job type), joining DTS job status with DocDB asset records.

Now we need to extend it to support **Dynamic Foraging** and, critically, to replicate **Alex Piet's automated session tracking email** which detects sessions at the rig level — including sessions that never made it to the DTS.

## Current Status (as of 2026-03-12)

**Tier 1 is complete** for both Dynamic Foraging and VR/Patch Foraging:

- Dynamic Foraging added to the project dropdown
- DTS job types configured (`dynamic_foraging_behavior_and_fiber`, `dynamic_foraging_behavior_only`, `dynamic_foraging_compression`, `dynamic_foraging`)
- DocDB query strategy: raw records via `name $in [DTS job names]` (fast, ~0.1s), derived records via `data_description.input_data_name $in [DTS job names]` (~8s in V1)
- Derived asset columns: Behavior Asset, Video Asset, FIP Asset
- Modal inspector for metadata and DTS task drill-down
- Rig Log column added as placeholder `(not yet implemented)` pending Tier 2

**Tier 2 (rig-level detection) is not yet implemented.** See below.

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

## Tier 2 Implementation Plan

### Key architectural point: no SSH from the app

Alex's cron job does the SSH to rigs. **We do not SSH from the Panel app.** Instead, we read from the network share where Alex saves the already-fetched data:

```
/allen/programs/mindscope/workgroups/behavioral-dynamics/aind_logs/
```

The `FileSystemRigLogSource` stub in `session_viewer.py` is designed for exactly this.

### Open questions before implementing

1. **Cron frequency** — This is the critical question. If the cron job runs only once daily (e.g. overnight), the rig log data is stale by mid-day and not useful for real-time session monitoring. We need to know:
   - How often does the cron run? (check `computer_list.json` / crontab in behavior_communication repo)
   - Is there a way to increase frequency, or run it on-demand?
   - Ideal: runs every 15–30 min so the Rig Log column reflects current rig state during the day.

2. **File structure at the network share** — What files are written, how are they named, and what fields do they contain? We need to map manifest filenames → session names to join with the table.

3. **Network share accessibility** — Is `/allen/programs/mindscope/workgroups/behavioral-dynamics/aind_logs/` mounted on the server where the Panel app runs? Verify with a quick `ls` from that server.

4. **Coverage** — Does `computer_list.json` include all Dynamic Foraging rigs? Any rigs missing?

### Extension to Patch Foraging

Unclear. Alex's system is focused on Dynamic Foraging behavior rigs. Patch foraging rigs may or may not:
- Use the same watchdog service / manifest format
- Be included in `computer_list.json`
- Write to the same or a parallel network share

If not covered by Alex's system, Patch Foraging Tier 2 would need to wait for the token server implementation (a planned AIND infrastructure feature that would provide a proper API for rig-side session status).

### Implementation sketch (once open questions are resolved)

```python
class FileSystemRigLogSource(RigLogSource):
    BASE_PATH = "/allen/programs/mindscope/workgroups/behavioral-dynamics/aind_logs"

    def get_manifest_sessions(self, date_from, date_to):
        # Read manifest listing files from BASE_PATH
        # Parse filenames → session names (subject_id, date, time)
        # Return list of dicts with at least: session_name, status, hostname
        ...
```

The `build_session_table` function already has a `RigLogSource` parameter slot in the interface. Populating the "Rig Log" column just requires wiring in a concrete `FileSystemRigLogSource` implementation.

### Key files to reference

- `session_viewer.py` — `RigLogSource` stub, `FileSystemRigLogSource` stub, "Rig Log" column placeholder
- `parse_upload_manifests.py` at https://github.com/AllenNeuralDynamics/behavior_communication/blob/main/data_transfer/parse_upload_manifests.py
- `check_upload_manifests.py` at https://github.com/AllenNeuralDynamics/behavior_communication/blob/main/data_transfer/check_upload_manifests.py
- `computer_list.json` in the same repo — lists all rigs that are SSHed into

### What NOT to do

- Don't SSH into rigs from the Panel app
- Don't rebuild the DTS task view or log viewer — link to them (already done via modal)
- Don't worry about Loki/Grafana integration for now
- Don't add scheduling or WaterLog features
