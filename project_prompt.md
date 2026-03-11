# Build a Session Status Viewer for AIND Metadata Portal

## Goal

Build a Streamlit page called `session_tracker.py` that can be added to the AIND metadata portal (https://github.com/AllenNeuralDynamics/aind-metadata-viz). This page gives scientists a project-filtered, session-level view showing where their data collection sessions are in the processing pipeline.

## Context

Scientists collect data on rigs. That data flows through: acquisition → watchdog → Data Transfer Service (DTS) → S3 → DocDB registration → Code Ocean processing pipelines → derived assets in DocDB. There is currently no single view showing end-to-end status. The DTS has its own job viewer and the metadata portal has an asset viewer, but they're separate tools. This page connects them.

## Architecture

**This is a read-only viewer. It makes zero changes to any existing system.** It queries two data sources on every page load:

### Data Source 1: DocDB (MongoDB)

DocDB contains metadata records for all data assets. Each record has fields including:
- `name` — the asset name (e.g. `behavior_822683_2026-02-26_16-59-38`)
- `subject.subject_id` — the mouse ID
- `data_description.project_name` — the project name
- `data_description.modality` — list of modalities
- `data_description.data_level` — either `raw` or `derived`
- `acquisition.acquisition_start_time` or `data_description.creation_time`

For a typical VR Foraging + FIP session, DocDB will contain:
- 1 raw asset (modalities: `behavior, behavior-videos`)
- 1 derived asset (modality: `behavior`) 
- 1 derived asset (modality: `fib`)

Use the `aind_data_access` library to query DocDB. Example pattern:

```python
from aind_data_access_api.document_db import MetadataDbClient

API_GATEWAY_HOST = "api.allenneuraldynamics.org"
DATABASE = "metadata_index"
COLLECTION = "data_assets"

client = MetadataDbClient(
    host=API_GATEWAY_HOST,
    database=DATABASE,
    collection=COLLECTION,
)

# Get records for a project
filter_query = {
    "data_description.project_name": ["Cognitive flexibility in patch foraging"],
}
results = client.retrieve_docdb_records(
    filter_query=filter_query,
    paginate_batch_size=500,
)
```

### Data Source 2: DTS REST API

The DTS is backed by Airflow. Its API is at `http://aind-data-transfer-service`. Key endpoint:

**GET `/api/v1/get_job_status_list`** — returns JSON with job statuses. Accepts query params:
- `dag_ids` — default `["transform_and_upload", "transform_and_upload_v2"]`
- `states` — optional filter (e.g. `["success", "failed", "running"]`)
- `execution_date_gte` — ISO datetime, must be within last 14 days (hardcoded limit)
- `execution_date_lte` — ISO datetime

Response includes for each job:
- `name` — the asset name / S3 prefix (matches DocDB asset names)
- `job_type` — e.g. `vr_foraging_fiber`, `SmartSPIM`, `vr_foraging`
- `job_state` — `success`, `failed`, `running`, `queued`
- `job_id` — the DAG run ID (needed for deep-linking)
- `dag_id` — typically `transform_and_upload_v2`
- `start_time`, `end_time`, `submit_time`

**Deep-linkable task view:** The URL pattern
```
http://aind-data-transfer-service/job_tasks_table?dag_id={dag_id}&dag_run_id={job_id}
```
renders a full task breakdown for any job. This is a confirmed working pattern — the page renders with all tasks, statuses, and log links. Use this for drill-down rather than rebuilding task views.

**Important: The DTS API only returns jobs from the last 14 days.** For older sessions, we can still show DocDB asset records but won't have DTS job status or drill-down links.

## What to Build

### Page layout

A Streamlit page with:

1. **Sidebar filters:**
   - Project name dropdown (query DocDB for distinct project names)
   - Date range selector (default: last 7 days)
   - Optional subject ID filter

2. **Main content: a session status table**

Each row represents one acquisition session (identified by subject_id + acquisition_start_time). Columns:

| Column | Source | What it shows |
|--------|--------|--------------|
| Subject ID | DocDB | The mouse ID |
| Session Date | DocDB | Acquisition start datetime |
| DTS Upload | DTS API | Status of the DTS job (success/failed/running/queued). Link to DTS task view. |
| Raw Asset | DocDB | Whether a raw asset exists. Link to metadata record. |
| Derived: behavior | DocDB | Whether a derived behavior asset exists. Link to CO. |
| Derived: fib | DocDB | Whether a derived fib asset exists (if applicable). Link to CO. |

Status indicators:
- ✅ for completed/exists
- ❌ for failed
- ⏳ for in progress
- ⬜ for not yet / not applicable

3. **Drill-down links:**
   - DTS status cells should link to: `http://aind-data-transfer-service/job_tasks_table?dag_id={dag_id}&dag_run_id={job_id}`
   - Asset cells should link to the metadata portal asset page or Code Ocean

### Core logic

```
1. Query DocDB for raw assets matching the project + date range
2. For each raw asset, query DocDB for derived assets with matching subject_id + acquisition_start_time
3. Query DTS API for jobs within the date range (if within 14-day window)
4. Join: match DTS jobs to DocDB raw assets by asset name
5. Render the table with status indicators and links
```

### Joining DTS jobs to DocDB assets

The DTS job `name` field contains the S3 prefix, which corresponds to the asset name in DocDB. The join key is this name. Example: a DTS job with `name = "822683_2026-02-26_16-59-38"` matches the DocDB raw asset whose `name` contains that string.

### Handling derived asset expectations

Different job types produce different derived assets. For the initial implementation, infer expected derived assets from the raw asset's modalities:
- If raw asset has `behavior` modality → expect a derived `behavior` asset
- If raw asset has `fib` modality → expect a derived `fib` asset
- If both → expect both

Show the appropriate columns dynamically based on what modalities appear in the filtered results.

## Reference Implementation

Look at `src/aind_metadata_viz/fiber_viewer.py` in the aind-metadata-viz repo for the pattern of:
- How pages are structured in this app
- How DocDB is queried
- How Streamlit components are used

The app structure lives in `src/aind_metadata_viz/app.py` — that's where new pages get registered.

## Technical Notes

- The metadata portal uses Streamlit and is deployed via Docker
- DocDB access uses `aind_data_access_api` — check the repo's existing requirements for the version
- The DTS API is internal (HTTP, no auth required from within the Allen network)
- Use `httpx` or `requests` to call the DTS API
- Keep it simple: one file (`session_tracker.py`), minimal dependencies beyond what the repo already has

## What NOT to build

- Don't rebuild the DTS task drill-down or log viewer — just link to it
- Don't rebuild the asset viewer — just link to it  
- Don't try to track pre-DTS events (acquisition failures, watchdog) — that requires a token server that doesn't exist yet
- Don't add write functionality — this is purely read-only
- Don't worry about scheduling, WaterLog, or IACUC metadata — those are separate projects