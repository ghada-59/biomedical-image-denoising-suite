"""Tests for benchmark aggregation, seeds, CSV output and windowing consistency.

Expected numbers are computed here with NumPy or by hand, not by calling the code
under test, so the tests check the mathematics and not only the table format.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import evaluate_denoising as bench
import filters
from conftest import make_dicom_bytes

HISTORICAL_DETAIL = Path(__file__).parent / "docs" / "results" / "denoising_benchmark.csv"
HISTORICAL_SUMMARY = Path(__file__).parent / "docs" / "results" / "denoising_summary.csv"
GROUP = ["Noise", "Noise Parameter", "Domain", "Filter"]


def _row(slice_index, repeat, filter_name, psnr, ssim, *, noise="Gaussian", domain="Spatial",
         parameter="variance=0.02", series="S1", seed=1):
    return {
        "Series": series, "Slice Index": slice_index, "Repeat": repeat, "Seed": seed, "Noise": noise,
        "Noise Parameter": parameter, "Domain": domain, "Filter": filter_name, "PSNR (dB)": psnr, "SSIM": ssim,
    }


def _grid():
    """2 slices x 3 repeats, Gaussian noise; spatial Mean filter + both noisy baselines."""
    rows = []
    for s in (10, 20):
        for r in (1, 2, 3):
            base_psnr, base_ssim = 18.0 + 0.1 * s + r, 0.20 + 0.001 * s
            for domain in ("Spatial", "Frequency"):
                rows.append(_row(s, r, "Noisy (Unfiltered)", base_psnr, base_ssim, domain=domain))
            rows.append(_row(s, r, "Mean", base_psnr + 6.0 + 0.5 * r, base_ssim + 0.40))
    return pd.DataFrame(rows)


# --- aggregate_results: baselines, gains, groups ---------------------------------------


def test_every_row_is_compared_with_the_noisy_image_of_the_same_slice_repeat_and_noise():
    detail, _ = bench.aggregate_results(_grid())
    mean_rows = detail[detail["Filter"] == "Mean"]
    expected_baseline = 18.0 + 0.1 * mean_rows["Slice Index"] + mean_rows["Repeat"]
    np.testing.assert_allclose(mean_rows["Baseline PSNR (dB)"], expected_baseline)
    np.testing.assert_allclose(mean_rows["PSNR Gain (dB)"], 6.0 + 0.5 * mean_rows["Repeat"])
    np.testing.assert_allclose(mean_rows["SSIM Gain"], 0.40)


def test_unfiltered_rows_have_zero_gain_in_both_domains():
    detail, _ = bench.aggregate_results(_grid())
    noisy = detail[detail["Filter"] == "Noisy (Unfiltered)"]
    assert set(noisy["Domain"]) == {"Spatial", "Frequency"}
    assert (noisy["PSNR Gain (dB)"] == 0).all() and (noisy["SSIM Gain"] == 0).all()


def test_baseline_merge_does_not_duplicate_or_drop_rows():
    frame = _grid()
    detail, _ = bench.aggregate_results(frame)
    assert len(detail) == len(frame)
    assert not detail.duplicated(["Series", "Slice Index", "Repeat", "Noise", "Domain", "Filter"]).any()


def test_baselines_of_different_noise_types_are_not_mixed():
    rows = []
    for noise, psnr_base in (("Gaussian", 18.0), ("Salt & Pepper", 21.0)):
        rows.append(_row(5, 1, "Noisy (Unfiltered)", psnr_base, 0.3, noise=noise))
        rows.append(_row(5, 1, "Median", psnr_base + 10, 0.9, noise=noise))
    detail, _ = bench.aggregate_results(pd.DataFrame(rows))
    median = detail[detail["Filter"] == "Median"].set_index("Noise")
    assert median.loc["Gaussian", "PSNR Gain (dB)"] == pytest.approx(10.0)
    assert median.loc["Salt & Pepper", "PSNR Gain (dB)"] == pytest.approx(10.0)
    assert median.loc["Salt & Pepper", "Baseline PSNR (dB)"] == pytest.approx(21.0)


def test_missing_baseline_gives_nan_gain_instead_of_an_error():
    frame = pd.DataFrame([_row(5, 1, "Mean", 25.0, 0.7)])
    detail, summary = bench.aggregate_results(frame)
    assert np.isnan(detail.loc[0, "PSNR Gain (dB)"])
    assert np.isnan(summary.loc[0, "Mean_PSNR_Gain_dB"])


def test_summary_has_one_row_per_noise_parameter_domain_filter_group():
    frame = _grid()
    _, summary = bench.aggregate_results(frame)
    expected = frame[GROUP].drop_duplicates().shape[0]
    assert len(summary) == expected == 3  # Frequency noisy, Spatial noisy, Spatial Mean
    assert not summary.duplicated(GROUP).any()


def test_different_noise_parameters_are_summarised_separately():
    frame = pd.concat([
        pd.DataFrame([_row(1, 1, "Noisy (Unfiltered)", 18.0, 0.2, parameter="variance=0.02")]),
        pd.DataFrame([_row(1, 1, "Noisy (Unfiltered)", 24.0, 0.5, parameter="variance=0.005")]),
    ])
    _, summary = bench.aggregate_results(frame)
    assert sorted(summary["Noise Parameter"]) == ["variance=0.005", "variance=0.02"]


# --- aggregate_results: statistics ---------------------------------------------------


def test_means_stds_and_counts_match_numpy():
    frame = _grid()
    _, summary = bench.aggregate_results(frame)
    mean_rows = frame[frame["Filter"] == "Mean"]
    row = summary[summary["Filter"] == "Mean"].iloc[0]
    assert row["Runs_Evaluated"] == 6
    assert row["Slices_Evaluated"] == 2
    assert row["Mean_PSNR_dB"] == pytest.approx(round(mean_rows["PSNR (dB)"].mean(), 3))
    assert row["Std_PSNR_dB"] == pytest.approx(round(np.std(mean_rows["PSNR (dB)"], ddof=1), 3))
    assert row["Mean_SSIM"] == pytest.approx(round(mean_rows["SSIM"].mean(), 4))
    assert row["Std_SSIM"] == pytest.approx(round(np.std(mean_rows["SSIM"], ddof=1), 4))


def test_mean_gains_equal_the_difference_of_means_for_a_complete_design():
    frame = _grid()
    _, summary = bench.aggregate_results(frame)
    mean_row = summary[summary["Filter"] == "Mean"].iloc[0]
    noisy = frame[(frame["Filter"] == "Noisy (Unfiltered)") & (frame["Domain"] == "Spatial")]
    filtered = frame[frame["Filter"] == "Mean"]
    assert mean_row["Mean_PSNR_Gain_dB"] == pytest.approx(
        round(filtered["PSNR (dB)"].mean() - noisy["PSNR (dB)"].mean(), 3)
    )


def test_aggregation_uses_full_precision_and_rounds_only_the_result():
    # Mean of the values = 20.000733 -> 20.001, but the mean of the 3-decimal rounded
    # values would be 20.000333 -> 20.000. The summary must show 20.001.
    rows = [_row(i, 1, "Mean", value, 0.5) for i, value in enumerate((20.0004, 20.0004, 20.0014))]
    _, summary = bench.aggregate_results(pd.DataFrame(rows))
    assert summary.loc[0, "Mean_PSNR_dB"] == 20.001
    assert round(np.mean([20.0, 20.0, 20.001]), 3) == 20.0  # what rounding first would give


def test_a_single_run_group_reports_zero_standard_deviation():
    """Documents current behaviour: ``std`` of one value is NaN and is written as 0.

    Reporting 0 for n=1 suggests perfect repeatability; the V2 benchmark should leave
    it empty instead. This test records the present contract so a change is deliberate.
    """
    _, summary = bench.aggregate_results(pd.DataFrame([_row(1, 1, "Mean", 25.0, 0.7)]))
    assert summary.loc[0, "Runs_Evaluated"] == 1
    assert summary.loc[0, "Std_PSNR_dB"] == 0 and summary.loc[0, "Std_SSIM"] == 0


def test_nan_metrics_are_skipped_in_means_but_still_counted_as_runs():
    rows = [_row(1, 1, "Mean", 24.0, 0.6), _row(1, 2, "Mean", float("nan"), 0.8)]
    _, summary = bench.aggregate_results(pd.DataFrame(rows))
    assert summary.loc[0, "Mean_PSNR_dB"] == 24.0
    assert summary.loc[0, "Runs_Evaluated"] == 2  # counts rows, including the NaN one
    assert summary.loc[0, "Mean_SSIM"] == pytest.approx(0.7)


def test_perfect_reconstruction_gives_infinite_psnr_that_propagates_to_the_mean():
    rows = [_row(1, 1, "Mean", float("inf"), 1.0), _row(1, 2, "Mean", 30.0, 0.9)]
    _, summary = bench.aggregate_results(pd.DataFrame(rows))
    assert np.isinf(summary.loc[0, "Mean_PSNR_dB"])


def test_exact_duplicate_rows_are_counted_twice():
    """Documents that duplicates are not removed: they inflate Runs_Evaluated."""
    row = _row(1, 1, "Mean", 25.0, 0.7)
    _, summary = bench.aggregate_results(pd.DataFrame([row, dict(row)]))
    assert summary.loc[0, "Runs_Evaluated"] == 2


# --- write_reports: CSV generation -----------------------------------------------------


def test_write_reports_creates_both_csv_files_and_round_trips(tmp_path):
    out = tmp_path / "nested" / "reports"
    detail, summary, detail_path, summary_path = bench.write_reports(_grid(), out)
    assert detail_path == out / "denoising_benchmark.csv" and summary_path == out / "denoising_summary.csv"

    summary_csv = pd.read_csv(summary_path)
    pd.testing.assert_frame_equal(summary_csv, summary, check_dtype=False)

    detail_csv = pd.read_csv(detail_path)
    assert len(detail_csv) == len(detail)
    assert list(detail_csv.columns) == list(detail.columns)
    assert detail_csv.columns[-4:].tolist() == ["Baseline PSNR (dB)", "Baseline SSIM", "PSNR Gain (dB)", "SSIM Gain"]


def test_detailed_csv_is_rounded_for_display_but_returned_detail_is_not(tmp_path):
    frame = pd.DataFrame([
        _row(1, 1, "Noisy (Unfiltered)", 18.123456, 0.123456),
        _row(1, 1, "Mean", 25.987654, 0.765432),
    ])
    detail, _, detail_path, _ = bench.write_reports(frame, tmp_path)
    shown = pd.read_csv(detail_path).set_index("Filter")
    assert shown.loc["Mean", "PSNR (dB)"] == 25.988 and shown.loc["Mean", "SSIM"] == 0.7654
    assert detail.set_index("Filter").loc["Mean", "PSNR (dB)"] == 25.987654


def test_write_reports_overwrites_only_its_own_two_files(tmp_path):
    (tmp_path / "keep_me.txt").write_text("historical", encoding="utf-8")
    bench.write_reports(_grid(), tmp_path)
    assert (tmp_path / "keep_me.txt").read_text(encoding="utf-8") == "historical"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["denoising_benchmark.csv", "denoising_summary.csv", "keep_me.txt"]


@pytest.mark.skipif(not (HISTORICAL_DETAIL.is_file() and HISTORICAL_SUMMARY.is_file()), reason="historical snapshot not present")
def test_historical_summary_is_the_aggregate_of_the_historical_detail():
    """Regression check against the committed 0.10-cutoff snapshot (read only).

    The detailed CSV is rounded (3 and 4 decimals), so recomputed means may differ from
    the published full-precision ones by at most one rounding step.
    """
    detail = pd.read_csv(HISTORICAL_DETAIL)
    historical = pd.read_csv(HISTORICAL_SUMMARY)
    _, recomputed = bench.aggregate_results(detail[bench_columns()])
    merged = recomputed.merge(historical, on=GROUP, suffixes=("_new", "_old"))
    assert len(merged) == len(historical) == len(recomputed)
    for column in ("Slices_Evaluated", "Runs_Evaluated"):
        assert (merged[column + "_new"] == merged[column + "_old"]).all()
    for column, tol in (("Mean_PSNR_dB", 1.5e-3), ("Std_PSNR_dB", 1.5e-3), ("Mean_PSNR_Gain_dB", 1.5e-3),
                        ("Mean_SSIM", 1.5e-4), ("Std_SSIM", 1.5e-4), ("Mean_SSIM_Gain", 1.5e-4)):
        assert (merged[column + "_new"] - merged[column + "_old"]).abs().max() <= tol, column


def bench_columns():
    return ["Series", "Slice Index", "Repeat", "Seed", "Noise", "Noise Parameter", "Domain", "Filter", "PSNR (dB)", "SSIM"]


# --- seeds ---------------------------------------------------------------------------


def test_seed_derivation_has_a_known_value():
    # 42 + slice 15 * 100003 + repeat 0 * 1009 + Gaussian offset 101
    assert bench.derive_run_seed(42, 15, "Gaussian", 0) == 1500188


def test_seeds_are_unique_over_a_realistic_grid():
    seeds = {
        bench.derive_run_seed(42, s, noise, r)
        for s in range(0, 600) for r in range(0, 50) for noise in bench.NOISE_TYPES
    }
    assert len(seeds) == 600 * 50 * len(bench.NOISE_TYPES)
    assert max(seeds) < 2**32


@pytest.mark.parametrize("args", [(-1, 0, "Gaussian", 0), (42, -1, "Gaussian", 0), (42, 0, "Gaussian", -1)])
def test_negative_seed_inputs_are_rejected(args):
    with pytest.raises(ValueError):
        bench.derive_run_seed(*args)


def test_unknown_noise_type_is_rejected_by_seed_derivation():
    with pytest.raises(ValueError):
        bench.derive_run_seed(42, 0, "Poisson", 0)


@pytest.mark.skipif(not HISTORICAL_DETAIL.is_file(), reason="historical snapshot not present")
def test_seed_formula_reproduces_every_seed_recorded_in_the_historical_csv():
    detail = pd.read_csv(HISTORICAL_DETAIL)
    for _, row in detail.drop_duplicates(["Slice Index", "Noise", "Repeat"]).iterrows():
        assert bench.derive_run_seed(42, int(row["Slice Index"]), row["Noise"], int(row["Repeat"]) - 1) == row["Seed"]


# --- one slice end to end (small synthetic phantom) --------------------------------------


@pytest.fixture
def phantom() -> np.ndarray:
    yy, xx = np.mgrid[0:48, 0:48]
    radius = np.hypot(yy - 24, xx - 24)
    image = np.where(radius < 16, 0.7, 0.1) + 0.2 * (radius < 6)
    return np.clip(image, 0.0, 1.0)


def _run_slice(phantom, repeat=0, seed=5, noise="Gaussian"):
    return bench._evaluate_one_slice(
        clean_image=phantom, series_name="synthetic", slice_index=3, noise_type=noise,
        noise_variance=0.01, salt_pepper_amount=0.02, repeat_index=repeat, seed=seed, save_visuals=False,
    )


def test_one_slice_yields_eight_rows_with_consistent_metadata(phantom):
    rows = _run_slice(phantom)
    assert len(rows) == 8
    assert [r["Domain"] for r in rows] == ["Spatial"] * 4 + ["Frequency"] * 4
    assert [r["Filter"] for r in rows] == [
        "Noisy (Unfiltered)", "Mean", "Median", "Gaussian", "Noisy (Unfiltered)", "Ideal", "Gauss", "Butterworth",
    ]
    assert {r["Seed"] for r in rows} == {5} and {r["Repeat"] for r in rows} == {1}
    assert {r["Noise Parameter"] for r in rows} == {"variance=0.01"}


def test_unfiltered_baseline_is_identical_in_both_domains_and_matches_the_formula(phantom):
    rows = _run_slice(phantom)
    noisy_rows = [r for r in rows if r["Filter"] == "Noisy (Unfiltered)"]
    assert noisy_rows[0]["PSNR (dB)"] == noisy_rows[1]["PSNR (dB)"]
    assert noisy_rows[0]["SSIM"] == noisy_rows[1]["SSIM"]

    noisy = filters.add_noise(phantom, "Gaussian", var=0.01, seed=5)
    expected_psnr = 10 * np.log10(1.0 / np.mean((phantom - noisy) ** 2))
    assert noisy_rows[0]["PSNR (dB)"] == pytest.approx(expected_psnr, abs=1e-9)


def test_one_slice_is_reproducible_and_depends_on_the_seed(phantom):
    assert _run_slice(phantom) == _run_slice(phantom)
    assert _run_slice(phantom, seed=6) != _run_slice(phantom, seed=5)


def test_salt_and_pepper_row_labels_the_amount_parameter(phantom):
    rows = _run_slice(phantom, noise="Salt & Pepper")
    assert {r["Noise Parameter"] for r in rows} == {"amount=0.02"}


def test_run_without_visuals_writes_no_files(phantom, tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "VISUALS_DIR", tmp_path / "2D")
    _run_slice(phantom)
    assert not (tmp_path / "2D").exists()


# --- windowing consistency between the interactive loader and the benchmark --------------


def _dicom_with_hu(hu: np.ndarray, center: float, width: float) -> bytes:
    return make_dicom_bytes(
        series_uid="1.2.3", instance_number=1, z_mm=0.0, rows=hu.shape[0], cols=hu.shape[1],
        hu=hu, overrides={"WindowCenter": center, "WindowWidth": width},
    )


def test_dicom_window_in_the_loader_matches_the_benchmark_window():
    hu = np.linspace(-2000, 1000, 40 * 40).reshape(40, 40).round()
    payload = _dicom_with_hu(hu, center=-600, width=1500)
    loaded = filters.load_medical_image(_named(payload, "ct.dcm"))
    expected = bench.window_ct_slice(hu, window_center=-600, window_width=1500)
    np.testing.assert_allclose(loaded, expected, atol=1e-12)


def test_window_endpoints_follow_the_dicom_linear_function():
    # DICOM PS3.3 C.11.2.1.2: values <= c-0.5-(w-1)/2 -> 0, > c-0.5+(w-1)/2 -> 1, c-0.5 -> 0.5
    center, width = -600.0, 1500.0
    lower = center - 0.5 - (width - 1) / 2
    upper = center - 0.5 + (width - 1) / 2
    hu = np.array([[lower, lower + 1, center - 0.5, upper, upper + 1]])
    out = bench.window_ct_slice(hu, center, width)
    assert out[0, 0] == 0.0 and out[0, 4] == 1.0
    assert out[0, 2] == pytest.approx(0.5)
    assert 0.0 < out[0, 1] < 0.01 and 0.99 < out[0, 3] <= 1.0


def test_benchmark_volume_path_and_loader_path_give_the_same_normalised_slice(tmp_path):
    from src.dicom_volume import load_dicom_volume

    hu = np.random.default_rng(3).uniform(-1500, 500, size=(24, 24)).round()
    for index in range(2):
        (tmp_path / f"s{index}.dcm").write_bytes(
            make_dicom_bytes(series_uid="1.2.3", instance_number=index + 1, z_mm=2.0 * index, rows=24, cols=24,
                             hu=hu, overrides={"WindowCenter": -600, "WindowWidth": 1500})
        )
    volume, *_ = load_dicom_volume(tmp_path)
    via_benchmark = bench.window_ct_slice(volume[0], -600, 1500)
    via_loader = filters.load_medical_image(_named((tmp_path / "s0.dcm").read_bytes(), "s0.dcm"))
    np.testing.assert_allclose(via_benchmark, via_loader, atol=1e-6)


def test_loader_without_window_tags_min_max_normalises_each_image_separately():
    """Documents that images lacking WindowCenter/WindowWidth are scaled by their own range,
    so metrics from two such images are not on a common intensity scale."""
    low = np.full((8, 8), -500.0)
    low[0, 0] = 500.0
    high = low * 0.5
    arrays = []
    for hu in (low, high):
        payload = make_dicom_bytes(series_uid="1.2.3", instance_number=1, z_mm=0.0, rows=8, cols=8, hu=hu,
                                   omit=("WindowCenter", "WindowWidth"))
        arrays.append(filters.load_medical_image(_named(payload, "x.dcm")))
    np.testing.assert_allclose(arrays[0], arrays[1], atol=1e-9)
    assert arrays[0].min() == 0.0 and arrays[0].max() == 1.0


def _named(payload: bytes, name: str):
    buffer = io.BytesIO(payload)
    buffer.name = name
    return buffer
