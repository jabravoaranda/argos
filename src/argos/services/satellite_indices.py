from __future__ import annotations

import math

VALID_SCL_CLASSES = {4, 5}
INVALID_SCL_CLASSES = {0, 1, 3, 6, 8, 9, 10, 11}
PROCESSING_VERSION = "s2-indices-v1"
SENTINEL_2_SOURCE_CODE = "copernicus_sentinel_2_l2a"
SENTINEL_2_COLLECTION = "sentinel-2-l2a"
SENTINEL_1_SOURCE_CODE = "copernicus_sentinel_1_grd"
SENTINEL_1_COLLECTION = "sentinel-1-grd"
SATELLITE_METRICS = ("ndvi", "savi", "ndre", "ndmi")


def safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0 or not math.isfinite(numerator) or not math.isfinite(denominator):
        return math.nan
    return numerator / denominator


def ndvi(*, b08: float, b04: float) -> float:
    return safe_ratio(b08 - b04, b08 + b04)


def savi(*, b08: float, b04: float) -> float:
    return 1.5 * safe_ratio(b08 - b04, b08 + b04 + 0.5)


def ndre(*, b8a: float, b05: float) -> float:
    return safe_ratio(b8a - b05, b8a + b05)


def ndmi(*, b08: float, b11: float) -> float:
    return safe_ratio(b08 - b11, b08 + b11)


def is_valid_sentinel_2_sample(*, data_mask: int, scl: int) -> bool:
    return data_mask == 1 and scl in VALID_SCL_CLASSES and scl not in INVALID_SCL_CLASSES


def quality_status(
    valid_pixel_fraction: float,
    *,
    valid_threshold: float,
    partial_threshold: float,
) -> str:
    if valid_pixel_fraction >= valid_threshold:
        return "valid"
    if valid_pixel_fraction >= partial_threshold:
        return "partial"
    return "invalid"
