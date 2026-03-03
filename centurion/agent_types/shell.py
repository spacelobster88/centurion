"""Shell agent type — runs arbitrary shell commands via async subprocess.

On macOS, operations requiring FullDiskAccess/Accessibility/Automation
permissions should be routed through iTerm2 context.
"""

from __future__ import annotations

import asyncio
import os
import platform
import time
from typing import Any, AsyncIterator

from centurion.agent_types.base import AgentResult, AgentType
from centurion.config import ResourceRequirements, ResourceSpec


class ShellAgentType(AgentType):
    """Agent type that executes shell commands via async subprocess."""

    name = "shell"

    def __init__(
        self,
        shell: str = "",
        use_iterm2: bool | None = None,
    ) -> None:
        self.shell = shell or os.getenv("SHELL", "/bin/zsh")
        # On macOS, default to iTerm2 awareness since only iTerm2 has
        # FullDiskAccess, Accessibility, and Automation permissions
        if use_iterm2 is None:
            self.use_iterm2 = platform.system() == "Darwin"
        else:
            self.use_iterm2 = use_iterm2

    async def spawn(self, legionary_id: str, cwd: str, env: dict[str, str]) -> dict:
        """Shell agents are invocation-based. Return config as handle."""
        return {"legionary_id": legionary_id, "cwd": cwd, "env": env}

    async def send_task(self, handle: Any, task: str, timeout: float) -> AgentResult:
        cwd = handle.get("cwd", "/tmp")
        extra_env = handle.get("env", {})

        env = dict(os.environ)
        env.update(extra_env)

        start = time.monotonic()

        proc = await asyncio.create_subprocess_exec(
            self.shell, "-c", task,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return AgentResult(
                success=False,
                output="",
                error=f"Shell command timed out after {timeout}s",
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
        return
        yield

    async def terminate(self, handle: Any, graceful: bool = True) -> None:
        pass

    def resource_requirements(self) -> ResourceRequirements:
        return ResourceRequirements(
            requests=ResourceSpec(cpu_millicores=200, memory_mb=50),
            limits=ResourceSpec(cpu_millicores=500, memory_mb=200),
        )
