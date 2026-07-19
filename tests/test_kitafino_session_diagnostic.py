"""Tests for the safe local Kitafino session diagnostic."""

from __future__ import annotations

import importlib.util
from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace

from yarl import URL

SCRIPT = Path(__file__).parents[1] / "scripts" / "diagnose_kitafino_session.py"
SPEC = importlib.util.spec_from_file_location("kitafino_session_diagnostic", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)


def test_host_and_domain_values_are_classified() -> None:
    assert diagnostic._host_category("https://auth.kitafino.de/private") == "auth"
    assert diagnostic._host_category("user.kitafino.de") == "user"
    assert diagnostic._host_category("user.kitafino.de:443") == "user"
    assert diagnostic._host_category("attacker.example") == "other"
    assert diagnostic._host_category("https://[invalid") == "other"
    assert diagnostic._domain_category(".kitafino.de") == "kitafino_parent"
    assert diagnostic._domain_category("private.example") == "other"


def test_cookie_summary_exposes_neither_names_nor_values() -> None:
    cookies = SimpleCookie()
    cookies["PHPSESSID"] = "REAL_SESSION_VALUE"
    cookies["PHPSESSID"]["domain"] = ".kitafino.de"
    cookies["private-account-cookie"] = "PRIVATE_ACCOUNT_VALUE"

    result = diagnostic._cookie_summary(cookies.values())
    rendered = repr(result)

    assert result == {
        "count": 2,
        "php_session_present": True,
        "php_session_domain_categories": ["kitafino_parent"],
    }
    assert "REAL_SESSION_VALUE" not in rendered
    assert "PRIVATE_ACCOUNT_VALUE" not in rendered
    assert "private-account-cookie" not in rendered

    eligible = diagnostic._eligible_cookie_summary(cookies.values())
    assert eligible == {"count": 2, "php_session_present": True}
    assert "domain" not in repr(eligible)


def test_redirect_summary_exposes_no_path_query_or_location() -> None:
    response = SimpleNamespace(
        status=302,
        url=URL("https://auth.kitafino.de/private?account=secret"),
        headers={"Location": "https://user.kitafino.de/household?id=secret"},
    )

    result = diagnostic._redirects([response])

    assert result == [{"status": 302, "destination_host": "user"}]
    assert "secret" not in repr(result)


def test_login_marker_source_is_classified_without_content() -> None:
    assert (
        diagnostic._login_marker_source(
            "https://auth.kitafino.de/sys_k2/index.php?action=login",
            '<input name="passwort">PRIVATE PAGE CONTENT',
        )
        == "url_and_password_marker"
    )
    assert diagnostic._login_marker_source("https://user.kitafino.de/", "meal") == "none"


def test_main_reports_missing_environment_without_values(monkeypatch, capsys) -> None:
    monkeypatch.setenv("KITAFINO_USERNAME", "PRIVATE_USERNAME")
    monkeypatch.delenv("KITAFINO_PASSWORD", raising=False)

    assert diagnostic.main() == 2
    output = capsys.readouterr().out

    assert "missing_credentials" in output
    assert "PRIVATE_USERNAME" not in output
