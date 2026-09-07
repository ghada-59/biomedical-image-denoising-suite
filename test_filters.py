from __future__ import annotations

import types

import cv2
import numpy as np
import pytest

import filters


@pytest.fixture
def clean_image() -> np.ndarray:
    size_y, size_x = 120, 160
    yy, xx = np.mgrid[0:size_y, 0:size_x]
    cy, cx = size_y / 2, size_x / 2
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

    image = np.zeros((size_y, size_x), dtype=np.float64)
    image[r < min(size_y, size_x) * 0.45] = 0.4
    image[r < min(size_y, size_x) * 0.30] = 0.7
    image[r < min(size_y, size_x) * 0.12] = 0.95
    image += 0.05

    image = cv2.GaussianBlur(image, (5, 5), sigmaX=1.0)
    return np.clip(image, 0.0, 1.0)


def _fake_dicom_dataset(**kwargs) -> types.SimpleNamespace:
    return types.SimpleNamespace(**kwargs)


class _FakeUploadedFile:

    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def read(self) -> bytes:
        return self._data

    def seek(self, pos: int) -> None:
        pass


@pytest.mark.parametrize("noise_type", filters.NOISE_TYPES)
def test_add_noise_preserves_shape_and_range(clean_image, noise_type):
    noisy = filters.add_noise(clean_image, noise_type, var=0.02, amount=0.05, seed=1)
    assert noisy.shape == clean_image.shape
    assert noisy.min() >= 0.0 and noisy.max() <= 1.0


def test_add_noise_unknown_type_raises(clean_image):
    with pytest.raises(ValueError):
        filters.add_noise(clean_image, "UnknownType")


def test_add_noise_is_reproducible_with_seed(clean_image):
    a = filters.add_noise(clean_image, "Gaussian", var=0.02, seed=7)
    b = filters.add_noise(clean_image, "Gaussian", var=0.02, seed=7)
    np.testing.assert_array_equal(a, b)


def test_calculate_metrics_identical_images(clean_image):
    p, s = filters.calculate_metrics(clean_image, clean_image)
    assert s == 1.0
    assert p == float("inf")


def test_calculate_metrics_finite_for_different_images(clean_image):
    noisy = filters.add_noise(clean_image, "Gaussian", var=0.02, seed=1)
    p, s = filters.calculate_metrics(clean_image, noisy)
    assert np.isfinite(p)
    assert 0.0 <= s <= 1.0


def test_to_uint8_rounds_instead_of_truncating():
    result = filters._to_uint8(np.array([0.5, 0.999]))
    assert result[0] == 128
    assert result[1] == 255


def test_to_uint8_clips_out_of_range_values():
    result = filters._to_uint8(np.array([-0.1, 1.1]))
    assert result[0] == 0
    assert result[1] == 255


def test_apply_spatial_filters_shapes_and_range(clean_image):
    noisy = filters.add_noise(clean_image, "Gaussian", var=0.02, seed=1)
    mean_img, median_img, gauss_img = filters.apply_spatial_filters(noisy, kernel_size=5)
    for img in (mean_img, median_img, gauss_img):
        assert img.shape == clean_image.shape
        assert img.min() >= -1e-9 and img.max() <= 1 + 1e-9


def test_apply_spatial_filters_accepts_even_kernel_size(clean_image):
    result = filters.apply_spatial_filters(clean_image, kernel_size=6)
    assert all(img.shape == clean_image.shape for img in result)


def test_apply_spatial_filters_rejects_non_positive_kernel(clean_image):
    with pytest.raises(ValueError):
        filters.apply_spatial_filters(clean_image, kernel_size=0)


def test_median_filter_beats_mean_filter_on_salt_and_pepper(clean_image):
    noisy = filters.add_noise(clean_image, "Salt & Pepper", amount=0.1, seed=3)
    mean_img, median_img, _ = filters.apply_spatial_filters(noisy, kernel_size=5)
    _, ssim_mean = filters.calculate_metrics(clean_image, mean_img)
    _, ssim_median = filters.calculate_metrics(clean_image, median_img)
    assert ssim_median > ssim_mean


@pytest.mark.parametrize("filter_type", filters.FREQUENCY_FILTERS)
def test_apply_frequency_lowpass_shapes_and_range(clean_image, filter_type):
    noisy = filters.add_noise(clean_image, "Gaussian", var=0.02, seed=1)
    img_back, spectrum, spectrum_f = filters.apply_frequency_lowpass(
        noisy, cutoff_ratio=0.15, filter_type=filter_type
    )
    assert img_back.shape == clean_image.shape
    assert img_back.min() >= 0.0 and img_back.max() <= 1.0
    assert spectrum.shape == clean_image.shape


@pytest.mark.parametrize("filter_type", filters.FREQUENCY_FILTERS)
def test_apply_frequency_lowpass_attenuates_spectrum_energy(clean_image, filter_type):
    noisy = filters.add_noise(clean_image, "Gaussian", var=0.02, seed=1)
    _, spectrum, spectrum_f = filters.apply_frequency_lowpass(
        noisy, cutoff_ratio=0.15, filter_type=filter_type
    )
    assert spectrum_f.sum() < spectrum.sum()


def test_apply_frequency_lowpass_unknown_filter_raises(clean_image):
    with pytest.raises(ValueError):
        filters.apply_frequency_lowpass(clean_image, filter_type="not_a_filter")


def test_apply_frequency_lowpass_preserves_mean_brightness(clean_image):
    img_back, _, _ = filters.apply_frequency_lowpass(
        clean_image, cutoff_ratio=0.3, filter_type="gauss"
    )
    assert img_back.mean() == pytest.approx(clean_image.mean(), abs=1e-6)


def test_load_medical_image_png_roundtrip(clean_image):
    ok, buf = cv2.imencode(".png", filters._to_uint8(clean_image))
    assert ok
    result = filters.load_medical_image(_FakeUploadedFile("scan.png", buf.tobytes()))
    assert result.shape == clean_image.shape
    assert result.min() >= 0.0 and result.max() <= 1.0


def test_load_medical_image_corrupt_file_raises_value_error():
    with pytest.raises(ValueError):
        filters.load_medical_image(_FakeUploadedFile("broken.png", b"not an image"))


def test_load_dicom_applies_hu_rescale_and_clinical_window(monkeypatch):
    raw = np.array([[1024, 1424], [1064, 2024]], dtype=np.int16)
    fake_ds = _fake_dicom_dataset(
        pixel_array=raw,
        RescaleSlope=1.0,
        RescaleIntercept=-1024.0,
        PhotometricInterpretation="MONOCHROME2",
        WindowCenter=40.0,
        WindowWidth=400.0,
    )
    monkeypatch.setattr(filters.pydicom, "dcmread", lambda *_: fake_ds)

    result = filters.load_medical_image("fake_ct.dcm")
    assert result.shape == raw.shape
    assert result.min() >= 0.0 and result.max() <= 1.0
    assert result[0, 0] == pytest.approx(0.4, abs=1e-6)


def test_load_dicom_monochrome1_inverts_using_bits_stored(monkeypatch):
    raw = np.array([[0, 4095]], dtype=np.int16)
    fake_ds = _fake_dicom_dataset(
        pixel_array=raw,
        RescaleSlope=1.0,
        RescaleIntercept=0.0,
        PhotometricInterpretation="MONOCHROME1",
        BitsStored=12,
    )
    monkeypatch.setattr(filters.pydicom, "dcmread", lambda *_: fake_ds)

    result = filters.load_medical_image("fake_mono1.dcm")
    assert result[0, 0] > result[0, 1]


def test_load_dicom_multiframe_keeps_first_frame(monkeypatch):
    frame = np.full((16, 16), 100, dtype=np.int16)
    fake_ds = _fake_dicom_dataset(
        pixel_array=np.stack([frame, frame + 500]),
        RescaleSlope=1.0,
        RescaleIntercept=0.0,
        PhotometricInterpretation="MONOCHROME2",
    )
    monkeypatch.setattr(filters.pydicom, "dcmread", lambda *_: fake_ds)

    result = filters.load_medical_image("fake_multiframe.dcm")
    assert result.ndim == 2
    assert result.shape == frame.shape


if __name__ == "__main__":
    pytest.main([__file__, "-v"])