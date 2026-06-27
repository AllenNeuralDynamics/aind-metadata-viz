"""Bedrock-backed agent loop for the /chat endpoint."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import boto3

from .prompt import SYSTEM_PROMPT
from .security import extract_json_field
from .tools import invoke_tool, list_allowed_tools, to_bedrock_tool_spec

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"
DEFAULT_REGION = "us-west-2"

# Env-overridable safety caps.
MAX_ITERATIONS = int(os.environ.get("CHAT_MAX_ITERATIONS", "12"))
MAX_TOOL_CALLS = int(os.environ.get("CHAT_MAX_TOOL_CALLS", "24"))
MAX_TOOL_RESULT_BYTES = int(
    os.environ.get("CHAT_MAX_TOOL_RESULT_BYTES", "100000")
)
PER_TOOL_TIMEOUT_S = float(os.environ.get("CHAT_TOOL_TIMEOUT_S", "60"))


@dataclass
class ToolCallRecord:
    """Audit record for a single tool invocation."""

    name: str
    input: dict
    output: str
    is_error: bool


@dataclass
class ChatResult:
    """Final result of an agent run."""

    response: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    stop_reason: str = "end_turn"
    iterations: int = 0


def _bedrock_client():
    """Build a Bedrock runtime client, assuming a role if configured."""
    role_arn = os.environ.get("BEDROCK_ROLE_ARN") or None
    region = os.environ.get("AWS_REGION", DEFAULT_REGION)
    if role_arn:
        sts = boto3.client("sts")
        assumed = sts.assume_role(
            RoleArn=role_arn, RoleSessionName="chat-agent"
        )
        creds = assumed["Credentials"]
        return boto3.client(
            "bedrock-runtime",
            region_name=region,
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    return boto3.client("bedrock-runtime", region_name=region)


def _history_to_messages(history: list[dict] | None) -> list[dict]:
    """Convert client-supplied turn history to Bedrock message blocks."""
    msgs: list[dict] = []
    for turn in history or []:
        role = turn.get("role")
        content = turn.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        msgs.append({"role": role, "content": [{"text": content}]})
    return msgs


def _converse_sync(bedrock, **kwargs) -> dict:
    """Wrapper to allow easy patching from tests."""
    return bedrock.converse(**kwargs)


def _parse_final_response(text: str) -> str:
    """Extract the user-facing answer from the model's JSON output.

    The system prompt requires final answers to be ``{"response": ...}``.
    Pulling the value out of that fixed field means a prompt-injection
    attempt cannot change the shape of what we hand back to the caller.
    """
    response = extract_json_field(text, "response")
    if response is None:
        logger.warning("Agent final answer was not valid JSON; got %r", text[:200])
        return (
            "A response could not be produced in the expected format."
        )
    return response


async def run_agent(
    message: str,
    history: list[dict] | None = None,
    *,
    model_id: str | None = None,
    bedrock_client_factory=_bedrock_client,
) -> ChatResult:
    """Run the agent loop and return the final result.

    Parameters
    ----------
    message:
        The user's new message.
    history:
        Optional list of prior turns. Each turn is ``{"role": ..., "content": ...}``.
    model_id:
        Override the default model.
    bedrock_client_factory:
        Injected for tests so they can supply a mock Bedrock client.
    """
    tools = await list_allowed_tools()
    tool_specs = [to_bedrock_tool_spec(t) for t in tools]
    tool_names = {t.name for t in tools}

    messages = _history_to_messages(history)
    messages.append({"role": "user", "content": [{"text": message}]})

    bedrock = bedrock_client_factory()
    chosen_model = model_id or os.environ.get("CHAT_MODEL_ID", DEFAULT_MODEL_ID)

    tool_calls: list[ToolCallRecord] = []
    stop_reason = "end_turn"
    total_tool_calls = 0

    for iteration in range(1, MAX_ITERATIONS + 1):
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _converse_sync(
                bedrock,
                modelId=chosen_model,
                system=[{"text": SYSTEM_PROMPT}],
                messages=messages,
                toolConfig={"tools": tool_specs},
            ),
        )

        output_msg = response["output"]["message"]
        # Append assistant turn (with tool_use blocks if any) so the next
        # request has the full context.
        messages.append(output_msg)

        bedrock_stop = response.get("stopReason", "end_turn")
        content_blocks = output_msg.get("content", [])

        if bedrock_stop != "tool_use":
            text_parts = [
                b["text"] for b in content_blocks if "text" in b
            ]
            return ChatResult(
                response=_parse_final_response("\n".join(text_parts).strip()),
                tool_calls=tool_calls,
                stop_reason=bedrock_stop,
                iterations=iteration,
            )

        # Execute each requested tool, building a single user turn
        # containing one toolResult per toolUse.
        tool_result_blocks: list[dict] = []
        for block in content_blocks:
            if "toolUse" not in block:
                continue
            tu = block["toolUse"]
            tool_use_id = tu["toolUseId"]
            name = tu["name"]
            args = tu.get("input", {}) or {}

            if total_tool_calls >= MAX_TOOL_CALLS:
                tool_result_blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [
                                {
                                    "text": (
                                        "Tool call budget exhausted. "
                                        "Answer with what you have."
                                    )
                                }
                            ],
                            "status": "error",
                        }
                    }
                )
                continue

            if name not in tool_names:
                tool_result_blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [
                                {
                                    "text": (
                                        f"Tool '{name}' is not available."
                                    )
                                }
                            ],
                            "status": "error",
                        }
                    }
                )
                tool_calls.append(
                    ToolCallRecord(
                        name=name,
                        input=args,
                        output="not available",
                        is_error=True,
                    )
                )
                total_tool_calls += 1
                continue

            try:
                text, is_error = await asyncio.wait_for(
                    invoke_tool(
                        name, args, max_bytes=MAX_TOOL_RESULT_BYTES
                    ),
                    timeout=PER_TOOL_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                text = (
                    f"Tool '{name}' timed out after "
                    f"{PER_TOOL_TIMEOUT_S:.0f}s."
                )
                is_error = True
            except Exception as exc:  # noqa: BLE001
                logger.exception("Tool '%s' failed", name)
                text = (
                    f"Tool '{name}' raised: {type(exc).__name__}: {exc}"
                )
                is_error = True

            tool_calls.append(
                ToolCallRecord(
                    name=name,
                    input=args,
                    output=text,
                    is_error=is_error,
                )
            )
            total_tool_calls += 1
            tool_result_blocks.append(
                {
                    "toolResult": {
                        "toolUseId": tool_use_id,
                        "content": [{"text": text}],
                        "status": "error" if is_error else "success",
                    }
                }
            )

        if not tool_result_blocks:
            # Bedrock said tool_use but gave us no toolUse blocks; bail.
            return ChatResult(
                response="",
                tool_calls=tool_calls,
                stop_reason="empty_tool_use",
                iterations=iteration,
            )

        messages.append({"role": "user", "content": tool_result_blocks})

    # Loop exhausted. Ask the model for a final answer in a bounded extra
    # step so the user still gets prose back.
    final_messages = messages + [
        {
            "role": "user",
            "content": [
                {
                    "text": (
                        "You have used the maximum number of tool calls."
                        " Give your best answer now without requesting any"
                        ' more tools, as the required JSON object'
                        ' {"response": "..."}.'
                    )
                }
            ],
        }
    ]
    final_response = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: _converse_sync(
            bedrock,
            modelId=chosen_model,
            system=[{"text": SYSTEM_PROMPT}],
            messages=final_messages,
        ),
    )
    text_parts = [
        b["text"]
        for b in final_response["output"]["message"].get("content", [])
        if "text" in b
    ]
    return ChatResult(
        response=_parse_final_response("\n".join(text_parts).strip()),
        tool_calls=tool_calls,
        stop_reason="max_iterations",
        iterations=MAX_ITERATIONS,
    )


def result_to_dict(result: ChatResult) -> dict[str, Any]:
    """JSON-serialize a ChatResult for the HTTP response body."""
    return {
        "response": result.response,
        "stop_reason": result.stop_reason,
        "iterations": result.iterations,
        "tool_calls": [
            {
                "name": c.name,
                "input": c.input,
                "output": c.output,
                "is_error": c.is_error,
            }
            for c in result.tool_calls
        ],
    }
