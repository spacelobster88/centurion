"""A2A protocol HTTP endpoints for Centurion.

Implements the core A2A endpoints:
- GET  /.well-known/agent.json  — Agent Card discovery
- POST /a2a                     — Task submission (A2A JSON-RPC)
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from centurion.a2a.agent_card import build_agent_card

if TYPE_CHECKING:
    from centurion.core.engine import Centurion

logger = logging.getLogger(__name__)

a2a_router = APIRouter(tags=["a2a"])


# ---------------------------------------------------------------------------
# Agent Card discovery
# ---------------------------------------------------------------------------


@a2a_router.get("/.well-known/agent.json")
async def agent_card(request: Request) -> dict[str, Any]:
    """Return the A2A Agent Card for discovery."""
    base_url = str(request.base_url).rstrip("/")
    return build_agent_card(base_url=base_url)


# ---------------------------------------------------------------------------
# A2A JSON-RPC endpoint
# ---------------------------------------------------------------------------


class A2AMessage(BaseModel):
    """A single A2A message part."""

    role: str = "user"
    parts: list[dict[str, Any]] = Field(default_factory=list)


class A2ATaskRequest(BaseModel):
    """A2A task/send request body."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    params: dict[str, Any] = Field(default_factory=dict)


@a2a_router.post("/a2a")
async def a2a_task_handler(request: Request, body: A2ATaskRequest) -> dict[str, Any]:
    """Handle A2A JSON-RPC task requests.

    Maps A2A tasks to Centurion fleet operations:
    - Extracts the prompt from the A2A message parts
    - Submits to the first available century in the first legion
    - Returns an A2A-compliant response
    """
    engine: Centurion = request.app.state.centurion

    # Extract prompt from A2A message parts
    message = body.params.get("message", {})
    parts = message.get("parts", [])
    prompt = ""
    for part in parts:
        if part.get("type") == "text":
            prompt += part.get("text", "")
        elif "text" in part:
            prompt += part["text"]

    if not prompt:
        raise HTTPException(status_code=400, detail="No text content in A2A message")

    # Find a legion and century to submit to
    if not engine.legions:
        raise HTTPException(
            status_code=503,
            detail="No legions available. Use /api/centurion/legions to create one first.",
        )

    legion = next(iter(engine.legions.values()))
    if not legion.centuries:
        raise HTTPException(
            status_code=503,
            detail=f"Legion {legion.id!r} has no centuries. Add one first.",
        )

    century = next(iter(legion.centuries.values()))
    task_id = f"a2a-{uuid.uuid4().hex[:8]}"

    await century.submit_task(prompt=prompt, priority=5, task_id=task_id)

    logger.info(
        "A2A task submitted",
        extra={"a2a_id": body.id, "task_id": task_id, "prompt_len": len(prompt)},
    )

    # Return A2A-compliant response (task accepted)
    return {
        "id": body.id,
        "result": {
            "id": task_id,
            "status": {
                "state": "submitted",
                "message": {
                    "role": "agent",
                    "parts": [{"type": "text", "text": f"Task {task_id} submitted to century {century.id}"}],
                },
            },
        },
    }
