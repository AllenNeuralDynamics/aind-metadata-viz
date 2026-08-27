"""The authoring agent: a sandboxed Claude Agent SDK session writing to an outbox.

Users build new nodes by asking for a claim from the graph page. The agent is
the `Claude Agent SDK <https://code.claude.com/docs/en/agent-sdk>`_ - Claude
Code as a library, with its own agent loop, built-in tools and permission
system - deliberately *not* the in-process Bedrock Converse loop in
``chat/agent.py``, which stays untouched.

The session runs in a worker process (``agent_worker.py``) launched through
``sandbox.run_sandboxed`` rather than in the portal process. That is not
incidental: the SDK merges its ``env`` option over ``os.environ`` instead of
replacing it, so an in-process session would inherit the portal's whole
environment - including the ECS task-role URI and the session secret. Behind
the sandbox the environment is rebuilt from an allowlist.

Three properties make this safe to expose:

**The sandbox.** The worker runs under ``sandbox.py``'s limits with a scrubbed
environment. Its only credentials are short-lived Bedrock keys this module
mints (see ``_bedrock_env``); it gets no write credentials to
``aind-scratch-data``, no portal session secret, and no path to the task role.
Killing a job mid-run leaves the graph unchanged, because the job never
touches the graph.

**The tool policy.** ``agent_worker`` gives the session a fixed tool surface
with ``permission_mode="dontAsk"``, no network-reaching tools, and a
``PreToolUse`` hook that refuses writes outside the job directory.

**The outbox contract.** The agent writes finished node documents and code
sidecars into ``outbox/`` in its job directory. When the job exits, the server
validates everything through the same path as ``POST /verification/nodes`` -
Pydantic models, triple signature checks, code layout gates - and inserts what
passes as ``proposed`` nodes. That keeps prompt injection and agent error
inside a validation boundary instead of trusting the agent's writes.

The model is ``AGENT_MODEL`` (Claude Sonnet 5 on Bedrock by default). This is
the same model family ``chat/agent.py`` already calls through the
``bedrock-access`` role, so the only IAM change needed is
``bedrock:InvokeModel`` on this inference profile in addition to whatever
profiles the role already allows.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
from typing import Dict, List, Optional, Tuple

import boto3

from .graph import now_iso, validate_node
from .sandbox import (
    DEFAULT_TIMEOUT_SECONDS,
    grant_to_sandbox_user,
    kill_group,
    run_sandboxed,
    sandbox_env,
)
from .skills import SKILLS
from .store import InvalidId, safe_code_path, safe_id

logger = logging.getLogger(__name__)

#: Worker script run in the sandbox; it drives the Claude Agent SDK session.
#: The SDK bundles the Claude Code CLI inside its wheel, so there is no binary
#: to install and nothing to find on PATH.
#:
#: Run by *path*, not with ``python -m``. ``-m`` imports the parent package
#: first, and ``verification/__init__`` pulls in the whole portal app - the
#: chat router, the MCP server, fastmcp - none of which the worker needs, and
#: some of which cannot even be imported inside the sandbox (fastmcp probes for
#: a ``.env`` file at import time and raises on a directory it cannot read).
AGENT_WORKER_PATH = os.environ.get(
    "VGRAPH_AGENT_WORKER", os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_worker.py")
)

#: Model the session runs on, as a Bedrock model id.
#:
#: It has to be a cross-Region inference profile: Claude Sonnet 5 has no
#: in-Region inference on ``bedrock-runtime`` in any region, so a plain
#: ``anthropic.claude-sonnet-5`` will not resolve. ``global.`` routes
#: worldwide; ``us.`` is the data-residency-constrained alternative, keeping
#: requests inside US and Canada regions (``eu.`` and ``au.`` also exist).
AGENT_MODEL = os.environ.get("VGRAPH_AGENT_MODEL", "global.anthropic.claude-sonnet-5")

AGENT_ROOT = os.environ.get("VGRAPH_AGENT_ROOT", "/tmp/vgraph-agent")

AGENT_TIMEOUT_SECONDS = int(os.environ.get("VGRAPH_AGENT_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))

MAX_REQUEST_BYTES = 4096

MAX_OUTBOX_NODES = int(os.environ.get("VGRAPH_MAX_OUTBOX_NODES", "200"))

#: Ceiling on one node's code sidecar, so a job cannot exhaust memory by
#: writing an enormous tree into its outbox.
MAX_OUTBOX_CODE_BYTES = int(os.environ.get("VGRAPH_MAX_OUTBOX_CODE_BYTES", str(8 * 1024 * 1024)))

TRANSCRIPT_TAIL_BYTES = 20_000

#: Where the portal drops live instructions for a running session, and where
#: it asks one to stop. The worker drains the steer file between turns.
CONTROL_DIRNAME = "control"
STEER_FILENAME = "steer.jsonl"
STOP_FILENAME = "stop"

MAX_STEER_BYTES = 4096

#: Sessions currently running, by job id, so the cancel and steer endpoints can
#: reach one mid-flight. The queue runs jobs one at a time, so this holds at
#: most a single entry, but keying it means a stale request cannot cancel an
#: unrelated job that started since.
ACTIVE_JOBS: "Dict[str, AgentJob]" = {}


PROMPT_TEMPLATE = """You are authoring nodes for a verification graph.

Read the skills in `.claude/skills/` first - `graph-schema`,
`dynamic-routing-data`, `node-authoring` and `recursive-verification`. They
are the contract, not background reading.

The current graph is exported to `manifest.json` in this directory. Search it
for nodes that already cover part of the request and reuse them rather than
re-authoring them.

Write everything you produce into `outbox/` - node documents to
`outbox/nodes/<node-id>.json`, code sidecars to `outbox/code/<node-id>/`. You
have no access to the graph's storage; the outbox is the only way anything you
write reaches the graph, and every document is validated before it is
accepted.

The request:

{request}
"""


class AgentJob:
    """One agent job's directory and lifecycle."""

    def __init__(self, job_id: str, request: str, manifest: List[dict], root: Optional[str] = None):
        """Create the job directory, skills, manifest export and outbox."""
        base = root or AGENT_ROOT
        os.makedirs(base, exist_ok=True)
        self.job_id = job_id
        self.request = request
        self.dir = tempfile.mkdtemp(prefix=f"{job_id}-", dir=base)
        self.transcript_path = os.path.join(self.dir, "transcript.txt")
        self._process = None
        self.cancelled = False
        self._write_scaffold(manifest)

    def _write_scaffold(self, manifest: List[dict]) -> None:
        """Write the skills, the read-only manifest export, and the empty outbox."""
        for name, body in SKILLS.items():
            skill_dir = os.path.join(self.dir, ".claude", "skills", name)
            os.makedirs(skill_dir, exist_ok=True)
            with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write(body)

        with open(os.path.join(self.dir, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)

        with open(os.path.join(self.dir, "request.md"), "w", encoding="utf-8") as handle:
            handle.write(self.request)

        # The worker runs in another process, so the prompt is handed over on
        # disk rather than on the command line - it is too long for argv and
        # would otherwise show up in the process table.
        with open(os.path.join(self.dir, "prompt.txt"), "w", encoding="utf-8") as handle:
            handle.write(self.prompt())

        os.makedirs(os.path.join(self.dir, "outbox", "nodes"), exist_ok=True)
        os.makedirs(os.path.join(self.dir, "outbox", "code"), exist_ok=True)
        os.makedirs(os.path.join(self.dir, CONTROL_DIRNAME), exist_ok=True)

        # Created by the portal (root in the container); run by `vgraph`.
        grant_to_sandbox_user(self.dir)

    def prompt(self) -> str:
        """Return the prompt handed to the agent."""
        return PROMPT_TEMPLATE.format(request=self.request)

    def command(self) -> List[str]:
        """Return the full argv for this job's worker process."""
        return [sys.executable, AGENT_WORKER_PATH, self.dir]

    @property
    def control_dir(self) -> str:
        """Directory holding this job's steer and stop files."""
        return os.path.join(self.dir, CONTROL_DIRNAME)

    def steer(self, message: str) -> None:
        """Queue a live instruction the session picks up at its next turn."""
        text = (message or "").strip()
        if not text:
            raise ValueError("steering message is empty")
        if len(text.encode("utf-8")) > MAX_STEER_BYTES:
            raise ValueError(f"steering message exceeds {MAX_STEER_BYTES} bytes")
        path = os.path.join(self.control_dir, STEER_FILENAME)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"message": text}) + "\n")
        grant_to_sandbox_user(self.control_dir)

    def cancel(self) -> bool:
        """Stop the session now. Returns True if a live process was signalled.

        The stop file is written first so a worker between turns exits cleanly,
        then the process group is killed so one mid-turn stops anyway. Either
        way the outbox is still on disk and is still harvested and validated -
        cancelling loses the session, not the work it already finished.
        """
        self.cancelled = True
        try:
            with open(os.path.join(self.control_dir, STOP_FILENAME), "w", encoding="utf-8") as handle:
                handle.write("stop\n")
        except OSError:  # pragma: no cover - the job directory is ours
            pass
        process = self._process
        if process is None or process.poll() is not None:
            return False
        kill_group(process)
        return True

    def run(self, timeout: int = AGENT_TIMEOUT_SECONDS) -> dict:
        """Run the session to completion and return its sandbox result as a dict."""
        env = sandbox_env(_bedrock_env())
        env["VGRAPH_AGENT_MODEL"] = AGENT_MODEL
        # The SDK and the CLI it bundles both read config from ``$HOME``. Point
        # HOME at the job directory so each job gets a private, writable config
        # root instead of sharing one under /tmp, and so nothing written there
        # outlives the job.
        env["HOME"] = self.dir
        result = run_sandboxed(
            self.command(),
            cwd=self.dir,
            env=env,
            timeout=timeout,
            on_start=self._register_process,
        )
        # The worker streams the session transcript to disk as it goes; the
        # sandbox output is the worker's own stdout/stderr, which matters when
        # the session never got far enough to write a transcript.
        if not os.path.exists(self.transcript_path):
            with open(self.transcript_path, "w", encoding="utf-8") as handle:
                handle.write(result.output)
        return result.to_dict()

    def _register_process(self, process) -> None:
        """Record the live worker process so ``cancel`` can reach it."""
        self._process = process
        if self.cancelled:
            # Cancelled between queueing and spawning; do not let it run on.
            kill_group(process)

    def transcript(self) -> str:
        """Return the tail of the agent's transcript, for progress polling."""
        return read_transcript(self.transcript_path)

    def cleanup(self) -> None:
        """Remove the job directory."""
        shutil.rmtree(self.dir, ignore_errors=True)


def _bedrock_env() -> Dict[str, str]:
    """Return the only credentials the session is entitled to: Bedrock, short-lived.

    The portal holds an ECS task role that can reach far more than Bedrock, so
    the worker is never given a path to it. Instead this assumes
    ``BEDROCK_ROLE_ARN`` *here*, in the parent, exactly as ``chat/agent.py``
    does, and passes the resulting temporary keys down. The worker therefore
    holds credentials scoped to the Bedrock role and expiring on their own.

    Passing the profile down instead would not work anyway: the profile's
    ``credential_source = EcsContainer`` needs
    ``AWS_CONTAINER_CREDENTIALS_RELATIVE_URI``, which the sandbox strips - and
    un-stripping it would hand the worker the task role itself.
    """
    env = {
        "AWS_REGION": os.environ.get("AWS_REGION", "us-west-2"),
        "CLAUDE_CODE_USE_BEDROCK": "1",
    }
    role_arn = os.environ.get("BEDROCK_ROLE_ARN")
    if not role_arn:
        return env

    assumed = boto3.client("sts").assume_role(
        RoleArn=role_arn,
        RoleSessionName="verification-graph-agent",
        DurationSeconds=int(os.environ.get("VGRAPH_AGENT_CREDENTIAL_TTL", "3600")),
    )
    credentials = assumed["Credentials"]
    env["AWS_ACCESS_KEY_ID"] = credentials["AccessKeyId"]
    env["AWS_SECRET_ACCESS_KEY"] = credentials["SecretAccessKey"]
    env["AWS_SESSION_TOKEN"] = credentials["SessionToken"]
    return env


def read_transcript(path: str, tail_bytes: int = TRANSCRIPT_TAIL_BYTES) -> str:
    """Return the last *tail_bytes* of the transcript at *path*, or an empty string."""
    try:
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            if size > tail_bytes:
                handle.seek(size - tail_bytes)
            return handle.read()
    except OSError:
        return ""


# --------------------------------------------------------------------------
# The outbox
# --------------------------------------------------------------------------


def read_outbox(job_dir: str) -> Tuple[List[dict], Dict[str, Dict[str, bytes]], List[dict]]:
    """Read a job's outbox.

    Returns ``(documents, code_by_node_id, rejected)``. Files that are not
    parseable JSON are rejected here rather than raising, so one bad document
    cannot discard a whole job's work.
    """
    documents: List[dict] = []
    rejected: List[dict] = []
    nodes_dir = os.path.join(job_dir, "outbox", "nodes")

    for name in sorted(os.listdir(nodes_dir)) if os.path.isdir(nodes_dir) else []:
        if not name.endswith(".json"):
            continue
        path = os.path.join(nodes_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                documents.append(json.load(handle))
        except (OSError, ValueError) as exc:
            rejected.append({"file": name, "reason": f"unreadable node document: {exc}"})

    if len(documents) > MAX_OUTBOX_NODES:
        rejected.append(
            {"file": "outbox", "reason": f"outbox holds {len(documents)} nodes; limit is {MAX_OUTBOX_NODES}"}
        )
        documents = documents[:MAX_OUTBOX_NODES]

    # Ids are checked *before* any code directory is opened. A node id becomes
    # a path component below, so an id like "../.." would otherwise send the
    # walk outside the job tree - and the later `safe_id` call at write time
    # would be far too late, the files having already been read.
    documents = _with_safe_ids(documents, rejected)

    code = {doc["id"]: _read_code_dir(job_dir, doc["id"]) for doc in documents if doc.get("id")}
    return documents, code, rejected


def _with_safe_ids(documents: List[dict], rejected: List[dict]) -> List[dict]:
    """Drop documents whose id is not safe to use as a path component.

    Documents with no id at all are kept: ``validate_outbox`` rejects those
    with a clearer reason, and a missing id is never used as a path.
    """
    kept: List[dict] = []
    for doc in documents:
        node_id = doc.get("id")
        if node_id is None:
            kept.append(doc)
            continue
        try:
            safe_id(str(node_id))
        except InvalidId as exc:
            rejected.append({"file": str(node_id)[:80], "reason": f"unsafe node id: {exc}"})
            continue
        kept.append(doc)
    return kept


def _read_code_dir(job_dir: str, node_id: str) -> Dict[str, bytes]:
    """Return one node's code sidecar from the outbox as ``{relpath: bytes}``.

    Hardened against a job that plants symlinks in its own outbox: the root is
    resolved and confirmed to sit inside the job directory, symlinked entries
    are skipped rather than followed, and the total is capped.
    """
    job_root = os.path.realpath(job_dir)
    root = os.path.realpath(os.path.join(job_dir, "outbox", "code", node_id))
    files: Dict[str, bytes] = {}
    if not root.startswith(job_root + os.sep) or not os.path.isdir(root):
        return files

    budget = MAX_OUTBOX_CODE_BYTES
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for filename in filenames:
            full = os.path.join(dirpath, filename)
            # A symlink here could point at any file the sandbox user can read,
            # which would copy it into the graph's code sidecars.
            if os.path.islink(full):
                continue
            relpath = os.path.relpath(full, root)
            try:
                safe_code_path(relpath)
            except InvalidId:
                continue
            try:
                with open(full, "rb") as handle:
                    data = handle.read(budget + 1)
            except OSError:  # pragma: no cover - unreadable file in our own tmpdir
                continue
            if len(data) > budget:
                return files
            budget -= len(data)
            files[relpath] = data
    return files


def validate_outbox(documents: List[dict], existing: Dict[str, dict]) -> Tuple[List[dict], List[dict]]:
    """Validate outbox documents against the graph plus each other.

    Documents are validated in dependency order, so a statement may reference
    another document from the same outbox. Returns ``(accepted, rejected)``.
    """
    pending = {doc["id"]: doc for doc in documents if doc.get("id")}
    rejected = [
        {"file": "<no id>", "reason": "node document has no id"}
        for doc in documents
        if not doc.get("id")
    ]

    known = dict(existing)
    accepted: List[dict] = []

    # Repeatedly accept whatever validates against what is known so far. A
    # document that never validates is reported with its last failure reason.
    last_error: Dict[str, str] = {}
    progress = True
    while pending and progress:
        progress = False
        for node_id in list(pending):
            doc = pending[node_id]
            error = validate_node(doc, {**known, node_id: doc})
            if error is None:
                accepted.append(doc)
                known[node_id] = doc
                del pending[node_id]
                progress = True
            else:
                last_error[node_id] = error

    for node_id, doc in pending.items():
        rejected.append({"file": f"{node_id}.json", "reason": last_error.get(node_id, "did not validate")})

    return accepted, rejected


def attribute(doc: dict, orcid: str, job_id: str) -> dict:
    """Stamp an accepted outbox document as agent-authored and ``proposed``.

    The server owns status and provenance; whatever the agent wrote for them
    is discarded here, which is what keeps an agent from declaring its own
    work verified.
    """
    author = f"{orcid} via agent job {job_id}"
    doc["status"] = "proposed" if doc.get("kind") == "statement" else doc.get("status")
    if doc.get("kind") != "statement":
        doc.pop("status", None)
    doc["provenance"] = {
        "author": author,
        "created": now_iso(),
        "updated": now_iso(),
        "history": [{"at": now_iso(), "author": author, "action": "created", "detail": "agent outbox"}],
    }
    return doc
