# aind-session-mcp: Design Document

## Overview

A lightweight MCP server that exposes `aind-session-utils` functions as tools for Claude. Enables natural language queries about session status, pipeline health, and error diagnosis. Runs locally on your machine — if you're on VPN, all data sources are available.

## Architecture

```
Claude Desktop / Claude Code
  └── local MCP server (stdio)
        └── aind-session-mcp (Python process on YOUR machine)
              └── imports aind-session-utils
                    ├── DocDB      (cloud ✅)
                    ├── Code Ocean (cloud ✅, needs API token)
                    ├── DTS        (on-prem, needs VPN)
                    ├── Watchdog   (on-prem, needs VPN)
                    ├── Manifests  (network mount, needs VPN)
                    └── Rig logs   (network mount, needs VPN)
```

## Repo & Installation

Separate repo: `aind-session-mcp`. Depends on `aind-session-utils` + `mcp` SDK.

```bash
pip install aind-session-mcp
```

`claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "aind-sessions": {
      "command": "python",
      "args": ["-m", "aind_session_mcp"],
      "env": {
        "CODEOCEAN_DOMAIN": "https://codeocean.allenneuraldynamics.org",
        "CODEOCEAN_API_TOKEN": "<your-token>"
      }
    }
  }
}
```

**Credentials:** Only `CODEOCEAN_DOMAIN` and `CODEOCEAN_API_TOKEN`. DocDB is unauthenticated. On-prem sources need VPN but no auth.

## Tools

### 1. `find_sessions`
Search sessions by project, date range, subject. Returns status across all pipeline stages plus completeness. Starting point for most queries.

### 2. `get_session_detail`
Full DocDB metadata for one session (raw + derived records, QC evaluations, investigator list). Use for inspecting specific sessions.

### 3. `get_pipeline_log`
Fetch CO pipeline log text for a session. Use when investigating processing failures.

### 4. `find_incomplete_sessions`
Find sessions missing derived assets. Groups by missing modality pattern. Primary diagnostic tool.

### 5. `get_error_summary`
Batch-fetch pipeline logs for multiple sessions. Returns raw log text — Claude categorizes errors, finds patterns, counts occurrences. **This is the "wow" tool.**

### 6. `list_projects`
List available project configs and their expected modalities/pipelines.

### 7. `refresh_sessions`
Force re-query of specific sessions (for reprocessing cases).

### 8. `get_session_qc`
Fetch QC evaluation results for a session's derived assets. Returns per-modality pass/fail with evaluation names. DocDB `quality_control.evaluations` on derived records already has this data.

### 9. `get_qc_summary`
Aggregate QC pass rates across sessions for a project/date range. Equivalent to the QC Summary table in Alex's email — pass rates by modality and evaluation type, with 7-day and 30-day trends.

## Replacing Alex's Email

Alex Piet runs a daily cron job (`behavior_communication/data_transfer/parse_upload_manifests.py`) that generates an HTML status email for Dynamic Foraging. Here's what it covers and how we compare:

| Email feature | MCP coverage | Notes |
|---|---|---|
| Complete sessions (raw + derived) | ✅ `find_sessions` | |
| No processed data asset | ✅ `find_incomplete_sessions` | |
| No data assets on CO | ✅ `find_sessions` | raw_co_asset_id is None |
| Stalled uploads | ✅ Already reading manifests | manifest/ vs manifest_complete/ |
| Processing errors | ✅ `get_error_summary` | Claude reads logs, categorizes |
| QC pass/fail per modality (Beh/Video/FIP) | ✅ `get_session_qc` | DocDB quality_control.evaluations |
| QC summary (7d/30d rates) | ✅ `get_qc_summary` | Aggregation on DocDB |
| PI for each session | ✅ DocDB | `data_description.investigators` |
| Trainer for each session | ✅ DocDB | `session.experimenter_full_name` |
| Missing data (expected, no manifest) | ❌ | Needs rig schedule CSV — DF-specific |
| Scheduled (today, no manifest yet) | ❌ | Same — needs schedule CSV |
| Backlog (all-time unprocessed) | ✅ `find_incomplete_sessions` | Set days_back=365+ |

**Key insight on PI mapping:** Alex uses a manually maintained CSV (`DynamicForagingSchedule.csv`) to map mice → PIs. But DocDB already has `data_description.investigators` and `session.experimenter_full_name` on every record that made it to registration. We don't need the CSV for any session that exists in DocDB. The CSV is only needed for "missing data" and "scheduled" rows — sessions that were expected but never happened (no DocDB record exists). We should not try to replicate that — let Alex's cron keep doing rig-schedule detection.

## Automated Monitoring (Future)

Beyond the interactive MCP, the same library enables proactive monitoring:

**Scenario: Periodic health check + Slack notifications.** A cron job on an on-prem VM (with VPN access) runs every 2 hours:

1. Calls `find_incomplete_sessions` for the past 48 hours
2. Compares against last run to find *newly* stuck sessions
3. For new failures, fetches the CO log and uses Claude API to classify the error
4. Looks up the PI from `data_description.investigators` in DocDB
5. Posts a Slack message to the PI: "Session 823164 (mouse 823164, Kenta Hagihara) failed behavior processing — timeout during video compression on rig W10DT714674. GitHub issue #423 may be related."

This replaces the daily email blast with targeted, real-time notifications to the right person. Scientists stop scanning a wall of text every morning — they only hear about *their* problems, when they happen.

**Scenario: Weekly health report.** Claude generates a trend analysis: "Pipeline health is down 12% this week. 19 video compression timeouts on rig W10DT714027 (all after March 15). FIB pipeline clean. QC behavior pass rate steady at 95%. Fiber photometry CMOS Floor signal pass rate is 44% — this has been low for 30 days and may need investigation."

**Scenario: Backlog triage.** That 1,308-session processing backlog in Alex's email? An agent could batch through it: fetch logs, categorize by error type, group by rig/PI/date, and produce an actionable report in minutes. "842 are from pre-October 2024 on rigs that have been decommissioned — safe to mark as won't-fix. 312 are missing sync files. 154 are memory errors on W10DT714084."

## Source Availability

```python
def _availability_note() -> str:
    unavailable = []
    if not dts.is_available():
        unavailable.append("DTS (upload status) — requires VPN")
    if not watchdog.is_available():
        unavailable.append("Watchdog logs — requires VPN")
    if not manifests.is_available():
        unavailable.append("Rig manifests — requires network mount")
    if not codeocean.is_available():
        unavailable.append("Code Ocean — check API token")
    if unavailable:
        return "Note: some data sources are unavailable:\n" + \
               "\n".join(f"  - {s}" for s in unavailable)
    return ""
```

## Design Principles

1. **Tools return data, Claude does analysis.** Error categorization, pattern detection, and summaries are Claude's job. Don't build intelligence into tools.
2. **Shared store.** The parquet cache at `~/.cache/aind_session_utils/` is shared between the Panel viewer and MCP.
3. **Degrade gracefully.** Every source can be unavailable. Always return something useful.
4. **Tool descriptions are for Claude.** Write them as instructions for when/how to use each tool.
5. **Keep it thin.** ~200-300 lines. Query logic belongs in the library, not here.

## Example Conversations

### "How many sessions are stuck?"
```
User: How many Dynamic Foraging sessions are missing derived assets in the past 3 months?
Claude: [calls find_incomplete_sessions(project="Dynamic Foraging", days_back=90)]
Claude: 47 incomplete out of 1,832 total. 31 missing behavior, 12 missing FIB,
        4 with nothing processed. The behavior failures cluster in the past 2 weeks.
        Want me to pull the logs?
```

### "What's causing the failures?"
```
User: Yes, grab the logs for the behavior failures.
Claude: [calls get_error_summary(session_names=[...31...], pipeline="Behavior")]
Claude: 3 error categories:
        1. Video compression timeout (19 sessions) — all on W10DT714027, after March 15
        2. Missing sync file (8 sessions) — mixed rigs
        3. Memory error (4 sessions) — all on W10DT714031
        Want me to check GitHub for existing issues?
```

### "Check GitHub"
```
User: Yeah, check GitHub.
Claude: [calls GitHub MCP: search_issues(...)]
Claude: Found issue #423 "Video compression timeout" opened 3 days ago by @alex-piet.
        Covers your 19 sessions. Missing sync files — no existing issue. Want me to draft one?
```

### "What's the QC situation?"
```
User: How's QC looking this week for Dynamic Foraging?
Claude: [calls get_qc_summary(project="Dynamic Foraging", days_back=7)]
Claude: Behavior QC is solid — 95% pass rate on side bias, 100% on basic config.
        Fiber photometry CMOS Floor signal is concerning at 39% — it's been below 50%
        for 30 days. That might be a hardware issue on the FIP rigs. Everything else
        is above 90%.
```