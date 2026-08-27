"""Runs one authoring job's Claude Agent SDK session inside the sandbox.

This module is the process ``agent.AgentJob`` spawns. It exists as a separate
process rather than an in-process call for one specific reason: the SDK
*merges* its ``env`` option over ``os.environ`` rather than replacing it, so an
in-process session would hand the Claude Code subprocess the portal's entire
environment - the ECS task-role URI, the session secret, the DocDB password.
Running the session behind ``sandbox.run_sandboxed`` means the environment is
built from an allowlist instead, and the resource limits and privilege drop
still apply.

Two layers constrain the session:

* **The OS sandbox** (``sandbox.py``) - scrubbed environment, CPU/memory/file
  limits, an unprivileged user, and a wall-clock timeout. This is what the
  process can do at all.
* **The SDK's tool policy** (this module) - a fixed tool surface with
  ``permission_mode="dontAsk"``, so anything not pre-approved is denied rather
  than prompted for, plus a ``PreToolUse`` hook that refuses writes outside the
  job directory. This is what the agent loop will choose to do.

Neither replaces the outbox contract. Nothing this session writes reaches the
graph except through ``agent.read_outbox`` and ``agent.validate_outbox``.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, List

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher

#: Built-in tools the session may use at all. Everything else - notably
#: WebFetch and WebSearch - is left out of the request entirely, so the model
#: never sees a network-reaching tool it could be talked into using.
AGENT_TOOLS: List[str] = ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]

#: Tools removed from the request outright, even if they reappear in a preset.
AGENT_DENIED_TOOLS: List[str] = ["WebFetch", "WebSearch"]

#: Tool calls that write to disk, and so have to be path-checked.
_WRITE_TOOLS = ("Write", "Edit", "NotebookEdit", "MultiEdit")

MAX_TURNS = int(os.environ.get("VGRAPH_AGENT_MAX_TURNS", "120"))

TRANSCRIPT_NAME = "transcript.txt"

#: Mirrors ``agent.CONTROL_DIRNAME`` / ``STEER_FILENAME`` / ``STOP_FILENAME``.
#: Duplicated rather than imported because this module deliberately does not
#: import the ``aind_metadata_viz`` package (see ``agent.AGENT_WORKER_PATH``).
CONTROL_DIRNAME = "control"
STEER_FILENAME = "steer.jsonl"
STOP_FILENAME = "stop"


def _escapes(job_dir: str, path: str) -> bool:
    """True when *path* resolves outside *job_dir*.

    ``realpath`` is used on both sides so a symlink planted inside the job
    directory cannot be used to write through to somewhere else.
    """
    if not path:
        return False
    root = os.path.realpath(job_dir)
    target = os.path.realpath(os.path.join(job_dir, path))
    return not (target == root or target.startswith(root + os.sep))


def make_write_guard(job_dir: str):
    """Build the ``PreToolUse`` hook that confines writes to the job directory.

    Hooks run before every other permission step and a hook denial holds in
    every permission mode, which makes this the one control that cannot be
    widened by a stray allow rule.
    """

    async def guard(input_data: Dict[str, Any], tool_use_id, context):
        """Deny a write whose target path escapes the job directory."""
        if input_data.get("tool_name") not in _WRITE_TOOLS:
            return {}
        tool_input = input_data.get("tool_input") or {}
        path = tool_input.get("file_path") or tool_input.get("path") or ""
        if not _escapes(job_dir, str(path)):
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "Writes are confined to this job directory. Put node documents in "
                    "outbox/nodes/ and code in outbox/code/."
                ),
            }
        }

    return guard


def build_options(job_dir: str, model: str) -> ClaudeAgentOptions:
    """Build the locked-down session options for one job."""
    return ClaudeAgentOptions(
        cwd=job_dir,
        model=model or None,
        tools=AGENT_TOOLS,
        allowed_tools=AGENT_TOOLS,
        disallowed_tools=AGENT_DENIED_TOOLS,
        # Anything not pre-approved is denied outright. A headless session has
        # nobody to prompt, so the alternative is silently relying on the
        # absence of a callback.
        permission_mode="dontAsk",
        # Only this job's own .claude/ is read. Without the explicit list the
        # SDK would also load the host's user and local settings.
        setting_sources=["project"],
        skills="all",
        max_turns=MAX_TURNS,
        hooks={"PreToolUse": [HookMatcher(hooks=[make_write_guard(job_dir)])]},
        env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
    )


def render(message) -> str:
    """Render one SDK message as transcript text."""
    lines: List[str] = []
    for block in getattr(message, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            lines.append(text)
            continue
        name = getattr(block, "name", None)
        if name:
            lines.append(f"[tool: {name}]")
    result = getattr(message, "result", None)
    if result:
        lines.append(str(result))
    return "\n".join(lines)


def stop_requested(job_dir: str) -> bool:
    """True once the portal has asked this session to stop."""
    return os.path.exists(os.path.join(job_dir, CONTROL_DIRNAME, STOP_FILENAME))


def drain_steering(job_dir: str, consumed: int) -> List[str]:
    """Return steering messages queued after the first *consumed* of them."""
    path = os.path.join(job_dir, CONTROL_DIRNAME, STEER_FILENAME)
    try:
        with open(path, encoding="utf-8") as handle:
            lines = [line for line in handle.read().splitlines() if line.strip()]
    except OSError:
        return []
    messages = []
    for line in lines[consumed:]:
        try:
            messages.append(str(json.loads(line)["message"]))
        except (ValueError, KeyError, TypeError):
            continue
    return messages


#: Wrapper around a steering message, so a live instruction reads as an
#: operator note rather than as data the agent should treat as a claim.
STEER_TEMPLATE = """The person who asked for this work has sent a live instruction:

{message}

Take it into account and carry on. It does not replace the outbox contract."""


async def run_session(job_dir: str, prompt: str, model: str) -> dict:
    """Run the session to completion, streaming the transcript to disk.

    The session is bidirectional rather than one-shot so it can be steered:
    between turns the worker drains any instructions the portal has queued and
    sends them as the next turn. A stop request ends the loop, leaving whatever
    is already in the outbox to be harvested and validated as usual.
    """
    transcript_path = os.path.join(job_dir, TRANSCRIPT_NAME)
    turns = 0
    steers = 0
    summary = ""
    stopped = False

    with open(transcript_path, "w", encoding="utf-8") as transcript:

        def write(text: str) -> None:
            """Append *text* to the transcript and flush, so polling sees it live."""
            if text:
                transcript.write(text + "\n")
                transcript.flush()

        async with ClaudeSDKClient(options=build_options(job_dir, model)) as client:
            await client.query(prompt)
            while True:
                async for message in client.receive_response():
                    turns += 1
                    write(render(message))
                    if getattr(message, "result", None):
                        summary = str(message.result)
                    if stop_requested(job_dir):
                        await client.interrupt()
                        stopped = True
                        break

                if stopped or stop_requested(job_dir):
                    stopped = True
                    write("[stopped at the operator's request]")
                    break

                queued = drain_steering(job_dir, steers)
                if not queued:
                    break
                steers += len(queued)
                for message_text in queued:
                    write(f"[steering: {message_text}]")
                await client.query(STEER_TEMPLATE.format(message="\n".join(queued)))

    return {"turns": turns, "steers": steers, "summary": summary, "stopped": stopped}


def main(argv: List[str]) -> int:
    """Entry point: ``python -m ...agent_worker <job-dir>``."""
    if len(argv) < 2:
        print("usage: agent_worker <job-dir>", file=sys.stderr)
        return 2
    job_dir = argv[1]
    with open(os.path.join(job_dir, "prompt.txt"), encoding="utf-8") as handle:
        prompt = handle.read()
    model = os.environ.get("VGRAPH_AGENT_MODEL", "")

    try:
        outcome = asyncio.run(run_session(job_dir, prompt, model))
    except Exception as exc:  # noqa: BLE001 - the parent only sees our exit code
        print(f"[agent session failed: {type(exc).__name__}: {exc}]", file=sys.stderr)
        return 1
    print(json.dumps(outcome))
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(main(sys.argv))
