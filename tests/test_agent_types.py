"""Tests for the built-in agent types and the registry."""

from __future__ import annotations

import platform

import pytest

from centurion.agent_types.claude_api import ClaudeApiAgentType
from centurion.agent_types.claude_cli import ClaudeCliAgentType
from centurion.agent_types.registry import AgentTypeRegistry
from centurion.agent_types.shell import ShellAgentType
from centurion.config import ResourceRequirements
from tests.conftest import MockAgentType

# =========================================================================
# Registry
# =========================================================================


class TestRegistry:
    def test_register_and_create(self):
        reg = AgentTypeRegistry()
        reg.register("mock", MockAgentType)
        agent = reg.create("mock", delay=0.05)
        assert isinstance(agent, MockAgentType)
        assert agent.delay == 0.05

    def test_create_unknown_raises(self):
        reg = AgentTypeRegistry()
        with pytest.raises(ValueError, match="Unknown agent type"):
            reg.create("nonexistent")

    def test_list_types(self):
        reg = AgentTypeRegistry()
        reg.register("mock", MockAgentType)
        reg.register("shell", ShellAgentType)
        types = reg.list_types()
        assert "mock" in types
        assert "shell" in types
        assert types["mock"] is MockAgentType


# =========================================================================
# MockAgentType
# =========================================================================


class TestMockAgentType:
    @pytest.mark.asyncio
    async def test_spawn(self):
        agent = MockAgentType()
        handle = await agent.spawn("leg-1", "/tmp", {})
        assert handle["legionary_id"] == "leg-1"

    @pytest.mark.asyncio
    async def test_send_task_success(self):
        agent = MockAgentType(delay=0.01, fail_rate=0.0)
        handle = await agent.spawn("leg-1", "/tmp", {})
        result = await agent.send_task(handle, "test prompt", timeout=5.0)
        assert result.success is True
        assert "test prompt" in result.output

    @pytest.mark.asyncio
    async def test_send_task_failure(self):
        agent = MockAgentType(delay=0.01, fail_rate=1.0)
        handle = await agent.spawn("leg-1", "/tmp", {})
        result = await agent.send_task(handle, "test", timeout=5.0)
        assert result.success is False
        assert result.error == "Mock failure"

    @pytest.mark.asyncio
    async def test_terminate(self):
        agent = MockAgentType()
        handle = await agent.spawn("leg-1", "/tmp", {})
        await agent.terminate(handle)  # should not raise

    def test_resource_requirements(self):
        agent = MockAgentType()
        reqs = agent.resource_requirements()
        assert isinstance(reqs, ResourceRequirements)
        assert reqs.requests.cpu_millicores == 10
        assert reqs.requests.memory_mb == 10

    @pytest.mark.asyncio
    async def test_call_count(self):
        agent = MockAgentType()
        handle = await agent.spawn("leg-1", "/tmp", {})
        assert agent._call_count == 0
        await agent.send_task(handle, "a", 5.0)
        await agent.send_task(handle, "b", 5.0)
        assert agent._call_count == 2


# =========================================================================
# ShellAgentType
# =========================================================================


class TestShellAgentType:
    def test_name(self):
        agent = ShellAgentType()
        assert agent.name == "shell"

    def test_macos_iterm2_default(self):
        agent = ShellAgentType()
        if platform.system() == "Darwin":
            assert agent.use_iterm2 is True
        else:
            assert agent.use_iterm2 is False

    def test_explicit_iterm2_override(self):
        agent = ShellAgentType(use_iterm2=False)
        assert agent.use_iterm2 is False

    @pytest.mark.asyncio
    async def test_spawn(self):
        agent = ShellAgentType()
        handle = await agent.spawn("leg-sh-1", "/tmp", {"FOO": "bar"})
        assert handle["legionary_id"] == "leg-sh-1"
        assert handle["cwd"] == "/tmp"
        assert handle["env"]["FOO"] == "bar"

    @pytest.mark.asyncio
    async def test_send_task_echo(self):
        agent = ShellAgentType()
        handle = await agent.spawn("leg-sh-1", "/tmp", {})
        result = await agent.send_task(handle, "echo hello", timeout=10.0)
        assert result.success is True
        assert result.output == "hello"
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_send_task_exit_code(self):
        agent = ShellAgentType()
        handle = await agent.spawn("leg-sh-1", "/tmp", {})
        result = await agent.send_task(handle, "exit 42", timeout=10.0)
        assert result.success is False
        assert result.exit_code == 42

    @pytest.mark.asyncio
    async def test_send_task_timeout(self):
        agent = ShellAgentType()
        handle = await agent.spawn("leg-sh-1", "/tmp", {})
        result = await agent.send_task(handle, "sleep 60", timeout=0.5)
        assert result.success is False
        assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_send_task_stderr(self):
        agent = ShellAgentType()
        handle = await agent.spawn("leg-sh-1", "/tmp", {})
        result = await agent.send_task(handle, "echo err >&2; exit 1", timeout=10.0)
        assert result.success is False
        assert "err" in result.error

    def test_resource_requirements(self):
        agent = ShellAgentType()
        reqs = agent.resource_requirements()
        assert reqs.requests.cpu_millicores == 200
        assert reqs.requests.memory_mb == 50
        assert reqs.limits.cpu_millicores == 500


# =========================================================================
# ClaudeCliAgentType (no real subprocess, just config/spawn checks)
# =========================================================================


class TestClaudeCliAgentType:
    def test_name(self):
        agent = ClaudeCliAgentType()
        assert agent.name == "claude_cli"

    def test_default_skip_permissions(self):
        agent = ClaudeCliAgentType()
        assert agent.skip_permissions is True

    def test_custom_config(self):
        agent = ClaudeCliAgentType(
            model="claude-opus-4-6",
            binary="/usr/local/bin/claude",
            skip_permissions=False,
            allowed_tools="Read,Write",
        )
        assert agent.model == "claude-opus-4-6"
        assert agent.binary == "/usr/local/bin/claude"
        assert agent.skip_permissions is False
        assert agent.allowed_tools == "Read,Write"

    @pytest.mark.asyncio
    async def test_spawn(self):
        agent = ClaudeCliAgentType()
        handle = await agent.spawn("leg-cli-1", "/tmp/work", {"KEY": "val"})
        assert handle["legionary_id"] == "leg-cli-1"
        assert handle["cwd"] == "/tmp/work"
        assert handle["env"]["KEY"] == "val"

    @pytest.mark.asyncio
    async def test_terminate(self):
        agent = ClaudeCliAgentType()
        handle = await agent.spawn("leg-cli-1", "/tmp", {})
        await agent.terminate(handle)  # no-op, should not raise

    def test_resource_requirements(self):
        agent = ClaudeCliAgentType()
        reqs = agent.resource_requirements()
        assert reqs.requests.cpu_millicores == 500
        assert reqs.requests.memory_mb == 250
        assert reqs.limits.cpu_millicores == 1000


# =========================================================================
# ClaudeApiAgentType (no real API call, just config checks)
# =========================================================================


class TestClaudeApiAgentType:
    def test_name(self):
        agent = ClaudeApiAgentType()
        assert agent.name == "claude_api"

    def test_default_model(self):
        agent = ClaudeApiAgentType()
        assert agent.model == "claude-sonnet-4-6"

    def test_custom_config(self):
        agent = ClaudeApiAgentType(
            model="claude-opus-4-6",
            max_tokens=8192,
            api_key="sk-test-key",
            system_prompt="You are a test agent.",
        )
        assert agent.model == "claude-opus-4-6"
        assert agent.max_tokens == 8192
        assert agent.api_key == "sk-test-key"
        assert agent.system_prompt == "You are a test agent."

    @pytest.mark.asyncio
    async def test_spawn_stateless(self):
        agent = ClaudeApiAgentType(api_key="sk-test")
        handle = await agent.spawn("leg-api-1", "/tmp", {})
        assert handle["legionary_id"] == "leg-api-1"
        assert handle["api_key"] == "sk-test"

    @pytest.mark.asyncio
    async def test_spawn_env_override(self):
        agent = ClaudeApiAgentType(api_key="sk-default")
        handle = await agent.spawn("leg-api-1", "/tmp", {"ANTHROPIC_API_KEY": "sk-env"})
        assert handle["api_key"] == "sk-env"

    @pytest.mark.asyncio
    async def test_send_task_no_api_key(self):
        agent = ClaudeApiAgentType(api_key="")
        handle = {"legionary_id": "test", "api_key": ""}
        result = await agent.send_task(handle, "test", timeout=5.0)
        assert result.success is False
        assert "ANTHROPIC_API_KEY" in result.error or "anthropic" in result.error.lower()

    @pytest.mark.asyncio
    async def test_terminate_noop(self):
        agent = ClaudeApiAgentType()
        await agent.terminate({})  # should not raise

    def test_resource_requirements(self):
        agent = ClaudeApiAgentType()
        reqs = agent.resource_requirements()
        assert reqs.requests.cpu_millicores == 100
        assert reqs.requests.memory_mb == 50
        assert reqs.limits.memory_mb == 100
