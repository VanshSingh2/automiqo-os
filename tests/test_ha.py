"""Tests for the HA layer: role selection + cluster-wide run_once locking."""
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ha import leader


# ── role() ──────────────────────────────────────────────────────────────────
def test_role_defaults_to_all(monkeypatch):
    monkeypatch.delenv("ROLE", raising=False)
    assert leader.role() == "all"


def test_role_reads_env(monkeypatch):
    for r in ("web", "worker", "scheduler", "all"):
        monkeypatch.setenv("ROLE", r)
        assert leader.role() == r


def test_role_unknown_falls_back_to_all(monkeypatch):
    monkeypatch.setenv("ROLE", "banana")
    assert leader.role() == "all"


# ── run_once() ───────────────────────────────────────────────────────────────
async def test_run_once_true_when_lock_acquired():
    r = MagicMock()
    r.set = AsyncMock(return_value=True)  # SET NX succeeded
    with patch("backend.dispatcher.queue.get_redis", new=AsyncMock(return_value=r)):
        got = await leader.run_once("dept:coo:2026-07-09", ttl_seconds=60)
    assert got is True
    # Called with nx=True and an expiry.
    _, kwargs = r.set.call_args
    assert kwargs.get("nx") is True
    assert kwargs.get("ex") == 60


async def test_run_once_false_when_already_claimed():
    r = MagicMock()
    r.set = AsyncMock(return_value=None)  # SET NX returns None when key exists
    with patch("backend.dispatcher.queue.get_redis", new=AsyncMock(return_value=r)):
        got = await leader.run_once("dept:coo:2026-07-09")
    assert got is False


async def test_run_once_fails_open_on_redis_error():
    # If Redis is unavailable, run_once must fail OPEN (return True) so a single
    # node still does its work; idempotency guards against rare duplicates.
    with patch("backend.dispatcher.queue.get_redis", new=AsyncMock(side_effect=RuntimeError("redis down"))):
        got = await leader.run_once("urgent:123")
    assert got is True


def test_node_id_is_short_hex():
    assert isinstance(leader.NODE_ID, str) and len(leader.NODE_ID) == 12
    int(leader.NODE_ID, 16)  # valid hex
