"""Executes node code server-side and records what happened.

This is the machinery behind ``POST /verification/nodes/{id}/verify``. It is
the same sandbox the agent uses (see ``sandbox.py``), minus the LLM.

A run is five steps:

1. Materialize a job directory with the node's code sidecar and a ``data/``
   directory holding the node's declared data assets (dynamic routing parquet
   from the public ``allen-data-views`` bucket, fetched over plain HTTPS).
2. Build a virtualenv from ``environment.lock``, cached by lock-file hash so
   repeat runs are fast.
3. Run ``pytest --cov --cov-fail-under=100``, then the known cases, then
   ``analysis.py``'s ``main(data_dir)`` - each as a sandboxed subprocess with
   a CPU/memory/time budget and no AWS credentials in its environment.
4. Compare the result against what the node claims: ``result_hash`` equality
   for the reproducible axis, the statement's own claim for the others.
5. Return a run record the caller writes to ``runs/`` and folds into the
   node's verification record.

The code gates of the plan's section 3 are enforced here in ``check_code_layout``
and ``run_gates``: a node whose tests are red, whose coverage is under 100%,
or which has no passing known case cannot leave ``proposed`` status.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

from .graph import now_iso
from .sandbox import (
    DEFAULT_TIMEOUT_SECONDS,
    SandboxResult,
    grant_to_sandbox_user,
    run_sandboxed,
    sandbox_env,
)

#: Public bucket holding the dynamic routing parquet cache.
DATA_CACHE_BASE = os.environ.get(
    "VGRAPH_DATA_CACHE_BASE",
    "https://allen-data-views.s3.us-west-2.amazonaws.com/data-asset-cache",
)

#: Where job directories are materialized.
JOB_ROOT = os.environ.get("VGRAPH_JOB_ROOT", "/tmp/vgraph-jobs")

#: Where virtualenvs are cached, keyed by environment.lock hash.
VENV_ROOT = os.environ.get("VGRAPH_VENV_ROOT", "/tmp/vgraph-venvs")

#: Files every code sidecar must contain (plan section 3).
REQUIRED_CODE_FILES = (
    "analysis.py",
    "test_analysis.py",
    "known_cases.json",
    "environment.lock",
)

MAX_DOWNLOAD_BYTES = int(os.environ.get("VGRAPH_MAX_DOWNLOAD_BYTES", str(512 * 1024**2)))


class RunnerError(RuntimeError):
    """Raised when a run cannot be set up (bad layout, unreachable data)."""


# --------------------------------------------------------------------------
# Hashing
# --------------------------------------------------------------------------


def canonical_json(value) -> str:
    """Serialize *value* canonically, so equal results hash equally."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def result_hash(result) -> str:
    """Return the SHA-256 of a result's canonical JSON serialization."""
    return hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()


def code_hash(files: Dict[str, bytes]) -> str:
    """Return the SHA-256 covering ``analysis.py`` plus ``environment.lock``.

    Any change to either resets the node's reproducibility status to stale,
    which is exactly the set of things that can change a result.
    """
    digest = hashlib.sha256()
    for name in ("analysis.py", "environment.lock"):
        digest.update(name.encode())
        digest.update(b"\x00")
        digest.update(files.get(name, b""))
        digest.update(b"\x00")
    return digest.hexdigest()


# --------------------------------------------------------------------------
# Code gates
# --------------------------------------------------------------------------


def check_code_layout(files: Dict[str, bytes]) -> dict:
    """Check a code sidecar against the fixed layout of plan section 3.

    Returns ``{"ok": bool, "missing": [...], "known_cases": int, "errors": [...]}``.
    A sidecar is only well-formed when every required file is present and
    ``known_cases.json`` holds at least one case - the guard against code that
    runs but tests the wrong thing.
    """
    missing = [name for name in REQUIRED_CODE_FILES if name not in files]
    errors: List[str] = []
    known_cases = 0

    if "known_cases.json" in files:
        try:
            cases = json.loads(files["known_cases.json"].decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            errors.append(f"known_cases.json is not valid JSON: {exc}")
        else:
            if not isinstance(cases, list):
                errors.append("known_cases.json must be a list of cases")
            else:
                known_cases = len(cases)
                if known_cases == 0:
                    errors.append("known_cases.json must contain at least one case")

    if "environment.lock" in files and not files["environment.lock"].strip():
        errors.append("environment.lock is empty; the environment must be pinned")

    return {
        "ok": not missing and not errors,
        "missing": missing,
        "known_cases": known_cases,
        "errors": errors,
    }


# --------------------------------------------------------------------------
# Job directory
# --------------------------------------------------------------------------


def materialize_job(node_id: str, files: Dict[str, bytes], root: Optional[str] = None) -> str:
    """Write a code sidecar into a fresh job directory and return its path."""
    base = root or JOB_ROOT
    os.makedirs(base, exist_ok=True)
    job_dir = tempfile.mkdtemp(prefix=f"{node_id}-", dir=base)
    code_dir = os.path.join(job_dir, "code")
    os.makedirs(code_dir, exist_ok=True)
    for relpath, data in files.items():
        target = os.path.join(code_dir, relpath)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
    os.makedirs(os.path.join(job_dir, "data"), exist_ok=True)
    # Written by the portal (root in the container); run by `vgraph`.
    grant_to_sandbox_user(job_dir)
    return job_dir


def data_url(ref: dict, version: str) -> str:
    """Return the HTTPS URL of one declared data reference."""
    table = ref["table"]
    asset_name = ref.get("asset_name")
    base = f"{DATA_CACHE_BASE}/{ref.get('version') or version}"
    if asset_name:
        return f"{base}/{table}/asset_name={asset_name}/data.pqt"
    return f"{base}/{table}.pqt"


def resolve_cache_version(opener=urllib.request.urlopen) -> str:
    """Return the newest cache version folder name, e.g. ``bdc-v0.40``."""
    url = f"{DATA_CACHE_BASE}/cache_versions.json"
    try:
        with opener(url, timeout=30) as response:
            versions = json.loads(response.read().decode())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RunnerError(f"could not resolve the cache version from {url}: {exc}") from exc
    if not isinstance(versions, list) or not versions:
        raise RunnerError("cache_versions.json must be a non-empty list")

    def sort_key(name: str):
        """Sort ``bdc-v0.40`` style names numerically, not lexically."""
        bare = str(name).split("-v")[-1]
        return [int(part) if part.isdigit() else 0 for part in bare.split(".")]

    return sorted((str(v) for v in versions), key=sort_key)[-1]


def download_data(refs: List[dict], dest: str, version: str, opener=urllib.request.urlopen) -> List[dict]:
    """Download every declared data reference into *dest*.

    Returns one manifest entry per reference so the run record names exactly
    which bytes the analysis saw. Files land at
    ``<dest>/<table>/asset_name=<name>/data.pqt``, mirroring the cache layout,
    so ``analysis.py`` reads the same relative paths locally as in S3.
    """
    manifest = []
    for ref in refs:
        url = data_url(ref, version)
        relative = url.split(f"/{version}/", 1)[-1]
        target = os.path.join(dest, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            with opener(url, timeout=120) as response:
                payload = response.read(MAX_DOWNLOAD_BYTES + 1)
        except (urllib.error.URLError, OSError) as exc:
            raise RunnerError(f"could not fetch {url}: {exc}") from exc
        if len(payload) > MAX_DOWNLOAD_BYTES:
            raise RunnerError(f"{url} exceeds the {MAX_DOWNLOAD_BYTES} byte download limit")
        with open(target, "wb") as handle:
            handle.write(payload)
        manifest.append(
            {
                "table": ref["table"],
                "asset_name": ref.get("asset_name"),
                "version": ref.get("version") or version,
                "path": relative,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return manifest


# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------


def ensure_venv(lock_text: str, root: Optional[str] = None) -> Tuple[str, SandboxResult]:
    """Build (or reuse) a virtualenv pinned by *lock_text*; return its python path.

    Venvs are cached by lock-file hash, so the second node using the same
    pinned environment starts instantly.
    """
    base = root or VENV_ROOT
    os.makedirs(base, exist_ok=True)
    digest = hashlib.sha256(lock_text.encode("utf-8")).hexdigest()[:16]
    venv_dir = os.path.join(base, digest)
    python = os.path.join(venv_dir, "bin", "python")
    if os.path.exists(python):
        return python, SandboxResult(0, "[venv cache hit]")

    created = run_sandboxed([sys.executable, "-m", "venv", venv_dir], cwd=base, timeout=300)
    if not created.ok:
        shutil.rmtree(venv_dir, ignore_errors=True)
        return python, created

    lock_path = os.path.join(base, f"{digest}.lock")
    with open(lock_path, "w", encoding="utf-8") as handle:
        handle.write(lock_text)

    installed = run_sandboxed(
        [python, "-m", "pip", "install", "--no-input", "--disable-pip-version-check",
         "-r", lock_path, "pytest", "pytest-cov"],
        cwd=base,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    if not installed.ok:
        shutil.rmtree(venv_dir, ignore_errors=True)
    return python, installed


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------

#: Wrapper that imports the node's analysis module, calls ``main(data_dir)``
#: and prints the result as canonical JSON between markers the runner parses.
_MAIN_WRAPPER = """
import json, os, sys
sys.path.insert(0, os.getcwd())
import analysis
result = analysis.main(sys.argv[1])
print("<<<VGRAPH_RESULT>>>")
print(json.dumps(result, sort_keys=True, separators=(",", ":"), default=str))
"""


def parse_result(output: str):
    """Extract the JSON result the analysis wrapper printed, or None."""
    marker = "<<<VGRAPH_RESULT>>>"
    if marker not in output:
        return None
    tail = output.rsplit(marker, 1)[1].strip()
    try:
        return json.loads(tail.splitlines()[0]) if tail else None
    except (ValueError, IndexError):
        return None


def run_gates(python: str, code_dir: str) -> dict:
    """Run the test suite with the 100% coverage gate and the known cases.

    Returns ``{"tests": {...}, "known_cases": {...}, "ok": bool}``.
    """
    tests = run_sandboxed(
        [python, "-m", "pytest", "-q", "--cov=analysis", "--cov-report=term-missing",
         "--cov-fail-under=100", "test_analysis.py"],
        cwd=code_dir,
    )
    known = run_sandboxed(
        [python, "-c", _KNOWN_CASES_WRAPPER],
        cwd=code_dir,
    )
    return {
        "tests": tests.to_dict(),
        "known_cases": known.to_dict(),
        "ok": tests.ok and known.ok,
    }


#: Runs every entry of ``known_cases.json`` through the analysis module.
#: Each case is ``{"name", "input", "expected"}``; ``input`` is passed to
#: ``analysis.known_case(input)`` when that hook exists, else to ``main``.
_KNOWN_CASES_WRAPPER = """
import json, os, sys
sys.path.insert(0, os.getcwd())
import analysis
cases = json.load(open("known_cases.json"))
runner = getattr(analysis, "known_case", None) or analysis.main
failures = []
for case in cases:
    got = runner(case.get("input"))
    want = case.get("expected")
    if got != want:
        failures.append({"name": case.get("name"), "got": got, "expected": want})
if failures:
    print(json.dumps(failures, indent=2))
    sys.exit(1)
print(f"{len(cases)} known case(s) passed")
"""


def run_analysis(python: str, code_dir: str, data_dir: str) -> Tuple[SandboxResult, object]:
    """Run ``analysis.main(data_dir)`` in the sandbox; return the result and its value."""
    outcome = run_sandboxed(
        [python, "-c", _MAIN_WRAPPER, data_dir],
        cwd=code_dir,
        env=sandbox_env(),
    )
    return outcome, parse_result(outcome.output)


def evaluate_axis(axis: str, node: dict, fresh_result, previous_hash: Optional[str]) -> Tuple[bool, str]:
    """Decide whether a fresh result satisfies *axis*; return (passed, note).

    The reproducible axis is pure hash equality against the stored result -
    same data, same code, same answer. The other three axes swap data or code
    per plan section 2, so their pass condition is the statement's own claim
    still holding, which the analysis reports as ``result["holds"]``.
    """
    if fresh_result is None:
        return False, "analysis produced no parseable result"

    fresh_hash = result_hash(fresh_result)
    if axis == "reproducible":
        if previous_hash is None:
            return True, f"first run; recorded result_hash {fresh_hash[:12]}"
        if fresh_hash == previous_hash:
            return True, f"result_hash matches ({fresh_hash[:12]})"
        return False, f"result_hash changed: {previous_hash[:12]} -> {fresh_hash[:12]}"

    holds = fresh_result.get("holds") if isinstance(fresh_result, dict) else None
    if holds is None:
        return False, f"{axis} axis needs the analysis to report a boolean 'holds' field"
    return bool(holds), f"claim {'holds' if holds else 'does not hold'} under the {axis} axis"


def verify_node(
    node: dict,
    files: Dict[str, bytes],
    axis: str = "reproducible",
    job_root: Optional[str] = None,
    venv_root: Optional[str] = None,
    opener=urllib.request.urlopen,
) -> dict:
    """Run one verification axis for *node* and return the run record.

    The record is what the caller writes to ``runs/<node-id>/<ts>/`` and folds
    into the node's verification record. It always reports honestly: a run
    that could not even start comes back with ``passed: False`` and a reason,
    never as a silent skip.
    """
    # now_iso() includes a UTC offset like "+00:00"; store.safe_code_path (which
    # this stamp is later validated against, since it becomes an S3 key
    # component under runs/<node-id>/<stamp>/) only allows
    # [A-Za-z0-9._-], so every other character - not just ":" - must go.
    stamp = re.sub(r"[^A-Za-z0-9._-]", "-", now_iso())
    record = {
        "node_id": node.get("id"),
        "axis": axis,
        "ran_at": now_iso(),
        "code_hash": code_hash(files),
        "env": "environment.lock",
        "passed": False,
        "stage": "layout",
    }

    gates = check_code_layout(files)
    record["layout"] = gates
    if not gates["ok"]:
        record["note"] = "code sidecar does not meet the required layout"
        record["log"] = json.dumps(gates, indent=2)
        record["stamp"] = stamp
        return record

    job_dir = materialize_job(node.get("id") or "node", files, root=job_root)
    code_dir = os.path.join(job_dir, "code")
    data_dir = os.path.join(job_dir, "data")
    log_parts: List[str] = []
    try:
        record["stage"] = "data"
        version = resolve_cache_version(opener=opener)
        record["data"] = download_data(node.get("data") or [], data_dir, version, opener=opener)
        record["cache_version"] = version

        record["stage"] = "environment"
        python, env_result = ensure_venv(files["environment.lock"].decode("utf-8", "replace"), root=venv_root)
        log_parts.append(f"--- environment ---\n{env_result.output}")
        if not env_result.ok:
            record["note"] = "could not build the pinned environment"
            return record

        record["stage"] = "gates"
        gate_results = run_gates(python, code_dir)
        record["gates"] = gate_results
        log_parts.append(f"--- tests ---\n{gate_results['tests']['output']}")
        log_parts.append(f"--- known cases ---\n{gate_results['known_cases']['output']}")
        if not gate_results["ok"]:
            record["note"] = "code gates failed (tests, 100% coverage, or known cases)"
            return record

        record["stage"] = "analysis"
        outcome, value = run_analysis(python, code_dir, data_dir)
        log_parts.append(f"--- analysis ---\n{outcome.output}")
        if not outcome.ok:
            record["note"] = "analysis.py did not exit cleanly"
            return record

        record["result"] = value
        record["result_hash"] = result_hash(value)
        previous = _previous_result_hash(node, axis)
        record["passed"], record["note"] = evaluate_axis(axis, node, value, previous)
        record["stage"] = "complete"
    except RunnerError as exc:
        record["note"] = str(exc)
    finally:
        record["log"] = "\n\n".join(log_parts)
        record["stamp"] = stamp
        shutil.rmtree(job_dir, ignore_errors=True)
    return record


def _previous_result_hash(node: dict, axis: str) -> Optional[str]:
    """Return the result_hash recorded for *axis*, or None if there is none."""
    entry = ((node.get("verification") or {}).get(axis) or {})
    run = entry.get("run") or {}
    return run.get("result_hash")


def apply_run(node: dict, record: dict) -> dict:
    """Fold a run record into *node*'s verification record; return the node.

    Also refreshes ``code_hash`` on the node's reproducible axis, so a later
    code change is detectable as staleness.
    """
    axis = record["axis"]
    verification = node.setdefault("verification", {})
    entry = verification.setdefault(axis, {"status": "not_attempted", "runs": []})

    previous_run = entry.get("run")
    if previous_run:
        entry.setdefault("runs", []).append(previous_run)

    entry["run"] = {
        "code_hash": record.get("code_hash"),
        "env": record.get("env"),
        "result_hash": record.get("result_hash"),
        "ran_at": record.get("ran_at"),
        "log": record.get("log_prefix"),
        "passed": record.get("passed"),
    }
    entry["status"] = "passed" if record.get("passed") else "failed"
    entry["note"] = record.get("note")

    if axis == "reproducible" and not record.get("passed"):
        node["status"] = "failed" if record.get("stage") == "analysis" else node.get("status", "proposed")
    return node


def code_is_stale(node: dict, files: Dict[str, bytes]) -> bool:
    """True when the sidecar no longer matches the hash the last run recorded."""
    recorded = ((node.get("verification") or {}).get("reproducible") or {}).get("run") or {}
    previous = recorded.get("code_hash")
    return bool(previous) and previous != code_hash(files)
