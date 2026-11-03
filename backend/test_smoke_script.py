"""scripts/smoke_test.py (the check to run against a deployed API and dashboard) must pass on the real application and must fail when something is wrong."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "backend" / "docs" / "results"
spec = importlib.util.spec_from_file_location("smoke_test", ROOT / "scripts" / "smoke_test.py")
smoke = importlib.util.module_from_spec(spec)
sys.modules["smoke_test"] = smoke                                       # the dataclass decorator looks its module up by name
spec.loader.exec_module(smoke)


def sender(client: TestClient):
    def send(method, target, headers=None, body=None):
        response = client.request(method, target, headers=headers, content=body)
        return response.status_code, {k.lower(): v for k, v in response.headers.items()}, response.content
    return send


@pytest.fixture()
def shipped_runs(monkeypatch):
    monkeypatch.setenv("BENCHMARK_RUN_DIRS", str(RESULTS / "benchmark_v2_methods_2026-10-25"))
    monkeypatch.setenv("BENCHMARK_3D_RUN_DIRS", os.pathsep.join(str(RESULTS / name) for name in ("benchmark_3d_2026-10-26", "benchmark_3d_correlated_2026-10-27")))


def levels(results):
    return {r.name: r.level for r in results}


def test_every_check_passes_on_the_real_application_with_the_shipped_runs(shipped_runs):
    results = smoke.check_api(sender(TestClient(api.app)), do_denoise=True)
    failed = [(r.name, r.detail) for r in results if r.level == "FAIL"]
    assert failed == []
    names = levels(results)
    assert names["GET /api/health"] == "PASS" and names["Benchmark V2 runs"] == "PASS" and names["Benchmark 3D runs"] == "PASS"
    assert names["POST /api/denoise (mean, Gaussian noise, seed 7)"] == "PASS"
    assert "2 run(s)" in next(r.detail for r in results if r.name == "Benchmark 3D runs")        # the independent and the correlated run
    assert "1 run(s)" in next(r.detail for r in results if r.name == "Benchmark V2 runs")


def test_runs_that_are_not_configured_are_a_warning_not_a_failure(monkeypatch):
    monkeypatch.delenv("BENCHMARK_RUN_DIRS", raising=False)
    monkeypatch.delenv("BENCHMARK_3D_RUN_DIRS", raising=False)
    results = smoke.check_api(sender(TestClient(api.app)), do_denoise=False)
    assert levels(results)["Benchmark V2 runs"] == "WARN" and levels(results)["Benchmark 3D runs"] == "WARN"
    assert all(r.level != "FAIL" for r in results)
    assert "POST /api/denoise (mean, Gaussian noise, seed 7)" not in levels(results)           # --no-denoise sends nothing to the denoising endpoint


def test_a_recorded_file_that_was_altered_is_reported_as_a_failure(tmp_path, monkeypatch):
    import shutil

    run = tmp_path / "benchmark_3d_2026-10-26"
    shutil.copytree(RESULTS / "benchmark_3d_2026-10-26", run)
    (run / "test_summary.csv").write_bytes((run / "test_summary.csv").read_bytes() + b"\n")
    monkeypatch.setenv("BENCHMARK_3D_RUN_DIRS", str(run))
    monkeypatch.delenv("BENCHMARK_RUN_DIRS", raising=False)
    results = smoke.check_api(sender(TestClient(api.app)), do_denoise=False)
    assert levels(results)["Benchmark 3D runs"] == "FAIL"


def test_an_api_that_does_not_answer_stops_the_run_with_one_clear_failure():
    def down(method, target, headers=None, body=None):
        return 502, {}, b"Bad gateway"
    results = smoke.check_api(down, do_denoise=True)
    assert [(r.level, r.name) for r in results] == [("FAIL", "GET /api/health")]


def test_the_exit_status_follows_the_failures(monkeypatch, capsys):
    monkeypatch.setattr(smoke, "http_request", lambda base, timeout: sender(TestClient(api.app)))
    monkeypatch.delenv("BENCHMARK_RUN_DIRS", raising=False)
    monkeypatch.delenv("BENCHMARK_3D_RUN_DIRS", raising=False)
    assert smoke.main(["--api", "http://testserver", "--no-denoise"]) == 0
    assert "failed" in capsys.readouterr().out
    monkeypatch.setattr(smoke, "http_request", lambda base, timeout: (lambda *a, **k: (500, {}, b"")))
    assert smoke.main(["--api", "http://testserver", "--no-denoise"]) == 1


# --- dashboard checks -------------------------------------------------------------------------------------------------------------

API = "https://api.example.org"
SITE = "https://dashboard.example.org"
PAGE = b'<html><body><div id="root"></div><script type="module" src="/assets/index-abc.js"></script></body></html>'


def fake_site(bundle: bytes, page: bytes = PAGE, status: int = 200):
    def send(method, target, headers=None, body=None):
        return (status, {}, page) if target == "/" else (200, {}, bundle)
    return send


def fake_api(allowed: str | None, foreign: str | None = None):
    def send(method, target, headers=None, body=None):
        origin = (headers or {}).get("Origin")
        value = allowed if origin == SITE else foreign
        return 200, ({"access-control-allow-origin": value} if value else {}), b"{}"
    return send


def test_a_correctly_configured_dashboard_passes():
    results = smoke.check_site(fake_api(SITE), fake_site(b"fetch('" + API.encode() + b"/api/health')"), API, SITE)
    assert [(r.level, r.name) for r in results] == [("PASS", "CORS allows the dashboard's origin"), ("PASS", "CORS refuses an unrelated origin"),
                                                    ("PASS", "dashboard page"), ("PASS", "dashboard build points at the API")]


def test_a_missing_cors_entry_is_reported_with_the_remedy():
    results = smoke.check_site(fake_api(None), fake_site(API.encode()), API, SITE)
    cors = next(r for r in results if r.name.startswith("CORS allows"))
    assert cors.level == "FAIL" and "CORS_ORIGINS" in cors.detail


@pytest.mark.parametrize("foreign", ["*", smoke.FOREIGN_ORIGIN])
def test_an_api_that_answers_every_origin_fails(foreign):
    results = smoke.check_site(fake_api(SITE, foreign), fake_site(API.encode()), API, SITE)
    assert next(r for r in results if r.name == "CORS refuses an unrelated origin").level == "FAIL"


def test_a_build_without_the_api_address_fails_with_the_remedy():
    results = smoke.check_site(fake_api(SITE), fake_site(b"fetch('/api/health')"), API, SITE)
    build = next(r for r in results if r.name == "dashboard build points at the API")
    assert build.level == "FAIL" and "VITE_API_BASE_URL" in build.detail


def test_a_page_that_is_not_the_application_fails():
    results = smoke.check_site(fake_api(SITE), fake_site(b"", page=b"<html>Not found</html>", status=404), API, SITE)
    assert results[-1].level == "FAIL" and results[-1].name == "dashboard page"


def test_the_same_origin_needs_no_cors_and_no_baked_address():
    results = smoke.check_site(fake_api(None), fake_site(b"fetch('/api/health')"), API, API)
    assert [(r.level, r.name) for r in results] == [("PASS", "CORS"), ("PASS", "dashboard page")]
