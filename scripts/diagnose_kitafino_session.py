r"""Safely diagnose the Kitafino login/session hand-off.

Credentials are read from KITAFINO_USERNAME and KITAFINO_PASSWORD. The script
prints only classified metadata; response bodies, cookie values, credentials,
headers, and full URLs are never emitted or persisted.

Git Bash:
    export KITAFINO_USERNAME='...'
    read -rsp 'Kitafino password: ' KITAFINO_PASSWORD && export KITAFINO_PASSWORD
    .venv/Scripts/python.exe scripts/diagnose_kitafino_session.py

PowerShell:
    $env:KITAFINO_USERNAME = '...'
    $env:KITAFINO_PASSWORD = Read-Host 'Kitafino password'
    .\.venv\Scripts\python.exe scripts\diagnose_kitafino_session.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Iterable
from http.cookies import Morsel
from typing import Any
from urllib.parse import urljoin, urlsplit

LOGIN_URL = "https://auth.kitafino.de/sys_k2/index.php?action=do_login"
MEAL_PLAN_URL = "https://user.kitafino.de/sys_k2/index.php?action=bestellen"
USER_AGENT = "Mozilla/5.0 (Home Assistant Kitafino Meal Plan)"
TIMEOUT_SECONDS = 15


def _host_category(url_or_host: object) -> str:
    """Map a URL or hostname to a non-sensitive Kitafino host category."""
    value = str(url_or_host).strip().lower()
    try:
        hostname = urlsplit(value if "://" in value else f"//{value}").hostname
    except ValueError:
        return "other"
    if hostname == "auth.kitafino.de":
        return "auth"
    if hostname == "user.kitafino.de":
        return "user"
    return "other"


def _domain_category(domain: object) -> str:
    """Map a cookie domain without returning the raw value."""
    normalized = str(domain).strip().lower().lstrip(".")
    if normalized == "kitafino.de":
        return "kitafino_parent"
    if normalized == "auth.kitafino.de":
        return "auth_host"
    if normalized == "user.kitafino.de":
        return "user_host"
    return "other"


def _redirects(history: Iterable[Any]) -> list[dict[str, object]]:
    """Return status and classified destination host for redirect responses."""
    result: list[dict[str, object]] = []
    for response in history:
        location = response.headers.get("Location", "")
        destination = urljoin(str(response.url), location) if location else response.url
        result.append(
            {
                "status": int(response.status),
                "destination_host": _host_category(destination),
            }
        )
    return result


def _cookie_summary(cookies: Iterable[Morsel[str]]) -> dict[str, object]:
    """Summarize cookie scope without exposing cookie names or values."""
    cookie_list = list(cookies)
    session_cookies = [
        cookie for cookie in cookie_list if cookie.key.upper() == "PHPSESSID"
    ]
    return {
        "count": len(cookie_list),
        "php_session_present": bool(session_cookies),
        "php_session_domain_categories": sorted(
            {_domain_category(cookie["domain"]) for cookie in session_cookies}
        ),
    }


def _eligible_cookie_summary(cookies: Iterable[Morsel[str]]) -> dict[str, object]:
    """Summarize cookies selected for a request without claiming stored scope."""
    cookie_list = list(cookies)
    return {
        "count": len(cookie_list),
        "php_session_present": any(
            cookie.key.upper() == "PHPSESSID" for cookie in cookie_list
        ),
    }


def _login_marker_source(url: object, text: str) -> str:
    """Classify why a response appears to be a login page."""
    lowered_url = str(url).lower()
    lowered_text = text.lower()
    url_marker = "action=login" in lowered_url
    password_marker = (
        'name="passwort"' in lowered_text or 'id="passwort"' in lowered_text
    )
    if url_marker and password_marker:
        return "url_and_password_marker"
    if url_marker:
        return "url_marker"
    if password_marker:
        return "password_marker"
    return "none"


async def _run(username: str, password: str) -> dict[str, object]:
    """Execute the production-equivalent request sequence."""
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
    payload = {
        "benutzername": username,
        "passwort": password,
        "login": "Anmelden",
    }
    async with aiohttp.ClientSession(
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    ) as session:
        async with session.post(LOGIN_URL, data=payload) as response:
            login_text = await response.text(errors="replace")
            login = {
                "status": response.status,
                "final_host": _host_category(response.url),
                "redirects": _redirects(response.history),
                "login_marker": _login_marker_source(response.url, login_text),
            }

        stored_cookies = _cookie_summary(session.cookie_jar)
        eligible_cookies = _eligible_cookie_summary(
            session.cookie_jar.filter_cookies(MEAL_PLAN_URL).values()
        )

        async with session.get(MEAL_PLAN_URL) as response:
            meal_text = await response.text(errors="replace")
            meal_plan = {
                "status": response.status,
                "final_host": _host_category(response.url),
                "redirects": _redirects(response.history),
                "login_marker": _login_marker_source(response.url, meal_text),
            }

    return {
        "diagnostic_version": 1,
        "login": login,
        "cookies_after_login": stored_cookies,
        "cookies_eligible_for_user_host": eligible_cookies,
        "meal_plan": meal_plan,
    }


def main() -> int:
    """Run the safe diagnostic CLI."""
    username = os.environ.get("KITAFINO_USERNAME", "").strip()
    password = os.environ.get("KITAFINO_PASSWORD", "").strip()
    if not username or not password:
        print(
            json.dumps(
                {
                    "error": "missing_credentials",
                    "required_environment_variables": [
                        "KITAFINO_USERNAME",
                        "KITAFINO_PASSWORD",
                    ],
                },
                sort_keys=True,
            )
        )
        return 2

    try:
        result = asyncio.run(_run(username, password))
    except ModuleNotFoundError as err:
        if err.name != "aiohttp":
            raise
        print(json.dumps({"error": "aiohttp_not_installed"}, sort_keys=True))
        return 3
    except (TimeoutError, asyncio.TimeoutError):
        print(json.dumps({"error": "timeout"}, sort_keys=True))
        return 4
    except OSError:
        print(json.dumps({"error": "network_error"}, sort_keys=True))
        return 5
    except Exception as err:  # aiohttp is intentionally imported only at runtime
        if err.__class__.__module__.startswith("aiohttp"):
            print(json.dumps({"error": "http_client_error"}, sort_keys=True))
            return 5
        raise

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
