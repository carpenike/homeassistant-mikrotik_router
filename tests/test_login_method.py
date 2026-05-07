"""Tests for the librouteros 4.x login_method translation in MikrotikAPI.connect.

The librouteros library went through a breaking API change between 3.x
and 4.x:

  * 3.x accepted ``login_methods=['plain']`` (plural kwarg, list of strings)
  * 4.x requires ``login_method=plain`` (singular kwarg, callable)

Existing config entries on this integration store the legacy string
``"plain"``. ``MikrotikAPI.connect`` translates that string to the
matching callable at runtime so old saved configs continue to work
against new librouteros versions.

These tests exercise that translation end-to-end by mocking
``librouteros.connect`` and inspecting the kwargs it receives.
"""

from unittest.mock import MagicMock, patch

import librouteros
import pytest
from librouteros.login import plain, token

from mikrotik_router.mikrotikapi import MikrotikAPI


@pytest.fixture
def fake_connect():
    """Patch ``librouteros.connect`` and return the mock."""
    with patch.object(librouteros, "connect") as mock:
        mock.return_value = MagicMock(name="fake_connection")
        yield mock


def _new_api(login_method) -> MikrotikAPI:
    return MikrotikAPI(
        host="127.0.0.1",
        username="u",
        password="p",
        port=8728,
        use_ssl=False,
        login_method=login_method,
    )


def test_legacy_string_plain_translates_to_callable(fake_connect: MagicMock) -> None:
    api = _new_api("plain")
    assert api.connect() is True
    kwargs = fake_connect.call_args.kwargs
    assert "login_method" in kwargs, "must use singular kwarg for librouteros 4.x"
    assert "login_methods" not in kwargs, "plural kwarg is the broken legacy form"
    assert kwargs["login_method"] is plain


def test_legacy_string_token_translates_to_callable(fake_connect: MagicMock) -> None:
    api = _new_api("token")
    assert api.connect() is True
    assert fake_connect.call_args.kwargs["login_method"] is token


def test_unknown_string_falls_back_to_plain(fake_connect: MagicMock, caplog) -> None:
    api = _new_api("nonsense")
    assert api.connect() is True
    assert fake_connect.call_args.kwargs["login_method"] is plain
    assert any(
        "unknown login method" in rec.getMessage().lower() for rec in caplog.records
    ), "unknown login methods must log a warning"


def test_callable_passes_through_unchanged(fake_connect: MagicMock) -> None:
    """If config already supplies a callable (new code path), respect it."""
    api = _new_api(plain)
    assert api.connect() is True
    assert fake_connect.call_args.kwargs["login_method"] is plain
