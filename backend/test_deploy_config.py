"""render.yaml and the CI workflows must agree with the code and files they refer to (no YAML library needed)."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
RENDER = (ROOT / "render.yaml").read_text(encoding="utf-8")


def env_vars() -> dict[str, str]:
    pairs = re.findall(r"- key: (\w+)\s*\n\s*value: \"?([^\"\n]+)\"?", RENDER)
    return dict(pairs)


def test_every_limit_set_on_render_is_a_variable_the_api_really_reads():
    source = (BACKEND / "api.py").read_text(encoding="utf-8")
    read_by_api = set(re.findall(r'_env_int\("(\w+)"', source)) | {"CORS_ORIGINS"} | set(re.findall(r'os\.getenv\("(\w+)"', (BACKEND / "api_v2.py").read_text(encoding="utf-8")))
    for name in env_vars():
        if name.startswith(("MAX_", "BENCHMARK_", "CORS_", "CT_")):
            assert name in read_by_api, f"{name} is set in render.yaml but never read by the API"


def test_render_limits_are_positive_integers_and_tighter_than_the_local_defaults():
    import api

    values = env_vars()
    limits = {"MAX_UPLOAD_MB": api.MAX_UPLOAD_BYTES // (1024 * 1024), "MAX_IMAGE_PIXELS": api.MAX_IMAGE_PIXELS,
              "MAX_ADVANCED_PIXELS": api.MAX_ADVANCED_PIXELS, "MAX_CONCURRENT_JOBS": api.MAX_CONCURRENT_JOBS,
              "MAX_CT_FILES": api.MAX_CT_FILES, "MAX_CT_TOTAL_MB": api.MAX_CT_TOTAL_BYTES // (1024 * 1024)}
    for name, local_default in limits.items():
        assert name in values, f"{name} should be set for the small hosted instance"
        assert 0 < int(values[name]) <= local_default, name
    assert int(values["MAX_ADVANCED_PIXELS"]) <= int(values["MAX_IMAGE_PIXELS"])


def test_the_hosted_benchmark_run_exists_and_is_served_by_the_api(monkeypatch):
    import api_v2

    run = BACKEND / env_vars()["BENCHMARK_RUN_DIRS"]
    assert (run / "run_metadata.json").is_file()
    monkeypatch.chdir(BACKEND)                                         # Render starts the service inside rootDir
    monkeypatch.setenv("BENCHMARK_RUN_DIRS", env_vars()["BENCHMARK_RUN_DIRS"])
    assert list(api_v2.configured_runs()) == [run.name]


def test_the_api_service_points_at_files_that_exist():
    assert "rootDir: backend" in RENDER and "startCommand: uvicorn api:app" in RENDER
    assert (BACKEND / "requirements-api.txt").is_file() and "pip install -r requirements-api.txt" in RENDER
    assert "app = FastAPI(" in (BACKEND / "api.py").read_text(encoding="utf-8")
    assert "healthCheckPath: /api/health" in RENDER and '@app.get("/api/health")' in (BACKEND / "api.py").read_text(encoding="utf-8")


def test_the_api_requirements_cover_what_the_api_imports():
    manifest = (BACKEND / "requirements-api.txt").read_text(encoding="utf-8").lower()
    for package in ("fastapi", "uvicorn", "python-multipart", "numpy", "scipy", "pandas", "scikit-image", "pydicom", "pywavelets", "opencv-python-headless", "plotly", "pillow"):
        assert package in manifest, package
    assert "matplotlib" not in manifest and "streamlit" not in manifest and "vtk" not in manifest     # not needed by the hosted API


def test_the_static_site_installs_from_the_lockfile_with_a_node_version_the_frontend_accepts():
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert (ROOT / "frontend" / "package-lock.json").is_file() and "npm ci" in RENDER
    minimum_major = int(re.search(r">=(\d+)", package["engines"]["node"]).group(1))
    assert int(env_vars()["NODE_VERSION"]) >= minimum_major
    assert "staticPublishPath: frontend/dist" in RENDER and "VITE_API_BASE_URL" in RENDER


def test_the_workflows_use_the_same_node_version_and_the_tests_this_repository_has():
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    minimum_major = int(re.search(r">=(\d+)", package["engines"]["node"]).group(1))
    frontend = (ROOT / ".github" / "workflows" / "react-dashboard.yml").read_text(encoding="utf-8")
    assert int(re.search(r'node-version: "(\d+)"', frontend).group(1)) >= minimum_major
    for script in ("lint", "test", "build"):
        assert f"run: npm run {script}" in frontend and script in package["scripts"]
    backend = (ROOT / ".github" / "workflows" / "pytest.yml").read_text(encoding="utf-8")
    assert "working-directory: backend" in backend and "pytest" in backend and "ruff check" in backend
