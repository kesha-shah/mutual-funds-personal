"""
Submit the CAMS Consolidated Account Statement (CAS) request form.

The CAS PDF is emailed to the address registered in your MF folios.
This script only fills and submits the public form — no login involved.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

import yaml
from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
DEBUG_DIR = ROOT / "debug"

CAS_URL = "https://www.camsonline.com/Investors/Statements/Consolidated-Account-Statement"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(
            f"Missing {CONFIG_PATH}. Copy config.example.yaml to config.yaml and fill it in."
        )
    from analytics.accounts import load_config as _load
    return _load()


def dump_debug(page: Page, tag: str) -> None:
    DEBUG_DIR.mkdir(exist_ok=True)
    page.screenshot(path=str(DEBUG_DIR / f"{tag}.png"), full_page=True)
    (DEBUG_DIR / f"{tag}.html").write_text(page.content())
    print(f"  [debug] saved debug/{tag}.png and debug/{tag}.html")


def _coerce_date(value, fallback_today: bool = False) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        if fallback_today and value.strip().lower() == "today":
            return date.today()
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    raise ValueError(f"Cannot interpret date: {value!r}")


def _form_date(d: date) -> str:
    # CAMS form uses DD-MMM-YYYY (e.g. 04-May-2026)
    return d.strftime("%d-%b-%Y")


def dismiss_disclaimer(page: Page) -> None:
    """CAMS shows a Disclaimer modal on first visit (no cookies set):
    select the ACCEPT radio, then click PROCEED."""
    try:
        page.wait_for_selector("text=Disclaimer", timeout=5000)
    except PWTimeout:
        return  # no disclaimer (cookies already set in this context)

    print("-> Disclaimer modal detected; accepting")
    # Click the radio's circle (.mat-radio-container) — clicking the label
    # would hit the embedded "Terms" / "Privacy Policy" links instead.
    page.locator(
        'mat-radio-button:has(input[value="ACCEPT"]) .mat-radio-container'
    ).click()
    page.wait_for_timeout(300)
    page.get_by_role("button", name="PROCEED").click()
    # Wait for the modal to disappear before continuing.
    try:
        page.wait_for_selector("text=Disclaimer", state="hidden", timeout=5000)
    except PWTimeout:
        pass
    page.wait_for_timeout(500)


def submit_cas_request(page: Page, cfg: dict) -> None:
    cams = cfg["cams"]
    email = cams["email"]
    pdf_password = cams["pdf_password"]
    from_date = _coerce_date(cams["from_date"])
    to_date = _coerce_date(cams["to_date"], fallback_today=True)
    dry_run = bool(cams.get("dry_run", True))

    print(f"-> opening {CAS_URL}")
    page.goto(CAS_URL, wait_until="networkidle")
    dump_debug(page, "01_loaded")

    dismiss_disclaimer(page)
    dump_debug(page, "02_after_cookie")

    # CAMS embeds a chat widget (cdk-overlay-container) that intercepts clicks.
    # Dismiss it if it auto-opened.
    for sel in ["button[aria-label='Close']", ".close-chat", "#chat-close"]:
        try:
            page.locator(sel).first.click(timeout=1500)
            break
        except Exception:
            continue

    # Tile grid: pick "CAS - CAMS+ KFintech" if not already active.
    tile = page.get_by_text("CAS - CAMS+ KFintech", exact=False).first
    if tile.is_visible():
        try:
            tile.click(timeout=3000)
        except PWTimeout:
            pass

    def click_radio(value: str, description: str) -> None:
        print(f"-> selecting {description} (value={value})")
        page.locator(f'mat-radio-button:has(input[value="{value}"])').click(force=True)

    click_radio("detailed", "Detailed statement type")
    page.wait_for_timeout(800)

    # Specific Period unlocks the From/To date inputs.
    click_radio("SP", "Specific Period")
    page.wait_for_timeout(800)
    dump_debug(page, "after_sp")

    # Material datepicker inputs stay readonly even when enabled. Set the
    # value via JS and fire Angular-friendly events so the FormControl picks it up.
    def fill_date(input_id: str, value: str, description: str) -> None:
        print(f"-> filling {description}: {value}")
        page.locator(f"input#{input_id}").evaluate(
            """(el, val) => {
                el.removeAttribute('readonly');
                el.removeAttribute('disabled');
                el.value = val;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            }""",
            value,
        )

    fill_date("fromDate_new", _form_date(from_date), "From date")
    fill_date("to-date-input", _form_date(to_date), "To date")

    click_radio("N", "Without zero balance folios")

    print(f"-> filling email: {email}")
    page.locator('input[formcontrolname="email_id"]').fill(email)

    print("-> filling password (twice)")
    page.locator("#password").fill(pdf_password)
    page.locator("#confirmPassword").fill(pdf_password)

    dump_debug(page, "before_submit")

    if dry_run:
        print("-> DRY RUN: form is filled but Submit will NOT be clicked.")
        print("   Set cams.dry_run: false in config.yaml to actually submit.")
        page.wait_for_timeout(2000)
        return

    print("-> clicking Submit and waiting for /api/v1/camsonline response")
    with page.expect_response(
        lambda r: "api/v1/camsonline" in r.url and r.request.method == "POST",
        timeout=90_000,
    ) as resp_info:
        page.get_by_role("button", name="Submit").click(force=True)

    response = resp_info.value
    print(f"   API status: {response.status}")
    # Give the UI a moment to render the success/failure dialog.
    page.wait_for_timeout(2000)
    dump_debug(page, "after_submit")


def submit_via_playwright(force: bool = False, headless: bool | None = None) -> dict:
    """Run the full CAMS form submission and return a status dict.

    Parameters
    ----------
    force : bool
        If True, override config's ``cams.dry_run`` and actually click Submit.
        Use this when invoking from the UI.
    headless : bool | None
        Override config's playwright.headless. None = use config.
    """
    cfg = load_config()
    if force:
        cfg = {**cfg, "cams": {**cfg["cams"], "dry_run": False}}
    pw_cfg = cfg.get("playwright", {})
    is_headless = pw_cfg.get("headless", False) if headless is None else headless

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=is_headless,
            slow_mo=pw_cfg.get("slow_mo_ms", 0) if not is_headless else 0,
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="en-IN",
        )
        page = context.new_page()
        try:
            submit_cas_request(page, cfg)
            return {
                "ok": True,
                "submitted": not cfg["cams"].get("dry_run", True),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            browser.close()


def main() -> None:
    result = submit_via_playwright()
    if not result.get("ok"):
        sys.exit(result.get("error") or "submission failed")


if __name__ == "__main__":
    main()
