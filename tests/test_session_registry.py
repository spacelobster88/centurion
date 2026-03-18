"""Tests for SessionRegistry — parent-child session relationship tracking."""

from __future__ import annotations

import time

import pytest

from centurion.core.session_registry import SessionMeta, SessionRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry() -> SessionRegistry:
    return SessionRegistry()


# ---------------------------------------------------------------------------
# register_session
# ---------------------------------------------------------------------------

class TestRegisterSession:
    def test_register_basic(self):
        reg = _make_registry()
        reg.register_session("s1", parent_id=None, session_type="interactive")
        meta = reg.get_session_meta("s1")
        assert meta is not None
        assert meta.session_type == "interactive"
        assert meta.status == "active"
        assert meta.pinned is False

    def test_register_with_parent(self):
        reg = _make_registry()
        reg.register_session("parent", parent_id=None, session_type="interactive")
        reg.register_session("child", parent_id="parent", session_type="background")
        assert reg.get_parent("child") == "parent"
        assert "child" in reg.get_children("parent")

    def test_register_duplicate_raises(self):
        reg = _make_registry()
        reg.register_session("s1", parent_id=None, session_type="interactive")
        with pytest.raises(ValueError, match="already registered"):
            reg.register_session("s1", parent_id=None, session_type="interactive")

    def test_register_with_pinned(self):
        reg = _make_registry()
        reg.register_session("s1", parent_id=None, session_type="background", pinned=True)
        assert reg.get_session_meta("s1").pinned is True


# ---------------------------------------------------------------------------
# register_child (convenience method)
# ---------------------------------------------------------------------------

class TestRegisterChild:
    def test_register_child_creates_relationship(self):
        reg = _make_registry()
        reg.register_session("parent", parent_id=None, session_type="interactive")
        reg.register_session("child", parent_id=None, session_type="background")
        reg.register_child("parent", "child")
        assert reg.get_parent("child") == "parent"
        assert "child" in reg.get_children("parent")

    def test_register_child_unknown_parent_raises(self):
        reg = _make_registry()
        reg.register_session("child", parent_id=None, session_type="background")
        with pytest.raises(ValueError, match="not registered"):
            reg.register_child("unknown", "child")

    def test_register_child_unknown_child_raises(self):
        reg = _make_registry()
        reg.register_session("parent", parent_id=None, session_type="interactive")
        with pytest.raises(ValueError, match="not registered"):
            reg.register_child("parent", "unknown")


# ---------------------------------------------------------------------------
# get_children / get_parent
# ---------------------------------------------------------------------------

class TestGetChildrenParent:
    def test_get_children_empty(self):
        reg = _make_registry()
        reg.register_session("s1", parent_id=None, session_type="interactive")
        assert reg.get_children("s1") == []

    def test_get_children_multiple(self):
        reg = _make_registry()
        reg.register_session("p", parent_id=None, session_type="interactive")
        reg.register_session("c1", parent_id="p", session_type="background")
        reg.register_session("c2", parent_id="p", session_type="background")
        children = reg.get_children("p")
        assert sorted(children) == ["c1", "c2"]

    def test_get_parent_none(self):
        reg = _make_registry()
        reg.register_session("s1", parent_id=None, session_type="interactive")
        assert reg.get_parent("s1") is None

    def test_get_parent_unknown_session(self):
        reg = _make_registry()
        assert reg.get_parent("nonexistent") is None

    def test_get_children_unknown_session(self):
        reg = _make_registry()
        assert reg.get_children("nonexistent") == []


# ---------------------------------------------------------------------------
# is_orphan
# ---------------------------------------------------------------------------

class TestIsOrphan:
    def test_not_orphan_with_live_parent(self):
        reg = _make_registry()
        reg.register_session("p", parent_id=None, session_type="interactive")
        reg.register_session("c", parent_id="p", session_type="background")
        assert reg.is_orphan("c") is False

    def test_orphan_after_parent_terminated(self):
        reg = _make_registry()
        reg.register_session("p", parent_id=None, session_type="interactive")
        reg.register_session("c", parent_id="p", session_type="background")
        reg.terminate_session("p")
        assert reg.is_orphan("c") is True

    def test_root_session_not_orphan(self):
        """A session with no parent is not an orphan."""
        reg = _make_registry()
        reg.register_session("s1", parent_id=None, session_type="interactive")
        assert reg.is_orphan("s1") is False

    def test_orphan_after_parent_unregistered(self):
        reg = _make_registry()
        reg.register_session("p", parent_id=None, session_type="interactive")
        reg.register_session("c", parent_id="p", session_type="background")
        reg.unregister_session("p")
        assert reg.is_orphan("c") is True

    def test_unknown_session_not_orphan(self):
        reg = _make_registry()
        assert reg.is_orphan("nonexistent") is False


# ---------------------------------------------------------------------------
# unregister_session
# ---------------------------------------------------------------------------

class TestUnregisterSession:
    def test_unregister_removes_meta(self):
        reg = _make_registry()
        reg.register_session("s1", parent_id=None, session_type="interactive")
        reg.unregister_session("s1")
        assert reg.get_session_meta("s1") is None

    def test_unregister_cleans_parent_link(self):
        reg = _make_registry()
        reg.register_session("p", parent_id=None, session_type="interactive")
        reg.register_session("c", parent_id="p", session_type="background")
        reg.unregister_session("c")
        assert reg.get_children("p") == []

    def test_unregister_idempotent(self):
        reg = _make_registry()
        reg.unregister_session("nonexistent")  # should not raise

    def test_unregister_parent_orphans_children(self):
        reg = _make_registry()
        reg.register_session("p", parent_id=None, session_type="interactive")
        reg.register_session("c", parent_id="p", session_type="background")
        reg.unregister_session("p")
        # Child still exists but parent is gone
        assert reg.get_session_meta("c") is not None
        assert reg.is_orphan("c") is True


# ---------------------------------------------------------------------------
# terminate_session
# ---------------------------------------------------------------------------

class TestTerminateSession:
    def test_terminate_sets_status(self):
        reg = _make_registry()
        reg.register_session("s1", parent_id=None, session_type="interactive")
        reg.terminate_session("s1")
        meta = reg.get_session_meta("s1")
        assert meta.status == "terminated"

    def test_terminate_unknown_raises(self):
        reg = _make_registry()
        with pytest.raises(ValueError, match="not registered"):
            reg.terminate_session("nonexistent")


# ---------------------------------------------------------------------------
# update_last_active
# ---------------------------------------------------------------------------

class TestUpdateLastActive:
    def test_updates_timestamp(self):
        reg = _make_registry()
        reg.register_session("s1", parent_id=None, session_type="interactive")
        old_ts = reg.get_session_meta("s1").last_active
        time.sleep(0.01)
        reg.update_last_active("s1")
        new_ts = reg.get_session_meta("s1").last_active
        assert new_ts > old_ts

    def test_update_unknown_raises(self):
        reg = _make_registry()
        with pytest.raises(ValueError, match="not registered"):
            reg.update_last_active("nonexistent")


# ---------------------------------------------------------------------------
# get_all_sessions
# ---------------------------------------------------------------------------

class TestGetAllSessions:
    def test_empty(self):
        reg = _make_registry()
        assert reg.get_all_sessions() == {}

    def test_returns_all(self):
        reg = _make_registry()
        reg.register_session("s1", parent_id=None, session_type="interactive")
        reg.register_session("s2", parent_id=None, session_type="background")
        all_sessions = reg.get_all_sessions()
        assert set(all_sessions.keys()) == {"s1", "s2"}

    def test_excludes_unregistered(self):
        reg = _make_registry()
        reg.register_session("s1", parent_id=None, session_type="interactive")
        reg.register_session("s2", parent_id=None, session_type="background")
        reg.unregister_session("s1")
        assert set(reg.get_all_sessions().keys()) == {"s2"}


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# closeable_info
# ---------------------------------------------------------------------------

class TestCloseableInfo:
    def test_no_children_is_closeable(self):
        """Session with no children should be closeable."""
        reg = _make_registry()
        reg.register_session("s1", parent_id=None, session_type="interactive")
        info = reg.closeable_info("s1")
        assert info["has_bg_children"] is False
        assert info["bg_child_ids"] == []
        assert info["closeable"] is True
        assert "no active background children" in info["reason"]

    def test_active_bg_children_not_closeable(self):
        """Session with active background children should NOT be closeable."""
        reg = _make_registry()
        reg.register_session("p", parent_id=None, session_type="interactive")
        reg.register_session("c1", parent_id="p", session_type="background")
        reg.register_session("c2", parent_id="p", session_type="background")
        info = reg.closeable_info("p")
        assert info["has_bg_children"] is True
        assert sorted(info["bg_child_ids"]) == ["c1", "c2"]
        assert info["closeable"] is False
        assert "has active background children" in info["reason"]

    def test_terminated_children_are_closeable(self):
        """Session whose background children are all terminated should be closeable."""
        reg = _make_registry()
        reg.register_session("p", parent_id=None, session_type="interactive")
        reg.register_session("c1", parent_id="p", session_type="background")
        reg.terminate_session("c1")
        info = reg.closeable_info("p")
        assert info["has_bg_children"] is False
        assert info["bg_child_ids"] == []
        assert info["closeable"] is True

    def test_pinned_session_never_closeable(self):
        """Pinned sessions are never closeable, even with no children."""
        reg = _make_registry()
        reg.register_session("s1", parent_id=None, session_type="interactive", pinned=True)
        info = reg.closeable_info("s1")
        assert info["closeable"] is False
        assert "pinned" in info["reason"]

    def test_pinned_with_active_children(self):
        """Pinned session with active children: not closeable, reason mentions pinned."""
        reg = _make_registry()
        reg.register_session("p", parent_id=None, session_type="interactive", pinned=True)
        reg.register_session("c1", parent_id="p", session_type="background")
        info = reg.closeable_info("p")
        assert info["closeable"] is False
        assert "pinned" in info["reason"]

    def test_mix_active_and_terminated_children(self):
        """One active, one terminated child — still not closeable."""
        reg = _make_registry()
        reg.register_session("p", parent_id=None, session_type="interactive")
        reg.register_session("c1", parent_id="p", session_type="background")
        reg.register_session("c2", parent_id="p", session_type="background")
        reg.terminate_session("c1")
        info = reg.closeable_info("p")
        assert info["has_bg_children"] is True
        assert info["bg_child_ids"] == ["c2"]
        assert info["closeable"] is False

    def test_unknown_session_returns_defaults(self):
        """Unknown session returns closeable with empty children."""
        reg = _make_registry()
        info = reg.closeable_info("nonexistent")
        assert info["has_bg_children"] is False
        assert info["bg_child_ids"] == []
        assert info["closeable"] is True
        assert "no active background children" in info["reason"]

    def test_unregistered_children_not_counted(self):
        """Children that were unregistered should not count as active."""
        reg = _make_registry()
        reg.register_session("p", parent_id=None, session_type="interactive")
        reg.register_session("c1", parent_id="p", session_type="background")
        reg.unregister_session("c1")
        info = reg.closeable_info("p")
        assert info["has_bg_children"] is False
        assert info["closeable"] is True


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Deep nesting & relationship cascades
# ---------------------------------------------------------------------------

class TestDeepNesting:
    def test_grandchildren(self):
        """Three-level nesting: parent -> child -> grandchild."""
        reg = _make_registry()
        reg.register_session("root", parent_id=None, session_type="interactive")
        reg.register_session("child", parent_id="root", session_type="background")
        reg.register_session("grandchild", parent_id="child", session_type="background")
        assert reg.get_parent("grandchild") == "child"
        assert reg.get_parent("child") == "root"
        assert "grandchild" in reg.get_children("child")
        assert "child" in reg.get_children("root")
        # grandchild is NOT a direct child of root
        assert "grandchild" not in reg.get_children("root")

    def test_grandchild_orphaned_when_parent_terminated(self):
        """Terminating intermediate parent orphans grandchild."""
        reg = _make_registry()
        reg.register_session("root", parent_id=None, session_type="interactive")
        reg.register_session("child", parent_id="root", session_type="background")
        reg.register_session("grandchild", parent_id="child", session_type="background")
        reg.terminate_session("child")
        assert reg.is_orphan("grandchild") is True
        # child itself is also orphaned only if root dies, not yet
        assert reg.is_orphan("child") is False

    def test_terminate_parent_makes_closeable_info_update(self):
        """After terminating the only child, parent becomes closeable."""
        reg = _make_registry()
        reg.register_session("p", parent_id=None, session_type="interactive")
        reg.register_session("c", parent_id="p", session_type="background")
        # Before: not closeable
        assert reg.closeable_info("p")["closeable"] is False
        reg.terminate_session("c")
        # After: closeable
        info = reg.closeable_info("p")
        assert info["closeable"] is True
        assert info["bg_child_ids"] == []

    def test_interactive_children_not_counted_as_bg(self):
        """closeable_info counts ALL active children, not just background type.

        Note: closeable_info checks child status==active, regardless of type.
        An interactive child that is active still blocks closeability.
        """
        reg = _make_registry()
        reg.register_session("p", parent_id=None, session_type="interactive")
        reg.register_session("ic", parent_id="p", session_type="interactive")
        info = reg.closeable_info("p")
        # The implementation counts any active child (bg_child_ids is named for
        # bg but actually includes all active children in sorted children set)
        assert "ic" in info["bg_child_ids"]
        assert info["closeable"] is False

    def test_closeable_info_after_unregister_child(self):
        """Unregistering a child makes the parent closeable."""
        reg = _make_registry()
        reg.register_session("p", parent_id=None, session_type="interactive")
        reg.register_session("c1", parent_id="p", session_type="background")
        reg.register_session("c2", parent_id="p", session_type="background")
        reg.unregister_session("c1")
        info = reg.closeable_info("p")
        assert info["bg_child_ids"] == ["c2"]
        assert info["closeable"] is False
        reg.unregister_session("c2")
        info = reg.closeable_info("p")
        assert info["closeable"] is True

    def test_terminated_session_not_in_get_all_after_unregister(self):
        """Unregistered sessions should not appear in get_all_sessions."""
        reg = _make_registry()
        reg.register_session("s1", parent_id=None, session_type="interactive")
        reg.terminate_session("s1")
        assert "s1" in reg.get_all_sessions()
        reg.unregister_session("s1")
        assert "s1" not in reg.get_all_sessions()

    def test_register_child_overrides_parent(self):
        """register_child should update the parent link of a session."""
        reg = _make_registry()
        reg.register_session("p1", parent_id=None, session_type="interactive")
        reg.register_session("p2", parent_id=None, session_type="interactive")
        reg.register_session("c", parent_id="p1", session_type="background")
        assert reg.get_parent("c") == "p1"
        reg.register_child("p2", "c")
        assert reg.get_parent("c") == "p2"
        assert "c" in reg.get_children("p2")
        # Note: register_child doesn't remove from old parent, so both have it
        assert "c" in reg.get_children("p1")

    def test_closeable_info_pinned_overrides_children_check(self):
        """Pinned takes priority: even with no children, pinned is not closeable."""
        reg = _make_registry()
        reg.register_session("p", parent_id=None, session_type="background", pinned=True)
        info = reg.closeable_info("p")
        assert info["closeable"] is False
        assert info["has_bg_children"] is False
        assert "pinned" in info["reason"]


class TestThreadSafety:
    def test_concurrent_register(self):
        """Verify no crash under concurrent access."""
        import threading

        reg = _make_registry()
        errors = []

        def register_batch(start: int):
            try:
                for i in range(start, start + 50):
                    reg.register_session(f"s{i}", parent_id=None, session_type="interactive")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register_batch, args=(i * 50,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(reg.get_all_sessions()) == 200
