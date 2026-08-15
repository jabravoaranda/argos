from __future__ import annotations

import re
from urllib.error import URLError
from urllib.request import urlopen

import pytest

pytest.importorskip("playwright")


ARGOS_DASHBOARD_URL = "http://localhost:8501"


def argos_dashboard_is_running() -> bool:
    try:
        with urlopen(ARGOS_DASHBOARD_URL, timeout=3) as response:
            return response.status < 500
    except URLError:
        return False
    except TimeoutError:
        return False


def test_argos_dashboard_valves_has_no_horizontal_overflow(page) -> None:
    if not argos_dashboard_is_running():
        pytest.skip("ARGOS Streamlit dashboard is not running at http://localhost:8501")

    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(ARGOS_DASHBOARD_URL, wait_until="domcontentloaded")
    page.get_by_test_id("stSidebar").wait_for()
    expect_sidebar = page.get_by_test_id("stSidebar")
    assert expect_sidebar.is_visible()

    page.get_by_role("button", name=re.compile(r"\bVálvulas\b")).first.click()
    page.get_by_text("Electroválvulas").first.wait_for(state="visible", timeout=10_000)

    has_horizontal_overflow = page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth",
    )
    assert has_horizontal_overflow is False


def test_argos_dashboard_home_header_clears_streamlit_toolbar(page) -> None:
    if not argos_dashboard_is_running():
        pytest.skip("ARGOS Streamlit dashboard is not running at http://localhost:8501")

    page.set_viewport_size({"width": 1909, "height": 1009})
    page.goto(ARGOS_DASHBOARD_URL, wait_until="domcontentloaded")
    page.get_by_test_id("stSidebar").wait_for()
    page.get_by_role("button", name=re.compile(r"\bInicio\b")).first.click()
    page.locator(".argos-top-shell").wait_for()

    header_bottom, shell_top = page.evaluate(
        """() => {
            const toolbar = document.querySelector('header[data-testid="stHeader"]');
            const shell = document.querySelector('.argos-top-shell');
            return [
                toolbar ? toolbar.getBoundingClientRect().bottom : 0,
                shell ? shell.getBoundingClientRect().top : -1,
            ];
        }""",
    )
    assert shell_top >= header_bottom
