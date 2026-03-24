"""Tests for Jetsam detection and handling."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from centurion.agent_types.base import AgentResult
from centurion.core.century import Century, CenturyConfig
from centurion.core.events import EventBus
from centurion.core.exceptions import AgentProcessError
from centurion.core.jetsam import JetsamTracker, confirm_jetsam_kill, is_sigkill
from centurion.core.legionary import Legionary, LegionaryStatus


# ---------------------------------------------------------------------------
# Unit tests: is_sigkill
# ---------------------------------------------------------------------------


class TestIsSigkill:
    def test_exit_code_neg9(self):
        assert is_sigkill(-9) is True

    def test_exit_code_137(self):
        assert is_sigkill(137) is True

    def test_exit_code_0(self):
        assert is_sigkill(0) is False

    def test_exit_code_1(self):
        assert is_sigkill(1) is False

    def test_exit_code_neg15(self):
        assert is_sigkill(-15) is False

    def test_exit_code_none(self):
        assert is_sigkill(None) is False


# ---------------------------------------------------------------------------
# Unit tests: confirm_jetsam_kill
# ---------------------------------------------------------------------------


class TestConfirmJetsamKill:
    @patch("centurion.core.jetsam.platform")
    def test_non_darwin_returns_false(self, mock_platform):
        mock_platform.system.return_value = "Linux"
        assert confirm_jetsam_kill() is False

    @patch("centurion.core.jetsam.platform")
    @patch("centurion.core.jetsam.subprocess")
    def test_jetsam_found_in_log(self, mock_subprocess, mock_platform):
        mock_platform.system.return_value = "Darwin"
        mock_result = type("Result", (), {"returncode": 0, "stdout": "2024-01-01 jetsam: killing pid 1234\n"})()
        mock_subprocess.run.return_value = mock_result
        assert confirm_jetsam_kill(pid=1234) is True

    @patch("centurion.core.jetsam.platform")
    @patch("centurion.core.jetsam.subprocess")
    def test_no_jetsam_in_log(self, mock_subprocess, mock_platform):
        mock_platform.system.return_value = "Darwin"
        mock_result = type("Result", (), {"returncode": 0, "stdout": "nothing relevant here\n"})()
        mock_subprocess.run.return_value = mock_result
        assert confirm_jetsam_kill() is False

    @patch("centurion.core.jetsam.platform")
    @patch("centurion.core.jetsam.subprocess")
    def test_log_command_fails(self, mock_subprocess, mock_platform):
        mock_platform.system.return_value = "Darwin"
        mock_result = type("Result", (), {"returncode": 1, "stdout": ""})()
        mock_subprocess.run.return_value = mock_result
        assert confirm_jetsam_kill() is False


# ---------------------------------------------------------------------------
# Unit tests: JetsamTracker
# ---------------------------------------------------------------------------


class TestJetsamTracker:
    def test_initial_state(self):
        tracker = JetsamTracker()
        assert tracker.kill_count == 0
        assert tracker.last_kill_details is None

    def test_record_kill(self):
        tracker = JetsamTracker()
        tracker.record_kill("leg-abc", exit_code=-9, confirmed=True)
        assert tracker.kill_count == 1
        details = tracker.last_kill_details
        assert details["legionary_id"] == "leg-abc"
        assert details["exit_code"] == -9
        assert details["confirmed_via_log"] is True

    def test_multiple_kills(self):
        tracker = JetsamTracker()
        tracker.record_kill("leg-1", exit_code=-9)
        tracker.record_kill("leg-2", exit_code=137)
        assert tracker.kill_count == 2
        assert tracker.last_kill_details["legionary_id"] == "leg-2"

    def test_to_dict(self):
        tracker = JetsamTracker()
        tracker.record_kill("leg-x", exit_code=-9, confirmed=False)
        d = tracker.to_dict()
        assert d["jetsam_kill_count"] == 1
        assert d["last_jetsam_kill"]["legionary_id"] == "leg-x"


# ---------------------------------------------------------------------------
# Integration: Legionary detects Jetsam kill
# ---------------------------------------------------------------------------


async def test_legionary_jetsam_detection(mock_agent_type):
    """When agent exits with SIGKILL and Jetsam is confirmed, failure_type is 'jetsam'."""
    leg = Legionary(agent_type=mock_agent_type, century_id="cent-test")
    leg.handle = await mock_agent_type.spawn(leg.id, "/tmp", {})

    mock_agent_type.send_task = AsyncMock(
        return_value=AgentResult(
            success=False,
            output="",
            error="Killed",
            exit_code=-9,
            duration_seconds=0.1,
        )
    )

    with patch("centurion.core.legionary.confirm_jetsam_kill", return_value=True):
        with pytest.raises(AgentProcessError) as exc_info:
            await leg.execute("task-jetsam", "This gets jetsam-killed", timeout=10.0)

    assert exc_info.value.jetsam is True
    assert exc_info.value.exit_code == -9
    assert exc_info.value.retryable is True


async def test_legionary_sigkill_no_jetsam(mock_agent_type):
    """When agent exits with SIGKILL but Jetsam is NOT confirmed, failure_type is 'sigkill_unknown'."""
    leg = Legionary(agent_type=mock_agent_type, century_id="cent-test")
    leg.handle = await mock_agent_type.spawn(leg.id, "/tmp", {})

    mock_agent_type.send_task = AsyncMock(
        return_value=AgentResult(
            success=False,
            output="",
            error="Killed",
            exit_code=-9,
            duration_seconds=0.1,
        )
    )

    with patch("centurion.core.legionary.confirm_jetsam_kill", return_value=False):
        with pytest.raises(AgentProcessError) as exc_info:
            await leg.execute("task-sigkill", "This gets killed", timeout=10.0)

    assert exc_info.value.jetsam is False
    assert exc_info.value.exit_code == -9


# ---------------------------------------------------------------------------
# Integration: Century handles Jetsam kill with event + respawn
# ---------------------------------------------------------------------------


async def test_century_jetsam_emits_event_and_respawns(mock_agent_type):
    """On Jetsam kill, Century emits jetsam_eviction event and replaces the legionary."""
    event_bus = EventBus()
    config = CenturyConfig(min_legionaries=1, max_legionaries=3, autoscale=False)
    century = Century("cent-jetsam", config, mock_agent_type, event_bus=event_bus)

    await century.muster(1)
    assert len(century.legionaries) == 1
    leg_id = list(century.legionaries.keys())[0]
    leg = century.legionaries[leg_id]

    # Make the agent return a SIGKILL result
    mock_agent_type.send_task = AsyncMock(
        return_value=AgentResult(
            success=False,
            output="",
            error="Killed by Jetsam",
            exit_code=-9,
            duration_seconds=0.1,
        )
    )

    # Subscribe to events before starting
    queue = event_bus.subscribe()

    # Start the century and submit a task
    with patch("centurion.core.legionary.confirm_jetsam_kill", return_value=True):
        await century.start()
        future = await century.submit_task("doomed task", task_id="task-doomed")

        # Wait for task to be processed
        try:
            await asyncio.wait_for(future, timeout=5.0)
        except (AgentProcessError, asyncio.TimeoutError):
            pass

        # Give worker loop time to emit event and respawn
        await asyncio.sleep(0.2)

    # Check that jetsam_eviction event was emitted
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    jetsam_events = [e for e in events if e.event_type == "jetsam_eviction"]
    assert len(jetsam_events) >= 1, f"Expected jetsam_eviction event, got: {[e.event_type for e in events]}"
    assert jetsam_events[0].payload["exit_code"] == -9
    assert jetsam_events[0].payload["century_id"] == "cent-jetsam"

    # Check tracker
    assert century.jetsam_tracker.kill_count >= 1

    await century.dismiss()


# ---------------------------------------------------------------------------
# Century status_report includes jetsam metrics
# ---------------------------------------------------------------------------


async def test_century_status_report_includes_jetsam(mock_agent_type):
    """status_report() includes jetsam tracker data."""
    config = CenturyConfig(min_legionaries=1, autoscale=False)
    century = Century("cent-report", config, mock_agent_type)
    await century.muster(1)

    report = century.status_report()
    assert "jetsam" in report
    assert report["jetsam"]["jetsam_kill_count"] == 0
    assert report["jetsam"]["last_jetsam_kill"] is None

    # Simulate a kill
    century.jetsam_tracker.record_kill("leg-test", exit_code=-9, confirmed=True)
    report = century.status_report()
    assert report["jetsam"]["jetsam_kill_count"] == 1

    await century.dismiss()
