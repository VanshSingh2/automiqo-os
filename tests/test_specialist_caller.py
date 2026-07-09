"""Tests for the specialist caller + agency-agents (submodule) integration."""
import os
import pytest

from agents.shared.specialist_caller import SpecialistCaller, SPECIALIST_REGISTRY

_LIB = os.path.join(os.path.dirname(__file__), "..", "specialist_library")
_HAS_LIB = os.path.isdir(_LIB) and os.listdir(_LIB)


def test_registry_entries_are_well_formed():
    assert len(SPECIALIST_REGISTRY) >= 20
    for key, info in SPECIALIST_REGISTRY.items():
        assert info["file"].endswith(".md"), key
        assert info["use_when"], key


def test_load_prompt_unknown_key_returns_none():
    assert SpecialistCaller()._load_prompt("no_such_specialist") is None


async def test_consult_unknown_specialist_is_graceful():
    out = await SpecialistCaller().consult("no_such_specialist", "do a thing")
    assert "not available" in out.lower()


def test_list_available_returns_all_registered():
    listed = SpecialistCaller().list_available()
    assert len(listed) == len(SPECIALIST_REGISTRY)
    assert all("key" in x and "available" in x for x in listed)


@pytest.mark.skipif(not _HAS_LIB, reason="specialist_library submodule not checked out")
def test_all_registered_specialist_files_exist():
    caller = SpecialistCaller()
    missing = [key for key in SPECIALIST_REGISTRY
               if caller._load_prompt(key) is None]
    assert missing == [], f"missing specialist files: {missing}"
