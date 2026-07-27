from __future__ import annotations

import math

import pytest

from argos.services.satellite_indices import (
    is_valid_sentinel_2_sample,
    ndmi,
    ndre,
    ndvi,
    quality_status,
    safe_ratio,
    savi,
)


def test_satellite_indices_use_expected_formulas() -> None:
    assert ndvi(b08=0.8, b04=0.2) == pytest.approx(0.6)
    assert savi(b08=0.8, b04=0.2) == pytest.approx(0.6)
    assert ndre(b8a=0.6, b05=0.2) == pytest.approx(0.5)
    assert ndmi(b08=0.7, b11=0.3) == pytest.approx(0.4)


def test_safe_ratio_returns_nan_for_zero_denominator() -> None:
    assert math.isnan(safe_ratio(1.0, 0.0))


def test_sentinel_2_sample_mask_accepts_only_documented_valid_classes() -> None:
    assert is_valid_sentinel_2_sample(data_mask=1, scl=4)
    assert is_valid_sentinel_2_sample(data_mask=1, scl=5)
    assert not is_valid_sentinel_2_sample(data_mask=1, scl=9)
    assert not is_valid_sentinel_2_sample(data_mask=0, scl=4)


def test_quality_status_thresholds() -> None:
    assert quality_status(0.50, valid_threshold=0.50, partial_threshold=0.20) == "valid"
    assert quality_status(0.30, valid_threshold=0.50, partial_threshold=0.20) == "partial"
    assert quality_status(0.10, valid_threshold=0.50, partial_threshold=0.20) == "invalid"
