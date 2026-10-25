"""The Windows development helper (dev.cmd / scripts/dev.ps1) and the integrity of the repository's text files.

Several of these tests exist because of defects found while testing the helper: a regular-expression escape that had silently become a
control character, a pattern that missed the real Vite command line, and a first version that stopped processes merely because their
command line contained the words "uvicorn api:app" (it terminated unrelated shells).
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "dev.ps1"
TEXT_SUFFIXES = {".py", ".js", ".jsx", ".mjs", ".json", ".md", ".css", ".html", ".yml", ".yaml", ".toml", ".ps1", ".cmd", ".txt", ".ini"}
SKIPPED_DIRECTORIES = {"node_modules", ".git", ".venv", "dist", "data", "reports", "outputs", "__pycache__", ".pytest_cache", "test-results", ".claude", "results"}


def text_files():
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in TEXT_SUFFIXES and not (set(path.relative_to(ROOT).parts) & SKIPPED_DIRECTORIES) and path.name != "package-lock.json":
            yield path


def test_no_text_file_of_the_repository_contains_a_stray_control_character():
    """A '\\b' that turned into a backspace, or a '\\x00' into a NUL, changes what a script does without being visible."""
    offenders = {}
    for path in text_files():
        data = path.read_bytes()
        bad = [i for i, byte in enumerate(data) if byte < 32 and byte not in (9, 10, 13)]
        if bad:
            offenders[str(path.relative_to(ROOT))] = bad[:3]
    assert offenders == {}


def test_the_windows_scripts_contain_no_tab_character():
    """A '\\t' typed inside a path string becomes a tab (`data<TAB>cia`) and silently points at a folder that does not exist."""
    for path in (SCRIPT, ROOT / "dev.cmd"):
        assert b"\t" not in path.read_bytes(), path.name


def test_the_readme_documents_the_helper_the_way_it_is_actually_invoked():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    actions = re.search(r"ValidateSet\(([^)]*)\)", script).group(1)
    for action in re.findall(r"'(\w+)'", actions):
        assert f".\\dev.cmd {action}" in readme, action
    for switch in re.findall(r"\[switch\]\$(\w+)", script):
        assert f"-{switch}" in readme, switch
    code_lines = [line.strip() for block in re.findall(r"```bat\n(.*?)```", readme, re.S) for line in block.splitlines()]
    assert not [line for line in code_lines if re.match(r"dev\.cmd\b", line)]            # a bare `dev.cmd` is "not recognized" when the current folder is not searched
    assert "python -m uvicorn api:app --host 127.0.0.1 --port 8000" in code_lines          # the documented command is the one the helper runs
    started = script.replace("`", "").replace('"$python" ', "python ").replace("$apiPort", "8000").replace(' --app-dir "$backend"', "")    # --app-dir only names the folder
    assert "python -m uvicorn api:app --host 127.0.0.1 --port 8000" in started


def test_the_services_are_started_without_a_terminal_window_that_could_be_closed():
    """Each service used to get its own console window (a Windows Terminal window on many machines); closing it ended the service and the open
    page then said 'The dashboard server is not responding'. The services must run in a console without a window, with output in log files.
    Checked for real on Windows by starting from a console window, closing it and probing both services (see the README)."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "$info.CreateNoWindow = $true" in script and "$info.UseShellExecute = $false" in script
    assert not re.search(r"Start-Process[^\n]*cmd(\.exe)?'?\s+[^\n]*'?/k", script) and "cmd.exe /k" not in script       # no console window per service
    assert "Start-Detached $backend" in script and "Start-Detached $frontend" in script
    assert "logs\\dev" in script and "/logs/" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_the_helper_exists_and_is_reachable_from_the_repository_root():
    launcher = (ROOT / "dev.cmd").read_text(encoding="utf-8")
    assert "scripts\\dev.ps1" in launcher and "%*" in launcher and SCRIPT.is_file()


def test_the_helper_uses_the_same_ports_and_run_as_the_rest_of_the_project():
    script = SCRIPT.read_text(encoding="utf-8")
    vite = (ROOT / "frontend" / "vite.config.js").read_text(encoding="utf-8")
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "$apiPort = 8000" in script and "$webPort = 5173" in script
    assert "http://127.0.0.1:8000" in vite and "port: 5173" in vite
    run = re.search(r"\$runDir = '([^']+)'", script).group(1)
    assert (ROOT / "backend" / run / "run_metadata.json").is_file() and run in render
    assert "--host 127.0.0.1" in script                                     # the documented bind address


def test_the_process_patterns_match_the_real_command_lines_and_nothing_loose():
    """The regular expressions of the helper, tested against genuine command lines (taken from a real run on Windows)."""
    script = SCRIPT.read_text(encoding="utf-8")
    api_pattern = re.search(r"Test-ProjectApi.*?-match '([^']+)'\) \}", script, re.S).group(1)
    vite_pattern = re.search(r"Test-ProjectDashboard.*?-match '([^']+)'\) \}", script, re.S).group(1)
    window_pattern = re.search(r"-match '(title Denoising \(API\|dashboard\) &)'", script).group(1)
    real_vite = '"node"   "D:\\myprojects\\x\\frontend\\node_modules\\.bin\\\\..\\vite\\bin\\vite.js" --host 127.0.0.1'
    real_api = '"D:\\venvs\\python.exe"   -m uvicorn api:app --host 127.0.0.1 --port 8000 '
    assert re.search(vite_pattern, real_vite) and re.search(vite_pattern, real_vite.replace("\\", "/"))
    assert re.search(api_pattern, real_api)
    assert re.search(window_pattern, 'cmd.exe /k "title Denoising API & cd /d "D:\\x" & python')
    # looser text must not match: a tool whose command line merely mentions the words
    assert not re.search(vite_pattern, 'bash -c "npm run dev"') and not re.search(api_pattern, "bash -c npm run dev")
    assert not re.search(window_pattern, 'cmd.exe /k "title Something else & dir"')


@pytest.mark.skipif(sys.platform != "win32", reason="the helper is a Windows PowerShell script")
def test_stop_never_selects_an_unrelated_process_whose_command_line_mentions_uvicorn():
    decoy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", "8000"])
    try:
        time.sleep(1.0)
        result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "stop", "-DryRun"],
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        assert str(decoy.pid) not in result.stdout                          # a decoy that does not listen on the project's ports is never targeted
        assert decoy.poll() is None
    finally:
        decoy.kill()
        decoy.wait()


@pytest.mark.skipif(sys.platform != "win32", reason="the helper is a Windows PowerShell script")
def test_status_reports_the_python_it_will_use_and_fails_clearly_for_a_missing_one(monkeypatch):
    env = {**__import__("os").environ, "DENOISING_PYTHON": sys.executable}
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "status"], capture_output=True, text=True, timeout=120, env=env)
    assert f"Python used for the API: {sys.executable}" in result.stdout
    missing = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "status"], capture_output=True, text=True, timeout=120,
                             env={**env, "DENOISING_PYTHON": "C:\\does\\not\\exist\\python.exe"})
    assert missing.returncode == 1 and "DENOISING_PYTHON points to a file that does not exist" in missing.stdout
