"""render.yaml and the CI workflows must agree with the code and files they refer to (no YAML library needed)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
RENDER = (ROOT / "render.yaml").read_text(encoding="utf-8")


def env_vars() -> dict[str, str]:
    pairs = re.findall(r"- key: (\w+)\s*\n\s*value: \"?([^\"\n]+)\"?", RENDER)
    return dict(pairs)


def test_every_limit_set_on_render_is_a_variable_the_api_really_reads():
    source = (BACKEND / "api.py").read_text(encoding="utf-8")
    read_by_api = set(re.findall(r'_env_int\("(\w+)"', source)) | {"CORS_ORIGINS"}
    for module in ("api_v2.py", "api_3d.py"):
        read_by_api |= set(re.findall(r'os\.getenv\("(\w+)"', (BACKEND / module).read_text(encoding="utf-8")))
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


def test_the_hosted_benchmark_3d_runs_exist_and_are_served_by_the_api(monkeypatch):
    import api_3d

    entries = env_vars()["BENCHMARK_3D_RUN_DIRS"].split(":")                # Render runs on Linux, where several entries are separated by ':'
    assert len(entries) == 2 and len(set(entries)) == 2
    for entry in entries:
        assert (BACKEND / entry / "run_metadata.json").is_file(), entry
    monkeypatch.chdir(BACKEND)                                         # Render starts the service inside rootDir
    monkeypatch.setenv("BENCHMARK_3D_RUN_DIRS", os.pathsep.join(entries))
    assert list(api_3d.configured_runs()) == sorted(Path(e).name for e in entries)
    assert all(api_3d.integrity(path)["status"] == "verified" for path in api_3d.configured_runs().values())


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
    assert "working-directory: backend" in backend and "pytest" in backend
    assert "ruff check --config ruff.toml . ../scripts" in backend          # the deployment smoke test lives in scripts/ and is linted too
    assert "ruff check --config ruff.toml . ../scripts" in (ROOT / "backend" / "CONTRIBUTING.md").read_text(encoding="utf-8")


def test_the_render_addresses_of_the_two_services_refer_to_each_other():
    api_name = re.search(r"name: (biomedical-[\w-]*api)\b", RENDER).group(1)
    site_name = re.search(r"name: (biomedical-[\w-]*dashboard)\b", RENDER).group(1)
    assert env_vars()["VITE_API_BASE_URL"] == f"https://{api_name}.onrender.com"       # the page calls the API
    assert env_vars()["CORS_ORIGINS"] == f"https://{site_name}.onrender.com"           # and the API accepts that page


# --- .env.example files --------------------------------------------------------------------------------------------------------

def example_names(path: Path) -> set[str]:
    """Variables set in an example file, whether the line is active or a commented-out alternative."""
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", path.read_text(encoding="utf-8"), flags=re.M))


def variables_read_by_the_api() -> set[str]:
    names = {"CORS_ORIGINS"}
    for module in ("api.py", "api_v2.py", "api_3d.py"):
        source = (BACKEND / module).read_text(encoding="utf-8")
        names |= set(re.findall(r'(?:_env_int|os\.getenv)\("(\w+)"', source))
    return names


def test_the_backend_example_documents_exactly_the_variables_the_api_reads():
    assert example_names(BACKEND / ".env.example") == variables_read_by_the_api()


def test_the_backend_example_values_are_the_defaults_of_the_code():
    import api

    values = dict(re.findall(r"^([A-Z][A-Z0-9_]+)=(.*)$", (BACKEND / ".env.example").read_text(encoding="utf-8"), flags=re.M))
    assert int(values["MAX_UPLOAD_MB"]) * 1024 * 1024 == api.MAX_UPLOAD_BYTES
    assert int(values["MAX_IMAGE_PIXELS"]) == api.MAX_IMAGE_PIXELS and int(values["MAX_ADVANCED_PIXELS"]) == api.MAX_ADVANCED_PIXELS
    assert int(values["MAX_CONCURRENT_JOBS"]) == api.MAX_CONCURRENT_JOBS and int(values["MAX_CT_FILES"]) == api.MAX_CT_FILES
    assert int(values["MAX_CT_TOTAL_MB"]) * 1024 * 1024 == api.MAX_CT_TOTAL_BYTES


def test_the_run_directories_in_the_backend_example_exist_and_match_render(monkeypatch):
    import api_3d
    import api_v2

    text = (BACKEND / ".env.example").read_text(encoding="utf-8")
    v2 = re.search(r"^BENCHMARK_RUN_DIRS=(.+)$", text, flags=re.M).group(1)
    assert v2 == env_vars()["BENCHMARK_RUN_DIRS"]
    alternatives = re.findall(r"^# BENCHMARK_3D_RUN_DIRS=(.+)$", text, flags=re.M)
    assert len(alternatives) == 2                                            # the Windows form and the Linux form
    for value, separator in zip(alternatives, (";", ":")):
        assert value.replace(separator, ":") == env_vars()["BENCHMARK_3D_RUN_DIRS"]
    monkeypatch.setenv("BENCHMARK_RUN_DIRS", v2)
    assert list(api_v2.configured_runs())
    monkeypatch.setenv("BENCHMARK_3D_RUN_DIRS", alternatives[0 if os.pathsep == ";" else 1])
    assert len(api_3d.configured_runs()) == 2                                # the line for this system finds both runs


def test_the_frontend_example_sets_only_what_the_build_reads_from_a_dotenv_file():
    names = example_names(ROOT / "frontend" / ".env.example")
    assert names == {"VITE_API_BASE_URL"}
    assert "import.meta.env.VITE_API_BASE_URL" in (ROOT / "frontend" / "src" / "api.js").read_text(encoding="utf-8")
    assert "process.env.VITE_DEV_API_TARGET" in (ROOT / "frontend" / "vite.config.js").read_text(encoding="utf-8")


def test_the_example_files_are_not_ignored_by_git_but_real_env_files_are():
    import shutil
    import subprocess

    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("needs git and a checkout")

    def ignored(path: str) -> bool:
        return subprocess.run(["git", "check-ignore", "--quiet", path], cwd=ROOT, check=False).returncode == 0

    assert not ignored("backend/.env.example") and not ignored("frontend/.env.example")
    assert ignored("backend/.env") and ignored("frontend/.env") and ignored("frontend/.env.production")
