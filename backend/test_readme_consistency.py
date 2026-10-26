"""Facts the README states about the code must match the code (endpoints, scripts, environment variables, shipped run)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import api

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def registered_routes() -> set[tuple[str, str]]:
    """Every (method, path) the application serves, from its OpenAPI schema (it includes the nested v2 router)."""
    paths = api.app.openapi()["paths"]
    return {(method.upper(), re.sub(r"\{[^}]+\}", "{}", path)) for path, operations in paths.items() for method in operations}


def test_every_endpoint_in_the_readme_table_exists():
    table = README.split("### API", 1)[1].split("Example (from the repository root", 1)[0]
    mentioned = re.findall(r"`(GET|POST) (/api/[^`]*)`", table)
    mentioned += [("GET", path) for path in re.findall(r"`(/runs[^`]*|/api/samples/\{id\}/file)`", table)]
    assert len(mentioned) >= 9
    routes = registered_routes()
    for method, path in mentioned:
        normalised = re.sub(r"\{[^}]+\}", "{}", path if path.startswith("/api") else "/api/v2" + path)
        assert (method, normalised) in routes, f"{method} {path} is in the README but not in the API"


def test_the_readme_example_request_uses_real_fields_and_files():
    command = re.search(r"curl -X POST (\S+) \\\n\s+(.*)", README)
    assert command and command.group(1).endswith("/api/denoise")
    assert "file=@backend/samples/head_ct.png" in command.group(2)
    assert (ROOT / "backend" / "samples" / "head_ct.png").is_file()
    for field in re.findall(r"-F \"?(\w+)=", command.group(2)):
        assert field in {"file", "noise_type", "seed", "methods"}


def test_the_shipped_run_named_in_the_readme_exists_and_is_the_one_render_serves():
    names = set(re.findall(r"benchmark_v2_methods_\d{4}-\d{2}-\d{2}", README))
    assert names, "the README should name the shipped run"
    for name in names:
        assert (ROOT / "backend" / "docs" / "results" / name / "run_metadata.json").is_file()
        assert name in (ROOT / "render.yaml").read_text(encoding="utf-8")


def test_every_npm_script_the_docs_mention_exists():
    scripts = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["scripts"]
    texts = (README, (ROOT / "frontend" / "README.md").read_text(encoding="utf-8"), (ROOT / "backend" / "CONTRIBUTING.md").read_text(encoding="utf-8"))
    mentioned = {script for text in texts for script in re.findall(r"npm run (\w+)", text)}
    mentioned |= {"test" for text in texts if re.search(r"npm test", text)}
    assert {"dev", "build", "lint", "test", "e2e"} <= mentioned
    for script in mentioned:
        assert script in scripts, f"npm script {script!r} is documented but not defined"


def test_every_environment_variable_the_readme_names_is_read_by_the_code():
    source = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "backend").glob("api*.py"))
    for name in set(re.findall(r"`((?:MAX|BENCHMARK|CORS|CT)_[A-Z_]+)`", README)):
        assert name in source, f"{name} is documented but never read"


def test_every_bundled_sample_is_catalogued_and_has_a_provenance_entry():
    import sample_images

    samples = ROOT / "backend" / "samples"
    provenance = (samples / "README.md").read_text(encoding="utf-8")
    files = {path.name for path in samples.iterdir() if path.is_file() and path.name != "README.md"}
    assert files == {sample.filename for sample in sample_images.SAMPLES}
    for name in files:
        assert f"`{name}`" in provenance, f"{name} has no entry in backend/samples/README.md"
