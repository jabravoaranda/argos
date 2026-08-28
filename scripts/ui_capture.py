from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


DEFAULT_VIEWPORTS = {
    "1920x1080": (1920, 1080),
    "1600x900": (1600, 900),
    "1366x768": (1366, 768),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture and minimally validate the ARGOS Streamlit UI. ARGOS must already be running.",
    )
    parser.add_argument("--url", default="http://localhost:8501", help="ARGOS dashboard URL.")
    parser.add_argument("--browser", choices=("chromium", "firefox"), default="firefox")
    parser.add_argument("--page", default="Válvulas", help="Visible sidebar page button to click before capture.")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--device-scale-factor", type=float, default=1.0)
    parser.add_argument("--wait-ms", type=int, default=1_000, help="Extra wait after page navigation before validation/capture.")
    parser.add_argument("--output", type=Path, default=Path("artifacts/ui/argos-ui.png"))
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="Capture the initial viewport matrix: 1920x1080, 1600x900 and 1366x768.",
    )
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    return parser.parse_args()


def click_sidebar_page(page: Page, page_name: str, timeout_ms: int) -> None:
    button = page.get_by_role("button", name=re.compile(rf"\b{re.escape(page_name)}\b")).first
    button.wait_for(state="visible", timeout=timeout_ms)
    page.wait_for_function(
        """
        (name) => [...document.querySelectorAll('button')]
            .some((button) => (button.innerText || '').includes(name) && !button.disabled)
        """,
        arg=page_name,
        timeout=timeout_ms,
    )
    button.click(timeout=timeout_ms)
    wait_for_argos_page(page, page_name, timeout_ms)


def wait_for_argos_ready(page: Page, timeout_ms: int) -> None:
    page.wait_for_function(
        """
        () => {
            const main = document.querySelector('[data-testid="stMainBlockContainer"]');
            return main && (main.innerText || '').trim().length > 0;
        }
        """,
        timeout=timeout_ms,
    )


def wait_for_argos_page(page: Page, page_name: str, timeout_ms: int) -> None:
    expected_text = "Electroválvulas" if page_name.casefold() in {"válvulas", "valvulas"} else page_name
    page.get_by_text(expected_text).first.wait_for(state="visible", timeout=timeout_ms)
    page.wait_for_timeout(750)


def has_horizontal_overflow(page: Page) -> bool:
    return bool(
        page.evaluate(
            """
            () => document.documentElement.scrollWidth > document.documentElement.clientWidth
            """
        )
    )


def viewport_metrics(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => ({
            href: window.location.href,
            userAgent: navigator.userAgent,
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight,
            devicePixelRatio: window.devicePixelRatio,
            visualViewportWidth: window.visualViewport ? window.visualViewport.width : null,
            visualViewportHeight: window.visualViewport ? window.visualViewport.height : null,
            documentClientWidth: document.documentElement.clientWidth,
            documentClientHeight: document.documentElement.clientHeight,
            documentScrollWidth: document.documentElement.scrollWidth,
            documentScrollHeight: document.documentElement.scrollHeight,
            bodyTextLength: (document.body.innerText || '').length,
        })
        """
    )


def overflowing_elements(page: Page) -> list[dict[str, Any]]:
    return page.evaluate(
        """
        () => {
            const viewportWidth = document.documentElement.clientWidth;
            const viewportHeight = document.documentElement.clientHeight;
            const selectors = [
                '[data-testid="stSidebar"]',
                '[data-testid="stAppViewContainer"]',
                '[data-testid="stMainBlockContainer"]',
                '[data-testid="stVerticalBlockBorderWrapper"]',
                '[data-testid="stPlotlyChart"]',
                'button'
            ];
            const seen = new Set();
            const out = [];
            for (const selector of selectors) {
                for (const element of document.querySelectorAll(selector)) {
                    if (seen.has(element)) continue;
                    seen.add(element);
                    const rect = element.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) continue;
                    const exceedsRight = rect.right > viewportWidth + 1;
                    const exceedsLeft = rect.left < -1;
                    if (exceedsRight || exceedsLeft) {
                        out.push({
                            tag: element.tagName.toLowerCase(),
                            testid: element.getAttribute('data-testid'),
                            text: (element.innerText || '').trim().slice(0, 80),
                            left: Math.round(rect.left),
                            right: Math.round(rect.right),
                            top: Math.round(rect.top),
                            bottom: Math.round(rect.bottom),
                            viewportWidth,
                            viewportHeight,
                        });
                    }
                }
            }
            return out.slice(0, 20);
        }
        """
    )


def valve_button_layout_errors(page: Page) -> list[str]:
    return page.evaluate(
        """
        () => {
            const errors = [];
            const targets = ['Abrir', 'Cerrar'];
            for (const target of targets) {
                const buttons = [...document.querySelectorAll('button')]
                    .filter((button) => {
                        const text = (button.innerText || '').replace(/\\s+/g, ' ').trim();
                        return new RegExp(`(^| )${target}( |$)`).test(text) && !text.includes('todo');
                    });
                if (buttons.length === 0) {
                    errors.push(`No visible button text found: ${target}`);
                    continue;
                }
                for (const [index, button] of buttons.entries()) {
                    const rect = button.getBoundingClientRect();
                    const style = window.getComputedStyle(button);
                    const text = (button.innerText || '').trim();
                    const isVisible = rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden';
                    if (!isVisible) errors.push(`${target} #${index + 1} is not visible`);
                    if (text.includes('\\n')) errors.push(`${target} #${index + 1} text is split across lines`);
                    if (button.scrollWidth > button.clientWidth + 1) {
                        errors.push(`${target} #${index + 1} text overflows horizontally`);
                    }
                    if (rect.width < 44) {
                        errors.push(`${target} #${index + 1} is too narrow: width=${Math.round(rect.width)}`);
                    }
                }
            }
            return errors;
        }
        """
    )


def validate_layout(page: Page, page_name: str) -> list[str]:
    errors: list[str] = []
    if has_horizontal_overflow(page):
        errors.append("Horizontal overflow detected: document scrollWidth exceeds clientWidth.")

    overflow = overflowing_elements(page)
    if overflow:
        errors.append(f"Elements exceed viewport: {overflow}")

    if page_name.casefold() in {"válvulas", "valvulas"}:
        errors.extend(valve_button_layout_errors(page))

    return errors


def capture_one(
    *,
    browser_name: str,
    url: str,
    page_name: str,
    width: int,
    height: int,
    output: Path,
    timeout_ms: int,
    device_scale_factor: float,
    wait_ms: int,
) -> list[str]:
    output.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser_type = getattr(playwright, browser_name)
        browser = browser_type.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=device_scale_factor,
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_selector('[data-testid="stSidebar"]', timeout=timeout_ms)
            wait_for_argos_ready(page, timeout_ms)
            click_sidebar_page(page, page_name, timeout_ms)
            page.wait_for_timeout(wait_ms)
            errors = validate_layout(page, page_name)
            page.screenshot(path=output, full_page=False)
            metrics_path = output.with_suffix(f"{output.suffix}.json")
            metrics_path.write_text(
                json.dumps(viewport_metrics(page), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return errors
        finally:
            browser.close()


def matrix_output_path(base_output: Path, browser_name: str, width: int, height: int) -> Path:
    suffix = "".join(base_output.suffixes) or ".png"
    stem = base_output.name[: -len(suffix)] if base_output.name.endswith(suffix) else base_output.stem
    return base_output.with_name(f"{stem}-{browser_name}-{width}x{height}{suffix}")


def main() -> int:
    args = parse_args()
    viewports = DEFAULT_VIEWPORTS.values() if args.matrix else [(args.width, args.height)]
    all_errors: list[str] = []
    try:
        for width, height in viewports:
            output = matrix_output_path(args.output, args.browser, width, height) if args.matrix else args.output
            errors = capture_one(
                browser_name=args.browser,
                url=args.url,
                page_name=args.page,
                width=width,
                height=height,
                output=output,
                timeout_ms=args.timeout_ms,
                device_scale_factor=args.device_scale_factor,
                wait_ms=args.wait_ms,
            )
            print(f"Captured {args.browser} {width}x{height}: {output}")
            print(f"Metrics: {output.with_suffix(f'{output.suffix}.json')}")
            for error in errors:
                all_errors.append(f"{width}x{height}: {error}")
    except (PlaywrightError, PlaywrightTimeoutError) as exc:
        print(f"UI capture failed: {exc}", file=sys.stderr)
        return 2

    if all_errors:
        print("Layout validation failed:", file=sys.stderr)
        for error in all_errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
