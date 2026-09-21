"""
Submit the CAMS Consolidated Account Statement (CAS) request form.

The CAS PDF is emailed to the address registered in your MF folios.
This script only fills and submits the public form — no login involved.

The form requires a "PDF password" the user picks; CAMS uses it to encrypt
the emailed PDF. We default this to the account's login email (the user can
override in Settings).
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

from analytics.accounts import AccountContext, app_config

ROOT = Path(__file__).resolve().parent.parent
DEBUG_DIR = ROOT / "debug"

CAS_URL = "https://www.camsonline.com/Investors/Statements/Consolidated-Account-Statement"


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


# The CAMS form hides behind up to three overlays on a cold visit: a ConsenPro
# cookie banner, an optional Disclaimer modal, and a rotating "<AMC> Mutual Fund
# is now live!" promo dialog. CAMS adds and drops these without notice, so every
# dismissal here is best-effort and must never raise — an overlay that isn't
# there is the normal case, not a failure.


def _click_first(page: Page, selectors, timeout: int = 1500) -> bool:
    for sel in selectors:
        try:
            page.locator(sel).first.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False


# The Disclaimer and the promo are the same Angular component (app-camsterms)
# in the same container class, so they're told apart by the ACCEPT radio that
# only the Disclaimer has. Matching on the *word* "Disclaimer" does not work:
# the page footer links to "Disclaimer & Terms of Use", so a text match hits
# even when no modal is open — we'd then hunt for an ACCEPT radio that isn't
# there and die on its click timeout.
DISCLAIMER_DIALOG = 'mat-dialog-container:has(input[value="ACCEPT"])'
PROMO_DIALOG = 'mat-dialog-container:not(:has(input[value="ACCEPT"]))'


def dismiss_cookie_banner(page: Page, timeout: int = 3000) -> None:
    """ConsenPro cookie banner (#cc-main), bottom-right. "Essential only" is
    enough to dismiss it and keeps us out of the analytics cookie buckets."""
    banner = page.locator("#cc-main .cm").first
    try:
        banner.wait_for(state="visible", timeout=timeout)
    except PWTimeout:
        return
    print("-> cookie banner detected; accepting essential only")
    _click_first(page, (
        '#cc-main button.cm__btn[data-role="necessary"]',
        '#cc-main button.cm__btn[data-role="all"]',
    ))
    try:
        banner.wait_for(state="hidden", timeout=4000)
    except PWTimeout:
        print("   warning: cookie banner still showing; continuing anyway")


def dismiss_disclaimer(page: Page, timeout: int = 3000) -> None:
    """Disclaimer modal (shown when no consent cookie is set): select the
    ACCEPT radio, then click PROCEED."""
    dialog = page.locator(DISCLAIMER_DIALOG).first
    try:
        dialog.wait_for(state="visible", timeout=timeout)
    except PWTimeout:
        return
    print("-> Disclaimer modal detected; accepting")
    _click_first(page, (
        f'{DISCLAIMER_DIALOG} mat-radio-button:has(input[value="ACCEPT"]) .mat-radio-container',
        f'{DISCLAIMER_DIALOG} mat-radio-button:has(input[value="ACCEPT"])',
    ))
    page.wait_for_timeout(300)
    _click_first(page, (f'{DISCLAIMER_DIALOG} button:has-text("PROCEED")',), timeout=3000)
    try:
        dialog.wait_for(state="hidden", timeout=5000)
    except PWTimeout:
        print("   warning: Disclaimer modal still showing; continuing anyway")


def dismiss_promo(page: Page, timeout: int = 3000) -> None:
    """Close the promo dialog (e.g. "ASK Mutual Fund is now live!") — a banner
    image with one close icon and no accept/decline. Its modal backdrop
    swallows clicks on the form underneath, so this has to go before we touch
    any field."""
    dialog = page.locator(PROMO_DIALOG).first
    try:
        dialog.wait_for(state="visible", timeout=timeout)
    except PWTimeout:
        return
    print("-> promo popup detected; closing")
    _click_first(page, (
        f"{PROMO_DIALOG} mat-icon.close-popup",
        f"{PROMO_DIALOG} .closeicon",
        f"{PROMO_DIALOG} .close-icon",
        f"{PROMO_DIALOG} [aria-label='Close']",
    ))
    # If no close control matched, Escape dismisses a mat-dialog too.
    try:
        if dialog.is_visible():
            page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        dialog.wait_for(state="hidden", timeout=4000)
    except PWTimeout:
        print("   warning: promo popup may still be open; continuing anyway")


def clear_overlays(page: Page, rounds: int = 3, timeout: int = 3000) -> None:
    """Clear whatever is covering the form, in whatever order CAMS stacked it.
    Loops because closing one overlay can reveal the next, and returns as soon
    as no dialog is left so a clean page costs one pass, not `rounds`."""
    for _ in range(rounds):
        dismiss_cookie_banner(page, timeout=timeout)
        dismiss_disclaimer(page, timeout=timeout)
        dismiss_promo(page, timeout=timeout)
        page.wait_for_timeout(400)
        dialogs = page.locator("mat-dialog-container")
        if not dialogs.count() or not dialogs.first.is_visible():
            return


def submit_cas_request(page: Page, ctx: AccountContext, *, dry_run: bool) -> None:
    email = ctx.email
    pdf_password = ctx.pdf_password
    from_date = _coerce_date(ctx.from_date)
    to_date = date.today()

    print(f"-> opening {CAS_URL}")
    page.goto(CAS_URL, wait_until="networkidle")
    dump_debug(page, "01_loaded")

    clear_overlays(page)
    dump_debug(page, "02_after_cookie")

    for sel in ["button[aria-label='Close']", ".close-chat", "#chat-close"]:
        try:
            page.locator(sel).first.click(timeout=1500)
            break
        except Exception:
            continue

    tile = page.get_by_text("CAS - CAMS+ KFintech", exact=False).first
    if tile.is_visible():
        try:
            tile.click(timeout=3000)
        except PWTimeout:
            pass

    def click_radio(
        value: str,
        description: str,
        label: str | None = None,
        prefer_label: bool = False,
    ) -> None:
        """Select a mat-radio-button. Matches by input value="..." by default;
        set prefer_label=True to match the visible label text first (use this
        where CAMS reuses/swaps the value= codes, e.g. the folio-listing group
        where "N"/"Y" have flipped meanings between form revisions)."""
        print(f"-> selecting {description}")
        by_label = (
            page.locator("mat-radio-button", has_text=label).first if label else None
        )
        by_value = page.locator(f'mat-radio-button:has(input[value="{value}"])')
        primary, secondary = (
            (by_label, by_value) if prefer_label and by_label else (by_value, by_label)
        )
        try:
            primary.wait_for(state="attached", timeout=15_000)
            primary.click(force=True)
            return
        except PWTimeout:
            pass
        # primary selector failed (CAMS may have renamed/swapped it); capture the
        # live DOM and fall back to the other matching strategy.
        dump_debug(page, f"radio_fail_{value}")
        if secondary is not None:
            print(f"   primary match failed; falling back for {description!r}")
            secondary.wait_for(state="attached", timeout=15_000)
            secondary.click(force=True)
            return
        raise PWTimeout(
            f"radio value={value!r} ({description}) not found; see debug/radio_fail_{value}.html"
        )

    click_radio("detailed", "Detailed statement type", label="Detailed")
    page.wait_for_timeout(800)
    dump_debug(page, "after_detailed")

    # Selecting "detailed" reveals the Period radios (formcontrolname
    # "request_flag": CF/PF/SP, defaulting to CF) plus From/To date inputs.
    # Choose SP (Specific Period) so we can set an explicit date range.
    click_radio("SP", "Specific Period")
    page.wait_for_timeout(800)
    dump_debug(page, "after_sp")

    def fill_date(control: str, value: str, description: str) -> None:
        print(f"-> filling {description}: {value}")
        page.locator(f'input[formcontrolname="{control}"]').evaluate(
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

    fill_date("from_date", _form_date(from_date), "From date")
    fill_date("to_date", _form_date(to_date), "To date")

    # CAMS has swapped the folio-listing value codes between revisions
    # (value="N" once meant "Without", now means "With"), so match the stable
    # visible label rather than the volatile code.
    click_radio(
        "N",
        "With zero balance folios",
        label="With zero balance folios",
        prefer_label=True,
    )

    print(f"-> filling email: {email}")
    page.locator('input[formcontrolname="email_id"]').fill(email)

    print("-> filling password (twice)")
    page.locator("#password").fill(pdf_password)
    page.locator("#confirmPassword").fill(pdf_password)

    # A promo dialog can land late, after the form is already filled; its
    # backdrop would eat the Submit click. Re-check with short timeouts.
    clear_overlays(page, rounds=2, timeout=800)

    dump_debug(page, "before_submit")

    if dry_run:
        print("-> DRY RUN: form is filled but Submit will NOT be clicked.")
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
    try:
        body = response.text() or ""
    except Exception:
        body = ""
    page.wait_for_timeout(2500)
    dump_debug(page, "after_submit")
    DEBUG_DIR.mkdir(exist_ok=True)
    (DEBUG_DIR / "after_submit_response.txt").write_text(
        f"HTTP {response.status}\n\n{body}"
    )

    snippet = body.strip().replace("\n", " ")[:300]

    if response.status >= 400:
        suffix = f" — response: {snippet}" if snippet else ""
        raise RuntimeError(
            f"CAMS rejected the request (HTTP {response.status}). "
            f"Usually a CAMS-side rate limit or transient error — wait and retry.{suffix}"
        )

    # Strict success: require a positive signal, not just absence of failure.
    # CAMS can return 200 on captcha block / silent rejection — we should NOT
    # tell the user "submitted" unless we have actual confirmation.
    body_lower = body.lower()
    body_success_signals = (
        '"success":true', '"status":"success"', '"status":"ok"',
        "request has been", "email has been sent", "successfully submitted",
        "request received", "request submitted",
    )
    has_body_success = any(s in body_lower for s in body_success_signals)

    has_dom_success = False
    if not has_body_success:
        success_re = (
            "/Thank you|request has been|email has been sent|"
            "will be sent to|successfully submitted|received your request|"
            "dispatched|sent to your registered/i"
        )
        try:
            page.wait_for_selector(f"text={success_re}", timeout=8000)
            has_dom_success = True
        except PWTimeout:
            pass

    if not (has_body_success or has_dom_success):
        raise RuntimeError(
            "Couldn't submit the CAS request to CAMS this time. "
            "Try clicking **Refresh CAS** again in a minute.\n\n"
            "If this keeps happening, submit the form yourself here:\n"
            f"  {CAS_URL}\n\n"
            "Use the same CAS PDF password you've set in this app's settings — "
            "otherwise the emailed PDF won't open here.\n\n"
            "Once CAMS emails you the statement, come back and click "
            "**Process inbox** to load it."
        )
    print(f"-> submit confirmed via {'API body' if has_body_success else 'page text'}")


def submit_via_playwright(ctx: AccountContext, *, dry_run: bool = False, headless: bool | None = None) -> dict:
    """Run the full CAMS form submission and return a status dict.

    Parameters
    ----------
    ctx : AccountContext
        Which CAS account to submit for (provides email + PDF password).
    dry_run : bool
        Fill the form but don't click Submit. Default False.
    headless : bool | None
        Override the playwright.headless setting from config.yaml.
    """
    pw_cfg = app_config().get("playwright") or {}
    is_headless = pw_cfg.get("headless", True) if headless is None else headless

    with sync_playwright() as p:
        # Use the real installed Chrome (channel="chrome") rather than the
        # bundled Chromium build, and strip the most obvious automation tells.
        # reCAPTCHA on the CAMS form scores Playwright Chromium as a bot even
        # in headed mode because `navigator.webdriver === true` and the
        # `--enable-automation` flag are visible; the args + init script below
        # patch those out so the captcha is more likely to mint a token silently.
        # Falls back to bundled Chromium if Chrome isn't installed locally.
        launch_args = dict(
            headless=is_headless,
            slow_mo=pw_cfg.get("slow_mo_ms", 0) if not is_headless else 0,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
                "--no-first-run",
            ],
        )
        try:
            browser = p.chromium.launch(channel="chrome", **launch_args)
        except Exception:
            browser = p.chromium.launch(**launch_args)

        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="en-IN",
        )
        # Hide `navigator.webdriver` (reCAPTCHA's single most popular check).
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = context.new_page()
        try:
            submit_cas_request(page, ctx, dry_run=dry_run)
            return {"ok": True, "submitted": not dry_run}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            browser.close()
