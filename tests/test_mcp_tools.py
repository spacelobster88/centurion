"""Comprehensive tests for centurion/mcp/tools.py MCP tool definitions.

Tests all 17 MCP tools, verifying:
- Correct HTTP method and API path for each tool
- Correct payload/params construction including optional parameters
- Error handling for ConnectError, TimeoutException, HTTPStatusError
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from centurion.mcp.tools import (
    API_BASE,
    _delete,
    _get,
    _post,
    _request,
    add_century,
    cancel_task,
    disband_legion,
    fleet_status,
    get_century,
    get_legion,
    get_legionary,
    get_task,
    hardware_status,
    list_agent_types,
    list_legionaries,
    list_legions,
    raise_legion,
    remove_century,
    scale_century,
    submit_batch,
    submit_task,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_response():
    """Create a mock httpx.Response that passes raise_for_status and returns JSON."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"ok": True}
    resp.raise_for_status.return_value = None
    return resp


@pytest.fixture
def patch_request(mock_response):
    """Patch httpx.request and return the mock for assertion."""
    with patch("centurion.mcp.tools.httpx.request", return_value=mock_response) as m:
        yield m


# ---------------------------------------------------------------------------
# Helper / internal function tests
# ---------------------------------------------------------------------------


class TestRequestHelper:
    """Tests for _request, _get, _post, _delete helpers."""

    def test_request_calls_httpx_with_correct_args(self, patch_request):
        result = _request("GET", "/some/path")
        patch_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/some/path",
            timeout=30,
        )
        assert result == {"ok": True}

    def test_request_with_custom_timeout(self, patch_request):
        _request("POST", "/path", timeout=60, json={"x": 1})
        patch_request.assert_called_once_with(
            "POST",
            f"{API_BASE}/path",
            timeout=60,
            json={"x": 1},
        )

    def test_get_delegates_to_request(self, patch_request):
        result = _get("/test", params={"a": "1"})
        patch_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/test",
            timeout=30,
            params={"a": "1"},
        )
        assert result == {"ok": True}

    def test_post_delegates_to_request(self, patch_request):
        result = _post("/test", json={"key": "val"})
        patch_request.assert_called_once_with(
            "POST",
            f"{API_BASE}/test",
            timeout=30,
            json={"key": "val"},
        )
        assert result == {"ok": True}

    def test_delete_delegates_to_request(self, patch_request):
        result = _delete("/test")
        patch_request.assert_called_once_with(
            "DELETE",
            f"{API_BASE}/test",
            timeout=30,
        )
        assert result == {"ok": True}


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for _request error handling (ConnectError, Timeout, HTTPStatusError)."""

    def test_connect_error_returns_error_dict(self):
        with patch("centurion.mcp.tools.httpx.request", side_effect=httpx.ConnectError("refused")):
            result = _request("GET", "/status")
        assert "error" in result
        assert "Cannot connect" in result["error"]
        assert API_BASE in result["error"]

    def test_timeout_exception_returns_error_dict(self):
        with patch("centurion.mcp.tools.httpx.request", side_effect=httpx.TimeoutException("timed out")):
            result = _request("GET", "/slow", timeout=5)
        assert "error" in result
        assert "timed out" in result["error"]
        assert "5s" in result["error"]

    def test_http_status_error_returns_error_dict(self):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_request = MagicMock(spec=httpx.Request)
        exc = httpx.HTTPStatusError("error", request=mock_request, response=mock_resp)

        with patch("centurion.mcp.tools.httpx.request", side_effect=exc):
            result = _request("GET", "/missing")
        assert "error" in result
        assert "404" in result["error"]
        assert "Not Found" in result["error"]

    def test_http_status_error_truncates_long_body(self):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 500
        mock_resp.text = "x" * 1000
        mock_request = MagicMock(spec=httpx.Request)
        exc = httpx.HTTPStatusError("error", request=mock_request, response=mock_resp)

        with patch("centurion.mcp.tools.httpx.request", side_effect=exc):
            result = _request("GET", "/fail")
        # The error message should truncate at 500 chars
        assert len(result["error"]) < 600


# ---------------------------------------------------------------------------
# Fleet tools
# ---------------------------------------------------------------------------


class TestFleetTools:
    def test_fleet_status(self, patch_request, mock_response):
        mock_response.json.return_value = {"legions": 2, "centuries": 5}
        result = fleet_status()
        patch_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/status",
            timeout=30,
            params=None,
        )
        assert result == {"legions": 2, "centuries": 5}

    def test_hardware_status(self, patch_request, mock_response):
        mock_response.json.return_value = {"cpu": "80%", "memory": "4GB"}
        result = hardware_status()
        patch_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/hardware",
            timeout=30,
            params=None,
        )
        assert result == {"cpu": "80%", "memory": "4GB"}


# ---------------------------------------------------------------------------
# Legion tools
# ---------------------------------------------------------------------------


class TestLegionTools:
    def test_raise_legion_minimal(self, patch_request):
        result = raise_legion(name="alpha")
        patch_request.assert_called_once_with(
            "POST",
            f"{API_BASE}/legions",
            timeout=30,
            json={"name": "alpha"},
        )
        assert result == {"ok": True}

    def test_raise_legion_with_legion_id(self, patch_request):
        raise_legion(name="beta", legion_id="leg-123")
        call_kwargs = patch_request.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["name"] == "beta"
        assert payload["legion_id"] == "leg-123"

    def test_raise_legion_with_quota(self, patch_request):
        quota = {"max_centuries": 5, "max_legionaries": 50}
        raise_legion(name="gamma", quota=quota)
        call_kwargs = patch_request.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["quota"] == quota

    def test_raise_legion_with_all_options(self, patch_request):
        quota = {"max_centuries": 10}
        raise_legion(name="delta", legion_id="leg-456", quota=quota)
        call_kwargs = patch_request.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload == {"name": "delta", "legion_id": "leg-456", "quota": quota}

    def test_raise_legion_omits_none_values(self, patch_request):
        raise_legion(name="epsilon")
        call_kwargs = patch_request.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "legion_id" not in payload
        assert "quota" not in payload

    def test_list_legions(self, patch_request, mock_response):
        mock_response.json.return_value = [{"id": "leg-1"}, {"id": "leg-2"}]
        result = list_legions()
        patch_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/legions",
            timeout=30,
            params=None,
        )
        assert len(result) == 2

    def test_get_legion(self, patch_request):
        get_legion("leg-abc")
        patch_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/legions/leg-abc",
            timeout=30,
            params=None,
        )

    def test_disband_legion(self, patch_request):
        disband_legion("leg-xyz")
        patch_request.assert_called_once_with(
            "DELETE",
            f"{API_BASE}/legions/leg-xyz",
            timeout=30,
        )


# ---------------------------------------------------------------------------
# Century tools
# ---------------------------------------------------------------------------


class TestCenturyTools:
    def test_add_century_minimal(self, patch_request):
        add_century(legion_id="leg-1")
        call_kwargs = patch_request.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload == {
            "agent_type": "claude_cli",
            "min_legionaries": 1,
            "max_legionaries": 10,
            "autoscale": True,
            "task_timeout": 300.0,
        }
        # Verify the URL includes the legion_id
        assert call_kwargs[0] == ("POST", f"{API_BASE}/legions/leg-1/centuries")

    def test_add_century_with_all_options(self, patch_request):
        config = {"model": "claude-opus-4-6"}
        add_century(
            legion_id="leg-2",
            agent_type="custom_agent",
            century_id="cent-99",
            agent_type_config=config,
            min_legionaries=3,
            max_legionaries=20,
            autoscale=False,
            task_timeout=600.0,
        )
        call_kwargs = patch_request.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["agent_type"] == "custom_agent"
        assert payload["century_id"] == "cent-99"
        assert payload["agent_type_config"] == config
        assert payload["min_legionaries"] == 3
        assert payload["max_legionaries"] == 20
        assert payload["autoscale"] is False
        assert payload["task_timeout"] == 600.0

    def test_add_century_omits_none_optional_fields(self, patch_request):
        add_century(legion_id="leg-3")
        call_kwargs = patch_request.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "century_id" not in payload
        assert "agent_type_config" not in payload

    def test_get_century(self, patch_request):
        get_century("cent-42")
        patch_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/centuries/cent-42",
            timeout=30,
            params=None,
        )

    def test_scale_century(self, patch_request):
        scale_century("cent-42", target_count=5)
        patch_request.assert_called_once_with(
            "POST",
            f"{API_BASE}/centuries/cent-42/scale",
            timeout=30,
            json={"target_count": 5},
        )

    def test_remove_century(self, patch_request):
        remove_century("cent-42")
        patch_request.assert_called_once_with(
            "DELETE",
            f"{API_BASE}/centuries/cent-42",
            timeout=30,
        )


# ---------------------------------------------------------------------------
# Task tools
# ---------------------------------------------------------------------------


class TestTaskTools:
    def test_submit_task_minimal(self, patch_request):
        submit_task(century_id="cent-1", prompt="Do work")
        call_kwargs = patch_request.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload == {"prompt": "Do work", "priority": 5}
        assert call_kwargs[0] == ("POST", f"{API_BASE}/centuries/cent-1/tasks")

    def test_submit_task_with_task_id(self, patch_request):
        submit_task(century_id="cent-1", prompt="Do work", task_id="task-abc")
        call_kwargs = patch_request.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["task_id"] == "task-abc"

    def test_submit_task_with_custom_priority(self, patch_request):
        submit_task(century_id="cent-1", prompt="Urgent", priority=1)
        call_kwargs = patch_request.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["priority"] == 1

    def test_submit_task_omits_none_task_id(self, patch_request):
        submit_task(century_id="cent-1", prompt="Work")
        call_kwargs = patch_request.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "task_id" not in payload

    def test_submit_batch(self, patch_request, mock_response):
        prompts = ["task1", "task2", "task3"]
        mock_response.json.return_value = [{"id": "t1"}, {"id": "t2"}, {"id": "t3"}]
        result = submit_batch(legion_id="leg-1", prompts=prompts)
        call_kwargs = patch_request.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload == {
            "prompts": prompts,
            "priority": 5,
            "distribute": "round_robin",
        }
        assert call_kwargs[0] == ("POST", f"{API_BASE}/legions/leg-1/tasks")
        assert len(result) == 3

    def test_submit_batch_with_custom_options(self, patch_request):
        submit_batch(
            legion_id="leg-2",
            prompts=["a", "b"],
            priority=1,
            distribute="least_loaded",
        )
        call_kwargs = patch_request.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["priority"] == 1
        assert payload["distribute"] == "least_loaded"

    def test_get_task(self, patch_request):
        get_task("task-xyz")
        patch_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/tasks/task-xyz",
            timeout=30,
            params=None,
        )

    def test_cancel_task(self, patch_request):
        cancel_task("task-xyz")
        patch_request.assert_called_once_with(
            "POST",
            f"{API_BASE}/tasks/task-xyz/cancel",
            timeout=30,
            json=None,
        )


# ---------------------------------------------------------------------------
# Legionary tools
# ---------------------------------------------------------------------------


class TestLegionaryTools:
    def test_list_legionaries(self, patch_request, mock_response):
        mock_response.json.return_value = [{"id": "leg-inst-1"}, {"id": "leg-inst-2"}]
        result = list_legionaries("cent-5")
        patch_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/centuries/cent-5/legionaries",
            timeout=30,
            params=None,
        )
        assert len(result) == 2

    def test_get_legionary(self, patch_request):
        get_legionary("lgn-42")
        patch_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/legionaries/lgn-42",
            timeout=30,
            params=None,
        )


# ---------------------------------------------------------------------------
# Agent type tools
# ---------------------------------------------------------------------------


class TestAgentTypeTools:
    def test_list_agent_types(self, patch_request, mock_response):
        mock_response.json.return_value = {"claude_cli": {"class": "ClaudeCLI"}}
        result = list_agent_types()
        patch_request.assert_called_once_with(
            "GET",
            f"{API_BASE}/agent-types",
            timeout=30,
            params=None,
        )
        assert "claude_cli" in result


# ---------------------------------------------------------------------------
# Parametrized tests for all GET-based tools (method and path)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_func, args, expected_method, expected_path_suffix",
    [
        (fleet_status, {}, "GET", "/status"),
        (hardware_status, {}, "GET", "/hardware"),
        (list_legions, {}, "GET", "/legions"),
        (get_legion, {"legion_id": "lg-1"}, "GET", "/legions/lg-1"),
        (get_century, {"century_id": "c-1"}, "GET", "/centuries/c-1"),
        (get_task, {"task_id": "t-1"}, "GET", "/tasks/t-1"),
        (list_legionaries, {"century_id": "c-1"}, "GET", "/centuries/c-1/legionaries"),
        (get_legionary, {"legionary_id": "l-1"}, "GET", "/legionaries/l-1"),
        (list_agent_types, {}, "GET", "/agent-types"),
    ],
    ids=[
        "fleet_status",
        "hardware_status",
        "list_legions",
        "get_legion",
        "get_century",
        "get_task",
        "list_legionaries",
        "get_legionary",
        "list_agent_types",
    ],
)
def test_get_tools_method_and_path(patch_request, tool_func, args, expected_method, expected_path_suffix):
    tool_func(**args)
    call_args = patch_request.call_args[0]
    assert call_args[0] == expected_method
    assert call_args[1] == f"{API_BASE}{expected_path_suffix}"


@pytest.mark.parametrize(
    "tool_func, args, expected_method, expected_path_suffix",
    [
        (disband_legion, {"legion_id": "lg-1"}, "DELETE", "/legions/lg-1"),
        (remove_century, {"century_id": "c-1"}, "DELETE", "/centuries/c-1"),
    ],
    ids=["disband_legion", "remove_century"],
)
def test_delete_tools_method_and_path(patch_request, tool_func, args, expected_method, expected_path_suffix):
    tool_func(**args)
    call_args = patch_request.call_args[0]
    assert call_args[0] == expected_method
    assert call_args[1] == f"{API_BASE}{expected_path_suffix}"


@pytest.mark.parametrize(
    "tool_func, args, expected_path_suffix",
    [
        (raise_legion, {"name": "test"}, "/legions"),
        (add_century, {"legion_id": "lg-1"}, "/legions/lg-1/centuries"),
        (scale_century, {"century_id": "c-1", "target_count": 3}, "/centuries/c-1/scale"),
        (submit_task, {"century_id": "c-1", "prompt": "go"}, "/centuries/c-1/tasks"),
        (submit_batch, {"legion_id": "lg-1", "prompts": ["a"]}, "/legions/lg-1/tasks"),
        (cancel_task, {"task_id": "t-1"}, "/tasks/t-1/cancel"),
    ],
    ids=[
        "raise_legion",
        "add_century",
        "scale_century",
        "submit_task",
        "submit_batch",
        "cancel_task",
    ],
)
def test_post_tools_method_and_path(patch_request, tool_func, args, expected_path_suffix):
    tool_func(**args)
    call_args = patch_request.call_args[0]
    assert call_args[0] == "POST"
    assert call_args[1] == f"{API_BASE}{expected_path_suffix}"


# ---------------------------------------------------------------------------
# Parametrized error handling across representative tools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_func, args",
    [
        (fleet_status, {}),
        (raise_legion, {"name": "x"}),
        (disband_legion, {"legion_id": "lg-1"}),
        (submit_task, {"century_id": "c-1", "prompt": "go"}),
    ],
    ids=["fleet_status", "raise_legion", "disband_legion", "submit_task"],
)
class TestErrorsAcrossTools:
    def test_connect_error(self, tool_func, args):
        with patch("centurion.mcp.tools.httpx.request", side_effect=httpx.ConnectError("refused")):
            result = tool_func(**args)
        assert "error" in result
        assert "Cannot connect" in result["error"]

    def test_timeout_error(self, tool_func, args):
        with patch("centurion.mcp.tools.httpx.request", side_effect=httpx.TimeoutException("timed out")):
            result = tool_func(**args)
        assert "error" in result
        assert "timed out" in result["error"]

    def test_http_status_error(self, tool_func, args):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"
        mock_req = MagicMock(spec=httpx.Request)
        exc = httpx.HTTPStatusError("error", request=mock_req, response=mock_resp)
        with patch("centurion.mcp.tools.httpx.request", side_effect=exc):
            result = tool_func(**args)
        assert "error" in result
        assert "503" in result["error"]


# ---------------------------------------------------------------------------
# API_BASE configuration
# ---------------------------------------------------------------------------


class TestApiBaseConfig:
    def test_default_api_base(self):
        assert API_BASE == "http://localhost:8100/api/centurion"

    def test_api_base_used_in_requests(self, patch_request):
        fleet_status()
        url = patch_request.call_args[0][1]
        assert url.startswith(API_BASE)
