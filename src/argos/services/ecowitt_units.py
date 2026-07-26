from __future__ import annotations


def fahrenheit_to_celsius(value_f: float) -> float:
    return (value_f - 32.0) * 5.0 / 9.0


def inhg_to_hpa(value_inhg: float) -> float:
    return value_inhg * 33.8638866667


def mph_to_mps(value_mph: float) -> float:
    return value_mph * 0.44704


def inches_to_mm(value_in: float) -> float:
    return value_in * 25.4
