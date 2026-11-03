"""Smoke test for a running API and, optionally, the dashboard that talks to it (local or deployed).

    python scripts/smoke_test.py --api https://your-api.example [--site https://your-dashboard.example] [--no-denoise]

Standard library only. It reads the API's public endpoints and, unless --no-denoise is given, sends one bundled sample image
(the API's own `chest_ct` sample, downloaded from the same API) to /api/denoise with the cheapest method. It sends nothing else:
no uploads from your disk, no credentials. Exit status 0 when no check failed (warnings do not fail the run), 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
LOCAL_PATH = re.compile(r"[A-Za-z]:\\|/home/|/Users/|/opt/|/app/|/var/|Traceback")
FOREIGN_ORIGIN = "https://smoke-test-unrelated-origin.invalid"

# request(method, url_path_or_url, headers, body) -> (status, headers with lower-case names, body bytes)
Request = Callable[[str, str, dict | None, bytes | None], tuple[int, dict, bytes]]


@dataclass
class Result:
    level: str          # PASS, WARN or FAIL
    name: str
    detail: str = ""


def http_request(base: str, timeout: float) -> Request:
    def send(method: str, target: str, headers: dict | None = None, body: bytes | None = None):
        url = target if target.startswith("http") else base.rstrip("/") + target
        request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:                      # noqa: S310 (the URL is the one the user passed)
                return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
        except urllib.error.HTTPError as error:
            return error.code, {k.lower(): v for k, v in error.headers.items()}, error.read()
    return send


def multipart(fields: dict[str, str], file_field: str, filename: str, payload: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode() for key, value in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode()
                 + payload + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _json(body: bytes):
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def origin_of(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def check_api(send: Request, do_denoise: bool) -> list[Result]:
    results: list[Result] = []

    def record(level: str, name: str, detail: str = "") -> None:
        results.append(Result(level, name, detail))

    status, _, body = send("GET", "/api/health", None, None)
    health = _json(body)
    if status == 200 and isinstance(health, dict) and health.get("status") == "ok":
        record("PASS", "GET /api/health", f"version {health.get('version')}")
        if health.get("unavailable_methods"):
            record("WARN", "optional methods unavailable", "; ".join(health.get("problems", [])))
    else:
        record("FAIL", "GET /api/health", f"HTTP {status}, body is not the health document")
        return results                                                       # nothing else can work

    status, _, body = send("GET", "/api/methods", None, None)
    catalogue = _json(body)
    ok = status == 200 and isinstance(catalogue, dict) and len(catalogue.get("methods", [])) == 9 and {"max_upload_mb", "max_image_pixels"} <= set(catalogue.get("limits", {}))
    record("PASS" if ok else "FAIL", "GET /api/methods", "nine methods and the server limits" if ok else f"HTTP {status}, unexpected catalogue")

    sample_bytes, sample_name = None, None
    status, _, body = send("GET", "/api/samples", None, None)
    samples = (_json(body) or {}).get("samples", []) if status == 200 else []
    if samples:
        chosen = next((s for s in samples if s.get("id") == "chest_ct"), samples[0])
        status, headers, payload = send("GET", f"/api/samples/{urllib.parse.quote(chosen['id'])}/file", None, None)
        if status == 200 and payload.startswith(PNG_SIGNATURE):
            record("PASS", "bundled samples", f"{len(samples)} listed; {chosen['id']} downloads as a PNG ({len(payload)} bytes)")
            sample_bytes, sample_name = payload, chosen.get("filename", "sample.png")
        else:
            record("FAIL", "bundled sample file", f"HTTP {status}, content-type {headers.get('content-type')}")
    else:
        record("FAIL", "GET /api/samples", f"HTTP {status}, no sample listed")

    for label, path in (("Benchmark V2", "/api/v2/runs"), ("Benchmark 3D", "/api/3d/runs")):
        status, _, body = send("GET", path, None, None)
        listing = _json(body)
        if status != 200 or not isinstance(listing, dict):
            record("FAIL", f"GET {path}", f"HTTP {status}")
        elif not listing.get("runs"):
            record("WARN", f"{label} runs", "none configured on this server (the page will say so)")
        else:
            states = {run["id"]: run.get("integrity", {}).get("status") for run in listing["runs"]}
            bad = {k: v for k, v in states.items() if v != "verified"}
            record("FAIL" if bad else "PASS", f"{label} runs", f"not verified: {bad}" if bad else f"{len(states)} run(s), every recorded file matches its SHA-256")

    junk, junk_type = multipart({}, "file", "notes.txt", b"this is not an image", "text/plain")
    status, _, body = send("POST", "/api/denoise", {"Content-Type": junk_type}, junk)
    refused = status in (400, 413, 422) and not LOCAL_PATH.search(body.decode("utf-8", "replace"))
    record("PASS" if refused else "FAIL", "invalid upload is refused cleanly", f"HTTP {status}" + ("" if refused else ", or the message exposes server details"))

    if do_denoise and sample_bytes:
        fields = {"noise_type": "Gaussian", "seed": "7", "methods": "mean"}
        payload, content_type = multipart(fields, "file", sample_name, sample_bytes, "image/png")
        replies = []
        for _ in range(2):
            status, _, body = send("POST", "/api/denoise", {"Content-Type": content_type}, payload)
            replies.append((status, _json(body)))
        (s1, r1), (s2, r2) = replies
        if s1 == 200 and isinstance(r1, dict):
            rows = {row["Filter"]: row for row in r1.get("results", [])}
            numeric = "Mean" in rows and isinstance(rows["Mean"].get("PSNR (dB)"), (int, float)) and "Noisy input" in rows
            same = s2 == 200 and isinstance(r2, dict) and r2.get("results") == r1.get("results")
            record("PASS" if numeric and same else "FAIL", "POST /api/denoise (mean, Gaussian noise, seed 7)",
                   f"PSNR of the mean filter {rows['Mean']['PSNR (dB)']} dB; second identical request gives the same scores: {same}" if numeric else "unexpected reply")
        else:
            record("FAIL", "POST /api/denoise", f"HTTP {s1} {s2 if s1 != 200 else ''}".strip())
    elif do_denoise:
        record("WARN", "POST /api/denoise", "skipped: no sample image could be downloaded")
    return results


def check_site(send_api: Request, send_site: Request, api_url: str, site_url: str) -> list[Result]:
    results: list[Result] = []
    site_origin, api_origin = origin_of(site_url), origin_of(api_url)

    status, headers, _ = send_api("GET", "/api/health", {"Origin": site_origin}, None)
    allowed = headers.get("access-control-allow-origin")
    if site_origin == api_origin:
        results.append(Result("PASS", "CORS", "same origin; no cross-origin call is needed"))
    else:
        results.append(Result("PASS" if allowed == site_origin else "FAIL", "CORS allows the dashboard's origin",
                              f"Access-Control-Allow-Origin: {allowed!r} (expected {site_origin!r}); set CORS_ORIGINS on the API" if allowed != site_origin else site_origin))
        _, foreign, _ = send_api("GET", "/api/health", {"Origin": FOREIGN_ORIGIN}, None)
        leaked = foreign.get("access-control-allow-origin") in ("*", FOREIGN_ORIGIN)
        results.append(Result("FAIL" if leaked else "PASS", "CORS refuses an unrelated origin", f"Access-Control-Allow-Origin: {foreign.get('access-control-allow-origin')!r}"))

    status, headers, body = send_site("GET", "/", None, None)
    html = body.decode("utf-8", "replace")
    if status != 200 or 'id="root"' not in html:
        results.append(Result("FAIL", "dashboard page", f"HTTP {status}; the page does not contain the application root"))
        return results
    results.append(Result("PASS", "dashboard page", "serves the application shell"))
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
    if not scripts:
        results.append(Result("FAIL", "dashboard bundle", "no script found in the page"))
        return results
    status, _, script = send_site("GET", urllib.parse.urljoin(site_url.rstrip("/") + "/", scripts[0]), None, None)
    if site_origin != api_origin:
        points = status == 200 and api_origin.encode() in script
        results.append(Result("PASS" if points else "FAIL", "dashboard build points at the API",
                              api_origin if points else f"the main bundle does not contain {api_origin}; rebuild with VITE_API_BASE_URL set"))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", required=True, help="origin of the API, for example https://your-api.example or http://127.0.0.1:8000")
    parser.add_argument("--site", help="origin of the dashboard; adds the CORS and build checks")
    parser.add_argument("--no-denoise", action="store_true", help="do not send the sample image to /api/denoise")
    parser.add_argument("--timeout", type=float, default=90.0, help="seconds per request (a sleeping free-tier service needs up to a minute to wake)")
    args = parser.parse_args(argv)

    api = args.api.rstrip("/")
    results = check_api(http_request(api, args.timeout), not args.no_denoise)
    if args.site:
        results += check_site(http_request(api, args.timeout), http_request(args.site.rstrip("/"), args.timeout), api, args.site)
    for result in results:
        print(f"{result.level:4}  {result.name}" + (f"  -  {result.detail}" if result.detail else ""))
    failed = [r for r in results if r.level == "FAIL"]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed or warned; {len(failed)} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
