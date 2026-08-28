"""Pydantic models for the verification graph.

Three node kinds share one document store and one id namespace:

* ``entity`` - a noun (unit, session, brain area, stimulus, behavior,
  population), grounded in the dynamic routing data cache so it is checkable.
* ``relation`` - a verb ("responds to"), carrying the operational definition
  and a pointer to the code that implements its test.
* ``statement`` - a (subject, relation, object) triple plus its value, its
  dependencies on lower-level statements, and its verification record.

Every statement carries four independent verification axes (see
``VerificationRecord``). The contract is that the record is always explicit
about which axes hold, which failed, and which were never attempted.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------

NodeKind = Literal["entity", "relation", "statement"]

EntityType = Literal[
    "unit",
    "session",
    "brain_area",
    "stimulus",
    "behavior",
    "population",
]

AxisName = Literal["reproducible", "replicable", "robust", "generalizable"]

AXIS_NAMES: tuple = ("reproducible", "replicable", "robust", "generalizable")

AxisStatus = Literal["passed", "failed", "not_attempted", "stale"]

NodeStatus = Literal["proposed", "verified", "stale", "failed"]

#: Node statuses ordered worst-first. ``compute_effective_status`` propagates
#: the worst status found along ``depends_on`` edges, so this ordering is the
#: single definition of "worse".
STATUS_SEVERITY: Dict[str, int] = {
    "failed": 3,
    "stale": 2,
    "proposed": 1,
    "verified": 0,
}


# --------------------------------------------------------------------------
# Shared sub-documents
# --------------------------------------------------------------------------


class Grounding(BaseModel):
    """Where an entity lives in the dynamic routing data cache."""

    table: str = Field(..., description="Cache table, e.g. 'platform_swdb_units'")
    asset_name: Optional[str] = Field(
        default=None, description="Data asset partition, e.g. '660023_2023-08-08'"
    )
    selector: Dict[str, Any] = Field(
        default_factory=dict,
        description="Column/value pairs identifying the row(s), e.g. {'unit_id': 123}",
    )


class DataRef(BaseModel):
    """A pinned data asset a statement's analysis reads."""

    table: str = Field(..., description="Cache table the analysis reads")
    asset_name: Optional[str] = Field(default=None, description="Asset partition name")
    version: Optional[str] = Field(
        default=None, description="Cache version pinned for this reference"
    )


class RunRef(BaseModel):
    """Pointer to one recorded verification run."""

    code_hash: Optional[str] = Field(default=None, description="Hash of analysis.py + environment.lock")
    env: Optional[str] = Field(default=None, description="Environment lock file used")
    result_hash: Optional[str] = Field(default=None, description="Hash of the canonical result JSON")
    ran_at: Optional[str] = Field(default=None, description="ISO-8601 UTC timestamp of the run")
    log: Optional[str] = Field(default=None, description="S3 prefix holding the run log and result")
    passed: Optional[bool] = Field(default=None, description="Whether this run satisfied the axis")


class AxisRecord(BaseModel):
    """Status of one verification axis, plus what was done to reach it."""

    status: AxisStatus = Field(default="not_attempted", description="Axis outcome")
    method: Optional[str] = Field(
        default=None, description="How the axis was tested, e.g. '5-fold cross-validation over trials'"
    )
    code: Optional[str] = Field(
        default=None, description="Alternate code directory used (robust/generalizable axes)"
    )
    note: Optional[str] = Field(default=None, description="Free-text detail, e.g. why an axis failed")
    run: Optional[RunRef] = Field(default=None, description="Most recent run for this axis")
    runs: List[RunRef] = Field(default_factory=list, description="Earlier runs, newest last")


class VerificationRecord(BaseModel):
    """The four independent verification axes of a statement.

    * ``reproducible`` - same data, same code.
    * ``replicable`` - different data, same code.
    * ``robust`` - same data, different code.
    * ``generalizable`` - different data and different code.
    """

    reproducible: AxisRecord = Field(default_factory=AxisRecord)
    replicable: AxisRecord = Field(default_factory=AxisRecord)
    robust: AxisRecord = Field(default_factory=AxisRecord)
    generalizable: AxisRecord = Field(default_factory=AxisRecord)


class ProvenanceEvent(BaseModel):
    """One entry in a node's change history."""

    at: str = Field(..., description="ISO-8601 UTC timestamp")
    author: str = Field(..., description="ORCID iD, or '<orcid> via agent job <id>'")
    action: str = Field(..., description="What happened, e.g. 'created', 'verified', 'approved'")
    detail: Optional[str] = Field(default=None, description="Optional free-text detail")


class Provenance(BaseModel):
    """Who created a node and everything that has happened to it since."""

    author: str = Field(..., description="Original author: ORCID iD or agent job id")
    created: str = Field(..., description="ISO-8601 UTC creation timestamp")
    updated: Optional[str] = Field(default=None, description="ISO-8601 UTC timestamp of the last write")
    history: List[ProvenanceEvent] = Field(default_factory=list, description="Change history, oldest first")


class RelationSignature(BaseModel):
    """Entity types a relation accepts on each side of the triple."""

    subject: List[EntityType] = Field(..., description="Entity types allowed as the subject")
    object: List[EntityType] = Field(..., description="Entity types allowed as the object")


# --------------------------------------------------------------------------
# Node documents
# --------------------------------------------------------------------------


class EntityNode(BaseModel):
    """A noun in the graph, grounded in the data cache."""

    id: str = Field(..., description="Stable node id, e.g. 'ent-unit-660023_2023-08-08-123'")
    kind: Literal["entity"] = "entity"
    entity_type: EntityType = Field(..., description="What kind of thing this is")
    label: str = Field(..., description="Human-readable label")
    grounding: Optional[Grounding] = Field(
        default=None, description="Where this entity lives in the data cache"
    )
    members: List[str] = Field(
        default_factory=list,
        description="For 'population' entities: the entity ids that make up the set",
    )
    provenance: Optional[Provenance] = Field(default=None, description="Authorship and change history")


class RelationNode(BaseModel):
    """A verb in the graph, with an operational definition and its test code."""

    id: str = Field(..., description="Stable node id, e.g. 'rel-responds-to'")
    kind: Literal["relation"] = "relation"
    label: str = Field(..., description="Human-readable verb phrase, e.g. 'responds to'")
    definition: str = Field(..., description="Operational definition: exactly what the test means")
    code: Optional[str] = Field(default=None, description="Code sidecar prefix, e.g. 'code/rel-responds-to/'")
    signature: RelationSignature = Field(..., description="Entity types allowed on each side")
    provenance: Optional[Provenance] = Field(default=None, description="Authorship and change history")


class StatementNode(BaseModel):
    """A (subject, relation, object) triple plus evidence and dependencies."""

    id: str = Field(..., description="Stable node id, e.g. 'stmt-01J...'")
    kind: Literal["statement"] = "statement"
    label: Optional[str] = Field(default=None, description="Plain-English rendering of the claim")
    subject: str = Field(..., description="Entity node id on the subject side")
    relation: str = Field(..., description="Relation node id")
    object: str = Field(..., description="Entity node id on the object side")
    value: Dict[str, Any] = Field(
        default_factory=dict, description="The measured result, e.g. {'p': 0.0004, 'effect': '+3.1 Hz'}"
    )
    depends_on: List[str] = Field(
        default_factory=list, description="Lower-level statement ids this claim is built on"
    )
    code: Optional[str] = Field(default=None, description="Code sidecar prefix for this statement's analysis")
    data: List[DataRef] = Field(default_factory=list, description="Pinned data assets the analysis reads")
    verification: VerificationRecord = Field(
        default_factory=VerificationRecord, description="The four verification axes"
    )
    status: NodeStatus = Field(default="proposed", description="Stored status, before dependency propagation")
    provenance: Optional[Provenance] = Field(default=None, description="Authorship and change history")


AnyNode = Annotated[
    Union[EntityNode, RelationNode, StatementNode],
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------
# Create bodies (server owns id, status, verification, provenance)
# --------------------------------------------------------------------------


class EntityCreate(BaseModel):
    """Request body for creating an entity node."""

    kind: Literal["entity"] = "entity"
    id: Optional[str] = Field(default=None, description="Optional explicit id; generated when omitted")
    entity_type: EntityType = Field(..., description="What kind of thing this is")
    label: str = Field(..., description="Human-readable label")
    grounding: Optional[Grounding] = Field(default=None, description="Where this entity lives in the cache")
    members: List[str] = Field(default_factory=list, description="Member entity ids for populations")


class RelationCreate(BaseModel):
    """Request body for creating a relation node."""

    kind: Literal["relation"] = "relation"
    id: Optional[str] = Field(default=None, description="Optional explicit id; generated when omitted")
    label: str = Field(..., description="Human-readable verb phrase")
    definition: str = Field(..., description="Operational definition of the test")
    code: Optional[str] = Field(default=None, description="Code sidecar prefix")
    signature: RelationSignature = Field(..., description="Entity types allowed on each side")


class StatementCreate(BaseModel):
    """Request body for creating a statement node."""

    kind: Literal["statement"] = "statement"
    id: Optional[str] = Field(default=None, description="Optional explicit id; generated when omitted")
    label: Optional[str] = Field(default=None, description="Plain-English rendering of the claim")
    subject: str = Field(..., description="Entity node id on the subject side")
    relation: str = Field(..., description="Relation node id")
    object: str = Field(..., description="Entity node id on the object side")
    value: Dict[str, Any] = Field(default_factory=dict, description="The measured result")
    depends_on: List[str] = Field(default_factory=list, description="Lower-level statement ids")
    code: Optional[str] = Field(default=None, description="Code sidecar prefix")
    data: List[DataRef] = Field(default_factory=list, description="Pinned data assets")
    verification: Optional[VerificationRecord] = Field(
        default=None,
        description="Axes the author claims their code supports; runs still have to confirm them",
    )


AnyNodeCreate = Annotated[
    Union[EntityCreate, RelationCreate, StatementCreate],
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------
# Compiled snapshot (what the UI loads in one GET)
# --------------------------------------------------------------------------


class GraphNodeSummary(BaseModel):
    """One node as it appears in the compiled whole-graph snapshot."""

    id: str = Field(..., description="Node id")
    kind: NodeKind = Field(..., description="entity | relation | statement")
    label: str = Field(..., description="Human-readable label")
    entity_type: Optional[EntityType] = Field(default=None, description="Set for entity nodes only")
    status: Optional[NodeStatus] = Field(default=None, description="Stored status of a statement")
    effective_status: Optional[NodeStatus] = Field(
        default=None, description="Status after propagating the worst status along depends_on"
    )
    axes: Dict[str, str] = Field(
        default_factory=dict, description="Axis name -> axis status, for statement nodes"
    )
    depth: int = Field(default=0, description="Derivation depth: 0 for foundations, 1 + max(dep depth) above")
    has_code: bool = Field(default=False, description="Whether the node has a code sidecar")
    updated: Optional[str] = Field(default=None, description="ISO-8601 UTC timestamp of the last write")


class GraphEdge(BaseModel):
    """One edge in the compiled snapshot."""

    id: str = Field(..., description="Stable edge id")
    source: str = Field(..., description="Source node id")
    target: str = Field(..., description="Target node id")
    type: Literal["subject", "relation", "object", "depends_on", "member"] = Field(
        ..., description="Structural role of the edge"
    )


class GraphSnapshot(BaseModel):
    """The compiled whole-graph snapshot served to the UI."""

    generated: str = Field(..., description="ISO-8601 UTC timestamp the snapshot was compiled")
    nodes: List[GraphNodeSummary] = Field(default_factory=list, description="Every node, summarized")
    edges: List[GraphEdge] = Field(default_factory=list, description="Every edge")


class ManifestEntry(BaseModel):
    """One row of the id -> summary index the agent reads."""

    id: str = Field(..., description="Node id")
    kind: NodeKind = Field(..., description="entity | relation | statement")
    label: str = Field(..., description="Human-readable label")
    status: Optional[NodeStatus] = Field(default=None, description="Effective status")
    updated: Optional[str] = Field(default=None, description="ISO-8601 UTC timestamp of the last write")


# --------------------------------------------------------------------------
# Verification / agent request + response bodies
# --------------------------------------------------------------------------


class VerifyRequest(BaseModel):
    """Request body for ``POST /verification/nodes/{id}/verify``."""

    axis: AxisName = Field(default="reproducible", description="Which verification axis to run")


class JobStatus(BaseModel):
    """Status of a queued runner or agent job."""

    job_id: str = Field(..., description="Job identifier")
    kind: Literal["verify"] = Field(..., description="What sort of job this is")
    state: Literal["queued", "running", "done", "failed"] = Field(..., description="Lifecycle state")
    node_id: Optional[str] = Field(default=None, description="Node the job targets, for verify jobs")
    axis: Optional[AxisName] = Field(default=None, description="Axis the job runs, for verify jobs")
    created: str = Field(..., description="ISO-8601 UTC timestamp the job was queued")
    finished: Optional[str] = Field(default=None, description="ISO-8601 UTC timestamp the job ended")
    error: Optional[str] = Field(default=None, description="Failure message, when state is 'failed'")
    result: Optional[Dict[str, Any]] = Field(default=None, description="Job outcome payload")


class VerifyBatchRequest(BaseModel):
    """Request body for ``POST /verification/verify-batch``.

    Either name the nodes explicitly, or omit ``node_ids`` to target every
    node in the graph that has a code sidecar (optionally narrowed further by
    ``status``, e.g. ``"proposed"`` to skip anything already verified).
    """

    node_ids: Optional[List[str]] = Field(
        default=None, description="Node ids to verify; omit to target every eligible node"
    )
    axis: AxisName = Field(default="reproducible", description="Which verification axis to run")
    status: Optional[str] = Field(
        default=None, description="When node_ids is omitted, restrict to nodes at this status"
    )


class SkippedNode(BaseModel):
    """One node a batch verify request declined to queue."""

    node_id: str = Field(..., description="The node that was skipped")
    reason: str = Field(..., description="Why it was skipped, e.g. 'no code sidecar' or 'already queued'")


class VerifyBatchResult(BaseModel):
    """Response body for ``POST /verification/verify-batch``."""

    queued: List[JobStatus] = Field(..., description="Jobs newly queued by this request")
    skipped: List[SkippedNode] = Field(..., description="Eligible-looking nodes that were not queued, and why")


class CodeFile(BaseModel):
    """One file in a node's code sidecar."""

    path: str = Field(..., description="Path relative to the node's code directory")
    size: int = Field(..., description="Size in bytes")


class CodeListing(BaseModel):
    """Listing of a node's code sidecar."""

    node_id: str = Field(..., description="Node the code belongs to")
    files: List[CodeFile] = Field(default_factory=list, description="Files present, sorted by path")
    code_hash: Optional[str] = Field(default=None, description="Hash of analysis.py + environment.lock")
    gates: Dict[str, Any] = Field(
        default_factory=dict, description="Layout gate results (see runner.check_code_layout)"
    )
