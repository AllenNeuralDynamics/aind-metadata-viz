"""Pure graph functions: status propagation, snapshot compilation, validation.

Node documents in S3 are the source of truth; everything here derives from
them. Keeping the derivation pure (dicts in, dicts out) is what makes the
staleness rules testable without touching S3 or the runner.

The central rule is that a statement's *effective* status is never better
than the worst status anywhere in its ``depends_on`` ancestry - a claim built
on a failed foundation is a failed claim, however green its own run was.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .models import AXIS_NAMES, STATUS_SEVERITY


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string, e.g. '...T00:00:00.000000Z'.

    Always UTC, so the '+00:00' offset isoformat() would otherwise append is
    fixed and known - swapped for 'Z' rather than left in, since a few callers
    (verify_node's run stamp) turn this straight into an S3 key component and
    '+' is not a safe character there.
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _worst(*statuses: str) -> str:
    """Return the worst of *statuses* under ``STATUS_SEVERITY``."""
    return max(statuses, key=lambda s: STATUS_SEVERITY.get(s, 3))


def node_label(node: dict) -> str:
    """Return a human-readable label for *node*, falling back to its id."""
    return node.get("label") or node.get("id") or ""


def compute_effective_status(nodes_by_id: Dict[str, dict]) -> Dict[str, str]:
    """Return node id -> effective status for every node in *nodes_by_id*.

    Entities and relations have no status of their own and are reported as
    ``verified`` so they never drag a statement down. A statement's effective
    status is the worst of its own stored status and the effective statuses of
    everything it depends on. A dependency that is missing, or a cycle, counts
    as ``failed``.
    """
    effective: Dict[str, str] = {}
    visiting: Set[str] = set()

    def resolve(node_id: str) -> str:
        if node_id in effective:
            return effective[node_id]
        node = nodes_by_id.get(node_id)
        if node is None:
            return "failed"
        if node.get("kind") != "statement":
            effective[node_id] = "verified"
            return "verified"
        if node_id in visiting:
            # A depends_on cycle cannot be evaluated; refuse to call it verified.
            return "failed"

        visiting.add(node_id)
        status = node.get("status") or "proposed"
        for dep_id in node.get("depends_on") or []:
            status = _worst(status, resolve(dep_id))
        visiting.discard(node_id)

        effective[node_id] = status
        return status

    for node_id in nodes_by_id:
        resolve(node_id)
    return effective


def compute_depths(nodes_by_id: Dict[str, dict]) -> Dict[str, int]:
    """Return node id -> derivation depth.

    Entities, relations and statements with no dependencies sit at depth 0;
    every other statement sits one above the deepest thing it derives from.
    Missing dependencies and cycles contribute no depth, so the function
    always terminates.
    """
    depths: Dict[str, int] = {}
    visiting: Set[str] = set()

    def resolve(node_id: str) -> int:
        if node_id in depths:
            return depths[node_id]
        node = nodes_by_id.get(node_id)
        if node is None or node_id in visiting:
            return 0
        deps = node.get("depends_on") or []
        if not deps:
            depths[node_id] = 0
            return 0
        visiting.add(node_id)
        depth = 1 + max(resolve(dep_id) for dep_id in deps)
        visiting.discard(node_id)
        depths[node_id] = depth
        return depth

    for node_id in nodes_by_id:
        resolve(node_id)
    return depths


def axis_summary(node: dict) -> Dict[str, str]:
    """Return axis name -> axis status for a statement node."""
    record = node.get("verification") or {}
    summary = {}
    for axis in AXIS_NAMES:
        entry = record.get(axis) or {}
        summary[axis] = entry.get("status") or "not_attempted"
    return summary


def _edges_for(node: dict) -> List[dict]:
    """Return every outgoing edge of *node*."""
    node_id = node["id"]
    kind = node.get("kind")
    edges: List[dict] = []
    if kind == "statement":
        for role in ("subject", "relation", "object"):
            target = node.get(role)
            if target:
                edges.append(
                    {"id": f"{node_id}--{role}--{target}", "source": node_id, "target": target, "type": role}
                )
        for dep_id in node.get("depends_on") or []:
            edges.append(
                {"id": f"{node_id}--dep--{dep_id}", "source": node_id, "target": dep_id, "type": "depends_on"}
            )
    elif kind == "entity":
        for member_id in node.get("members") or []:
            edges.append(
                {"id": f"{node_id}--member--{member_id}", "source": node_id, "target": member_id, "type": "member"}
            )
    return edges


def compile_snapshot(nodes: Iterable[dict]) -> dict:
    """Compile node documents into the whole-graph snapshot the UI loads.

    Nodes are summarized (no code, no run history, no full value payload
    beyond what the graph view needs) and every edge is materialized, so the
    demo graph fits comfortably in one GET.
    """
    nodes_by_id = {n["id"]: n for n in nodes if n.get("id")}
    effective = compute_effective_status(nodes_by_id)
    depths = compute_depths(nodes_by_id)

    summaries: List[dict] = []
    edges: List[dict] = []
    for node_id, node in nodes_by_id.items():
        kind = node.get("kind")
        provenance = node.get("provenance") or {}
        summary = {
            "id": node_id,
            "kind": kind,
            "label": node_label(node),
            "entity_type": node.get("entity_type") if kind == "entity" else None,
            "status": node.get("status") if kind == "statement" else None,
            "effective_status": effective.get(node_id) if kind == "statement" else None,
            "axes": axis_summary(node) if kind == "statement" else {},
            "depth": depths.get(node_id, 0),
            "has_code": bool(node.get("code")),
            "updated": provenance.get("updated") or provenance.get("created"),
        }
        summaries.append(summary)
        edges.extend(_edges_for(node))

    summaries.sort(key=lambda s: (s["depth"], s["kind"], s["id"]))
    edges.sort(key=lambda e: e["id"])
    return {"generated": now_iso(), "nodes": summaries, "edges": edges}


def compile_manifest(nodes: Iterable[dict]) -> List[dict]:
    """Compile the compact id -> summary index the agent and UI search over."""
    nodes_by_id = {n["id"]: n for n in nodes if n.get("id")}
    effective = compute_effective_status(nodes_by_id)
    entries = []
    for node_id, node in nodes_by_id.items():
        provenance = node.get("provenance") or {}
        entries.append(
            {
                "id": node_id,
                "kind": node.get("kind"),
                "label": node_label(node),
                "status": effective.get(node_id) if node.get("kind") == "statement" else None,
                "updated": provenance.get("updated") or provenance.get("created"),
            }
        )
    entries.sort(key=lambda e: e["id"])
    return entries


def subgraph(snapshot: dict, root_id: str) -> dict:
    """Return the part of *snapshot* reachable from *root_id* along its edges.

    Reachability follows edges outward from the root, which for a statement
    means its triple and everything it derives from - the evidence beneath a
    claim, which is what the UI wants when it focuses one node.
    """
    adjacency: Dict[str, List[str]] = {}
    for edge in snapshot.get("edges", []):
        adjacency.setdefault(edge["source"], []).append(edge["target"])

    reachable: Set[str] = set()
    stack = [root_id]
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        stack.extend(adjacency.get(node_id, []))

    return {
        "generated": snapshot.get("generated"),
        "nodes": [n for n in snapshot.get("nodes", []) if n["id"] in reachable],
        "edges": [
            e
            for e in snapshot.get("edges", [])
            if e["source"] in reachable and e["target"] in reachable
        ],
    }


def filter_by_status(snapshot: dict, status: str) -> dict:
    """Return *snapshot* keeping only statements whose effective status is *status*.

    Entities and relations referenced by a surviving statement are kept so the
    filtered graph still renders complete triples.
    """
    kept: Set[str] = set()
    for node in snapshot.get("nodes", []):
        if node["kind"] == "statement" and node.get("effective_status") == status:
            kept.add(node["id"])

    for edge in snapshot.get("edges", []):
        if edge["source"] in kept and edge["type"] in ("subject", "relation", "object"):
            kept.add(edge["target"])

    return {
        "generated": snapshot.get("generated"),
        "nodes": [n for n in snapshot.get("nodes", []) if n["id"] in kept],
        "edges": [
            e for e in snapshot.get("edges", []) if e["source"] in kept and e["target"] in kept
        ],
    }


# --------------------------------------------------------------------------
# Write-time validation
# --------------------------------------------------------------------------


def validate_node(doc: dict, existing: Dict[str, dict]) -> Optional[str]:
    """Validate a node document against the rest of the graph.

    *existing* maps id -> node document for everything already in the graph
    (plus, when validating an agent outbox, the other documents in that
    outbox). Returns an error message, or ``None`` when the node is valid.
    """
    kind = doc.get("kind")
    if kind == "entity":
        return _validate_entity(doc, existing)
    if kind == "relation":
        return None
    if kind == "statement":
        return _validate_statement(doc, existing)
    return f"unknown node kind '{kind}'"


def _validate_entity(doc: dict, existing: Dict[str, dict]) -> Optional[str]:
    """Check that a population entity's members exist and are entities."""
    for member_id in doc.get("members") or []:
        member = existing.get(member_id)
        if member is None:
            return f"member '{member_id}' is not in the graph"
        if member.get("kind") != "entity":
            return f"member '{member_id}' is not an entity node"
    return None


def _side_error(role: str, entity_id: str, allowed: List[str], existing: Dict[str, dict]) -> Optional[str]:
    """Check one side of a triple against the relation's signature."""
    entity = existing.get(entity_id)
    if entity is None:
        return f"{role} '{entity_id}' is not in the graph"
    if entity.get("kind") != "entity":
        return f"{role} '{entity_id}' is not an entity node"
    entity_type = entity.get("entity_type")
    if allowed and entity_type not in allowed:
        return f"{role} '{entity_id}' is a {entity_type}; relation accepts {sorted(allowed)}"
    return None


def _validate_statement(doc: dict, existing: Dict[str, dict]) -> Optional[str]:
    """Check a statement's triple signature and its depends_on references."""
    relation = existing.get(doc.get("relation") or "")
    if relation is None:
        return f"relation '{doc.get('relation')}' is not in the graph"
    if relation.get("kind") != "relation":
        return f"'{doc.get('relation')}' is not a relation node"

    signature = relation.get("signature") or {}
    error = _side_error("subject", doc.get("subject") or "", signature.get("subject") or [], existing)
    if error:
        return error
    error = _side_error("object", doc.get("object") or "", signature.get("object") or [], existing)
    if error:
        return error

    for dep_id in doc.get("depends_on") or []:
        dep = existing.get(dep_id)
        if dep is None:
            return f"depends_on '{dep_id}' is not in the graph"
        if dep.get("kind") != "statement":
            return f"depends_on '{dep_id}' is not a statement node"

    if _creates_cycle(doc, existing):
        return "depends_on introduces a cycle"
    return None


def _creates_cycle(doc: dict, existing: Dict[str, dict]) -> bool:
    """Return True if *doc*'s dependencies eventually lead back to *doc*."""
    target = doc.get("id")
    if not target:
        return False
    seen: Set[str] = set()
    stack = list(doc.get("depends_on") or [])
    while stack:
        node_id = stack.pop()
        if node_id == target:
            return True
        if node_id in seen:
            continue
        seen.add(node_id)
        node = existing.get(node_id)
        if node:
            stack.extend(node.get("depends_on") or [])
    return False


def mark_descendants_stale(nodes_by_id: Dict[str, dict], changed_id: str) -> List[str]:
    """Mark every statement that derives from *changed_id* as ``stale``.

    Returns the ids that changed. Called after a node's code or run result
    moves, so claims sitting on top of it stop presenting as verified until
    they are re-run.
    """
    dependents: Dict[str, List[str]] = {}
    for node_id, node in nodes_by_id.items():
        for dep_id in node.get("depends_on") or []:
            dependents.setdefault(dep_id, []).append(node_id)

    touched: List[str] = []
    stack = list(dependents.get(changed_id, []))
    seen: Set[str] = set()
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        node = nodes_by_id[node_id]
        if node.get("status") == "verified":
            node["status"] = "stale"
            touched.append(node_id)
        stack.extend(dependents.get(node_id, []))
    return touched


def statement_sentence(doc: dict, nodes_by_id: Dict[str, dict]) -> str:
    """Render a statement as a plain-English sentence using its triple's labels."""
    if doc.get("label"):
        return doc["label"]
    parts: Tuple[str, str, str] = (
        node_label(nodes_by_id.get(doc.get("subject") or "", {})) or doc.get("subject", "?"),
        node_label(nodes_by_id.get(doc.get("relation") or "", {})) or doc.get("relation", "?"),
        node_label(nodes_by_id.get(doc.get("object") or "", {})) or doc.get("object", "?"),
    )
    return " ".join(parts)
