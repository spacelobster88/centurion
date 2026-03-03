"""Claude CLI agent type — spawns Claude via async subprocess.

Uses --dangerously-skip-permissions as required for automated agent spawning.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, AsyncIterator

from centurion.agent_types.base import AgentResult, AgentType
from centurion.config import ResourceRequirements, ResourceSpec


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
        start = time.monotonic()

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
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return AgentResult(
                success=False,
                output="",
                error=f"Task timed out after {timeout}s",
                exit_code=-1,
                duration_seconds=time.monotonic() - start,
            )

        elapsed = time.monotonic() - start
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
