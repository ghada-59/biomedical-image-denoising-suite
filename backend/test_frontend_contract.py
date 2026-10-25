"""The frontend tests mock the API with fixtures; this test keeps those fixtures equal to what the backend really serves."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import api

FIXTURE = Path(__file__).resolve().parent.parent / "frontend" / "src" / "test" / "fixtures" / "api_contract.json"
REGENERATE = (
    "Regenerate with (from backend/): python -c \"import json; from fastapi.testclient import TestClient; import api; "
    "c = TestClient(api.app); open('../frontend/src/test/fixtures/api_contract.json', 'w', newline='\\n').write(json.dumps("
    "{'methods': c.get('/api/methods').json(), 'samples': c.get('/api/samples').json()}, indent=2, sort_keys=True) + '\\n')\""
)


def test_the_frontend_fixtures_equal_the_live_method_and_sample_catalogues():
    live = TestClient(api.app)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["methods"] == live.get("/api/methods").json(), REGENERATE
    assert fixture["samples"] == live.get("/api/samples").json(), REGENERATE
