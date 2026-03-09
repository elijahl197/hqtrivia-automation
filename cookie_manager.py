#!/usr/bin/env python3
"""
NYT-S Cookie Manager

Extracts and caches the NYT-S session cookie so you never have to
open DevTools manually. On first run (or when the cookie expires) a
headed browser window opens; you log in once and the cookie is saved
to ~/.nyt_mini_cookie for all future runs.
"""

import json
import time
from pathlib import Path

COOKIE_FILE = Path.home() / '.nyt_mini_cookie'
COOKIE_MAX_AGE = 60 * 60 * 23   # treat cookie as stale after 23 hours
LOGIN_TIMEOUT  = 180             # seconds to wait for the user to log in


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------

def _load_saved() -> str | None:
    """Return the cached cookie value if it exists and is still fresh."""
    if not COOKIE_FILE.exists():
        return None
    try:
        data = json.loads(COOKIE_FILE.read_text())
        age  = time.time() - data.get('saved_at', 0)
        if age < COOKIE_MAX_AGE:
            return data.get('value')
    except Exception:
        pass
    return None


def _save(value: str) -> None:
    """Write the cookie value and a timestamp to disk."""
    COOKIE_FILE.write_text(json.dumps({'value': value, 'saved_at': time.time()}))
    COOKIE_FILE.chmod(0o600)   # owner-read-only


# ---------------------------------------------------------------------------
# Browser automation
# ---------------------------------------------------------------------------

def _extract_via_browser() -> str:
    """
    Open a headed Chromium window.

    • If the user is already logged in the cookie is grabbed immediately.
    • Otherwise the NYT login page opens and we poll until the NYT-S
      cookie appears (i.e. the user has finished logging in).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "Playwright is not installed.\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        )

    print("Opening browser to extract your NYT-S cookie…")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx     = browser.new_context()
        page    = ctx.new_page()

        # Check whether the user is already logged in.
        page.goto('https://www.nytimes.com', wait_until='domcontentloaded')
        nyt_s = _find_nyt_s(ctx)

        if not nyt_s:
            # Redirect to login page and wait for the user.
            page.goto('https://myaccount.nytimes.com/auth/login',
                      wait_until='domcontentloaded')
            print("Please log in to nytimes.com in the browser window.")
            print(f"Waiting up to {LOGIN_TIMEOUT}s…")

            deadline = time.time() + LOGIN_TIMEOUT
            while time.time() < deadline:
                nyt_s = _find_nyt_s(ctx)
                if nyt_s:
                    break
                time.sleep(2)

        browser.close()

    if not nyt_s:
        raise SystemExit(
            "Timed out waiting for the NYT-S cookie. "
            "Did you finish logging in?"
        )

    print("Cookie captured successfully.")
    return nyt_s


def _find_nyt_s(ctx) -> str | None:
    """Return the NYT-S cookie value from the browser context, or None."""
    for cookie in ctx.cookies('https://www.nytimes.com'):
        if cookie['name'] == 'NYT-S':
            return cookie['value']
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_cookie(force_refresh: bool = False) -> str:
    """
    Return a valid NYT-S cookie.

    Uses the cached value if it is fresh; otherwise opens a browser window
    so the user can log in and captures the cookie automatically.

    Args:
        force_refresh: Ignore the cache and always open a fresh browser session.
    """
    if not force_refresh:
        cached = _load_saved()
        if cached:
            print(f"Using saved NYT-S cookie (cached at {COOKIE_FILE}).")
            return cached

    value = _extract_via_browser()
    _save(value)
    return value
