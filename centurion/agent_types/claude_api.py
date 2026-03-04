"""Claude API agent type — uses the Anthropic Python SDK."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, AsyncIterator

from centurion.agent_types.base import AgentResult, AgentType
from centurion.config import ResourceRequirements, ResourceSpec

logger = logging.getLogger(__name__)


class ClaudeApiAgentType(AgentType):
    """Agent type that calls Claude via the Anthropic HTTP API."""

    name = "claude_api"

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
        api_key: str = "",
        system_prompt: str = "",
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.system_prompt = system_prompt

    async def spawn(self, legionary_id: str, cwd: str, env: dict[str, str]) -> dict:
        """API agents are stateless — return config as handle."""
        return {
            "legionary_id": legionary_id,
            "api_key": env.get("ANTHROPIC_API_KEY", self.api_key),
        }

    async def send_task(self, handle: Any, task: str, timeout: float) -> AgentResult:
        try:
            import anthropic
        except ImportError:
            return AgentResult(
                success=False,
                error="anthropic package not installed. Run: pip install anthropic",
            )

        api_key = handle.get("api_key", self.api_key)
        if not api_key:
            return AgentResult(
                success=False,
                error="ANTHROPIC_API_KEY not set",
            )

        client = anthropic.AsyncAnthropic(api_key=api_key)
        messages = [{"role": "user", "content": task}]
        legionary_id = handle.get("legionary_id", "unknown")

        start = time.monotonic()
        logger.debug("send_task: starting legionary_id=%s model=%s max_tokens=%d", legionary_id, self.model, self.max_tokens)
        try:
            response = await client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=messages,
                system=self.system_prompt or anthropic.NOT_GIVEN,
                timeout=timeout,
            )
            elapsed = time.monotonic() - start
            output = ""
            for block in response.content:
                if block.type == "text":
                    output += block.text
            logger.info(
                "send_task: completed legionary_id=%s model=%s duration=%.2fs input_tokens=%d output_tokens=%d",
                legionary_id, response.model, elapsed,
                response.usage.input_tokens, response.usage.output_tokens,
            )
            return AgentResult(
                success=True,
                output=output.strip(),
                exit_code=0,
                duration_seconds=round(elapsed, 2),
                metadata={
                    "model": response.model,
                    "usage": {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                    },
                    "stop_reason": response.stop_reason,
                },
            )
        except Exception as e:
            elapsed = time.monotonic() - start
            logger.warning("send_task: failed legionary_id=%s error=%s duration=%.2fs", legionary_id, e, elapsed)
            return AgentResult(
                success=False,
                error=str(e),
                duration_seconds=round(elapsed, 2),
            )

    async def stream_output(self, handle: Any) -> AsyncIterator[str]:
        # Could be implemented with streaming API in the future
        return
        yield

    async def terminate(self, handle: Any, graceful: bool = True) -> None:
        # API agents are stateless — nothing to terminate
        pass

    def resource_requirements(self) -> ResourceRequirements:
        return ResourceRequirements(
            requests=ResourceSpec(cpu_millicores=100, memory_mb=50),
            limits=ResourceSpec(cpu_millicores=200, memory_mb=100),
        )
