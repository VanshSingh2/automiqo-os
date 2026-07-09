"""API-layer smoke tests: routes are registered and return expected shapes.

Individual routers are mounted on a throwaway FastAPI app so the heavy main.py
lifespan (schedulers, workers) never starts.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(router):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_health_endpoint():
    from backend.api.health import router
    r = _client(router).get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_modules_registry_lists_departments():
    from backend.api.business_modules_api import router
    r = _client(router).get("/modules/registry")
    assert r.status_code == 200
    body = r.json()
    keys = {d["key"] for d in body["departments"]}
    # CEO is not a toggleable department; real depts are present
    assert "ceo" not in keys
    assert {"coo", "cmo", "cro", "cfo", "cto"}.issubset(keys)
    assert "appointment_service" in body["profiles"]


def test_modules_get_uses_supabase(make_sb):
    from unittest.mock import patch
    from backend.api import business_modules_api
    sb = make_sb({"businesses": [{"config": {"industry": "med spa"}, "industry": "med spa"}]})
    with patch("backend.memory.supabase_client.get_supabase", return_value=sb):
        r = _client(business_modules_api.router).get("/modules/biz-1")
    assert r.status_code == 200
    assert "departments" in r.json()
