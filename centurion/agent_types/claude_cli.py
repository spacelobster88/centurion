"""Claude CLI agent type — spawns Claude via async subprocess.

Uses --dangerously-skip-permissions as required for automated agent spawning.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import TYPE_CHECKING, Any

from centurion.agent_types.base import AgentResult, AgentType
from centurion.config import ResourceRequirements, ResourceSpec
from centurion.core.exceptions import TaskTimeoutError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class ClaudeCliAgentType(AgentType):
    """Agent type that invokes Claude CLI (claude -p) via async subprocess."""

    name = "claude_cli"

    def __init__(
        self,
        model: str = "",
        binary: str = "claude",
        skip_permissions: bool = True,
        allowed_tools: str = "",
    ) -> None:
        self.model = model
        self.binary = binary
        self.skip_permissions = skip_permissions
        self.allowed_tools = allowed_tools

    async def spawn(self, legionary_id: str, cwd: str, env: dict[str, str]) -> dict:
        """Claude CLI is invocation-based, not persistent. Return config as handle."""
        return {"legionary_id": legionary_id, "cwd": cwd, "env": env}

    async def send_task(self, handle: Any, task: str, timeout: float) -> AgentResult:
        args = [self.binary, "-p", "--output-format", "text"]
        if self.skip_permissions:
            args.append("--dangerously-skip-permissions")
        if self.model:
            args.extend(["--model", self.model])
        if self.allowed_tools:
            args.extend(["--allowedTools", self.allowed_tools])

        # Sanitize env: remove CLAUDECODE to prevent nested session errors
        clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        clean_env.update(handle.get("env", {}))

        cwd = handle.get("cwd", "/tmp")
        legionary_id = handle.get("legionary_id", "unknown")
        start = time.monotonic()
        logger.debug("send_task: starting legionary_id=%s cwd=%s", legionary_id, cwd)

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=clean_env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=task.encode()),
                timeout=timeout,
            )
        except TimeoutError as exc:
            logger.warning("send_task: timeout legionary_id=%s after %.1fs", legionary_id, timeout)
            # Graceful shutdown: SIGTERM first, then SIGKILL if needed
            try:
                proc.terminate()  # SIGTERM
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except (TimeoutError, ProcessLookupError):
                try:
                    proc.kill()  # SIGKILL
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except (TimeoutError, ProcessLookupError):
                    pass
            raise TaskTimeoutError(
                f"Task timed out after {timeout}s",
                timeout_seconds=timeout,
            ) from exc

        elapsed = time.monotonic() - start
        if proc.returncode != 0:
            logger.warning(
                "send_task: failed legionary_id=%s exit_code=%d duration=%.2fs",
                legionary_id,
                proc.returncode,
                elapsed,
            )
        else:
            logger.info(
                "send_task: completed legionary_id=%s exit_code=0 duration=%.2fs",
                legionary_id,
                elapsed,
            )
        return AgentResult(
            success=proc.returncode == 0,
            output=stdout.decode(errors="replace").strip(),
            error=stderr.decode(errors="replace").strip() if proc.returncode != 0 else None,
            exit_code=proc.returncode,
            duration_seconds=round(elapsed, 2),
        )

    async def stream_output(self, handle: Any) -> AsyncIterator[str]:
        # Claude CLI doesn't support persistent streaming; yield nothing
        return
        yield  # make it an async generator

    async def terminate(self, handle: Any, graceful: bool = True) -> None:
        # Claude CLI is invocation-based — nothing persistent to terminate
        pass

    def resource_requirements(self) -> ResourceRequirements:
        return ResourceRequirements(
            requests=ResourceSpec(cpu_millicores=500, memory_mb=250),
            limits=ResourceSpec(cpu_millicores=1000, memory_mb=500),
        )
