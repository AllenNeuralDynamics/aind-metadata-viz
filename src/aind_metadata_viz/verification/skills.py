"""Skill documents written into every agent job directory.

``omp`` inherits rules, skills and MCP servers from ``.claude`` on disk, so
the job directory gets a ``.claude/skills/<name>/SKILL.md`` for each of the
four skills the plan calls for. They are Python string constants rather than
package data files so no packaging configuration has to change, and so the
schema documentation cannot drift away from ``models.py`` unnoticed.
"""

from __future__ import annotations

from typing import Dict

GRAPH_SCHEMA = """---
name: graph-schema
description: Node JSON schemas, storage layout, and the outbox contract.
  Read this before writing any node document.
---

# Verification graph schema

Three node kinds share one id namespace. Every node is a JSON document.

## Entity - a noun

```json
{
  "kind": "entity",
  "id": "ent-unit-660023_2023-08-08-123",
  "entity_type": "unit",
  "label": "Unit 123 (session 660023_2023-08-08)",
  "grounding": {
    "table": "platform_swdb_units",
    "asset_name": "660023_2023-08-08",
    "selector": {"unit_id": 123}
  }
}
```

`entity_type` is one of: `unit`, `session`, `brain_area`, `stimulus`,
`behavior`, `population`. A `population` entity also carries
`"members": ["<entity id>", ...]`.

## Relation - a verb

```json
{
  "kind": "relation",
  "id": "rel-responds-to",
  "label": "responds to",
  "definition": "Mean firing rate in the 0-200ms window after stimulus onset
                 exceeds the pre-stimulus baseline, Wilcoxon signed-rank
                 p < 0.01 across trials.",
  "code": "code/rel-responds-to/",
  "signature": {"subject": ["unit"], "object": ["stimulus"]}
}
```

The `definition` must be operational: a reader has to be able to tell from it
alone what would make the relation false. "responds to" means nothing until it
names a test.

## Statement - a triple plus evidence

```json
{
  "kind": "statement",
  "id": "stmt-unit-123-responds-vis1",
  "label": "Unit 123 responds to vis1",
  "subject": "ent-unit-660023_2023-08-08-123",
  "relation": "rel-responds-to",
  "object": "ent-stim-vis1",
  "value": {"p": 0.0004, "effect": "+3.1 Hz", "holds": true},
  "depends_on": ["stmt-unit-123-located-ca3"],
  "code": "code/stmt-unit-123-responds-vis1/",
  "data": [{"table": "platform_swdb_events",
            "asset_name": "660023_2023-08-08"}],
  "verification": {
    "reproducible": {"status": "not_attempted"},
    "replicable": {"status": "not_attempted",
                   "method": "5-fold cross-validation over trials"},
    "robust": {"status": "not_attempted"},
    "generalizable": {"status": "not_attempted"}
  }
}
```

Rules the server enforces on write, so get them right:

- The subject's and object's `entity_type` must appear in the relation's
  `signature`. A statement whose object is a `session` cannot use a relation
  whose signature says `object: ["stimulus"]`.
- Every id in `depends_on` must already be in the graph **or** be another
  document in your outbox. Dangling references are rejected outright.
- `depends_on` must not form a cycle.
- You never set `status` or `provenance`. The server owns both. Everything you
  author enters as `proposed`.
- Set each axis's `status` to `not_attempted` unless a run actually happened.
  Claiming an axis you did not test is the one unforgivable error here.

## Storage layout

```
s3://aind-scratch-data/verification-graph/
  nodes/<node-id>.json
  code/<node-id>/...
  runs/<node-id>/<timestamp>/
  snapshots/graph.json
  manifest.json
```

## The outbox contract

**You cannot write to the graph.** Write finished node documents to
`outbox/nodes/<node-id>.json` and code sidecars to
`outbox/code/<node-id>/<file>` in this job directory. When you exit, the
server validates every document through exactly the same code path as the
public create endpoint - Pydantic models, triple signature checks, grounding
checks, code layout gates - and inserts what passes as `proposed` nodes.
Anything that fails validation is reported back with a reason and discarded.

Nothing you produce reaches `verified` without a reproducibility run and an
admin approval, so do not try to shortcut that; write honest documents
instead.
"""

DYNAMIC_ROUTING_DATA = """---
name: dynamic-routing-data
description: The dynamic routing dataset, its cached parquet tables, and how
  to read them from a job's local data directory.
---

# Dynamic routing data

The Dynamic Routing task is a cross-modal set-shifting task. A mouse is
rewarded for licking to a target stimulus, and which modality is the target
alternates across blocks within a session.

- Stimuli: `vis1` and `vis2` (visual gratings), `sound1` and `sound2`
  (auditory tones). `vis1` and `sound1` are the two possible targets.
- A session is divided into blocks. In a visual block, licking to `vis1` is
  rewarded and licking to `sound1` is not; in an auditory block the roles
  swap. `vis2` and `sound2` are never rewarded.
- The response window is the fixed interval after stimulus onset in which a
  lick counts as a response.
- Performance is usually summarized per block as d-prime between the target
  and the non-target of the same modality, and between modalities.

## Cached tables

The merged SWDB NWB files are far too large to read directly, so a cache job
flattens them into parquet tables partitioned by `asset_name`:

| Table | One row per | Key columns |
|---|---|---|
| `platform_swdb_sessions` | session | `asset_name`, `subject_id`, `session_date` |
| `platform_swdb_trials` | trial | stimulus, block, response, times |
| `platform_swdb_performance` | block x measure | d-prime and rate measures |
| `platform_swdb_events` | event | `kind`, `t`, `t_stop`, `label`, `value` |
| `platform_swdb_eye` | eye-tracking sample | pupil area, gaze |
| `platform_swdb_running` | running sample | speed |

`platform_swdb_events.kind` is one of `lick`, `reward`,
`quiescent_violation`, `epoch`, `opto`, `vis_rf`, `aud_rf`. Times (`t`,
`t_stop`) are seconds from `session_start_time`.

## Reading them

In S3 a partition lives at
`data-asset-cache/<version>/<table>/asset_name=<name>/data.pqt`.

The runner downloads every partition your node declares in its `data` list
into the job's local `data/` directory, **mirroring that same relative path**.
So `analysis.py` reads:

```python
import os
import pandas as pd

def _table(data_dir, table, asset_name):
    return pd.read_parquet(
        os.path.join(data_dir, table, f"asset_name={asset_name}", "data.pqt")
    )
```

Declare every table you read in the node's `data` list, or it will not be
downloaded and your analysis will fail with a missing file.

**Verify column names before you rely on them.** Read one partition and print
its columns rather than assuming a schema from this document; the cache
evolves, and a wrong column name is a failed run.
"""

NODE_AUTHORING = """---
name: node-authoring
description: How to write analysis.py, its tests, and its known cases so a
  node can pass the server's code gates.
---

# Authoring a node's code

Every relation and statement node with code gets a directory with a fixed
layout. The server refuses to promote a node out of `proposed` unless all of
it is present and green.

```
outbox/code/<node-id>/
  analysis.py          # entry point: main(data_dir) -> result dict
  test_analysis.py     # unit tests, 100% line coverage of analysis.py
  known_cases.json     # fixture inputs with expected outputs
  environment.lock     # pinned pip requirements (pip freeze format)
```

## analysis.py

```python
\"\"\"Whether unit 123 responds to vis1 in session 660023_2023-08-08.\"\"\"

import os
import pandas as pd


def compute(events, trials):
    \"\"\"Pure function over dataframes - this is what the tests exercise.\"\"\"
    ...
    return {"p": p_value, "effect": effect, "holds": bool(p_value < 0.01)}


def known_case(payload):
    \"\"\"Run one known_cases.json entry through the same pure function.\"\"\"
    return compute(pd.DataFrame(payload["events"]),
                   pd.DataFrame(payload["trials"]))


def main(data_dir):
    \"\"\"Entry point the runner calls with the local data directory.\"\"\"
    asset = "asset_name=660023_2023-08-08"
    events = pd.read_parquet(
        os.path.join(data_dir, "platform_swdb_events", asset, "data.pqt"))
    trials = pd.read_parquet(
        os.path.join(data_dir, "platform_swdb_trials", asset, "data.pqt"))
    return compute(events, trials)
```

Requirements:

- `main(data_dir)` returns a **JSON-serializable dict**. Its canonical JSON
  serialization is hashed into `result_hash`; anything unstable in it (a
  timestamp, a dict ordering, an unrounded float that varies by platform)
  will make the node fail its own reproducibility check on the second run.
  Round floats explicitly.
- Include a boolean `holds` key saying whether the claim is true. The
  replicable, robust and generalizable axes are evaluated on it.
- Be deterministic. Fix every seed. Never read the clock, the network, or
  anything outside `data_dir`.
- Split the logic into a pure function over in-memory data plus a thin `main`
  that loads files. That split is what makes 100% coverage achievable.

## test_analysis.py

Plain `pytest`. The gate is `pytest --cov=analysis --cov-fail-under=100`, so
**every line of analysis.py** must be exercised, `main` included - use a
`tmp_path` fixture with a small parquet file written by the test.

## known_cases.json

A list of cases, each `{"name", "input", "expected"}`. `input` is passed to
`analysis.known_case(...)` when that hook exists, otherwise to `main`.

At least one case must be synthetic data whose answer is known **by
construction**:

```json
[
  {"name": "injected response tests positive", "input": {...},
   "expected": {"p": 0.0, "effect": 5.0, "holds": true}},
  {"name": "flat unit tests negative", "input": {...},
   "expected": {"p": 1.0, "effect": 0.0, "holds": false}}
]
```

Known cases are the guard against code that runs cleanly but tests the wrong
thing. A test suite proves the code does what you wrote; a known case proves
what you wrote was the right thing. Write both a positive and a negative case
- code that returns `True` unconditionally passes a positive case.

## environment.lock

`pip freeze` format, fully pinned:

```
numpy==1.26.4
pandas==2.2.2
pyarrow==16.1.0
scipy==1.13.1
```

Keep it minimal. Every package is installed into a fresh virtualenv on the
first run that uses this lock file.
"""

RECURSIVE_VERIFICATION = """---
name: recursive-verification
description: How to decompose a high-level claim into verified sub-claims,
  reusing what the graph already has. Follow this for every request.
---

# Recursive verification

A request like "verify that 30% of CA3 units respond to vis1" is not one
node. It is a small tree, and your job is to build it bottom-up so the claim
at the top sits on foundations that are individually checkable.

## The procedure

**1. Search before you author.** Read `manifest.json` in this job directory.
For every sub-claim you need, look for a node that already covers it. If a
verified node exists, reuse its id in `depends_on` and do not re-author it.
Duplicating an existing verified node is a worse outcome than authoring
nothing.

**2. Author the lowest level first.** For the CA3 example:

- Layer 1: per-unit `is located in` statements, from the units table. Nearly
  trivial - a parquet lookup - and that is the point. Even trivial claims get
  the full record, and they verify cheaply.
- Layer 2: per-unit `responds to` statements, from the events and trials
  tables.
- Layer 3: the population aggregate, whose `depends_on` spans every layer-1
  and layer-2 node it summarizes.

Write the entities and relations you need before the statements that
reference them.

**3. Never emit a dangling reference.** Every id in a `depends_on`, and every
subject/relation/object id, must be either already in the manifest or another
document in your outbox. The server rejects the whole document otherwise.

**4. Declare axes honestly.** Say which verification axes the code you wrote
actually supports, and mark the rest `not_attempted`:

- `reproducible` - your `main(data_dir)` is deterministic over pinned data.
  Every node you write should support this one.
- `replicable` - your code can be re-run on held-out or resampled data and the
  claim still evaluated. Name the exact resampling method in `method`.
- `robust` - an independent second implementation reaches the same conclusion.
  You have not written one unless you actually wrote one.
- `generalizable` - both data and code swapped.

Marking an axis `not_attempted` is a correct, complete answer. Claiming an
axis you did not test is the one thing that makes the whole graph worthless.

## Working style

- Inspect the data before you write the analysis. Read a partition, print the
  columns and a few rows, and confirm the schema matches what you assumed.
- Prefer many small, cheap, obviously-correct statements over one large clever
  one. The graph's value is that the foundations are boring.
- If a sub-claim turns out to be false, say so and author it as a statement
  whose value records that it does not hold. A false statement honestly
  recorded is a useful node; a missing one is not.
"""

#: Skill name -> SKILL.md body, written into ``.claude/skills/<name>/SKILL.md``.
SKILLS: Dict[str, str] = {
    "graph-schema": GRAPH_SCHEMA,
    "dynamic-routing-data": DYNAMIC_ROUTING_DATA,
    "node-authoring": NODE_AUTHORING,
    "recursive-verification": RECURSIVE_VERIFICATION,
}
