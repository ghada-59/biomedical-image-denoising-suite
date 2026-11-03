"""Tests of the 2D lab API: method catalogue, method selection, parameters used, timings, sample images and load limits."""

from __future__ import annotations

import re
import threading

import numpy as np
import pytest
from fastapi.testclient import TestClient

import api
import methods as M
import sample_images
from filters import apply_frequency_lowpass, apply_spatial_filters
from conftest import make_png_bytes

ALL_IDS = [m.id for m in M.METHODS]
DATA_URL = re.compile(r"^data:image/png;base64,[A-Za-z0-9+/=]+$")


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app, raise_server_exceptions=False)


@pytest.fixture
def png() -> bytes:
    return make_png_bytes((64, 64))


def post(client, payload, filename="slice.png", **fields):
    data = {key: str(value) for key, value in fields.items()}
    return client.post("/api/denoise", files={"file": (filename, payload, "image/png")}, data=data)


# --- catalogue -----------------------------------------------------------------------------


def test_the_catalogue_lists_every_method_with_parameters_limits_and_defaults(client):
    body = client.get("/api/methods").json()
    assert [m["id"] for m in body["methods"]] == ALL_IDS == list(M.BY_ID)
    assert body["default_methods"] == ["mean", "median", "gaussian", "fft_ideal", "fft_gauss", "fft_butterworth"]
    assert body["noise_types"] == ["None", "Gaussian", "Salt & Pepper", "Speckle (synthetic)"]
    assert set(body["limits"]) == {"max_upload_mb", "max_image_pixels", "max_advanced_pixels", "max_concurrent_jobs"}
    assert body["limits"]["max_advanced_pixels"] == api.MAX_ADVANCED_PIXELS
    for method in body["methods"]:
        assert method["label"] and method["family"] and method["summary"] and method["assumption"] and method["reference"]
        assert method["parameters"], method["id"]
        for param in method["parameters"]:
            assert param["minimum"] <= param["default"] <= param["maximum"]
            assert param["help"] and param["label"]
    assert {m["id"] for m in body["methods"] if m["heavy"]} == {"bilateral", "nlm", "wavelet"}


def test_every_catalogued_parameter_is_a_form_field_with_the_same_limits():
    """The catalogue drives the dashboard's controls; the endpoint enforces the limits. They must not drift apart."""
    schema = api.app.openapi()
    body_ref = schema["paths"]["/api/denoise"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
    properties = schema["components"]["schemas"][body_ref.split("/")[-1]]["properties"]
    for name, param in M.PARAMS.items():
        assert name in properties, name
        field = properties[name]
        default = field["default"]
        assert default == param.default or float(default) == pytest.approx(param.default), name
        if param.exclusive_minimum:
            assert field.get("exclusiveMinimum") == param.minimum, name
        else:
            assert field.get("minimum") == param.minimum, name
        if param.exclusive_maximum:
            assert field.get("exclusiveMaximum") == param.maximum and "maximum" not in field, name
        else:
            assert field.get("maximum") == param.maximum and "exclusiveMaximum" not in field, name


def test_the_highest_value_a_control_offers_is_accepted_by_the_server():
    """What the slider can reach must be a valid request: the endpoint's limits and the dashboard's control range agree."""
    import numpy as np

    from conftest import make_png_bytes

    c = TestClient(api.app, raise_server_exceptions=False)
    image = make_png_bytes((64, 64))
    for method in M.METHODS:
        for param in method.params:
            step = param.step
            top = param.maximum - step if param.exclusive_maximum else param.maximum
            if param.integer:
                top = min(int(top), 31)
            bottom = param.minimum + step if param.exclusive_minimum else param.minimum
            for value in (bottom, top):
                response = c.post("/api/denoise", files={"file": ("s.png", image, "image/png")},
                                  data={"methods": method.id, param.name: str(float(np.round(value, 6)) if not param.integer else int(value))})
                assert response.status_code == 200, f"{method.id} {param.name}={value}: {response.status_code} {response.text[:120]}"


def test_method_ids_are_parsed_in_order_without_duplicates_and_rejected_when_unknown():
    assert M.parse_method_ids("nlm, mean,nlm ,") == ["nlm", "mean"]
    for bad in ("", " , ", "mean,nope", "MEAN"):
        with pytest.raises(ValueError):
            M.parse_method_ids(bad)


# --- the registry runs the same code as the original filters --------------------------------------


@pytest.fixture(scope="module")
def image():
    return np.random.default_rng(0).uniform(0.1, 0.9, (48, 48))


@pytest.mark.parametrize("kernel", [3, 5, 7])
def test_spatial_methods_equal_the_original_spatial_filters(image, kernel):
    mean, median, gaussian = apply_spatial_filters(image, kernel_size=kernel, sigma=1.3)
    values = {"kernel_size": kernel, "sigma": 1.3}
    np.testing.assert_array_equal(M.BY_ID["mean"].run(image, values)[0], mean)
    np.testing.assert_array_equal(M.BY_ID["median"].run(image, values)[0], median)
    np.testing.assert_array_equal(M.BY_ID["gaussian"].run(image, values)[0], gaussian)


@pytest.mark.parametrize("method_id, kind", [("fft_ideal", "ideal"), ("fft_gauss", "gauss"), ("fft_butterworth", "butterworth")])
def test_frequency_methods_equal_the_original_frequency_filter(image, method_id, kind):
    expected = apply_frequency_lowpass(image, cutoff_ratio=0.2, filter_type=kind)[0]
    np.testing.assert_array_equal(M.BY_ID[method_id].run(image, {"cutoff_ratio": 0.2})[0], expected)


def test_even_kernels_are_raised_to_odd_and_the_used_value_is_reported(image):
    for method_id in ("mean", "median", "gaussian"):
        assert M.BY_ID[method_id].run(image, {"kernel_size": 4, "sigma": 0.0})[1]["kernel_size"] == 5


def test_gaussian_sigma_zero_is_reported_as_automatic(image):
    _, used = M.BY_ID["gaussian"].run(image, {"kernel_size": 5, "sigma": 0.0})
    assert "auto" in used["sigma"]
    assert M.BY_ID["gaussian"].run(image, {"kernel_size": 5, "sigma": 1.5})[1]["sigma"] == 1.5


def test_wavelet_levels_are_capped_to_what_the_image_supports_and_reported():
    small = np.random.default_rng(1).uniform(0.2, 0.8, (16, 16))
    large = np.random.default_rng(1).uniform(0.2, 0.8, (96, 96))
    assert M.BY_ID["wavelet"].run(small, {"wavelet_sigma": 0.1})[1]["levels"] == 1
    assert M.BY_ID["wavelet"].run(large, {"wavelet_sigma": 0.1})[1]["levels"] == 3
    with pytest.raises(ValueError):
        M.BY_ID["wavelet"].run(np.zeros((8, 8)), {"wavelet_sigma": 0.1})


@pytest.mark.parametrize("method_id", ALL_IDS)
def test_every_method_returns_a_unit_range_image_of_the_same_shape(image, method_id):
    values = {p.name: p.default for p in M.PARAMS.values()}
    out, used = M.BY_ID[method_id].run(image, values)
    assert out.shape == image.shape and 0.0 <= out.min() and out.max() <= 1.0 and used


# --- /api/denoise with method selection ------------------------------------------------------------


def test_the_default_request_still_returns_the_six_original_filters(client, png):
    body = post(client, png).json()
    assert [row["Filter"] for row in body["results"]] == ["Noisy input", "Mean", "Median", "Gaussian", "Frequency ideal",
                                                          "Frequency Gaussian", "Frequency Butterworth"]
    assert [m["id"] for m in body["methods"]] == list(M.DEFAULT_METHOD_IDS)


def test_all_nine_methods_run_through_the_api_and_report_parameters_and_timings(client, png):
    body = post(client, png, methods=",".join(ALL_IDS), noise_type="Gaussian", seed=5, nlm_h=0.08, wavelet_sigma=0.12,
                bilateral_sigma_color=0.2, bilateral_sigma_space=2.0).json()
    labels = ["Noisy input"] + [M.BY_ID[i].label for i in ALL_IDS]
    assert [r["Filter"] for r in body["results"]] == labels and set(body["images"]) == set(labels)
    assert all(DATA_URL.match(url) for url in body["images"].values())
    assert [m["id"] for m in body["methods"]] == ALL_IDS
    used = {m["id"]: m["parameters"] for m in body["methods"]}
    assert used["bilateral"] == {"sigma_color": 0.2, "sigma_space": 2.0}
    assert used["nlm"] == {"h": 0.08, "patch_size": 5, "patch_distance": 6}
    assert used["wavelet"]["assumed_noise_sd"] == 0.12 and used["wavelet"]["wavelet"] == "sym4" and used["wavelet"]["shifts_averaged"] == 16
    assert used["fft_butterworth"] == {"cutoff_ratio": 0.15, "order": 2}
    assert body["settings"] == {"noise_type": "Gaussian", "noise_amount": None, "noise_variance": 0.02, "seed": 5}
    timings = body["timings_ms"]
    assert set(timings) == set(labels) | {"total"} and all(v >= 0 for v in timings.values())
    assert timings["total"] >= sum(v for k, v in timings.items() if k != "total") * 0.9
    assert all(set(row) == {"Filter", "PSNR (dB)", "SSIM"} for row in body["results"])          # timings are not in the rows


def test_the_selection_decides_which_outputs_exist_and_keeps_the_requested_order(client, png):
    body = post(client, png, methods="nlm,mean").json()
    assert [r["Filter"] for r in body["results"]] == ["Noisy input", "Non-local means", "Mean"]
    assert set(body["timings_ms"]) == {"Noisy input", "Non-local means", "Mean", "total"}


def test_results_are_reproducible_for_all_methods_even_though_timings_vary(client, png):
    fields = dict(methods=",".join(ALL_IDS), noise_type="Speckle (synthetic)", seed=3)
    first, second = post(client, png, **fields).json(), post(client, png, **fields).json()
    assert first["results"] == second["results"] and first["images"] == second["images"] and first["methods"] == second["methods"]


@pytest.mark.parametrize("methods", [" , ", "mean,nope", "MEAN", "x" * 201])
def test_a_bad_method_selection_is_a_422_with_a_text_detail(client, png, methods):
    response = post(client, png, methods=methods)
    assert response.status_code == 422 and isinstance(response.json()["detail"], str)


def test_an_omitted_or_empty_selection_means_the_default_six_methods(client, png):
    # An empty multipart field is read as "not sent"; the dashboard therefore refuses to submit an empty selection.
    assert [m["id"] for m in post(client, png, methods="").json()["methods"]] == list(M.DEFAULT_METHOD_IDS)
    assert [m["id"] for m in post(client, png).json()["methods"]] == list(M.DEFAULT_METHOD_IDS)


@pytest.mark.parametrize("field, value", [
    ("bilateral_sigma_color", 0), ("bilateral_sigma_color", -0.1), ("bilateral_sigma_color", "nan"), ("bilateral_sigma_color", 1.5),
    ("bilateral_sigma_space", 0), ("bilateral_sigma_space", 5.5), ("bilateral_sigma_space", "inf"),
    ("nlm_h", 0), ("nlm_h", "nan"), ("nlm_h", 2),
    ("wavelet_sigma", 0), ("wavelet_sigma", -1), ("wavelet_sigma", "nan"), ("wavelet_sigma", 1.01),
])
def test_invalid_parameters_of_the_added_methods_are_rejected_with_422(client, png, field, value):
    response = post(client, png, methods="bilateral,nlm,wavelet", **{field: value})
    assert response.status_code == 422, response.text
    assert field in response.json()["detail"] and isinstance(response.json()["detail"], str)


def test_a_too_small_image_is_a_clean_422_for_the_wavelet_and_fine_for_the_others(client):
    tiny = make_png_bytes((8, 8))
    assert post(client, tiny, methods="wavelet").status_code == 422
    assert post(client, tiny, methods="mean,median,bilateral").status_code == 200
    assert post(client, make_png_bytes((6, 6)), methods="bilateral").status_code == 422     # below the 8 x 8 minimum of the denoisers


def test_heavy_methods_are_capped_by_pixel_count_but_the_classical_filters_are_not(client, png, monkeypatch):
    monkeypatch.setattr(api, "MAX_ADVANCED_PIXELS", 100)
    response = post(client, png, methods="mean,nlm,bilateral")
    assert response.status_code == 413
    detail = response.json()["detail"]
    assert "Non-local means" in detail and "Bilateral" in detail and "Mean" not in detail and "100" in detail
    assert post(client, png, methods="mean,median").status_code == 200


# --- load protection --------------------------------------------------------------------------------


def test_a_busy_server_answers_503_with_retry_after_and_recovers(client, png, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(api, "_JOB_SLOTS", slots)
    response = post(client, png)
    assert response.status_code == 503 and response.headers["retry-after"] == "5" and isinstance(response.json()["detail"], str)
    slots.release()
    assert post(client, png).status_code == 200
    assert slots.acquire(blocking=False)                       # the slot was released after the successful job
    slots.release()


def test_a_failed_job_releases_its_slot(client, png, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(api, "_JOB_SLOTS", slots)
    assert post(client, png, methods="wavelet", wavelet_sigma=0).status_code == 422
    assert post(client, make_png_bytes((8, 8)), methods="wavelet").status_code == 422        # fails inside the slot
    assert slots.acquire(blocking=False)
    slots.release()


def test_the_ct_reconstruction_also_respects_the_slot_limit(client, dicom_series_bytes, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(api, "_JOB_SLOTS", slots)
    files = [("files", (name, payload, "application/dicom")) for name, payload in dicom_series_bytes(3)]
    response = client.post("/api/ct/volume", files=files)
    assert response.status_code == 503


# --- sample images ----------------------------------------------------------------------------------


def test_the_sample_listing_states_provenance_licence_and_cautions(client):
    samples = client.get("/api/samples").json()["samples"]
    assert [s["id"] for s in samples] == [s.id for s in sample_images.available_samples()] and len(samples) == 3
    for sample in samples:
        assert sample["provenance"] and sample["licence"] and sample["caution"] and sample["description"]
        assert sample["file_url"] == f"/api/samples/{sample['id']}/file" and sample["size_bytes"] > 0
    by_id = {s["id"]: s for s in samples}
    assert "phantom" in by_id["synthetic_ct"]["modality"] and "not tissue" in by_id["cell_phase"]["description"]
    chest = by_id["chest_ct"]   # a slice of a public series whose licence is established at the source (the collection's own record)
    assert chest["modality"].startswith("CT") and "MRI" not in chest["label"] and "LIDC-IDRI-0709" in chest["description"]
    assert "CC BY 3.0" in chest["licence"] and "Attribution is required" in chest["licence"] and "not verified" not in chest["licence"].lower()
    assert "10.7937/K9/TCIA.2015.LO9QL9SX" in chest["provenance"] and "teaching device" in chest["caution"]
    assert set(by_id) == {"synthetic_ct", "chest_ct", "cell_phase"}      # a sample whose terms cannot be verified is not bundled


def test_sample_files_are_served_exactly_and_unknown_ids_are_404(client):
    for sample in sample_images.available_samples():
        response = client.get(f"/api/samples/{sample.id}/file")
        assert response.status_code == 200 and response.content == sample.path().read_bytes()
        assert response.headers["content-type"].startswith(sample.media_type)
    for bad in ("nope", "..", "%2e%2e%2fapi.py", "chest_ct.png", "head_ct", "brain_mri", "synthetic_ct%2f..%2f..%2fapi.py"):    # file names and the retired ids are not sample ids
        assert client.get(f"/api/samples/{bad}/file").status_code == 404


def test_a_missing_sample_file_is_not_listed_and_not_served(client, monkeypatch, tmp_path):
    monkeypatch.setattr(sample_images, "SAMPLES_DIR", tmp_path)
    assert client.get("/api/samples").json() == {"samples": []}
    assert client.get("/api/samples/synthetic_ct/file").status_code == 404


@pytest.mark.parametrize("sample", sample_images.SAMPLES, ids=lambda s: s.id)
def test_every_bundled_sample_can_be_denoised_with_every_method_like_an_upload(client, sample):
    payload = sample.path().read_bytes()
    response = client.post("/api/denoise", files={"file": (sample.filename, payload, sample.media_type)},
                           data={"methods": ",".join(ALL_IDS), "noise_type": "Gaussian", "seed": "1"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["results"]) == 10 and body["width"] > 0 and all(np.isfinite(r["SSIM"]) for r in body["results"])
