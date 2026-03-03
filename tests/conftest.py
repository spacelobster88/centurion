import asyncio
import pytest
from centurion.agent_types.base import AgentResult, AgentType
from centurion.config import ResourceRequirements, ResourceSpec

class MockAgentType(AgentType):
    """Fast mock agent for testing -- no real subprocess."""
    name = "mock"

    def __init__(self, delay: float = 0.01, fail_rate: float = 0.0):
        self.delay = delay
        self.fail_rate = fail_rate
        self._call_count = 0

    async def spawn(self, legionary_id, cwd, env):
        return {"legionary_id": legionary_id}

    async def send_task(self, handle, task, timeout):
        import random, time
        self._call_count += 1
        start = time.monotonic()
        await asyncio.sleep(self.delay)
        if random.random() < self.fail_rate:
            return AgentResult(success=False, output="", error="Mock failure", duration_seconds=time.monotonic()-start)
        return AgentResult(success=True, output=f"Mock result for: {task}", duration_seconds=time.monotonic()-start)

    async def stream_output(self, handle):
        return; yield

    async def terminate(self, handle, graceful=True):
        pass

    def resource_requirements(self):
        return ResourceRequirements(
            requests=ResourceSpec(cpu_millicores=10, memory_mb=10),
            limits=ResourceSpec(cpu_millicores=10, memory_mb=10),
        )

@pytest.fixture
def mock_agent_type():
    return MockAgentType()

@pytest.fixture
def failing_agent_type():
    return MockAgentType(fail_rate=1.0)
