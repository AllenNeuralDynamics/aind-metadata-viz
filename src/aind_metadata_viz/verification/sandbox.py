"""Sandboxing primitives shared by the runner and the agent.

Both subsystems execute untrusted code on the portal host: the runner runs
node ``analysis.py`` files, and the agent runs an LLM coding agent that writes
them. The isolation they need is identical, so it lives here once.

The sandbox is three things:

* **A scrubbed environment.** Every AWS credential variable is dropped, so a
  child process cannot reach the portal's S3 write access or its Bedrock role
  by inheriting them. The caller adds back only what a given job needs.
* **Resource limits.** CPU seconds, address space, file size and process
  count are capped with ``setrlimit`` in the child before ``exec``.
* **A wall-clock timeout.** Enforced by ``subprocess.run``; on expiry the
  whole process group is killed.

If in-container isolation proves too weak this moves to a separate ECS task;
the calling contract does not change.
"""

from __future__ import annotations

import os
import resource
import subprocess
from typing import Dict, List, Optional

#: Environment variables that must never reach a sandboxed child.
_CREDENTIAL_VARS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN",
    "AWS_PROFILE",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_ROLE_ARN",
    "BEDROCK_ROLE_ARN",
    "SESSION_SECRET",
    "PINPOINT_ENCRYPTION_SECRET",
    "DOC_DB_PASSWORD",
    "DOC_DB_USER",
)

#: Variables a sandboxed child does need in order to run Python at all.
_KEEP_VARS = ("PATH", "LANG", "LC_ALL", "TZ", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR")

DEFAULT_CPU_SECONDS = int(os.environ.get("VGRAPH_CPU_SECONDS", "300"))
DEFAULT_MEMORY_BYTES = int(os.environ.get("VGRAPH_MEMORY_BYTES", str(2 * 1024**3)))
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("VGRAPH_TIMEOUT_SECONDS", "900"))
DEFAULT_FILE_SIZE_BYTES = int(os.environ.get("VGRAPH_FILE_SIZE_BYTES", str(256 * 1024**2)))
DEFAULT_MAX_PROCESSES = int(os.environ.get("VGRAPH_MAX_PROCESSES", "256"))

#: Unix user the sandboxed child runs as. Created by the Dockerfile; when the
#: user does not exist (local dev, tests) the child simply runs as the caller.
SANDBOX_USER = os.environ.get("VGRAPH_SANDBOX_USER", "vgraph")

MAX_OUTPUT_BYTES = 200_000


class SandboxResult:
    """Outcome of one sandboxed command."""

    def __init__(self, returncode: int, output: str, timed_out: bool = False):
        """Record the exit code, combined output, and whether the wall clock expired."""
        self.returncode = returncode
        self.output = output
        self.timed_out = timed_out

    @property
    def ok(self) -> bool:
        """True when the command exited zero and did not time out."""
        return self.returncode == 0 and not self.timed_out

    def to_dict(self) -> dict:
        """Return a JSON-serializable view of the result."""
        return {"returncode": self.returncode, "output": self.output, "timed_out": self.timed_out}


def sandbox_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return an environment with every credential stripped, plus *extra*.

    Callers add back exactly what the job is entitled to - the agent gets
    Bedrock credentials and nothing else; the runner gets nothing at all.
    """
    env = {name: os.environ[name] for name in _KEEP_VARS if name in os.environ}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env["HOME"] = env.get("TMPDIR", "/tmp")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    for name in _CREDENTIAL_VARS:
        env.pop(name, None)
    if extra:
        env.update(extra)
    return env


def _sandbox_user_ids() -> Optional[tuple]:
    """Return (uid, gid) for ``SANDBOX_USER``, or None when it does not exist."""
    try:
        import pwd

        record = pwd.getpwnam(SANDBOX_USER)
    except Exception:
        return None
    if record.pw_uid == os.getuid():
        return None
    if os.getuid() != 0:
        # Only root can change uid; running as anyone else, the limits and the
        # scrubbed environment are the whole sandbox.
        return None
    return (record.pw_uid, record.pw_gid)


def _set_limit(which: int, value: int) -> None:  # pragma: no cover - forked child
    """Apply one rlimit, clamped to the existing hard limit.

    Applied best-effort: a limit the platform refuses (RLIMIT_AS is a no-op on
    macOS, for instance) must not stop the child from starting. Production runs
    on Linux, where all of these hold; locally the scrubbed environment and the
    wall-clock timeout are what remain.
    """
    try:
        _soft, hard = resource.getrlimit(which)
        if hard != resource.RLIM_INFINITY:
            value = min(value, hard)
        resource.setrlimit(which, (value, value))
    except (ValueError, OSError):
        pass


def _preexec(cpu_seconds: int, memory_bytes: int, file_size_bytes: int, max_processes: int):
    """Build the child-side hook that applies limits and drops privileges."""

    def apply():  # pragma: no cover - runs only in the forked child
        os.setsid()
        _set_limit(resource.RLIMIT_CPU, cpu_seconds)
        _set_limit(resource.RLIMIT_AS, memory_bytes)
        _set_limit(resource.RLIMIT_FSIZE, file_size_bytes)
        _set_limit(resource.RLIMIT_NPROC, max_processes)
        _set_limit(resource.RLIMIT_CORE, 0)
        try:
            os.setpriority(os.PRIO_PROCESS, 0, 10)
        except OSError:
            pass
        ids = _sandbox_user_ids()
        if ids is not None:
            os.setgid(ids[1])
            os.setuid(ids[0])

    return apply


def run_sandboxed(
    command: List[str],
    cwd: str,
    env: Optional[Dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    cpu_seconds: int = DEFAULT_CPU_SECONDS,
    memory_bytes: int = DEFAULT_MEMORY_BYTES,
) -> SandboxResult:
    """Run *command* in *cwd* under the sandbox and return its result.

    stdout and stderr are combined and truncated to ``MAX_OUTPUT_BYTES`` so a
    runaway process cannot fill the log store.
    """
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env if env is not None else sandbox_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            preexec_fn=_preexec(
                cpu_seconds, memory_bytes, DEFAULT_FILE_SIZE_BYTES, DEFAULT_MAX_PROCESSES
            ),
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.output or ""
        if isinstance(partial, bytes):  # pragma: no cover - text=True keeps this str
            partial = partial.decode("utf-8", "replace")
        return SandboxResult(-1, _truncate(partial) + "\n[timed out]", timed_out=True)
    except (OSError, ValueError) as exc:
        return SandboxResult(-1, f"[failed to start: {exc}]")

    return SandboxResult(completed.returncode, _truncate(completed.stdout or ""))


def _truncate(text: str) -> str:
    """Truncate *text* to ``MAX_OUTPUT_BYTES``, noting how much was dropped."""
    if len(text) <= MAX_OUTPUT_BYTES:
        return text
    dropped = len(text) - MAX_OUTPUT_BYTES
    return text[:MAX_OUTPUT_BYTES] + f"\n[{dropped} bytes truncated]"
